"""RTP / 波动率回归验证脚本。

用法::

    python -m slotmcp.tools.verify_rtp                       # 验证全部机台，10 万局
    python -m slotmcp.tools.verify_rtp -g candy_carnival -n 200000
    python -m slotmcp.tools.verify_rtp --json report.json    # 输出机器可读报告

退出码非 0 表示存在超出容差的机台，可直接作为 CI 门槛。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..engine.game import get_registry
from ..engine.simulator import simulate

__all__ = ["main", "parse_args"]


def parse_args(argv: list | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Slot 机台 RTP 回归验证")
    parser.add_argument("-g", "--game", action="append", default=[], help="指定机台 id，可重复")
    parser.add_argument("-n", "--spins", type=int, default=100_000, help="每台仿真局数")
    parser.add_argument("-b", "--bet", type=float, default=1.0, help="单局下注额")
    parser.add_argument("-s", "--seed", type=int, default=20240604, help="随机种子")
    parser.add_argument("--json", dest="json_path", default="", help="导出 JSON 报告路径")
    parser.add_argument("--quiet", action="store_true", help="不打印进度")
    return parser.parse_args(argv)


def configure_console() -> None:
    """Windows 下默认控制台为 GBK，这里统一切成 UTF-8，避免打印表情/符号时抛异常。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - 不支持重配置时忽略
        pass


def main(argv: list | None = None) -> int:
    configure_console()
    args = parse_args(argv)
    registry = get_registry()
    game_ids = args.game or registry.ids()

    reports = []
    failed = []
    header = f"{'机台':<18}{'局数':>9}{'RTP':>9}{'命中率':>9}{'波动率':>9}{'最大倍率':>10}{'结论':>8}"
    print(header)
    print("-" * 76)
    for game_id in game_ids:
        machine = registry.get(game_id)

        def progress(done: int, total: int) -> None:
            if not args.quiet:
                print(f"  [{game_id}] {done}/{total}", flush=True)

        report = simulate(
            machine,
            spins=args.spins,
            bet=args.bet,
            seed=f"{args.seed}:{game_id}",
            progress_callback=progress,
        )
        reports.append(report.to_dict())
        if not report.within_tolerance:
            failed.append(game_id)
        print(
            f"{report.game_id:<18}{report.spins:>9}{report.rtp:>9.4f}"
            f"{report.hit_rate:>9.4f}{report.volatility:>9.2f}"
            f"{report.max_win_multiplier:>10.1f}{'OK' if report.within_tolerance else 'NG':>8}"
        )
        for etype, stats in report.feature_stats.items():
            freq = stats["frequency"]
            extra = (
                f"，RTP 贡献 {stats['rtp_contribution']:.4f}"
                if "rtp_contribution" in stats
                else ""
            )
            print(f"    - {etype:<22} 1/{1 / freq:>10.1f} 局触发{extra}")

    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n报告已写入: {args.json_path}")

    if failed:
        print(f"\n[NG] 超出容差的机台: {', '.join(failed)}")
        return 1
    print("\n[OK] 全部机台 RTP 均在容差内")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
