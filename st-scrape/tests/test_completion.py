"""Time-gate decision logic. now is always injected, so tests are deterministic."""
from datetime import datetime
from zoneinfo import ZoneInfo

from ingestion import completion

CPH = ZoneInfo("Europe/Copenhagen")


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=CPH)


def test_windows_default_grace_and_deadline():
    scrape_after, deadline = completion.windows("2024-07-11", 6, 72)
    # End of 2024-07-11 23:59 CPH + 6h -> 2024-07-12 05:59
    assert scrape_after == at(2024, 7, 12, 5, 59)
    # + 72h from 23:59 on the 11th -> 2024-07-14 23:59
    assert deadline == at(2024, 7, 14, 23, 59)


def test_skip_before_scrape_window():
    # Noon on the meet's last day, well before end+6h.
    assert completion.decide(at(2024, 7, 11, 12), "2024-07-11", 6, 72) == "skip"


def test_check_inside_window():
    # 08:00 the morning after — past +6h, before +72h.
    assert completion.decide(at(2024, 7, 12, 8), "2024-07-11", 6, 72) == "check"


def test_deadline_after_window():
    # Five days later — past the 72h deadline.
    assert completion.decide(at(2024, 7, 16, 8), "2024-07-11", 6, 72) == "deadline"


def test_custom_grace_hours_shift_window():
    # grace 0 -> window opens at 23:59 on the meet's last day.
    assert completion.decide(at(2024, 7, 11, 23, 30), "2024-07-11", 0, 72) == "skip"
    assert completion.decide(at(2024, 7, 12, 0, 30), "2024-07-11", 0, 72) == "check"
