#!/bin/bash

TIME_DATE='date +%m-%d-%y'
TIME_CLOCK='date +%H_%M_%S'

# Function to get the value of the --name option
fetch_args() {
	while getopts ":n:" opt; do
		case $opt in
		*n)
			name=$OPTARG
			;;
		esac
	done
}

# Call the function to get the value of the --name option
fetch_args "$@"
STREAMER_NAME=$name
echo "Selected streamer: $STREAMER_NAME"
config_file="$STREAMER_NAME.config"

#? Check if the config exists
if test -f "$config_file"; then
	echo "Found config file"
else
	echo "Config file is missing"
	exit 1
fi

echo "Starting AutoVOD"
echo "Loading $config_file"
source $config_file
echo ""

while true; do
	if [[ "$API_CALLS" == "true" ]]; then
		#? Fetching stream metadata
		# Using my own API to wrap around twitch's API to fetch additional stream metadata.
		# Src code for this: https://github.com/jenslys/twitch-api-wrapper

		# Store the orignal values
		variables=("VIDEO_TITLE" "VIDEO_PLAYLIST" "VIDEO_DESCRIPTION")
		for var in "${variables[@]}"; do
			original_var=original_$var
			eval "$original_var=\$$var"
		done

		echo "Trying to fetching stream metadata"
		json=$(curl -s --retry 5 --retry-delay 2 --connect-timeout 30 $API_URL)
		if [ "$json" = "Too many requests, please try again later." ]; then
			echo "$json"
			echo ""
		else
			FETCHED_TITLE=$(echo "$json" | jq -r '.stream_title')
			FETCHED_GAME=$(echo "$json" | jq -r '.stream_game')
		fi

		if [ "$STREAMER_TITLE" = null ]; then
			echo "Stream seems offline, can't fetch metadata."
			echo ""
		else
			echo "Stream is online!"
			echo "Current Title: ""$FETCHED_TITLE"
			echo "Current Game: ""$FETCHED_GAME"

			#? Replace the variables with the fetched metadata
			for var in "${variables[@]}"; do
				eval "$var=\${$var//\$STREAMER_TITLE/$FETCHED_TITLE}"
				eval "$var=\${$var//\$STREAMER_GAME/$FETCHED_GAME}"
			done

			echo ""
		fi
	fi

	#? Splitting the stream into parts
	# Here we override the video_duratiation variable with the split_video_duration variable.
	# We then compare the current date with the date from the last time we ran the script.
	# if the date is the same, we add 1 to the current part variable.
	# if the date is different, we reset the current part variable to 1.
	if [[ "$SPLIT_INTO_PARTS" == "true" ]]; then
		VIDEO_DURATION=$SPLIT_VIDEO_DURATION
		if [[ "$($TIME_DATE)" == "$TIME_DATE_CHECK" ]]; then
			# Increment the CURRENT_PART variable
			CURRENT_PART=$(($CURRENT_PART + 1))
		else
			# Reset CURRENT_PART to 1 if the current date is not equal to TIME_DATE_CHECK
			CURRENT_PART=1
		fi
		# Add " - Part $CURRENT_PART" to the end of the VIDEO_TITLE variable
		VIDEO_TITLE="$VIDEO_TITLE - Part $CURRENT_PART"
	fi

	STREAMLINK_OPTIONS="best --hls-duration $VIDEO_DURATION --twitch-disable-hosting --twitch-disable-ads --twitch-disable-reruns -O --loglevel error" # https://streamlink.github.io/cli.html#twitch

	echo "Checking twitch.tv/"$STREAMER_NAME "for a stream"

	if [ "$UPLOAD_SERVICE" = "youtube" ]; then
		#? Check if requrired files exists
		# The script wont work if these files are missing.
		# So we check if they exists, if not we exit the script.
		if test -f request.token -a -f client_secrets.json -a -f "$config_file"; then
			echo "All required files exist"
		else
			echo "One or more required files are missing"
			exit 1
		fi

		# Create the input file with upload parameters
		echo '{"title":"'"$VIDEO_TITLE"'","privacyStatus":"'"$VIDEO_VISIBILITY"'","description":"'"$VIDEO_DESCRIPTION"'","playlistTitles":["'"${VIDEO_PLAYLIST}"'"]}' >/tmp/input.$STREAMER_NAME

		# Pass the stream from streamlink to youtubeuploader and then send the file to the void (dev/null)
		streamlink twitch.tv/$STREAMER_NAME $STREAMLINK_OPTIONS | youtubeuploader -metaJSON /tmp/input.$STREAMER_NAME -filename - >/dev/null 2>&1 && TIME_DATE_CHECK=$($TIME_DATE)
	elif [ "$UPLOAD_SERVICE" = "s3" ]; then
		# Saves the stream to a temp file stream.tmp
		# Then when the stream is finished, uploads the file to S3
		# https://docs.aws.amazon.com/cli/latest/reference/s3api/put-object.html
		streamlink twitch.tv/$STREAMER_NAME $STREAMLINK_OPTIONS -o - >stream.tmp
		aws s3api put-object --bucket $S3_BUCKET --key $S3_OBJECT_KEY --body stream.tmp --endpoint-url $S3_ENDPOINT_URL >/dev/null 2>&1 && TIME_DATE_CHECK=$($TIME_DATE)
		wait # Wait untill its done uploading before deleting the file
		rm -f stream.tmp
	else
		echo "Invalid upload service specified: $UPLOAD_SERVICE" >&2
		exit 1
	fi

	# Restore the original values
	for var in "${variables[@]}"; do
		eval "$var=\$original_$var"
	done

	echo "Trying again in 1 minute"
	sleep 60
done
