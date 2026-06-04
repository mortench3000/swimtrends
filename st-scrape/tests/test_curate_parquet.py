"""Parquet writer: round-trips rows, handles nulls, and builds partition paths."""
import io

import pyarrow.parquet as pq

from curate import parquet


def test_partition_path_per_meet():
    assert parquet.object_key("fact_result", season=2021, course="LCM", meet_id="8609") == \
        "curated/fact_result/season=2021/course=LCM/meet=8609.parquet"


def test_write_round_trips_with_nulls():
    rows = [
        {"result_id": "1-0", "points": 1000, "points_fixed": None,
         "season": 2021, "course": "LCM"},
        {"result_id": "1-1", "points": None, "points_fixed": None,
         "season": 2021, "course": "LCM"},
    ]
    data = parquet.write_parquet_bytes("fact_result", rows)
    table = pq.read_table(io.BytesIO(data))
    out = table.to_pylist()
    assert out[0]["result_id"] == "1-0" and out[0]["points"] == 1000
    assert out[1]["points"] is None


def test_empty_rows_still_writes_valid_schema():
    data = parquet.write_parquet_bytes("fact_split", [])
    table = pq.read_table(io.BytesIO(data))
    assert table.num_rows == 0
    assert "result_id" in table.schema.names
