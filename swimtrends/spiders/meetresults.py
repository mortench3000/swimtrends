# -*- coding: utf-8 -*-
import scrapy
import dateparser
import urllib.parse as urlparse
import logging
import html2text
from ..items import Meet
from ..items import Race
from ..items import Result
from urllib.parse import parse_qs


class MeetResultsSpider(scrapy.Spider):
    name = 'meetresults'
    allowed_domains = ['livetiming.dk']
    start_urls = [l.strip() for l in open('urls.txt').readlines()]

    def __init__(self, meet_category=None, *args, **kwargs):
        super(MeetResultsSpider, self).__init__(*args, **kwargs)
        self.meet_category = str(meet_category)

    def parse(self, response):
        races = response.css('div.center table tbody tr td a::attr(href)')
        for race in races:
            if race.extract().startswith( 'results.php' ):
                yield response.follow(race.extract(), callback=self.parse_race_results)
        
        next_session = response.xpath('//li[@class="active"]/following-sibling::li[1]/a/@href')[1].get()
        if next_session and 'session=0' not in next_session:
            yield scrapy.Request(response.urljoin(next_session), callback=self.parse)

    def parse_race_results(self, response):
        meet = Meet()
        purl = urlparse.urlparse(response.url)
        meet['meetId'] = parse_qs(purl.query)['cid'][0]
        meet['name'] = response.xpath('//td[@class="csDCA4E998"]').xpath('.//nobr/text()').get()
        meet['category'] = self.meet_category
        venue = response.xpath('//td[@class="cs196BF2C"]')[1].xpath('.//nobr/text()').get()
        if 'Placering' in venue:
            venue = response.xpath('//td[@class="cs196BF2C"]')[2].xpath('.//nobr/text()').get()
        meet['venue'] = venue.strip()
#       meet['arranger'] = response.xpath('//td[@class="cs196BF2C"]')[3].xpath('.//nobr/text()').get()
        course_text = response.xpath('//td[@class="cs196BF2C"]')[5].xpath('.//nobr/text()').get()
        meet['course'] = get_course_code( course_text )
        meet_date = response.xpath('//td[@class="cs196BF2C"]')[7].xpath('.//nobr/text()').get().strip().split()[:3]
        meet['date'] = dateparser.parse(''.join(meet_date), date_formats=['%d%B%Y']).strftime('%d-%m-%Y')
        meet.setdefault('race', [])

        race_titles = response.xpath('//td[@class="csCAB76A03"]').xpath('.//nobr/text()').getall()
        is_multi_final_race =  len(race_titles) > 1 and '\xa0A\xa0Finale' in race_titles[0]
        if not is_multi_final_race and len(race_titles) == 2:
            del race_titles[0]

        logging.debug("Got %s race titles - %s", len(race_titles), race_titles[0])

        for race_title in race_titles:
            race = Race()
            race['title'] = race_title.split(",")[1].split('-')[0].strip()
            race['nbr'] = race_title.split(",")[0].split()[1]
            race['distance'] = race_title.split(",")[1].strip().split()[0].strip().split('m')[0]
            relay = '4X' in race['distance'] or '4x' in race['distance'] # True/False
            discipline_da = ''
            gender_text = ''
            logging.debug('Race title: %s', race_title)
            if race_title.find('200+150+100+50') > -1:
                # Løb 30, 200+150+100+50 m fri D, Finaler
                relay = True
                race['distance'] = '10X50'
                discipline_da = 'Frisv\u00f8mning'
                gender_text = race_title.split(",")[1].strip()[len(race_title.split(",")[1].strip())-1]
            elif 'IM\xa0Medley' in race_title:
                # Løb 13, 4x200m IM Medley Damer - Finale
                discipline_da = 'IM Medley'
                gender_text = race_title.split(",")[1].strip().split()[3].strip()
            else:
                # Løb 5, 50m Brystsvømning Damer - A Finale
                discipline_da = race_title.split(",")[1].strip().split()[1].strip()
                gender_text = race_title.split(",")[1].strip().split()[2].strip()
           
            race['gender'] = get_gender_code( gender_text )

            if len(race_title.split(",")) == 3:  # i.e. 'Løb 2, 50m Brystsvømning Damer, DMJ - A Finale'
                session = race_title.split(",")[2].strip() # Everything from last ','
            else:
                session = race_title.split("-")[1].strip().split()[0]
                if is_multi_final_race:
                    session = session + " " + race_title.split("-")[1].strip().split()[1]

            race['session'] = session
            race['is_para'] = 'Para' in race_title
            race['stroke'] = get_discipline_code( discipline_da )
            race['page'] = response.url
            race.setdefault('results', [])

            logging.debug("Adding race %s", race['title'])
            meet['race'].append(race)

        # FINA = False
        # if response.xpath('//td[@class="cs3262E375"]')[2].xpath('.//nobr/text()').get() == 'Fina':
        #     FINA = True

        logging.debug("Got %s races", len(meet['race']))

        table_rows = response.css('div.center table tr')
        race_result_dict = {}
        race_idx = 0
        header_idx = 0
        for row_idx, row in enumerate(table_rows):
            cells = row.css('td')
            if 'Plac' in str(cells[1].xpath('.//nobr/text()').get()):
                header_idx = row_idx
                break

        logging.debug("Got header row at %s", header_idx)

        table_rows = table_rows[header_idx:len(table_rows)-7] # Skip all non swimmer row at start and end
        points_idx = 0
        completed_time_idx = 0
        for cell_idx, cell in enumerate(table_rows[0].css('td')):
            if 'FINA' in str(cell.xpath('.//nobr/text()').get()):
                points_idx = cell_idx
            elif 'Tid' in str(cell.xpath('.//nobr/text()').get()):
                completed_time_idx = cell_idx

        logging.debug("Got points at %s and completed time at %s", points_idx, completed_time_idx)

        for row in table_rows:
            cells = row.css('td')
            rank = str(cells[1].xpath('.//nobr/text()').get()).strip()
            if rank == '':
                continue
            elif len(race_titles)>race_idx+1 and rank == race_titles[race_idx+1]:  # new (sub)race
                meet['race'][race_idx]['results'] = list(race_result_dict.values())
                race_idx += 1
                race_result_dict = {}
                continue
            if rank[0] == '=':  # i.e. '=26' 
                rank = rank[1:]
            if rank.isdigit() or rank == '-':
                race_result = Result()
                race_result['rank'] = rank
                race_result['swimmer'] = cells[3].xpath('.//nobr/text()').get()
                race_result['swimmer_url'] = cells[3].xpath('./@onmousedown').re_first(r"ASPx\.xr_NavigateUrl\('(.+?)'")
                race_result['year_of_birth'] = '0' if relay else cells[4].xpath('.//nobr/text()').get()
                race_result['team'] = cells[5].xpath('.//nobr/text()').get()
                if race_result['team'] == None:
                    race_result['team'] = '-'
                # race_result['nationality'] = cells[6].xpath('.//nobr/text()').get()
                race_result['nationality'] = 'DEN'
                # cell_idx = 8 if relay else 7
                race_result['points'] = cells[points_idx].xpath('.//nobr/text()').get()
                # cell_idx = 11 if relay else 8
                race_result['completed_time'] = cells[completed_time_idx].xpath('.//nobr/text()').get()
                race_result['is_para'] = str(cells[-1].xpath('.//nobr/text()').get()).startswith('S')
                race_result_key = (race_result['swimmer'], race_result['year_of_birth'],  race_result['team'])
                race_result_dict[race_result_key] = race_result  # Overwrites previous result with same key

        meet['race'][race_idx]['results'] = list(race_result_dict.values())
        yield meet

#
# Functions
#
def get_discipline_code( discipline_da ):
    if discipline_da == 'Frisv\u00f8mning':
        return 'FREE'
    elif discipline_da == 'Brystsv\u00f8mning':
        return 'BREAST'
    elif discipline_da == 'Rygsv\u00f8mning':
        return 'BACK'
    elif discipline_da == 'Butterfly':
        return 'FLY'
    elif discipline_da in ['IM', 'Ind.', 'Indv.Medley', 'Medley', 'IM Medley']:
        return 'MEDLEY'
    else:
        return discipline_da.upper()

def get_gender_code( gender_text ):
    if gender_text.lower().find('herrer') > -1:
        return "M" #Male
    elif gender_text.lower().find('damer') > -1:
        return "F" #Female
    elif gender_text.lower().find('mix')  > -1:
        return "X" #Mix
    if gender_text[0].lower() == "h":
        return "M" #Male
    elif gender_text[0].lower() == "d":
        return "F" #Female
    else:
        logging.debug("Unable to determine the gender from: " + gender_text)
        return "?" #Unknown

def get_course_code( course_text ):
    if course_text == "25m":
        return "SCM" #Short
    elif course_text == "50m":
        return "LCM" #Long"
    else:
        logging.debug("Unable to determine the course from: " + course_text)
        return "?" #Unknown
