#!/usr/bin/env bash
set -e
pip install --upgrade pip
pip install setuptools wheel
export PIP_NO_BUILD_ISOLATION=false
pip install -r requirements.txt
