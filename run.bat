@echo off
chcp 65001 >nul
title MahyarFree

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python not found. Install Python 3.11+ and try again.
    pause
    exit /b 1
)

python -c "import webview" >nul 2>nul
if errorlevel 1 (
    echo [i] Installing dependencies for the first run...
    python -m pip install -r requirements.txt
)

if not exist "mahyarfree\bin\sing-box.exe" (
    echo [i] Downloading proxy cores...
    python tools\fetch_cores.py
)

echo Starting MahyarFree...
start "" pythonw app.py
exit /b 0
