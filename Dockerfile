FROM alpine:3.17

#* Define an arg variable
ARG	TWITCH_USER

#* Upgrade the system and install dependencies
RUN apk add --no-cache --upgrade python3 tar wget bash jq rclone curl \
	&& python3 -m ensurepip \
	&& pip3 install --no-cache-dir --upgrade streamlink cloudscraper

#* Install streamlink plugins
RUN wget --progress=dot:giga -O "/usr/lib/python3.10/site-packages/streamlink/plugins/kick.py" "https://raw.githubusercontent.com/nonvegan/streamlink-plugin-kick/master/kick.py"

#* Install youtubeuploader
RUN wget --progress=dot:giga https://github.com/porjo/youtubeuploader/releases/download/23.03/youtubeuploader_23.03_Linux_x86_64.tar.gz \
	&& tar -xvf youtubeuploader_23.03_Linux_x86_64.tar.gz \
	&& rm youtubeuploader_23.03_Linux_x86_64.tar.gz \
	&& mv youtubeuploader /usr/local/bin/youtubeuploader

#* Copy the required files
COPY	${TWITCH_USER}.config /autoVOD/${TWITCH_USER}.config
COPY	AutoVOD.sh /autoVOD/AutoVOD.sh
COPY	client_secrets.json /autoVOD/client_secrets.json
COPY	request.token /autoVOD/request.token

#* Permissions
RUN chmod +x /autoVOD/AutoVOD.sh

#* Start AutoVOD
WORKDIR /autoVOD
ENTRYPOINT ["/autoVOD/AutoVOD.sh"]
CMD	["noUsernamePassed"]
