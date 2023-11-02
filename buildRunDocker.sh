#!/bin/bash

# Takes the streamer name as an argument
# Example: ./buildRunDocker.sh xqc

name=$1
docker build --build-arg TWITCH_USER=$name -t autovod . && docker run -d autovod $name
