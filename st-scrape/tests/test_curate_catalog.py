"""Glue table input is derived from the same schema, partitioned by season/course."""
from curate import catalog


def test_table_input_has_partition_keys_and_columns():
    ti = catalog.table_input("fact_result", "s3://bucket/curated/fact_result/")
    assert ti["Name"] == "fact_result"
    part_keys = [c["Name"] for c in ti["PartitionKeys"]]
    assert part_keys == ["season", "course"]
    col_names = [c["Name"] for c in ti["StorageDescriptor"]["Columns"]]
    # Partition columns must NOT also appear in Columns (Glue rejects overlap).
    assert "season" not in col_names and "course" not in col_names
    assert "result_id" in col_names and "points" in col_names
    assert ti["StorageDescriptor"]["Location"] == "s3://bucket/curated/fact_result/"


def test_all_five_tables_supported():
    for name in ["dim_meet", "dim_race", "fact_result", "fact_split", "obt_result"]:
        ti = catalog.table_input(name, f"s3://bucket/curated/{name}/")
        assert ti["Name"] == name
