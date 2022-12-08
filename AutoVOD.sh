#!/bin/bash

echo "Starting AutoVOD..."
echo "Using Twitch user: $TWITCH_USER"
echo ""
echo ""

# Every minute, try to download the Twitch stream, and send it to YouTube.
# Everything through the pipe, no video file is created.

function getStreamTitle() {
	json=$(curl -s https://twitch-api-wrapper.vercel.app/title/$1) # https://github.com/jenslys/twitch-api-wrapper
	if [ "$json" = "[]" ]; then
		echo "Stream is offline"
	elif [ "$json" = "Too many requests, please try again later." ]; then
		echo "Too many API requests"
	else
		echo "$json" | jq -r '.streamTitle'
	fi
}

function getStreamGame() {
	#! Not implemented yet.
}

while true; do
	STREAMER_NAME=$TWITCH_USER                                            #! Dont change this.
	TIME_DATE=[$(date +"%m.%d.%y")]                                       # Preview example: [08.10.21]
	VIDEO_VISIBILITY="unlisted"                                           #* Options: unlisted, private, public
	VIDEO_DESCRIPTION="Uploaded using https://github.com/jenslys/AutoVOD" # YouTube video description.
	VIDEO_TITLE="$STREAMER_NAME - $TIME_DATE"                             # Title of the Youtube video.
	VIDEO_DURATION="12:00:00"                                             # XX:XX:XX (YouTube has a upload limit of 12 hours per video).
	VIDEO_PLAYLIST="$STREAMER_NAME VODs"                                  # Playlist to upload to.
	SPLIT_INTO_PARTS="false"                                              # If you want to split the video into parts, set this to true. (if this is enabled VIDEO_DURATION is ignored).
	SPLIT_VIDEO_DURATION="06:00:00"                                       # Duration of each part. (XX:XX:XX)
	API_CALLS="false"                                                     # Enable this if you want to use more stream metadata like STREAM_TITLE and STREAM_GAME. (This is a boolean value, because we dont want to make unnecessary API calls. if variables are not used)
	if [[API_CALLS == "true"]]; then                                      #? If API_CALLS is enabled.
		STREAM_TITLE=$(getStreamTitle "$STREAMER_NAME")                      #* Optional variable you can add to VIDEO_TITLE if you want to display the stream title.
		STREAM_GAME=""                                                       #* Not implemented yet.
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
