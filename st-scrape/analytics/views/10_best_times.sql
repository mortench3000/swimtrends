-- Fastest individual swim per swimmer, event, course (all seasons).
CREATE OR REPLACE VIEW personal_best AS
SELECT
    swimmer_id,
    any_value(name)                                  AS name,
    gender, distance, stroke, course,
    min(completed_centiseconds)                      AS best_centiseconds,
    arg_min(completed_time, completed_centiseconds)  AS best_time,
    arg_min(points,         completed_centiseconds)  AS points,
    arg_min(meet_name,      completed_centiseconds)  AS meet_name,
    arg_min(meet_date,      completed_centiseconds)  AS meet_date,
    arg_min(season,         completed_centiseconds)  AS season
FROM individual_results
WHERE completed_centiseconds IS NOT NULL
GROUP BY swimmer_id, gender, distance, stroke, course;

-- Fastest individual swim per swimmer, event, course, season.
CREATE OR REPLACE VIEW season_best AS
SELECT
    swimmer_id,
    any_value(name)                                  AS name,
    season, gender, distance, stroke, course,
    min(completed_centiseconds)                      AS best_centiseconds,
    arg_min(completed_time, completed_centiseconds)  AS best_time,
    arg_min(points,         completed_centiseconds)  AS points,
    arg_min(meet_name,      completed_centiseconds)  AS meet_name,
    arg_min(meet_date,      completed_centiseconds)  AS meet_date
FROM individual_results
WHERE completed_centiseconds IS NOT NULL
GROUP BY swimmer_id, season, gender, distance, stroke, course;

-- Ranked leaderboard by World Aquatics points per event/season.
-- Emits a points_rank column; filter `WHERE points_rank <= 8` for a top-8.
-- Note: ranks all individual swims, not best-per-swimmer, so one swimmer may
-- appear multiple times. Join to personal_best/season_best to deduplicate.
CREATE OR REPLACE VIEW event_leaderboard AS
SELECT
    season, gender, distance, stroke, course,
    swimmer_id, name, club, points, completed_time, meet_name, meet_date,
    rank() OVER (
        PARTITION BY season, gender, distance, stroke, course
        ORDER BY points DESC
    ) AS points_rank
FROM individual_results
WHERE points IS NOT NULL;
