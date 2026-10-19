#!/bin/bash

set -Eeuo pipefail

TIME_DATE='date +%d-%m-%y'
TIME_CLOCK='date +%H_%M_%S'
CC='date +%H:%M:%S''|'

# Globals for cleanup
TEMP_FILE=""

usage() {
    cat <<USAGE
Usage: $0 [-n STREAMER_NAME] | [STREAMER_NAME]

Examples:
  $0 -n Asmongold
  $0 Asmongold

If no name is provided and exactly one *.config (excluding default.config)
exists in the current directory, that config will be used.
USAGE
}

# Parse args: support -n and positional, plus -h
parse_args() {
    local opt
    local name=""
    while getopts ":n:h" opt; do
        case "$opt" in
            n) name="$OPTARG" ;;
            h) usage; exit 0 ;;
            \?) echo "Invalid option: -$OPTARG" >&2; usage; exit 1 ;;
            :) echo "Option -$OPTARG requires an argument." >&2; usage; exit 1 ;;
        esac
    done
    shift $((OPTIND-1))

    # Positional fallback
    if [[ -z "${STREAMER_NAME:-}" ]]; then
        if [[ -n "$name" ]]; then
            STREAMER_NAME="$name"
        elif [[ $# -ge 1 ]]; then
            STREAMER_NAME="$1"
        fi
    fi
}

parse_args "$@"

# Normalize the docker default CMD placeholder if present
if [[ "${STREAMER_NAME:-}" == "noUsernamePassed" ]]; then
    STREAMER_NAME=""
fi

if [ -f /.dockerenv ]; then
	#? If the script is running inside a docker container
	echo "$($CC) Docker detected"
else
	#? If the script is running on a host machine
	echo "$($CC) Docker not detected"
fi

# If still no STREAMER_NAME, auto-select if exactly one *.config exists (excluding default)
if [[ -z "${STREAMER_NAME:-}" ]]; then
    mapfile -t _configs < <(ls -1 *.config 2>/dev/null | grep -v '^default\.config$' || true)
    if [[ ${#_configs[@]} -eq 1 ]]; then
        STREAMER_NAME="${_configs[0]%\.config}"
    elif [[ ${#_configs[@]} -eq 0 ]]; then
        echo "$($CC) Missing required argument: STREAMER_NAME (-n or positional) and no *.config found."
        exit 1
    else
        echo "$($CC) Multiple config files found. Please specify STREAMER_NAME (-n or positional)."
        printf '%s\n' "${_configs[@]}"
        exit 1
    fi
fi

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
if ! source "$config_file"; then
	echo "$($CC) Failed to load config file: $config_file"
	exit 1
fi
echo ""

# Re-encode preset default
RE_ENCODE_PRESET="${RE_ENCODE_PRESET:-medium}"

# Cleanup temporary artifacts on exit
cleanup() {
    # temp recording file
    if [[ -n "${TEMP_FILE:-}" && -f "$TEMP_FILE" ]]; then
        rm -f -- "$TEMP_FILE" || true
    fi
    # youtube meta file
    if [[ -n "${STREAMER_NAME:-}" && -f "/tmp/input.$STREAMER_NAME" ]]; then
        rm -f -- "/tmp/input.$STREAMER_NAME" || true
    fi
}
trap cleanup EXIT

determineSource() {
	echo "$($CC) Determining stream source"
	STREAM_SOURCE_URL=""
	case $STREAM_SOURCE in
	"twitch")
		STREAM_SOURCE_URL="twitch.tv/$STREAMER_NAME"
		echo "$($CC) Stream source: $STREAM_SOURCE_URL"
		;;
	"kick")
		STREAM_SOURCE_URL="kick.com/$STREAMER_NAME"
		echo "$($CC) Stream source: $STREAM_SOURCE_URL"
		;;
	"youtube")
		STREAM_SOURCE_URL="youtube.com/@$STREAMER_NAME/live"
		echo "$($CC) Stream source: $STREAM_SOURCE_URL"
		;;
	*)
		echo "$($CC) Unknown stream source: $STREAM_SOURCE"
		exit 1
		;;
	esac
}

determineSource

checkStreamLive() {
    if streamlink "$STREAM_SOURCE_URL" >/dev/null 2>&1; then
        echo "$($CC) Stream is live"
        return 0
    else
        echo "$($CC) Stream is not live"
        return 1
    fi
}

while true; do
	# Store the orignal values
	variables=("VIDEO_TITLE" "VIDEO_PLAYLIST" "VIDEO_DESCRIPTION" "RCLONE_FILENAME" "RCLONE_DIR" "LOCAL_FILENAME")
	TIME_DATE_CACHE=$($TIME_DATE) # We don't need to execute same command repeatedly
	TIME_CLOCK_CACHE=$($TIME_CLOCK)
	for var in "${variables[@]}"; do
		original_var=original_$var
		eval "$original_var=\$$var"
		eval "replace_var=\$$var"
		replace_var=${replace_var//TIME_DATE/$TIME_DATE_CACHE}
		replace_var=${replace_var//TIME_CLOCK/$TIME_CLOCK_CACHE}
		eval "$var=\$replace_var"
	done

	fetchMetadata() {
		#? Fetching stream metadata (Only for twitch atm)
		# Using my own API to wrap around twitch's API to fetch additional stream metadata.
		# Src code for this: https://github.com/jenslys/twitch-api-wrapper

		extract_base_domain() {
			# Extract the base domain from the API_URL variable
			url=$1
			base_domain=$(echo "$url" | awk -F[/:] '{print $4}')
			echo "$base_domain"
		}

		FULL_API_URL="https://$(extract_base_domain "$API_URL")/info/$STREAMER_NAME"

		echo "$($CC) Trying to fetch stream metadata"

		json=$(curl -s --retry 5 --retry-delay 2 --connect-timeout 30 "$FULL_API_URL")
		if [ -z "$json" ]; then
			echo "Error: Failed to fetch data from $FULL_API_URL"
			exit 1
		fi

		if [ "$json" = "Too many requests, please try again later." ]; then
			echo "$($CC) $json"
			echo ""
		else
			FETCHED_TITLE=$(echo "$json" | jq -r '.stream_title')
			FETCHED_GAME=$(echo "$json" | jq -r '.stream_game')

			# URL encode the fetched game title
			FETCHED_GAME_ENCODED=$(printf '%s' "$FETCHED_GAME" | jq -sRr @uri)
		fi

		if [ "$FETCHED_TITLE" = null ] || [ "$FETCHED_TITLE" = "initial_title" ]; then
			echo "$($CC) Stream seems offline, not able to fetch metadata."
			echo ""
		else
			echo "$($CC) Stream is online!"
			echo "$($CC) Current Title: ""$FETCHED_TITLE"
			echo "$($CC) Current Game: ""$FETCHED_GAME"

			#? Replace the variables with the fetched metadata
			for var in "${variables[@]}"; do
				eval "$var=\${$var//\$STREAMER_TITLE/$FETCHED_TITLE}"
				eval "$var=\${$var//\$STREAMER_GAME/$FETCHED_GAME_ENCODED}"
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

		if [[ -z "$SPLIT_VIDEO_DURATION" ]]; then
			echo "$($CC) SPLIT_VIDEO_DURATION variable is not defined"
			exit 1
		fi

		VIDEO_DURATION="$SPLIT_VIDEO_DURATION"
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

	if checkStreamLive; then
		if [[ "$API_CALLS" == "true" ]]; then
			fetchMetadata # Fetch metadata from the API
		fi

		if [[ "$SPLIT_INTO_PARTS" == "true" ]]; then
			splitVideo # Split the video into parts
		fi

		# Base options without forcing -O or -o; decide per path
		STREAMLINK_BASE_OPTS="$STREAMLINK_QUALITY --hls-duration $VIDEO_DURATION --loglevel $STREAMLINK_LOGS" # https://streamlink.github.io/cli.html#twitch

		echo "$($CC) Checking $STREAM_SOURCE_URL" "for a stream"

		case "$UPLOAD_SERVICE" in
		"youtube")
			#? Check if required files exist
			# The script won't work if these files are missing.
			# So we check if they exist, if not we exit the script.
			if test -f request.token -a -f client_secrets.json -a -f "$config_file"; then
				echo "$($CC) All required files found"
			else
				echo "$($CC) One or more required files are missing"
				exit 1
			fi

			# Create the input file with upload parameters (robust JSON via jq)
			jq -n \
			  --arg t "$VIDEO_TITLE" \
			  --arg v "$VIDEO_VISIBILITY" \
			  --arg d "$VIDEO_DESCRIPTION" \
			  --arg p "$VIDEO_PLAYLIST" \
			  '{title:$t, privacyStatus:$v, description:$d, playlistTitles:[$p]}' >"/tmp/input.$STREAMER_NAME"

			# Pass the stream from streamlink to youtubeuploader and then send the file to the void (dev/null)
			if ! streamlink "$STREAM_SOURCE_URL" $STREAMLINK_BASE_OPTS "${STREAMLINK_FLAGS[@]}" -O | youtubeuploader -metaJSON "/tmp/input.$STREAMER_NAME" -filename - >/dev/null 2>&1; then
				echo "$($CC) youtubeuploader failed uploading the stream"
			else # If the upload was successful
				TIME_DATE_CHECK=$($TIME_DATE)
				echo "$($CC) Stream uploaded to youtube"
				echo ""
			fi
			;;

		"rclone")
			# Saves the stream to a temp file using mktemp
			# When the stream is finished, uploads the file to rclone
			# then deletes the temp file
			# https://rclone.org/commands/rclone_copyto/

			TEMP_FILE=$(mktemp -t autovod.XXXXXX)

			if [ "$RE_ENCODE" == "true" ]; then
				#? Re-encode the stream before uploading it to rclone
				# This is useful if you want to re-encode the stream to a different codec, quality or file size.
				# Pipes the stream from streamlink to ffmpeg and then to the matroska temp file
				# https://ffmpeg.org/ffmpeg.html

				echo "$($CC) Re-encoding stream"
				if ! streamlink "$STREAM_SOURCE_URL" $STREAMLINK_BASE_OPTS "${STREAMLINK_FLAGS[@]}" -O | ffmpeg -i pipe:0 -c:v "$RE_ENCODE_CODEC" -crf "$RE_ENCODE_CRF" -preset "$RE_ENCODE_PRESET" -hide_banner -loglevel "$RE_ENCODE_LOG" -f matroska "$TEMP_FILE" >/dev/null 2>&1; then
					echo "$($CC) ffmpeg failed re-encoding the stream"
				else
					echo "$($CC) Stream re-encoded as $TEMP_FILE"
				fi
			else
				# Saves the file to disk so it can later be uploaded by rclone
				if ! streamlink "$STREAM_SOURCE_URL" $STREAMLINK_BASE_OPTS "${STREAMLINK_FLAGS[@]}" -o "$TEMP_FILE"; then
					echo "$($CC) streamlink failed saving the stream to disk"
				else # If the stream was saved to disc
					echo "$($CC) Stream saved to disk as $TEMP_FILE"
				fi
			fi

			if ! rclone copyto "$TEMP_FILE" "$RCLONE_REMOTE:$RCLONE_DIR/$RCLONE_FILENAME.$RCLONE_FILEEXT" >/dev/null 2>&1; then
				echo "$($CC) rclone failed uploading the stream"
				if [ "$SAVE_ON_FAIL" == "true" ]; then
					#? Save the temp file if rclone fails
					NEW_TEMP_FILE=$(mktemp -t "stream_failed_${STREAMER_NAME}.XXXXXX")
					mv "$TEMP_FILE" "$NEW_TEMP_FILE" # Rename the temp file
					echo "$($CC) Temp file renamed to $NEW_TEMP_FILE"
				fi
			else
				echo "$($CC) Stream uploaded to rclone"
				rm -f -- "$TEMP_FILE" # Delete the temp file
				TIME_DATE_CHECK=$($TIME_DATE)
			fi
			;;

		"restream")
			# This code takes a stream from a twitch.tv streamer, and re-streams it
			# to a twitch.tv channel using RTMPS. The stream is re-muxed to a format
			# that is compatible with RTMPS. The stream is also re-encoded to a
			# format that is compatible with RTMPS.
			if ! streamlink "$STREAM_SOURCE_URL" $STREAMLINK_BASE_OPTS "${STREAMLINK_FLAGS[@]}" -O 2>/dev/null | ffmpeg -re -i - -ar "$AUDIO_BITRATE" -acodec "$AUDIO_CODEC" -vcodec copy -f "$FILE_FORMAT" "$RTMPS_URL""$RTMPS_STREAM_KEY" >/dev/null 2>&1; then
				echo "$($CC) ffmpeg failed re-streaming the stream"
			else # If the stream was re-streamed
				echo "$($CC) Stream re-streamed to $RTMPS_CHANNEL"
				TIME_DATE_CHECK=$($TIME_DATE)
			fi
			;;

		"local")
			TEMP_FILE=$(mktemp -t autovod.XXXXXX)

			if ! streamlink "$STREAM_SOURCE_URL" $STREAMLINK_BASE_OPTS "${STREAMLINK_FLAGS[@]}" -o "$TEMP_FILE"; then
				echo "$($CC) streamlink failed saving the stream"
				if [ "$SAVE_ON_FAIL" == "true" ] && [ -s "$TEMP_FILE" ]; then
					#? Save the temp file if rclone fails
					NEW_LOCAL_FILENAME="${LOCAL_FILENAME}_failed.$LOCAL_EXTENSION"
					mv "$TEMP_FILE" "$NEW_LOCAL_FILENAME" # Rename the local file
					echo "$($CC) Local failed file renamed to $NEW_LOCAL_FILENAME"
				fi
				rm -f -- "$TEMP_FILE"
			else
				if [ "$RE_ENCODE" == "true" ]; then
					echo "$($CC) Re-encoding stream"
					if ! ffmpeg -i "$TEMP_FILE" -c:v "$RE_ENCODE_CODEC" -crf "$RE_ENCODE_CRF" -preset "$RE_ENCODE_PRESET" -hide_banner -loglevel "$RE_ENCODE_LOG" -f matroska "$LOCAL_FILENAME" >/dev/null 2>&1; then
						echo "$($CC) ffmpeg failed re-encoding the stream"
					else # If the stream was re-encoded
						echo "$($CC) Stream re-encoded as $LOCAL_FILENAME"
					fi
				else
					# If you just want to save the stream locally to your machine
					if ! mv "$TEMP_FILE" "$LOCAL_FILENAME.$LOCAL_EXTENSION"; then
						echo "$($CC) failed to move temp file to disk." # May be disk R/O mode?
						if [ "$SAVE_ON_FAIL" == "true" ]; then
							# Failed to move. so, we cannot do anything :(
							echo "$($CC) Local failed file renamed to $TEMP_FILE"
						else
							rm -f -- "$TEMP_FILE"
						fi
					else
						echo "$($CC) Stream saved to disk as $LOCAL_FILENAME.$LOCAL_EXTENSION"
						rm -f -- "$TEMP_FILE"
						TIME_DATE_CHECK=$($TIME_DATE)
					fi
				fi
			fi
			;;

		*)
			echo "$($CC) Invalid upload service specified: $UPLOAD_SERVICE" >&2
			exit 1
			;;
		esac
	else
		echo "$($CC) Stream is offline. Skipping upload process."
	fi

	# Restore the original values
	for var in "${variables[@]}"; do
		eval "$var=\$original_$var"
	done

	echo "$($CC) Trying again in 1 minute"
	sleep 60
done
