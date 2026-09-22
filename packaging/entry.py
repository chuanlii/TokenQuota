"""PyInstaller 的打包入口，等价于仓库根目录的 ``run.pyw``。

单独放一个 ``.py`` 而不是直接拿 ``.pyw`` 去分析：PyInstaller 对 ``.pyw`` 的
处理依赖后缀推断，用普通 ``.py`` 更稳，控制台窗口由 spec 里的 ``console=False`` 关掉。
"""

from __future__ import annotations

import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
