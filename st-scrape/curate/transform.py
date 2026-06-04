"""Pure curated transform: parsed raw dicts -> {table_name: [row dicts]}."""
from curate import classify, model


def transform_meet(meet, races, results, base_times, overrides):
    """meet: dict. races/results: lists of dicts. base_times: lookup table.
    overrides: {race_id: 'open'|'para'}. Returns the five curated tables."""
    season, course = meet["season"], meet["course"]
    class_by_id = classify.authoritative_class(races, overrides)
    races_by_id = {r["race_id"]: r for r in races}

    fact_result = model.build_fact_result(
        results, races_by_id, class_by_id, base_times,
        meet_id=meet["meet_id"], season=season, course=course)

    return {
        "dim_meet": [model.build_dim_meet(meet)],
        "dim_race": model.build_dim_race(races, class_by_id, season=season, course=course),
        "fact_result": fact_result,
        "fact_split": model.build_fact_split(
            results, meet_id=meet["meet_id"], season=season, course=course),
        "obt_result": model.build_obt(fact_result, meet, races_by_id, class_by_id),
    }
