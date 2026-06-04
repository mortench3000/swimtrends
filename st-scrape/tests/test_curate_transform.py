"""transform_meet ties model builders together from parsed raw dicts."""
from curate import transform

MEET = {"meet_id": 8609, "meet": "DM L 2021", "venue": "Aarhus", "course": "LCM",
        "season": 2021, "date": "08-07-2021", "category": ["DM-L"]}
RACES = [
    {"meet_id": 8609, "race_id": 1, "number": 1, "name": "100 Fri - Damer",
     "distance": 100, "stroke": "Fri", "gender": "F", "relay_count": 1,
     "type": "Final", "class": "open"},
    {"meet_id": 8609, "race_id": 2, "number": 2, "name": "100 Fri - Damer",
     "distance": 100, "stroke": "Fri", "gender": "F", "relay_count": 1,
     "type": "Timed final", "class": "open"},   # para by heuristic (dup of race 1)
]
RESULTS = [
    {"race_id": 1, "Rank": 1, "Name": "A", "Swimmer_id": "7", "completed_time": "1:00.00",
     "completed_centiseconds": 6000, "splits": []},
    {"race_id": 2, "Rank": 1, "Name": "P", "Swimmer_id": "8", "completed_time": "1:10.00",
     "completed_centiseconds": 7000, "splits": []},
]


def test_transform_produces_all_tables_and_para_is_unscored():
    base_times = {(2021, "LCM", "F", 1, 100, "FREE"): 60.0}
    tables = transform.transform_meet(MEET, RACES, RESULTS, base_times, overrides={})
    assert set(tables) == {"dim_meet", "dim_race", "fact_result", "fact_split", "obt_result"}
    assert len(tables["dim_meet"]) == 1
    # Race 2 is para (Timed final duplicating race 1's name) -> dim_race says so.
    race_class = {r["race_id"]: r["class"] for r in tables["dim_race"]}
    assert race_class == {1: "open", 2: "para"}
    # Open result scored, para result unscored.
    pts = {r["race_id"]: r["points"] for r in tables["fact_result"]}
    assert pts[1] == 1000 and pts[2] is None
