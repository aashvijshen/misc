@echo off
setlocal
title MapMaker 3D — Build Standalone Windows .EXE
cd /d "%~dp0"

echo ==================================================
echo     BUILDING STANDALONE MAPMAKER3D.EXE (WINDOWS)
echo ==================================================

call run_mapmaker.bat --help >nul 2>nul
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] Please run run_mapmaker.bat once first to initialize .venv.
    pause
    exit /b 1
)

echo [*] Installing PyInstaller into .venv...
"%VENV_PY%" -m pip install pyinstaller

echo [*] Compiling single-file MapMaker3D.exe...
"%VENV_PY%" -m PyInstaller --noconfirm --clean --onefile ^
    --name "MapMaker3D" ^
    --add-data "gui;gui" ^
    --collect-data "matplotlib" ^
    --collect-submodules "shapely" ^
    --collect-submodules "scipy.spatial" ^
    --collect-submodules "scipy.ndimage" ^
    app.py

echo.
if exist "dist\MapMaker3D.exe" (
    echo [SUCCESS] Built standalone executable: dist\MapMaker3D.exe
) else (
    echo [ERROR] Build failed. Check output above.
)
pause
