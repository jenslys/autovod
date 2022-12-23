![AutoVOD Icon](https://cdn.lystad.io/autovod_icon.png)

# AutoVOD

![Releases](https://img.shields.io/github/v/release/jenslys/AutoVOD.svg)

This script lets you automatically record and upload broadcasts from Twitch and upload it directly to YouTube. Broadcasts are downloaded in the best quality available, no transcoding, and sent directly to YouTube, meaning no video is stored on the disk and the stream is directly sent back to YouTube.

The script checks every minute if the selected streamer is live, if the streamer is; it starts immediately sending/uploading the stream to YouTube. After the stream is finished, the video gets processed by YouTube and made public.

## Table of contents

- [Standalone Installation](#standalone-installation)
  - [Automatic Installation](#automatic-installation)
  - [Manual Installation](#manual-installation)
- [Setup](#setup)
- [Usage](#usage)
- [Docker](#using-docker)
- [Credit](#credit)

## Standalone Installation

### Automatic Installation

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/jenslys/autovod/master/install.sh)"
```

### Manual Installation

#### PM2

```bash
apt-get install npm
npm install pm2 -g
pm2 startup
```

#### Streamlink

```bash
apt-get install python3-pip tar
pip3 install --upgrade streamlink
```

#### JQ

```bash
apt-get install jq
```

#### YouTubeUploader

```bash
wget https://github.com/porjo/youtubeuploader/releases/download/22.03/youtubeuploader_22.03_Linux_x86_64.tar.gz
tar -xvf youtubeuploader_22.03_Linux_x86_64.tar.gz && rm youtubeuploader_22.03_Linux_x86_64.tar.gz
mv youtubeuploader /usr/local/bin/youtubeuploader
```

#### AutoVOD

```bash
git clone https://github.com/jenslys/autovod.git
cd autovod
```

#### Sample video

```bash
wget -c -O sample.mp4 https://download.samplelib.com/mp4/sample-5s.mp4
```

#### Note
Daily uploading high quality files/streams to a server may be resource intensive, hence i would recommend using a hosting provider that offers large or unmetered amount of bandwith. Server resource exhaustion may cause vods to fail uploading.

I would recommend [Terrahost](https://terrahost.com/virtual-servers) <sub><sup>(Not sponsored)</sup></sub><br> They offer budget VPS with unmetered* bandwidth.

## Setup

Set up your credentials to allow YouTubeUploader to upload videos to YouTube.

1. Create an account on [Google Developers Console](https://console.developers.google.com)
1. Create a new project
1. Enable the [YouTube Data API (APIs & Auth -> Libary)](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
1. Go to the [Consent Screen](https://console.cloud.google.com/apis/credentials/consent) section, setup an external application, fill in your information and add the user/s that are going to be using the app (Channel/s you are uploading videos to). Enable the **".../auth/youtube.upload"** scope. Then save.
1. Go to the [Credentials](https://console.cloud.google.com/apis/api/youtube.googleapis.com/credentials) section, click "Create credentials" and select "OAuth client ID", select Application Type 'Web Application'. Add a 'Authorised redirect URI' of `http://localhost:8080/oauth2callback`
1. Once created click the download (JSON) button in the list and saving it as `client_secrets.json`
1. Getting token from YouTube:
    1. Due to [recent changes](https://developers.googleblog.com/2022/02/making-oauth-flows-safer.html#disallowed-oob) to the Google TOS, if you are running this utility for the first time and want to run it on a Headless server, you have to first run the tool on your local machine (Somewhere with a web browser)

        ```bash
        youtubeuploader -filename sample.mp4
        ```

    1. and then simply copy the token file along with `youtubeuploader` and `client_secrets.json` to the remote host. make sure these are placed inside the autovod folder

**Note**
To be able to upload videos as either "Unlisted or Public", you will have to request an [API audit](https://support.google.com/youtube/contact/yt_api_form) from YouTube for your project. Without an audit your videos will be locked as private.

## Usage

### Define the Twitch Username

This is the name of the Twitch user whose broadcast will be automatically uploaded to YouTube.

```bash
export TWITCH_USER=username
```

### Start AutoVOD

```bash
pm2 start AutoVOD.sh --name $TWITCH_USER
pm2 save
```

### Check status

```bash
pm2 status
```

## Using docker

This script can be used inside a docker container. To build a container, first execute all Setup-Steps, then build the image:
```bash
docker build --build-arg TWITCH_USER=<your twitch username> -t autovod .
```
You can now run this container
```bash
docker run -d autovod 
```

## Credit

- Original script by [arnicel](https://github.com/arnicel/autoTwitchToYouTube)
- YoutubeUploader by [porjo](https://github.com/porjo/youtubeuploader)
- Streamlink by [streamlink](https://github.com/streamlink/streamlink)
- Icon by [xyaia](https://macosicons.com/#/u/xyaia)
