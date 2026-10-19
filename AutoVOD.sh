#!/bin/bash
# AutoVOD 3.x compatibility entry point.
#
# The recorder/uploader itself is autovod.py now (see README.md and REVIEW.md).
# This shim exists so existing pm2/systemd units keep working unchanged:
#
#     pm2 start AutoVOD.sh --name StreamerName -- StreamerName
#     ./AutoVOD.sh -n StreamerName
#
# It simply forwards every argument to autovod.py using a Python >= 3.8.
# The 2.x bash implementation is preserved in legacy/AutoVOD-bash.sh.

set -Eeuo pipefail

DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# MSYS/git-bash hands out /c/... paths that a native python.exe cannot open
if command -v cygpath >/dev/null 2>&1; then
    SCRIPT_DIR="$(cygpath -w "$DIR")"
else
    SCRIPT_DIR="$DIR"
fi

usable_python() {
    # a candidate counts only if it really starts and is at least Python 3.8
    command -v "$1" >/dev/null 2>&1 || return 1
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1
}

PYTHON="${AUTOVOD_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
    for candidate in "${DIR}/.venv/bin/python3" "${DIR}/.venv/bin/python" python3 python; do
        if usable_python "$candidate"; then
            PYTHON="$candidate"
            break
        fi
    done
fi

if [[ -z "$PYTHON" ]]; then
    echo "error: no usable python3 (>= 3.8) found - install it or set AUTOVOD_PYTHON" >&2
    exit 127
fi

exec "$PYTHON" "${SCRIPT_DIR}/autovod.py" "$@"
