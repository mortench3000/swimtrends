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

select re.re_swimmer, re.re_birth, re.re_pit_age_group, re.re_points, re.re_points_calc
from meet m, race ra, race_result re
where m.meet_id = ra.meet_id
	and 'DMJ' = ANY (m.category)
	and m.course = 'SCM'
	and m.season = 2015
	and ra.race_id = re.race_id
	and re.re_rank >=1
	and re.re_pit_age_group = 'J1'
	and ra.ra_nbr = 1
order by re.re_points_calc desc;
	
select distinct ra.ra_nbr
from meet m, race ra
where m.meet_id = ra.meet_id
	and 'DMJ' = ANY (m.category)
	and m.course = 'SCM'
	and m.season = 2015
	and ra.ra_relay_count = 1
order by ra.ra_nbr asc;

