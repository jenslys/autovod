# Use an intermediate image for building
FROM alpine:3.17 as builder

# Define an arg variable
ARG	TWITCH_USER

# Upgrade the system and install dependencies
RUN apk add --no-cache --upgrade python3 tar wget bash jq rclone curl \
	&& python3 -m ensurepip \
	&& pip3 install --no-cache-dir --upgrade streamlink cloudscraper

# Install streamlink plugins
RUN wget --progress=dot:giga -O "/usr/lib/python3.10/site-packages/streamlink/plugins/kick.py" "https://raw.githubusercontent.com/nonvegan/streamlink-plugin-kick/master/kick.py"

# Install youtubeuploader
RUN wget --progress=dot:giga https://github.com/porjo/youtubeuploader/releases/download/23.03/youtubeuploader_23.03_Linux_x86_64.tar.gz \
	&& tar -xvf youtubeuploader_23.03_Linux_x86_64.tar.gz \
	&& rm youtubeuploader_23.03_Linux_x86_64.tar.gz \
	&& mv youtubeuploader /usr/local/bin/youtubeuploader

# Use a fresh image for the final build
FROM alpine:3.17

# Copy the required files
COPY --from=builder /usr/local/bin/youtubeuploader /usr/local/bin/youtubeuploader
COPY AutoVOD.sh /autoVOD/AutoVOD.sh

# Permissions
RUN chmod +x /autoVOD/AutoVOD.sh

# Start AutoVOD
WORKDIR /autoVOD
ENTRYPOINT ["/autoVOD/AutoVOD.sh"]
CMD	["noUsernamePassed"]
