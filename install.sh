#!/bin/bash
# AutoVOD 3.x installer - idempotent, supports apt and dnf (and warns on others).
#
#   sh -c "$(curl -fsSL https://raw.githubusercontent.com/jenslys/autovod/master/install.sh)"
#
# What it does
#   1. installs the system packages AutoVOD needs (git, python3, venv, jq is NOT
#      needed anymore, tar, wget, curl, ffmpeg, npm only if you want pm2)
#   2. installs streamlink and, optionally, rclone/youtubeuploader
#   3. clones/updates AutoVOD and installs it into its own virtualenv
#
# Everything is re-runnable: existing packages, binaries and the checkout are
# detected and skipped instead of being reinstalled.
set -Eeuo pipefail

now=$(date +"%T")
g='\033[0;32m'
y='\033[0;33m'
c='\033[0m'
log() { printf "${g}[%s] %s${c}\n" "$now" "$*"; }
warn() { printf "${y}[%s] %s${c}\n" "$now" "$*"; }

REPO_URL="${AUTOVOD_REPO:-https://github.com/jenslys/autovod.git}"
TARGET_DIR="${AUTOVOD_DIR:-$PWD/autovod}"
YOUTUBEUPLOADER_VERSION="${YOUTUBEUPLOADER_VERSION:-1.25.5}"

is_root() { [[ "${EUID:-$(id -u)}" -eq 0 ]]; }
SUDO=""
if ! is_root && command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
fi

# --- package manager --------------------------------------------------------
if command -v apt-get >/dev/null 2>&1; then
    PM="apt-get"; PM_INSTALL="$SUDO apt-get install -y"; PM_UPDATE="$SUDO apt-get update -qq"
elif command -v dnf >/dev/null 2>&1; then
    PM="dnf"; PM_INSTALL="$SUDO dnf install -y"; PM_UPDATE="$SUDO dnf check-update -q || true"
elif command -v pacman >/dev/null 2>&1; then
    PM="pacman"; PM_INSTALL="$SUDO pacman -S --noconfirm"; PM_UPDATE="$SUDO pacman -Sy"
else
    warn "unsupported package manager: install python3, python3-venv, pip, git, curl, wget and ffmpeg yourself"
    PM=""
fi

have() { command -v "$1" >/dev/null 2>&1; }

if [[ -n "$PM" ]]; then
    log "Updating package lists (no dist-upgrade, that is not our business)"
    $PM_UPDATE || warn "package list update failed, continuing"

    packages=(git curl wget python3 tar)
    # Debian/Ubuntu call the venv module python3-venv, Fedora python3-pip provides it
    if [[ "$PM" == "apt-get" ]]; then
        packages+=(python3-venv python3-pip)
    else
        packages+=(python3-pip)
    fi
    if ! have ffmpeg; then
        packages+=(ffmpeg)
    fi

    for package in "${packages[@]}"; do
        if [[ "$PM" == "apt-get" ]]; then
            if dpkg -s "$package" >/dev/null 2>&1; then
                log "$package already installed"
                continue
            fi
        else
            if rpm -q "$package" >/dev/null 2>&1; then
                log "$package already installed"
                continue
            fi
        fi
        log "installing $package"
        $PM_INSTALL "$package" || warn "could not install $package - continue without it"
    done
fi

# --- streamlink -------------------------------------------------------------
log "Installing Streamlink into $TARGET_DIR/.venv"
mkdir -p "$TARGET_DIR"
if [[ ! -d "$TARGET_DIR/.venv" ]]; then
    python3 -m venv "$TARGET_DIR/.venv" \
        || warn "python3-venv is missing - install it and re-run this script"
fi
VENV_PY="$TARGET_DIR/.venv/bin/python3"
if [[ -x "$VENV_PY" ]]; then
    "$VENV_PY" -m pip install --upgrade pip >/dev/null
    "$VENV_PY" -m pip install --upgrade streamlink
    log "Streamlink $("$TARGET_DIR/.venv/bin/streamlink" --version 2>/dev/null | head -1) installed"
else
    warn "no virtualenv created - falling back to 'pipx install streamlink' or a distro package"
    if have streamlink; then
        log "system streamlink found: $(streamlink --version)"
    elif have pipx; then
        pipx install streamlink
    else
        warn "no streamlink available - AutoVOD cannot record without it"
    fi
fi

# --- optional binaries ------------------------------------------------------
if have rclone; then
    log "rclone already installed ($(rclone version | head -1))"
else
    if $PM_INSTALL rclone >/dev/null 2>&1; then
        log "rclone installed"
    else
        warn "rclone not installed - run 'rclone config' yourself if you need it"
    fi
fi

if have youtubeuploader; then
    log "youtubeuploader already installed"
else
    printf "${y}[%s] Install youtubeuploader (needed for UPLOAD_SERVICE=youtube)? [y/N] ${c}\n" "$now"
    read -r answer
    if [[ "$answer" == [yY] ]]; then
        case "$(uname -m)" in
            x86_64|amd64) arch="amd64" ;;
            aarch64|arm64) arch="arm64" ;;
            armv7l) arch="arm" ;;
            *) arch="" ;;
        esac
        if [[ -z "$arch" ]]; then
            warn "unsupported architecture $(uname -m) - download youtubeuploader manually"
        else
            url="https://github.com/porjo/youtubeuploader/releases/download/v${YOUTUBEUPLOADER_VERSION}/youtubeuploader_${YOUTUBEUPLOADER_VERSION}_Linux_${arch}.tar.gz"
            tmpdir=$(mktemp -d)
            if curl -fsSL "$url" -o "$tmpdir/youtubeuploader.tar.gz"; then
                tar -xzf "$tmpdir/youtubeuploader.tar.gz" -C "$tmpdir"
                $SUDO install -m 0755 "$tmpdir/youtubeuploader" /usr/local/bin/youtubeuploader
                log "youtubeuploader installed to /usr/local/bin/youtubeuploader"
            else
                warn "download failed: $url"
            fi
            rm -rf "$tmpdir"
        fi
    else
        log "skipping youtubeuploader"
    fi
fi

# --- AutoVOD itself ---------------------------------------------------------
if [[ -d "$TARGET_DIR/.git" ]]; then
    log "updating existing checkout in $TARGET_DIR"
    git -C "$TARGET_DIR" pull --ff-only || warn "git pull failed - resolve it manually"
else
    log "cloning $REPO_URL into $TARGET_DIR"
    git clone --depth 1 "$REPO_URL" "$TARGET_DIR"
fi
chmod +x "$TARGET_DIR/AutoVOD.sh" "$TARGET_DIR/autovod.py" 2>/dev/null || true

log "Done."
cat <<EOF

Next steps
  1. cd $TARGET_DIR
  2. cp default.config YourStreamerName.config && nano YourStreamerName.config
  3. ./autovod.py -n YourStreamerName --check     # preflight, tells you what is missing
  4. ./autovod.py -n YourStreamerName --list-streams
  5. pm2 start AutoVOD.sh --name YourStreamerName -- YourStreamerName
EOF
