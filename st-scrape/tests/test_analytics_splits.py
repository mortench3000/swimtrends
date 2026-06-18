import duckdb

from analytics import loader
from tests.analytics_fixtures import build_curated

EVENT = dict(relay_count=1, type="Final", gender="M", distance=100,
             stroke="Free", course="LCM")


def test_pacing_flags_negative_split():
    con = duckdb.connect()
    build_curated(
        con,
        obt=[dict(result_id="r1", swimmer_id="s1", rank=1, completed_centiseconds=5800,
                  season=2024, birth_year=2008, **EVENT)],
        # 4 laps; second half (laps 3-4) faster than first half (laps 1-2).
        splits=[
            dict(result_id="r1", race_id=1, distance=25, split_centiseconds=1500,
                 cumulative_centiseconds=1500),
            dict(result_id="r1", race_id=1, distance=50, split_centiseconds=1500,
                 cumulative_centiseconds=3000),
            dict(result_id="r1", race_id=1, distance=75, split_centiseconds=1400,
                 cumulative_centiseconds=4400),
            dict(result_id="r1", race_id=1, distance=100, split_centiseconds=1400,
                 cumulative_centiseconds=5800),
        ],
    )
    loader.create_views(con)
    row = con.execute(
        "SELECT first_half_cs, second_half_cs, back_half_delta_cs, negative_split "
        "FROM pacing WHERE result_id='r1'").fetchone()
    assert row == (3000, 2800, -200, True)
