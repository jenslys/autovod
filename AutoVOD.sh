#!/bin/bash

# Function to get the value of the --name option
fetch_args() {
	# Parse command-line options
	while getopts ":n:" opt; do
		case $opt in
		n)
			name=$OPTARG
			;;
		\?)
			echo "Invalid option: -$OPTARG" >&2
			exit 1
			;;
		:)
			echo "Option -$OPTARG requires an argument." >&2
			exit 1
			;;
		esac
	done
}

# Call the function to get the value of the --name option
fetch_args "$@"
STREAMER_NAME=$name
echo "Selected streamer: $STREAMER_NAME"
config_file="$STREAMER_NAME.config"

#? Check if requrired files exists
# The script wont work if these files are missing.
# So we check if they exists, if not we exit the script.
if test -f request.token -a -f client_secrets.json -a -f "$config_file"; then
	echo "All required files exist"
else
	echo "One or more required files are missing"
	exit 1
fi

echo "Starting AutoVOD"
echo "Loading $config_file"
source $config_file
echo ""
while true; do
	TIME_DATE=[$(date +"%m.%d.%y")]

	getStreamInfo() {
		#? Checking if we need to fetch stream metadata.
		# Checks if the variables contain the string "STREAMER_TITLE" or "STREAMER_GAME".
		# If it does, we use the API to fetch the stream metadata.
		# These check were added so we don't make unnecessary calls to my API.
		fetch_metadata=false
		for var in "$@"; do
			if [[ "$var" == *"$STREAMER_TITLE"* || "$var" == *"$STREAMER_GAME"* ]]; then
				fetch_metadata=true
				break
			fi
		done

		if $fetch_metadata; then
			#? Fetching stream metadata
			# Using my own API to wrap around twitch's API to fetch additional stream metadata.
			# Src code for this: https://github.com/jenslys/twitch-api-wrapper
			echo "Trying to fetching stream metadata"
			json=$(curl -s --retry 5 --retry-delay 2 --connect-timeout 30 $API_URL)
			if [ "$json" = "Too many requests, please try again later." ]; then
				echo "$json"
				echo ""
			fi

			STREAMER_TITLE=$(echo "$json" | jq -r '.stream_title')
			STREAMER_GAME=$(echo "$json" | jq -r '.stream_game')

			if [ "$STREAMER_TITLE" = null ]; then
				echo "Stream seems offline, can't fetch metadata."
				echo ""
				return 1
			else
				echo "Stream is online!"
				echo "Current Title: "$STREAMER_TITLE
				echo "Current Game: "$STREAMER_GAME
				echo ""
				return 0
			fi
		fi
	}

	if ! getStreamInfo "$VIDEO_TITLE" "$VIDEO_DESCRIPTION" "$VIDEO_PLAYLIST"; then
		echo "Skipping fetching extra metadata"
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

	echo "Checking twitch.tv/"$STREAMER_NAME "for a stream"

	echo "STREAMER_NAME: $STREAMER_NAME"
	echo "VIDEO_TITLE: $VIDEO_TITLE"
	echo "VIDEO_DESCRIPTION: $VIDEO_DESCRIPTION"
	echo "VIDEO_PLAYLIST: $VIDEO_PLAYLIST"
	echo "API_URL: $API_URL"

	# Create the input file with upload parameters
	echo '{"title":"'"$VIDEO_TITLE"'","privacyStatus":"'"$VIDEO_VISIBILITY"'","description":"'"$VIDEO_DESCRIPTION"'","playlistTitles":["'"${VIDEO_PLAYLIST}"'"]}' >/tmp/input.$STREAMER_NAME

	# Pass the stream from streamlink to youtubeuploader and then send the file to the void (dev/null)
	streamlink twitch.tv/$STREAMER_NAME $STREAMLINK_OPTIONS | youtubeuploader -metaJSON /tmp/input.$STREAMER_NAME -filename - >/dev/null 2>&1 && TIME_DATE_CHECK=$TIME_DATE

	echo "Trying again in 1 minute"
	sleep 60
done
