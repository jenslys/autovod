# AutoVOD 3.x image.
#
# Changes compared to 2.x:
#   * no credentials/secrets are COPYed at build time anymore - the OAuth files
#     and, more importantly, the streamer config are mounted at runtime, so the
#     same image serves every streamer and no secret ends up in a layer
#   * ffmpeg is included (re-encode / restream were broken inside the container)
#   * runs as a non-root user with a volume for recordings
#   * a virtualenv holds streamlink, so no PEP 668 "externally managed" problems
#   * tini for correct signal handling (docker stop -> clean finalisation)
FROM python:3.12-slim

ARG YOUTUBEUPLOADER_VERSION=1.25.5

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/autovod/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash ca-certificates curl ffmpeg rclone tini tzdata procps \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/autovod \
    && /opt/autovod/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/autovod/bin/pip install --no-cache-dir streamlink

# youtubeuploader (multi-arch: amd64/arm64)
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) ua="amd64" ;; \
        arm64) ua="arm64" ;; \
        *) echo "unsupported architecture $arch - youtube uploads will not work"; ua="" ;; \
    esac; \
    if [ -n "$ua" ]; then \
        curl -fsSL -o /tmp/yt.tar.gz "https://github.com/porjo/youtubeuploader/releases/download/v${YOUTUBEUPLOADER_VERSION}/youtubeuploader_${YOUTUBEUPLOADER_VERSION}_Linux_${ua}.tar.gz"; \
        tar -xzf /tmp/yt.tar.gz -C /usr/local/bin youtubeuploader; \
        rm -f /tmp/yt.tar.gz; \
        chmod +x /usr/local/bin/youtubeuploader; \
    fi

COPY autovod.py /autovod/autovod.py
COPY AutoVOD.sh /autovod/AutoVOD.sh
COPY default.config /autovod/default.config

RUN useradd --create-home --uid 1000 autovod \
    && mkdir -p /recordings \
    && chown -R autovod:autovod /autovod /recordings \
    && chmod +x /autovod/AutoVOD.sh /autovod/autovod.py

USER autovod
WORKDIR /autovod

# Mount your config + OAuth files here (read-only), e.g.:
#   -v $PWD/StreamerName.config:/autovod/StreamerName.config:ro
#   -v $PWD/client_secrets.json:/autovod/client_secrets.json:ro
#   -v $PWD/request.token:/autovod/request.token:ro
#   -v /srv/vods:/recordings
VOLUME ["/autovod", "/recordings"]

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
    CMD pgrep -f autovod.py >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/autovod/AutoVOD.sh"]
CMD ["--help"]
