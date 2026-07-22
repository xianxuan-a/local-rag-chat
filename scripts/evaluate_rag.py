"""RAG 评估命令行入口（后续阶段实现）。"""

from __future__ import annotations

import sys


def main() -> int:
    """明确报告当前阶段尚未提供 RAG 评估功能。"""

    print(
        "evaluate_rag 尚未实现：当前版本没有可评估的真实检索或模型问答。",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
