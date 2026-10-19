#!/usr/bin/env python3
"""Test stub for streamlink.

Selected through ``STREAMLINK_BIN``/``STREAMLINK_BIN`` so the test suite can
exercise the whole record/upload pipeline without touching the network.

Behaviour:
  * ``--version``        -> prints a fake version
  * ``--json``           -> live/offline JSON, controlled by STUB_LIVE
  * record mode          -> writes STUB_BYTES bytes to stdout and exits with
                            STUB_RECORD_EXIT (or 0 once STUB_FAIL_ONCE was used)
"""

import json
import os
import sys

ARGS = sys.argv[1:]


def main():
    if "--version" in ARGS:
        print("streamlink %s" % os.environ.get("STUB_VERSION", "8.4.0"))
        return 0
    if "--json" in ARGS:
        if os.environ.get("STUB_LIVE", "1") == "1":
            print(json.dumps({
                "plugin": "twitch",
                "metadata": {
                    "id": "stub-stream-id",
                    "author": "StubAuthor",
                    "category": "Just Chatting",
                    "title": os.environ.get("STUB_TITLE", "Stub title"),
                },
                "streams": {
                    "audio_only": {"type": "hls"},
                    "480p": {"type": "hls"},
                    "720p": {"type": "hls"},
                    "1080p60": {"type": "hls"},
                    "best": {"type": "hls"},
                },
            }))
            return 0
        print(json.dumps({"error": "No playable streams found on this URL: %s" % ARGS[-1]}))
        return 1

    # record mode: remember the exact argv so tests can inspect it
    log = os.environ.get("STUB_ARGV_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(ARGS) + "\n")

    size = int(os.environ.get("STUB_BYTES", "4096"))
    sys.stdout.buffer.write(b"A" * size)
    sys.stdout.buffer.flush()

    exit_code = int(os.environ.get("STUB_RECORD_EXIT", "0"))
    marker = os.environ.get("STUB_FAIL_ONCE")
    if marker and not os.path.exists(marker):
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("failed once\n")
        exit_code = int(os.environ.get("STUB_FAIL_ONCE_EXIT", "1"))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
