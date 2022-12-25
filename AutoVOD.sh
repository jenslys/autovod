#!/bin/bash

echo "Starting AutoVOD..."
echo "Loading config..."
source config.sh #? Loads config
echo "Using Twitch user: $STREAMER_NAME"
echo ""
echo ""

function getStreamInfo() {
	#? Fetching stream metadata
	# Using my own API to wrap around twitch's API to fetch additional stream metadata.
	# Src code for this: https://github.com/jenslys/twitch-api-wrapper
	echo "Fetching stream metadata..."
	echo ""
	json=$(curl -s --retry 5 --retry-delay 2 --connect-timeout 30 $API_URL)
	if [ "$json" = "Too many requests, please try again later." ]; then
		echo $json
		echo ""
		return
	fi

	STREAMER_TITLE=$(echo "$json" | jq -r '.stream_title')
	STREAMER_GAME=$(echo "$json" | jq -r '.stream_game')

	if [ "$json" = "[]" ]; then
		echo "Stream is offline, can't fetch metadata."
		echo ""
	else
		echo "Stream is online!"
		echo "Current Title: $STREAMER_TITLE"
		echo "Current Game: $STREAMER_GAME"
		echo ""
	fi
}

while true; do

	checkVariables() {
		#? Checking if we need to fetch stream metadata.
		# Checks if the variables contains the string "STREAMER_TITLE" or "STREAMER_GAME".
		# if it does, we use the API to fetch the stream metadata.
		# This check was added so we don't make unnenecesary API calls.
		for var in "$@"; do
			if [[ "$var" == *"STREAMER_TITLE"* || "$var" == *"STREAMER_GAME"* ]]; then
				return 0
			fi
		done

		return 1
	}

	if checkVariables "$VIDEO_TITLE" "$VIDEO_DESCRIPTION" "$VIDEO_PLAYLIST"; then
		getStreamInfo $STREAMER_NAME STREAMER_TITLE STREAMER_GAME
	fi

	#? Splitting the stream into parts
	# Here we override the video_duratiation variable with the split_video_duration variable.
	# We then compare the current date with the date from the last time we ran the script.
	# if the date is the same, we add 1 to the current part variable.
	# if the date is different, we reset the current part variable to 1.
	if [[ "$SPLIT_INTO_PARTS" == "true" ]]; then
		VIDEO_DURATION=$SPLIT_VIDEO_DURATION
		if [[ "$TIME_DATE" == "$TIME_DATE_CHECK" ]]; then
			CURRENT_PART=$(($CURRENT_PART + 1))
			VIDEO_TITLE="$VIDEO_TITLE - Part $CURRENT_PART"
		else
			CURRENT_PART=1
		fi
	fi

	STREAMLINK_OPTIONS="best --hls-duration $VIDEO_DURATION --twitch-disable-hosting --twitch-disable-ads --twitch-disable-reruns -O --loglevel error" # https://streamlink.github.io/cli.html#twitch

	echo "Checking twitch.tv/$STREAMER_NAME for a stream."

	# Create the input file with upload parameters
	echo '{"title":"'"$VIDEO_TITLE"'","privacyStatus":"'"$VIDEO_VISIBILITY"'","description":"'"$VIDEO_DESCRIPTION"'","playlistTitles":["'"${VIDEO_PLAYLIST}"'"]}' >/tmp/input.$STREAMER_NAME

	# Start StreamLink and YoutubeUploader
	streamlink twitch.tv/$STREAMER_NAME $STREAMLINK_OPTIONS | youtubeuploader -metaJSON /tmp/input.$STREAMER_NAME -filename - >/dev/null 2>&1 && TIME_DATE_CHECK=$TIME_DATE

	echo "Trying again in 1 minute"
	sleep 1m
done
