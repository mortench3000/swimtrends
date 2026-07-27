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


def digest_con() -> duckdb.DuckDBPyConnection:
    """DM-L, seasons 2021..2026. Six swimmers per event; points climb with
    season (base 400 + 20 per season past 2021) so medians differ per season,
    and swimmer index shifts points so top_swims has a stable order."""
    obt, meets = [], []
    for season in range(2021, 2027):
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
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con


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
