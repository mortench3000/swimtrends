-- 
select m.season, ra.ra_nbr, ra.ra_gender, ra.ra_stroke, ra.ra_distance, re.re_rank, re.re_swimmer, re.re_birth, re.re_completed_time, re.re_points, re.re_points_calc, ra.ra_link
from meet m, race ra, result re
where m.meet_id = ra.meet_id
	and m.category = 'DMY'
	and m.course = 'LCM'
	and ra.race_id = re.race_id
	and ra.ra_status like 'Finaler%'
	and ra.ra_relay_count = 1
	and re.re_rank >=1
--m.season, ra.ra_nbr, ra.ra_gender, ra.ra_stroke, ra.ra_distance, re.re_rank, re.re_swimmer, re.re_completed_time, re.re_points, re.re_points_calculated, ra.ra_link
order by m.season desc, ra.ra_nbr asc, re.re_rank asc;

--
select * from point_base_times where year = '2019' and course = 'LCM';

--
select re_age_group from race_result;
update race_result set re_age_group = -1;

update race_result set re_age_group = 1
where result_id in 
  (select re.result_id
  from meet m, race ra, race_result re
  where m.meet_id = ra.meet_id
      and m.season = 2014
      and m.category = 'DMY'
      and m.course = 'LCM'
	  and ra.race_id = re.race_id
	  and ra.ra_gender = 'M'
	  and re.re_birth = (select min(re.re_birth) from meet m, race ra, race_result re where m.meet_id = ra.meet_id and m.season = 2014 and ra.race_id = re.race_id and ra.ra_gender = 'M')
  )

select re.result_id
  from meet m, race ra, race_result re
  where m.meet_id = ra.meet_id
      and m.season = 2019
      and m.category = 'DMY'
      and m.course = 'LCM'
	  and ra.race_id = re.race_id
	  and ra.ra_gender = 'M'
	  and re.re_birth = (select min(re.re_birth) from meet m, race ra, race_result re where m.meet_id = ra.meet_id and m.season = 2014 and ra.race_id = re.race_id and ra.ra_gender = 'M')

select min(re.re_birth) from meet m, race ra, race_result re where m.meet_id = ra.meet_id and m.season = 2014 and ra.race_id = re.race_id and ra.ra_gender = 'M'
select min(re.re_birth) from meet m, race ra, race_result re where m.meet_id = ra.meet_id and m.season = 2019 and ra.race_id = re.race_id and ra.ra_gender = 'M'