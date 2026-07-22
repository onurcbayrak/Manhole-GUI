# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: `pyinstaller build_exe.spec` -> dist/manhole-gui/manhole-gui.exe"""

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

for pkg in ("rasterio", "fiona", "pyogrio", "geopandas", "shapely", "ultralytics", "PySide6"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        pass

block_cipher = None

a = Analysis(
    ["src/sas_manhole_gui/app.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="manhole-gui",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="manhole-gui",
)
