#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import psycopg2
import itertools
import urllib.parse as urlparse
from urllib.parse import parse_qs

#################################################################################
# File: post-process.py
# Post processing of scraped swim meets
#  - Update pit_age_group field in race_results table for each meet_id
#
#################################################################################

meetIds = []
with open('urls.txt') as urls:
    for url in urls:
        purl = urlparse.urlparse(url)
        meetIds.append(int(parse_qs(purl.query)['cid'][0]))

genders = ['M','F']
y3_ages = [15,14]
j3_ages = [18,17]
s3_ages = [21,20]

# List meetIds where DMJ is part of another meet i.e. DM
dmj_multi_meets = [1870,2039,2309,2485]

# ----------------------------------------------------------------------------

ag_SQL =  \
 "update race_result set re_pit_age_group = %s \
  where result_id in ( \
   select re.result_id \
   from meet m, race ra, race_result re \
   where m.meet_id = %s \
    and m.meet_id = ra.meet_id \
    and ra.race_id = re.race_id \
    and ra.ra_gender = %s \
    and re.re_birth = ( \
        select m.season-%s \
        from meet m \
        where m.meet_id = %s) \
  );"

ag_s_SQL =  \
 "update race_result set re_pit_age_group = %s \
  where result_id in ( \
   select re.result_id \
   from meet m, race ra, race_result re \
   where m.meet_id = %s \
    and m.meet_id = ra.meet_id \
    and ra.race_id = re.race_id \
    and ra.ra_gender = %s \
    and re.re_birth < ( \
        select m.season-%s \
        from meet m \
        where m.meet_id = %s) \
  );"

# ----------------------------------------------------------------------------

dmj_category_update_SQL = \
 "update meet m \
  set category = category || '{\"DMJ\"}'::meet_category_type[] \
  where m.meet_id = %s;"

# ----------------------------------------------------------------------------

ag_rank_SQL_1 =  \
 "select distinct ra.ra_nbr \
  from meet m, race ra \
  where m.meet_id = %s \
    and m.meet_id = ra.meet_id \
    and ra.ra_relay_count = 1;"

ag_rank_SQL_2 = \
 "select re.result_id, re.re_swimmer, re.re_points_calc \
  from meet m, race ra, race_result re \
  where m.meet_id = ra.meet_id \
    and m.meet_id = %s \
    and ra.ra_nbr = %s \
    and ra.race_id = re.race_id \
    and re.re_rank >=1 \
    and re.re_pit_age_group = %s \
  order by re.re_points_calc desc;"

ag_rank_update_SQL = \
 "update race_result \
  set re_pit_age_group_rank = %s \
  where result_id = %s;"

# ----------------------------------------------------------------------------

con = psycopg2.connect(host=os.environ.get('POSTGRES_HOST'),
    database=os.environ.get('POSTGRES_DB'),
    user=os.environ.get('POSTGRES_USER'),
    password=os.environ.get('POSTGRES_PASSWORD'))

with con:
    cur = con.cursor()
    for meetId in meetIds:

        if meetId in dmj_multi_meets:
            cur.execute(dmj_category_update_SQL, [meetId])
            con.commit()

        for (gender, y3_age, j3_age, s3_age) in zip(genders, y3_ages, j3_ages, s3_ages):

            # Youth 1-3
            ag_data = ('Y3', meetId, gender, y3_age, meetId)
            cur.execute(ag_SQL, ag_data)
            ag_data = ('Y2', meetId, gender, y3_age-1, meetId)
            cur.execute(ag_SQL, ag_data)
            ag_data = ('Y1', meetId, gender, y3_age-2, meetId)
            cur.execute(ag_SQL, ag_data)

            # Junior 1-3
            ag_data = ('J3', meetId, gender, j3_age, meetId)
            cur.execute(ag_SQL, ag_data)
            ag_data = ('J2', meetId, gender, j3_age-1, meetId)
            cur.execute(ag_SQL, ag_data)
            ag_data = ('J1', meetId, gender, j3_age-2, meetId)
            cur.execute(ag_SQL, ag_data)

            # Senior 1-3
            ag_data = ('S3', meetId, gender, s3_age, meetId)
            cur.execute(ag_SQL, ag_data)
            ag_data = ('S2', meetId, gender, s3_age-1, meetId)
            cur.execute(ag_SQL, ag_data)
            ag_data = ('S1', meetId, gender, s3_age-2, meetId)
            cur.execute(ag_SQL, ag_data)

            # Senior
            ag_data = ('S', meetId, gender, s3_age, meetId)
            cur.execute(ag_s_SQL, ag_data)

        # Get all indv races for update of age group rank
        cur.execute(ag_rank_SQL_1, [meetId])
        race_nbrs = cur.fetchall()
        for race in race_nbrs:
            for ag in ('Y1','Y2','Y3','J1','J2','J3','S1','S2','S3','S'):
                ag_data = (meetId, race[0], ag)
                cur.execute(ag_rank_SQL_2, ag_data)
                results = cur.fetchall()
                swimmers = []
                i = 0
                for result in results:
                    result_id = result[0]
                    swimmer = result[1]
                    if swimmer not in swimmers:
                        swimmers.append(swimmer)
                        i+=1
                        ag_update = (i, result_id)
                        cur.execute(ag_rank_update_SQL, ag_update)

        con.commit()
    cur.close()
