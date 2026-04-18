#!/usr/bin/env bash
set -e

# Install ffmpeg
apt-get update && apt-get install -y ffmpeg fontconfig

# Download Japanese font (Noto Sans JP)
mkdir -p /opt/render/project/src/fonts
curl -L -o /opt/render/project/src/fonts/NotoSansJP-Bold.ttf \
  "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP-Bold.ttf"
fc-cache -fv

pip install --upgrade pip
pip install -r requirements.txt
