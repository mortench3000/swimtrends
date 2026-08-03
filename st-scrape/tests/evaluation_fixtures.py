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


def multi_title_con() -> duckdb.DuckDBPyConnection:
    """One DM-L meet built to exercise both per-entity aggregates.

    Deliberate contents, each pinning one rule:
      * Mathias Christensen wins 4 finals across 3 strokes (the DM-L/10334
        shape) and is SECOND in a fifth -- a second place is not a title.
      * Anders Andersen and Anna Testsen win 3 each, so the block's tie on
        `titles` is broken by name; Anna's Ryg titles are entered before her
        Fri one, so canonical stroke order is observable.
      * Dobbelt Vinder wins 2: below the threshold, absent from the block.
      * A dead heat (two rank-1 rows in one event, same club) gives that club
        two titles from one event.
      * Heat Winner wins a HEAT with more points than anyone: not a title.
      * A class='para' swim with 999 points: invisible to both blocks.
      * Three filler clubs with no podiums and 3/2/1 swimmers: the top-5 cut
        and the `swimmers DESC` fallback ordering.
    """
    mid, season, mdate = "M2026", 2026, "2026-04-10"
    mname = "Multi Champs 2026"
    meets = [dict(meet_id=mid, meet_name=mname, venue="Aarhus", course="LCM",
                  season=season, meet_date=mdate, category=["DM-L"])]
    obt, rid = [], 0

    def add(sid, name, club, gender, distance, stroke, points, rank,
            phase="Final", klass="open"):
        nonlocal rid
        rid += 1
        cs = 6000 + rid
        obt.append(_row(
            result_id=f"{mid}-{rid}", race_id=rid, meet_id=mid, rank=rank,
            name=name, swimmer_id=sid, club=club, completed_time=_time(cs),
            completed_centiseconds=cs, points=points, points_fixed=points,
            season=season, meet_name=mname, meet_date=mdate, distance=distance,
            stroke=stroke, gender=gender, type=phase, **{"class": klass}))

    for g, d, st, p in [("M", 200, "IM", 764), ("M", 100, "Fly", 729),
                        ("M", 200, "Bryst", 725), ("M", 400, "IM", 715)]:
        add("m1", "Mathias Christensen", "Sigma Swim Allerød", g, d, st, p, 1)
    add("m1", "Mathias Christensen", "Sigma Swim Allerød", "M", 100, "Bryst", 690, 2)

    for d, p in [(50, 800), (100, 790), (200, 780)]:
        add("m2", "Anders Andersen", "AGF", "M", d, "Fri", p, 1)

    for d, st, p in [(100, "Ryg", 770), (200, "Ryg", 760), (100, "Fri", 750)]:
        add("m3", "Anna Testsen", "AGF", "F", d, st, p, 1)

    for d, p in [(50, 700), (100, 695)]:
        add("m4", "Dobbelt Vinder", "VEST", "F", d, "Bryst", p, 1)

    add("m5", "Dead Heat A", "AGF", "F", 200, "Fly", 710, 1)
    add("m6", "Dead Heat B", "AGF", "F", 200, "Fly", 710, 1)
    add("h1", "Heat Winner", "VEST", "M", 50, "Ryg", 900, 1, phase="Heats")
    add("p1", "Para Swimmer", "PARAKLUB", "M", 100, "Fly", 999, 1,
        phase="Timed final", klass="para")

    for club, n in [("KLUB A", 3), ("KLUB B", 2), ("KLUB C", 1)]:
        for i in range(n):
            add(f"{club[-1].lower()}{i}", f"{club} Swimmer {i}", club,
                "M", 200, "IM", 400 - i, 4 + i)

    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con


def duplicate_win_con() -> duckdb.DuckDBPyConnection:
    """A swimmer whose win in one event is duplicated as a Timed final
    alongside its Final row, both class='open' -- reachable when a para
    override (`swimtrends class set`) leaves both rows open. Without a
    swimmer x event dedup, counting rows inflates the swimmer's title count
    (here from 2 real titles to 3 counted rows) and wrongly admits a
    below-threshold swimmer to the block.
    """
    mid, season, mdate = "DUP2026", 2026, "2026-04-10"
    mname = "Duplicate Champs 2026"
    meets = [dict(meet_id=mid, meet_name=mname, venue="Aarhus", course="LCM",
                  season=season, meet_date=mdate, category=["DM-L"])]
    obt, rid = [], 0

    def add(sid, name, club, gender, distance, stroke, points, rank,
            phase="Final", klass="open"):
        nonlocal rid
        rid += 1
        cs = 6000 + rid
        obt.append(_row(
            result_id=f"{mid}-{rid}", race_id=rid, meet_id=mid, rank=rank,
            name=name, swimmer_id=sid, club=club, completed_time=_time(cs),
            completed_centiseconds=cs, points=points, points_fixed=points,
            season=season, meet_name=mname, meet_date=mdate, distance=distance,
            stroke=stroke, gender=gender, type=phase, **{"class": klass}))

    add("d1", "Double Winner", "AGF", "M", 100, "Fri", 750, 1)
    add("d1", "Double Winner", "AGF", "M", 200, "Fri", 740, 1)
    # The 200m Fri win duplicated as a Timed final -- same swimmer and event,
    # both class='open'.
    add("d1", "Double Winner", "AGF", "M", 200, "Fri", 740, 1,
        phase="Timed final")

    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con


def unscored_win_con() -> duckdb.DuckDBPyConnection:
    """A rank-1 final with points=NULL (no base time for that event/season),
    alongside enough scored wins to clear MIN_TITLES. A points-less win must
    not be counted as a title (clubs) or appear in a multi-title swimmer's
    wins (where every other points value in the digest is non-null).
    """
    mid, season, mdate = "UNS2026", 2026, "2026-04-10"
    mname = "Unscored Champs 2026"
    meets = [dict(meet_id=mid, meet_name=mname, venue="Aarhus", course="LCM",
                  season=season, meet_date=mdate, category=["DM-L"])]
    obt, rid = [], 0

    def add(sid, name, club, gender, distance, stroke, points, rank,
            phase="Final"):
        nonlocal rid
        rid += 1
        cs = 6000 + rid
        obt.append(_row(
            result_id=f"{mid}-{rid}", race_id=rid, meet_id=mid, rank=rank,
            name=name, swimmer_id=sid, club=club, completed_time=_time(cs),
            completed_centiseconds=cs, points=points, points_fixed=points,
            season=season, meet_name=mname, meet_date=mdate, distance=distance,
            stroke=stroke, gender=gender, type=phase))

    for d, st, p in [(100, "Fri", 750), (200, "Fri", 740), (200, "Ryg", 730)]:
        add("u1", "Unscored Sweeper", "AGF", "M", d, st, p, 1)
    # A fourth final win, but with no base time to score it against.
    add("u1", "Unscored Sweeper", "AGF", "M", 400, "Fri", None, 1)

    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con


def junior_multi_title_con() -> duckdb.DuckDBPyConnection:
    """A DM-L + DMJ-L meet where a SENIOR sweeps the finals and a JUNIOR sweeps
    the junior field.

    The junior title comes from the qualifying swim, so Senior Sweeper's three
    finals (and his own heats) must be invisible on the junior path: the junior
    digest must report Junior Jens, not him. Three events, so a junior clears
    MIN_TITLES.
    """
    mid, season, mdate = "JM2026", 2026, "2026-04-10"
    mname = "Junior Multi Champs 2026"
    events = [("M", 100, "Fri"), ("M", 200, "Fri"), ("M", 100, "Ryg")]
    meets = [dict(meet_id=mid, meet_name=mname, venue="Aarhus", course="LCM",
                  season=season, meet_date=mdate, category=["DM-L", "DMJ-L"])]
    obt, rid = [], 0

    def add(sid, name, club, by, gender, distance, stroke, points, rank, cs, phase):
        nonlocal rid
        rid += 1
        obt.append(_row(
            result_id=f"{mid}-{rid}", race_id=rid, meet_id=mid, rank=rank,
            name=name, swimmer_id=sid, club=club, birth_year=by,
            completed_time=_time(cs), completed_centiseconds=cs, points=points,
            points_fixed=points, season=season, meet_name=mname, meet_date=mdate,
            distance=distance, stroke=stroke, gender=gender, type=phase))

    for i, (g, d, st) in enumerate(events):
        add("sen1", "Senior Sweeper", "SENIORKLUB", 2000, g, d, st,
            900 - i, 1, 5000 + i, "Final")
        add("sen1", "Senior Sweeper", "SENIORKLUB", 2000, g, d, st,
            880 - i, 1, 5100 + i, "Heats")
        add("jun1", "Junior Jens", "AGF", season - 17, g, d, st,
            700 - i, 2, 5300 + i, "Heats")
        add("jun2", "Junior Jonas", "VEST", season - 17, g, d, st,
            650 - i, 3, 5400 + i, "Heats")

    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con
