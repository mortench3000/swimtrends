-- Relay entries exploded to one row per (relay swim, meet category), mirroring
-- results_by_category. Meets with no championship category are excluded.
CREATE OR REPLACE VIEW relay_results_by_category AS
SELECT r.*, cat.category AS category
FROM relay_results r
JOIN cur_dim_meet m USING (meet_id)
CROSS JOIN UNNEST(m.category) AS cat(category);

-- How a relay event's standard moves across seasons, per championship category.
-- No cut-line: relays are timed finals (no heats). relay_count is part of the
-- key so 4x100 and (any) 8x100 of the same stroke stay distinct.
CREATE OR REPLACE VIEW relay_event_standard_by_season AS
SELECT
    category, season, course, gender, distance, stroke, relay_count,
    count(*)                                       AS swims,
    min(completed_centiseconds)                    AS best_cs,
    quantile_cont(completed_centiseconds, 0.5)     AS median_cs,
    avg(completed_centiseconds) FILTER (WHERE time_rank <= 8) AS top8_avg_cs
FROM (
    SELECT *,
        rank() OVER (
            PARTITION BY category, season, course, gender, distance, stroke, relay_count
            ORDER BY completed_centiseconds
        ) AS time_rank
    FROM relay_results_by_category
    WHERE completed_centiseconds IS NOT NULL
)
GROUP BY category, season, course, gender, distance, stroke, relay_count;
