import duckdb

from analytics import loader
from tests.analytics_fixtures import build_curated

EVENT = dict(relay_count=1, type="Final", gender="M", distance=200,
             stroke="Breast", course="LCM")


def _con(obt):
    con = duckdb.connect()
    build_curated(con, obt=obt)
    loader.create_views(con)
    return con


def test_personal_best_picks_fastest_swim():
    con = _con([
        dict(result_id="a", swimmer_id="s1", rank=2, completed_centiseconds=15000,
             completed_time="2:30.00", points=600, meet_name="M1", meet_date="2024-03-01",
             season=2024, birth_year=2008, **EVENT),
        dict(result_id="b", swimmer_id="s1", rank=1, completed_centiseconds=14800,
             completed_time="2:28.00", points=620, meet_name="M2", meet_date="2024-05-01",
             season=2024, birth_year=2008, **EVENT),
    ])
    row = con.execute(
        "SELECT best_centiseconds, best_time, meet_name FROM personal_best "
        "WHERE swimmer_id = 's1'").fetchone()
    assert row == (14800, "2:28.00", "M2")


def test_event_leaderboard_ranks_by_points_desc():
    con = _con([
        dict(result_id="a", swimmer_id="s1", rank=1, completed_centiseconds=14800,
             points=620, season=2024, birth_year=2008, **EVENT),
        dict(result_id="b", swimmer_id="s2", rank=2, completed_centiseconds=15000,
             points=600, season=2024, birth_year=2007, **EVENT),
    ])
    rows = con.execute(
        "SELECT swimmer_id, points_rank FROM event_leaderboard ORDER BY points_rank"
    ).fetchall()
    assert rows == [("s1", 1), ("s2", 2)]
