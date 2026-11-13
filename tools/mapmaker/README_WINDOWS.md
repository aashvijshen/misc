# Running MapMaker 3D on Windows 10 / 11

## Option A: Instant Double-Click Run (Recommended)
1. Install **Python 3.10+** from [python.org/downloads](https://www.python.org/downloads/) if not already installed.
2. Extract `MapMaker3D_Windows_Portable.zip` to any folder (e.g. `C:\Tools\MapMaker3D`).
3. Double-click **`run_mapmaker.bat`**.
   - On first run, it automatically creates a local `.venv` folder and installs `numpy`, `scipy`, `shapely`, `Pillow`, and `matplotlib` (takes ~30 seconds once).
   - Opens MapMaker 3D in a standalone Chrome/Edge app window on `http://127.0.0.1:8765` (bound to `127.0.0.1` so Windows Defender Firewall never prompts for admin permissions).
4. Click **✨ Generate STLs, Bambu .3MF & Preview**, then click **📂 Show in Explorer** to drag `full_assembly.3mf` directly into **Bambu Studio**!

## Option B: Command Line (`cmd.exe` / PowerShell)
```bat
mapmaker_cli.bat --location "Mount Fuji" --frame --orientation wall_hanging --title "MOUNT FUJI" --output exports\fuji
```

## Option C: Build a Zero-Python Standalone `MapMaker3D.exe`
Double-click **`build_windows_exe.bat`** on Windows to compile `dist\MapMaker3D.exe` via PyInstaller.
