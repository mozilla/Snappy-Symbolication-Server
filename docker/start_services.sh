#!/bin/bash

# Open these in the background
memcached -d -U 0 -l 0.0.0.0 -m 64 -p 11211 &
python /app/snappy/DiskCache.py -c /app/docker/dockerconfig.json &

# Open this in the foreground so the docker container continues
# to run
python /app/snappy/SymServer.py -c /app/docker/dockerconfig.json
