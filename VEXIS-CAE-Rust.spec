# -*- mode: python ; coding: utf-8 -*-
import os

HERE = os.path.abspath(os.getcwd())
REPO_ROOT = HERE
LIBS_ROOT = os.path.join(REPO_ROOT, "src", "libs")
ICON_PATH = os.path.join(HERE, "src", "icons", "icon.ico")

a = Analysis(
    ["gui_main.py"],
    pathex=[HERE, REPO_ROOT, LIBS_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=["PySide6.QtSvg", "vexis_vulkan_core", "waffleiron", "waffleiron.xplt"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VEXIS-CAE-Rust",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[ICON_PATH] if os.path.exists(ICON_PATH) else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VEXIS-CAE-Rust",
)
