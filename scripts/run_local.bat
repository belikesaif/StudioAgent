@echo off
REM StudioAgent - Local Development Launch Script (Windows)

echo === StudioAgent Local Dev ===

REM Check for .env
if not exist .env (
    echo No .env file found. Copying from .env.example...
    copy .env.example .env
    echo Please edit .env with your API keys, then re-run this script.
    exit /b 1
)

REM Create and/or activate virtual environment
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

REM Check for FFmpeg
where ffmpeg >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: FFmpeg is not installed or not on PATH.
    echo Install it from: https://ffmpeg.org/download.html
    echo Or via winget: winget install Gyan.FFmpeg
    exit /b 1
)

REM Install dependencies into venv
echo Installing dependencies...
pip install -r requirements.txt --quiet

REM Create temp directory
if not exist tmp mkdir tmp

REM Launch server
echo.
echo Starting StudioAgent on http://localhost:8080
echo.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
