"""一键跑通全部自测（引擎 / MCP / Blender 桥接 / Web UI / 静态站 / 外部服务）。

    python tests/run_tests.py            # 全部
    python tests/run_tests.py engine mcp # 只跑指定模块
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITES = ["engine", "mcp", "bridge", "ui", "static_site", "services"]


def run(suite: str) -> int:
    print(f"\n{'=' * 58}\n>>> tests/test_{suite}.py\n{'=' * 58}")
    started = time.time()
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests" / f"test_{suite}.py")],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src"), **dict(__import__("os").environ)},
    )
    print(f"—— {suite} 用时 {time.time() - started:.1f}s，退出码 {result.returncode}")
    return result.returncode


def main(argv: list) -> int:
    suites = argv if argv else SUITES
    unknown = [s for s in suites if s not in SUITES]
    if unknown:
        print(f"未知套件: {unknown}（可选: {', '.join(SUITES)}）")
        return 2

    failures = []
    for suite in suites:
        if run(suite) != 0:
            failures.append(suite)
    if failures:
        print(f"\n[NG] 失败套件: {', '.join(failures)}")
        return 1
    print("\n[OK] 全部测试通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
