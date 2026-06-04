"""Glue Data Catalog table definitions derived from the Parquet schemas.

season/course are partition keys (encoded in the S3 path), so they are declared
as PartitionKeys and excluded from the regular column list."""
import pyarrow as pa

from curate import parquet

PARTITION_COLS = ("season", "course")

_ARROW_TO_GLUE = {pa.string(): "string", pa.int64(): "bigint"}


def _glue_type(arrow_type):
    if pa.types.is_list(arrow_type):
        inner = _ARROW_TO_GLUE[arrow_type.value_type]
        return f"array<{inner}>"
    return _ARROW_TO_GLUE[arrow_type]


def table_input(table, location):
    """Return a Glue CreateTable 'TableInput' dict for one curated table."""
    schema = parquet.SCHEMAS[table]
    columns = [{"Name": f.name, "Type": _glue_type(f.type)}
               for f in schema if f.name not in PARTITION_COLS]
    return {
        "Name": table,
        "TableType": "EXTERNAL_TABLE",
        "Parameters": {"classification": "parquet", "EXTERNAL": "TRUE"},
        "PartitionKeys": [
            {"Name": "season", "Type": "bigint"},
            {"Name": "course", "Type": "string"},
        ],
        "StorageDescriptor": {
            "Columns": columns,
            "Location": location,
            "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
            "SerdeInfo": {
                "SerializationLibrary":
                    "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
            },
        },
    }
