#!/bin/bash
# Build and run AutoVOD in Docker for one streamer.
#
#   ./buildRunDocker.sh StreamerName
#
# The config file (and, for YouTube, client_secrets.json/request.token) must
# exist next to this script. Secrets are mounted, never baked into the image.
set -Eeuo pipefail

name="${1:-}"
if [[ -z "$name" ]]; then
    echo "usage: $0 <StreamerName>   (needs ./StreamerName.config)" >&2
    exit 1
fi

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

if [[ ! -f "$name.config" ]]; then
    echo "error: $name.config not found - copy default.config and edit it" >&2
    exit 1
fi

mounts=(-v "$here/$name.config:/autovod/$name.config:ro")
for secret in client_secrets.json request.token; do
    if [[ -f "$here/$secret" ]]; then
        mounts+=(-v "$here/$secret:/autovod/$secret:ro")
    fi
done

recordings="${AUTOVOD_RECORDINGS:-$here/recordings}"
mkdir -p "$recordings"
mounts+=(-v "$recordings:/recordings")

docker build -t autovod .
docker rm -f "autovod-$name" >/dev/null 2>&1 || true
docker run -d --name "autovod-$name" --restart unless-stopped \
    "${mounts[@]}" \
    -e AUTOVOD_LOCAL_DIR="${AUTOVOD_LOCAL_DIR:-/recordings}" \
    -e AUTOVOD_TEMP_DIR="${AUTOVOD_TEMP_DIR:-/tmp/autovod}" \
    autovod -n "$name"

echo "started container autovod-$name"
echo "logs:       docker logs -f autovod-$name"
echo "recordings: $recordings"
