#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AutoVOD 3.x - realtime recorder + uploader for Twitch / Kick / YouTube Live.

Records a live stream with streamlink and hands it to one of four sinks:

    youtube   streamlink -> youtubeuploader (direct upload, no transcoding)
    rclone    streamlink -> (optional ffmpeg re-encode) -> rclone copyto
    restream  streamlink -> ffmpeg -> RTMP(S) endpoint (re-stream)
    local     streamlink -> local file

Why a rewrite: the 2.x bash script could not safely template stream metadata
(eval based substitution), crashed on undefined variables while splitting parts
(set -u), lost whole recordings when a single pipe broke, had no locking, no
retry/backoff and no way to see why an upload failed (every child's stderr went
to /dev/null).  See REVIEW.md for the full list and the evidence.

Design goals
    * stdlib only (no jq, no bash), Python 3.8+
    * never lose recorded data: recording to disk is the default for youtube too
    * deterministic config parsing of the existing *.config files (bash subset)
    * structured, timestamped logs including child process stderr
    * idempotent parts: per-streamer state so restarts continue numbering
    * one instance per streamer (file lock), graceful shutdown (pm2/systemd)

Usage:
    ./autovod.py -n StreamerName          # uses StreamerName.config
    ./autovod.py -n StreamerName --once   # single check/record cycle
    ./autovod.py --check -n StreamerName  # preflight only, changes nothing
    ./autovod.py -n StreamerName --list-streams
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

VERSION = "3.1.0"
PROG = "autovod"

# ----------------------------------------------------------------------------
# logging
# ----------------------------------------------------------------------------

LEVELS = {"none": 100, "error": 40, "warning": 30, "info": 20, "debug": 10}

#: streamlink plugin arguments that were disabled upstream (>= 7.5.0) and only
#: produce deprecation warnings today.  They are filtered out of the user's
#: STREAMLINK_FLAGS with an explanatory log line instead of silently breaking.
DEPRECATED_STREAMLINK_FLAGS = (
    "--twitch-disable-ads",
    "--twitch-disable-reruns",
    "--twitch-disable-hosting",
)

#: ffmpeg container name per file extension (used by the re-encode step)
CONTAINER_BY_EXT = {
    "mkv": "matroska",
    "webm": "webm",
    "mp4": "mp4",
    "mov": "mov",
    "ts": "mpegts",
    "flv": "flv",
}


class Log:
    """Timestamped logger writing to stdout and (optionally) a rotating file."""

    def __init__(self, level="info", path=None, max_mb=10, backups=3):
        self.level = LEVELS.get(str(level).lower(), 20)
        self.path = path
        self.max_bytes = int(float(max_mb) * 1024 * 1024)
        self.backups = int(backups)
        self._lock = threading.Lock()
        self._fh = None
        if path:
            self._open()

    def _open(self):
        try:
            directory = os.path.dirname(os.path.abspath(self.path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            if self.max_bytes and os.path.exists(self.path) and os.path.getsize(self.path) >= self.max_bytes:
                self._rotate()
            self._fh = open(self.path, "a", encoding="utf-8")
        except OSError as exc:
            self._fh = None
            print("warning: cannot open log file %s: %s" % (self.path, exc))

    def _rotate(self):
        for index in range(self.backups - 1, 0, -1):
            src = "%s.%d" % (self.path, index)
            dst = "%s.%d" % (self.path, index + 1)
            if os.path.exists(src):
                try:
                    os.replace(src, dst)
                except OSError:
                    pass
        try:
            os.replace(self.path, self.path + ".1")
        except OSError:
            pass

    def emit(self, level_no, level_name, message):
        if level_no < self.level:
            return
        line = "%s | %-7s | %s" % (time.strftime("%H:%M:%S"), level_name.upper(), message)
        with self._lock:
            print(line, flush=True)
            if self._fh:
                try:
                    self._fh.write(line + "\n")
                    self._fh.flush()
                except OSError:
                    pass

    def debug(self, msg):
        self.emit(10, "debug", msg)

    def info(self, msg):
        self.emit(20, "info", msg)

    def warning(self, msg):
        self.emit(30, "warning", msg)

    def error(self, msg):
        self.emit(40, "error", msg)

    def child(self, prefix, line):
        """Log a line produced by a child process."""
        self.emit(20, "info", "[%s] %s" % (prefix, line.rstrip()))

    def close(self):
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None


LOG = Log()


class ConfigError(Exception):
    """Raised for invalid or incomplete configuration."""


# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------

_DURATION_UNITS_RE = re.compile(
    r"^\s*(?:(?P<h>\d+)\s*h)?\s*(?:(?P<m>\d+)\s*m)?\s*(?:(?P<s>\d+(?:\.\d+)?)\s*s)?\s*$",
    re.IGNORECASE,
)


def parse_duration(value, default=None):
    """Parse '12:00:00', '06:00:00', '1:30', '30m', '1h30m', '45' or '45s'.

    Returns seconds, or ``default`` for an empty value.
    """
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    if text.isdigit():
        return int(text)
    if ":" in text:
        parts = text.split(":")
        if len(parts) > 3:
            raise ConfigError("cannot parse duration %r (use HH:MM:SS)" % value)
        try:
            numbers = [float(part) for part in parts]
        except ValueError:
            raise ConfigError("cannot parse duration %r (use HH:MM:SS)" % value)
        if len(numbers) == 1:
            return int(numbers[0])
        if len(numbers) == 2:      # MM:SS
            minutes, seconds = numbers
            return int(minutes * 60 + seconds)
        hours, minutes, seconds = numbers
        return int(hours * 3600 + minutes * 60 + seconds)
    match = _DURATION_UNITS_RE.match(text)
    if match and any(match.group(group) for group in ("h", "m", "s")):
        hours = int(match.group("h") or 0)
        minutes = int(match.group("m") or 0)
        seconds = float(match.group("s") or 0)
        return int(hours * 3600 + minutes * 60 + seconds)
    raise ConfigError("cannot parse duration %r (use HH:MM:SS, 30m or 1h30m)" % value)


def format_duration(seconds):
    seconds = max(0, int(seconds))
    return "%02d:%02d:%02d" % (seconds // 3600, (seconds % 3600) // 60, seconds % 60)


def human_bytes(num):
    step = 1024.0
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(num) < step:
            return "%.1f %s" % (num, unit)
        num /= step
    return "%.1f PiB" % num


def good_filename(value):
    """Make a string safe to use inside a file name (keeps it recognisable)."""
    value = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "-", str(value))
    value = re.sub(r"\s+", " ", value).strip()
    return value


def which(program):
    return shutil.which(program)


# ----------------------------------------------------------------------------
# config parser (bash subset - the existing *.config files keep working)
# ----------------------------------------------------------------------------

_ASSIGN_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


class Config:
    """Parse a ``StreamerName.config`` file.

    Supported syntax (everything the 2.x default.config and real world configs
    use)::

        KEY=value               # unquoted
        KEY="a $OTHER b"        # double quotes, $VAR expanded
        KEY='literal $VAR'      # single quotes, no expansion
        KEY=("a" "b" "$C")      # arrays (STREAMLINK_FLAGS)
        # comment / #? comment

    Deliberately not a shell: a config file cannot execute code.
    """

    ALIASES = {
        "TITLE": "VIDEO_TITLE",
        "DESCRIPTION": "VIDEO_DESCRIPTION",
        "VISIBILITY": "VIDEO_VISIBILITY",
        "PLAYLIST": "VIDEO_PLAYLIST",
        "TAGS": "VIDEO_TAGS",
        "CATEGORY_ID": "VIDEO_CATEGORY_ID",
        "LANGUAGE": "VIDEO_LANGUAGE",
        "SOURCE_URL": "STREAM_URL",
    }

    def __init__(self, path, streamer=None, env_overrides=True):
        self.path = os.path.abspath(path)
        self.dir = os.path.dirname(self.path)
        self.streamer = streamer or os.path.splitext(os.path.basename(self.path))[0]
        self.values = {}
        self.arrays = {}
        self.warnings = []
        self.env = dict(os.environ)
        self.env["STREAMER_NAME"] = self.streamer
        self._parse()
        for alias, target in self.ALIASES.items():
            if alias in self.values and target not in self.values:
                self.values[target] = self.values.pop(alias)
        if env_overrides:
            self._apply_env_overrides()

    # -- parsing ------------------------------------------------------------
    def _parse(self):
        if not os.path.isfile(self.path):
            raise ConfigError("config file not found: %s" % self.path)
        with open(self.path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.read().replace("\r\n", "\n").split("\n")

        buffer = None  # collecting a multi line array
        for number, raw in enumerate(lines, start=1):
            if buffer is not None:
                buffer += "\n" + raw
                if ")" in raw:
                    self._store_array(buffer, number)
                    buffer = None
                continue
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("set ") or stripped.startswith("unset "):
                continue  # 'set -a' / 'set +a' markers
            match = _ASSIGN_RE.match(raw)
            if not match:
                self.warnings.append("line %d ignored (not KEY=value): %s" % (number, stripped))
                continue
            key, rest = match.group(1), match.group(2)
            if rest.lstrip().startswith("("):
                tail = rest.lstrip()[1:]
                if ")" in tail:
                    self._store_array(key + "=" + rest, number, key=key)
                else:
                    buffer = key + "=" + rest
                continue
            self._store_scalar(key, rest)

    def _store_scalar(self, key, rest):
        words = self._parse_words(rest)
        value = " ".join(words) if words else ""
        self.values[key] = value
        self.env[key] = value

    def _store_array(self, text, number, key=None):
        if key is None:
            match = _ASSIGN_RE.match(text.split("\n", 1)[0])
            if not match:
                self.warnings.append("line %d: broken array, ignored" % number)
                return
            key = match.group(1)
        inner = text[text.index("(") + 1:]
        inner = inner.rsplit(")", 1)[0]
        items = self._parse_words(inner)
        self.arrays[key] = items
        self.env[key] = " ".join(items)

    def _parse_words(self, text):
        """Split into shell-like words honouring quoting, then expand."""
        words = []
        current = []
        pending_quote = None
        index = 0
        length = len(text)
        while index < length:
            char = text[index]
            if pending_quote:
                current.append(char)
                if char == pending_quote:
                    pending_quote = None
                index += 1
                continue
            if char in ("'", '"'):
                pending_quote = char
                current.append(char)
                index += 1
                continue
            if char == "#" and (not current or current[-1].isspace()):
                break  # comment starts here
            if char.isspace():
                if current:
                    words.append("".join(current))
                    current = []
                index += 1
                continue
            if char == "\\" and index + 1 < length:
                current.append(text[index:index + 2])
                index += 2
                continue
            current.append(char)
            index += 1
        if current:
            words.append("".join(current))
        return [self._expand(word) for word in words]

    def _expand(self, word):
        out = []
        index = 0
        length = len(word)
        while index < length:
            char = word[index]
            if char == "\\" and index + 1 < length:
                out.append(word[index + 1])
                index += 2
                continue
            if char == "'":
                end = word.find("'", index + 1)
                if end == -1:
                    raise ConfigError("unterminated single quote in %s" % self.path)
                out.append(word[index + 1:end])
                index = end + 1
                continue
            if char == '"':
                index += 1
                while index < length and word[index] != '"':
                    if word[index] == "\\" and index + 1 < length and word[index + 1] in '"\\$`':
                        out.append(word[index + 1])
                        index += 2
                        continue
                    if word[index] == "$":
                        value, index = self._expand_var(word, index)
                        out.append(value)
                        continue
                    out.append(word[index])
                    index += 1
                index += 1  # closing quote
                continue
            if char == "$":
                value, index = self._expand_var(word, index)
                out.append(value)
                continue
            out.append(char)
            index += 1
        return "".join(out)

    def _expand_var(self, word, index):
        """Expand $VAR, ${VAR}, ${VAR:-default} at ``index`` (pointing at $)."""
        index += 1
        if index < len(word) and word[index] == "{":
            end = word.find("}", index)
            if end == -1:
                return "$", index
            name = word[index + 1:end]
            index = end + 1
        else:
            match = re.match(r"[A-Za-z_][A-Za-z0-9_]*|\d", word[index:])
            if not match:
                return "$", index
            name = match.group(0)
            index += len(name)
        default = ""
        if ":-" in name:
            name, default = name.split(":-", 1)
        if name in self.env:
            return str(self.env[name]), index
        if default:
            return default, index
        if name:
            self.warnings.append("undefined variable $%s expanded to empty string" % name)
        return "", index

    def _apply_env_overrides(self):
        prefix = "AUTOVOD_"
        for key, value in os.environ.items():
            if key.startswith(prefix) and len(key) > len(prefix):
                self.values[key[len(prefix):]] = value

    # -- accessors ----------------------------------------------------------
    def get(self, key, default=""):
        value = self.values.get(key)
        return default if value is None else value

    def get_list(self, key, default=None):
        if key in self.arrays:
            return list(self.arrays[key])
        raw = self.get(key, "")
        if str(raw).strip() == "":
            return list(default or [])
        return str(raw).split()

    def get_bool(self, key, default=False):
        raw = self.values.get(key)
        if raw is None or str(raw).strip() == "":
            return default
        return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")

    def get_int(self, key, default=0):
        raw = self.values.get(key)
        if raw is None or str(raw).strip() == "":
            return default
        try:
            return int(float(str(raw).strip()))
        except ValueError:
            raise ConfigError("%s must be a number, got %r" % (key, raw))

    def get_float(self, key, default=0.0):
        raw = self.values.get(key)
        if raw is None or str(raw).strip() == "":
            return default
        try:
            return float(str(raw).strip())
        except ValueError:
            raise ConfigError("%s must be a number, got %r" % (key, raw))

    def path_in_config_dir(self, value):
        if not value:
            return value
        return value if os.path.isabs(value) else os.path.join(self.dir, value)

    def require(self, *keys):
        missing = [key for key in keys if str(self.get(key, "")).strip() == "" and key not in self.arrays]
        if missing:
            raise ConfigError(
                "missing required setting(s) in %s: %s"
                % (os.path.basename(self.path), ", ".join(missing))
            )

    def describe(self):
        rows = []
        for key in sorted(set(list(self.values) + list(self.arrays))):
            if key in self.arrays:
                rows.append("%s=(%s)" % (key, " ".join(self.arrays[key])))
            else:
                rows.append("%s=%s" % (key, self.values[key]))
        return "\n".join(rows)


# ----------------------------------------------------------------------------
# state + lock
# ----------------------------------------------------------------------------

class State:
    """Persisted per-streamer counters so restarts do not renumber or overwrite."""

    def __init__(self, path):
        self.path = path
        self.data = {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                self.data = loaded
        except (OSError, ValueError):
            self.data = {}

    def save(self):
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


class LockError(Exception):
    pass


class FileLock:
    """Cross platform exclusive lock (fcntl / msvcrt)."""

    def __init__(self, path):
        self.path = path
        self._fh = None
        self._impl = None

    def acquire(self):
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._fh = open(self.path, "a+")
        try:
            import fcntl  # type: ignore
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._impl = "fcntl"
        except ImportError:
            try:
                import msvcrt  # type: ignore
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                self._impl = "msvcrt"
            except Exception as exc:  # noqa: BLE001
                self._close()
                raise LockError(str(exc))
        except OSError as exc:
            self._close()
            raise LockError(str(exc))
        self._fh.seek(0)
        self._fh.truncate()
        self._fh.write("%d\n" % os.getpid())
        self._fh.flush()

    def _close(self):
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    def release(self):
        if not self._fh:
            return
        try:
            if self._impl == "fcntl":
                import fcntl  # type: ignore
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            elif self._impl == "msvcrt":
                import msvcrt  # type: ignore
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:  # noqa: BLE001
            pass
        self._close()


# ----------------------------------------------------------------------------
# child processes
# ----------------------------------------------------------------------------

class ChildProcess:
    """A process plus a thread that forwards its output to the logger."""

    def __init__(self, argv, log, name=None, stdout=None, stderr=subprocess.PIPE, stdin=None,
                 pump_stdout=None):
        self.argv = argv
        self.log = log
        self.name = name or os.path.basename(argv[0])
        self.stderr_lines = []
        self.stdout_lines = []
        self.returncode = None
        creationflags = 0
        preexec = None
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            preexec = os.setsid
        self.proc = subprocess.Popen(
            argv,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            preexec_fn=preexec,
            bufsize=0,
        )
        self._threads = []
        if stderr is subprocess.PIPE:
            self._threads.append(self._pump(self.proc.stderr, self.stderr_lines))
        # Only read stdout ourselves when nobody else consumes the pipe: a
        # thread that drains the pipe would steal data from the next process
        # in the chain.
        if pump_stdout is None:
            pump_stdout = stdout is subprocess.PIPE
        if pump_stdout and stdout is subprocess.PIPE:
            self._threads.append(self._pump(self.proc.stdout, self.stdout_lines))

    def _pump(self, stream, sink):
        def run():
            try:
                for raw in iter(stream.readline, b""):
                    line = raw.decode("utf-8", "replace")
                    sink.append(line.rstrip("\n"))
                    self.log.child(self.name, line)
            except (ValueError, OSError):
                pass
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def poll(self):
        return self.proc.poll()

    def wait(self, timeout=None):
        try:
            self.returncode = self.proc.wait(timeout=timeout)
        finally:
            for thread in self._threads:
                thread.join(timeout=5)
        return self.returncode

    def terminate(self, grace=10):
        if self.proc.poll() is not None:
            self.returncode = self.proc.returncode
            return self.returncode
        try:
            if os.name == "nt":
                self.proc.terminate()
            else:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                self.proc.terminate()
            except OSError:
                pass
        try:
            return self.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self.kill()
            return self.wait(timeout=grace)

    def kill(self):
        try:
            if os.name == "nt":
                self.proc.kill()
            else:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass


def run_capture(argv, log, name=None, timeout=None):
    """Run a short command to completion, returning (returncode, stdout_text)."""
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        log.error("%s timed out" % (name or argv[0]))
    text = out.decode("utf-8", "replace")
    for line in err.decode("utf-8", "replace").splitlines():
        if line.strip():
            log.child(name or os.path.basename(argv[0]), line)
    return proc.returncode, text


# ----------------------------------------------------------------------------
# streamlink probe
# ----------------------------------------------------------------------------

class Probe:
    def __init__(self, live, streams, metadata, error=None, raw=None):
        self.live = live
        self.streams = streams or {}
        self.metadata = metadata or {}
        self.error = error
        self.raw = raw

    @property
    def title(self):
        return str(self.metadata.get("title") or "").strip()

    @property
    def game(self):
        for key in ("category", "game"):
            value = self.metadata.get(key)
            if value:
                return str(value).strip()
        return ""

    @property
    def stream_id(self):
        return str(self.metadata.get("id") or "").strip()


def parse_probe_output(text):
    """Turn ``streamlink --json`` output into a Probe (never raises)."""
    payload = None
    try:
        payload = json.loads(text)
    except ValueError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                payload = json.loads(text[start:end + 1])
            except ValueError:
                payload = None
    if not isinstance(payload, dict):
        return Probe(False, {}, {}, error="unparsable streamlink output")
    streams = payload.get("streams") or {}
    metadata = payload.get("metadata") or {}
    if payload.get("error"):
        return Probe(False, streams, metadata, error=str(payload["error"]), raw=payload)
    if not streams:
        return Probe(False, {}, metadata, error="no streams in response", raw=payload)
    return Probe(True, streams, metadata, raw=payload)


# ----------------------------------------------------------------------------
# notifications
# ----------------------------------------------------------------------------

class Notifier:
    """Optional Discord webhook notifications (stdlib only, never fatal)."""

    def __init__(self, url, events, streamer, log):
        self.url = url or ""
        self.events = set(events or [])
        self.streamer = streamer
        self.log = log

    def send(self, event, message):
        if not self.url or event not in self.events:
            return
        content = "**[%s] %s**\n%s" % (self.streamer, event, message)
        payload = json.dumps({"username": "AutoVOD", "content": content[:1900]}).encode("utf-8")
        request = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response.read(64)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.log.warning("discord notification failed: %s" % exc)


# ----------------------------------------------------------------------------
# part / part result
# ----------------------------------------------------------------------------

class Part:
    """Everything a sink needs to record/upload one chunk of the stream."""

    def __init__(self, index, title, description, playlist, base, duration, now, metadata=None):
        self.index = index
        self.title = title
        self.description = description
        self.playlist = playlist
        self.base = base
        self.duration = duration
        self.now = now
        self.metadata = metadata or {}
        self.started = time.time()

    @property
    def suffix(self):
        return "-Part_%d" % self.index if self.index > 1 else ""


class PartResult:
    def __init__(self, ok, message, artifact=None, uploaded=False, seconds=0.0):
        self.ok = ok
        self.message = message
        self.artifact = artifact
        self.uploaded = uploaded
        self.seconds = seconds


# ----------------------------------------------------------------------------
# sinks
# ----------------------------------------------------------------------------

class Sink:
    name = "sink"

    def __init__(self, app):
        self.app = app
        self.cfg = app.cfg
        self.log = app.log

    def preflight(self):
        return []

    def record(self, part):
        raise NotImplementedError

    # -- shared helpers -----------------------------------------------------
    def render_base(self, key, part, default="$STREAMER_NAME"):
        template = str(self.cfg.get(key, default) or default)
        return good_filename(self.app.render(template + part.suffix, part=part))

    def finish_dry_run(self, part, what):
        self.log.info("[dry-run] would %s (%s)" % (what, part.title))
        return PartResult(True, "[dry-run] %s" % what, seconds=float(part.duration or 0))


class LocalSink(Sink):
    name = "local"

    def preflight(self):
        problems = []
        if not str(self.cfg.get("LOCAL_FILENAME", "")).strip():
            problems.append("LOCAL_FILENAME is empty")
        return problems

    def record(self, part):
        extension = str(self.cfg.get("LOCAL_EXTENSION", "mkv") or "mkv").lstrip(".")
        directory = self.cfg.path_in_config_dir(self.cfg.get("LOCAL_DIR", ""))
        base = self.render_base("LOCAL_FILENAME", part)
        name = "%s.%s" % (base, extension)
        target = os.path.join(directory, name) if directory else name
        target = self.app.unique_path(target)
        partial = target + ".part"
        if self.app.dry_run:
            self.app.record_to_path(partial, part, label="streamlink")
            return self.finish_dry_run(part, "record %s" % target)
        self.log.info("recording to %s" % target)
        code, seconds = self.app.record_to_path(partial, part, label="streamlink")
        if code != 0 and not self.app.stop_requested:
            self.log.error("streamlink exited with code %s" % code)
        if not os.path.exists(partial) or os.path.getsize(partial) == 0:
            if os.path.exists(partial):
                os.remove(partial)
            return PartResult(False, "no data recorded", seconds=seconds)
        if self.cfg.get_bool("RE_ENCODE", False):
            encoded = self.app.unique_path(target)
            if not self.app.reencode(partial, encoded):
                if self.cfg.get_bool("SAVE_ON_FAIL", False):
                    self.log.warning("re-encode failed, keeping raw file %s" % partial)
                    return PartResult(False, "re-encode failed (raw kept: %s)" % partial,
                                      artifact=partial, seconds=seconds)
                os.remove(partial)
                return PartResult(False, "re-encode failed", seconds=seconds)
            os.remove(partial)
            os.replace(encoded, target)
        else:
            os.replace(partial, target)
        size = os.path.getsize(target)
        self.log.info("saved %s (%s)" % (target, human_bytes(size)))
        return PartResult(True, "saved %s (%s)" % (target, human_bytes(size)), artifact=target,
                          seconds=seconds)


class RcloneSink(Sink):
    name = "rclone"

    def preflight(self):
        problems = []
        if not which(self.app.rclone_cmd[0]):
            problems.append("%s is not installed / not in PATH" % self.app.rclone_cmd[0])
        remote = str(self.cfg.get("RCLONE_REMOTE", "")).strip()
        if not remote or remote == "remote-name":
            problems.append("RCLONE_REMOTE is not configured (still the default placeholder)")
        if self.cfg.get_bool("RE_ENCODE", False) and not which(self.app.ffmpeg_cmd[0]):
            problems.append("RE_ENCODE=true but %s is not installed" % self.app.ffmpeg_cmd[0])
        return problems

    def record(self, part):
        extension = str(self.cfg.get("RCLONE_FILEEXT", "mkv") or "mkv").lstrip(".")
        base = self.render_base("RCLONE_FILENAME", part)
        workdir = self.app.work_dir()
        raw = os.path.join(workdir, "%s.raw" % base)
        final = raw
        reencode = self.cfg.get_bool("RE_ENCODE", False)
        if reencode:
            final = os.path.join(workdir, "%s.%s" % (base, extension))
        if self.app.dry_run:
            self.app.record_to_path(raw, part, label="streamlink")
            if reencode:
                self.app.reencode(raw, final)
            self.log.info("[dry-run] rclone copyto %s %s:/%s" % (final, self.cfg.get("RCLONE_REMOTE"), base))
            return self.finish_dry_run(part, "record + upload")

        self.log.info("recording to %s" % raw)
        code, seconds = self.app.record_to_path(raw, part, label="streamlink")
        if code != 0 and not self.app.stop_requested:
            self.log.error("streamlink exited with code %s" % code)
        if not os.path.exists(raw) or os.path.getsize(raw) == 0:
            self.log.error("nothing recorded, skipping upload")
            if os.path.exists(raw):
                os.remove(raw)
            return PartResult(False, "no data recorded", seconds=seconds)

        if reencode:
            if not self.app.reencode(raw, final):
                if self.cfg.get_bool("SAVE_ON_FAIL", False):
                    self.log.warning("re-encode failed, keeping raw file %s" % raw)
                    return PartResult(False, "re-encode failed (raw kept: %s)" % raw,
                                      artifact=raw, seconds=seconds)
                os.remove(raw)
                return PartResult(False, "re-encode failed", seconds=seconds)

        directory = str(self.cfg.get("RCLONE_DIR", "")).strip("/")
        leaf = "%s.%s" % (base, extension)
        target = "%s:/%s" % (self.cfg.get("RCLONE_REMOTE"), ("%s/%s" % (directory, leaf)) if directory else leaf)
        argv = self.app.rclone_cmd + ["copyto", final, target, "--progress", "--stats-one-line",
                                      "--stats", "30s", "--retries",
                                      str(self.cfg.get_int("RCLONE_RETRIES", 3))]
        argv += self.cfg.get_list("RCLONE_FLAGS", [])
        attempts = max(1, self.cfg.get_int("UPLOAD_RETRY_MAX", 3))
        for attempt in range(1, attempts + 1):
            self.log.info("uploading to %s (attempt %d/%d)" % (target, attempt, attempts))
            code = self.app.run_streamed(argv, "rclone")
            if code == 0:
                size = os.path.getsize(final)
                self.log.info("upload finished: %s (%s)" % (target, human_bytes(size)))
                os.remove(final)
                if final != raw and os.path.exists(raw):
                    os.remove(raw)
                return PartResult(True, "uploaded %s" % target, artifact=target, uploaded=True,
                                  seconds=seconds)
            self.log.error("rclone exited with code %s" % code)
            if attempt < attempts:
                time.sleep(min(60, 5 * attempt))
        if self.cfg.get_bool("SAVE_ON_FAIL", False):
            keep = self.app.unique_path(os.path.join(workdir, leaf))
            os.replace(final, keep)
            self.log.warning("upload failed, keeping file as %s" % keep)
            return PartResult(False, "upload failed (file kept: %s)" % keep, artifact=keep,
                              seconds=seconds)
        self.log.error("upload failed, discarding %s" % final)
        os.remove(final)
        return PartResult(False, "upload failed", seconds=seconds)


class RestreamSink(Sink):
    name = "restream"

    def preflight(self):
        problems = []
        if not which(self.app.ffmpeg_cmd[0]):
            problems.append("%s is not installed / not in PATH" % self.app.ffmpeg_cmd[0])
        if not str(self.cfg.get("RTMPS_STREAM_KEY", "")).strip():
            problems.append("RTMPS_STREAM_KEY is empty")
        return problems

    def record(self, part):
        url = str(self.cfg.get("RTMPS_URL", "rtmp://a.rtmp.youtube.com/live2/"))
        key = str(self.cfg.get("RTMPS_STREAM_KEY", ""))
        target = url + key
        audio = self.app.audio_settings()
        if audio["legacy"]:
            self.log.warning(
                "AUDIO_BITRATE=%s looks like a sample rate (2.x meaning); using %s Hz / %s bitrate - "
                "please set AUDIO_BITRATE=%s and AUDIO_SAMPLERATE=%s"
                % (audio["raw"], audio["samplerate"], audio["bitrate"], audio["bitrate"],
                   audio["samplerate"])
            )
        container = str(self.cfg.get("FILE_FORMAT", "flv") or "flv")
        codec = str(self.cfg.get("RESTREAM_VIDEO_CODEC", "copy") or "copy")
        argv = self.app.ffmpeg_cmd + ["-hide_banner",
                                      "-loglevel", str(self.cfg.get("RESTREAM_FFMPEG_LOG", "warning")),
                                      "-i", "pipe:0", "-c:v", codec]
        if codec == "copy" and container == "mpegts":
            argv += ["-bsf:v", "h264_mp4toannexb"]
        argv += ["-c:a", str(self.cfg.get("AUDIO_CODEC", "aac")),
                 "-b:a", audio["bitrate"],
                 "-ar", str(audio["samplerate"]),
                 "-ac", str(audio["channels"])]
        if self.cfg.get_bool("RESTREAM_FORCE_KEYFRAMES", True) and codec != "copy":
            argv += ["-g", str(self.cfg.get_int("RESTREAM_GOP", 60))]
        argv += ["-f", container, target]

        if self.app.dry_run:
            self.log.info("[dry-run] %s > 0 | %s"
                          % (" ".join(self.app.streamlink_argv(duration=part.duration)), " ".join(argv)))
            return self.finish_dry_run(part, "restream to %s" % url)

        attempts = max(1, self.cfg.get_int("RECONNECT_MAX", 5))
        started = time.time()
        for attempt in range(1, attempts + 1):
            if self.app.stop_requested:
                break
            self.log.info("restreaming to %s (attempt %d/%d)" % (url, attempt, attempts))
            sl = ChildProcess(self.app.streamlink_argv(duration=part.duration), self.log,
                              name="streamlink", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              pump_stdout=False)
            ff = ChildProcess(argv, self.log, name="ffmpeg", stdin=sl.proc.stdout)
            sl.proc.stdout.close()
            self.app.active_child = sl
            code = ff.wait()
            self.app.active_child = None
            sl.terminate(grace=5)
            if code == 0:
                self.log.info("restream stopped (stream ended)")
                return PartResult(True, "restream finished", seconds=time.time() - started)
            self.log.error("ffmpeg exited with code %s" % code)
            if self.app.stop_requested or not self.app.still_live():
                break
            time.sleep(min(30, 5 * attempt))
        return PartResult(False, "restream failed", seconds=time.time() - started)


class YoutubeSink(Sink):
    name = "youtube"

    def preflight(self):
        problems = []
        if not which(self.app.ytuploader_cmd[0]):
            problems.append("%s is not installed / not in PATH" % self.app.ytuploader_cmd[0])
        for key, default in (("YOUTUBE_SECRETS", "client_secrets.json"),
                             ("YOUTUBE_TOKEN_CACHE", "request.token")):
            path = self.cfg.path_in_config_dir(str(self.cfg.get(key, default) or default))
            if not os.path.isfile(path):
                problems.append("%s missing (%s)" % (os.path.basename(path), path))
        return problems

    def record(self, part):
        base = self.render_base("YOUTUBE_FILENAME", part, default="$STREAMER_NAME-TIME_DATE")
        workdir = self.app.work_dir()
        cache_path = os.path.join(workdir, "%s.upload.mkv" % base)
        record_to_disk = self.cfg.get_bool("YOUTUBE_RECORD_TO_DISK", True)
        started = time.time()

        if self.app.dry_run:
            target = cache_path if record_to_disk else "-"
            self.app.record_to_path(target, part, label="streamlink")
            self.log.info("[dry-run] youtubeuploader -filename %s -metaJSON <generated>" % target)
            return self.finish_dry_run(part, "record + upload")

        if not record_to_disk:
            return self._record_and_pipe(part, base, started)

        self.log.info("recording to %s (upload starts when the part is complete)" % cache_path)
        code, seconds = self.app.record_to_path(cache_path, part, label="streamlink")
        if code != 0 and not self.app.stop_requested:
            self.log.error("streamlink exited with code %s" % code)
        if not os.path.exists(cache_path) or os.path.getsize(cache_path) == 0:
            if os.path.exists(cache_path):
                os.remove(cache_path)
            return PartResult(False, "no data recorded", seconds=seconds)
        size = os.path.getsize(cache_path)
        minimum = self.cfg.get_int("YOUTUBE_MIN_BYTES", 1048576)
        if size < minimum:
            self.log.warning("recorded part is only %s but YOUTUBE_MIN_BYTES=%d - uploading anyway"
                             % (human_bytes(size), minimum))
        self.log.info("recorded %s (%s), starting upload" % (cache_path, human_bytes(size)))

        attempts = max(1, self.cfg.get_int("UPLOAD_RETRY_MAX", 3))
        for attempt in range(1, attempts + 1):
            self.log.info("uploading to youtube (attempt %d/%d)" % (attempt, attempts))
            code = self.app.run_streamed(self._upload_argv(cache_path, base, part), "youtubeuploader")
            if code == 0:
                video_url = self._uploaded_video_url(base)
                if video_url:
                    self.log.info("uploaded: %s" % video_url)
                    self.app.notifier.send("end", "uploaded: %s" % video_url)
                else:
                    self.log.info("upload finished")
                if self.cfg.get_bool("YOUTUBE_KEEP_LOCAL", False):
                    keep = self.app.unique_path(os.path.join(workdir, "%s.mkv" % base))
                    os.replace(cache_path, keep)
                    self.log.info("local copy kept as %s" % keep)
                else:
                    os.remove(cache_path)
                return PartResult(True,
                                  "uploaded to youtube" + (" (%s)" % video_url if video_url else ""),
                                  artifact=video_url or cache_path, uploaded=True, seconds=seconds)
            self.log.error("youtubeuploader exited with code %s" % code)
            if attempt < attempts:
                time.sleep(min(60, 10 * attempt))
        if self.cfg.get_bool("SAVE_ON_FAIL", False):
            keep = self.app.unique_path(os.path.join(workdir, "%s.failed.mkv" % base))
            os.replace(cache_path, keep)
            self.log.warning("upload failed, keeping file as %s" % keep)
            return PartResult(False, "upload failed (file kept: %s)" % keep, artifact=keep,
                              seconds=seconds)
        self.log.error("upload failed, discarding %s" % cache_path)
        os.remove(cache_path)
        return PartResult(False, "upload failed", seconds=seconds)

    def _record_and_pipe(self, part, base, started):
        """2.x behaviour: streamlink stdout -> youtubeuploader stdin (no file)."""
        self.log.info("streaming directly to youtube (no local copy)")
        sl = ChildProcess(self.app.streamlink_argv(duration=part.duration), self.log,
                          name="streamlink", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          pump_stdout=False)
        up = ChildProcess(self._upload_argv("-", base, part), self.log, name="youtubeuploader",
                          stdin=sl.proc.stdout)
        sl.proc.stdout.close()
        self.app.active_child = sl
        code = up.wait()
        self.app.active_child = None
        sl.terminate(grace=5)
        if code != 0:
            self.log.error("youtubeuploader exited with code %s and nothing was kept - set "
                           "YOUTUBE_RECORD_TO_DISK=true to survive this" % code)
            return PartResult(False, "upload failed", seconds=time.time() - started)
        video_url = self._uploaded_video_url(base)
        self.log.info("upload finished" + (" - %s" % video_url if video_url else ""))
        if video_url:
            self.app.notifier.send("end", "uploaded: %s" % video_url)
        return PartResult(True, "uploaded to youtube", uploaded=True,
                          artifact=video_url or base, seconds=time.time() - started)

    def _common_args(self):
        args = []
        secrets = self.cfg.path_in_config_dir(str(self.cfg.get("YOUTUBE_SECRETS", "client_secrets.json")))
        cache = self.cfg.path_in_config_dir(str(self.cfg.get("YOUTUBE_TOKEN_CACHE", "request.token")))
        if secrets:
            args += ["-secrets", secrets]
        if cache:
            args += ["-cache", cache]
        ratelimit = self.cfg.get_int("YOUTUBE_RATELIMIT", 0)
        if ratelimit > 0:
            args += ["-ratelimit", str(ratelimit)]
        if str(self.cfg.get("YOUTUBE_NOTIFY_SUBSCRIBERS", "")).strip():
            args.append("-notify=%s" % ("true" if self.cfg.get_bool("YOUTUBE_NOTIFY_SUBSCRIBERS") else "false"))
        return args

    def _upload_argv(self, filename, base, part):
        workdir = self.app.work_dir()
        metadata_path = os.path.join(workdir, "%s.meta.json" % base)
        with open(metadata_path, "w", encoding="utf-8") as handle:
            json.dump(self.app.youtube_metadata(part), handle, indent=2)
        out_path = os.path.join(workdir, "%s.meta.out.json" % base)
        argv = self.app.ytuploader_cmd + ["-filename", filename, "-metaJSON", metadata_path,
                                          "-metaJSONout", out_path]
        return argv + self._common_args()

    def _uploaded_video_url(self, base):
        path = os.path.join(self.app.work_dir(), "%s.meta.out.json" % base)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        video_id = data.get("id") or data.get("videoId")
        if not video_id:
            for key in ("video", "snippet", "resourceId"):
                value = data.get(key)
                if isinstance(value, dict) and value.get("id"):
                    video_id = value["id"]
                    break
        return "https://youtu.be/%s" % video_id if video_id else None


SINKS = {
    "local": LocalSink,
    "rclone": RcloneSink,
    "restream": RestreamSink,
    "youtube": YoutubeSink,
}


# ----------------------------------------------------------------------------
# application
# ----------------------------------------------------------------------------

class AutoVod:
    def __init__(self, cfg, log, once=False, dry_run=False, force=False, probe_only=False):
        self.cfg = cfg
        self.log = log
        self.once = once
        self.dry_run = dry_run
        self.force = force
        self.probe_only = probe_only
        self.streamer = cfg.streamer
        self.stop_requested = False
        self.active_child = None
        self._stop_event = threading.Event()
        #: binary overrides - useful for venv/pipx installs, wrappers and tests
        self.streamlink_cmd = cfg.get_list("STREAMLINK_BIN", ["streamlink"])
        self.ffmpeg_cmd = cfg.get_list("FFMPEG_BIN", ["ffmpeg"])
        self.rclone_cmd = cfg.get_list("RCLONE_BIN", ["rclone"])
        self.ytuploader_cmd = cfg.get_list("YOUTUBE_UPLOADER_BIN", ["youtubeuploader"])
        self.state_dir = cfg.path_in_config_dir(cfg.get("STATE_DIR", ".autovod")) or ".autovod"
        self.state = State(os.path.join(self.state_dir, "%s.state.json" % self.streamer))
        self.lock = FileLock(os.path.join(self.state_dir, "%s.lock" % self.streamer))
        self.notifier = Notifier(cfg.get("DISCORD_WEBHOOK", ""),
                                 cfg.get_list("NOTIFY_ON", ["error"]),
                                 self.streamer, log)
        self.sink_name = str(cfg.get("UPLOAD_SERVICE", "youtube")).strip().lower()
        sink_class = SINKS.get(self.sink_name)
        if not sink_class:
            raise ConfigError("invalid UPLOAD_SERVICE %r (valid: %s)"
                              % (self.sink_name, ", ".join(sorted(SINKS))))
        self.sink = sink_class(self)
        self.stream_url = self._build_stream_url()
        self.duration = self._part_duration()
        self.quality = str(cfg.get("STREAMLINK_QUALITY", "best")).strip() or "best"
        self.session_count = 0

    # -- config derived -----------------------------------------------------
    def _build_stream_url(self):
        url = str(self.cfg.get("STREAM_URL", "")).strip()
        if url:
            return url
        source = str(self.cfg.get("STREAM_SOURCE", "twitch")).strip().lower()
        name = str(self.cfg.get("STREAMER_CHANNEL", "") or self.streamer).strip()
        if source == "twitch":
            return "twitch.tv/%s" % name
        if source == "kick":
            return "kick.com/%s" % name
        if source == "youtube":
            return "youtube.com/@%s/live" % name
        raise ConfigError("invalid STREAM_SOURCE %r (valid: twitch, kick, youtube - or set STREAM_URL)"
                          % source)

    def _part_duration(self):
        if self.cfg.get_bool("SPLIT_INTO_PARTS", False):
            return parse_duration(self.cfg.get("SPLIT_VIDEO_DURATION", "06:00:00"), 6 * 3600)
        return parse_duration(self.cfg.get("VIDEO_DURATION", "12:00:00"), 12 * 3600)

    def streamlink_flags(self):
        filtered = []
        for flag in self.cfg.get_list("STREAMLINK_FLAGS", []):
            base = flag.split("=", 1)[0]
            if base in DEPRECATED_STREAMLINK_FLAGS:
                self.log.warning("dropping %s: disabled by streamlink >= 7.5.0 (ad filtering is "
                                 "always on, rerun/hosting blocking was removed)" % base)
                continue
            filtered.append(flag)
        filtered.extend(self.cfg.get_list("STREAMLINK_EXTRA_ARGS", []))
        if self.sink_name == "restream" and not any("--twitch-supported-codecs" in flag for flag in filtered):
            filtered.append("--twitch-supported-codecs=h264")
        return filtered

    def streamlink_common(self):
        argv = self.streamlink_cmd + ["--loglevel", str(self.cfg.get("STREAMLINK_LOGS", "error"))]
        argv += ["--retry-streams", str(self.cfg.get_int("STREAMLINK_RETRY_STREAMS", 2))]
        argv += ["--retry-max", str(self.cfg.get_int("STREAMLINK_RETRY_MAX", 3))]
        argv += ["--retry-open", str(self.cfg.get_int("STREAMLINK_RETRY_OPEN", 3))]
        argv += ["--stream-timeout", str(self.cfg.get_int("STREAMLINK_STREAM_TIMEOUT", 60))]
        edge = self.cfg.get_int("STREAMLINK_HLS_LIVE_EDGE", 0)
        if edge:
            argv += ["--hls-live-edge", str(edge)]
        return argv + self.streamlink_flags()

    def streamlink_argv(self, duration=None, quality=None):
        """Full record command.

        ``--stdout`` is always set explicitly: the 2.x script relied on the
        streamlink default of "play with a local player" being overridden by
        ``-O`` and would otherwise spawn a video player on a server.
        """
        argv = self.streamlink_common() + ["--stdout"]
        if duration:
            argv += ["--hls-duration", format_duration(duration)]
        argv.append(self.stream_url)
        argv.append(self._stream_selection(quality))
        return argv

    def _stream_selection(self, quality=None):
        quality = quality or self.quality
        fallback = str(self.cfg.get("QUALITY_FALLBACK", "best")).strip()
        if fallback and fallback != quality and quality not in ("best", "worst"):
            return "%s,%s" % (quality, fallback)
        return quality

    def probe_argv(self):
        return self.streamlink_common() + ["--json", self.stream_url]

    def work_dir(self):
        path = self.cfg.path_in_config_dir(self.cfg.get("TEMP_DIR", "tmp")) or "tmp"
        os.makedirs(path, exist_ok=True)
        return path

    def unique_path(self, path):
        if self.force or not os.path.exists(path):
            return path
        root, ext = os.path.splitext(path)
        index = 1
        while True:
            candidate = "%s-%d%s" % (root, index, ext)
            if not os.path.exists(candidate):
                return candidate
            index += 1

    def audio_settings(self):
        raw = str(self.cfg.get("AUDIO_BITRATE", "128")).strip() or "128"
        legacy = raw.isdigit() and int(raw) > 1000
        samplerate = int(raw) if legacy else self.cfg.get_int("AUDIO_SAMPLERATE", 44100)
        if legacy:
            bitrate = "%sk" % (self.cfg.get("AUDIO_BITRATE_DEFAULT", "128"))
        else:
            bitrate = raw if raw.lower().endswith("k") else "%sk" % raw
        return {"legacy": legacy, "raw": raw, "bitrate": bitrate, "samplerate": samplerate,
                "channels": self.cfg.get_int("AUDIO_CHANNELS", 2)}

    def youtube_metadata(self, part=None):
        """Build the youtubeuploader metaJSON.

        ``part`` is the fully rendered part (title/description/playlist already
        contain the stream metadata), so nothing is re-rendered here.
        """
        if part is not None:
            title = part.title
            description = part.description
            playlist = str(part.playlist or "").strip()
        else:
            title = self.render(str(self.cfg.get("VIDEO_TITLE", "$STREAMER_NAME - TIME_DATE")))
            description = self.render(str(self.cfg.get("VIDEO_DESCRIPTION", "")))
            playlist = self.render(str(self.cfg.get("VIDEO_PLAYLIST", ""))).strip()
        meta = {
            "title": title,
            "privacyStatus": str(self.cfg.get("VIDEO_VISIBILITY", "unlisted") or "unlisted"),
        }
        if description:
            meta["description"] = description.replace("\\n", "\n")
        if playlist:
            meta["playlistTitles"] = [playlist]
        tags = [tag.strip() for tag in str(self.cfg.get("VIDEO_TAGS", "")).split(",") if tag.strip()]
        if tags:
            meta["tags"] = tags
        for key, target in (("VIDEO_CATEGORY_ID", "categoryId"), ("VIDEO_LANGUAGE", "language")):
            value = str(self.cfg.get(key, "")).strip()
            if value:
                meta[target] = value
        if str(self.cfg.get("VIDEO_MADE_FOR_KIDS", "")).strip():
            meta["madeForKids"] = self.cfg.get_bool("VIDEO_MADE_FOR_KIDS")
        extra_path = self.cfg.path_in_config_dir(str(self.cfg.get("VIDEO_META_EXTRA_JSON", "")))
        if extra_path and os.path.isfile(extra_path):
            try:
                with open(extra_path, "r", encoding="utf-8") as handle:
                    extra = json.load(handle)
                if isinstance(extra, dict):
                    meta.update(extra)
            except (OSError, ValueError) as exc:
                self.log.warning("cannot read VIDEO_META_EXTRA_JSON: %s" % exc)
        return meta

    # -- rendering ----------------------------------------------------------
    def render(self, template, part=None, metadata=None):
        """Replace the documented placeholders - no eval, no shell."""
        if metadata is None:
            metadata = part.metadata if part else {}
        now = part.now if part else datetime.now()
        title = str(metadata.get("title") or "").strip()
        game = str(metadata.get("category") or metadata.get("game") or "").strip()
        stream_id = str(metadata.get("id") or "").strip()
        date_format = str(self.cfg.get("DATE_FORMAT", "%d-%m-%y"))
        clock_format = str(self.cfg.get("CLOCK_FORMAT", "%H_%M_%S"))
        mapping = (
            ("{{TITLE}}", title),
            ("{{GAME}}", game),
            ("{{CATEGORY}}", game),
            ("{{STREAMER}}", self.streamer),
            ("{{ID}}", stream_id),
            ("{{DATE}}", now.strftime(date_format)),
            ("{{TIME}}", now.strftime(clock_format)),
            ("{{PART}}", str(part.index) if part else ""),
            ("$STREAMER_TITLE", title),
            ("$STREAMER_GAME", game),
            ("$STREAMER_NAME", self.streamer),
            ("TIME_DATE", now.strftime(date_format)),
            ("TIME_CLOCK", now.strftime(clock_format)),
            ("initial_title", title),  # 2.x placeholder value, kept for old configs
            ("inital_game", game),     # 2.x typo, kept for old configs
        )
        result = str(template)
        for token, value in mapping:
            if token in result:
                result = result.replace(token, value)
        return result

    # -- preflight ----------------------------------------------------------
    def preflight(self):
        problems = []
        if not which(self.streamlink_cmd[0]):
            problems.append("%s is not installed / not in PATH" % self.streamlink_cmd[0])
        else:
            version = self.streamlink_version()
            if version and version < (6, 0, 0):
                problems.append("streamlink %s is too old (>= 6.0 needed for --json/--retry-*), "
                                "please upgrade" % ".".join(str(part) for part in version))
        if not self.duration:
            problems.append("VIDEO_DURATION / SPLIT_VIDEO_DURATION is 0")
        for warning in self.cfg.warnings:
            self.log.warning("config: %s" % warning)
        problems.extend(self.sink.preflight())
        return problems

    def streamlink_version(self):
        try:
            _code, text = run_capture(self.streamlink_cmd + ["--version"], self.log, name="streamlink",
                                      timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
        return tuple(int(part) for part in match.groups()) if match else None

    # -- child helpers ------------------------------------------------------
    def run_streamed(self, argv, name):
        """Run a long command and stream its output into the log."""
        self.log.debug("exec: %s" % " ".join(argv))
        return ChildProcess(argv, self.log, name=name).wait()

    # -- recording ----------------------------------------------------------
    def record_to_path(self, path, part, label="streamlink"):
        """Run streamlink writing to ``path``, reconnecting while still live."""
        attempts = max(1, self.cfg.get_int("RECONNECT_MAX", 5))
        delay = self.cfg.get_int("RECONNECT_DELAY", 10)
        started = time.time()
        last_code = 0
        for attempt in range(1, attempts + 1):
            if self.stop_requested:
                break
            remaining = None
            if part.duration:
                remaining = max(5, int(part.duration - (time.time() - started)))
            argv = self.streamlink_argv(duration=remaining)
            if self.dry_run:
                self.log.info("[dry-run] %s > %s" % (" ".join(argv), path))
                return 0, 0.0
            self.log.debug("exec: %s" % " ".join(argv))
            directory = os.path.dirname(os.path.abspath(path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            mode = "wb" if attempt == 1 else "ab"
            with open(path, mode) as sink:
                child = ChildProcess(argv, self.log, name=label, stdout=sink,
                                     stderr=subprocess.PIPE)
                self.active_child = child
                try:
                    last_code = child.wait()
                finally:
                    self.active_child = None
            if last_code == 0:
                return 0, time.time() - started
            if self.stop_requested:
                return last_code, time.time() - started
            self.log.warning("streamlink exited with code %s" % last_code)
            if not self.still_live():
                self.log.info("stream is offline, ending this part")
                return last_code, time.time() - started
            if attempt >= attempts:
                self.log.error("giving up after %d attempts" % attempts)
                break
            wait = min(delay * attempt, 120)
            self.log.info("stream still live - reconnecting in %ss" % wait)
            self._stop_event.wait(wait)
        return last_code, time.time() - started

    def reencode(self, source, target):
        codec = str(self.cfg.get("RE_ENCODE_CODEC", "libx265"))
        extension = os.path.splitext(target)[1].lstrip(".").lower()
        container = CONTAINER_BY_EXT.get(extension)
        argv = self.ffmpeg_cmd + ["-hide_banner",
                                  "-loglevel", str(self.cfg.get("RE_ENCODE_LOG", "error")),
                                  "-i", source, "-map", "0",
                                  "-c:v", codec,
                                  "-crf", str(self.cfg.get("RE_ENCODE_CRF", "25")),
                                  "-preset", str(self.cfg.get("RE_ENCODE_PRESET", "medium")),
                                  "-c:a", str(self.cfg.get("RE_ENCODE_AUDIO_CODEC", "copy") or "copy")]
        if container:
            argv += ["-f", container]
        argv.append(target)
        if self.dry_run:
            self.log.info("[dry-run] %s" % " ".join(argv))
            return True
        self.log.info("re-encoding %s -> %s" % (source, target))
        code = self.run_streamed(argv, "ffmpeg")
        if code != 0:
            self.log.error("ffmpeg exited with code %s" % code)
            return False
        return True

    # -- liveness -----------------------------------------------------------
    def probe(self):
        if self.dry_run:
            self.log.info("[dry-run] %s" % " ".join(self.probe_argv()))
            return Probe(True, {"best": {}}, {"title": "dry-run", "category": "dry-run", "id": "0"})
        argv = self.probe_argv()
        self.log.debug("probe: %s" % " ".join(argv))
        code, text = run_capture(argv, self.log, name="streamlink", timeout=180)
        probe = parse_probe_output(text)
        if not probe.live and probe.error:
            self.log.debug("probe says offline: %s (exit %s)" % (probe.error, code))
        return probe

    def still_live(self):
        if self.stop_requested:
            return False
        return self.probe().live

    # -- state --------------------------------------------------------------
    def next_part_index(self, now):
        today = now.strftime(str(self.cfg.get("DATE_FORMAT", "%d-%m-%y")))
        if self.state.get("date") != today:
            index = 1
        else:
            index = int(self.state.get("part", 0) or 0) + 1
        self.state.set("date", today)
        self.state.set("part", index)
        self.state.set("updated", now.isoformat(timespec="seconds"))
        return index

    def make_part(self, metadata, now):
        index = self.next_part_index(now)
        base = good_filename(self.render(str(self.cfg.get("RCLONE_FILENAME", "$STREAMER_NAME")
                                           or "$STREAMER_NAME"), metadata=metadata))
        raw_title = str(self.cfg.get("VIDEO_TITLE", "$STREAMER_NAME - TIME_DATE"))
        raw_description = str(self.cfg.get("VIDEO_DESCRIPTION", ""))
        raw_playlist = str(self.cfg.get("VIDEO_PLAYLIST", ""))
        part = Part(index, raw_title, raw_description, raw_playlist, base, self.duration, now, metadata)
        part.title = self.render(raw_title, part=part)
        part.description = self.render(raw_description, part=part)
        part.playlist = self.render(raw_playlist, part=part)
        if (self.cfg.get_bool("SPLIT_INTO_PARTS", False) or index > 1) and "{{PART}}" not in raw_title:
            part.title = "%s Part: %d" % (part.title, index)
        self.state.save()
        return part

    # -- main loop ----------------------------------------------------------
    def run(self):
        self.log.info("AutoVOD %s - streamer=%s source=%s sink=%s"
                      % (VERSION, self.streamer, self.stream_url, self.sink_name))
        problems = self.preflight()
        if problems:
            for problem in problems:
                self.log.error("preflight: %s" % problem)
            return 2
        self.log.info("preflight ok (stream selection=%s, part length=%s, split=%s)"
                      % (self._stream_selection(), format_duration(self.duration),
                         self.cfg.get_bool("SPLIT_INTO_PARTS", False)))
        if self.probe_only:
            return self.report_probe()
        use_lock = self.cfg.get_bool("LOCK", True) and not self.dry_run
        if use_lock:
            try:
                self.lock.acquire()
            except LockError as exc:
                self.log.error("another AutoVOD instance is already running for %s (%s)"
                               % (self.streamer, exc))
                return 3
        else:
            self.log.info("lock disabled (LOCK=false or --dry-run)")
        interval = max(5, self.cfg.get_int("POLL_INTERVAL", 60))
        max_interval = max(interval, self.cfg.get_int("POLL_INTERVAL_MAX", 300))
        backoff = self.cfg.get_bool("POLL_BACKOFF", True)
        idle = interval
        try:
            while True:
                probe = self.probe()
                if not probe.live:
                    self.log.info("stream is offline (%s) - next check in %ss"
                                  % (probe.error or "no streams", idle))
                    if self.once:
                        return 1
                    if self._stop_event.wait(idle):
                        break
                    if backoff:
                        idle = min(max_interval, int(idle * 1.5))
                    continue
                idle = interval
                metadata = dict(probe.metadata)
                self.apply_metadata_fallback(metadata)
                now = datetime.now()
                self.log.info("stream is live: %s%s"
                              % (metadata.get("title") or "-",
                                 " [%s]" % metadata.get("category") if metadata.get("category") else ""))
                part = self.make_part(metadata, now)
                self.log.info("part %d -> %s" % (part.index, part.title))
                self.notifier.send("start", "part %d: %s" % (part.index, part.title))
                result = self.sink.record(part)
                if result.ok:
                    self.session_count += 1
                    self.state.set("last_success", now.isoformat(timespec="seconds"))
                    self.state.set("last_message", result.message)
                    self.state.save()
                    self.log.info("part %d done: %s" % (part.index, result.message))
                    self.notifier.send("end", "part %d done: %s" % (part.index, result.message))
                else:
                    self.log.error("part %d failed: %s" % (part.index, result.message))
                    self.notifier.send("error", "part %d failed: %s" % (part.index, result.message))
                if self.once:
                    return 0 if result.ok else 1
                if self.stop_requested:
                    break
                if self.stream_continues(part, result):
                    continue
                if self._stop_event.wait(interval):
                    break
            self.log.info("shutting down")
            return 0
        finally:
            if use_lock:
                self.lock.release()

    def report_probe(self):
        probe = self.probe()
        if not probe.live:
            self.log.info("stream offline (%s)" % (probe.error or "no streams"))
            return 1
        self.log.info("stream is live")
        self.log.info("title: %s" % (probe.title or "-"))
        self.log.info("category: %s" % (probe.game or "-"))
        self.log.info("id: %s" % (probe.stream_id or "-"))
        self.log.info("available qualities: %s" % ", ".join(sorted(probe.streams)))
        return 0

    def stream_continues(self, part, result):
        """True when the part ended by hitting the duration limit while live."""
        if not result.ok or not part.duration:
            return False
        return result.seconds + 5 >= part.duration

    def apply_metadata_fallback(self, metadata):
        """Legacy API_URL support (deprecated) - streamlink metadata wins."""
        legacy = str(self.cfg.get("API_URL", "")).strip()
        if not (self.cfg.get_bool("API_CALLS", False) and legacy):
            return
        if metadata.get("title") and metadata.get("title") != "initial_title":
            return
        url = legacy if legacy.startswith("http") else "https://" + legacy.lstrip("/")
        url = url.rstrip("/") + "/info/" + self.streamer
        self.log.warning("API_URL/API_CALLS is deprecated - streamlink already provides the metadata")
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.log.warning("legacy API_URL lookup failed (%s) - using streamlink metadata" % exc)
            return
        if isinstance(payload, dict):
            metadata.setdefault("title", payload.get("stream_title") or "")
            metadata.setdefault("category", payload.get("stream_game") or "")

    def request_stop(self):
        if self.stop_requested:
            return
        self.stop_requested = True
        self._stop_event.set()
        self.log.info("stop requested - finishing the current part")
        child = self.active_child
        if child is not None:
            self.log.info("stopping %s" % child.name)
            child.terminate(grace=10)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def find_configs(directory):
    return [entry for entry in sorted(os.listdir(directory))
            if entry.endswith(".config") and entry != "default.config"]


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Record Twitch/Kick/YouTube Live streams and upload them "
                    "(youtube / rclone / restream / local).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="config files are plain '<name>.config' files - see default.config for every option",
    )
    parser.add_argument("-n", "--name", help="streamer name (uses <name>.config)")
    parser.add_argument("streamer", nargs="?",
                        help="streamer name (2.x style positional argument, same as -n)")
    parser.add_argument("-c", "--config", help="path to a config file (overrides --name)")
    parser.add_argument("--once", action="store_true", help="one check/record cycle, then exit")
    parser.add_argument("--dry-run", action="store_true", help="print what would run, touch nothing")
    parser.add_argument("--check", action="store_true", help="preflight check only (no recording)")
    parser.add_argument("--list-streams", action="store_true",
                        help="report live state, metadata and available qualities")
    parser.add_argument("--print-config", action="store_true", help="print the parsed config and exit")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument("-q", "--quiet", action="store_true", help="only warnings and errors")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version", version="AutoVOD %s" % VERSION)
    return parser


def main(argv=None):
    global LOG
    args = build_parser().parse_args(argv)
    if args.name is None:
        args.name = args.streamer
    directory = os.getcwd()
    if args.config:
        config_path = os.path.abspath(args.config)
    elif args.name:
        config_path = os.path.join(directory, args.name + ".config")
    else:
        candidates = find_configs(directory)
        if len(candidates) == 1:
            config_path = os.path.join(directory, candidates[0])
        elif not candidates:
            print("error: no *.config found and no -n/--name given", file=sys.stderr)
            return 2
        else:
            print("error: multiple config files found, pass -n/--name:", file=sys.stderr)
            for candidate in candidates:
                print("  %s" % candidate, file=sys.stderr)
            return 2

    try:
        cfg = Config(config_path, streamer=args.name)
    except ConfigError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    level = "debug" if args.verbose else ("warning" if args.quiet else cfg.get("LOG_LEVEL", "info"))
    log_path = cfg.get("LOG_FILE", "")
    LOG = Log(level, cfg.path_in_config_dir(log_path) if log_path else None,
              cfg.get_float("LOG_MAX_MB", 10), cfg.get_int("LOG_BACKUPS", 3))

    if args.print_config:
        print(cfg.describe())
        return 0

    try:
        app = AutoVod(cfg, LOG, once=args.once, dry_run=args.dry_run, force=args.force,
                      probe_only=args.list_streams)
    except ConfigError as exc:
        LOG.error(str(exc))
        return 2

    if args.check:
        problems = app.preflight()
        if problems:
            for problem in problems:
                LOG.error("preflight: %s" % problem)
            return 2
        LOG.info("all checks passed: %s (%s -> %s)" % (app.streamer, app.stream_url, app.sink_name))
        return 0

    def handle_signal(signum, _frame):
        app.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handle_signal)
        except (ValueError, AttributeError):
            pass

    if app.sink_name == "youtube":
        if cfg.get_bool("YOUTUBE_RECORD_TO_DISK", True):
            LOG.info("youtube sink records each part to disk first (survives a failed upload); "
                     "set YOUTUBE_RECORD_TO_DISK=false for pipe-only uploads")
        else:
            LOG.warning("pipe-only youtube upload: if the upload dies, the recorded part is lost")

    try:
        return app.run()
    except ConfigError as exc:
        LOG.error(str(exc))
        return 2
    except KeyboardInterrupt:
        app.request_stop()
        return 0
    finally:
        LOG.close()


if __name__ == "__main__":
    sys.exit(main())
