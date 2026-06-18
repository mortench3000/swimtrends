import duckdb

from analytics import loader
from tests.analytics_fixtures import build_curated

EVENT = dict(relay_count=1, type="Final", gender="F", distance=100,
             stroke="Free", course="LCM")


def _con(obt):
    con = duckdb.connect()
    build_curated(con, obt=obt)
    loader.create_views(con)
    return con


def test_swimmer_progression_delta_vs_previous_swim():
    con = _con([
        dict(result_id="a", swimmer_id="s1", rank=1, completed_centiseconds=6000,
             points=600, meet_date="2024-03-01", season=2024, birth_year=2010, **EVENT),
        dict(result_id="b", swimmer_id="s1", rank=1, completed_centiseconds=5900,
             points=620, meet_date="2024-06-01", season=2024, birth_year=2010, **EVENT),
    ])
    rows = con.execute(
        "SELECT meet_date, delta_centiseconds FROM swimmer_progression "
        "WHERE swimmer_id='s1' ORDER BY meet_date").fetchall()
    assert rows == [("2024-03-01", None), ("2024-06-01", -100)]


def test_cross_era_best_ranks_by_points_fixed():
    con = _con([
        dict(result_id="a", swimmer_id="s1", rank=1, completed_centiseconds=5900,
             points=620, points_fixed=700, season=2024, birth_year=2010, **EVENT),
        dict(result_id="b", swimmer_id="s2", rank=1, completed_centiseconds=5950,
             points=610, points_fixed=720, season=2020, birth_year=2006, **EVENT),
    ])
    rows = con.execute(
        "SELECT swimmer_id, era_rank FROM cross_era_best ORDER BY era_rank").fetchall()
    assert rows == [("s2", 1), ("s1", 2)]  # s2 wins on points_fixed despite slower time


def test_biggest_improvers_season_over_season():
    con = _con([
        dict(result_id="a", swimmer_id="s1", rank=1, completed_centiseconds=6200,
             points=560, season=2023, birth_year=2010, **EVENT),
        dict(result_id="b", swimmer_id="s1", rank=1, completed_centiseconds=6000,
             points=600, season=2024, birth_year=2010, **EVENT),
    ])
    row = con.execute(
        "SELECT season, improvement_centiseconds, improvement_points "
        "FROM biggest_improvers WHERE swimmer_id='s1'").fetchone()
    assert row == (2024, 200, 40)  # 200cs faster, +40 points vs 2023
