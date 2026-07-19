import json
from pathlib import Path

import duckdb

from webbuild import shape, queries
from tests.webbuild_fixtures import curated_con
from tests.analytics_fixtures import build_curated
from analytics.loader import create_views


def test_race_key_slug():
    assert shape.race_key("M", 100, "Fri", "LCM") == "M-100-Fri-LCM"


def test_write_json_roundtrip_keeps_danish(tmp_path: Path):
    p = tmp_path / "sub" / "x.json"
    shape.write_json(p, {"club": "Svømmeklubben Åræø"})
    text = p.read_text(encoding="utf-8")
    assert "Åræø" in text            # not \u-escaped
    assert json.loads(text)["club"] == "Svømmeklubben Åræø"


def test_fixture_has_views_and_two_seasons():
    con = curated_con()
    seasons = [r[0] for r in con.execute(
        "SELECT DISTINCT season FROM results_by_category "
        "WHERE category='DM-L' ORDER BY season").fetchall()]
    assert seasons == [2025, 2026]


def test_build_index_lists_category_and_seasons():
    idx = queries.build_index(curated_con())
    assert idx["attribution"] == "Data fra svømmetider.dk"
    dm_l = [c for c in idx["categories"] if c["code"] == "DM-L"][0]
    assert dm_l["seasons"] == [2026, 2025]      # newest first


def test_build_meets_lists_meets_newest_first():
    out = queries.build_meets(curated_con(), "DM-L")
    assert out["category"] == "DM-L"
    seasons = [m["season"] for m in out["meets"]]
    assert seasons == [2026, 2025]
    m = out["meets"][0]
    assert m["meet_id"] == "M2026"
    assert m["events"] == 2                 # 100 Fri + 200 Ryg
    assert m["entrants"] == 22              # 11 distinct swimmers/event x 2
    assert m["clubs"] >= 3


def test_build_meet_facts_and_comparison():
    out = queries.build_meet(curated_con(), "DM-L", "M2026")
    assert out["meet_id"] == "M2026"
    f = out["facts"]
    assert f["events"] == 2
    assert f["entrants"] == 22
    assert f["swims"] > 0
    assert f["top_points"] >= f["median_points"]
    comp_seasons = [c["season"] for c in out["season_comparison"]]
    assert comp_seasons == [2026, 2025]        # <=5, newest first


def test_build_races_lists_events_with_winner():
    out = queries.build_races(curated_con(), "DM-L", "M2026")
    keys = {r["race_key"] for r in out["races"]}
    assert "M-100-Fri-LCM" in keys
    fri = [r for r in out["races"] if r["race_key"] == "M-100-Fri-LCM"][0]
    assert fri["label"] == "M 100m Fri (LCM)"
    assert fri["contestants"] == 11         # 3 finalists + 8 heat fillers
    assert fri["winner_name"] == "Anna Berg"   # fastest final


def test_build_races_winning_time_with_sub_and_over_minute():
    """Regression: winning_time must use arg_min, not lexicographic min.

    When one finalist swims sub-minute (e.g. 58.21) and another over-minute
    (e.g. 1:02.48), lexicographic min("58.21", "1:02.48") returns "1:02.48"
    because "1" < "5" in ASCII. This test ensures winning_time picks the
    actual fastest time via arg_min(completed_time, completed_centiseconds).
    """
    # Build minimal curated connection with one event: sub-minute vs over-minute
    def _obt_row(**kw):
        base = {
            "result_id": None, "race_id": None, "meet_id": None, "rank": None,
            "name": None, "swimmer_id": None, "nationality": "DEN", "club": None,
            "birth_year": 2005, "completed_time": None, "completed_centiseconds": None,
            "points": 500, "points_fixed": 500, "season": None, "course": "LCM",
            "meet_name": None, "venue": "Aarhus", "meet_date": None, "number": 1,
            "race_name": None, "distance": None, "stroke": None, "gender": None,
            "relay_count": 1, "type": None, "class": "open",
        }
        base.update(kw)
        return base

    obt = []
    meet_id, meet_name, season, meet_date = "MINMAX", "Sub vs Over Minute", 2026, "2026-07-19"
    meets = [dict(meet_id=meet_id, meet_name=meet_name, venue="Aarhus",
                  course="LCM", season=season, meet_date=meet_date,
                  category=["DM-L"])]

    # Event: M 100 Fri, two finalists with times on opposite sides of 60 seconds
    # Times formatted without leading 0: "58.21" (sub-60) vs "1:02.48" (over-60)
    # Lexicographic min("58.21", "1:02.48") = "1:02.48" (wrong, because "1" < "5")
    # Correct min by centiseconds: 5821 < 6248, so "58.21" wins

    finalists = [
        ("fast-swimmer", "Fast Runner", "SpeedClub", 5821, "58.21"),     # sub-60
        ("slow-swimmer", "Slow Jogger", "SlowClub", 6248, "1:02.48"),    # over-60
    ]

    # Heats: both finalists + heat fillers
    rid = 0
    slowest = max(cs for _, _, _, cs, _ in finalists)
    for i, (sid, name, club, cs, time_str) in enumerate(sorted(
        finalists + [
            (f"h-filler-{j}", f"Heater {j}", "HeatClub", slowest + j * 30,
             f"{(slowest + j*30)//6000}:{((slowest + j*30)%6000)//100:02d}.{(slowest + j*30)%100:02d}")
            for j in range(8)
        ], key=lambda x: x[3]), 1):
        rid += 1
        obt.append(_obt_row(
            result_id=f"{meet_id}-h-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=sid, club=club,
            completed_time=time_str, completed_centiseconds=cs,
            season=season, meet_name=meet_name,
            meet_date=meet_date, distance=100, stroke="Fri", gender="M",
            type="Heats"))

    # Finals: only finalists, faster times
    for i, (sid, name, club, cs, _) in enumerate(sorted(finalists, key=lambda x: x[3]), 1):
        rid += 1
        fcs = cs - 50  # finalists go 50 cs faster
        # Format: keep same format style (without leading 0 for sub-60)
        if fcs < 6000:
            fcs_str = f"{(fcs % 6000) // 100}.{fcs % 100:02d}"
        else:
            fcs_str = f"{fcs // 6000}:{((fcs % 6000) // 100):02d}.{fcs % 100:02d}"
        obt.append(_obt_row(
            result_id=f"{meet_id}-f-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=sid, club=club,
            completed_time=fcs_str, completed_centiseconds=fcs,
            season=season, meet_name=meet_name,
            meet_date=meet_date, distance=100, stroke="Fri", gender="M",
            type="Final"))

    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)

    # Query and verify
    out = queries.build_races(con, "DM-L", meet_id)
    race = out["races"][0]

    # The winner should be the faster finalist (5821 - 50 = 5771 cs = "57.71")
    assert race["winner_name"] == "Fast Runner", \
        f"Expected 'Fast Runner' but got '{race['winner_name']}'"
    # The winning time should be the sub-minute time (57.71)
    assert race["winning_time"] == "57.71", \
        f"Expected '57.71' but got '{race['winning_time']}'"


def test_build_race_facts_podium_and_comparison():
    con = curated_con()
    out = queries.build_race(con, "DM-L", "M2026", "M", 100, "Fri", "LCM")
    assert out["race_key"] == "M-100-Fri-LCM"
    f = out["facts"]
    assert f["contestants"] == 11
    assert f["cutline_centiseconds"] is not None   # 8th heat swim exists
    assert f["winning_time"] is not None
    podium = out["podium"]
    assert [p["rank"] for p in podium] == [1, 2, 3]
    assert podium[0]["name"] == "Anna Berg"
    comp_seasons = [c["season"] for c in out["season_comparison"]]
    assert comp_seasons == [2026, 2025]
    assert out["season_comparison"][0]["best_cs"] is not None

    # Regression: winning_time must be the fastest finalist's time, not a
    # lexicographic min of the completed_time strings.
    fastest_final_time = con.execute(
        "SELECT completed_time FROM results_by_category "
        "WHERE category='DM-L' AND meet_id='M2026' AND gender='M' AND distance=100 "
        "AND stroke='Fri' AND course='LCM' AND phase IN ('final','timed_final') "
        "AND NOT is_dq ORDER BY completed_centiseconds LIMIT 1"
    ).fetchone()[0]
    assert f["winning_time"] == fastest_final_time
    assert podium[0]["time"] == fastest_final_time


def test_build_race_winning_time_sub_and_over_minute():
    """Regression: build_race winning_time must use arg_min, not lexicographic min.

    When one finalist swims sub-minute (e.g. 57.71) and another over-minute
    (e.g. 1:02.48), lexicographic min("57.71", "1:02.48") returns "1:02.48"
    because "1" < "5" in ASCII. This test ensures build_race picks the actual
    fastest time via arg_min(completed_time, completed_centiseconds).
    """
    def _obt_row(**kw):
        base = {
            "result_id": None, "race_id": None, "meet_id": None, "rank": None,
            "name": None, "swimmer_id": None, "nationality": "DEN", "club": None,
            "birth_year": 2005, "completed_time": None, "completed_centiseconds": None,
            "points": 500, "points_fixed": 500, "season": None, "course": "LCM",
            "meet_name": None, "venue": "Aarhus", "meet_date": None, "number": 1,
            "race_name": None, "distance": None, "stroke": None, "gender": None,
            "relay_count": 1, "type": None, "class": "open",
        }
        base.update(kw)
        return base

    obt = []
    meet_id, meet_name, season, meet_date = "BR100", "Build Race Sub Over", 2026, "2026-07-19"
    meets = [dict(meet_id=meet_id, meet_name=meet_name, venue="Aarhus",
                  course="LCM", season=season, meet_date=meet_date,
                  category=["DM-L"])]

    # Event: M 100 Fri, two finalists with times on opposite sides of 60 seconds
    # Times formatted without leading 0: "57.71" (sub-60) vs "1:02.48" (over-60)
    # Lexicographic min("57.71", "1:02.48") = "1:02.48" (wrong, because "1" < "5")
    # Correct min by centiseconds: 5771 < 6248, so "57.71" wins

    finalists = [
        ("sub-fast", "Sub Minute", "FastClub", 5771, "57.71"),         # sub-60
        ("over-slow", "Over Minute", "SlowClub", 6248, "1:02.48"),     # over-60
    ]

    # Heats: both finalists + heat fillers
    rid = 0
    slowest = max(cs for _, _, _, cs, _ in finalists)
    for i, (sid, name, club, cs, time_str) in enumerate(sorted(
        finalists + [
            (f"h-filler-{j}", f"Heater {j}", "HeatClub", slowest + j * 30,
             f"{(slowest + j*30)//6000}:{((slowest + j*30)%6000)//100:02d}.{(slowest + j*30)%100:02d}")
            for j in range(8)
        ], key=lambda x: x[3]), 1):
        rid += 1
        obt.append(_obt_row(
            result_id=f"{meet_id}-h-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=sid, club=club,
            completed_time=time_str, completed_centiseconds=cs,
            season=season, meet_name=meet_name,
            meet_date=meet_date, distance=100, stroke="Fri", gender="M",
            type="Heats"))

    # Finals: only finalists, faster times
    for i, (sid, name, club, cs, _) in enumerate(sorted(finalists, key=lambda x: x[3]), 1):
        rid += 1
        fcs = cs - 50  # finalists go 50 cs faster
        # Format: keep same format style (without leading 0 for sub-60)
        if fcs < 6000:
            fcs_str = f"{(fcs % 6000) // 100}.{fcs % 100:02d}"
        else:
            fcs_str = f"{fcs // 6000}:{((fcs % 6000) // 100):02d}.{fcs % 100:02d}"
        obt.append(_obt_row(
            result_id=f"{meet_id}-f-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=sid, club=club,
            completed_time=fcs_str, completed_centiseconds=fcs,
            season=season, meet_name=meet_name,
            meet_date=meet_date, distance=100, stroke="Fri", gender="M",
            type="Final"))

    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)

    # Query build_race and verify winning_time and podium[0]
    out = queries.build_race(con, "DM-L", meet_id, "M", 100, "Fri", "LCM")

    # The winner should be the faster finalist (5771 - 50 = 5721 cs = "57.21")
    assert out["podium"][0]["name"] == "Sub Minute", \
        f"Expected podium[0] 'Sub Minute' but got '{out['podium'][0]['name']}'"
    # The winning time should be the sub-minute time (57.21)
    expected_winning_time = "57.21"
    assert out["facts"]["winning_time"] == expected_winning_time, \
        f"Expected facts['winning_time'] '{expected_winning_time}' but got '{out['facts']['winning_time']}'"
    assert out["podium"][0]["time"] == expected_winning_time, \
        f"Expected podium[0]['time'] '{expected_winning_time}' but got '{out['podium'][0]['time']}'"


def test_build_race_facts_dsq_counted_from_results():
    """Regression: facts["dsq"] must count DSQ rows.

    _RACE_FACTS_SQL previously sourced "dsq" from results_by_category, which
    is built on individual_results (analytics/views/00_base.sql), and that
    view filters out is_dq rows upstream. So dsq was silently always 0.
    DSQ rows live in the base `results` view and must be counted from there:
    meet_id + event tuple, is_dq, NOT is_relay.
    """
    def _obt_row(**kw):
        base = {
            "result_id": None, "race_id": None, "meet_id": None, "rank": None,
            "name": None, "swimmer_id": None, "nationality": "DEN", "club": None,
            "birth_year": 2005, "completed_time": None, "completed_centiseconds": None,
            "points": 500, "points_fixed": 500, "season": None, "course": "LCM",
            "meet_name": None, "venue": "Aarhus", "meet_date": None, "number": 1,
            "race_name": None, "distance": None, "stroke": None, "gender": None,
            "relay_count": 1, "type": None, "class": "open",
        }
        base.update(kw)
        return base

    meet_id, season, meet_date = "MDSQ", 2026, "2026-07-19"
    meets = [dict(meet_id=meet_id, meet_name="DSQ Meet", venue="Aarhus",
                  course="LCM", season=season, meet_date=meet_date,
                  category=["DM-L"])]

    common = dict(season=season, meet_name="DSQ Meet", meet_date=meet_date,
                  distance=100, stroke="Fri", gender="M", meet_id=meet_id)

    obt = [
        # Two valid finalists (heats + final each, as the fixture pattern does)
        _obt_row(result_id="h1", race_id=1, rank=1, name="A One", swimmer_id="s1",
                 club="AGF", completed_time="55.00", completed_centiseconds=5500,
                 type="Heats", **common),
        _obt_row(result_id="h2", race_id=2, rank=2, name="B Two", swimmer_id="s2",
                 club="AGF", completed_time="56.00", completed_centiseconds=5600,
                 type="Heats", **common),
        _obt_row(result_id="f1", race_id=3, rank=1, name="A One", swimmer_id="s1",
                 club="AGF", completed_time="54.50", completed_centiseconds=5450,
                 type="Final", **common),
        _obt_row(result_id="f2", race_id=4, rank=2, name="B Two", swimmer_id="s2",
                 club="AGF", completed_time="55.50", completed_centiseconds=5550,
                 type="Final", **common),
        # DSQ rows: rank -1, individual (relay_count=1), same event/meet
        _obt_row(result_id="dq1", race_id=5, rank=-1, name="C Three", swimmer_id="s3",
                 club="AGF", completed_time="DSQ", completed_centiseconds=None,
                 type="Heats", **common),
        _obt_row(result_id="dq2", race_id=6, rank=-1, name="D Four", swimmer_id="s4",
                 club="AGF", completed_time="DSQ", completed_centiseconds=None,
                 type="Final", **common),
    ]

    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)

    out = queries.build_race(con, "DM-L", meet_id, "M", 100, "Fri", "LCM")
    assert out["facts"]["dsq"] == 2, \
        f"Expected 2 DSQ rows counted, got {out['facts']['dsq']}"
    assert out["facts"]["contestants"] == 2, \
        "contestants must count only valid (non-DQ) swimmers"
