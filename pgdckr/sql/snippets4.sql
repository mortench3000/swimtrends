--
-- Fordeling af deltageres agegroups for DM-K
select agegroup, count(*)
from(
	select distinct re.re_swimmer as swimmer, re.re_pit_age_group as agegroup
	from meet m, race ra, race_result re
	where m.meet_id = ra.meet_id
	and m.meet_id = 3904
	and 'DM' = ANY (m.category)
	and m.course = 'SCM'
	and ra.race_id = re.race_id
	and ra.ra_gender = 'M'
	and ra.ra_relay_count = 1
	order by re.re_pit_age_group
) q1
group by agegroup
order by agegroup;