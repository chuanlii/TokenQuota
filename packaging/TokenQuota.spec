# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（单文件 / 目录版两种形态共用一份 spec）。

用法（在仓库根目录）::

    python -m PyInstaller packaging/TokenQuota.spec --noconfirm

形态由环境变量控制（``build.ps1`` 会替你设好）：

* ``TOKENQUOTA_ONE_FILE`` —— 默认 ``1``，打成单个 ``TokenQuota.exe``；
  设成 ``0`` 则打成目录版 ``dist/TokenQuota/``（启动更快）。
* ``TOKENQUOTA_CONSOLE`` —— 默认 ``0``，不显示控制台窗口；设成 ``1`` 便于看报错。
"""

import os
from pathlib import Path

# SPECPATH 由 PyInstaller 注入，指向本文件所在目录
_SPEC_DIR = Path(SPECPATH)  # noqa: F821
ROOT = _SPEC_DIR.parent
ICON_PATH = _SPEC_DIR / "TokenQuota.ico"
VERSION_PATH = _SPEC_DIR / "version_info.txt"

ONE_FILE = os.environ.get("TOKENQUOTA_ONE_FILE", "1") != "0"
SHOW_CONSOLE = os.environ.get("TOKENQUOTA_CONSOLE", "0") == "1"

# 程序只用到 QtCore / QtGui / QtSvg / QtWidgets（网络走标准库 urllib），
# 其余 Qt 子模块一律排除——不排的话单文件包会从 ~60MB 涨到 200MB 以上。
QT_UNUSED = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtConcurrent",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.QtHelp",
    "PySide6.QtHttpServer",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtSvgWidgets",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtXml",
]

# 标准库里用不到的部分。注意别把 email 排掉：http.client 解析响应头要用它。
STDLIB_UNUSED = [
    "tkinter",
    "unittest",
    "pydoc",
    "doctest",
    "lib2to3",
    "setuptools",
    "pip",
    "distutils",
    "sqlite3",
]

analysis = Analysis(
    [str(_SPEC_DIR / "entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=QT_UNUSED + STDLIB_UNUSED,
    noarchive=False,
)

pyz = PYZ(analysis.pure)

_exe_kwargs = {
    "name": "TokenQuota",
    "debug": False,
    "bootloader_ignore_signals": False,
    "strip": False,
    # Qt 的 DLL 被 UPX 压过容易起不来，这里始终关掉
    "upx": False,
    "console": SHOW_CONSOLE,
    "disable_windowed_traceback": False,
    "argv_emulation": False,
    "target_arch": None,
    "codesign_identity": None,
    "entitlements_file": None,
    "icon": str(ICON_PATH) if ICON_PATH.is_file() else None,
    "version": str(VERSION_PATH) if VERSION_PATH.is_file() else None,
}

if ONE_FILE:
    exe = EXE(pyz, analysis.scripts, analysis.binaries, analysis.datas, [], **_exe_kwargs)
else:
    exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, **_exe_kwargs)
    collected = COLLECT(
        exe,
        analysis.binaries,
        analysis.datas,
        strip=False,
        upx=False,
        name="TokenQuota",
    )
