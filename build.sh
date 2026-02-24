#!/usr/bin/env bash
set -e

# Install ffmpeg + ffprobe (ffprobe comes bundled with ffmpeg)
apt-get update && apt-get install -y ffmpeg

# Verify
echo "✅ ffmpeg: $(ffmpeg -version 2>&1 | head -1)"
echo "✅ ffprobe: $(ffprobe -version 2>&1 | head -1)"

# Install Python deps
pip install -r requirements.txt

echo "✅ Build completed"
