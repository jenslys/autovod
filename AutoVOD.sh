#!/bin/bash

echo "Starting AutoVOD..."
echo "Using Twitch user: $2"
echo ""
echo ""

# Every minute, try to download the Twitch stream, and send it to YouTube.
# Everything through the pipe, no video file is created.

while true; do
	# Variables
	STREAMER_NAME=$2                                                                                                                        #! Dont change this
	TIME_DATE=[$(date +"%m.%d.%y")]                                                                                                         # Example: [08.10.21]
	VIDEO_VISIBILITY="unlisted"                                                                                                             #* Options: unlisted, private, public
	VIDEO_DESCRIPTION="Watch $STREAMER_NAME live on https://twitch.tv/$STREAMER_NAME \n\nUploaded using https://github.com/jenslys/AutoVOD" # YouTube video description.
	VIDEO_TITLE="$STREAMER_NAME - $TIME_DATE"                                                                                               # Title of the Youtube video.
	VIDEO_DURATION="12:00:00"                                                                                                               # XX:XX:XX (YouTube has a upload limit of 12 hours per video).
	VIDEO_PLAYLIST="$STREAMER_NAME VODs"                                                                                                    # Playlist to upload to.
	SPLIT_INTO_PARTS="false"                                                                                                                # If you want to split the video into parts, set this to true. (if this is enabled VIDEO_DURATION is ignored).
	SPLIT_VIDEO_DURATION="06:00:00"

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
