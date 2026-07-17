select * from meet order by meet_id asc;

select * from meet
where 'DMY' = ANY (category)
and course = 'LCM'
order by season asc;

select count(*) from race
where meet_id = 6695;

select count(*) from race_result re
where re.race_id IN (select ra.race_id from race ra where ra.meet_id = 7204);

delete from race_result re
where re.race_id IN (select ra.race_id from race ra where ra.meet_id = 7204);
delete from race ra
where ra.meet_id = 7204;

select * from race ra
where meet_id = 6695
and ra.ra_is_para = False
-- and ra.ra_gender = 'F'
order by ra.ra_nbr asc;

select * from race_result
where race_id = 7025
order by re_rank asc;

update race
set ra_status = 'Finale'
where race_id = 6957
and ra_status = 'Direkte';

select * from meet
where 'DMY' = ANY (category)
and course = 'LCM'
order by season asc;

select * from meet
where 'DMJ' = ANY (category)
and course = 'LCM'
order by season asc;

select count(*) from race
where meet_id = 7456;

delete from race_result re
where re.race_id IN (select ra.race_id from race ra where ra.meet_id = 7456);
delete from race ra
where ra.meet_id = 7456;

select * from race
where meet_id = 7456
and ra_relay_count = 4
--and ra_gender = 'F'
--and ra_status = 'A Finale'
order by ra_nbr asc;

select * from race_result
where race_id = 8009
--or race_id = 7912
and re_rank >=1
order by re_rank asc;

select * from race
where meet_id = 7456
and ra_gender = 'F'
and ra_distance = 200
and ra_stroke = 'FREE'
and ra_relay_count = 1
order by ra_nbr asc;

select * from race_result
where race_id = 7936
order by re_rank asc;

select * from race
where meet_id = 7456
and ra_relay_count = 1
and ra_gender = 'M'
and ra_distance = 100
and ra_stroke = 'FLY'
order by race_id asc;

select * from race_result
where race_id = 7780
order by re_rank asc;

select count(*) from race_result
where race_id = 7768 or race_id = 7770;


select count(*) from race_result re
where re.race_id IN (select ra.race_id from race ra where ra.meet_id = 7456);
select * from race ra
where ra.meet_id = 7456;


delete from race_result re
where re.race_id IN (select ra.race_id from race ra where ra.meet_id = 7456);
delete from race ra
where ra.meet_id = 7456;

