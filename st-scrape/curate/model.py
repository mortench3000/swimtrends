"""Build curated table rows from raw meet/race/result dicts.

result_id is race-local ordinal (f"{race_id}-{i}"), NOT Rank: disqualified swims
share Rank=-1 and would collide. Raw file order is deterministic, so ordinals are
stable across re-runs."""
from curate import points as points_mod


def build_dim_meet(meet):
    return {
        "meet_id": str(meet["meet_id"]),
        "meet_name": meet.get("meet", ""),
        "venue": meet.get("venue", ""),
        "course": meet["course"],
        "season": meet["season"],
        "meet_date": meet.get("date", ""),
        "category": list(meet.get("category", [])),
    }


def build_dim_race(races, class_by_id, *, season, course):
    rows = []
    for r in races:
        rows.append({
            "race_id": r["race_id"],
            "meet_id": str(r["meet_id"]),
            "number": r.get("number"),
            "name": r["name"],
            "distance": r["distance"],
            "stroke": r["stroke"],
            "gender": r["gender"],
            "relay_count": r["relay_count"],
            "type": r["type"],
            "class": class_by_id[r["race_id"]],
            "season": season,
            "course": course,
        })
    return rows


def _result_ids(results):
    """Assign race-local ordinal ids in raw file order."""
    counters, ids = {}, []
    for r in results:
        rid = r["race_id"]
        i = counters.get(rid, 0)
        ids.append(f"{rid}-{i}")
        counters[rid] = i + 1
    return ids


def build_fact_result(results, races_by_id, class_by_id, base_times, *,
                      meet_id, season, course):
    ids = _result_ids(results)
    rows = []
    for result_id, r in zip(ids, results):
        race = races_by_id.get(r["race_id"])
        cs = r.get("completed_centiseconds")
        if race is None:
            p = pf = None
        else:
            p, pf = points_mod.score_result(
                base_times, season, course, race,
                klass=class_by_id.get(r["race_id"], "open"),
                completed_centiseconds=cs, rank=r.get("Rank"))
        rows.append({
            "result_id": result_id,
            "race_id": r["race_id"],
            "meet_id": str(meet_id),
            "rank": r.get("Rank"),
            "name": r.get("Name", ""),
            "swimmer_id": r.get("Swimmer_id"),
            "nationality": r.get("nationality"),
            "club": r.get("club"),
            "birth_year": r.get("birth_year"),
            "completed_time": r.get("completed_time"),
            "completed_centiseconds": cs,
            "points": p,
            "points_fixed": pf,
            "season": season,
            "course": course,
        })
    return rows


def build_fact_split(results, *, meet_id, season, course):
    ids = _result_ids(results)
    rows = []
    for result_id, r in zip(ids, results):
        for s in r.get("splits", []):
            rows.append({
                "result_id": result_id,
                "race_id": r["race_id"],
                "distance": s.get("distance"),
                "split_time": s.get("split_time"),
                "split_centiseconds": s.get("split_centiseconds"),
                "cumulative_time": s.get("cumulative_time"),
                "cumulative_centiseconds": s.get("cumulative_centiseconds"),
                "season": season,
                "course": course,
            })
    return rows


def build_obt(fact_result_rows, meet, races_by_id, class_by_id):
    rows = []
    for fr in fact_result_rows:
        race = races_by_id.get(fr["race_id"], {})
        row = dict(fr)
        row.update({
            "meet_name": meet.get("meet", ""),
            "venue": meet.get("venue", ""),
            "meet_date": meet.get("date", ""),
            "number": race.get("number"),
            "race_name": race.get("name"),
            "distance": race.get("distance"),
            "stroke": race.get("stroke"),
            "gender": race.get("gender"),
            "relay_count": race.get("relay_count"),
            "type": race.get("type"),
            "class": class_by_id.get(fr["race_id"], "open"),
        })
        rows.append(row)
    return rows
