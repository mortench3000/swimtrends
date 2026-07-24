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
    event_tag = f"{gender}{distance}{stroke}"
    field = finalists + [(f"h-{event_tag}-{i}", f"Heat Swimmer {i}", "HeatKlub", slowest + i * 30)
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


def _relay_event(meet_id, meet_name, season, meet_date, gender, distance, stroke,
                 relay_count, teams, start_rid):
    """teams: list of (team_name, club, cs). One timed-final row per team, ranked."""
    rows = []
    rid = start_rid
    for i, (name, club, cs) in enumerate(sorted(teams, key=lambda x: x[2]), 1):
        rows.append(_obt_row(
            result_id=f"{meet_id}-r-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=None, club=club,
            completed_time=f"{cs//6000}:{(cs%6000)//100:02d}.{cs%100:02d}",
            completed_centiseconds=cs, season=season, meet_name=meet_name,
            meet_date=meet_date, distance=distance, stroke=stroke, gender=gender,
            relay_count=relay_count, type="Timed final"))
        rid += 1
    return rows, rid


def _combined_event(meet_id, meet_name, season, meet_date, gender, distance, stroke,
                    finalists, heat_only):
    """Combined senior+junior event. finalists: (sid, name, club, final_cs, birth_year)
    -> heats (final_cs+50) AND final. heat_only: (sid, name, club, heat_cs, birth_year)
    -> heats only, e.g. juniors who never reach the senior final. Returns rows."""
    rows = []
    rid = 0
    field = [(sid, name, club, cs + 50, by) for sid, name, club, cs, by in finalists]
    field += list(heat_only)
    for i, (sid, name, club, cs, by) in enumerate(sorted(field, key=lambda x: x[3]), 1):
        rid += 1
        rows.append(_obt_row(
            result_id=f"{meet_id}-h-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=sid, club=club, birth_year=by,
            completed_time=f"{cs//6000}:{(cs%6000)//100:02d}.{cs%100:02d}",
            completed_centiseconds=cs, season=season, meet_name=meet_name,
            meet_date=meet_date, distance=distance, stroke=stroke, gender=gender,
            type="Heats"))
    for i, (sid, name, club, cs, by) in enumerate(sorted(finalists, key=lambda x: x[3]), 1):
        rid += 1
        rows.append(_obt_row(
            result_id=f"{meet_id}-f-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=sid, club=club, birth_year=by,
            completed_time=f"{cs//6000}:{(cs%6000)//100:02d}.{cs%100:02d}",
            completed_centiseconds=cs, season=season, meet_name=meet_name,
            meet_date=meet_date, distance=distance, stroke=stroke, gender=gender,
            type="Final"))
    return rows


def combined_con() -> duckdb.DuckDBPyConnection:
    """A meet tagged BOTH DM-L and DMJ-L (a combined senior+junior championship),
    2025 + 2026. In M 100 Fri three seniors (born 2000) fill the final and take the
    senior podium; four juniors (born season-17 -> age 17) swim heats only and never
    reach the final, so the junior championship (ranked on the qualifying heat swim)
    is a different podium. This is the case webbuild must junior-scope."""
    obt, meets = [], []
    for season, mid, mdate in [(2025, "C2025", "2025-04-10"),
                               (2026, "C2026", "2026-04-10")]:
        name = f"Combined Champs {season}"
        meets.append(dict(meet_id=mid, meet_name=name, venue="Aarhus",
                          course="LCM", season=season, meet_date=mdate,
                          category=["DM-L", "DMJ-L"]))
        seniors = [("cs1", "Senior Ace", "AGF", 5300, 2000),
                   ("cs2", "Senior Two", "SIGMA", 5350, 2000),
                   ("cs3", "Senior Three", "VEST", 5400, 2000)]
        fillers = [(f"cf{i}", f"Filler {i}", "FILL", 5450 + i * 30, 2000)
                   for i in range(5)]                 # 5 fillers -> final has 8
        juniors = [("cj1", "Junior Fast", "AGF", 5700, season - 17),
                   ("cj2", "Junior Mid", "SIGMA", 5750, season - 17),
                   ("cj3", "Junior Slow", "VEST", 5800, season - 17),
                   ("cj4", "Junior Last", "AGF", 5850, season - 17)]
        obt += _combined_event(mid, name, season, mdate, "M", 100, "Fri",
                               seniors + fillers, juniors)
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con


def junior_only_con() -> duckdb.DuckDBPyConnection:
    """A DMJ-L meet NOT combined with any senior category: juniors race their own
    heats + final, medals from the final. webbuild must leave this untouched
    (junior_scoped == False, all senior-structure tiles present)."""
    mid, name, season, mdate = "J2026", "Junior Champs 2026", 2026, "2026-04-10"
    meets = [dict(meet_id=mid, meet_name=name, venue="Aarhus", course="LCM",
                  season=season, meet_date=mdate, category=["DMJ-L"])]
    rows, _ = _event(mid, name, season, mdate, "M", 100, "Fri",
                     [("j1", "Ung Anna", "AGF", 5600),
                      ("j2", "Ung Bo", "SIGMA", 5650),
                      ("j3", "Ung Cara", "VEST", 5700)], start_rid=1)
    con = duckdb.connect()
    build_curated(con, obt=rows, meets=meets, splits=[])
    create_views(con)
    return con


def relay_con() -> duckdb.DuckDBPyConnection:
    """A DM-L meet in 2025 + 2026 with individual AND relay events, so relay
    queries and the individual aggregates are exercised side by side. Separate
    from curated_con() so its magic numbers stay stable."""
    obt, meets = [], []
    for season, mid, mdate in [(2025, "R2025", "2025-04-10"),
                               (2026, "R2026", "2026-04-10")]:
        name = f"Relay Champs {season}"
        meets.append(dict(meet_id=mid, meet_name=name, venue="Aarhus",
                          course="LCM", season=season, meet_date=mdate,
                          category=["DM-L"]))
        rid = 1
        rows, rid = _event(mid, name, season, mdate, "M", 100, "Fri",
                           [("s1", "Anna Berg", "AGF", 5200),
                            ("s2", "Bo Dahl", "SIGMA", 5250),
                            ("s3", "Cara Elg", "AGF", 5300)], start_rid=rid)
        obt += rows
        rows, rid = _relay_event(mid, name, season, mdate, "F", 100, "HM", 4,
                                 [("Aalborg 1", "Aalborg SK", 25051),
                                  ("Thisted", "Thisted SK", 25444),
                                  ("A6 1", "A6", 26254)], start_rid=rid)
        obt += rows
    # a DQ relay team in 2026 (rank -1): excluded from relay_results, counted by
    # the relay DSQ query (Task 4).
    obt.append(_obt_row(
        result_id="R2026-dq", race_id=9990, meet_id="R2026", rank=-1,
        name="DQ Team", swimmer_id=None, club="DQ SK", completed_time=None,
        completed_centiseconds=None, season=2026, meet_name="Relay Champs 2026",
        meet_date="2026-04-10", distance=100, stroke="HM", gender="F",
        relay_count=4, type="Timed final"))
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con


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
