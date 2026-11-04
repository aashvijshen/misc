@echo off
setlocal EnableExtensions
title KIKKER-15 // Kikkerland 15-Note Music Box Studio

cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if exist ".venv\Scripts\python.exe" goto :check_deps

echo [Setup] Searching for Python 3.10+ on Windows ...
set "PY_CMD="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=py -3"
    goto :create_venv
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :create_venv
)

echo.
echo ====================================================================
echo   [ERROR] Python 3.10 or newer was not found on this Windows PC.
echo   1. Download Python 3.11+ from https://www.python.org/downloads/windows/
echo   2. IMPORTANT: Check "Add python.exe to PATH" in the installer!
echo   3. Double-click run_windows.bat again.
echo ====================================================================
echo.
pause
exit /b 1

:create_venv
echo [Setup] Creating local virtual environment (.venv) ...
%PY_CMD% -m venv ".venv"
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment in .venv
    pause
    exit /b 1
)

:check_deps
".venv\Scripts\python.exe" -c "import hashlib, pathlib, sys; req = hashlib.sha256(pathlib.Path('requirements.txt').read_bytes()).hexdigest(); st = pathlib.Path('.venv/.deps_stamp'); ok = st.exists() and st.read_text().strip() == req; raise SystemExit(0 if ok else 1)" >nul 2>nul
if not errorlevel 1 goto :launch_app

echo [Setup] Installing Python packages (first run only) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install dependencies from requirements.txt.
    echo Check your internet connection and re-run run_windows.bat.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import hashlib, pathlib; pathlib.Path('.venv/.deps_stamp').write_text(hashlib.sha256(pathlib.Path('requirements.txt').read_bytes()).hexdigest())"

:launch_app
".venv\Scripts\python.exe" launch.py %*
if errorlevel 1 (
    echo.
    echo [Server exited with an error]
    pause
    exit /b 1
)
endlocal
