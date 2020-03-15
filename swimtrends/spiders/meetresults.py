# -*- coding: utf-8 -*-
import scrapy
import dateparser
import urllib.parse as urlparse
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
        self.meet_category = meet_category

    def parse(self, response):
        races = response.css('table>tbody>tr')
        for race in races.css( 'td.subtablealt>a::attr(href)' ):
            if race.extract().startswith( 'results.php' ):
                yield response.follow(race.extract(), callback=self.parse_race_results)

    def parse_race_results(self, response):
        table = response.css('table')

        cells = table[1].css('tr>td.WG3::text')

        meet = Meet()
        purl = urlparse.urlparse(response.url)
        meet['meetId'] = parse_qs(purl.query)['cid'][0]
        meet['name'] = cells[2].extract().strip()
        meet['category'] = self.meet_category
        meet['venue'] = cells[9].extract().strip()
#       meet['arranger'] = cells[16].extract().strip()
        course_text = cells[23].extract().strip()
        meet['course'] = get_course_code( course_text )
        meet['date'] = dateparser.parse( cells[30].extract().strip(), date_formats=['%d %B %Y'] ).strftime('%d-%m-%Y')
        meet.setdefault('race', [])

        race_table_idx = 2
        while race_table_idx < len(table)-2:
            race = Race()
            cells = table[race_table_idx].css('tr>td.WG4::text')

            race_title = cells[0].extract().strip()
            race['nbr'] = race_title.split(",")[0].split()[1]
            race['distance'] = race_title.split(",")[1].strip().split()[0].strip().split('m')[0]
            discipline_da = ''
            if race_title.find('200+150+100+50') > -1:  # 'Løb 30, 200+150+100+50 m fri D, Finaler'
                race['distance'] = '10X50'
                discipline_da = 'Frisv\u00f8mning'
                gender_text = race_title.split(",")[1].strip()[len(race_title.split(",")[1].strip())-1]
                race['gender'] = get_gender_code( gender_text )
            else:
                discipline_da = race_title.split(",")[1].strip().split()[1].strip()
                gender_text = race_title.split(",")[1].strip().split()[2].strip()
                race['gender'] = get_gender_code( race_title )

            race['text'] = race_title.split(",")[2].strip()
            race['stroke'] = get_discipline_code( discipline_da )
            race['page'] = response.url
            race.setdefault('results', [])

            race_table_idx+=1
            result_rows = table[race_table_idx].css('tr')
            # parse header
            FINA = False
            if result_rows[0].css('td::text')[4].extract().strip().upper() =='FINA':
                FINA = True

            i = 3 #Skip header
            # Find first result element
            while True:
                cells = result_rows[i].css('td::text')
                if len(cells) > 0 and cells[0].extract().strip().isnumeric():  #First result element
                    break
                i+=1

            while i < len(result_rows)-1:
                result = Result()
                cells = result_rows[i].css('td::text')
                #Result element row 1
                result['rank'] = cells[0].extract().strip()

                if len(result_rows[i].css('td>a::text')) > 0:
                    result['swimmer'] = result_rows[i].css('td>a::text')[0].extract().strip()
                    result['swimmer_url'] = result_rows[i].css('td>a::attr(href)')[0].extract()
                else:
                    result['swimmer'] = cells[1].extract().strip()
                    result['swimmer_url'] = ''

                result['year_of_birth'] = cells[2].extract().strip()
                if FINA:
                    result['points'] = cells[4].extract().strip()
                    result['team'] = result_rows[i+1].css('td::text')[1].extract().strip()
                else:
                    result['team'] = cells[3].extract().strip()
                    result['points'] = '0'

                result['completed_time'] = cells[9].extract().strip()

                race['results'].append(result)

                # Find next result element
                i+=1
                while i < len(result_rows)-1:
                    cells = result_rows[i].css('td::text')
                    if len(cells[0].extract().strip()) > 0:
                        break
                    i+=1

            meet['race'].append(race)
            race_table_idx+=1

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
    elif discipline_da in ['IM', 'Ind.', 'Indv.Medley', 'Medley']:
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
        return "?" #Unknown

def get_course_code( course_text ):
    if course_text == "25m":
        return "SCM" #Short
    elif course_text == "50m":
        return "LCM" #Long"
    else:
        return "?" #Unknown
