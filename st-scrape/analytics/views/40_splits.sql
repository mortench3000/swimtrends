-- Pacing per individual result: first-half vs second-half time from splits.
-- Laps are ordered by cumulative time; for an odd lap count the middle lap
-- falls into the second half (integer division). negative_split = faster back half.
CREATE OR REPLACE VIEW pacing AS
WITH ordered AS (
    SELECT
        result_id, split_centiseconds,
        row_number() OVER (PARTITION BY result_id ORDER BY cumulative_centiseconds) AS lap,
        count(*)     OVER (PARTITION BY result_id) AS laps
    FROM cur_fact_split
    WHERE split_centiseconds IS NOT NULL
),
halves AS (
    SELECT
        result_id,
        sum(split_centiseconds) FILTER (WHERE lap <= laps // 2) AS first_half_cs,
        sum(split_centiseconds) FILTER (WHERE lap >  laps // 2) AS second_half_cs
    FROM ordered
    WHERE laps >= 2
    GROUP BY result_id
)
SELECT
    h.result_id,
    r.name, r.gender, r.distance, r.stroke, r.course, r.season, r.meet_name,
    h.first_half_cs, h.second_half_cs,
    h.second_half_cs - h.first_half_cs AS back_half_delta_cs,
    h.second_half_cs < h.first_half_cs AS negative_split
FROM halves h
JOIN individual_results r USING (result_id);
