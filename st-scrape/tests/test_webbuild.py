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
