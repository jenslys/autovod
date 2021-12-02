#!/bin/bash

now=$(date +"%T")
g='\033[0;32m'
c='\033[0m'

printf "${g}[$now] Updating and upgrading packages...${c}\n"
apt-get -qq update && apt-get -qq upgrade

printf "${g}[$now] Installing Packages${c}\n"
sudo apt-get install npm python3-pip tar -y

printf "${g}[$now] Installing PM2${c}\n"
npm install pm2 -g && pm2 startup

printf "${g}[$now] Installing Streamlink${c}\n"
pip3 install --upgrade streamlink

printf "${g}[$now] Installing YouTubeUploader${c}\n"
wget https://github.com/porjo/youtubeuploader/releases/latest/download/youtubeuploader_linux_amd64.tar.gz
tar -xvf youtubeuploader_linux_amd64.tar.gz && rm youtubeuploader_linux_amd64.tar.gz
mv youtubeuploader_linux_amd64 /usr/local/bin/youtubeuploader

printf "${g}[$now] Installing AutoVOD${c}\n"
git clone https://github.com/jenslys/autovod.git && cd autovod

printf "${g}[$now] Installing Sample video${c}\n"
wget -c -O sample.mp4 https://download.samplelib.com/mp4/sample-5s.mp4
