"""Authoritative class = per-(meet,race) override if present, else the raw
Timed-final-duplicating-a-prelim/final heuristic."""
from curate import classify


def _race(race_id, name, rtype):
    return {"race_id": race_id, "name": name, "type": rtype}


def test_heuristic_marks_timed_final_duplicate_as_para():
    races = [
        _race(1, "100 Fri - Damer", "Heats"),
        _race(2, "100 Fri - Damer", "Final"),
        _race(3, "100 Fri - Damer", "Timed final"),  # para: duplicates a prelim/final
        _race(4, "800 Fri - Damer", "Timed final"),   # open: no prelim/final twin
    ]
    resolved = classify.authoritative_class(races, overrides={})
    assert resolved == {1: "open", 2: "open", 3: "para", 4: "open"}


def test_override_wins_over_heuristic():
    races = [_race(9, "50 Fri - Herrer", "Timed final")]  # heuristic -> open
    resolved = classify.authoritative_class(races, overrides={9: "para"})
    assert resolved == {9: "para"}


def test_override_can_force_open():
    races = [
        _race(1, "100 Fri - Damer", "Heats"),
        _race(2, "100 Fri - Damer", "Final"),
        _race(3, "100 Fri - Damer", "Timed final"),  # heuristic -> para
    ]
    resolved = classify.authoritative_class(races, overrides={3: "open"})
    assert resolved[3] == "open"
