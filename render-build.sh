#!/usr/bin/env bash
set -e

# Install ffmpeg (required for video conversion)
apt-get update && apt-get install -y ffmpeg

pip install --upgrade pip
pip install setuptools wheel
pip install --no-build-isolation -r requirements.txt
