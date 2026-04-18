#!/usr/bin/env bash
set -e

# Install ffmpeg (required for video conversion)
apt-get update && apt-get install -y ffmpeg

pip install --upgrade pip
pip install -r requirements.txt
