#!/bin/bash
docker-compose up -d
sleep 8

# Find container name
pgadm4=$(docker ps -a | grep pgadmin4 | awk '{print $NF}')

docker exec -u pgadmin:pgadmin -it ${pgadm4} mkdir -m 700 /var/lib/pgadmin/storage/pgadmin4_pgadmin.org
docker cp pgpassfile ${pgadm4}:/tmp/pgpassfile
docker exec -it -u root ${pgadm4} chown pgadmin:pgadmin /tmp/pgpassfile
docker exec -it ${pgadm4} mv /tmp/pgpassfile /var/lib/pgadmin/storage/pgadmin4_pgadmin.org
docker exec -it ${pgadm4} chmod 600 /var/lib/pgadmin/storage/pgadmin4_pgadmin.org/pgpassfile
docker cp servers.json ${pgadm4}:/tmp/servers.json
docker exec -it ${pgadm4} python /pgadmin4/setup.py --load-servers /tmp/servers.json

# Load table point_base_times from csv file
docker cp data/Points_Table_Base_Times.csv ${pgadm4}:/var/lib/pgadmin/storage/pgadmin4_pgadmin.org
docker exec -it -e PGPASSWORD=${POSTGRES_PASSWORD} ${pgadm4} \
  psql -h postgres -U postgres -d swimtrends -w \
  --command "\copy point_base_times (year, age_group, course, gender, relay_count, distance, stroke, basetime, basetime_in_sec) FROM '/var/lib/pgadmin/storage/pgadmin4_pgadmin.org/Points_Table_Base_Times.csv' DELIMITER ',' CSV HEADER QUOTE '\"' ESCAPE '''';"
