import duckdb

from analytics import loader
from tests.analytics_fixtures import build_curated

EVENT = dict(relay_count=1, type="Final", gender="M", distance=50,
             stroke="Free", course="LCM")


def _con(obt):
    con = duckdb.connect()
    build_curated(con, obt=obt)
    loader.create_views(con)
    return con


def test_club_leaderboard_counts_podiums_and_points():
    con = _con([
        dict(result_id="a", swimmer_id="s1", club="AC", rank=1, points=600,
             completed_centiseconds=2600, season=2024, birth_year=2008, **EVENT),
        dict(result_id="b", swimmer_id="s2", club="AC", rank=4, points=500,
             completed_centiseconds=2700, season=2024, birth_year=2008, **EVENT),
    ])
    row = con.execute(
        "SELECT swims, swimmers, podiums, total_points, best_points "
        "FROM club_leaderboard WHERE club='AC' AND season=2024").fetchone()
    assert row == (2, 2, 1, 1100, 600)


def test_age_group_ranking_buckets_and_ranks():
    con = _con([
        dict(result_id="a", swimmer_id="s1", rank=1, completed_centiseconds=2600,
             season=2024, birth_year=2010, **EVENT),  # age 14 -> 13-14
        dict(result_id="b", swimmer_id="s2", rank=1, completed_centiseconds=2500,
             season=2024, birth_year=2009, **EVENT),  # age 15 -> 15-16
    ])
    rows = con.execute(
        "SELECT swimmer_id, age_group, age_group_rank FROM age_group_ranking "
        "ORDER BY swimmer_id").fetchall()
    assert rows == [("s1", "13-14", 1), ("s2", "15-16", 1)]


def test_meet_summary_counts():
    con = _con([
        dict(result_id="a", race_id=1, swimmer_id="s1", meet_id="m1", meet_name="M1",
             rank=1, points=600, completed_centiseconds=2600, season=2024,
             birth_year=2008, **EVENT),
        dict(result_id="b", race_id=1, swimmer_id="s2", meet_id="m1", meet_name="M1",
             rank=2, points=580, completed_centiseconds=2650, season=2024,
             birth_year=2008, **EVENT),
    ])
    row = con.execute(
        "SELECT results, races, swimmers, top_points, top_points_swimmer "
        "FROM meet_summary WHERE meet_id='m1'").fetchone()
    assert row == (2, 1, 2, 600, "s1")


def test_meet_summary_standout_ignores_relay_entries():
    # A relay (swimmer_id NULL) holds the highest points; the standout swim must
    # still be the top individual swimmer, not the relay.
    con = _con([
        dict(result_id="a", race_id=1, swimmer_id="s1", meet_id="m1", meet_name="M1",
             rank=1, points=600, completed_centiseconds=2600, season=2024,
             birth_year=2008, **EVENT),
        dict(result_id="b", race_id=2, swimmer_id=None, meet_id="m1", meet_name="M1",
             rank=1, points=700, completed_centiseconds=10000, season=2024,
             relay_count=4, type="Final", gender="M", distance=200, stroke="Free",
             course="LCM"),
    ])
    row = con.execute(
        "SELECT results, swimmers, top_points, top_points_swimmer "
        "FROM meet_summary WHERE meet_id='m1'").fetchone()
    assert row == (2, 1, 600, "s1")
