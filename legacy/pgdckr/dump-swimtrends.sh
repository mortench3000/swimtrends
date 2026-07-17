#!/bin/bash

docker-compose exec postgres su postgres -c "pg_dump swimtrends" | grep -v default_table_access_method | gzip >./swimtrends.sql.gz
