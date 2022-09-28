FROM ubuntu:22.04

# Upgrade the system and install dependencies

RUN	apt-get update &&\
	apt-get upgrade -y &&\
	apt-get install -y --no-install-recommends \
	python3-pip tar wget

RUN	pip3 install --upgrade streamlink
RUN	wget https://github.com/porjo/youtubeuploader/releases/download/22.03/youtubeuploader_22.03_Linux_x86_64.tar.gz
RUN	tar -xvf youtubeuploader_22.03_Linux_x86_64.tar.gz && rm youtubeuploader_22.03_Linux_x86_64.tar.gz &&\
	mv youtubeuploader /usr/local/bin/youtubeuploader

# Copy the required files

COPY	AutoVOD.sh /autoVOD/AutoVOD.sh
COPY	client_secrets.json /autoVOD/client_secrets.json
COPY	request.token /autoVOD/request.token

# Set the environment variable
ARG	TWITCH_USER
ENV	TWITCH_USER=$TWITCH_USER

# Start AutoVod

WORKDIR /autoVOD
CMD	["bash", "AutoVOD.sh"]
