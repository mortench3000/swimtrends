-- One row per result, with universal derivations. NO category here: category is
-- a list on dim_meet and unnesting it would multiply rows and break aggregates.
-- Category lives in 50_field_evolution.sql's results_by_category instead.
CREATE OR REPLACE VIEW results AS
SELECT
    o.*,
    o.season - o.birth_year AS age,
    o.relay_count > 1       AS is_relay,
    o.rank = -1             AS is_dq,
    CASE o.type
        WHEN 'Heats' THEN 'heats'
        WHEN 'Final' THEN 'final'
        ELSE 'timed_final'
    END                     AS phase,
    concat_ws(' ', o.gender, o.distance || 'm', o.stroke, '(' || o.course || ')') AS event
FROM cur_obt o;

-- The default base for swimmer-level analysis: real individual swims only.
CREATE OR REPLACE VIEW individual_results AS
SELECT * FROM results
WHERE NOT is_relay AND swimmer_id IS NOT NULL AND NOT is_dq;
