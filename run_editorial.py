#!/usr/bin/env python3
"""隔离模式启动器：把包目录加入 sys.path 后转交 editorial.__main__。

用法（-I 保证不从当前目录或环境变量加载第三方代码）：
    python3 -I run_editorial.py check data/layout.json ...
"""

import sys
from pathlib import Path

PACKAGE_PARENT = Path(__file__).resolve().parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from editorial.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
