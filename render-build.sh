#!/usr/bin/env bash
set -e

# Install ffmpeg and font tools
apt-get update && apt-get install -y ffmpeg fontconfig

# Download Japanese font directly into the project
FONT_DIR="/opt/render/project/src/fonts"
mkdir -p "$FONT_DIR"

# Try multiple font sources as fallback
FONT_OK=false

# Source 1: Google Fonts GitHub (variable font)
if [ "$FONT_OK" = false ]; then
  curl -fsSL -o "$FONT_DIR/NotoSansJP-Bold.otf" \
    "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/Japanese/NotoSansCJKjp-Bold.otf" && FONT_OK=true || true
fi

# Source 2: Alternative URL
if [ "$FONT_OK" = false ]; then
  curl -fsSL -o "$FONT_DIR/NotoSansJP-Bold.otf" \
    "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf" && FONT_OK=true || true
fi

# Source 3: Install system package as last resort
if [ "$FONT_OK" = false ]; then
  apt-get install -y fonts-noto-cjk
  # Copy the installed font to our fonts dir
  find /usr/share/fonts -name "*NotoSansCJK*" -o -name "*NotoSans*JP*" | head -1 | xargs -I{} cp {} "$FONT_DIR/NotoSansJP-Bold.otf" || true
fi

# Register fonts with fontconfig
cp "$FONT_DIR"/*.otf /usr/local/share/fonts/ 2>/dev/null || cp "$FONT_DIR"/*.ttf /usr/local/share/fonts/ 2>/dev/null || true
fc-cache -fv

# Verify font is available
echo "=== Installed fonts ==="
ls -la "$FONT_DIR"/
fc-list | grep -i "noto" || echo "WARNING: Noto font not found in fc-list"

pip install --upgrade pip
pip install -r requirements.txt
