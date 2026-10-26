# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the YDL Studio single-file executable.

    pyinstaller scripts/YDL-Studio.spec --noconfirm

The result is ``dist/YDL-Studio.exe``: one portable file with no Python, no
virtual environment and no FFmpeg required on the target machine.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
PACKAGE = ROOT / "ydl_studio"

# yt-dlp builds its extractor list at run time by scanning its own packages, so
# a static import analysis would freeze an executable that only recognises a
# handful of sites.
hiddenimports = sorted(
    set(collect_submodules("yt_dlp"))
    # Pillow loads these on demand when a Tk image is created.
    | {"PIL.ImageTk", "PIL._tkinter_finder"}
)

datas = [(str(PACKAGE / "assets"), "ydl_studio/assets")]

excludes = [
    "pytest",
    "ruff",
    "setuptools",
    "pkg_resources",
    "pydoc_data",
    "tkinter.test",
    "matplotlib",
    "numpy",
]

a = Analysis(
    [str(ROOT / "scripts" / "launch.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="YDL-Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PACKAGE / "assets" / "icon.ico"),
)
