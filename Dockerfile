FROM alpine:latest

# Download sample file used to generating the token
RUN wget -c -O /tmp/sample.mp4 https://download.samplelib.com/mp4/sample-5s.mp4

# Install dependancies
RUN apk add --update nodejs npm tar py-pip bash nano gcc libc-dev

# Install youtube uploader library
RUN wget https://github.com/porjo/youtubeuploader/releases/latest/download/youtubeuploader_linux_amd64.tar.gz && \
  tar -xvf youtubeuploader_linux_amd64.tar.gz && rm youtubeuploader_linux_amd64.tar.gz && \
  mv youtubeuploader_linux_amd64 /usr/local/bin/youtubeuploader

# Install streamlink
RUN pip3 install --upgrade streamlink

WORKDIR /app
