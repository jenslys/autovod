#!/bin/bash
# shellcheck disable=SC2059

now=$(date +"%T")
g='\033[0;32m'
c='\033[0m'
log_file="autovod_installation.log"

# Log all the outputs of the script to the log file
exec &> >(tee -a "$log_file")

# Check if apt or yum is installed
if command -v apt-get &>/dev/null; then
  package_manager='apt-get'
  install_command='install'
  update_command='update'
  upgrade_command='upgrade'
elif command -v yum &>/dev/null; then
  package_manager='yum'
  install_command='install'
  update_command='check-update'
  upgrade_command='upgrade'
elif command -v dnf &>/dev/null; then
  package_manager='dnf'
  install_command='install'
  update_command='check-update'
  upgrade_command='upgrade'
else
  printf "${g}[$now] Error: Could not find a supported package manager. Exiting...${c}\n"
  exit 1
fi

printf "${g}[$now] Updating and upgrading packages...${c}\n"
$package_manager -qq $update_command && $package_manager -qq $upgrade_command

printf "${g}[$now] Installing necessary Packages...${c}\n"

# Package names for apt
apt_packages=(npm wget curl git python3-pip tar jq)
# Package names for yum
yum_packages=(npm wget curl git python3-pip tar jq)
# Package names for DNF
dnf_packages=(npm wget curl git python3-pip tar jq)

# Use the appropriate package array based on the detected package manager
if [ "$package_manager" = "apt-get" ]; then
  packages=("${apt_packages[@]}")
elif [ "$package_manager" = "yum" ]; then
  packages=("${yum_packages[@]}")
elif [ "$package_manager" = "dnf" ]; then
  packages=("${dnf_packages[@]}")
fi

# Install the packages
for package in "${packages[@]}"; do
  dpkg -s "$package" &>/dev/null
  if [ $? -eq 0 ]; then
    printf "${g}[$now] $package already installed...${c}\n"
  else
    sudo $package_manager $install_command "$package" -y
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

printf "${g}[$now] Install Rclone [Y/N]? ${c}\n"
read -r answer
if [ "$answer" = "Y" ]; then
  if ! [ -x "$(command -v rclone)" ]; then
    sudo $package_manager $install_command rclone -y
  else
    printf "${g}[$now] Rclone is already installed. Skipping...${c}\n"
  fi
else
  printf "${g}[$now] Skipping Rclone installation...${c}\n"
fi

printf "${g}[$now] Installing AutoVOD${c}\n"
if [ ! -d "./autovod" ]; then
  git clone https://github.com/jenslys/autovod.git && cd autovod || exit
else
  printf "${g}[$now] AutoVOD is already installed. Skipping...${c}\n"
fi

printf "${g}[$now] Installing Sample video${c}\n"
if [ ! -f "./sample.mp4" ]; then
  wget -c -O sample.mp4 https://download.samplelib.com/mp4/sample-5s.mp4
else
  printf "${g}[$now] Sample video is already present. Skipping...${c}\n"
fi
