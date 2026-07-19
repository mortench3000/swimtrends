"""One curated fixture for webbuild tests: a DM-L meet in 2025 and 2026.

Two events (M 100 Fri LCM, F 200 Ryg LCM), each with heats + final rows so
podium, cut-line and heats->final facts are all exercised. Rows are minimal but
schema-complete for the views.
"""
import duckdb

from analytics.loader import create_views
from tests.analytics_fixtures import build_curated


def _obt_row(**kw):
    base = {
        "result_id": None, "race_id": None, "meet_id": None, "rank": None, "name": None,
        "swimmer_id": None, "nationality": "DEN", "club": None, "birth_year": 2005,
        "completed_time": None, "completed_centiseconds": None, "points": 500,
        "points_fixed": 500, "season": None, "course": "LCM", "meet_name": None, "venue": "Aarhus",
        "meet_date": None, "number": 1, "race_name": None, "distance": None, "stroke": None,
        "gender": None, "relay_count": 1, "type": None, "class": "open",
    }
    base.update(kw)
    return base


def _event(meet_id, meet_name, season, meet_date, gender, distance, stroke,
           finalists, start_rid=1):
    """finalists: list of (swimmer_id, name, club, final_cs). Heats mirror them
    plus one extra swimmer so an 8th-place cut-line exists when >=8.
    Returns (rows, next_rid) so race_id is unique per meet."""
    rows = []
    rid = start_rid - 1
    # heats: everyone + a filler field so entrants can reach 8
    slowest = max(cs for _, _, _, cs in finalists)
    field = finalists + [(f"h{i}", f"Heat Swimmer {i}", "HeatKlub", slowest + i * 30)
                         for i in range(1, 9)]
    for i, (sid, name, club, cs) in enumerate(sorted(field, key=lambda x: x[3]), 1):
        rid += 1
        rows.append(_obt_row(
            result_id=f"{meet_id}-h-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=sid, club=club,
            completed_time=f"{cs//6000}:{(cs%6000)//100:02d}.{cs%100:02d}",
            completed_centiseconds=cs, season=season, meet_name=meet_name,
            meet_date=meet_date, distance=distance, stroke=stroke, gender=gender,
            type="Heats"))
    # final: the finalists only, faster times, ranked
    for i, (sid, name, club, cs) in enumerate(sorted(finalists, key=lambda x: x[3]), 1):
        rid += 1
        fcs = cs - 50
        rows.append(_obt_row(
            result_id=f"{meet_id}-f-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=sid, club=club,
            completed_time=f"{fcs//6000}:{(fcs%6000)//100:02d}.{fcs%100:02d}",
            completed_centiseconds=fcs, season=season, meet_name=meet_name,
            meet_date=meet_date, distance=distance, stroke=stroke, gender=gender,
            type="Final"))
    return rows, rid + 1


def curated_con() -> duckdb.DuckDBPyConnection:
    obt, meets = [], []
    for season, mid, mdate in [(2025, "M2025", "2025-04-10"),
                               (2026, "M2026", "2026-04-10")]:
        name = f"Danish Champs {season}"
        meets.append(dict(meet_id=mid, meet_name=name, venue="Aarhus",
                          course="LCM", season=season, meet_date=mdate,
                          category=["DM-L"]))
        next_rid = 1
        rows, next_rid = _event(mid, name, season, mdate, "M", 100, "Fri",
                                [("s1", "Anna Berg", "AGF", 5200),
                                 ("s2", "Bo Dahl", "SIGMA", 5250),
                                 ("s3", "Cara Elg", "AGF", 5300)],
                                start_rid=next_rid)
        obt += rows
        rows, next_rid = _event(mid, name, season, mdate, "F", 200, "Ryg",
                                [("s4", "Dina Fog", "SIGMA", 13000),
                                 ("s5", "Eva Gru", "AGF", 13100),
                                 ("s6", "Fia Hald", "VEST", 13200)],
                                start_rid=next_rid)
        obt += rows
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con
