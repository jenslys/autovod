#!/bin/bash

echo "Starting AutoVOD..."
echo "Using Twitch user: $TWITCH_USER"
echo ""
echo ""

function getStreamInfo() {
	# This uses my own API wrapper for twitch that i have hosted. (https://github.com/jenslys/twitch-api-wrapper).
	# i would recommend self hosting yourself with your own API credentials. but you may use the one provided below.

	echo "Fetching stream metadata..."
	echo ""

	url="https://twitch-api-wrapper.vercel.app/info/$1"
	json=$(curl -s --retry 5 --retry-delay 2 --connect-timeout 30 $url)

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
	STREAMER_NAME=$TWITCH_USER                                            #! Dont change this.
	TIME_DATE=[$(date +"%m.%d.%y")]                                       # Preview example: [08.10.21]
	VIDEO_VISIBILITY="unlisted"                                           #* Options: unlisted, private, public
	VIDEO_DESCRIPTION="Uploaded using https://github.com/jenslys/AutoVOD" # YouTube video description.
	VIDEO_TITLE="$STREAMER_NAME - $TIME_DATE"                             # Title of the Youtube video.
	VIDEO_DURATION="12:00:00"                                             # XX:XX:XX (YouTube has a upload limit of 12 hours per video).
	VIDEO_PLAYLIST="$STREAMER_NAME VODs"                                  # Playlist to upload to.
	SPLIT_INTO_PARTS="false"                                              #? If you want to split the video into parts, set this to true. (if this is enabled VIDEO_DURATION is ignored).
	SPLIT_VIDEO_DURATION="06:00:00"                                       # Duration of each part. (XX:XX:XX)
	API_CALLS="false"                                                     #? Enable if you want to fetch stream metadata like the Title or Game. You can use the folowing variables with this enabled: $STREAMER_TITLE and $STREAMER_GAME.
	if [[$API_CALLS == "true"]]; then
		getStreamInfo $STREAMER_NAME STREAMER_TITLE STREAMER_GAME
	fi

	# Splitting the stream into parts (If enabled)
	if [[ "$SPLIT_INTO_PARTS" == "true" ]]; then
		VIDEO_DURATION=$SPLIT_VIDEO_DURATION
		if [[ "$TIME_DATE" == "$TIME_DATE_CHECK" ]]; then
			CURRENT_PART=$(($CURRENT_PART + 1))
			VIDEO_TITLE="$VIDEO_TITLE - Part $CURRENT_PART"
		else
			CURRENT_PART=1
		fi
	fi

	STREAMLINK_OPTIONS="best --hls-duration $VIDEO_DURATION --twitch-disable-hosting --twitch-disable-reruns -O --loglevel error" # https://streamlink.github.io/cli.html#twitch

	echo "Checking twitch.tv/$STREAMER_NAME for a stream."

	# Create the input file with upload parameters
	echo '{"title":"'"$VIDEO_TITLE"'","privacyStatus":"'"$VIDEO_VISIBILITY"'","description":"'"$VIDEO_DESCRIPTION"'","playlistTitles":["'"${VIDEO_PLAYLIST}"'"]}' >/tmp/input.$STREAMER_NAME

	# Start StreamLink and YoutubeUploader
	streamlink twitch.tv/$STREAMER_NAME $STREAMLINK_OPTIONS | youtubeuploader -metaJSON /tmp/input.$STREAMER_NAME -filename - >/dev/null 2>&1 && TIME_DATE_CHECK=$TIME_DATE

	echo "Trying again in 1 minute"
	sleep 1m
done
