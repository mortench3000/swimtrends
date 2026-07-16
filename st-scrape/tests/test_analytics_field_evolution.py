import duckdb

from analytics import loader
from tests.analytics_fixtures import build_curated

EVENT = dict(relay_count=1, gender="M", distance=200, stroke="Breast", course="LCM")


def _heats(n, season, cs_base):
    """n heat swims for one event/season at meet m1 (category DM-L)."""
    return [
        dict(result_id=f"{season}-{i}", swimmer_id=f"s{i}", rank=i + 1, type="Heats",
             completed_centiseconds=cs_base + i * 10, completed_time=f"t{i}",
             meet_id="m1", season=season, birth_year=2005, **EVENT)
        for i in range(n)
    ]


def _con(obt, meets):
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets)
    loader.create_views(con)
    return con


MEETS = [dict(meet_id="m1", season=2024, course="LCM", category=["DM-L"])]


def test_two_category_meet_pools_into_each_category():
    con = _con(
        obt=[dict(result_id="r1", swimmer_id="s1", rank=1, type="Final",
                  completed_centiseconds=15000, meet_id="m1", season=2024,
                  birth_year=2005, **EVENT)],
        meets=[dict(meet_id="m1", season=2024, course="LCM",
                    category=["DM-L", "DMJ-L"])],
    )
    cats = [r[0] for r in con.execute(
        "SELECT category FROM results_by_category WHERE result_id='r1' "
        "ORDER BY category").fetchall()]
    assert cats == ["DM-L", "DMJ-L"]


def test_final_cutline_is_eighth_fastest_heat_swim():
    # 10 heat swims; rank-8 fastest is the cut-line.
    con = _con(obt=_heats(10, 2024, 15000), meets=MEETS)
    row = con.execute(
        "SELECT cutline_centiseconds FROM final_cutline_by_season "
        "WHERE category='DM-L' AND season=2024").fetchone()
    assert row == (15000 + 7 * 10,)  # 8th fastest = index 7


def test_cutline_at_macro_supports_other_n():
    con = _con(obt=_heats(10, 2024, 15000), meets=MEETS)
    row = con.execute(
        "SELECT cutline_centiseconds FROM cutline_at(6) "
        "WHERE category='DM-L' AND season=2024").fetchone()
    assert row == (15000 + 5 * 10,)  # 6th fastest = index 5


def test_final_cutline_exposes_entrants_count():
    # 10 heat swims in the field -> entrants=10 alongside the rank-8 cut-line,
    # so an analyst can tell whether the cut-line is well-defined (entrants>=8).
    con = _con(obt=_heats(10, 2024, 15000), meets=MEETS)
    row = con.execute(
        "SELECT cutline_centiseconds, entrants FROM final_cutline_by_season "
        "WHERE category='DM-L' AND season=2024").fetchone()
    assert row == (15000 + 7 * 10, 10)


def test_cutline_at_macro_exposes_entrants_count():
    con = _con(obt=_heats(10, 2024, 15000), meets=MEETS)
    row = con.execute(
        "SELECT entrants FROM cutline_at(6) "
        "WHERE category='DM-L' AND season=2024").fetchone()
    assert row == (10,)


def test_swimmer_meets_lists_participation():
    con = _con(obt=_heats(10, 2024, 15000), meets=MEETS)
    rows = con.execute(
        "SELECT category, meet_id, swims FROM swimmer_meets "
        "WHERE swimmer_id='s0'").fetchall()
    assert rows == [("DM-L", "m1", 1)]


def test_medal_count_tallies_finals_podium_only():
    obt = [
        dict(result_id="r1", swimmer_id="s1", rank=1, type="Final",
             completed_centiseconds=15000, meet_id="m1", season=2024,
             birth_year=2005, **EVENT),
        dict(result_id="r2", swimmer_id="s1", rank=1, type="Heats",
             completed_centiseconds=15100, meet_id="m1", season=2024,
             birth_year=2005, **EVENT),  # heat win must NOT count as a medal
    ]
    con = _con(obt=obt, meets=MEETS)
    row = con.execute(
        "SELECT gold, silver, bronze, medals FROM medal_count "
        "WHERE swimmer_id='s1' AND category='DM-L'").fetchone()
    assert row == (1, 0, 0, 1)


def test_event_standard_by_season_best_and_count():
    con = _con(obt=_heats(10, 2024, 15000), meets=MEETS)
    row = con.execute(
        "SELECT swims, best_cs FROM event_standard_by_season "
        "WHERE category='DM-L' AND season=2024").fetchone()
    assert row == (10, 15000)


def test_event_standard_top3_and_top8_averages():
    # 10 swims at 15000,15010,...,15090. Mean of 3 fastest = 15010;
    # mean of 8 fastest = 15035.
    con = _con(obt=_heats(10, 2024, 15000), meets=MEETS)
    row = con.execute(
        "SELECT top3_avg_cs, top8_avg_cs FROM event_standard_by_season "
        "WHERE category='DM-L' AND season=2024").fetchone()
    assert row == (15010, 15035)
