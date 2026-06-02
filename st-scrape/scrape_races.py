import argparse
import json  # Added json import
import os  # Added for path manipulation (extracting nationality)
import sys
import time  # Added for retry backoff / politeness delay
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlparse  # Added for URL parsing

import requests
from bs4 import BeautifulSoup

# Removed unused get_id_from_url helper function

# Output locations, resolved relative to this script so they are independent of
# the current working directory: data files go in db/, scrape logs in logs/.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(SCRIPT_DIR, 'db')
LOG_DIR = os.path.join(SCRIPT_DIR, 'logs')

# Shared browser-like request headers.
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
}

# The site is served by LiteSpeed, which throttles bursts of requests by
# returning HTTP 415 (and occasionally 429/5xx). These are transient and worth
# retrying with exponential backoff; a short pause between successful requests
# keeps us under the throttle threshold in the first place.
RETRY_STATUS = {415, 429, 500, 502, 503, 504}
MAX_RETRIES = 5
REQUEST_DELAY = 0.25  # seconds to wait after each successful request

# Reuse a single connection (HTTP keep-alive) across all requests to the same
# host. This amortises the TCP/TLS handshake over thousands of requests and
# carries cookies forward like a real browser session. Sequential use only; a
# concurrent scraper should use one Session per worker thread.
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


class _Tee:
    """Fan writes out to several streams, so console output is also captured to
    a log file. Used to mirror stdout/stderr into logs/<meet>_scrape.log."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def fetch(url, timeout=30):
    """
    GET a URL with a browser User-Agent, transparently retrying transient
    throttling (415/429) and 5xx responses with exponential backoff.

    Returns a requests.Response with UTF-8 encoding set. Raises the underlying
    requests exception (e.g. HTTPError for a genuine 404, or the last network
    error) once retries are exhausted, so callers can handle real failures.
    """
    backoff = 1.0
    last_exc = None
    response = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = SESSION.get(url, timeout=timeout)
            if response.status_code in RETRY_STATUS:
                print(f"    Throttled ({response.status_code}) on {url} "
                      f"[attempt {attempt}/{MAX_RETRIES}], backing off {backoff:.1f}s", file=sys.stderr)
                time.sleep(backoff)
                backoff *= 2
                continue
            response.raise_for_status()  # genuine 4xx (e.g. 404) -> raise, no retry
            response.encoding = 'utf-8'
            time.sleep(REQUEST_DELAY)    # politeness pause between requests
            return response
        except requests.exceptions.HTTPError:
            raise  # non-retryable HTTP status (already filtered RETRY_STATUS)
        except requests.exceptions.RequestException as e:
            last_exc = e  # network error / timeout -> retry with backoff
            print(f"    Request error on {url} [attempt {attempt}/{MAX_RETRIES}]: {e}", file=sys.stderr)
            time.sleep(backoff)
            backoff *= 2

    if last_exc is not None:
        raise last_exc
    raise requests.HTTPError(
        f"Giving up on {url} after {MAX_RETRIES} attempts "
        f"(last status {response.status_code if response is not None else 'unknown'})")

# Danish month names -> month number. Used to parse dates like "5. april 2025"
# without depending on the process locale being set to da_DK (datetime.strptime
# with '%B' only understands the active locale, which is typically C/en_US and
# would make every date parse fail).
DANISH_MONTHS = {
    'januar': 1, 'februar': 2, 'marts': 3, 'april': 4, 'maj': 5, 'juni': 6,
    'juli': 7, 'august': 8, 'september': 9, 'oktober': 10, 'november': 11,
    'december': 12,
}


def parse_danish_date(date_text):
    """
    Parse a Danish-formatted date string such as "5. april 2025" into a
    datetime, independent of the process locale.

    Raises ValueError if the text does not match the expected 'day. month year'
    shape or the month name is not recognised.
    """
    # "05. april 2025" -> ["05", "april", "2025"]
    tokens = date_text.replace('.', '').split()
    if len(tokens) != 3:
        raise ValueError(f"Unexpected date format: {date_text!r}")
    day_str, month_name, year_str = tokens
    month = DANISH_MONTHS.get(month_name.lower())
    if month is None:
        raise ValueError(f"Unknown Danish month name: {month_name!r}")
    return datetime(int(year_str), month, int(day_str))


def time_to_centiseconds(time_str):
    """
    Convert a swim time string into integer hundredths of a second, the exact
    integer form best suited for numeric comparison and aggregation.

    Handles the "M:SS.hh" form (e.g. "1:02.48" -> 6248) and the sub-minute
    "SS.hh" form (e.g. "58.21" -> 5821), tolerating a comma or dot as the
    decimal separator. A missing or short fractional part is padded to
    hundredths ("58.2" -> 5820); a longer one is truncated.

    Returns None for blank values or anything that is not a parseable time
    (e.g. "DSQ", "DNS", "-"), so the caller can store it as a NULL.
    """
    if not time_str:
        return None
    text = time_str.strip().replace(',', '.')
    if not text:
        return None

    # Optional minutes component before the (last) colon, e.g. "1:02.48".
    minutes = 0
    seconds_part = text
    if ':' in text:
        minutes_str, seconds_part = text.rsplit(':', 1)
        try:
            minutes = int(minutes_str)
        except ValueError:
            return None  # Unexpected shape (e.g. extra colon) -> not a time

    # seconds_part is now "SS.hh", "SS.h" or "SS".
    if '.' in seconds_part:
        secs_str, frac_str = seconds_part.split('.', 1)
    else:
        secs_str, frac_str = seconds_part, ''
    # Normalise the fraction to exactly two digits (hundredths).
    frac_str = (frac_str + '00')[:2]

    try:
        seconds = int(secs_str)
        hundredths = int(frac_str)
    except ValueError:
        return None

    return (minutes * 60 + seconds) * 100 + hundredths

def scrape_meet_info(html_content, meet_category): # Added meet_category argument
    """
    Parses the HTML content of a swim meet page and extracts meet details.

    Args:
        html_content: A string containing the HTML source of the page.
        meet_category: List of category codes for the meet (a combined meet can
            carry several, e.g. ['DM-L', 'DMJ-L']). Stored verbatim under 'category'.

    Returns:
        A dictionary containing 'meet', 'venue', 'course', 'category', 'date', and 'season'.
        Returns None for values if not found.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    # Renamed keys and initialized dictionary
    meet_info = {'meet': None, 'venue': None, 'course': None, 'category': meet_category, 'date': None, 'season': None}

    # --- Find meet name ---
    meet_name_tag = soup.find('h3', class_='k-content__head-title')
    if meet_name_tag:
        meet_info['meet'] = meet_name_tag.get_text(strip=True) # Renamed key
    else:
        print("Warning: Could not find meet name tag.", file=sys.stderr)

    # Find venue
    placering_heading = soup.find('h3', class_='k-portlet__head-title', string=lambda t: t and 'Placering' in t)
    if placering_heading:
        portlet_head = placering_heading.find_parent('div', class_='k-portlet__head')
        if portlet_head:
            portlet_body = portlet_head.find_next_sibling('div', class_='k-portlet__body')
            if portlet_body:
                venue_p_tag = portlet_body.find('p') # Find the first <p> tag within the body
                if venue_p_tag:
                    venue_strong_tag = venue_p_tag.find('strong') # Find the <strong> tag within the <p>
                    if venue_strong_tag:
                        meet_info['venue'] = venue_strong_tag.get_text(strip=True)
                    else:
                        print("Warning: Could not find strong tag for venue name inside paragraph.", file=sys.stderr)
                else:
                    print("Warning: Could not find venue paragraph tag inside Placering portlet body.", file=sys.stderr)
            else:
                print("Warning: Could not find portlet body for Placering.", file=sys.stderr)
        else:
            print("Warning: Could not find parent portlet head for Placering heading.", file=sys.stderr)
    else:
        print("Warning: Could not find 'Placering' heading.", file=sys.stderr)


    # --- Locate the "Information om stævnet" portlet body once ---
    # Both the course type and the start date live in this same section, so we
    # resolve its body a single time and guard it. This avoids referencing an
    # unbound or stale 'portlet_body' if any part of the lookup fails.
    info_heading = soup.find('h3', class_='k-portlet__head-title', string=lambda t: t and 'Information om stævnet' in t)
    info_body = None
    if info_heading:
        portlet_head = info_heading.find_parent('div', class_='k-portlet__head')
        if portlet_head:
            info_body = portlet_head.find_next_sibling('div', class_='k-portlet__body')

    if info_body is None:
        print("Warning: Could not find 'Information om stævnet' section body. "
              "Course and date will be left unset.", file=sys.stderr)
    else:
        # --- Find Course Type ---
        # Look for the <strong> tag following 'Bassin:'
        bassin_label = info_body.find(string=lambda text: text and 'Bassin:' in text)
        if bassin_label:
            bassin_strong_tag = bassin_label.find_next('strong')
            if bassin_strong_tag:
                bassin = bassin_strong_tag.get_text(strip=True)
                # Course type is determined by the presence of '25m' or '50m' and UNKNOWN if neither is found
                if '50m' in bassin:
                    meet_info['course'] = 'LCM' # Renamed key
                elif '25m' in bassin:
                    meet_info['course'] = 'SCM' # Renamed key
                else:
                    meet_info['course'] = 'UNK' # Renamed key
                    print("Warning: Course type could not be determined from 'Bassin:' value.", file=sys.stderr)
            else:
                print("Warning: Could not find <strong> tag for 'Bassin:' value.", file=sys.stderr)
        else:
            print("Warning: Could not find 'Bassin:' text in the Information section body.", file=sys.stderr)

        # --- Find Start Date (same body, now guaranteed bound) ---
        start_date_label = info_body.find(string=lambda text: text and 'Stævnestart' in text)
        if start_date_label:
            start_date_strong_tag = start_date_label.find_next('strong')
            if start_date_strong_tag:
                # Extract the date text and reformat it
                date_text = start_date_strong_tag.get_text(strip=True)
                try:
                    # Parse the Danish date format (locale-independent)
                    parsed_date = parse_danish_date(date_text)
                    meet_info['date'] = parsed_date.strftime('%d-%m-%Y') # Renamed key

                    # Calculate season based on month
                    start_month = parsed_date.month
                    start_year = parsed_date.year
                    if 1 <= start_month <= 7:
                        meet_info['season'] = start_year
                    else: # Months 8-12
                        meet_info['season'] = start_year + 1

                except ValueError:
                    print(f"Warning: Could not parse date '{date_text}' into the format 'dd-MM-yyyy'. Season calculation skipped.", file=sys.stderr)
                    meet_info['date'] = date_text  # Fallback to the original text, Renamed key
                    meet_info['season'] = None # Ensure season is None if date parsing fails
            else:
                print("Warning: Could not find <strong> tag for 'Stævnestart' value.", file=sys.stderr)
        else:
            print("Warning: Could not find 'Stævnestart' text in the Information section body.", file=sys.stderr)

    return meet_info


def scrape_race_list(html_content, meet_id): # Added meet_id parameter
    """
    Parses the HTML content of a swim meet page and extracts race details.

    Args:
        html_content: A string containing the HTML source of the page.

    Returns:
        A list of dictionaries, where each dictionary represents a race
        and contains 'meet_id', 'race_id', 'number', 'name', 'distance', 'stroke', 'gender',
        'type', and 'link'. 'race_id' is the ID extracted from the URL.
        (Session and results_count information are no longer included).
        The 'link' is used internally but excluded from the final races JSONL output.
        Returns an empty list if the table is not found or parsing fails.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    races = []

    # Find the heading "Resultater"
    resultater_heading = soup.find('h3', id='resultater')
    if not resultater_heading:
        print("Error: Could not find the 'Resultater' heading.", file=sys.stderr)
        return races

    # Find the table immediately following the heading's parent div structure
    portlet_head = resultater_heading.find_parent('div', class_='k-portlet__head')
    if not portlet_head:
        print("Error: Could not find parent portlet head.", file=sys.stderr)
        return races

    portlet_body = portlet_head.find_next_sibling('div', class_='k-portlet__body')
    if not portlet_body:
        print("Error: Could not find portlet body.", file=sys.stderr)
        return races

    results_table = portlet_body.find('table', class_='table')
    if not results_table:
        print("Error: Could not find the results table.", file=sys.stderr)
        return races

    rows = results_table.find_all('tr')

    for row in rows:
        cells = row.find_all('td')

        # Process race data rows
        if len(cells) == 4:
            try:
                race_number = cells[0].get_text(strip=True)
                race_link_tag = cells[1].find('a')
                race_name = race_link_tag.get_text(strip=True) if race_link_tag else "N/A"
                race_href = race_link_tag['href'] if race_link_tag and race_link_tag.has_attr('href') else "N/A"
                # Prepend base URL if the link is relative
                if race_href.startswith('/'):
                    race_href = f"https://xn--svmmetider-1cb.dk{race_href}"

                original_race_type = cells[2].get_text(strip=True)
                # Map the site's Danish race-type label to our English output value.
                race_type_lower = original_race_type.lower()
                if 'finale' in race_type_lower:
                    mapped_race_type = 'Final'
                elif race_type_lower.startswith('swim-off'):
                    mapped_race_type = 'Swim-off'
                elif 'indledende' in race_type_lower:
                    mapped_race_type = 'Heats'
                else:
                    mapped_race_type = original_race_type # Keep original if no match

                # Extract race ID from URL
                parsed_url = urlparse(race_href)
                query_params = parse_qs(parsed_url.query)
                # Extract only the race ID from the URL query parameters and convert to int
                extracted_race_id_str = query_params.get('id', [None])[0]
                extracted_race_id = None
                if extracted_race_id_str:
                    try:
                        extracted_race_id = int(extracted_race_id_str)
                    except ValueError:
                        print(f"    Warning: Could not convert extracted race_id '{extracted_race_id_str}' to int.", file=sys.stderr)


                # Parse race_name for distance, stroke, gender, relay_count.
                # Individual events look like "100 Fri - Herrer"; relays look
                # like "4 x 100 Fri - Damer" (legs x leg-distance stroke).
                # relay_count defaults to 1 for individual events.
                distance, stroke, gender, relay_count = None, None, None, 1
                if race_name and ' - ' in race_name:
                    parts = race_name.split(' - ')
                    if len(parts) == 2:
                        event_part = parts[0]
                        gender_part = parts[1]

                        # Extract gender (relays may be mixed -> 'X')
                        if gender_part == 'Damer':
                            gender = 'F'
                        elif gender_part == 'Herrer':
                            gender = 'M'
                        elif gender_part == 'Mix':
                            gender = 'X'

                        event_tokens = event_part.split()
                        if len(event_tokens) >= 4 and event_tokens[1].lower() == 'x':
                            # Relay: "<legs> x <leg-distance> <stroke...>"
                            try:
                                relay_count = int(event_tokens[0])
                            except ValueError:
                                print(f"    Warning: Could not convert relay leg count '{event_tokens[0]}' to int for race '{race_name}'.", file=sys.stderr)
                            leg_distance_cleaned = event_tokens[2].replace('.', '') # strip thousand separators
                            try:
                                distance = int(leg_distance_cleaned) # per-leg distance, e.g. 100 for 4x100
                            except ValueError:
                                print(f"    Warning: Could not convert relay leg distance '{leg_distance_cleaned}' to int for race '{race_name}'.", file=sys.stderr)
                            stroke = ' '.join(event_tokens[3:])
                        else:
                            # Individual: "<distance> <stroke>"
                            event_parts = event_part.split(' ', 1) # Split only once
                            if len(event_parts) == 2:
                                distance_str = event_parts[0]
                                stroke = event_parts[1]
                                # Remove thousand separators before converting
                                distance_str_cleaned = distance_str.replace('.', '')
                                try:
                                    distance = int(distance_str_cleaned)
                                except ValueError:
                                    print(f"    Warning: Could not convert cleaned distance '{distance_str_cleaned}' (from '{distance_str}') to int for race '{race_name}'.", file=sys.stderr)
                                    distance = None # Set distance to None if conversion fails
                            else:
                                 print(f"Warning: Could not parse distance/stroke from '{event_part}' in race '{race_name}'", file=sys.stderr)
                    else:
                         print(f"Warning: Unexpected format for race_name '{race_name}' after splitting by ' - '", file=sys.stderr)
                elif race_name != "N/A":
                     print(f"Warning: Could not parse race_name '{race_name}' due to missing ' - ' separator", file=sys.stderr)


                # Convert race_number to int
                race_number_int = None
                try:
                    race_number_int = int(race_number)
                except ValueError:
                    print(f"    Warning: Could not convert race number '{race_number}' to int.", file=sys.stderr)

                # Classify the race: race numbers >= 100 are para races,
                # everything else is a regular ('open') race. If the number
                # could not be parsed we cannot tell, so default to 'open'.
                classification = 'para' if (race_number_int is not None and race_number_int >= 100) else 'open'

                races.append({
                    'meet_id': int(meet_id),      # Convert meet_id to int
                    'race_id': extracted_race_id, # Already int or None
                    'number': race_number_int,    # Use int version
                    'name': race_name,            # Keep original name
                    'distance': distance,         # Per-leg distance (int) or None
                    'stroke': stroke,     # Added stroke
                    'gender': gender,     # Added gender ('X' for mixed relays)
                    'relay_count': relay_count, # 1 for individual events, N for an N-leg relay
                    'type': mapped_race_type, # Use the mapped type
                    'class': classification, # 'para' (number >= 100) or 'open'
                    'link': race_href # Re-added link for result scraping
                })
            except Exception as e:
                print(f"Error processing row: {row}. Error: {e}", file=sys.stderr)

    return races


def meet_has_results(meet_id):
    """Return True if the meet page currently lists any races (results are
    published as races complete, so 'any races present' is our completeness
    signal). Returns False on any fetch/parse error so the dispatcher simply
    re-checks next hour rather than crashing the cycle."""
    url = f"https://xn--svmmetider-1cb.dk/staevne/?{meet_id}#resultater"
    try:
        response = fetch(url, timeout=30)
        races = scrape_race_list(response.text, meet_id)
        return bool(races)
    except Exception as e:  # network, parse, anything — treat as "not ready yet"
        print(f"meet_has_results({meet_id}) check failed: {e}", file=sys.stderr)
        return False


def scrape_split_times(split_url):
    """
    Scrape the per-length split times for a single result, as cumulative-distance
    laps. Works for both layouts the site uses:

      * Individual: 'Distance' | 'Split' | 'Samlet'
      * Relay:      'Svommer' | 'Argang' | 'Distance' | 'Split' | 'Tur' | 'Samlet' | 'Reaktionstid'

    Columns are located by header name, so for a relay this yields the team's
    cumulative per-50 splits (the 'Distance'/'Split'/'Samlet' columns); the
    per-member 'Svommer'/'Tur' columns are ignored under the team-result model.

    Args:
        split_url: Absolute URL of the split-times page.

    Returns:
        A list of dicts ordered by distance, each containing:
          'distance'               : int  – cumulative metres (50, 100, ...)
          'split_time'             : str  – length split as shown (e.g. '32.20')
          'split_centiseconds'     : int or None
          'cumulative_time'        : str  – total time as shown (e.g. '1:02.26')
          'cumulative_centiseconds': int or None
        Returns an empty list if the page has no split table (e.g. a single-
        length race) or on any fetch/parse error.
    """
    splits = []
    try:
        response = fetch(split_url, timeout=20)
        soup = BeautifulSoup(response.text, 'html.parser')

        table = soup.find('table', class_='table')
        if not table:
            return splits  # No splits available (e.g. single-length race)

        # Locate the Distance/Split/Samlet columns by header name so the same
        # logic handles the 3-column individual and 7-column relay tables.
        header_map = {th.get_text(strip=True).lower(): idx
                      for idx, th in enumerate(table.find_all('th'))}
        try:
            di, si, ci = header_map['distance'], header_map['split'], header_map['samlet']
        except KeyError:
            print(f"    Warning: Split table on {split_url} is missing expected "
                  f"Distance/Split/Samlet columns (headers: {list(header_map)}).", file=sys.stderr)
            return splits

        for row in table.find_all('tr'):
            cells = row.find_all('td')  # header uses <th>, so this skips it
            if len(cells) <= max(di, si, ci):
                continue
            distance_str = cells[di].get_text(strip=True)
            split_str = cells[si].get_text(strip=True)
            cumulative_str = cells[ci].get_text(strip=True)
            if not distance_str:
                continue  # skip any non-data rows lacking a distance

            try:
                distance_val = int(distance_str.replace('.', ''))  # strip thousand separators
            except ValueError:
                print(f"    Warning: Could not convert split distance '{distance_str}' to int.", file=sys.stderr)
                distance_val = None

            splits.append({
                'distance': distance_val,
                'split_time': split_str,
                'split_centiseconds': time_to_centiseconds(split_str),
                'cumulative_time': cumulative_str,
                'cumulative_centiseconds': time_to_centiseconds(cumulative_str),
            })
    except requests.exceptions.RequestException as e:
        print(f"    Error fetching split times {split_url}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"    An unexpected error occurred scraping split times from {split_url}: {e}", file=sys.stderr)

    return splits


def scrape_race_results(race_url, expected_race_type, race_id_for_results, is_relay=False): # Added race_id, relay flag
    """
    Scrapes the result rows from a specific race results page.

    For individual events each row is one swimmer; for relays each row is one
    team (team-result model). The two layouts share the same 6-cell structure,
    but differ in the per-row links: an individual's split-times link sits on the
    time cell, while a relay team's link sits on the team-name cell. We locate it
    by scanning for the 'splittider' href, so both cases work without special
    casing. For relays 'Swimmer_id' is left None (the name cell is a team).

    Args:
        race_url: The URL of the race results page.
        expected_race_type: The type of race expected ('Finale', 'Swim-off', or other like 'Indledende').
        race_id_for_results: The ID of the race these results belong to.
        is_relay: True if this race is a relay (suppresses swimmer-id extraction).

    Returns:
        A list of dictionaries, each representing a swimmer's or team's result
        with cleaned attributes, or an empty list on error.
    """
    results = []
    try:
        print(f"    Fetching results from: {race_url}")
        response = fetch(race_url, timeout=20) # Shorter timeout for individual races
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        # Relative split links must be resolved against the *final* URL: the
        # site redirects '/loeb?...' -> '/loeb/?...', and only the trailing-slash
        # form yields the correct '/loeb/splittider?...' path.
        results_page_url = response.url

        target_table = None
        # Find all result boxes
        result_boxes = soup.find_all('div', class_='box')
        if not result_boxes:
            print(f"    Warning: No result boxes found on page {race_url}", file=sys.stderr)
            return results

        # The page's box headers are in Danish, so translate our (English)
        # expected type back to the Danish keyword used to locate the table.
        type_lower = expected_race_type.lower()
        if type_lower in ('final', 'finale'):
            search_keyword = 'finale'
        elif type_lower.startswith('swim-off'):
            search_keyword = 'swim-off'
        else:
            search_keyword = 'indledende' # 'Heats'/preliminary is the default

        # Find the correct table based on the expected type in the header
        for box in result_boxes:
            header = box.find('div', class_='box-header')
            if header:
                h2 = header.find('h2')
                if h2 and search_keyword in h2.get_text(strip=True).lower():
                    body = box.find('div', class_='box-body')
                    if body:
                        target_table = body.find('table', class_='table')
                        if target_table:
                            print(f"    Found matching table for '{expected_race_type}'")
                            break # Found the table for the expected type

        # Fallback: If specific type not found, try finding 'Indledende' or use the first table
        if not target_table:
             print(f"    Warning: Could not find specific table for '{expected_race_type}'. Trying fallback.", file=sys.stderr)
             # Try finding 'Indledende' specifically if we didn't search for it initially
             if search_keyword != 'indledende':
                 for box in result_boxes:
                     header = box.find('div', class_='box-header')
                     if header:
                         h2 = header.find('h2')
                         if h2 and 'indledende' in h2.get_text(strip=True).lower():
                             body = box.find('div', class_='box-body')
                             if body:
                                 target_table = body.find('table', class_='table')
                                 if target_table:
                                     print("    Found fallback table for 'Indledende'")
                                     break
             # If still no table, use the first one found in any box
             if not target_table and result_boxes:
                 first_body = result_boxes[0].find('div', class_='box-body')
                 if first_body:
                     target_table = first_body.find('table', class_='table')
                     if target_table:
                         print("    Using first available results table as fallback.")


        if not target_table:
            print(f"    Error: Could not find any results table on page {race_url}", file=sys.stderr)
            return results

        # Extract data from the chosen table
        tbody = target_table.find('tbody')
        if not tbody:
             print(f"    Warning: Found table but no tbody on page {race_url}", file=sys.stderr)
             return results

        rows = tbody.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) == 6: # Rank, Name, Year, Club/Flag, Time, Reaction
                try:
                    # Convert Rank to int
                    rank_str = cells[0].get_text(strip=True)
                    rank_val = None
                    try:
                        rank_val = int(rank_str)
                    except ValueError:
                        if rank_str.upper() == 'DSQ':
                            rank_val = -1 # Assign -1 for DSQ
                            print(f"    Info: Rank '{rank_str}' mapped to -1.", file=sys.stderr)
                        else:
                            # Keep None if it's not DSQ and not an integer
                            print(f"    Warning: Could not convert non-DSQ rank '{rank_str}' to int. Storing as None.", file=sys.stderr)
                            rank_val = None

                    name_tag = cells[1].find('a')
                    name_val = name_tag.get_text(strip=True) if name_tag else cells[1].get_text(strip=True)
                    # Swimmer ID extraction - individual events only. For relays
                    # the name cell holds the team, and its link is the split-times
                    # page (not a swimmer profile), so there is no swimmer id.
                    swimmer_id_val = None
                    if not is_relay:
                        swimmer_id_href = name_tag['href'] if name_tag and name_tag.has_attr('href') else None
                        if swimmer_id_href and '?' in swimmer_id_href:
                            try:
                                swimmer_id_val = swimmer_id_href.split('?')[-1]
                            except IndexError:
                                print(f"    Warning: Could not split swimmer href '{swimmer_id_href}' to get ID.", file=sys.stderr)
                        elif swimmer_id_href:
                             print(f"    Warning: Swimmer href '{swimmer_id_href}' does not contain '?' for ID extraction.", file=sys.stderr)

                    # Convert Birth Year to int
                    birth_year_str = cells[2].get_text(strip=True)
                    birth_year_val = None
                    try:
                        birth_year_val = int(birth_year_str)
                    except ValueError:
                        print(f"    Warning: Could not convert birth year '{birth_year_str}' to int.", file=sys.stderr)


                    # Nationality and Club extraction
                    club_cell = cells[3]
                    flag_img = club_cell.find('img')
                    nationality_val = None
                    club_val = None
                    if flag_img and flag_img.has_attr('src'):
                        img_src = flag_img['src']
                        # Extract filename, remove extension for nationality
                        filename = os.path.basename(img_src)
                        nationality_val = os.path.splitext(filename)[0]
                        # Get text after the image tag for club
                        club_text_node = flag_img.next_sibling
                        if club_text_node and isinstance(club_text_node, str):
                             club_val = club_text_node.strip()
                        else: # Fallback if text isn't immediately after img
                             club_val = club_cell.get_text(strip=True) # Might include flag text if logic fails
                             print(f"    Warning: Could not find club text directly after flag for {name_val}. Using full cell text.", file=sys.stderr)

                    else: # No flag image found
                        nationality_val = 'UNK' # Or None, depending on preference
                        club_val = club_cell.get_text(strip=True)
                        print(f"    Warning: No flag image found for {name_val}. Setting nationality to {nationality_val}.", file=sys.stderr)


                    time_tag = cells[4].find('a')
                    completed_time_val = time_tag.get_text(strip=True) if time_tag else cells[4].get_text(strip=True)
                    # The split-times page is linked from the time cell (individual)
                    # or the team-name cell (relay); locate it by its 'splittider'
                    # href so both layouts work, then scrape the laps.
                    split_times = []
                    split_anchor = next(
                        (a for c in cells
                         for a in [c.find('a')]
                         if a and a.has_attr('href') and 'splittider' in a['href']),
                        None)
                    if split_anchor:
                        split_url = urljoin(results_page_url, split_anchor['href'])
                        split_times = scrape_split_times(split_url)
                    # reaction_time_val = cells[5].get_text(strip=True) # No longer needed

                    # Convert race_id_for_results to int (should already be int/None from race list)
                    race_id_int = None
                    if race_id_for_results is not None:
                        try:
                            race_id_int = int(race_id_for_results)
                        except ValueError:
                             print(f"    Warning: Could not convert race_id_for_results '{race_id_for_results}' to int.", file=sys.stderr)


                    results.append({
                        'race_id': race_id_int, # Use int version
                        'Rank': rank_val,       # Now int (-1 for DSQ) or None
                        'Name': name_val,
                        'Swimmer_id': swimmer_id_val, # String ID is fine
                        'nationality': nationality_val.upper(),
                        'club': club_val,
                        'birth_year': birth_year_val, # Already int or None
                        'completed_time': completed_time_val, # Original string, e.g. "1:02.48"
                        'completed_centiseconds': time_to_centiseconds(completed_time_val), # Int hundredths, or None
                        'splits': split_times # Per-lap split times (empty for single-length races)
                    })
                except Exception as e:
                    print(f"    Error processing result row: {row}. Error: {e}", file=sys.stderr)

    except requests.exceptions.RequestException as e:
        print(f"    Error fetching results URL {race_url}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"    An unexpected error occurred scraping results from {race_url}: {e}", file=sys.stderr)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape race details from a swim meet page.")
    parser.add_argument("meet_id", help="The ID of the swim meet to scrape.")
    parser.add_argument("meet_category", nargs='+',
                        help="One or more categories for the meet. A combined meet can carry several, "
                             "e.g. 'DM-L DMJ-L' or 'DM-L,DMJ-L'.") # Added argument (now multi-valued)
    args = parser.parse_args()

    meet_id = args.meet_id
    # Categories may be given space-separated and/or comma-separated; normalise
    # both into a clean list, e.g. ['DM-L', 'DMJ-L'].
    meet_category = [c.strip() for token in args.meet_category for c in token.split(',') if c.strip()]
    url = f"https://xn--svmmetider-1cb.dk/staevne/?{meet_id}#resultater"

    # Ensure output dirs exist and mirror all console output into a per-meet log.
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = open(os.path.join(LOG_DIR, f"{meet_id}_scrape.log"),
                    'w', encoding='utf-8', buffering=1)  # line-buffered for live tailing
    sys.stdout = _Tee(sys.__stdout__, log_file)
    sys.stderr = _Tee(sys.__stderr__, log_file)

    try:
        print(f"Fetching data from: {url}")
        response = fetch(url, timeout=30) # Retries transient throttling/5xx
        html = response.text

        # --- Scrape Meet Info ---
        # Pass meet_category to the function
        meet_details = scrape_meet_info(html, meet_category)
        if meet_details:
            print("\n--- Meet Information ---")
            # Updated print statements with new keys
            print(f"Meet: {meet_details.get('meet', 'Not Found')}")
            print(f"Venue: {meet_details.get('venue', 'Not Found')}")
            print(f"Course: {meet_details.get('course', 'Not Found')}")
            print(f"Date: {meet_details.get('date', 'Not Found')}")
            print(f"Category: {', '.join(meet_details.get('category') or []) or 'Not Found'}")
            print(f"Season: {meet_details.get('season', 'Not Found')}")
            print("-" * 25)

            # --- Write Meet Info to JSONL ---
            # Single-record JSONL, matching the *_races.jsonl / *_results.jsonl
            # convention and the downstream consumers that expect .jsonl.
            json_filename = os.path.join(DB_DIR, f"{meet_id}_meet_info.jsonl")
            # Prepare data for JSON in the specified order
            json_output_data = {
                'meet_id': int(meet_id),
                'meet': meet_details.get('meet'),
                'category': meet_details.get('category'),
                'venue': meet_details.get('venue'),
                'course': meet_details.get('course'),
                'date': meet_details.get('date'),
                'season': meet_details.get('season')
            }

            try:
                with open(json_filename, 'w', encoding='utf-8') as f:
                    # Dump the combined dictionary as one JSONL record
                    json.dump(json_output_data, f, ensure_ascii=False, separators=(',', ':'))
                    f.write('\n')
                print(f"Meet information saved to {json_filename}")
            except IOError as e:
                print(f"Error writing meet info to JSON file {json_filename}: {e}", file=sys.stderr)
            except Exception as e:
                 print(f"An unexpected error occurred while writing JSON: {e}", file=sys.stderr)

        else:
            print("Could not extract meet information.")

        # --- Scrape Race List ---
        extracted_races = scrape_race_list(html, meet_id) # Pass meet_id

        # --- Scrape Results for Each Race ---
        if extracted_races:
            print(f"\n--- Scraping Results for {len(extracted_races)} Races ---")
            for i, race in enumerate(extracted_races):
                race_id = race.get('race_id', 'N/A') # Get the race_id for this race
                print(f"  Scraping results for Race {i+1}/{len(extracted_races)} (ID: {race_id})...")
                if race.get('link') and race['link'] != "N/A":
                     # Pass race_id and relay flag to the scraping function
                    is_relay = race.get('relay_count', 1) > 1
                    race_results = scrape_race_results(race['link'], race['type'], race_id, is_relay)
                    race['results'] = race_results # Add results to the race dictionary
                else:
                    print(f"    Skipping results for race {race_id} due to missing link.")
                    race['results'] = [] # Ensure results key exists even if empty

            # --- Write Individual Results to JSONL ---
            results_jsonl_filename = os.path.join(DB_DIR, f"{meet_id}_results.jsonl")
            all_results = []
            for race in extracted_races:
                if race.get('results'):
                    all_results.extend(race['results']) # Collect all results

            if all_results:
                try:
                    with open(results_jsonl_filename, 'w', encoding='utf-8') as f:
                        for result in all_results:
                            # Write each individual result as a JSON line
                            json.dump(result, f, ensure_ascii=False)
                            f.write('\n')
                    print(f"\nIndividual results saved to {results_jsonl_filename}")
                except IOError as e:
                    print(f"Error writing results to JSONL file {results_jsonl_filename}: {e}", file=sys.stderr)
                except Exception as e:
                     print(f"An unexpected error occurred while writing results JSONL: {e}", file=sys.stderr)
            else:
                print("\nNo individual results found to write to results file.")


            # --- Write Races (WITHOUT results) to JSONL ---
            races_jsonl_filename = os.path.join(DB_DIR, f"{meet_id}_races.jsonl")
            try:
                with open(races_jsonl_filename, 'w', encoding='utf-8') as f:
                    for race in extracted_races:
                        # Create a copy and remove results and link before writing
                        race_metadata = race.copy()
                        race_metadata.pop('results', None) # Remove results key if it exists
                        race_metadata.pop('link', None)    # Remove link key if it exists
                        json.dump(race_metadata, f, ensure_ascii=False)
                        f.write('\n')
                print(f"Race metadata (excluding results and link) saved to {races_jsonl_filename}")
            except IOError as e:
                print(f"Error writing race metadata to JSONL file {races_jsonl_filename}: {e}", file=sys.stderr)
            except Exception as e:
                 print(f"An unexpected error occurred while writing JSONL: {e}", file=sys.stderr)

            # --- Print Races Info to Console (Results printing removed) ---
            print("\n--- Race Details ---")
            for race in extracted_races:
                print("\nRace Info:") # Keep printing race info
                print(f"  Meet ID: {race.get('meet_id', 'N/A')}")
                print(f"  Race ID: {race.get('race_id', 'N/A')}")
                # print(f"  Session: {race.get('session', 'N/A')}") # Removed session output
                print(f"  Race Number: {race.get('number', 'N/A')}")
                print(f"  Name: {race.get('name', 'N/A')}")
                print(f"  Distance: {race.get('distance', 'N/A')}") # Added distance output
                print(f"  Stroke: {race.get('stroke', 'N/A')}")     # Added stroke output
                print(f"  Gender: {race.get('gender', 'N/A')}")
                print(f"  Relay Count: {race.get('relay_count', 'N/A')}")
                print(f"  Type: {race.get('type', 'N/A')}")
                print(f"  Class: {race.get('class', 'N/A')}")
                # Link is still not printed to console, only used internally
                # Individual result printing removed from console output
                print("-" * 20) # Separator after each race info block
        else:
            print("No races found or error during parsing.")

    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
