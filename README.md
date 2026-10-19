# AutoVOD 3.x

[![tests](https://github.com/cens0r3d/autovod/actions/workflows/ci.yml/badge.svg)](https://github.com/cens0r3d/autovod/actions/workflows/ci.yml)

Record [Twitch.tv](https://twitch.tv), [Kick.com](https://kick.com) or
[YouTube Live](https://youtube.com/live) streams in realtime and upload them to
YouTube, an [rclone](https://rclone.org) remote, an RTMP(S) endpoint or your
local disk.

> **This is the 3.x rewrite of [jenslys/AutoVOD](https://github.com/jenslys/AutoVOD).**
> The 2.x shell implementation had several crash-on-first-use bugs (broken part
> splitting, an `eval` that executed stream titles, silent loss of a whole
> recording when an upload died). All of them, the evidence and the upstream
> issues they map to are documented in **[REVIEW.md](REVIEW.md)**. The old script
> is preserved unchanged in [`legacy/AutoVOD-bash.sh`](legacy/AutoVOD-bash.sh).

Important: this does **not** download the official Twitch/Kick/YouTube VOD after
the stream ends — it records the live stream with
[streamlink](https://streamlink.github.io/) and uploads it. Features that only
exist in the official VODs (e.g. Twitch's separate soundtrack audio track) are
therefore not part of the output. For that, use
[Twitch's manual export to YouTube](https://help.twitch.tv/s/article/video-on-demand).

Upload targets:

| `UPLOAD_SERVICE` | Behaviour | Needs |
|---|---|---|
| `youtube` | records each part, then uploads it with [youtubeuploader](https://github.com/porjo/youtubeuploader) (no transcoding; can also stream straight through with `YOUTUBE_RECORD_TO_DISK=false`) | `youtubeuploader`, `client_secrets.json`, `request.token` |
| `rclone` | records a part (optional ffmpeg re-encode), then `rclone copyto` to any [rclone provider](https://rclone.org/#providers) | `rclone`, optional `ffmpeg` |
| `restream` | pipes the stream through ffmpeg into an RTMP(S) endpoint | `ffmpeg` |
| `local` | writes the recording to disk (optionally re-encoded) | — |

---

## Requirements

* Linux server (also runs on macOS/Windows; production target is Linux)
* Python **3.8+** — the tool itself is one stdlib-only file, no `jq`, no bash logic
* [streamlink](https://streamlink.github.io/) **6.0+** (8.x recommended)
* optional: `ffmpeg` (re-encode / restream), `rclone` (rclone uploads),
  `youtubeuploader` (YouTube uploads)

## Installation

### Automatic

```sh
sh -c "$(curl -fsSL https://raw.githubusercontent.com/jenslys/autovod/master/install.sh)"
```

The installer is idempotent: it installs the system packages, creates a
virtualenv with streamlink, optionally downloads rclone/youtubeuploader
(architecture aware) and clones or updates the checkout. It never runs a
distribution upgrade of your server.

### Manual

```sh
apt-get install -y python3 python3-venv ffmpeg git curl            # dnf: python3 python3-pip ffmpeg git curl
python3 -m venv .venv && .venv/bin/pip install --upgrade streamlink # streamlink 8.x
git clone https://github.com/cens0r3d/autovod.git && cd autovod

# optional
apt-get install -y rclone                                           # rclone uploads
curl -fsSL -o /tmp/yt.tgz https://github.com/porjo/youtubeuploader/releases/download/v1.25.5/youtubeuploader_1.25.5_Linux_amd64.tar.gz
tar -xzf /tmp/yt.tgz -C /usr/local/bin youtubeuploader && chmod +x /usr/local/bin/youtubeuploader
```

If a binary lives outside `PATH` (virtualenv, wrapper, `nice`), point AutoVOD at
it instead of guessing: `STREAMLINK_BIN=("/opt/venv/bin/streamlink")`.

## Setup

### 1. Create a config per streamer

```sh
cp default.config StreamerName.config
nano StreamerName.config
```

`default.config` documents every setting. The file is parsed with a bash subset
(quotes, `$VARIABLE`, `KEY=(array)`, `#` comments) but is **never executed**, so
a config can neither run code nor break your shell.

Minimum to change for Twitch → YouTube:

```sh
STREAM_SOURCE="twitch"          # twitch | kick | youtube, or set STREAM_URL
STREAMER_CHANNEL=""             # only if the channel differs from the config name
UPLOAD_SERVICE="youtube"
VIDEO_VISIBILITY="unlisted"     # unlisted | private | public
VIDEO_PLAYLIST="$STREAMER_NAME VODs"
```

### 2. YouTube credentials (only for `UPLOAD_SERVICE=youtube`)

1. Create a project on the [Google Developers Console](https://console.developers.google.com).
2. Enable the [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com).
3. Configure the [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent)
   (external, add the channel as a test user) and enable the `.../auth/youtube.upload` scope.
4. Create credentials → *OAuth client ID* → *Web application* → redirect URI
   `http://localhost:8080/oauth2callback`, then download the JSON as
   `client_secrets.json`.
5. Get `request.token`: Google no longer allows the out-of-band flow, so run
   `youtubeuploader -filename sample.mp4` **once on a machine with a browser**
   and copy both `request.token` and `client_secrets.json` next to your config.
6. Both files are looked up relative to the config file (`YOUTUBE_SECRETS`,
   `YOUTUBE_TOKEN_CACHE`), so the working directory no longer matters.

Notes that save a lot of support tickets:

* Uploaded videos of an unaudited API project are forced to **private** and the
  daily quota is low (~6 uploads/day). For unlisted/public and more uploads,
  request an [API audit](https://support.google.com/youtube/contact/yt_api_form);
  it took around 20 days upstream. Written answers and screenshots of the audit
  form are collected in [upstream issue #32](https://github.com/jenslys/AutoVOD/issues/32).
* Tokens stop working when the consent screen stays in "testing": publish it.
* Videos longer than 15 minutes need a verified phone number on the channel.

### 3. rclone (only for `UPLOAD_SERVICE=rclone`)

```sh
rclone config          # create a remote, then set RCLONE_REMOTE="myremote"
rclone lsd myremote:   # verify it works before blaming AutoVOD
```

### 4. Twitch/Kick specifics

```sh
# ad-free / Turbo: put your personal Twitch token into the streamlink flags
STREAMLINK_FLAGS=("--twitch-api-header=Authorization=OAuth YOURTOKEN")

# Kick needs a Chromium-based browser for its JS challenge (streamlink 8.x)
STREAMLINK_EXTRA_ARGS=("--webbrowser" "--webbrowser-headless")

# higher quality (h265/av1 "enhanced broadcasting") — needs a modern player/ffmpeg
STREAMLINK_FLAGS=("--twitch-supported-codecs=h264,h265,av1")
```

`--twitch-disable-ads`, `--twitch-disable-reruns` and `--twitch-disable-hosting`
are **no-ops on streamlink ≥ 7.5.0** (ads are always filtered now); AutoVOD drops
them with a log line if an old config still contains them.

## Configuration reference

| Group | Settings |
|---|---|
| Source | `STREAM_SOURCE`, `STREAMER_CHANNEL`, `STREAM_URL` |
| Sink | `UPLOAD_SERVICE` |
| Streamlink | `STREAMLINK_QUALITY`, `QUALITY_FALLBACK`, `STREAMLINK_FLAGS`, `STREAMLINK_EXTRA_ARGS`, `STREAMLINK_LOGS`, `STREAMLINK_RETRY_STREAMS`, `STREAMLINK_RETRY_MAX`, `STREAMLINK_RETRY_OPEN`, `STREAMLINK_STREAM_TIMEOUT`, `STREAMLINK_HLS_LIVE_EDGE`, `STREAMLINK_BIN` |
| Recording | `VIDEO_DURATION`, `SPLIT_INTO_PARTS`, `SPLIT_VIDEO_DURATION`, `RECONNECT_MAX`, `RECONNECT_DELAY`, `SAVE_ON_FAIL`, `TEMP_DIR` |
| Runtime | `POLL_INTERVAL`, `POLL_INTERVAL_MAX`, `POLL_BACKOFF`, `LOCK`, `STATE_DIR`, `LOG_LEVEL`, `LOG_FILE`, `LOG_MAX_MB`, `LOG_BACKUPS`, `DISCORD_WEBHOOK`, `NOTIFY_ON` |
| Naming | `VIDEO_TITLE`, `VIDEO_DESCRIPTION`, `VIDEO_PLAYLIST`, `RCLONE_FILENAME`, `LOCAL_FILENAME`, `YOUTUBE_FILENAME`, `DATE_FORMAT`, `CLOCK_FORMAT` |
| YouTube | `VIDEO_VISIBILITY`, `VIDEO_TAGS`, `VIDEO_CATEGORY_ID`, `VIDEO_LANGUAGE`, `VIDEO_MADE_FOR_KIDS`, `VIDEO_META_EXTRA_JSON`, `YOUTUBE_RECORD_TO_DISK`, `YOUTUBE_KEEP_LOCAL`, `YOUTUBE_MIN_BYTES`, `YOUTUBE_RATELIMIT`, `YOUTUBE_NOTIFY_SUBSCRIBERS`, `YOUTUBE_SECRETS`, `YOUTUBE_TOKEN_CACHE`, `YOUTUBE_UPLOADER_BIN`, `UPLOAD_RETRY_MAX` |
| rclone | `RCLONE_REMOTE`, `RCLONE_DIR`, `RCLONE_FILEEXT`, `RCLONE_FLAGS`, `RCLONE_RETRIES`, `RCLONE_BIN` |
| Restream | `RTMPS_URL`, `RTMPS_STREAM_KEY`, `AUDIO_BITRATE`, `AUDIO_BITRATE_DEFAULT`, `AUDIO_SAMPLERATE`, `AUDIO_CHANNELS`, `AUDIO_CODEC`, `FILE_FORMAT`, `RESTREAM_VIDEO_CODEC`, `RESTREAM_FFMPEG_LOG`, `RESTREAM_FORCE_KEYFRAMES`, `RESTREAM_GOP` |
| Local | `LOCAL_DIR`, `LOCAL_EXTENSION` |
| Re-encode | `RE_ENCODE`, `RE_ENCODE_CODEC`, `RE_ENCODE_CRF`, `RE_ENCODE_PRESET`, `RE_ENCODE_AUDIO_CODEC`, `RE_ENCODE_LOG`, `FFMPEG_BIN` |
| Legacy (2.x) | `API_CALLS`, `API_URL` (optional metadata fallbacks). `STREAMER_TITLE`, `STREAMER_GAME` are tolerated in old files and ignored — use the `$STREAMER_*`/`{{TITLE}}` placeholders instead |

Short aliases are accepted for the common YouTube settings: `TITLE`,
`DESCRIPTION`, `VISIBILITY`, `PLAYLIST`, `TAGS`, `CATEGORY_ID`, `LANGUAGE`,
`SOURCE_URL` (e.g. `VISIBILITY="public"` instead of `VIDEO_VISIBILITY`).

Every setting can also be overridden per run with an environment variable:
`AUTOVOD_LOG_LEVEL=debug ./autovod.py -n StreamerName` (useful in Docker).

### Placeholders

Usable in `VIDEO_TITLE`, `VIDEO_DESCRIPTION`, `VIDEO_PLAYLIST`,
`RCLONE_FILENAME`, `LOCAL_FILENAME` and `YOUTUBE_FILENAME`:

| Placeholder | Value |
|---|---|
| `{{TITLE}}` `{{GAME}}` | stream title / game (from streamlink, no extra API) |
| `{{STREAMER}}` `{{ID}}` | streamer name / stream id |
| `{{DATE}}` `{{TIME}}` | current date/time (`DATE_FORMAT`, `CLOCK_FORMAT`) |
| `{{PART}}` | current part number (no automatic `Part: N` suffix then) |
| `TIME_DATE` `TIME_CLOCK` | 2.x spellings of `{{DATE}}`/`{{TIME}}` |
| `$STREAMER_TITLE` `$STREAMER_GAME` `$STREAMER_NAME` | 2.x spellings |

Example: `VIDEO_TITLE="{{STREAMER}}: {{TITLE}} [{{DATE}}]"`.

## Usage

```sh
./autovod.py -n StreamerName            # run forever (pm2/systemd/docker)
./autovod.py StreamerName               # 2.x style positional argument works too
./autovod.py -n StreamerName --once     # one check/record cycle, then exit
./autovod.py -n StreamerName --check    # preflight only: is everything installed/configured?
./autovod.py -n StreamerName --list-streams   # live state, title, game, available qualities
./autovod.py -n StreamerName --dry-run  # print the exact commands, write nothing
./autovod.py -n StreamerName --print-config   # parsed config (what AutoVOD really sees)
./AutoVOD.sh -n StreamerName            # compatibility shim, same arguments
```

If exactly one `*.config` (excluding `default.config`) exists, the name may be
omitted. Exit codes: `0` success, `1` stream offline / part failed, `2` config or
preflight problem, `3` another instance is already running for that streamer.

### pm2

```sh
pm2 start AutoVOD.sh --name StreamerName -- StreamerName
pm2 save
pm2 logs StreamerName
```

### systemd

```ini
# /etc/systemd/system/autovod@.service
[Unit]
Description=AutoVOD recorder for %i
After=network-online.target

[Service]
Type=simple
User=autovod
WorkingDirectory=/opt/autovod
ExecStart=/opt/autovod/autovod.py -n %i
Restart=always
RestartSec=30
# SIGTERM makes AutoVOD finish the current part (upload/save) before exiting
KillSignal=SIGTERM
TimeoutStopSec=300

[Install]
WantedBy=multi-user.target
```

```sh
systemctl enable --now autovod@StreamerName
```

### Docker

```sh
cp default.config StreamerName.config     # + client_secrets.json / request.token for YouTube
./buildRunDocker.sh StreamerName          # builds the image, mounts config + secrets + recordings
docker logs -f autovod-StreamerName
```

Config and credentials are mounted, never baked into the image; recordings go to
`./recordings` (or `AUTOVOD_RECORDINGS`). The container ships streamlink in a
virtualenv, ffmpeg, rclone and youtubeuploader, runs as a non-root user and uses
`tini` so `docker stop` finalises the current part. Kick inside Docker needs a
custom image with a headless Chromium (streamlink requirement).

## How a recording session works

1. **Poll** — every `POLL_INTERVAL` seconds (backing off to `POLL_INTERVAL_MAX`
   while offline) AutoVOD asks streamlink for the stream state via
   `streamlink --json`, which also yields title, game and stream id.
2. **Part** — on the first live detection a part is created: the part number
   (per day, persisted in `STATE_DIR`) is incremented, title/description/file
   names are rendered from the placeholders, and a `-Part_N` suffix is added
   from part 2 on — so a restarted recorder can never overwrite an earlier file.
3. **Record** — `streamlink --stdout` writes the part. If the stream drops while
   it is still live, AutoVOD reconnects up to `RECONNECT_MAX` times and appends
   to the same file instead of abandoning the rest of the stream.
4. **Hand over** — the sink uploads/saves the part, retrying `UPLOAD_RETRY_MAX`
   times; `SAVE_ON_FAIL=true` keeps the file on a permanent failure. Failed or
   interrupted parts stay visible as `*.part`, `*.raw` or `*.failed.mkv`.
5. **Repeat** — if the part ended because the duration limit was reached while
   the stream continued, the next part starts immediately; otherwise AutoVOD
   goes back to polling. `SIGTERM`/`SIGINT` finishes the current part first.

One instance per streamer is enforced with a lock file (`STATE_DIR/<name>.lock`).

## Migrating from 2.x

* `git pull`, then run `./autovod.py -n StreamerName --check`.
* Existing `*.config` files keep working; `AutoVOD.sh` is a shim, so pm2 units
  need no change. `UPLOAD_SERVICE` values are unchanged.
* `SPLIT_INTO_PARTS=true` works now (it crashed on the first part in 2.x).
* YouTube uploads buffer each part on disk (`YOUTUBE_RECORD_TO_DISK=true`) so a
  failed upload can be retried instead of losing the part. Set it to `false` for
  the old pipe-only behaviour (upload must then succeed in one go).
* `AUDIO_BITRATE` is a real bitrate (kbit/s) for re-streaming. A legacy value
  like `44100` is detected, translated to `128k` + `44100 Hz` and logged.
* `API_CALLS`/`API_URL` are optional legacy fallbacks — streamlink already
  provides the metadata, so the third-party API wrapper is no longer needed.
* New: `--check`, `--dry-run`, `--list-streams`, `--print-config`, log files
  with rotation, Discord notifications, per-streamer locking, graceful
  shutdown, configurable binary paths, `RECONNECT_*`/`UPLOAD_RETRY_*`.

## Troubleshooting

**"Broken pipe" / an upload failed** — the reason is now in the log (child
  process stderr is no longer sent to `/dev/null`). Typical causes: YouTube quota
  reached, expired `request.token`, rclone remote misconfigured, or the provider
  throttling the upload (use `YOUTUBE_RATELIMIT`, `RCLONE_FLAGS=("--bwlimit" "8M")`).
  With the default settings the part is kept and the upload is retried.

**Videos are private** — the API project is not audited (see above).

**Videos are shorter than 15 minutes / the upload stops early** — verify the
  channel's phone number, or lower `VIDEO_DURATION`/use `SPLIT_INTO_PARTS`.

**`exit 3` in the logs** — another AutoVOD process holds the lock for this
  streamer. `pm2 list`, `systemctl status autovod@StreamerName`, or check
  `STATE_DIR/<name>.lock` for the PID.

**Nothing happens although the stream is live** — run `--list-streams`: it shows
  whether streamlink can see the stream and which qualities exist. A requested
  quality that is not offered now falls back to `QUALITY_FALLBACK`.

**Kick URL fails** — streamlink needs a browser for Kick's JS challenge, add
  `STREAMLINK_EXTRA_ARGS=("--webbrowser" "--webbrowser-headless")`.

**Part numbering looks odd after a restart** — intended: the counter lives per
  day in `STATE_DIR/<name>.state.json` so nothing is overwritten. Delete the file
  to start again at part 1.

## Development

```sh
python -m unittest discover -s tests -t . -v     # 62 unit + end-to-end tests
```

The end-to-end tests run the real CLI against stub `streamlink`/`ffmpeg`/
`rclone`/`youtubeuploader` binaries (`tests/stubs/`) and assert exit codes, byte
counts, produced file names, temp-file cleanup and the exact argv handed to each
child process — no network, no credentials. CI runs them on Linux and Windows.

## Credits

* Original script by [arnicel](https://github.com/arnicel/autoTwitchToYouTube),
  2.x by [jenslys](https://github.com/jenslys/autovod)
* [YoutubeUploader](https://github.com/porjo/youtubeuploader) by porjo
* [Streamlink](https://github.com/streamlink/streamlink)
* Icon by [xyaia](https://macosicons.com/#/u/xyaia)

## License

Licensed under the [MIT License](LICENSE.md).
