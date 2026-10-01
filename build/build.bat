@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title MahyarFree - Build

echo ============================================================
echo   MahyarFree  -  Windows build
echo ============================================================
echo.

cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python not found in PATH. Install Python 3.11+ from python.org
    pause
    exit /b 1
)

echo [1/5] Installing build dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller pillow
if errorlevel 1 (
    echo [X] pip install failed
    pause
    exit /b 1
)

echo [2/5] Generating application icon...
python tools\make_icon.py

echo [3/5] Downloading proxy cores (sing-box + Xray)...
python tools\fetch_cores.py
if errorlevel 1 (
    echo [!] Core download failed - the app will fetch them on first run instead.
)

echo [4/4] Packaging with PyInstaller...
python -m PyInstaller build\mahyarfree.spec --noconfirm --clean
if errorlevel 1 (
    echo [X] PyInstaller failed
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   BUILD OK
echo   Output: dist\MahyarFree\MahyarFree.exe
echo ============================================================
echo.
if exist "dist\MahyarFree" explorer "dist\MahyarFree"
pause
