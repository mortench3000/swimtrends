# -*- coding: utf-8 -*-

import scrapy

class SwimtrendsItem(scrapy.Item):
    # define the fields for your item here like:
    # name = scrapy.Field()
    pass

class Meet(scrapy.Item):
    meetId = scrapy.Field(serializer=int)
    name = scrapy.Field()
    category = scrapy.Field() #DM, DMY, DMH, DMJ, DME (east), DMW (west), DMYE, DMYW
    venue = scrapy.Field()
    arranger = scrapy.Field()
    course = scrapy.Field()
    date = scrapy.Field()
    season = scrapy.Field(serializer=int) #Year of season finale i.e. 2020 - Sept -> Aug
    race = scrapy.Field()

class Race(scrapy.Item):
    nbr = scrapy.Field(serializer=int)
    text = scrapy.Field()
    gender = scrapy.Field()
    distance = scrapy.Field()
    stroke = scrapy.Field()
    relay_count = scrapy.Field(serializer=int)
    results = scrapy.Field()
    page = scrapy.Field()

class Result(scrapy.Item):
    swimmer = scrapy.Field()
    swimmer_url = scrapy.Field()
    year_of_birth = scrapy.Field(serializer=int)
    team = scrapy.Field()
    rank = scrapy.Field(serializer=int)
    points = scrapy.Field(serializer=int)
    points_calc = scrapy.Field(serializer=int)
    points_fixed = scrapy.Field(serializer=int)
    completed_time = scrapy.Field()
