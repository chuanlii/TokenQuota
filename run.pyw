"""无控制台窗口的启动脚本（配合 pythonw.exe 使用）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
