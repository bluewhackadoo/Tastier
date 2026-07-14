# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Tastier desktop release.

Builds a one-file executable for Windows and a single .app bundle for macOS.
Dev workflow remains unchanged: uvicorn app.main:app --reload
"""
import sys
from pathlib import Path

from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis

if sys.platform == 'darwin':
    from PyInstaller.building.osx import BUNDLE


ROOT = Path(SPECPATH).resolve()  # type: ignore[name-defined]


a = Analysis(
    ['run_app.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        ('app', 'app'),
        ('static', 'static'),
        ('.env.example', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest',
        '_pytest',
        'numpy.tests',
        'scipy',
        'tkinter',
        'matplotlib',
        'PIL',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Tastier',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='Tastier.app',
        icon=None,
        bundle_identifier='com.tastier.app',
    )
