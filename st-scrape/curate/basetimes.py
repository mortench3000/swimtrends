"""Load the WA base-times reference into the lookup the points module uses.

Keyed (season, course, gender, relay_count, distance, stroke) -> seconds."""
import json


def parse(jsonl_text):
    table = {}
    for line in jsonl_text.splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        table[(r["season"], r["course"], r["gender"], r["relay_count"],
               r["distance"], r["stroke"])] = r["basetime_in_sec"]
    return table
