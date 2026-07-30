"""Curated fixtures for digest tests: six seasons of DM-L with varied points.

webbuild_fixtures gives every swim points=500, which cannot exercise medians or
top-N ordering. Here points vary per swimmer and per season so the 5-season
window, the medians and the top-swims ranking are all observable.
"""
import duckdb

from analytics.loader import create_views
from tests.analytics_fixtures import build_curated


def _row(**kw):
    base = {
        "result_id": None, "race_id": None, "meet_id": None, "rank": None,
        "name": None, "swimmer_id": None, "nationality": "DEN", "club": None,
        "birth_year": 2000, "completed_time": None, "completed_centiseconds": None,
        "points": None, "points_fixed": None, "season": None, "course": "LCM",
        "meet_name": None, "venue": "Aarhus", "meet_date": None, "number": 1,
        "race_name": None, "distance": None, "stroke": None, "gender": None,
        "relay_count": 1, "type": None, "class": "open",
    }
    base.update(kw)
    return base


def _time(cs):
    return f"{cs // 6000}:{(cs % 6000) // 100:02d}.{cs % 100:02d}"


# (gender, distance, stroke) -> dist_group is sprint/middel/lang in digest.py
_EVENTS = [
    ("M", 100, "Fri"),      # sprint
    ("F", 200, "Ryg"),      # middel
    ("M", 800, "Fri"),      # lang
    ("F", 200, "Bryst"),    # middel
]


def _dm_l_con(seasons) -> duckdb.DuckDBPyConnection:
    """DM-L, the given seasons. Six swimmers per event; points climb with
    season (base 400 + 20 per season past 2021) so medians differ per season,
    and swimmer index shifts points so top_swims has a stable order.

    Each season also carries one class='para' swim, from a club that swims
    nowhere else, with points above every open swim of any season. The digest
    filters class = 'open' in five places (facts, history, elite, top_swims,
    by_stroke); dropping any one of them moves top_points, the medians, the club
    count or the top-swims ordering, so this single row pins all of them.
    """
    obt, meets = [], []
    for season in seasons:
        mid = f"D{season}"
        name = f"Danish Champs {season}"
        mdate = f"{season}-04-10"
        meets.append(dict(meet_id=mid, meet_name=name, venue="Aarhus",
                          course="LCM", season=season, meet_date=mdate,
                          category=["DM-L"]))
        rid = 0
        for ev_i, (gender, distance, stroke) in enumerate(_EVENTS):
            for i in range(6):
                rid += 1
                pts = 400 + 20 * (season - 2021) + (5 - i) * 30 + ev_i
                cs = 5200 + i * 40 + ev_i * 1000
                obt.append(_row(
                    result_id=f"{mid}-{rid}", race_id=rid, meet_id=mid,
                    rank=i + 1, name=f"Swimmer {ev_i}{i}",
                    swimmer_id=f"s{ev_i}{i}", club=["AGF", "SIGMA", "VEST"][i % 3],
                    completed_time=_time(cs), completed_centiseconds=cs,
                    points=pts, points_fixed=pts, season=season, meet_name=name,
                    meet_date=mdate, distance=distance, stroke=stroke,
                    gender=gender, type="Final"))
        # One para swim per season: a stroke and a club that appear nowhere
        # else, and more points than any open swim in any season.
        obt.append(_row(
            result_id=f"{mid}-para", race_id=900, meet_id=mid, rank=1,
            name="Para Swimmer", swimmer_id="p1", club="PARAKLUB",
            completed_time=_time(4800), completed_centiseconds=4800,
            points=999, points_fixed=999, season=season, meet_name=name,
            meet_date=mdate, distance=100, stroke="Fly", gender="M",
            type="Timed final", **{"class": "para"}))
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con


def digest_con() -> duckdb.DuckDBPyConnection:
    """DM-L, seasons 2021..2026 (no gaps)."""
    return _dm_l_con(range(2021, 2027))


def gapped_digest_con() -> duckdb.DuckDBPyConnection:
    """DM-L with a season gap at 2023-2024, to exercise the on-record window:
    season_history and by_stroke must both skip the gap, not count back 5
    calendar years from the meet's season."""
    return _dm_l_con([2019, 2020, 2021, 2022, 2025, 2026])


def junior_digest_con() -> duckdb.DuckDBPyConnection:
    """A meet tagged BOTH DM-L and DMJ-L, 2025 + 2026. Seniors (born 2000) fill
    the final; juniors (age 17) swim heats only, so junior_championship ranks a
    different podium than the senior final — the case digest.build must scope."""
    obt, meets = [], []
    for season in (2025, 2026):
        mid = f"J{season}"
        name = f"Combined Champs {season}"
        mdate = f"{season}-04-10"
        meets.append(dict(meet_id=mid, meet_name=name, venue="Aarhus",
                          course="LCM", season=season, meet_date=mdate,
                          category=["DM-L", "DMJ-L"]))
        rid = 0
        for phase, field in (
            ("Heats", [(f"sen{i}", f"Senior {i}", 2000, 5300 + i * 40, 600 - i * 20)
                       for i in range(3)]
                      + [(f"jun{i}", f"Junior {i}", season - 17, 5600 + i * 40,
                          520 - i * 20) for i in range(4)]),
            ("Final", [(f"sen{i}", f"Senior {i}", 2000, 5250 + i * 40, 620 - i * 20)
                       for i in range(3)]),
        ):
            for i, (sid, sname, by, cs, pts) in enumerate(field, 1):
                rid += 1
                obt.append(_row(
                    result_id=f"{mid}-{phase}-{rid}", race_id=rid, meet_id=mid,
                    rank=i, name=sname, swimmer_id=sid, club="AGF", birth_year=by,
                    completed_time=_time(cs), completed_centiseconds=cs,
                    points=pts, points_fixed=pts, season=season, meet_name=name,
                    meet_date=mdate, distance=100, stroke="Fri", gender="M",
                    type=phase))
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con


def tied_points_con() -> duckdb.DuckDBPyConnection:
    """One meet where many swims tie on points across the top-N cutoff.

    digest.TOP_N is 10; this builds 16 scoring swims of which 12 sit on exactly
    500 points, so the cutoff falls inside the tie and any non-total ordering
    can return a different set of rows per call — which is what the live zone
    does. Distinct swimmers and events, so the tie-break has something to sort
    on.
    """
    obt, meets = [], []
    mid, season, mdate = "T2026", 2026, "2026-04-10"
    meets.append(dict(meet_id=mid, meet_name="Tied Champs 2026", venue="Aarhus",
                      course="LCM", season=season, meet_date=mdate,
                      category=["DM-L"]))
    # 4 clearly-above-the-tie swims, then 12 all on 500.
    field = [(f"hi{i}", f"Alpha {i}", 900 - i) for i in range(4)]
    field += [(f"tie{i:02d}", f"Tied Swimmer {i:02d}", 500) for i in range(12)]
    for rid, (sid, sname, pts) in enumerate(field, 1):
        gender, distance, stroke = _EVENTS[rid % len(_EVENTS)]
        obt.append(_row(
            result_id=f"{mid}-{rid}", race_id=rid, meet_id=mid, rank=1,
            name=sname, swimmer_id=sid, club="AGF",
            completed_time=_time(6000 + rid), completed_centiseconds=6000 + rid,
            points=pts, points_fixed=pts, season=season,
            meet_name="Tied Champs 2026", meet_date=mdate,
            distance=distance, stroke=stroke, gender=gender, type="Final"))
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets)
    create_views(con)
    return con
