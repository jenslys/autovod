#!/bin/bash

# Every minute, try to download the Twitch stream, and send it to YouTube.
# Everything through the pipe, no video file is created
while true
do
	# Define some variables
	STREAMER_NAME=$TWITCH_USER
	TIME_DATE=$(date +"%m.%d.%y [%r]") # 07.21.21 [11:13:21 PM]
	VIDEO_VISIBILITY="unlisted" # unlisted, private, public
	VIDEO_DESCRIPTION="Uploaded using AutoVOD"
	STREAMLINK_OPTION="best --hls-duration 12:00:00 --twitch-disable-hosting --twitch-disable-reruns -O" 	# Upload limit is set to 12 hours, becauase of youtube's upload limit.

	# Create the input file. Contains upload parameters
	echo '{"title":"'"${STREAMER_NAME}"' - '"$TIME_DATE"'","privacyStatus":"'"$VIDEO_VISIBILITY"'","description":"'"$VIDEO_DESCRIPTION"'","playlistTitles":["'"${STREAMER_NAME}"'"]}' > /tmp/input.$STREAMER_NAME

	# Start streamlink and youtubeuploader
	streamlink twitch.tv/$STREAMER_NAME $STREAMLINK_OPTION 2>/dev/null | youtubeuploader -metaJSON /tmp/input.$STREAMER_NAME -filename - >/dev/null 2>&1

	sleep 1m
done