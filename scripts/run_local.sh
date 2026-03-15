#!/bin/bash
# StudioAgent - Local Development Launch Script

set -euo pipefail

echo "=== StudioAgent Local Dev ==="

# Check for .env
if [ ! -f .env ]; then
    echo "No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "Please edit .env with your API keys, then re-run this script."
    exit 1
fi

# Check for FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "ERROR: FFmpeg is not installed or not on PATH."
    echo "Install it from: https://ffmpeg.org/download.html"
    exit 1
fi

# Check for Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "ERROR: Python is not installed or not on PATH."
    exit 1
fi

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create temp directory
mkdir -p tmp

# Launch server
echo ""
echo "Starting StudioAgent on http://localhost:8080"
echo ""
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
