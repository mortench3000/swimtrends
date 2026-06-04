"""run_curate_task: read raw -> transform -> write curated parquet -> notify.
All I/O injected; verifies object keys, overwrite-by-meet, and notification."""
import io

import pyarrow.parquet as pq

from curate import run

MEET = ('{"meet_id": 8609, "meet": "DM L 2021", "venue": "Aarhus", '
        '"course": "LCM", "season": 2021, "date": "08-07-2021", "category": ["DM-L"]}')
RACES = (
    '{"meet_id": 8609, "race_id": 1, "number": 1, "name": "100 Fri - Damer", '
    '"distance": 100, "stroke": "Fri", "gender": "F", "relay_count": 1, '
    '"type": "Final", "class": "open"}\n'
)
RESULTS = (
    '{"race_id": 1, "Rank": 1, "Name": "A", "Swimmer_id": "7", '
    '"completed_time": "1:00.00", "completed_centiseconds": 6000, "splits": []}\n'
)
BASE_TIMES = ('{"season": 2021, "course": "LCM", "gender": "F", "relay_count": 1, '
              '"distance": 100, "stroke": "FREE", "basetime_in_sec": 60.0}\n')


def test_run_writes_all_five_tables_and_notifies():
    raw = {
        "raw/meet=8609/meet_info.jsonl": MEET,
        "raw/meet=8609/races.jsonl": RACES,
        "raw/meet=8609/results.jsonl": RESULTS,
        "reference/point_base_times.jsonl": BASE_TIMES,
    }
    written, notes = {}, []

    run.run_curate_task(
        meet_id="8609",
        read_text=lambda key: raw[key],
        get_overrides=lambda mid: {},
        write_bytes=lambda key, data: written.__setitem__(key, data),
        notify=lambda subject, msg: notes.append(subject),
    )

    assert set(written) == {
        "curated/dim_meet/season=2021/course=LCM/meet=8609.parquet",
        "curated/dim_race/season=2021/course=LCM/meet=8609.parquet",
        "curated/fact_result/season=2021/course=LCM/meet=8609.parquet",
        "curated/fact_split/season=2021/course=LCM/meet=8609.parquet",
        "curated/obt_result/season=2021/course=LCM/meet=8609.parquet",
    }
    fr = pq.read_table(io.BytesIO(
        written["curated/fact_result/season=2021/course=LCM/meet=8609.parquet"]))
    assert fr.to_pylist()[0]["points"] == 1000
    assert any("curat" in s.lower() for s in notes)
