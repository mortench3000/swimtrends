"""Authoritative open/para class for curated races.

Override-else-heuristic. The heuristic mirrors the raw zone's rule: a 'Timed
final' whose event name also appears as a Heats/Final in the same meet is a para
event (an able-bodied direct final has no prelim/final twin)."""


def authoritative_class(races, overrides):
    """races: list of dicts with race_id, name, type. overrides: {race_id: class}.
    Returns {race_id: 'open'|'para'}."""
    prelim_final_names = {r["name"] for r in races
                          if r.get("type") in ("Heats", "Final")}
    resolved = {}
    for r in races:
        rid = r["race_id"]
        if rid in overrides:
            resolved[rid] = overrides[rid]
            continue
        is_para = r.get("type") == "Timed final" and r.get("name") in prelim_final_names
        resolved[rid] = "para" if is_para else "open"
    return resolved
