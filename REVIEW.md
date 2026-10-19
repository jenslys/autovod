# AutoVOD 2.x review, and what 3.x changes

Scope: the repository as of upstream `master` @ `9b185a1` (2025-09-13), i.e.
`AutoVOD.sh` (2.x), `default.config`, `install.sh`, `Dockerfile`,
`buildRunDocker.sh`, `.github/workflows/test_bash_install.yml` and `README.md`.

Method: read the sources, ran the 2.x script against stub binaries
(`streamlink`, `curl`, `jq`) to reproduce the failure modes, checked every
external interface it depends on against the *current* upstream versions
(streamlink 8.x, youtubeuploader, rclone, pillow-free Python 3.12 base images),
and then wrote a replacement (`autovod.py`) plus a test suite
(`tests/test_unit.py`, `tests/test_integration.py`, 62 tests) to prove the
fixes. Everything in the "evidence" column below was executed, not inferred.

The 2.x implementation is kept unchanged in `legacy/AutoVOD-bash.sh` for
reference. `AutoVOD.sh` is now a thin compatibility shim that forwards to
`autovod.py`, so existing pm2/systemd units keep working.

---

## 1. Findings overview

| # | Severity | Finding | Evidence | 3.x |
|---|----------|---------|----------|-----|
| 1 | critical | `SPLIT_INTO_PARTS=true` crashes on the first part: `TIME_DATE_CHECK` is read before it is ever set (`set -u`) — the whole split feature is unusable | `AutoVOD-bash.sh:227` → `line 227: TIME_DATE_CHECK: unbound variable` | fixed (state file, per-day part counter) |
| 2 | critical | A stream title / game from the Twitch metadata API is injected into `eval` → arbitrary commands run as the AutoVOD user | `AutoVOD-bash.sh:207-208`; a title of `$(touch /tmp/verif/PWNED2)` created the file | fixed (pure Python string replacement) |
| 3 | critical | Title containing `}` (or other shell metacharacters) breaks the `eval` and aborts the loop → recording stops silently | `eval_test.sh` → `line 12: title}: command not found` | fixed |
| 4 | high | Metadata API answering `Too many requests, please try again later.` leaves `FETCHED_TITLE` unset → `set -u` kills the script | `AutoVOD-bash.sh:186,197` → `line 197: FETCHED_TITLE: unbound variable` | fixed (no third-party API needed any more) |
| 5 | high | Any missing variable on a code path is fatal: `RE_ENCODE`, `VIDEO_TITLE`, `RCLONE_*`, … → `unbound variable` instead of a usable message | `AutoVOD-bash.sh:157,292,315,354` → `line 354: RE_ENCODE: unbound variable` | fixed (defaults + `--check`) |
| 6 | high | YouTube upload is a bare pipe: when `youtubeuploader` dies (quota, expiry, network) `streamlink` gets SIGPIPE and **the whole part is lost**, with `>/dev/null 2>&1` hiding the reason (this is upstream issue #43 "Broken pipe") | `AutoVOD-bash.sh:275` | fixed: `YOUTUBE_RECORD_TO_DISK=true` records the part first, retries the upload from disk |
| 7 | high | `UPLOAD_SERVICE=restream` sets the audio **sample rate** from `AUDIO_BITRATE`, so the bitrate knob does nothing and `-ar 44100` is passed as `-ar <bitrate>`; `-re` throttles a live input for no benefit | `AutoVOD-bash.sh:333` | fixed (`-b:a 128k`, `-ar 44100`, no `-re`, legacy 2.x value auto-detected and warned about) |
| 8 | high | No locking: two processes for the same streamer (double `pm2 start`, a restart racing the old process) record concurrently into the same target file, and both write `/tmp/input.$STREAMER_NAME` | `AutoVOD-bash.sh:272,313` | fixed (per-streamer lock, exit code 3) |
| 9 | medium | A stream drop ends the recording; the loop waits 60 s and starts a **new part with the same file name**, so `rclone copyto` overwrites the first one and YouTube gets a duplicate title | `AutoVOD-bash.sh:313,344,395` | fixed (reconnect + append, part suffix, `unique_path`) |
| 10 | medium | With `SPLIT_INTO_PARTS=false` and a stream longer than `VIDEO_DURATION`, the second part reuses the same file name/title | `AutoVOD-bash.sh:313,363` | fixed (auto part numbering) |
| 11 | medium | Liveness check runs `streamlink URL` with no quality, no flags and no log level — it opens a real player session, spams logs and ignores `STREAMLINK_FLAGS` (so e.g. auth/sub-only handling differs from the recording call) | `AutoVOD-bash.sh:141` | fixed (`--json` probe, exit-code independent, 15 s) |
| 12 | medium | Default `STREAMLINK_FLAGS=("--twitch-disable-reruns" "--twitch-disable-hosting")` are **no-ops on streamlink ≥ 7.5.0** and print a deprecation warning on every call; `--twitch-disable-ads` is gone completely | `streamlink twitch.tv/x best --twitch-disable-reruns` → `[warnings][streamlinkdeprecation] The --twitch-disable-reruns plugin argument has been disabled and will be removed in the future` | fixed (filtered with a log line, `--twitch-supported-codecs` added) |
| 13 | medium | No quality fallback: requesting `1080p60` on a channel that does not offer it fails forever, the log only says "Stream is not live" | `STREAMLINK_QUALITY` used as a single value | fixed (`QUALITY_FALLBACK`, streamlink gets `1080p60,best`) |
| 14 | medium | Fixed `sleep 60` while offline → 1440 real stream-probe connections per day; no backoff, no `--retry-*`, no timeout configuration | `AutoVOD-bash.sh:395` | fixed (backoff to `POLL_INTERVAL_MAX`, `--retry-streams/--retry-max/--retry-open/--stream-timeout`) |
| 15 | medium | Container-side `Dockerfile` bakes `client_secrets.json` + `request.token` + the streamer config into the image and *fails to build* for rclone/local setups (upstream #62); no ffmpeg, so re-encode/restream are broken inside Docker; runs as root; no volume for recordings; installs the now useless `cloudscraper` | `Dockerfile` `COPY ${TWITCH_USER}.config`, `COPY client_secrets.json` | fixed (mount at runtime, ffmpeg included, non-root, volumes, tini, venv) |
| 16 | medium | `install.sh` runs a full `apt-get upgrade` of the user's server, installs streamlink with `pip3 install` as root into the system Python (fails with PEP 668 "externally managed environment" on Debian 12/Ubuntu 24.04), checks packages with `dpkg` on dnf systems, never installs ffmpeg, and pins three different youtubeuploader versions (README 23.03, install.sh 24.01, Dockerfile v1.25.5) with no CPU-arch detection | `install.sh:29,64,73-74`, README `:66` | fixed (no dist-upgrade, venv/pipx, arch detection, ffmpeg, idempotent) |
| 17 | medium | CI is meaningless and broken: workflow runs `./install.sh` twice on the runner (which mutates the runner and needs sudo), uses `actions/checkout@v2` (Node 12/16, deprecated), no shellcheck step (it was deleted in `22ddb42`) | `.github/workflows/test_bash_install.yml` | fixed (`.github/workflows/ci.yml`: bash -n, shellcheck, unit+integration tests on 3.8/3.12 Linux and Windows, docker build) |
| 18 | low | `request.token`, `client_secrets.json` and the config are resolved relative to the **current working directory**, not the script/config directory | `AutoVOD-bash.sh:259`, config `test -f "$config_file"` | fixed (paths relative to the config file) |
| 19 | low | Deprecated `test -f a -a -f b` (POSIX-XSI), `TIME_DATE='date +%d-%m-%y'` string-command trick, `mapfile < <(ls *.config)` glob handling | `AutoVOD-bash.sh:5-7,66,259` | n/a (dead code removed) |
| 20 | low | README documents settings that do not exist / contradict the code: `STREAMLINK_OPTIONS` (it is `STREAMLINK_FLAGS`), `docker build --build-arg USERNAME=` (Dockerfile expects `TWITCH_USER` → build fails), 2.x "no file on disk" claim, install commands collapsed into single lines | README `:224,261`; `Dockerfile` `ARG TWITCH_USER` | fixed (README rewritten against the real code) |
| 21 | low | `$STREAMER_TITLE` / `$STREAMER_GAME` placeholders are documented but do not work: the config is sourced with `set -a`, so `"$STREAMER_TITLE"` is expanded to `initial_title` before the script could replace it | `default.config:17-18,35` | fixed (`{{TITLE}}`, `{{GAME}}`, … and the `initial_title` sentinel honoured) |
| 22 | low | `buildRunDocker.sh` passes the name as a Docker `CMD` but nothing validates that `<name>.config` exists; `docker run -d autovod <name>` in the README omits the volume mounts, so recordings land in the container layer | `buildRunDocker.sh`, README `:262-266` | fixed |
| 23 | info | Kick support was removed upstream (`3201e9a`) but the option stayed. Kick is built into streamlink again, **but it needs a browser** to solve the JS challenge: `--webbrowser` (+ `--webbrowser-headless`), while the 2.x defaults assume it is not needed | streamlink plugin docs: *kick — web browser required for solving a JS challenge* | documented, `--check` warns; set `STREAMLINK_EXTRA_ARGS=("--webbrowser" "--webbrowser-headless")` in a container |
| 24 | info | Twitch "enhanced broadcasting" (h265/av1, fMP4) is not taken into account: without `--twitch-supported-codecs` you silently stay on the lower qualities, and copied h265 does not play on YouTube in re-stream mode | streamlink Twitch docs, "Higher quality streams" | `--twitch-supported-codecs=h264,h265,av1` in the new default config, h264 is forced for the restream service |
| 25 | info | No `--version`, `--dry-run`, `--check`, `--print-config`, no log file/rotation, no notification, no graceful shutdown (pm2 restart kills the record mid-part and the data is thrown away) | — | added |

Upstream issues this addresses: **#43** (broken pipe), **#62** (Docker + youtube
files), **#67/#81** (Dockerfile), **#73** (shellcheck action), **#91** (migrate
to Python), and partially **#94** (HLS segment errors: the reconnecting
recorder now survives them instead of dropping the rest of the stream).
Not in scope: **#18** (chat replay), **#54** (Twitch VOD instead of a live
recording — that needs Twitch's own export), **#32** (documentation text).

---

## 2. Evidence

Reproduced against the 2.x script with stub `streamlink`/`curl`/`jq` in `PATH`:

```console
$ bash AutoVOD-bash.sh tester                     # SPLIT_INTO_PARTS=true
22:00:43| Stream is live
AutoVOD-bash.sh: line 227: TIME_DATE_CHECK: unbound variable

$ bash AutoVOD-bash.sh tester                     # metadata API: "Too many requests…"
22:00:53| Trying to fetch stream metadata
22:00:53| Too many requests, please try again later.
AutoVOD-bash.sh: line 197: FETCHED_TITLE: unbound variable

$ bash AutoVOD-bash.sh tester                     # title = '$(touch /tmp/verif/PWNED2)'
marker created: YES-CODE-EXECUTED

$ bash AutoVOD-bash.sh tester                     # minimal config without RE_ENCODE
AutoVOD-bash.sh: line 354: RE_ENCODE: unbound variable
```

Current streamlink behaviour that the 2.x defaults ignore:

```console
$ streamlink twitch.tv/jenslys best --twitch-disable-reruns
[warnings][streamlinkdeprecation] The --twitch-disable-reruns plugin argument has been disabled and will be removed in the future

$ streamlink --json twitch.tv/lofigirl        # the modern liveness+metadata source
{"plugin":"twitch","metadata":{"id":"318011710180","author":"LofiGirl","category":"Music","title":"lofi hip hop radio"},
 "streams":{"audio_only":{…},"160p":{…},"360p":{…},"480p":{…},"720p":{…},"1080p":{…},"worst":{…},"best":{…}}}
```

The 3.x replacement is verified by 62 automated tests, run with stubbed
binaries so the complete pipeline is covered:

```console
$ python -m unittest discover -s tests -t .            # 62 tests, ~53 s
OK
```

Included: exit codes, file layout, part numbering across restarts, reconnect +
append, rclone target paths, youtube metadata/privacy/playlist/retry/keep-local,
pipe mode, restream ffmpeg arguments, lock refusal, dry-run, `--check`,
`--list-streams`, and two regressions that the tests found during development
(a logging thread stealing bytes from the streamlink→sink pipe, and part
metadata not being rendered into the YouTube upload).

---

## 3. What 3.x does differently

* **One Python file, stdlib only** (`autovod.py`, ~1800 lines): no `jq`, no
  `bash`, no `/tmp` file as an inter-process bus, config parsed with a
  bash-subset parser (never executed).
* **Sinks**: `local`, `rclone`, `youtube`, `restream` — same names as before,
  plus per-part retries, reconnect-while-live, `unique_path` collision
  protection and `SAVE_ON_FAIL` for every sink.
* **Metadata from streamlink itself** (`streamlink --json`): title, game and
  stream id without the third-party `twitch-api-wrapper`; the old
  `API_CALLS`/`API_URL` settings still work as a fallback.
* **Templates**: `{{TITLE}} {{GAME}} {{STREAMER}} {{ID}} {{DATE}} {{TIME}}
  {{PART}}` plus the 2.x `TIME_DATE`/`TIME_CLOCK`/`$STREAMER_TITLE`/
  `$STREAMER_GAME`/`initial_title` spellings.
* **Operations**: file lock per streamer, per-day part state
  (`.autovod/<name>.state.json`), backoff polling, graceful SIGTERM/SIGINT that
  finalises the current part, optional log file with rotation, optional Discord
  webhook, `--check` / `--dry-run` / `--list-streams` / `--print-config`.
* **Configurable binaries** (`STREAMLINK_BIN`, `FFMPEG_BIN`, `RCLONE_BIN`,
  `YOUTUBE_UPLOADER_BIN`, as arrays) — needed for venv installs, wrappers, and
  what made the test suite possible.
* **Docs/CI**: README rewritten against the real code, real CI
  (bash -n + shellcheck + tests on Linux/Windows + docker build).

## 4. Compatibility

* Existing `*.config` files are read as-is; unknown/new keys are optional.
* Existing pm2 units keep working (`AutoVOD.sh` is a shim now).
* `UPLOAD_SERVICE=youtube` with `YOUTUBE_RECORD_TO_DISK=true` (the new default)
  buffers each part on disk before uploading. That changes the "nothing is
  written to disk" property of 2.x in exchange for not losing a part when the
  upload breaks. Set `YOUTUBE_RECORD_TO_DISK=false` for the old behaviour.
* `AUDIO_BITRATE=44100` (2.x sample rate) is detected and translated to
  `128k` + `44100 Hz` with a warning instead of uploading broken audio settings.

## 5. Known limitations

* Chat replay (#18) and "download the finished official VOD" (#54) are not
  implemented — a live recorder cannot provide either.
* `AUDIO_BITRATE`/`AUDIO_SAMPLERATE` are split into two settings now; the
  auto-detection only migrates the exact 2.x meaning, not `8000`/`16000`.
* Kick needs a Chromium-based browser in the environment (streamlink
  requirement, not ours); the Docker image does not ship one, so Kick inside
  the container needs a custom image.
* The reconnect-append for `local`/`rclone` writes one file per part; a
  mid-stream drop leaves a short discontinuity at the seam. fMP4 sources (Twitch
  h265/av1) may need a remux (`ffmpeg -c copy`) before playback in strict
  players — same as a 2.x restart, but now without losing the rest of the stream.
* `--hls-duration` still cuts parts by duration, not by keyframe, which is why
  ffmpeg-based re-streaming needed `-g` handling.
