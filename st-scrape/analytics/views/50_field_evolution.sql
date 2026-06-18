-- Individual swims exploded to one row per (swim, meet category) for
-- championship trends. A meet tagged with multiple categories contributes to
-- each; counts here are per-category and intentionally NOT 1:1 with
-- individual_results. Meets with no category are excluded (not championships).
CREATE OR REPLACE VIEW results_by_category AS
SELECT r.*, cat.category AS category
FROM individual_results r
JOIN cur_dim_meet m USING (meet_id)
CROSS JOIN UNNEST(m.category) AS cat(category);

-- How an event's standard moves across seasons, per championship category.
CREATE OR REPLACE VIEW event_standard_by_season AS
SELECT
    category, season, course, gender, distance, stroke,
    count(*)                                       AS swims,
    min(completed_centiseconds)                    AS best_cs,
    quantile_cont(completed_centiseconds, 0.5)     AS median_cs,
    quantile_cont(completed_centiseconds, 0.25)    AS p25_cs,
    quantile_cont(completed_centiseconds, 0.75)    AS p75_cs,
    avg(completed_centiseconds) FILTER (WHERE time_rank <= 8) AS top8_avg_cs
FROM (
    SELECT *,
        rank() OVER (
            PARTITION BY category, season, course, gender, distance, stroke
            ORDER BY completed_centiseconds
        ) AS time_rank
    FROM results_by_category
    WHERE completed_centiseconds IS NOT NULL
)
GROUP BY category, season, course, gender, distance, stroke;

-- Preliminary swims ranked by time within championship/event/season.
CREATE OR REPLACE VIEW prelim_ranked AS
SELECT
    category, season, course, gender, distance, stroke,
    completed_centiseconds, completed_time, swimmer_id, name,
    row_number() OVER (
        PARTITION BY category, season, course, gender, distance, stroke
        ORDER BY completed_centiseconds
    ) AS heat_rank
FROM results_by_category
WHERE phase = 'heats' AND completed_centiseconds IS NOT NULL;

-- The cut-line to make an 8-lane final: the 8th-fastest prelim swim.
CREATE OR REPLACE VIEW final_cutline_by_season AS
SELECT
    category, season, course, gender, distance, stroke,
    completed_centiseconds AS cutline_centiseconds,
    completed_time         AS cutline_time,
    swimmer_id, name
FROM prelim_ranked
WHERE heat_rank = 8;

-- Same cut-line for an arbitrary final size: SELECT * FROM cutline_at(6).
CREATE OR REPLACE MACRO cutline_at(n) AS TABLE
SELECT
    category, season, course, gender, distance, stroke,
    completed_centiseconds AS cutline_centiseconds,
    completed_time         AS cutline_time,
    swimmer_id, name
FROM prelim_ranked
WHERE heat_rank = n;
