<p align="center"><img src="https://i.imgur.com/P2Ks26s.png" width="150"></p>

<h1 align="center">AutoVOD</h1>
<p align="center">
<a href="https://img.shields.io/github/v/release/jenslys/AutoVOD.svg"></a>
<a href="https://github.com/jenslys/AutoVOD/releases/"><img src="https://img.shields.io/github/v/release/jenslys/AutoVOD.svg" alt="Releases"></a>
<p align="center">This script was created to record broadcasts from Twitch and upload it to YouTube.
Broadcasts are downloaded in the best quality, no transcoding, and sent directly to YouTube, meaning no video is stored on the disk and the stream is directly sent back to YouTube.</p>
</p>

### Table of contents

- [Standalone Installation](#standalone-installation)
  - [Automatic Installation](#automatic-installation)
  - [Manual Installation](#manual-installation)
- [Setup](#setup)
- [Usage](#usage)
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

#### YouTubeUploader

```bash
wget https://github.com/porjo/youtubeuploader/releases/download/22.03/youtubeuploader_22.03_Linux_x86_64.tar.gz
tar -xvf youtubeuploader_22.03_Linux_x86_64.tar.gz && rm youtubeuploader_22.03_Linux_x86_64.tar.gz
mv youtubeuploader_22.03_Linux_x86_64 /usr/local/bin/youtubeuploader
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

## Setup

Set up your credentials to allow YouTubeUploader to upload videos to YouTube.

1. Create an account on [Google Developers Console](https://console.developers.google.com)
1. Create a new project
1. Enable the [YouTube Data API (APIs & Auth -> Libary)](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
1. Go to the [Consent Screen](https://console.cloud.google.com/apis/credentials/consent) section, setup an external application, fill in your information and add the users that are going to be using the app (Channels you are uploading videos to). Enable the **".../auth/youtube.upload"** scope. Then save.
1. Go to the [Credentials](https://console.cloud.google.com/apis/api/youtube.googleapis.com/credentials) section, click "Create credentials" and select "OAuth client ID", select Application Type 'Web Application'. Add a 'Authorised redirect URI' of `http://localhost:8080/oauth2callback`
1. Once created click the download (JSON) button in the list and saving it as `client_secrets.json`
1. Getting token from YouTube:
    1. Due to recent changes to Google/Youtubes TOS, if you are running this utility for the first time and want to run it on a Headless server, you have to first run the tool on your local machine and then simply copy the token file along with `youtubeuploader` and `client_secrets.json` to the remote host.

        ```bash
        youtubeuploader -filename sample.mp4
        ```

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

## Credit

- Original script by [arnicel](https://github.com/arnicel/autoTwitchToYouTube)
- YoutubeUploader by [porjo](https://github.com/porjo/youtubeuploader)
- Streamlink by [streamlink](https://github.com/streamlink/streamlink)
- Icon by [octaviotti](https://macosicons.com/u/octaviotti)
