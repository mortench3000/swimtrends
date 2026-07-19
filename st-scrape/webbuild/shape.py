"""Pure shaping + IO helpers for the web JSON build."""
import json
from pathlib import Path


def race_key(gender, distance, stroke, course) -> str:
    """URL key for an event within a meet, e.g. M-100-Fri-LCM."""
    return f"{gender}-{distance}-{stroke}-{course}"


def write_json(path: Path, data) -> None:
    """Write UTF-8 JSON, Danish chars intact, deterministic ordering."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")
