"""Row builders: dim_meet, dim_race, fact_result (+ result_id, points),
fact_split, obt_result."""
from curate import model

MEET = {"meet_id": 8609, "meet": "DM Langbane 2021", "venue": "Aarhus",
        "course": "LCM", "season": 2021, "date": "08-07-2021",
        "category": ["DM-L", "DMJ-L"]}

RACES = [
    {"meet_id": 8609, "race_id": 1, "number": 1, "name": "100 Fri - Damer",
     "distance": 100, "stroke": "Fri", "gender": "F", "relay_count": 1,
     "type": "Final", "class": "open"},
]

RESULTS = [
    {"race_id": 1, "Rank": 1, "Name": "A B", "Swimmer_id": "7", "nationality": "DK",
     "club": "C", "birth_year": 2001, "completed_time": "1:00.00",
     "completed_centiseconds": 6000,
     "splits": [{"distance": 50, "split_time": "29.00", "split_centiseconds": 2900,
                 "cumulative_time": "29.00", "cumulative_centiseconds": 2900}]},
    {"race_id": 1, "Rank": -1, "Name": "DQ One", "Swimmer_id": "8", "nationality": "DK",
     "club": "C", "birth_year": 2002, "completed_time": "DQ",
     "completed_centiseconds": None, "splits": []},
    {"race_id": 1, "Rank": -1, "Name": "DQ Two", "Swimmer_id": "9", "nationality": "DK",
     "club": "C", "birth_year": 2003, "completed_time": "DQ",
     "completed_centiseconds": None, "splits": []},
]


def test_dim_meet_row():
    row = model.build_dim_meet(MEET)
    assert row == {"meet_id": "8609", "meet_name": "DM Langbane 2021",
                   "venue": "Aarhus", "course": "LCM", "season": 2021,
                   "meet_date": "08-07-2021", "category": ["DM-L", "DMJ-L"]}


def test_dim_race_carries_authoritative_class_and_partitions():
    rows = model.build_dim_race(RACES, {1: "para"}, season=2021, course="LCM")
    assert rows[0]["class"] == "para"
    assert rows[0]["season"] == 2021 and rows[0]["course"] == "LCM"
    assert rows[0]["race_id"] == 1 and rows[0]["meet_id"] == "8609"


def test_result_id_uses_ordinal_not_rank_so_dqs_dont_collide():
    table = {(2021, "LCM", "F", 1, 100, "FREE"): 60.0}
    races_by_id = {1: RACES[0]}
    rows = model.build_fact_result(RESULTS, races_by_id, {1: "open"}, table,
                                   meet_id="8609", season=2021, course="LCM")
    ids = [r["result_id"] for r in rows]
    assert ids == ["1-0", "1-1", "1-2"]   # two DQs do NOT collide
    # First row scored (base 60.0 vs 60.0 swim -> 1000); DQs unscored.
    assert rows[0]["points"] == 1000 and rows[0]["points_fixed"] is None
    assert rows[1]["points"] is None and rows[2]["points"] is None
    assert rows[0]["rank"] == 1 and rows[0]["swimmer_id"] == "7"


def test_fact_split_keys_to_result_id():
    rows = model.build_fact_split(RESULTS, meet_id="8609", season=2021, course="LCM")
    assert len(rows) == 1                 # only the first result has splits
    assert rows[0]["result_id"] == "1-0"
    assert rows[0]["distance"] == 50 and rows[0]["split_centiseconds"] == 2900


def test_obt_inlines_meet_and_race_attributes():
    table = {(2021, "LCM", "F", 1, 100, "FREE"): 60.0}
    races_by_id = {1: RACES[0]}
    fact = model.build_fact_result(RESULTS, races_by_id, {1: "open"}, table,
                                   meet_id="8609", season=2021, course="LCM")
    obt = model.build_obt(fact, MEET, races_by_id, {1: "open"})
    assert obt[0]["meet_name"] == "DM Langbane 2021"
    assert obt[0]["race_name"] == "100 Fri - Damer"
    assert obt[0]["stroke"] == "Fri" and obt[0]["class"] == "open"
    assert obt[0]["result_id"] == "1-0" and obt[0]["points"] == 1000
