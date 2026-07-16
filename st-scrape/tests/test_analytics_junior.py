"""Junior identification: the `is_junior` flag and the `junior_championship`
standings view.

Junior = competition-season age 16-18 (birth years season-18 .. season-16),
a floor AND a ceiling. The junior title is decided from the QUALIFYING swim
(clean junior heats, or the timed final for 800/1500) -- never the senior
final, which most juniors never reach. See docs/analytics.md.
"""
import duckdb

from analytics import loader
from tests.analytics_fixtures import build_curated

EVENT = dict(relay_count=1, distance=100, stroke="Fly", course="LCM", gender="M")


def _row(rid, *, swimmer, cs, type_, season=2026, birth_year=2008, meet="m1",
         klass="open", rank=1, gender="M", distance=100, stroke="Fly"):
    e = dict(EVENT); e.update(gender=gender, distance=distance, stroke=stroke)
    return dict(result_id=rid, swimmer_id=swimmer, name=swimmer, club="C",
                rank=rank, type=type_, completed_centiseconds=cs,
                completed_time=str(cs), meet_id=meet, season=season,
                birth_year=birth_year, **{"class": klass}, **e)


DMJL = [dict(meet_id="m1", season=2026, course="LCM", category=["DM-L", "DMJ-L"])]


def _con(obt, meets=DMJL):
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets)
    loader.create_views(con)
    return con


# --- is_junior band ------------------------------------------------------
def test_is_junior_true_for_ages_16_to_18_false_outside():
    con = _con([
        _row("a", swimmer="s16", cs=6000, type_="Heats", birth_year=2010),  # age 16
        _row("b", swimmer="s18", cs=6000, type_="Heats", birth_year=2008),  # age 18
        _row("c", swimmer="s15", cs=6000, type_="Heats", birth_year=2011),  # age 15
        _row("d", swimmer="s19", cs=6000, type_="Heats", birth_year=2007),  # age 19
    ])
    got = dict(con.execute(
        "SELECT result_id, is_junior FROM results ORDER BY result_id").fetchall())
    assert got == {"a": True, "b": True, "c": False, "d": False}


# --- junior_championship standings ---------------------------------------
def test_ranks_juniors_by_qualifying_heat_not_senior_final():
    con = _con([
        # Junior A: heat 56.00 AND a faster senior-final 55.50 -> view must use the heat.
        _row("a_h", swimmer="A", cs=5600, type_="Heats", birth_year=2008),
        _row("a_f", swimmer="A", cs=5550, type_="Final", birth_year=2008),
        # Juniors B, C: heats only (never reached the senior final).
        _row("b_h", swimmer="B", cs=5700, type_="Heats", birth_year=2009),
        _row("c_h", swimmer="C", cs=5800, type_="Heats", birth_year=2010),
        # A senior with the fastest heat -> must NOT enter junior standings.
        _row("x_h", swimmer="X", cs=5000, type_="Heats", birth_year=2006),
    ])
    rows = con.execute(
        "SELECT swimmer_id, junior_rank, completed_centiseconds "
        "FROM junior_championship ORDER BY junior_rank").fetchall()
    assert rows == [("A", 1, 5600), ("B", 2, 5700), ("C", 3, 5800)]


def test_distance_events_use_timed_final():
    # 800m is a timed final (no heats); juniors are still ranked from it.
    con = _con([
        _row("p", swimmer="P", cs=90000, type_="Timed final", distance=800, birth_year=2008),
        _row("q", swimmer="Q", cs=91000, type_="Timed final", distance=800, birth_year=2009),
    ])
    rows = con.execute(
        "SELECT swimmer_id, junior_rank FROM junior_championship "
        "WHERE distance=800 ORDER BY junior_rank").fetchall()
    assert rows == [("P", 1), ("Q", 2)]


def test_excludes_para_dsq_and_non_dmjl_meets():
    con = _con(
        obt=[
            _row("para", swimmer="Pa", cs=5500, type_="Heats", birth_year=2008, klass="para"),
            _row("dsq", swimmer="Dq", cs=5500, type_="Heats", birth_year=2008, rank=-1),
            _row("other", swimmer="Ot", cs=5500, type_="Heats", birth_year=2008, meet="m2"),
        ],
        meets=DMJL + [dict(meet_id="m2", season=2026, course="LCM", category=["DM-L"])],
    )
    ids = [r[0] for r in con.execute(
        "SELECT swimmer_id FROM junior_championship").fetchall()]
    assert ids == []  # para, DSQ, and the DM-L-only meet all excluded
