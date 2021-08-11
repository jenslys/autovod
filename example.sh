#!/bin/bash

# Every minute, try to download the Twitch stream, and send it to YouTube.
# Everything through the pipe, no video file is created
while true
do
	# Define some variables
	STREAMER_NAME="xqcow"
	TIME_DATE=[$(date +"%m.%d.%y")] # [08.10.21]
	VIDEO_VISIBILITY="unlisted" # unlisted, private, public
	VIDEO_DESCRIPTION="Watch $STREAMER_NAME live on https://twitch.tv/$STREAMER_NAME \n\nUploaded using https://github.com/jenslys/AutoVOD"
	VIDEO_DURATION="12:00:00" # If SPLIT_INTO_PARTS is enabled, this value is overridden
	VIDEO_TITLE="tester 123"
	STREAMLINK_OPTIONS="best --hls-duration $VIDEO_DURATION --twitch-disable-hosting --twitch-disable-reruns -O"
	SPLIT_INTO_PARTS="true" #true, false

if [[ "$SPLIT_INTO_PARTS" == "true" ]]; then
		VIDEO_DURATION="05:59:59"
		if [[ "$TIME_DATE" == "$TIME_DATE_CHECK"  ]]; then
			CURRENT_PART=$(( $CURRENT_PART + 1 ))
			VIDEO_TITLE="$VIDEO_TITLE - Part $CURRENT_PART"
		else
		  CURRENT_PART=1
		fi
	fi

	# Create the input file. Contains upload parameters
	echo '{"title":"'"$VIDEO_TITLE"'","privacyStatus":"'"$VIDEO_VISIBILITY"'","description":"'"$VIDEO_DESCRIPTION"'","playlistTitles":["'"${STREAMER_NAME}"'"]}'
	echo $VIDEO_DURATION

	# Start streamlink and youtubeuploader
	TIME_DATE_CHECK=$TIME_DATE

	sleep 1m
done