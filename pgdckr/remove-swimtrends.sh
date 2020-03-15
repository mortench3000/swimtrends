#!/bin/bash

#Cleanup:
docker-compose stop
docker-compose rm -v -f
docker volume rm pgdckr_swimtrends-pgadmin
docker volume rm pgdckr_swimtrends-pgdata
