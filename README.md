![AutoVOD Icon](https://cdn.lystad.io/autovod_icon.png)

# AutoVOD

![Releases](https://img.shields.io/github/v/release/jenslys/AutoVOD.svg)

This script automates downloading and uploading Twitch.TV VODs to a selected upload provider.
Broadcasts are downloaded in realtime, in the best quality available.

Current available upload providers:

- **Youtube** (Needs no transcoding, so no file is stored on the disc. The stream is **directly** sent to YouTube)
- **S3** (Currently needs transcoding, so the stream is **temporally stored** on the disc before uploading to S3)

The script checks every minute if the selected streamer is live, if the streamer is; it immediately starts uploading/downloading the stream.

## Installation

### Automatic Installation

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
wget https://github.com/porjo/youtubeuploader/releases/download/23.01/youtubeuploader_23.01_Linux_x86_64.tar.gz
tar -xvf youtubeuploader_23.01_Linux_x86_64.tar.gz && rm youtubeuploader_23.01_Linux_x86_64.tar.gz
mv youtubeuploader /usr/local/bin/youtubeuploader
```

</details>

#### AWS-CLI

If you want to upload to an S3 Bucket

<details>
<summary>Instructions</summary>
<br>

```bash
apt-get install awscli
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
1. Enable the [YouTube Data API (APIs & Auth -> Libary)](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
1. Go to the [Consent Screen](https://console.cloud.google.com/apis/credentials/consent) section, setup an external application, fill in your information and add the user/s that are going to be using the app (Channel/s you are uploading videos to). Enable the **".../auth/youtube.upload"** scope. Then save.
1. Go to the [Credentials](https://console.cloud.google.com/apis/api/youtube.googleapis.com/credentials) section, click "Create credentials" and select "OAuth client ID", select Application Type 'Web Application'. Add a 'Authorised redirect URI' of `http://localhost:8080/oauth2callback`
1. Once created click the download (JSON) button in the list and save it as `client_secrets.json`
1. Getting token from YouTube:
    1. Due to [recent changes](https://developers.googleblog.com/2022/02/making-oauth-flows-safer.html#disallowed-oob) to the Google TOS, if you are running this utility for the first time and want to run it on a Headless server, you have to first run `youtubeuploader` on your local machine (Somewhere with a web browser)

        ```bash
        youtubeuploader -filename sample.mp4
        ```

    1. and then simply copy/move `request.token` and `client_secrets.json` to the remote host. Make sure these are placed inside the `autovod` folder.

**Note**
To be able to upload videos as either "Unlisted or Public" and upload multiple videos a day, you will have to request an [API audit](https://support.google.com/youtube/contact/yt_api_form) from YouTube. Without an audit your videos will be locked as private and you are limited to how many videos you can upload before you reach a quota.

<details>
<summary>Tips on passing the audit</summary>
<br>

I have applied for the audit twice (for two separate projects).

- First time, I was applying because I wanted to archive a particular streamer's streams to youtube.
- Second time, I was applying because I needed a higher quota for testing this tool

Both times I was accepted fairly easily.

Since this tool isn't very complex, and my goal function isn't that complex either, I typed almost the same thing on all fields, along the lines of: "I am going to upload a certain twitch user VODS to youtube, and need a higher quota, because the streamer streams multiple times a week and for x amount of hours. The tool is internal, so the only person that is authenticating through the tool is me." I also linked/referenced this GitHub page (don't know if that helped my case).

The field that wants you to upload a screen recording of the program; I just screen recorded myself doing the `youtubeuplaoder --filename sample.mp4` command. Since that is how we get the token from youtube.

I didn't spend a lot of time filling out the application.
It took around 20 days from submission to them accepting the audit.

I am leaving open the GitHub issue regarding this, in case people want to discuss or share the experience: [#32](https://github.com/jenslys/autovod/issues/32)

</details>

</details>

### S3 setup

<details>
<summary>Instructions</summary>

#### Refer to your S3-Provider on how to configure the AWS-CLI

Common S3 providers:

- [AWS S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/setup-aws-cli.html)
- [Cloudflare R2](https://developers.cloudflare.com/r2/examples/aws-cli/)
- [Wasabi S3](https://wasabi-support.zendesk.com/hc/en-us/articles/115001910791-How-do-I-use-AWS-CLI-with-Wasabi-)
- [Google Cloud Storage](https://developers.cloudflare.com/r2/examples/aws-cli/)
- [Backblaze B2](https://help.backblaze.com/hc/en-us/articles/360047779633-Quickstart-Guide-for-AWS-CLI-and-Backblaze-B2-Cloud-Storage)

</details>

## Usage

### Config file

We will create a dedicated config file for each steamer, in case are monitoring multiple streamers with different settings.

#### Create config file

```bash
cp default.config StreamerNameHere.config
```

#### Edit the config

Edit your newly created config

```bash
nano StreamerNameHere.config
```

### Start AutoVOD

```bash
pm2 start AutoVOD.sh --name StreamerNameHere
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
docker build --build-arg TWITCH_USER=<your twitch username> -t autovod .
```

You can now run this container

```bash
docker run -d autovod 
```

## FAQ

<details>
<summary>I am getting "[Error 32] Broken pipe"</summary>
<br>

There are multiple reasons this error can occur, check the following

#### YouTube

- That you have not reached your YouTube quota
- That your YouTube credential files have not expired
- You can check these by running `youtubeuploader --filename sample.mp4`
    then checking the output.

#### S3

- You have configured `aws` correctly
- You have inserted the correct variables inside the config.

#### Server resource exhaustion

- Uploading vods require alot of bandwith, check if the upload fails because your provider is limiting or cutting of the upload.

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

Licensed under the [GNU General Public License v3.0](LICENSE.md)
