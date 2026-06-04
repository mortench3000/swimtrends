"""Enrich db/<meet>_results.jsonl with World Aquatics points.

Two values are added per result:

  points        - season-relative: scored against the meet's OWN season base
                  times. Answers "how world-class for its era". null when that
                  season+course+event has no base time.
  points_fixed  - scored against a single fixed reference season
                  (FIXED_REF_SEASON). One stationary scale across all years,
                  so it is directly comparable across eras - the metric for
                  long-term trend analysis. null only when the event itself has
                  no base time in the reference season.

Formula (World Aquatics): points = trunc(1000 * (basetime / swimtime) ** 3).

Usage:
    python calc_points.py             # enrich every db/*_results.jsonl in place
    python calc_points.py 11712 12484 # only these meets
"""
import argparse
import glob
import json
import math
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(SCRIPT_DIR, 'db')
BASE_TIMES = os.path.join(DB_DIR, 'point_base_times.jsonl')

# Fixed reference season for points_fixed (the cross-era trend metric).
FIXED_REF_SEASON = 2026

# Scraper stroke codes (Danish) -> base-time stroke codes. Both the individual
# medley (IM) and the team medley relay (HM, 'holdmedley') map to MEDLEY.
STROKE_MAP = {'Fri': 'FREE', 'Ryg': 'BACK', 'Bryst': 'BREAST', 'Fly': 'FLY',
              'IM': 'MEDLEY', 'HM': 'MEDLEY'}

# Canonical result field order, with the two points fields placed right after
# the numeric time and before the (large) nested splits list.
RESULT_ORDER = ['race_id', 'Rank', 'Name', 'Swimmer_id', 'nationality', 'club',
                'birth_year', 'completed_time', 'completed_centiseconds',
                'points', 'points_fixed', 'splits']


def load_base_times(path):
    """Return {(season, course, gender, relay_count, distance, stroke): basetime_sec}."""
    table = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            table[(r['season'], r['course'], r['gender'], r['relay_count'],
                   r['distance'], r['stroke'])] = r['basetime_in_sec']
    return table


def calculate_points(basetime_sec, swimtime_sec):
    """World Aquatics points, truncated to an integer."""
    return math.trunc(1000 * math.pow(basetime_sec / swimtime_sec, 3))


def points_for(table, season, course, race, swimtime_sec):
    """Look up the base time for this race+season and score it, or None."""
    stroke = STROKE_MAP.get(race.get('stroke'))
    if stroke is None:
        return None
    base = table.get((season, course, race['gender'], race['relay_count'],
                      race['distance'], stroke))
    if base is None:
        return None
    return calculate_points(base, swimtime_sec)


def enrich_meet(meet_id, table):
    meet = json.loads(open(os.path.join(DB_DIR, f'{meet_id}_meet_info.jsonl'), encoding='utf-8').read())
    season, course = meet['season'], meet['course']
    races = {}
    with open(os.path.join(DB_DIR, f'{meet_id}_races.jsonl'), encoding='utf-8') as f:
        for line in f:
            ra = json.loads(line)
            races[ra['race_id']] = ra

    results_path = os.path.join(DB_DIR, f'{meet_id}_results.jsonl')
    rows = [json.loads(line) for line in open(results_path, encoding='utf-8')]

    n_points = n_fixed = 0
    for r in rows:
        race = races.get(r['race_id'])
        cs = r.get('completed_centiseconds')
        # Only score real swims: a finite time and not disqualified (rank -1).
        scorable = race is not None and cs is not None and r.get('Rank') != -1
        points = points_fixed = None
        if scorable:
            t = cs / 100.0
            points = points_for(table, season, course, race, t)
            points_fixed = points_for(table, FIXED_REF_SEASON, course, race, t)
        r['points'] = points
        r['points_fixed'] = points_fixed
        n_points += points is not None
        n_fixed += points_fixed is not None

    # Rewrite with points fields in canonical order (extras preserved at end).
    with open(results_path, 'w', encoding='utf-8') as f:
        for r in rows:
            ordered = {k: r[k] for k in RESULT_ORDER if k in r}
            ordered.update({k: v for k, v in r.items() if k not in RESULT_ORDER})
            json.dump(ordered, f, ensure_ascii=False)
            f.write('\n')

    total = len(rows)
    print(f"  {meet_id} (season {season} {course}): {total} results | "
          f"points {n_points} ({100*n_points//total if total else 0}%) | "
          f"points_fixed {n_fixed} ({100*n_fixed//total if total else 0}%)")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Add WA points to scraped results.')
    parser.add_argument('meet_ids', nargs='*', help='Meet IDs to enrich (default: all in db/).')
    args = parser.parse_args()

    table = load_base_times(BASE_TIMES)
    if args.meet_ids:
        meet_ids = args.meet_ids
    else:
        meet_ids = sorted(os.path.basename(p).split('_')[0]
                          for p in glob.glob(os.path.join(DB_DIR, '*_results.jsonl')))

    print(f"Scoring with {len(table)} base times (fixed reference season = {FIXED_REF_SEASON}):")
    for meet_id in meet_ids:
        enrich_meet(meet_id, table)
