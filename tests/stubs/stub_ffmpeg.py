#!/usr/bin/env python3
"""Test stub for ffmpeg.

  * ``-i <file> <out>``      -> copies the file (re-encode path)
  * ``-i pipe:0 ... rtmp://``-> reads stdin and writes the byte count to
                                STUB_RTMP_LOG (restream path)
"""

import json
import os
import sys


def main():
    args = sys.argv[1:]
    log = os.environ.get("STUB_ARGV_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(args) + "\n")

    source = None
    if "-i" in args:
        index = args.index("-i")
        if index + 1 < len(args):
            source = args[index + 1]
    target = args[-1] if args else ""

    if target.startswith("rtmp"):
        data = sys.stdin.buffer.read()
        rtmp_log = os.environ.get("STUB_RTMP_LOG")
        if rtmp_log:
            with open(rtmp_log, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"target": target, "bytes": len(data), "args": args}) + "\n")
        return int(os.environ.get("STUB_FFMPEG_EXIT", "0"))

    if source and source != "pipe:0" and target:
        try:
            with open(source, "rb") as handle:
                data = handle.read()
            with open(target, "wb") as handle:
                handle.write(data)
        except OSError as exc:
            print("stub ffmpeg: %s" % exc, file=sys.stderr)
            return 1
    return int(os.environ.get("STUB_FFMPEG_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
