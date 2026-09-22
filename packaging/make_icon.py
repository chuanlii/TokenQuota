"""生成 exe 图标 ``TokenQuota.ico``。

图标不是另画的：直接复用 ``app.tray.icon_pixmap`` 里托盘图标那份几何，
所以 exe、任务栏、托盘三处看到的是同一个图形。

Qt 只能写 PNG/BMP，不能写 ICO，这里自己拼 ICO 容器（PNG 压缩条目，
Windows Vista 以后都认），因此不引入 Pillow 之类的额外构建依赖。

用法（仓库根目录）::

    python packaging/make_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

#: 让 `import app...` 能找到包（脚本直接运行时 sys.path[0] 是 packaging/）
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication, QPixmap  # noqa: E402

from app.tray import icon_pixmap  # noqa: E402

OUT_PATH = HERE / "TokenQuota.ico"

#: Windows 各界面上会用到的小尺寸都给一份，避免系统拿大图硬缩。
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _png_bytes(pixmap: QPixmap) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not pixmap.save(buffer, "PNG"):
        raise RuntimeError("QPixmap 写 PNG 失败")
    return bytes(buffer.data())


def _ico_container(images: list[tuple[int, bytes]]) -> bytes:
    """把若干 (边长, PNG 字节) 拼成 ICO 文件。"""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = bytearray()
    body = bytearray()
    for side, data in images:
        # 256 在这个单字节字段里按规范写 0
        dim = 0 if side >= 256 else side
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        body += data
        offset += len(data)
    return bytes(header) + bytes(entries) + bytes(body)


def build() -> Path:
    if QGuiApplication.instance() is None:
        # QPixmap 要求有 GUI application 实例；这里只是离屏画图，不需要窗口
        QGuiApplication(sys.argv[:1])

    images = [(side, _png_bytes(icon_pixmap(side))) for side in SIZES]
    OUT_PATH.write_bytes(_ico_container(images))
    return OUT_PATH


def main() -> int:
    path = build()
    print(f"已生成 {path}（{path.stat().st_size} 字节，{len(SIZES)} 个尺寸）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
