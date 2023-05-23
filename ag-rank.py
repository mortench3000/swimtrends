#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import psycopg2

meetIds = [2039]

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

def rank(ag_rank_SQL_1, ag_rank_SQL_2, ag_rank_update_SQL, cur, meetId):
    cur.execute(ag_rank_SQL_1, [meetId])
    race_nbrs = cur.fetchall()
    for race in race_nbrs:
        for ag in ('Y1','Y2','Y3','J1','J2','J3','S1','S2','S3'):
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

con = psycopg2.connect(host=os.environ.get('POSTGRES_HOST'),
    database=os.environ.get('POSTGRES_DB'),
    user=os.environ.get('POSTGRES_USER'),
    password=os.environ.get('POSTGRES_PASSWORD'))

with con:
    cur = con.cursor()
    for meetId in meetIds:
        rank(ag_rank_SQL_1, ag_rank_SQL_2, ag_rank_update_SQL, cur, meetId)

    con.commit()

cur.close()
