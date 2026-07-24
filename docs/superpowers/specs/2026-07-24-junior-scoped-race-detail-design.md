# Junior-scoped race detail for combined DMJ-L meets

**Date:** 2026-07-24
**Status:** Design — ready for implementation planning

## Problem

A meet held as a combined senior + junior championship is tagged with both
categories in its scraped `meet_info` — e.g. meet 12486 has
`"category": ["DM-L", "DMJ-L"]`. The curated view `results_by_category`
(`analytics/views/50_field_evolution.sql`) explodes such a meet to one row per
category via `CROSS JOIN UNNEST(m.category)`, so for a combined meet the `DM-L`
and `DMJ-L` rows are the *same underlying swims*.

The web build (`st-scrape/webbuild/build.py` → `queries.py:build_race`) emits a
per-race JSON file per category, but the DMJ-L branch applies **no junior
filter**. Its podium comes from `_PODIUM_SQL` (senior final, `rank IN (1,2,3)`)
and its stat tiles from `_RACE_FACTS_SQL` (the whole `class='open'` field). For a
combined meet those resolve identically to the DM-L page — the DMJ-L race page is
a byte-for-byte duplicate of the senior page except the season-trend charts,
which differ only incidentally (the historical *meet population* per category
differs across seasons, not because anything is junior-filtered).

Observed: `https://swimtrends.dk/#/c/DMJ-L/m/12486/r/M-200-Bryst-LCM` shows the
senior final podium and senior field stats, not the junior championship.

The domain rule already exists in `analytics/views/60_junior.sql`
(`junior_championship`): the junior title is decided from the **qualifying swim**
(heats, or the timed final for 800/1500), not the senior final — because at a
combined meet a junior may never reach the senior final. That view is currently
**unused by webbuild**, so the true junior standings never reach the web app.

## Scope

Fix the **combined DMJ-L** race page only. Three categories of DMJ-L/DMJ-K meet
exist; only one is broken:

| Meet shape | Current behaviour | Action |
| --- | --- | --- |
| **DMJ-K** (short course) | Junior-only; never combined with a senior category. Whole field is juniors, real junior final → medals from the final. | **Unchanged.** |
| **DMJ-L, non-combined** | Junior-only; real junior final → medals from the final. Graphs meaningful as-is. | **Unchanged.** |
| **DMJ-L, combined** (also tagged a senior category) | No separate junior final; junior title comes from the qualifying swim. Currently shows senior data. | **Junior-scope** podium, tiles, graphs. |

The trigger is **combined-ness**, not the category string. This aligns with why
`junior_championship` uses the qualifying swim in the first place: it exists to
handle combined meets. Non-combined junior meets already render correctly and
must stay untouched (the user explicitly wants all graphs kept for those).

### Out of scope

- **DMJ-K junior scoping.** `junior_championship` is hardcoded to
  `category = 'DMJ-L'`. DMJ-K is never combined with a senior category, so its
  page is already correct and needs no change. A future short-course combined
  junior championship would require generalising the view; not now.
- Any change to DM-L, relays, or non-combined junior pages.

## Detection: is a meet combined?

In `build_race`, the meet is **combined** when its `dim_meet.category` list
contains a tag that is not a junior category:

```sql
SELECT category FROM cur_dim_meet WHERE meet_id = ?
```

`cur_dim_meet.category` is the raw list (`curate/model.py:17`,
`"category": list(meet.get("category", []))`). Combined =
`any(not c.startswith("DMJ") for c in category_list)`. The junior path fires
only when `category == 'DMJ-L'` **and** the meet is combined.

## Behaviour on a combined DMJ-L race page

Single source of truth: the `junior_championship` view. Podium, tiles, and graphs
all derive from juniors' qualifying swims — internally coherent.

### Podium

Source from `junior_championship`, `junior_rank IN (1, 2, 3)`, ordered by
`junior_rank`. Return the same shape the `<Podium>` component already consumes:
`{rank, name, swimmer_id, club, time, points}` with `rank = junior_rank` and
`time = completed_time`, `points` taken straight from the view (already computed
with the meet's base times — no recompute).

If fewer than 3 juniors swam the event, return whatever exists (1 or 2 rows).
`<Podium>` positions by rank, so a partial podium renders naturally — no padding.

### Stat tiles

Computed over the junior field (juniors' qualifying swims, i.e. the
`junior_championship` rows for the event):

| Tile | Combined DMJ-L value |
| --- | --- |
| Deltagere (contestants) | distinct juniors |
| Vindertid (winning_time) | junior gold (`junior_rank = 1`) |
| winner_points | junior gold points |
| Median | median of junior qualifying times |
| Spredning 1.–sidste (spread_1_last_cs) | over junior swims |
| Diskvalifikationer (dsq) | junior DSQs at the event |
| **A-finale-grænse (cutline)** | **dropped** — no junior final to qualify for |
| **Spredning 1.–8. (spread_1_8)** | **dropped** — no junior final |
| **Juniorer** | **dropped** — redundant, equals contestants |

Dropped tiles are omitted from the payload/rendering (not shown as a dash).

### Season graphs

New inline query in `queries.py` aggregating `junior_championship` grouped by
season for the event tuple `(gender, distance, stroke, course)`:

- `best_cs = min(completed_centiseconds)`
- `median_cs = quantile_cont(completed_centiseconds, 0.5)`
- `top8_avg_cs = avg` of the 8 fastest per season
- `swims = count`
- `cutline_cs = NULL` — cutline curve dropped (same reason as the tile)

Same season window as the existing `_RACE_COMPARE_SQL`: seasons `<=` the meet's
season, `ORDER BY season DESC LIMIT 5`.

Season basis is the **qualifying swim** (junior_championship uses
`phase IN ('heats','timed_final')`), so a season's "best time" is the best
qualifying swim, not the best final swim — consistent with how the podium and
tiles are derived. Accepted trade-off.

No new analytics view: `junior_championship` already spans all DMJ-L meets
(combined and non-combined) and is the correct junior universe to aggregate.

## Payload change

Add one boolean to the race JSON:

```
"junior_scoped": true    // only on combined DMJ-L; false/absent otherwise
```

Everything else keeps the existing `build_race` return shape (`category`,
`meet_id`, `race_key`, `label`, `is_relay`, `facts`, `podium`,
`season_comparison`).

## Frontend change (`web/src/routes/Race.svelte`)

The tile list and cutline chart are built unconditionally from fixed fields;
`Race.svelte` already omits tiles/charts conditionally via `race.is_relay`.
Mirror that pattern with `race.junior_scoped`:

- Omit the **A-finale-grænse** tile when `junior_scoped`.
- Omit the **Spredning 1.–8.** tile when `junior_scoped`.
- Omit the **Juniorer** tile when `junior_scoped`.
- Render the cutline `<TrendChart>` only when `!race.is_relay && !race.junior_scoped`.

No change to `<Podium>` or `<TrendChart>` internals — they already tolerate the
partial podium and null series.

## Testing (TDD, per repo convention)

Extend `st-scrape/tests/test_webbuild.py` using `tests/webbuild_fixtures.py` to
build an in-memory curated dataset for a **dual-tagged** `["DM-L","DMJ-L"]` meet
where at least one junior posts a fast qualifying (heats) time but does **not**
reach the senior final, and a senior wins the final. Assert on the emitted
DMJ-L race payload:

1. Podium = junior gold/silver/bronze by qualifying time — **differs** from the
   DM-L podium for the same race; junior gold ≠ senior winner.
2. `winning_time` / `winner_points` = junior gold (not senior winner).
3. `contestants` = junior count; `median`/`spread_1_last` over juniors.
4. `cutline`, `spread_1_8`, `juniors` tiles dropped; `junior_scoped == true`.
5. `season_comparison` points reflect juniors only (junior counts/times).

Regression guards (unchanged behaviour):

6. The **DM-L** payload for the same meet is unchanged (senior podium/tiles).
7. A **non-combined DMJ-L** meet fixture: `junior_scoped == false`, all tiles
   and the cutline chart data present, behaviour identical to today.

CDK tests are unaffected (no infra change). Run `.venv/bin/python -m pytest -q`
in `st-scrape` before claiming done.

## Files touched

- `st-scrape/webbuild/queries.py` — combined detection, junior podium query,
  junior facts, junior season-comparison query; branch in `build_race`.
- `web/src/routes/Race.svelte` — 4 conditionals on `junior_scoped`.
- `st-scrape/tests/test_webbuild.py` (+ fixtures if needed) — new assertions.
- No new analytics views; no CDK/infra change.
