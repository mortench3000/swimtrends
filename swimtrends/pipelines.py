# -*- coding: utf-8 -*-

import psycopg2
from datetime import datetime
import logging
import math

#--------------------------------
#
#--------------------------------
class SwimtrendsPipeline(object):
    def process_item(self, item, spider):
        return item

#--------------------------------
#
#--------------------------------
class MeetResultsPipeline(object):

    """ MeetResultsPipeline class """

    def __init__(self, pg_host, pg_user, pg_password, pg_db):
        self.pg_host = pg_host
        self.pg_user = pg_user
        self.pg_password = pg_password
        self.pg_db = pg_db

    @classmethod
    def from_crawler(cls, crawler):
        ## pull in information from settings.py
        return cls(
            pg_host=crawler.settings.get('POSTGRES_HOST'),
            pg_user=crawler.settings.get('POSTGRES_USER'),
            pg_password=crawler.settings.get('POSTGRES_PASSWORD'),
            pg_db=crawler.settings.get('POSTGRES_DB')
        )

    def open_spider(self, spider):
        hostname = self.pg_host
        username = self.pg_user
        password = self.pg_password
        database = self.pg_db
        self.connection = psycopg2.connect(host=hostname, user=username, password=password, dbname=database)
        self.cur = self.connection.cursor()

    def close_spider(self, spider):
        self.cur.close()
        self.connection.close()

    def process_item(self, item, spider):

        SQL = 'SELECT basetime_in_sec::float FROM point_base_times WHERE year=%s AND age_group=%s AND course=%s AND gender=%s AND relay_count=%s AND distance=%s AND stroke=%s'

        item['date'] = datetime.strptime(item['date'], '%d-%m-%Y').date()
        item['season'] = getSeason(item['date'])
        for race in item['race']:
            race['relay_count'] = 1
            if race['distance'].upper().find('X') > -1:
                race['relay_count'] = int(race['distance'].upper().split('X')[0].strip())
                race['distance'] = race['distance'].upper().split('X')[1].strip()

            # Determine which basetime to fetch
            if item['category'].find('DMY') > -1 and race['relay_count'] == 1:
                age_group = 'Y'
                season = 2020 # Age group base times exists only for season 2020 and only for indv. races
            else:
                age_group = 'S'
                season = item['season']
            logging.debug("Category: %s - Age group: %s - Season: %s", item['category'], age_group, season)

            # Find base time for race
            point_base_time = 0.0
            self.cur.execute(SQL, (season, age_group, item['course'], race['gender'], race['relay_count'], race['distance'], race['stroke']))
            if self.cur.rowcount > 0:
                point_base_time = self.cur.fetchone()[0]
                logging.debug("Point base time: %s", point_base_time)
            for result in race['results']:
                result['year_of_birth'] = int(result['year_of_birth'])
                result['points_calc'] = 0
                if result['rank'] == '-':
                    result['rank'] = -1 #DSQ, DNS etc
                    result['completed_time'] = ''
                else:
                    result['rank'] = int(result['rank'])
                    if point_base_time > 0:
                        completed_time_in_secs = getTimeInSecs(result['completed_time'])
                        result['points_calc'] = math.trunc(1000*math.pow(point_base_time/completed_time_in_secs,3))
                if len(result['points']) == 0:
                    result['points'] = 0
                else:
                    result['points'] = int(result['points'])
        return item

#--------------------------------
#
#--------------------------------
def getSeason(meet_date):
    if meet_date.month <= 8:    # Jan-Aug
        return meet_date.year
    else:
        return meet_date.year+1  #Sep-Dec

#--------------------------------
#
#--------------------------------
def getTimeInSecs(time_str):
    # Sample time_str: 2:08.77, 34.05

    if time_str.find(':') >=1 :
        min=int(time_str.split(':')[0])
        sec=int(time_str.split(':')[1].split('.')[0])
        dec=int(time_str.split('.')[1])/100
        return min*60+sec+dec
    else:
        return float(time_str)

#--------------------------------
#
#--------------------------------
class MeetResultsPGPipeline(object):

    """ MeetResultsPGPipeline class """

    def __init__(self, pg_host, pg_user, pg_password, pg_db):
        self.pg_host = pg_host
        self.pg_user = pg_user
        self.pg_password = pg_password
        self.pg_db = pg_db

    @classmethod
    def from_crawler(cls, crawler):
        ## pull in information from settings.py
        return cls(
            pg_host=crawler.settings.get('POSTGRES_HOST'),
            pg_user=crawler.settings.get('POSTGRES_USER'),
            pg_password=crawler.settings.get('POSTGRES_PASSWORD'),
            pg_db=crawler.settings.get('POSTGRES_DB')
        )

    def open_spider(self, spider):
        hostname = self.pg_host
        username = self.pg_user
        password = self.pg_password
        database = self.pg_db
        self.connection = psycopg2.connect(host=hostname, user=username, password=password, dbname=database)
        self.cur = self.connection.cursor()

    def close_spider(self, spider):
        self.cur.close()
        self.connection.close()

    def process_item(self, item, spider):
        SQL = "INSERT INTO meet(meet_id,m_name,category,venue,course,m_date,season) values(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (meet_id) DO NOTHING;"
        data = (item['meetId'], item['name'], item['category'], item['venue'], item['course'], item['date'], item['season'])
        self.cur.execute(SQL, data)
        self.connection.commit()

        for race in item['race']:
            ra_SQL = "INSERT INTO race(ra_nbr,ra_status,ra_gender,ra_distance,ra_stroke,ra_relay_count,ra_link,meet_id) values(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING race_id;"
            ra_data = (race['nbr'], race['text'], race['gender'], race['distance'], race['stroke'], race['relay_count'], race['page'], item['meetId'])
            self.cur.execute(ra_SQL, ra_data)
            race_id = self.cur.fetchone()[0]
            logging.debug('Race inserted with id %s', race_id)

            for result in race['results']:
                re_SQL = "INSERT INTO result(re_swimmer,re_swimmer_details,re_birth,re_team,re_rank,re_points,re_points_calc,re_completed_time,race_id) values(%s,%s,%s,%s,%s,%s,%s,%s,%s);"
                re_data = (result['swimmer'], result['swimmer_url'], result['year_of_birth'], result['team'], result['rank'], result['points'], result['points_calc'], result['completed_time'], race_id)
                self.cur.execute(re_SQL, re_data)

        self.connection.commit()
        return item
