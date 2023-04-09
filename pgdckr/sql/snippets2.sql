select * from race where meet_id=3038 order by ra_nbr asc;

select max(re_fina_points) from result where re_rank>=1;
select * from result where re_fina_points = 904;
select * from race where race_id = 128;

-- Delete sepcific meet
delete from race_result re
where re.race_id IN (select ra.race_id from race ra where ra.meet_id = 4791);
delete from race ra
where ra.meet_id = 4791;
delete from meet
where meet_id = 4791;

SELECT basetime_in_sec FROM fina_base_times WHERE year=2020 AND course='SCM' AND gender='F' AND relay_count=1 AND distance='200' AND stroke='MEDLEY';
SELECT basetime_in_sec, course FROM fina_base_times WHERE year=2020;
select * from fina_base_times order by year desc;

select * from meet order by m_date desc;
select count(*) from result where re_fina_points = 0 and re_rank >=1;
select count(*) from result;
select distinct(ra_gender) from race;
select count(*), ra_gender from race where ra_relay_count = 1 group by ra_gender;
select max(re_fina_points) from result;
select * from race ra,result re where ra.race_id = re.race_id and re.re_fina_points >= 850 order by re_fina_points desc;

select me.meet_id, me.m_name, me.season, ra.ra_nbr, ra.ra_gender, ra.ra_link
from meet me, race ra, result re
where me.meet_id=ra.meet_id
and me.meet_id = 4791
and ra.race_id = re.race_id
and re.re_fina_points = 0
and re.re_rank >=1
group by me.meet_id, me.m_name, me.season, ra.ra_nbr, ra.ra_gender, ra.ra_link
order by me.season desc;

select me.m_name, ra.ra_nbr, re.re_rank, re.re_swimmer, re.re_birth, ra.ra_gender, ra.ra_distance, ra.ra_stroke, re.re_completed_time, re.re_points, re.re_points_calc, ra.ra_link
from meet me, race ra, result re
where me.meet_id=ra.meet_id
and me.meet_id = 4201
and ra.race_id = re.race_id
and ra.ra_status like 'Finaler%'
and re.re_rank >=1
and re.re_rank <=5
and ra.ra_relay_count = 4
-- and re.re_points = 0
--and re.re_points <> re.re_points_calc
--group by me.meet_id, me.m_name, me.season, ra.ra_nbr, ra.ra_gender, ra.ra_distance, ra.ra_stroke, re.re_fina_points, re.re_fina_points_calc, ra.ra_link
order by ra.ra_nbr asc, ra.ra_gender, re.re_birth desc, re.re_rank asc;


select * from fina_base_times order by year desc, course, gender;

select * from point_base_times
where relay_count = 4
and course = 'SCM'
and gender = 'X';

select * from fina_base_times
where course = 'SCM'
and gender = 'F'
and relay_count = 1
and distance = 200
and stroke = 'BREAST'
order by year desc, course, gender;

select * from point_base_times where age_group = 'Y' order by gender;

truncate table result cascade;
truncate table result, race cascade;
truncate table meet, race, race_result cascade;

select count(*) from result;
select * from meet order by season desc;

-- Cleanup before import
DROP TABLE IF EXISTS race_result, race, meet, point_base_times CASCADE;
DROP TYPE IF EXISTS course_type, gender_type, stroke_type, race_status_type, age_group_type, pit_age_group_type, meet_category_type;

select * from meet
where 'DMJ' = ANY (category)
order by course, season desc;

select ra.ra_gender, ra.ra_stroke, ra.ra_distance
from meet m, race ra
where m.meet_id = ra.meet_id
and 'DMJ' = ANY (category)
and ra.ra_status = 'Finaler'
and ra.ra_relay_count = 1
group by ra.ra_gender, ra.ra_stroke, ra.ra_distance
order by ra.ra_stroke, ra.ra_distance;

select distinct re.re_pit_age_group
from meet m, race ra, race_result re
where m.meet_id = ra.meet_id
and 'DMJ' = ANY (category)
and ra.ra_status = 'Finaler'
and ra.race_id = re.race_id;

select season from meet
where 'DMJ' = ANY (category)
and course = 'SCM'
order by season desc;

select m.season, ra.ra_nbr, ra.ra_gender, ra.ra_stroke, ra.ra_distance, re.re_rank, re.re_swimmer, re.re_pit_age_group, re.re_team, re.re_birth, re.re_completed_time, re.re_points, re.re_points_calc, ra.ra_link
from meet m, race ra, race_result re
where m.meet_id = ra.meet_id
	and 'DMJ' = ANY (m.category)
	and m.course = 'SCM'
	and m.season = 2015
	and ra.race_id = re.race_id
--	and ra.ra_status = 'Finaler'
	and ra.ra_relay_count = 1
	and ra.ra_stroke = 'FLY'
	and ra.ra_distance = 50
	and ra.ra_gender = 'F'
	and re.re_rank >=1
--	and (re.re_pit_age_group = 'J1' or re.re_pit_age_group = 'J2' or re.re_pit_age_group = 'J3')
	and re.re_pit_age_group = 'J1'
--m.season, ra.ra_nbr, ra.ra_gender, ra.ra_stroke, ra.ra_distance, re.re_rank, re.re_swimmer, re.re_completed_time, re.re_points, re.re_points_calculated, ra.ra_link
order by m.season desc, re.re_points_calc desc;

select re.re_swimmer, re.re_birth, re.re_pit_age_group, re.re_points, re.re_points_fixed, re.re_points_calc, re.re_pit_age_group_rank
from meet m, race ra, race_result re
where m.meet_id = ra.meet_id
	and 'DMJ' = ANY (m.category)
	and m.course = 'SCM'
--	and m.season = 2020
	and ra.race_id = re.race_id
	and ra.ra_stroke = 'MEDLEY'
	and ra.ra_distance = 400
	and ra.ra_gender = 'M'
	and re.re_rank >=1
--	and re.re_pit_age_group = 'J3'
	and re.re_pit_age_group_rank > 0
	and re.re_swimmer = 'Mikkel Jørgensen'
order by re.re_pit_age_group_rank asc;

select re.re_rank, re.re_swimmer, re.re_birth, re.re_pit_age_group, re.re_completed_time, re.re_points, re.re_points_fixed, re.re_points_calc, ra.ra_status
from meet m, race ra, race_result re
where m.meet_id = ra.meet_id
	and 'DMJ' = ANY (m.category)
	and m.course = 'SCM'
	and m.season = 2018
	and ra.race_id = re.race_id
	and ra.ra_stroke = 'MEDLEY'
	and ra.ra_distance = 200
	and ra.ra_gender = 'F'
	and ra.ra_relay_count = 4
	and ra.ra_status = 'Finaler'
	and re.re_rank >=1
--	and re.re_pit_age_group = 'J3'
--	and re.re_pit_age_group_rank > 0
-- order by re.re_pit_age_group_rank asc
order by re.re_rank asc
;


select distinct ra.ra_nbr
from meet m, race ra
where m.meet_id = ra.meet_id
	and m.meet_id = 2039
	and ra.ra_relay_count = 1;
--order by ra.ra_nbr asc;

select re.re_swimmer, re.re_points_calc, re.re_pit_age_group_rank
from meet m, race ra, race_result re
where m.meet_id = ra.meet_id
	and m.meet_id = 2976
	and ra.ra_nbr = 27
	and ra.race_id = re.race_id
	and re.re_rank >=1
	and re.re_pit_age_group = 'J1'
order by re.re_points_calc desc;

ALTER TABLE race_result ADD COLUMN re_pit_age_group_rank SMALLINT DEFAULT 0;

select * from meet m
where 'DMJ' = ANY (m.category)
	and m.course = 'SCM'
--	and m.season = 2015
order by season desc
;