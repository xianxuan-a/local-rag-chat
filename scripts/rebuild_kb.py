"""重建知识库索引的命令行入口（后续阶段实现）。"""

from __future__ import annotations

import sys


def main() -> int:
    """明确报告当前阶段尚未提供索引重建功能。"""

    print(
        "rebuild_kb 尚未实现：当前版本不会解析文档或连接 Chroma。",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
