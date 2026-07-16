"""Results-row parsing, incl. the DSQ layout.

Ground truth (svømmetider.dk, 2016 & 2026 alike): a normal result row has 6
cells [#, Navn, Årgang, Klub, Tid, Reaktionstid]; a disqualified swim has *7*
cells with the rank cell rendered as '-' and the DSQ marker in the *time* cell:
['-', name, year, club, 'DSQ', reaction, '']. The old `len(cells) == 6` guard
dropped every DSQ silently. These pin: DSQ rows are captured as rank -1 with no
time, and normal rows are unaffected.
"""
from bs4 import BeautifulSoup

import scrape_races


def _tbody(html):
    return BeautifulSoup(f"<table><tbody>{html}</tbody></table>",
                         "html.parser").find("tbody")


NORMAL = (
    '<tr><td>1</td><td><a href="/svommer/?26884">Foo Bar</a></td>'
    '<td>1996</td><td><img src="/flags/DEN.png"/>Some Club</td>'
    '<td>25.30</td><td>+62</td></tr>'
)
DSQ = (
    '<tr><td>-</td><td><a href="/svommer/?999">Dsq Guy</a></td>'
    '<td>2005</td><td><img src="/flags/DEN.png"/>Club X</td>'
    '<td>DSQ</td><td>+189</td><td></td></tr>'
)


def _parse(html):
    return scrape_races.parse_results_table(
        _tbody(html), is_relay=False, race_id_for_results=42,
        results_page_url="https://example.test/loeb/?id=42")


def test_normal_row_parsed():
    rows = _parse(NORMAL)
    assert len(rows) == 1
    r = rows[0]
    assert r["Rank"] == 1
    assert r["Name"] == "Foo Bar"
    assert r["Swimmer_id"] == "26884"
    assert r["completed_centiseconds"] == 2530
    assert r["birth_year"] == 1996


def test_dsq_row_is_captured_as_rank_minus_one():
    rows = _parse(NORMAL + DSQ)
    assert len(rows) == 2, "DSQ (7-column) row must not be dropped"
    dsq = rows[1]
    assert dsq["Rank"] == -1
    assert dsq["Name"] == "Dsq Guy"
    assert dsq["Swimmer_id"] == "999"
    assert dsq["completed_centiseconds"] is None
    assert dsq["completed_time"] == "DSQ"


def test_short_rows_are_skipped():
    # A section/placeholder row with too few cells is not a result.
    rows = _parse('<tr><td colspan="6">Ingen resultater</td></tr>')
    assert rows == []
