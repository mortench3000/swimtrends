-- One swimmer's swims over time per event, with delta vs their previous swim.
-- delta_centiseconds < 0 means faster (an improvement).
CREATE OR REPLACE VIEW swimmer_progression AS
SELECT
    result_id,
    swimmer_id, name, gender, distance, stroke, course,
    season, meet_date, meet_name,
    completed_centiseconds, completed_time, points,
    completed_centiseconds - lag(completed_centiseconds) OVER w_prog AS delta_centiseconds,
    points - lag(points) OVER w_prog                                 AS delta_points
FROM individual_results
WHERE completed_centiseconds IS NOT NULL
WINDOW w_prog AS (
    PARTITION BY swimmer_id, gender, distance, stroke, course
    ORDER BY meet_date, result_id
);

-- Best performances of all time, era-normalised via points_fixed.
CREATE OR REPLACE VIEW cross_era_best AS
SELECT
    gender, distance, stroke, course,
    swimmer_id, name, club, season, meet_name, meet_date,
    completed_time, points, points_fixed,
    rank() OVER (
        PARTITION BY gender, distance, stroke, course
        ORDER BY points_fixed DESC
    ) AS era_rank
FROM individual_results
WHERE points_fixed IS NOT NULL;

-- Largest season-over-season improvement per swimmer/event.
-- improvement_centiseconds > 0 means this season's best was faster than last.
CREATE OR REPLACE VIEW biggest_improvers AS
WITH best AS (
    SELECT
        swimmer_id, any_value(name) AS name,
        season, gender, distance, stroke, course,
        min(completed_centiseconds) AS best_cs,
        max(points)                 AS best_points
    FROM individual_results
    WHERE completed_centiseconds IS NOT NULL
    GROUP BY swimmer_id, season, gender, distance, stroke, course
)
SELECT
    swimmer_id, name, gender, distance, stroke, course, season,
    best_cs,
    lag(best_cs) OVER w_impr                  AS prev_best_cs,
    lag(best_cs) OVER w_impr - best_cs        AS improvement_centiseconds,
    best_points - lag(best_points) OVER w_impr AS improvement_points
FROM best
WINDOW w_impr AS (
    PARTITION BY swimmer_id, gender, distance, stroke, course
    ORDER BY season
)
QUALIFY prev_best_cs IS NOT NULL;
