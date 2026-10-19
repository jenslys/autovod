#!/usr/bin/env python3
"""Test stub for rclone: `copyto <src> <dst> [flags]` copies into STUB_RCLONE_DIR."""

import json
import os
import sys


def main():
    args = sys.argv[1:]
    log = os.environ.get("STUB_ARGV_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(args) + "\n")
    positional = [arg for arg in args if not arg.startswith("--")]
    if len(positional) < 2 or positional[0] != "copyto":
        print("stub rclone: unexpected arguments %r" % args, file=sys.stderr)
        return 64
    source, destination = positional[1], positional[2]
    destination_dir = os.environ.get("STUB_RCLONE_DIR")
    if destination_dir:
        os.makedirs(destination_dir, exist_ok=True)
        leaf = destination.split("/")[-1]
        with open(source, "rb") as src:
            data = src.read()
        with open(os.path.join(destination_dir, leaf), "wb") as dst:
            dst.write(data)
        with open(os.path.join(destination_dir, "targets.txt"), "a", encoding="utf-8") as handle:
            handle.write(destination + "\n")
    return int(os.environ.get("STUB_RCLONE_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
