#!/bin/bash

echo "Starting AutoVOD..."
echo "Using Twitch user: $TWITCH_USER"
echo ""
echo ""

# Every minute, try to download the Twitch stream, and send it to YouTube.
# Everything through the pipe, no video file is created
while true
do
	# Define some variables
	STREAMER_NAME=$TWITCH_USER # Dont change this
	TIME_DATE=[$(date +"%m.%d.%y")] # [08.10.21]
	VIDEO_VISIBILITY="unlisted" # unlisted, private, public
	VIDEO_DESCRIPTION="Watch $STREAMER_NAME live on https://twitch.tv/$STREAMER_NAME \n\nUploaded using https://github.com/jenslys/AutoVOD"
	VIDEO_TITLE=$TIME_DATE
	VIDEO_DURATION="12:00:00" # XX:XX:XX (Youtube has a upload limit set to 12 hours per video)
	SPLIT_INTO_PARTS="true" # If you want to split the videos into multiple parts. (if this is enabled, VIDEO_DURATION is ignored)
	SPLIT_VIDEO_DURATION="05:59:59"
	if [[ "$SPLIT_INTO_PARTS" == "true" ]]; then
		VIDEO_DURATION=$SPLIT_VIDEO_DURATION
		if [[ "$TIME_DATE" == "$TIME_DATE_CHECK"  ]]; then
			CURRENT_PART=$(( $CURRENT_PART + 1 ))
			VIDEO_TITLE="$VIDEO_TITLE - Part $CURRENT_PART"
		else
		  CURRENT_PART=1
		fi
	fi
	STREAMLINK_OPTIONS="best --hls-duration $VIDEO_DURATION --twitch-disable-hosting --twitch-disable-reruns -O" # https://streamlink.github.io/cli.html#twitch

	echo "Checking twitch.tv/$STREAMER_NAME for a stream."

	# Create the input file. Contains upload parameters
	echo '{"title":"'"$VIDEO_TITLE"'","privacyStatus":"'"$VIDEO_VISIBILITY"'","description":"'"$VIDEO_DESCRIPTION"'","playlistTitles":["'"${STREAMER_NAME}"'"]}' > /tmp/input.$STREAMER_NAME

	# Start streamlink and youtubeuploader
	streamlink twitch.tv/$STREAMER_NAME $STREAMLINK_OPTIONS 2>/dev/null | youtubeuploader -metaJSON /tmp/input.$STREAMER_NAME -filename - >/dev/null 2>&1 && TIME_DATE_CHECK=$TIME_DATE

	echo "Trying again in 1 minute"
	sleep 1m
done
