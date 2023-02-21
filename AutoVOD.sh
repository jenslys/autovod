#!/bin/bash

TIME_DATE='date +%m-%d-%y'
TIME_CLOCK='date +%H_%M_%S'
CC='date +%H:%M:%S''|'

# Function to get the value of the --name option
fetchArgs() {
	while getopts ":n:" opt; do
		case $opt in
		*n)
			name=$OPTARG
			;;
		esac
	done
}

# Call the function to get the value of the --name option
fetchArgs "$@"
STREAMER_NAME=$name
echo "$($CC) Selected streamer: $STREAMER_NAME"
config_file="$STREAMER_NAME.config"

#? Check if the config exists
if test -f "$config_file"; then
	echo "$($CC) Found config file"
else
	echo "$($CC) Config file is missing"
	exit 1
fi

echo "$($CC) Starting AutoVOD"
echo "$($CC) Loading $config_file"
# shellcheck source=$STREAMER_NAME.config
source $config_file
echo ""

while true; do
	# Store the orignal values
	variables=("VIDEO_TITLE" "VIDEO_PLAYLIST" "VIDEO_DESCRIPTION" "RCLONE_FILENAME")
	for var in "${variables[@]}"; do
		original_var=original_$var
		eval "$original_var=\$$var"
	done

	fetchMetadata() {
		#? Fetching stream metadata
		# Using my own API to wrap around twitch's API to fetch additional stream metadata.
		# Src code for this: https://github.com/jenslys/twitch-api-wrapper

		echo "$($CC) Trying to fetch stream metadata"
		json=$(curl -s --retry 5 --retry-delay 2 --connect-timeout 30 "$API_URL""$STREAMER_NAME")
		if [ "$json" = "Too many requests, please try again later." ]; then
			echo "$($CC) $json"
			echo ""
		else
			FETCHED_TITLE=$(echo "$json" | jq -r '.stream_title')
			FETCHED_GAME=$(echo "$json" | jq -r '.stream_game')
		fi

		if [ "$STREAMER_TITLE" = null ]; then
			echo "$($CC) Stream seems offline, not able to fetch metadata."
			echo ""
		else
			echo "$($CC) Stream is online!"
			echo "$($CC) Current Title: ""$FETCHED_TITLE"
			echo "$($CC) Current Game: ""$FETCHED_GAME"

			#? Replace the variables with the fetched metadata
			for var in "${variables[@]}"; do
				eval "$var=\${$var//\$STREAMER_TITLE/$FETCHED_TITLE}"
				eval "$var=\${$var//\$STREAMER_GAME/$FETCHED_GAME}"
			done
			echo ""
		fi
	}

	splitVideo() {
		#? Splitting the stream into parts
		# Here we override the video_duration variable with the splitVideo_duration variable.
		# We then compare the current date with the date from the last time we ran the script.
		# if the date is the same, we add 1 to the current part variable.
		# if the date is different, we reset the current part variable to 1.
		VIDEO_DURATION=$SPLIT_VIDEO_DURATION
		if [[ "$($TIME_DATE)" == "$TIME_DATE_CHECK" ]]; then
			# Increment the CURRENT_PART variable
			CURRENT_PART=$(($CURRENT_PART + 1))
		else
			# Reset CURRENT_PART to 1 if the current date is not equal to TIME_DATE_CHECK
			CURRENT_PART=1
		fi
		# Add "- Part_$CURRENT_PART" to the end of the VIDEO_TITLE variable, LOCAL_FILENAME variable and RCLONE_FILENAME variable
		VIDEO_TITLE="$VIDEO_TITLE Part: $CURRENT_PART"
		RCLONE_FILENAME="$RCLONE_FILENAME""-Part_""$CURRENT_PART"
		LOCAL_FILENAME="$LOCAL_FILENAME""-Part_""$CURRENT_PART"
	}

	if [[ "$API_CALLS" == "true" ]]; then
		fetchMetadata # Fetch metadata from the API
	fi

	if [[ "$SPLIT_VIDEO" == "true" ]]; then
		splitVideo # Split the video into parts
	fi

	STREAMLINK_OPTIONS="$STREAMLINK_QUALITY --hls-duration $VIDEO_DURATION $STREAMLINK_FLAGS -O --loglevel $STREAMLINK_LOGS" # https://streamlink.github.io/cli.html#twitch

	echo "$($CC) Checking twitch.tv/""$STREAMER_NAME" "for a stream"

	if [ "$UPLOAD_SERVICE" = "youtube" ]; then
		#? Check if requrired files exists
		# The script wont work if these files are missing.
		# So we check if they exists, if not we exit the script.
		if test -f request.token -a -f client_secrets.json -a -f "$config_file"; then
			echo "$($CC) All required files found"
		else
			echo "$($CC) One or more required files are missing"
			exit 1
		fi

		# Create the input file with upload parameters
		echo '{"title":"'"$VIDEO_TITLE"'","privacyStatus":"'"$VIDEO_VISIBILITY"'","description":"'"$VIDEO_DESCRIPTION"'","playlistTitles":["'"${VIDEO_PLAYLIST}"'"]}' >/tmp/input.$STREAMER_NAME

		# Pass the stream from streamlink to youtubeuploader and then send the file to the void (dev/null)
		streamlink twitch.tv/$STREAMER_NAME $STREAMLINK_OPTIONS | youtubeuploader -metaJSON /tmp/input.$STREAMER_NAME -filename - >/dev/null 2>&1 && TIME_DATE_CHECK=$($TIME_DATE)
	elif [ "$UPLOAD_SERVICE" = "rclone" ]; then
		# Saves the stream to a temp file stream.tmp
		# When the stream is finished, uploads the file to rclone
		# then deletes the temp file
		# https://rclone.org/commands/rclone_copyto/

		TEMP_FILE="stream.tmp"

		if [ "$RE_ENCODE" == "true" ]; then
			#? Re-encode the stream before uploading it to rclone
			# This is useful if you want to re-encode the stream to a different codec, quality or file size.
			# Pipes the stream from streamlink to ffmpeg and then to the matroska temp file
			# https://ffmpeg.org/ffmpeg.html

			echo "$($CC) Re-encoding stream"
			streamlink twitch.tv/$STREAMER_NAME $STREAMLINK_OPTIONS --stdout | ffmpeg -i pipe:0 -c:v $RE_ENCODE_CODEC -crf $RE_ENCODE_CRF -preset $RE_ECODE_PRESET -hide_banner -loglevel $RE_ENCODE_LOG -f matroska $TEMP_FILE >/dev/null 2>&1
		else
			streamlink twitch.tv/$STREAMER_NAME $STREAMLINK_OPTIONS -o - >$TEMP_FILE
		fi

		rclone copyto $TEMP_FILE $RCLONE_REMOTE:$RCLONE_DIR/$RCLONE_FILENAME.$RCLONE_FILEEXT >/dev/null 2>&1 && TIME_DATE_CHECK=$($TIME_DATE)
		wait             # Wait until its done uploading before deleting the file
		rm -f $TEMP_FILE # Delete the temp file
	elif [ "$UPLOAD_SERVICE" = "restream" ]; then
		# This code takes a stream from a twitch.tv streamer, and re-streams it
		# to a twitch.tv channel using RTMPS. The stream is re-muxed to a format
		# that is compatible with RTMPS. The stream is also re-encoded to a
		# format that is compatible with RTMPS.
		streamlink twitch.tv/$STREAMER_NAME $STREAMLINK_OPTIONS -O 2>/dev/null | ffmpeg -re -i - -ar $AUDIO_BITRATE -acodec $AUDIO_CODEC -vcodec copy -f $FILE_FORMAT "$RTMPS_URL""$RTMPS_STREAM_KEY" >/dev/null 2>&1
	elif [ "$UPLOAD_SERVICE" = "local" ]; then
		# If you want to save the stream locally to your machine
		streamlink twitch.tv/$STREAMER_NAME $STREAMLINK_OPTIONS -o - >"$LOCAL_FILENAME.$LOCAL_EXTENSION"
	else
		echo "$($CC) Invalid upload service specified: $UPLOAD_SERVICE" >&2
		exit 1
	fi

	# Restore the original values
	for var in "${variables[@]}"; do
		eval "$var=\$original_$var"
	done

	echo "$($CC) Trying again in 1 minute"
	sleep 60
done
