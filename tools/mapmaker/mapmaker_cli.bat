@echo off
setlocal
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" mapmaker_cli.py %*
    exit /b %errorlevel%
)

py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if %errorlevel% equ 0 (
    py -3 mapmaker_cli.py %*
    exit /b %errorlevel%
)

python mapmaker_cli.py %*
