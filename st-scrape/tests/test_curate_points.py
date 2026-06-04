"""WA points: formula, stroke mapping, scorability, season vs fixed reference."""
from curate import points


def _table():
    # (season, course, gender, relay_count, distance, stroke) -> basetime_sec
    return {
        (2022, "LCM", "F", 1, 100, "FREE"): 51.71,
        (2026, "LCM", "F", 1, 100, "FREE"): 50.00,
    }


def test_formula_truncates():
    # 1000 * (51.71/51.71)**3 == 1000 exactly.
    assert points.calculate_points(51.71, 51.71) == 1000
    # Slower swim scores < 1000.
    assert points.calculate_points(51.71, 60.00) == 640


def test_stroke_mapping_im_and_holdmedley_to_medley():
    assert points.STROKE_MAP["IM"] == "MEDLEY"
    assert points.STROKE_MAP["HM"] == "MEDLEY"
    assert points.STROKE_MAP["Fri"] == "FREE"


def test_points_for_uses_season_and_fixed_reference():
    table = _table()
    race = {"gender": "F", "relay_count": 1, "distance": 100, "stroke": "Fri"}
    # season 2022 base 51.71 vs a 52.00 swim.
    assert points.points_for(table, 2022, "LCM", race, 52.00) == 983
    # fixed reference season 2026 base 50.00 vs the same swim.
    assert points.points_for(table, 2026, "LCM", race, 52.00) == 888


def test_points_for_returns_none_when_no_base_time():
    table = _table()
    race = {"gender": "M", "relay_count": 1, "distance": 100, "stroke": "Fri"}
    assert points.points_for(table, 2022, "LCM", race, 50.0) is None


def test_score_result_skips_dq_and_para_and_missing_time():
    table = _table()
    race = {"gender": "F", "relay_count": 1, "distance": 100, "stroke": "Fri"}
    # Normal scorable swim (open).
    p, pf = points.score_result(table, 2022, "LCM", race, klass="open",
                                completed_centiseconds=5200, rank=1)
    assert (p, pf) == (983, 888)
    # DQ (rank -1) -> not scored.
    assert points.score_result(table, 2022, "LCM", race, klass="open",
                               completed_centiseconds=5200, rank=-1) == (None, None)
    # Missing time -> not scored.
    assert points.score_result(table, 2022, "LCM", race, klass="open",
                               completed_centiseconds=None, rank=1) == (None, None)
    # Para -> never scored even with a valid time.
    assert points.score_result(table, 2022, "LCM", race, klass="para",
                               completed_centiseconds=5200, rank=1) == (None, None)
