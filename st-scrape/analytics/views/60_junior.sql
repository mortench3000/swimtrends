-- Junior championship standings (DMJ-L).
--
-- The junior title is decided from the QUALIFYING swim, not the senior final:
-- juniors race clean junior heats (or, for 800/1500, a shared timed final), so
-- ranking juniors by their heats / timed-final time reproduces the junior
-- classification even when a junior never reaches the senior final. Using the
-- senior 'final' phase would silently drop every junior who didn't qualify for
-- it. Scoped to DMJ-L-tagged meets (that is where a junior title exists) via
-- results_by_category, which also excludes relays and DQs. Para swims are left
-- out (`class='open'`); dead-heat ties share a rank, like `medal_count`.
--
-- junior_rank 1/2/3 = junior gold/silver/bronze.
-- e.g. SELECT * FROM junior_championship
--      WHERE season=2026 AND distance=100 AND stroke='Fly' AND gender='M'
--      ORDER BY junior_rank;
CREATE OR REPLACE VIEW junior_championship AS
SELECT
    meet_id, meet_name, season, category,
    event, gender, distance, stroke, course,
    swimmer_id, name, club, age, birth_year,
    completed_time, completed_centiseconds, points,
    rank() OVER (
        PARTITION BY meet_id, gender, distance, stroke, course
        ORDER BY completed_centiseconds
    ) AS junior_rank
FROM results_by_category
WHERE category = 'DMJ-L'
  AND is_junior
  AND class = 'open'
  AND phase IN ('heats', 'timed_final')
  AND completed_centiseconds IS NOT NULL;
