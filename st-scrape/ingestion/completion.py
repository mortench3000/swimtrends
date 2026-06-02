"""Pure completion-window logic for the dispatcher.

A meet is scraped after end_date 23:59 (local) + grace_hours, and force-scraped
once past end_date 23:59 + deadline_hours even if the page never showed results.
All functions take `now` explicitly so callers/tests control the clock.
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_GRACE_HOURS = 6
DEFAULT_DEADLINE_HOURS = 72
DEFAULT_TZ = "Europe/Copenhagen"

# Decisions returned by decide().
SKIP = "skip"          # too early — do nothing
CHECK = "check"        # in window — verify the page actually has results
DEADLINE = "deadline"  # past deadline — dispatch regardless (force fallback)


def windows(end_date, grace_hours, deadline_hours, tz=DEFAULT_TZ):
    """Return (scrape_after, deadline) as tz-aware datetimes.

    end_date is 'YYYY-MM-DD'. The anchor is 23:59 on that date in `tz`.
    """
    zone = ZoneInfo(tz)
    day = datetime.strptime(end_date, "%Y-%m-%d").date()
    anchor = datetime.combine(day, time(23, 59), tzinfo=zone)
    return anchor + timedelta(hours=grace_hours), anchor + timedelta(hours=deadline_hours)


def decide(now, end_date, grace_hours, deadline_hours, tz=DEFAULT_TZ):
    """Classify `now` against the meet's scrape/deadline windows."""
    scrape_after, deadline = windows(end_date, grace_hours, deadline_hours, tz)
    if now < scrape_after:
        return SKIP
    if now < deadline:
        return CHECK
    return DEADLINE
