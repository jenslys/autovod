#!/usr/bin/env python3
"""Test stub for youtubeuploader.

Reads the video either from stdin (``-filename -``) or from a file, writes a
fake ``-metaJSONout`` result and records what it was asked to upload.
"""

import json
import os
import sys


def parse(args):
    options = {}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("-filename", "-metaJSON", "-metaJSONout", "-secrets", "-cache", "-ratelimit"):
            options[arg] = args[index + 1] if index + 1 < len(args) else ""
            index += 2
            continue
        if arg.startswith("-notify="):
            options["-notify"] = arg.split("=", 1)[1]
        index += 1
    return options


def main():
    args = sys.argv[1:]
    options = parse(args)
    log = os.environ.get("STUB_ARGV_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(args) + "\n")

    filename = options.get("-filename", "")
    if filename == "-":
        data = sys.stdin.buffer.read()
    else:
        try:
            with open(filename, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            print("stub youtubeuploader: %s" % exc, file=sys.stderr)
            return 1

    metadata = {}
    meta_path = options.get("-metaJSON")
    if meta_path:
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                metadata = json.load(handle)
        except (OSError, ValueError) as exc:
            print("stub youtubeuploader: bad metaJSON: %s" % exc, file=sys.stderr)
            return 1

    record = {
        "bytes": len(data),
        "filename": filename,
        "title": metadata.get("title"),
        "privacyStatus": metadata.get("privacyStatus"),
        "playlistTitles": metadata.get("playlistTitles"),
        "tags": metadata.get("tags"),
        "language": metadata.get("language"),
        "notify": options.get("-notify"),
        "ratelimit": options.get("-ratelimit"),
        "categories/extra": {key: value for key, value in metadata.items()
                             if key not in ("title", "privacyStatus", "playlistTitles", "tags", "language")},
    }
    upload_log = os.environ.get("STUB_UPLOAD_LOG")
    if upload_log:
        with open(upload_log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    exit_code = int(os.environ.get("STUB_UPLOAD_EXIT", "0"))
    marker = os.environ.get("STUB_UPLOAD_FAIL_ONCE")
    if marker and not os.path.exists(marker):
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("failed once\n")
        exit_code = int(os.environ.get("STUB_UPLOAD_FAIL_ONCE_EXIT", "1"))
        print("stub youtubeuploader: simulated failure", file=sys.stderr)
        return exit_code

    out_path = options.get("-metaJSONout")
    if out_path and exit_code == 0:
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump({"id": "STUBVIDEOID1", "kind": "youtube#video"}, handle)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
