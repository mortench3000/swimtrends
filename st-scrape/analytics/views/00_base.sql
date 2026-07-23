-- One row per result, with universal derivations. NO category here: category is
-- a list on dim_meet and unnesting it would multiply rows and break aggregates.
-- Category lives in 50_field_evolution.sql's results_by_category instead.
CREATE OR REPLACE VIEW results AS
SELECT
    o.*,
    o.season - o.birth_year AS age,
    -- Junior championship band: competition-season age 16-18 (a floor AND a
    -- ceiling; sub-16 swimmers at a senior meet are too young for the junior
    -- title). Sliding by season, e.g. 2026 -> birth years 2008-2010.
    (o.season - o.birth_year) BETWEEN 16 AND 18 AS is_junior,
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

-- Relay entries, for the meet-page relay path only. Mirrors individual_results
-- but keeps null swimmer_id (a relay has no single swimmer). DQ excluded here;
-- para is excluded downstream by class='open' in the webbuild relay queries.
CREATE OR REPLACE VIEW relay_results AS
SELECT * FROM results
WHERE is_relay AND NOT is_dq;
