#!/bin/bash

now=$(date +"%T")
g='\033[0;32m'
c='\033[0m'

printf "${g}[$now] Updating and upgrading packages...${c}\n"
apt-get -qq update && apt-get -qq upgrade

printf "${g}[$now] Installing necessary Packages${c}\n"

packages=(npm wget curl git python3-pip tar jq)
for package in "${packages[@]}"; do
  dpkg -s "$package" &>/dev/null
  if [ $? -eq 0 ]; then
    printf "${g}[$now] $package already installed...${c}\n"
  else
    sudo apt-get install "$package" -y
  fi
done

printf "${g}[$now] Installing PM2${c}\n"
if ! [ -x "$(command -v pm2)" ]; then
  npm install pm2 -g && pm2 startup
else
  printf "${g}[$now] PM2 is already installed. Skipping...${c}\n"
fi

printf "${g}[$now] Installing Streamlink${c}\n"
if ! [ -x "$(command -v streamlink)" ]; then
  pip3 install --upgrade streamlink
else
  printf "${g}[$now] Streamlink is already installed. Skipping...${c}\n"
fi

printf "${g}[$now] Install YouTubeUploader [Y/N]? ${c}\n"
read -r answer
if [ "$answer" = "Y" ]; then
  if [ ! -f "/usr/local/bin/youtubeuploader" ]; then
    wget https://github.com/porjo/youtubeuploader/releases/download/23.01/youtubeuploader_23.01_Linux_x86_64.tar.gz
    tar -xvf youtubeuploader_23.01_Linux_x86_64.tar.gz && rm youtubeuploader_23.01_Linux_x86_64.tar.gz
    mv youtubeuploader /usr/local/bin/youtubeuploader
  else
    printf "${g}[$now] YouTubeUploader is already installed. Skipping...${c}\n"
  fi
else
  printf "${g}[$now] Skipping YouTubeUploader installation...${c}\n"
fi

printf "${g}[$now] Install AWS CLI [Y/N]? ${c}\n"
read -r answer
if [ "$answer" = "Y" ]; then
  if ! [ -x "$(command -v aws)" ]; then
    sudo apt-get install awscli -y
  else
    printf "${g}[$now] AWS CLI is already installed. Skipping...${c}\n"
  fi
else
  printf "${g}[$now] Skipping AWS CLI installation...${c}\n"
fi

printf "${g}[$now] Installing AutoVOD${c}\n"
if [ ! -d "./autovod" ]; then
  git clone https://github.com/jenslys/autovod.git && cd autovod
else
  printf "${g}[$now] AutoVOD is already installed. Skipping...${c}\n"
fi

printf "${g}[$now] Installing Sample video${c}\n"
if [ ! -f "./sample.mp4" ]; then
  wget -c -O sample.mp4 https://download.samplelib.com/mp4/sample-5s.mp4
else
  printf "${g}[$now] Sample video is already present. Skipping...${c}\n"
fi
