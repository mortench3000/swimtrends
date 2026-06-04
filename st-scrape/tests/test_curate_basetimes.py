"""Base-times loader parses JSONL into the (season,course,gender,relay,dist,stroke)
-> seconds lookup the points module expects."""
from curate import basetimes

JSONL = (
    '{"season": 2022, "course": "LCM", "gender": "F", "relay_count": 1, '
    '"distance": 100, "stroke": "FREE", "basetime": "51.71", "basetime_in_sec": 51.71}\n'
    '{"season": 2026, "course": "LCM", "gender": "F", "relay_count": 1, '
    '"distance": 100, "stroke": "FREE", "basetime": "50.00", "basetime_in_sec": 50.0}\n'
)


def test_parse_jsonl_to_lookup():
    table = basetimes.parse(JSONL)
    assert table[(2022, "LCM", "F", 1, 100, "FREE")] == 51.71
    assert table[(2026, "LCM", "F", 1, 100, "FREE")] == 50.0
