DROP TABLE IF EXISTS race_result, race, meet CASCADE;

CREATE TYPE course_type AS ENUM ('SCM', 'LCM');
CREATE TYPE gender_type AS ENUM ('M', 'F', 'X');
CREATE TYPE stroke_type AS ENUM ('FLY', 'BREAST', 'BACK', 'FREE', 'MEDLEY');
CREATE TYPE race_status_type AS ENUM ('PRELIM', 'A-FINAL', 'B-FINAL', 'C-FINAL', 'AGE-FINAL-1', 'AGE-FINAL-2', 'AGE-FINAL-3');
CREATE TYPE age_group_type AS ENUM ('Y', 'S');
CREATE TYPE pit_age_group_type AS ENUM ('Y1', 'Y2', 'Y3', 'J1', 'J2', 'J3', 'S', 'S1', 'S2', 'S3', '-');
CREATE TYPE meet_category_type AS ENUM('DMY', 'DMYE', 'DMYW', 'DMJ', 'DMJE', 'DMJW', 'DMH', 'DM', 'DME', 'DMW', 'DO')

CREATE TABLE meet (
    meet_id SMALLINT PRIMARY KEY,
    m_name TEXT NOT NULL,
    category meet_category_type [] NOT NULL,
    venue TEXT,
    arranger TEXT,
    course course_type,
    m_date DATE NOT NULL,
    season SMALLINT NOT NULL CHECK(season>=2005)
);

CREATE TABLE race (
    race_id SERIAL PRIMARY KEY,
    ra_nbr SMALLINT NOT NULL,
    ra_title TEXT,
    ra_status TEXT,
    ra_gender gender_type,
    ra_distance SMALLINT NOT NULL,
    ra_stroke stroke_type,
    ra_relay_count SMALLINT NOT NULL,
    ra_link VARCHAR(75) NOT NULL,
    meet_id SMALLINT REFERENCES meet(meet_id)
);

CREATE TABLE race_result (
    result_id SERIAL PRIMARY KEY,
    re_swimmer TEXT NOT NULL,
    re_swimmer_details TEXT,
    re_birth SMALLINT NOT NULL,
    re_pit_age_group pit_age_group_type DEFAULT '-',
    re_pit_age_group_rank SMALLINT DEFAULT 0,
    re_team TEXT NOT NULL,
    re_rank SMALLINT NOT NULL,
    re_points SMALLINT NOT NULL DEFAULT 0,
    re_points_calc SMALLINT NOT NULL DEFAULT 0,
    re_points_fixed SMALLINT NOT NULL DEFAULT 0,
    re_completed_time VARCHAR(8),
    race_id INTEGER REFERENCES race(race_id)
);

-- data/Points_Table_Base_Times.csv
-- year,course,age_group,gender,relay_count,distance,stroke,basetime,basetime_in_sec
DROP TABLE IF EXISTS point_base_times;
CREATE TABLE point_base_times (
    year SMALLINT NOT NULL,
    age_group age_group_type,
    course course_type,
    gender gender_type,
    relay_count SMALLINT NOT NULL DEFAULT 1,
    distance SMALLINT NOT NULL,
    stroke stroke_type,
    basetime VARCHAR(8) NOT NULL,
    basetime_in_sec NUMERIC(6,2) NOT NULL,
    UNIQUE (year,age_group,course,gender,relay_count,distance,stroke)
);
