# AutoVOD

![Releases](https://img.shields.io/github/v/release/jenslys/AutoVOD.svg)

This script automates downloading and uploading [Twitch.TV](https://twitch.tv) or [Kick.com](https://kick.com) streams to a selected upload provider. <br>

> **Note**
> This does not download and upload the **official Twitch/Kick VOD** after the stream is finished, but rather uses [streamlink](https://streamlink.github.io/) to record and upload the stream in realtime. So features like [separating different audio track for the VOD](https://help.twitch.tv/s/article/soundtrack-audio-configuration?language=en_US) are not supported. If that is something you are looking for, you should check out [Twitch's manual export to YouTube feature](https://help.twitch.tv/s/article/video-on-demand?language=en_US#:~:text=your%20Video%20Producer.-,Export,-Your%20Twitch%20account).

Current available upload options:

- **Youtube** (Needs no transcoding, so no file is stored on the disc.)
  - **Direct Upload**
  - **Re-stream**
- **Rclone** - *Should* work with supported all [providers](https://rclone.org/#providers)
  - **Direct upload** (Needs transcoding, so the stream is **temporally stored** on the disc before uploading)
- **Local**
  - **Local file** (Downloads the stream locally to your machine)

## Installation

### Automatic Installation

> **Note**
> Only supports APT or DNF. If you are using a different package manager, you will have to install the required packages manually.

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/jenslys/autovod/master/install.sh)"
```

### Manual Installation

<details>
<summary>Required packages</summary>

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

#### YoutubeUploader

If you want to upload to YouTube

<details>
<summary>Instructions</summary>
<br>

```bash
wget https://github.com/porjo/youtubeuploader/releases/download/23.03/youtubeuploader_23.03_Linux_x86_64.tar.gz
tar -xvf youtubeuploader_23.03_Linux_x86_64.tar.gz && rm youtubeuploader_23.03_Linux_x86_64.tar.gz
mv youtubeuploader /usr/local/bin/youtubeuploader
```

</details>

#### Rclone

If you want to upload to an any of the Rclone [providers](https://rclone.org/#providers)

<details>
<summary>Instructions</summary>
<br>

```bash
apt-get install rclone
```

</details>

#### FFMPEG

If you want to enable the re-encoding or re-streaming feature

<details>
<summary>Instructions</summary>
<br>

```bash
apt-get install ffmpeg
```

</details>

#### Kick Plugin

If you want to use kick.com as your source

<details>
<summary>Instructions</summary>
<br>

```bash
STREAMLINK_LOCATION=$(pip3 show streamlink | grep -E '^Location:' | awk '{print $2}') &&
      PLUGINS_DIR="${STREAMLINK_LOCATION}/streamlink/plugins" &&
      wget --progress=dot:giga -O "${PLUGINS_DIR}/kick.py" "https://raw.githubusercontent.com/nonvegan/streamlink-plugin-kick/master/kick.py"
```

</details>


#### AutoVOD

```bash
git clone https://github.com/jenslys/autovod.git
cd autovod
```

#### Sample video

```bash
wget -c -O sample.mp4 https://download.samplelib.com/mp4/sample-5s.mp4
```

</details>

## Setup

### Youtube setup

<details>
<summary>Instructions</summary>
<br>

Set up your credentials to allow YouTubeUploader to upload videos to YouTube.

1. Create an account on [Google Developers Console](https://console.developers.google.com)
1. Create a new project
1. Enable the [YouTube Data API (APIs & Auth -> Library)](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
1. Go to the [Consent Screen](https://console.cloud.google.com/apis/credentials/consent) section, setup an external application, fill in your information and add the user/s that are going to be using the app (Channel/s you are uploading videos to). Enable the **".../auth/youtube.upload"** scope. Then save.
1. Go to the [Credentials](https://console.cloud.google.com/apis/api/youtube.googleapis.com/credentials) section, click "Create credentials" and select "OAuth client ID", select Application Type 'Web Application'. Add a 'Authorised redirect URI' of `http://localhost:8080/oauth2callback`
1. Once created click the download (JSON) button in the list and save it as `client_secrets.json`
1. Getting token from YouTube:
    1. Due to [recent changes](https://developers.googleblog.com/2022/02/making-oauth-flows-safer.html#disallowed-oob) to the Google TOS, if you are running this utility for the first time and want to run it on a Headless server, you have to first run `youtubeuploader` on your local machine (Somewhere with a web browser)

        ```bash
        youtubeuploader -filename sample.mp4
        ```

    1. and then simply copy/move `request.token` and `client_secrets.json` to the remote host. Make sure these are placed inside the `autovod` folder.

> **Note**
> To be able to upload videos as either "Unlisted or Public" and upload multiple videos a day, you will have to request an [API audit](https://support.google.com/youtube/contact/yt_api_form) from YouTube. Without an audit your videos will be locked as private and you are limited to how many videos you can upload before you reach a quota.

<details>
<summary>Tips on passing the audit</summary>
<br>

I have applied for the audit twice (for two separate projects).

- First time, I was applying because I wanted to archive a particular streamer's streams to YouTube.
- Second time, I was applying because I needed a higher quota for the testing and development of AutoVOD.

Both times I was accepted fairly easily.

Since this tool isn't very complex, I typed almost the same thing on all fields, along the lines of:
> "I am going to upload a certain twitch user VODS to YouTube and need a higher quote because the streamer streams multiple times a week for x amount of hours. The tool is internal, so the only person that is authenticating through it is me. This is using Youtube Data API to upload to videos."

I also linked/referenced this GitHub page (Don't know if that helped my case).

The field that wants you to upload a screen recording of the program; I just screen recorded myself doing the `youtubeuplaoder --filename sample.mp4` command. Since that is how we get the token from youtube. You could also record the process starting AutoVOD.

> **Note**
> It took around 20 days from submission to them accepting the audit.

I am leaving open the GitHub issue regarding this, in case people want to discuss or share their experience: [#32](https://github.com/jenslys/autovod/issues/32)

</details>

</details>

### Rclone setup

<details>
<summary>Instructions</summary>

#### Refer to your provider on how to configure Rclone

https://rclone.org/#providers

</details>

## Usage

### Config file

We will create a dedicated config file for each steamer, in case are monitoring multiple streamers with different settings.

#### Create config file

> Note: Case sensitive, make sure to type the capitalization for the username the same on all inputs and files.

```bash
cp default.config StreamerNameHere.config
```

#### Edit the config

Edit your newly created config

```bash
nano StreamerNameHere.config
```

##### Optional additional setup steps

<details>
<summary>Stream metadata</summary>

**This currently only works if you are using Twitch.TV**

If you want to add stream metadata to your video, you will need to deploy an api wrapper for the Twitch API. You can find the instructions on how to do that [here](https://github.com/jenslys/twitch-api-wrapper). Once you have the wrapper deployed, you will need to add the url in the API_URL field in the config file and enable the API_CALLS field.

</details>

<details>
<summary>Disable ads</summary>

##### Fetching the OAuth token from 

Follow the instructions [here](https://streamlink.github.io/cli/plugins/twitch.html#authentication) to get your OAuth token.

Then add the OAuth token: `--twitch-api-header=Authorization=OAuth YOURCODEHERE` to the `STREAMLINK_OPTIONS` field in the config file.

##### Other options
Other options can be found [here](https://streamlink.github.io/cli.html#twitch)

</details>

### Start AutoVOD

```bash
pm2 start AutoVOD.sh --name <Streamer Name Here>
pm2 save
```

#### Check status

```bash
pm2 status
```

#### Check logs

```bash
pm2 logs
```

## Using docker

This script can be used inside a docker container. To build a container, first execute all [Setup-Steps](#setup), then build the image:

```bash
docker build --build-arg USERNAME=<Streamer Name Here> -t autovod .
```

You can now run this container

```bash
docker run -d autovod <Streamer Name Here>
```

Or you can run both commands in one line

```bash
./buildRunDocker.sh <Streamer Name Here>
```

## FAQ

<details>
<summary>I am getting "[Error 32] Broken pipe"</summary>
<br>

There are multiple reasons this error can occur, check the following

#### YouTube

- That you have not reached your [YouTube quota limit](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits#:~:text=Projects%20that%20enable%20the%20YouTube,majority%20of%20our%20API%20users.)
- That your YouTube credential files have not expired
- You can check these by running `youtubeuploader --filename sample.mp4`
    then checking the output.

#### Rclone

- You have configured `rclone` correctly
- You have inserted the correct variables inside the config.

#### Server resource exhaustion

- Uploading VODs require a lot of bandwidth, check if the upload fails because your provider is limiting or cutting of the upload.

</details>

<details>
<summary>My tokens keep getting revoked</summary>
<br>

- Visit the [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent) and click on the publish button to change from the testing status to the published status.

</details>

<details>
<summary>My video keeps getting marked as private</summary>
<br>

- To be able to upload videos as either "Unlisted or Public" and upload multiple videos a day, you will have to request an [API audit](https://support.google.com/youtube/contact/yt_api_form) from YouTube. Without an audit your videos will be locked as private and you are limited to how many videos you can upload before you reach a quota.

</details>

<details>
<summary>I cant upload videos longer then 15 minutes</summary>
<br>

- You will need to [verify](http://youtube.com/verify) your phone number on youtube to upload videos longer then 15 min

</details>

<details>
<summary>One or more required files are missing</summary>
<br>

The following files are required for the script to work:

- `nameOfStreamer.config`
- `request.token` (Only if uploading to YouTube)
- `client_secrets.json` (Only if uploading to YouTube)

It should look something like this:

![Screenshot](https://cdn.lystad.io/autovod_folder.jpeg)
</details>

## Credit

- Original script by [arnicel](https://github.com/arnicel/autoTwitchToYouTube)
- YoutubeUploader by [porjo](https://github.com/porjo/youtubeuploader)
- Streamlink by [streamlink](https://github.com/streamlink/streamlink)
- Icon by [xyaia](https://macosicons.com/#/u/xyaia)

## License

Licensed under the [MIT License](LICENSE.md)
