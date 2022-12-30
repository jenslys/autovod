#!/bin/bash

#? Colors
noColor="\033[0m"
yellow="\033[0;33m"
purple="\033[0;35m"
green="\033[0;32m"
cyan="\033[0;36m"
red="\033[0;31m"

CT=$yellow$(date +"%T")" |"$noColor #? Current time + Formatting

#? Check if requrired files exists in the same directory as the script
files=("request.token" "client_secrets.json" "config.cfg")
for file in "${files[@]}"; do
	if [[ ! -f "$file" ]]; then
		echo -e $red"$file is missing"$noColor
		echo -e "Add/Create $file then run $yellow"pm2 restart procces_id_here"$noColor to restart the script."
		exit 1
	fi
done

echo -e "$CT Loading config"
source config.cfg #? Loads config
echo -e "$CT Starting AutoVOD"
echo -e "$CT Loading config"
echo -e "$CT Using Twitch user: $cyan"$STREAMER_NAME"$noColor"
echo ""

getStreamInfo() {
	#? Fetching stream metadata
	# Using my own API to wrap around twitch's API to fetch additional stream metadata.
	# Src code for this: https://github.com/jenslys/twitch-api-wrapper
	echo -e "$CT Trying to fetching stream metadata"
	json=$(curl -s --retry 5 --retry-delay 2 --connect-timeout 30 $API_URL)
	if [ "$json" = "Too many requests, please try again later." ]; then
		echo -e "$CT $red"$json"$noColor"
		echo ""
	fi

	STREAMER_TITLE=$(echo "$json" | jq -r '.stream_title')
	STREAMER_GAME=$(echo "$json" | jq -r '.stream_game')

	if [ "$STREAMER_TITLE" = null ]; then
		echo -e "$CT Stream seems offline, can't fetch metadata."
		echo ""
	else
		echo -e "$CT $green"Stream is online!"$noColor"
		echo -e "$CT Current Title: $purple"$STREAMER_TITLE"$noColor"
		echo -e "$CT Current Game: $purple"$STREAMER_GAME"$noColor"
		echo ""
	fi
}

checkVariables() {
	#? Checking if we need to fetch stream metadata.
	# Checks if the variables contains the string "STREAMER_TITLE" or "STREAMER_GAME".
	# if it does, we use the API to fetch the stream metadata.
	# This check was added so we don't make unnenecesary API calls.
	for var in "$@"; do
		if [[ "$var" == *"$STREAMER_TITLE"* || "$var" == *"$STREAMER_GAME"* ]]; then
			return 0
		fi
	done

	return 1
}

if checkVariables "$VIDEO_TITLE" "$VIDEO_DESCRIPTION" "$VIDEO_PLAYLIST"; then
	getStreamInfo $STREAMER_NAME STREAMER_TITLE STREAMER_GAME
fi

while true; do
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

	echo -e "$CT Checking twitch.tv/$cyan"$STREAMER_NAME"$noColor" for a stream""

	# Create the input file with upload parameters
	echo -e '{"title":"'"$VIDEO_TITLE"'","privacyStatus":"'"$VIDEO_VISIBILITY"'","description":"'"$VIDEO_DESCRIPTION"'","playlistTitles":["'"${VIDEO_PLAYLIST}"'"]}' >/tmp/input.$STREAMER_NAME

	# Start StreamLink and YoutubeUploader
	streamlink twitch.tv/$STREAMER_NAME $STREAMLINK_OPTIONS | youtubeuploader -metaJSON /tmp/input.$STREAMER_NAME -filename - >/dev/null 2>&1 && TIME_DATE_CHECK=$TIME_DATE

	echo -e "$CT No stream found, Trying again in 1 minute"
	sleep 1m
done
