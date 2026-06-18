-- Per club per season: volume, distinct swimmers, podiums, points.
CREATE OR REPLACE VIEW club_leaderboard AS
SELECT
    club, season,
    count(*)                                      AS swims,
    count(DISTINCT swimmer_id)                    AS swimmers,
    count(*) FILTER (WHERE rank BETWEEN 1 AND 3)  AS podiums,
    sum(points)                                   AS total_points,
    max(points)                                   AS best_points
FROM individual_results
WHERE club IS NOT NULL
GROUP BY club, season;

-- Age-group rankings: bucket by competition-season age, rank within band.
CREATE OR REPLACE VIEW age_group_ranking AS
WITH banded AS (
    SELECT *,
        CASE
            WHEN age <= 12 THEN '<=12'
            WHEN age <= 14 THEN '13-14'
            WHEN age <= 16 THEN '15-16'
            WHEN age <= 18 THEN '17-18'
            ELSE '19+'
        END AS age_group
    FROM individual_results
    WHERE age IS NOT NULL AND completed_centiseconds IS NOT NULL
)
SELECT
    season, gender, distance, stroke, course, age_group,
    swimmer_id, name, club, age, completed_time, points,
    rank() OVER (
        PARTITION BY season, gender, distance, stroke, course, age_group
        ORDER BY completed_centiseconds
    ) AS age_group_rank
FROM banded;

-- Per-meet summary: volume + the standout swim.
CREATE OR REPLACE VIEW meet_summary AS
SELECT
    meet_id,
    any_value(meet_name)        AS meet_name,
    any_value(meet_date)        AS meet_date,
    any_value(season)           AS season,
    count(*)                    AS results,
    count(DISTINCT race_id)     AS races,
    count(DISTINCT swimmer_id)  AS swimmers,
    max(points)                 AS top_points,
    arg_max(swimmer_id, points) AS top_points_swimmer
FROM results
GROUP BY meet_id;
