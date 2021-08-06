# AutoVOD

This script was created to record a broadcast from Twitch and upload it on YouTube, in order to watch the stream later.
Broadcasts are downloaded in best quality, no transcoding, and sent directly to youtube, meaning no video is stored on the disk and the stream is directly sent back to YouTube. The script checks if the provided broadcaster is live every 1 min.

## Installation

### PM2

```bash
apt-get install npm
npm install pm2 -g
pm2 startup
```

### Streamlink

```bash
apt-get install python3-pip tar
pip3 install --upgrade streamlink
```

### YouTubeUploader

```bash
wget https://github.com/porjo/youtubeuploader/releases/latest/download/youtubeuploader_linux_amd64.tar.gz
tar -xvf youtubeuploader_linux_amd64.tar.gz
mv youtubeuploader_linux_amd64 /usr/local/bin/youtubeuploader
```

### AutoVOD

```bash
git clone "https://github.com/jenlys/AutoVOD.git"
cd AutoVOD
```

### Sample video

```bash
wget https://download.samplelib.com/mp4/sample-5s.mp4
```

## Setup

Set up your credentials to allow YouTubeUploader to upload videos to YouTube.

1. Create an account on the [Google Developers Console](https://console.developers.google.com)
1. Create a new project
1. Enable the [YouTube Data API (APIs & Auth -> Libary)](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
1. Go to the [Consent Screen](https://console.cloud.google.com/apis/credentials/consent) section, setup an external application, fill in your information, enable the **".../auth/youtube.upload"** scope. Then save.
1. Go to the [Credentials](https://console.cloud.google.com/apis/api/youtube.googleapis.com/credentials) section, click "Create credentials" and select "OAuth client ID", select Application Type 'Web Application'; once created click the download (JSON) button in the list and saving it as `client_secrets.json`
1. Run `youtubeuploader -headlessAuth -filename sample-5s.mp4`
1. Copy-and-paste the URL displayed and open that in your browser.
1. Copy the resulting authorisation code and paste it into the `youtubeuploader` prompt: _"Enter authorisation code here:"_
1. If everthing goes correctly, it will upload the sample video the provided YouTube channel.

**NOTICE: To be able to upload videos as either "Unlisted or Public", you will have to request an [API audit](https://support.google.com/youtube/contact/yt_api_form) from youtube for your project.** **Without an audit your videos will be locked as private.**

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

## Credit

- Orginal script by [arnicel](https://github.com/arnicel/autoTwitchToYouTube)
- YoutubeUploader by [porjo](https://github.com/porjo/youtubeuploader)
- Streamlink by [streamlink](https://github.com/streamlink/streamlink)
