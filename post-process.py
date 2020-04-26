#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import psycopg2
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

ag3_SQL =  \
 "update race_result set re_pit_age_group = 'Y3' \
  where result_id in ( \
   select re.result_id \
   from meet m, race ra, race_result re \
   where m.meet_id = %s \
    and 'DMY' = ANY (category) \
    and m.meet_id = ra.meet_id \
    and ra.race_id = re.race_id \
    and ra.ra_gender = %s \
    and re.re_birth = ( \
        select min(re.re_birth) \
        from meet m, race ra, race_result re \
        where m.meet_id = %s \
            and 'DMY' = ANY (category) \
            and m.meet_id = ra.meet_id \
            and ra.race_id = re.race_id \
            and ra.ra_gender = %s \
            and re.re_birth > 0) \
    );"

ag2_SQL = \
 "update race_result set re_pit_age_group = 'Y2' \
  where result_id in ( \
   select re.result_id \
   from meet m, race ra, race_result re \
   where m.meet_id = %s \
    and 'DMY' = ANY (category) \
    and m.meet_id = ra.meet_id \
    and ra.race_id = re.race_id \
    and ra.ra_gender = %s \
    and re.re_birth = ( \
        select min(re.re_birth)+1 \
        from meet m, race ra, race_result re \
        where m.meet_id = %s \
            and 'DMY' = ANY (category) \
            and m.meet_id = ra.meet_id \
            and ra.race_id = re.race_id \
            and ra.ra_gender = %s \
            and re.re_birth > 0) \
    );"

ag1_SQL = \
 "update race_result set re_pit_age_group = 'Y1' \
  where result_id in ( \
   select re.result_id \
   from meet m, race ra, race_result re \
   where m.meet_id = %s \
    and 'DMY' = ANY (category) \
    and m.meet_id = ra.meet_id \
    and ra.race_id = re.race_id \
    and ra.ra_gender = %s \
    and re.re_birth = ( \
        select min(re.re_birth)+2 \
        from meet m, race ra, race_result re \
        where m.meet_id = %s \
            and 'DMY' = ANY (category) \
            and m.meet_id = ra.meet_id \
            and ra.race_id = re.race_id \
            and ra.ra_gender = %s \
            and re.re_birth > 0) \
    );"

con = psycopg2.connect(host=os.environ.get('POSTGRES_HOST'),
    database=os.environ.get('POSTGRES_DB'),
    user=os.environ.get('POSTGRES_USER'),
    password=os.environ.get('POSTGRES_PASSWORD'))

with con:
    cur = con.cursor()
    for meetId in meetIds:
        for gender in ['M','F']:
            ag_data = (meetId, gender, meetId, gender)
            cur.execute(ag3_SQL, ag_data)
            cur.execute(ag2_SQL, ag_data)
            cur.execute(ag1_SQL, ag_data)
        con.commit()
    cur.close()
