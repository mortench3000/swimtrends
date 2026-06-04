"""Parquet schemas + writer + S3 object keys for the curated zone.

Explicit pyarrow schemas (not inferred) so an empty meet still writes a
well-typed file and the Glue catalog stays stable."""
import io

import pyarrow as pa
import pyarrow.parquet as pq

_S = pa.string()
_I = pa.int64()

SCHEMAS = {
    "dim_meet": pa.schema([
        ("meet_id", _S), ("meet_name", _S), ("venue", _S), ("course", _S),
        ("season", _I), ("meet_date", _S), ("category", pa.list_(_S)),
    ]),
    "dim_race": pa.schema([
        ("race_id", _I), ("meet_id", _S), ("number", _I), ("name", _S),
        ("distance", _I), ("stroke", _S), ("gender", _S), ("relay_count", _I),
        ("type", _S), ("class", _S), ("season", _I), ("course", _S),
    ]),
    "fact_result": pa.schema([
        ("result_id", _S), ("race_id", _I), ("meet_id", _S), ("rank", _I),
        ("name", _S), ("swimmer_id", _S), ("nationality", _S), ("club", _S),
        ("birth_year", _I), ("completed_time", _S), ("completed_centiseconds", _I),
        ("points", _I), ("points_fixed", _I), ("season", _I), ("course", _S),
    ]),
    "fact_split": pa.schema([
        ("result_id", _S), ("race_id", _I), ("distance", _I), ("split_time", _S),
        ("split_centiseconds", _I), ("cumulative_time", _S),
        ("cumulative_centiseconds", _I), ("season", _I), ("course", _S),
    ]),
    "obt_result": pa.schema([
        ("result_id", _S), ("race_id", _I), ("meet_id", _S), ("rank", _I),
        ("name", _S), ("swimmer_id", _S), ("nationality", _S), ("club", _S),
        ("birth_year", _I), ("completed_time", _S), ("completed_centiseconds", _I),
        ("points", _I), ("points_fixed", _I), ("season", _I), ("course", _S),
        ("meet_name", _S), ("venue", _S), ("meet_date", _S), ("number", _I),
        ("race_name", _S), ("distance", _I), ("stroke", _S), ("gender", _S),
        ("relay_count", _I), ("type", _S), ("class", _S),
    ]),
}


def object_key(table, *, season, course, meet_id):
    return (f"curated/{table}/season={season}/course={course}/"
            f"meet={meet_id}.parquet")


def write_parquet_bytes(table, rows):
    """Serialize rows to Snappy Parquet bytes using the table's fixed schema.
    Missing keys become nulls; extra keys are ignored."""
    schema = SCHEMAS[table]
    columns = {name: [row.get(name) for row in rows] for name in schema.names}
    arrays = [pa.array(columns[name], type=field.type)
              for name, field in zip(schema.names, schema)]
    arrow_table = pa.table(arrays, schema=schema)
    buf = io.BytesIO()
    pq.write_table(arrow_table, buf, compression="snappy")
    return buf.getvalue()
