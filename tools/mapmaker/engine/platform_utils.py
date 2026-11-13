"""Cross-platform OS utilities for MapMaker 3D (Windows 10/11, macOS, Linux).

Centralizes:
- Native OS cache directory resolution (%LOCALAPPDATA%\\MapMaker3D\\cache on Windows).
- Cross-OS TrueType bold font discovery (bundled Matplotlib, Windows Fonts, macOS, Linux).
- SSL-resilient HTTPS opening for Windows certificate stores.
- Windows NTFS lock-tolerant file/folder cleanup ([WinError 32] protection).
- Native OS file manager launcher (Windows Explorer `os.startfile`, macOS `open`, Linux `xdg-open`).
- PyInstaller frozen-executable resource path resolution.
"""

import os
import sys
import ssl
import stat
import time
import shutil
import subprocess
import urllib.request
from typing import Optional


def is_windows() -> bool:
    return sys.platform == "win32" or os.name == "nt"


def get_app_root_dir() -> str:
    """Returns bundled resource root (supports PyInstaller `_MEIPASS` single-file .exe)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_writable_base_dir() -> str:
    """Returns writable directory for `exports/` (next to .exe when frozen, or project root)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_cache_dir() -> str:
    """Returns the native OS cache directory for geospatial tiles and vectors."""
    if is_windows():
        local_app = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(local_app, "MapMaker3D", "cache")
    return os.path.expanduser("~/.cache/mapmaker3d")


def resolve_bold_ttf_path() -> Optional[str]:
    """Finds an installed or bundled Bold Sans-Serif TrueType font across Windows, macOS, and Linux."""
    # 1. Bundled Matplotlib DejaVuSans-Bold (identical across Windows, macOS, and Linux!)
    try:
        import matplotlib
        mpl_font = os.path.join(
            os.path.dirname(matplotlib.__file__),
            "mpl-data", "fonts", "ttf", "DejaVuSans-Bold.ttf"
        )
        if os.path.exists(mpl_font):
            return mpl_font
    except Exception:
        pass

    candidates = []
    if is_windows():
        windir = os.environ.get("WINDIR", r"C:\Windows")
        fdir = os.path.join(windir, "Fonts")
        local_fdir = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"
        )
        for d in (fdir, local_fdir):
            if d:
                candidates.extend([
                    os.path.join(d, "segoeuib.ttf"),
                    os.path.join(d, "arialbd.ttf"),
                    os.path.join(d, "calibrib.ttf"),
                    os.path.join(d, "verdanab.ttf"),
                ])
    elif sys.platform == "darwin":
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ])

    candidates.extend([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ])

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def urlopen_resilient(req: urllib.request.Request, timeout: float = 15.0):
    """Opens an HTTPS request with automatic `certifi` fallback if Windows CA store fails verification."""
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as err:
        if isinstance(getattr(err, "reason", None), ssl.SSLError):
            try:
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
                return urllib.request.urlopen(req, timeout=timeout, context=ctx)
            except Exception:
                pass
        raise


def safe_remove_path(target_path: str, retries: int = 3):
    """Removes a file or directory tree safely on Windows NTFS (tolerates read-only bits & transient locks)."""
    if not os.path.exists(target_path):
        return

    def _onerror(func, path, _exc_info):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass

    for attempt in range(retries):
        try:
            if os.path.isdir(target_path) and not os.path.islink(target_path):
                shutil.rmtree(target_path, onerror=_onerror)
            else:
                os.chmod(target_path, stat.S_IWRITE)
                os.remove(target_path)
            return
        except PermissionError:
            if attempt < retries - 1:
                time.sleep(0.15)
        except Exception:
            return


def open_in_file_explorer(folder_path: str) -> bool:
    """Opens `folder_path` in Windows Explorer, macOS Finder, or Linux file manager."""
    abs_p = os.path.abspath(folder_path)
    if not os.path.exists(abs_p):
        return False
    try:
        if is_windows() and hasattr(os, "startfile"):
            os.startfile(os.path.normpath(abs_p))  # type: ignore[attr-defined]
            return True
        elif sys.platform == "darwin":
            subprocess.Popen(["open", abs_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        else:
            subprocess.Popen(["xdg-open", abs_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except Exception:
        return False
