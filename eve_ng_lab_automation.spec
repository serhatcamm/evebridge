# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build spec for EVE-NG Lab Automation.
Produces a single-file Windows executable with the app icon embedded, both
as the .exe's own file icon (shown in Explorer/pinned shortcuts) and applied
at runtime to the window/taskbar (main_app.py's get_app_icon_path() knows how
to find icon.ico whether running as a plain script or from inside this build).

IMPORTANT: PyInstaller does not cross-compile — you must run this ON a
Windows machine to get a Windows .exe. The easiest way is double-clicking
build_exe.bat, which installs dependencies and invokes this spec for you.
Manual equivalent:  pyinstaller eve_ng_lab_automation.spec --noconfirm
"""

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# A handful of imports PyInstaller's static analysis can miss because they're
# pulled in through optional/try-except imports (paramiko's crypto backends).
# Over-including here is harmless; it just means slightly larger output, not a
# broken build.
hidden_imports = [
    'PyQt6.QtSvg',
    'PyQt6.QtPrintSupport',
]
hidden_imports += collect_submodules('paramiko')

a = Analysis(
    ['main_app.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.')],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='EVE-NG-Lab-Automation',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,               # windowed app, no console box behind it
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
