@echo off
setlocal EnableDelayedExpansion
title MapMaker 3D Desktop Studio
cd /d "%~dp0"

echo ==================================================
echo        MAPMAKER 3D — WINDOWS DESKTOP STUDIO
echo ==================================================

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    goto :check_deps
)

:: Probe py -3 first to avoid the Windows 10/11 Microsoft Store python.exe stub trap
set "SYS_PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if %errorlevel% equ 0 (
    set "SYS_PY=py -3"
    goto :create_venv
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if %errorlevel% equ 0 (
    set "SYS_PY=python"
    goto :create_venv
)

echo.
echo [ERROR] Python 3.9+ was not found on this Windows PC.
echo Please install Python 3.11 or 3.12 from https://www.python.org/downloads/
echo ^(Tip: The standard installer includes the 'py' launcher automatically.^)
echo.
pause
exit /b 1

:create_venv
echo [*] Creating isolated local Python environment (.venv)...
%SYS_PY% -m venv "%~dp0.venv"
if not exist "%VENV_PY%" (
    echo [ERROR] Could not create .venv. Falling back to system Python...
    set "VENV_PY=%SYS_PY%"
)

:check_deps
"%VENV_PY%" -c "import numpy, scipy, shapely, PIL, matplotlib" >nul 2>nul
if %errorlevel% neq 0 (
    echo [*] Installing required Python packages into .venv ^(first-time setup^)...
    "%VENV_PY%" -m pip install --upgrade pip >nul 2>nul
    "%VENV_PY%" -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies from requirements.txt.
        pause
        exit /b 1
    )
)

echo [*] Starting MapMaker 3D...
"%VENV_PY%" app.py %*
if %errorlevel% neq 0 (
    echo.
    echo [!] MapMaker 3D exited with an error.
    pause
)
