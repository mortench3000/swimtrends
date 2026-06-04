"""World Aquatics points (pure). Ported from calc_points.py.

points = trunc(1000 * (basetime / swimtime) ** 3).
Two scores per result:
  points        - vs the meet's OWN season base times (era-relative).
  points_fixed  - vs FIXED_REF_SEASON (one stationary cross-era scale).
"""
import math

FIXED_REF_SEASON = 2026

# Danish scraper stroke codes -> base-time stroke codes. IM (individual medley)
# and HM (holdmedley / team medley relay) both map to MEDLEY.
STROKE_MAP = {"Fri": "FREE", "Ryg": "BACK", "Bryst": "BREAST", "Fly": "FLY",
              "IM": "MEDLEY", "HM": "MEDLEY"}


def calculate_points(basetime_sec, swimtime_sec):
    """WA points, truncated to an integer."""
    return math.trunc(1000 * math.pow(basetime_sec / swimtime_sec, 3))


def points_for(table, season, course, race, swimtime_sec):
    """Look up the base time for this race+season and score it, or None."""
    stroke = STROKE_MAP.get(race.get("stroke"))
    if stroke is None:
        return None
    base = table.get((season, course, race["gender"], race["relay_count"],
                      race["distance"], stroke))
    if base is None:
        return None
    return calculate_points(base, swimtime_sec)


def score_result(table, season, course, race, *, klass,
                 completed_centiseconds, rank):
    """Return (points, points_fixed). Para, DQ (rank -1), and missing-time
    results are never scored."""
    if klass == "para" or completed_centiseconds is None or rank == -1:
        return (None, None)
    t = completed_centiseconds / 100.0
    return (points_for(table, season, course, race, t),
            points_for(table, FIXED_REF_SEASON, course, race, t))
