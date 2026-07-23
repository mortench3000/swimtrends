"""Pure shaping + IO helpers for the web JSON build."""
import json
from pathlib import Path


def race_key(gender, distance, stroke, course, relay_count=1) -> str:
    """URL key for an event within a meet, e.g. M-100-Fri-LCM. Relays encode the
    leg count so a 4x100 (per-leg distance 100) does not collide with the
    individual 100, e.g. F-4x100-HM-LCM."""
    dist = f"{relay_count}x{distance}" if relay_count > 1 else str(distance)
    return f"{gender}-{dist}-{stroke}-{course}"


def write_json(path: Path, data) -> None:
    """Write UTF-8 JSON, Danish chars intact, deterministic ordering."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")
