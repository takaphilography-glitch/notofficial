#!/usr/bin/env bash
set -e
pip install --upgrade pip
pip install setuptools wheel
pip install --no-build-isolation -r requirements.txt
