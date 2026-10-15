@echo off
title MapMaker 3D Desktop Application
cd /d "%~dp0"

echo ==================================================
echo           MAPMAKER 3D WINDOWS LAUNCHER
echo ==================================================

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.9+ from https://www.python.org/
    pause
    exit /b 1
)

python -c "import numpy, scipy, shapely, PIL" >nul 2>nul
if %errorlevel% neq 0 (
    echo [*] Installing required Python dependencies...
    python -m pip install -r requirements.txt
)

python app.py
pause
