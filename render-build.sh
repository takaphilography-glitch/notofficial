#!/usr/bin/env bash
set -e

# Install ffmpeg and Japanese fonts
apt-get update && apt-get install -y ffmpeg fonts-noto-cjk fontconfig
fc-cache -fv

pip install --upgrade pip
pip install -r requirements.txt
