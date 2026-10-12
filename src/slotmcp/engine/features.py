"""特性算子：扩展 Wild、级联坠落、Hold & Win 网格处理。

每个算子都是「输入网格 -> 输出网格 + 事件描述」的纯函数（除 RNG 采样外），
便于被主循环按配置自由组合，也便于单独写单元测试。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from .evaluator import Position
from .reels import Grid, ReelStripSet
from .rng import SlotRNG

__all__ = [
    "collect_positions",
    "count_symbols",
    "expand_wild_reels",
    "cascade_collapse",
    "place_random_wilds",
    "collect_coins",
]


def place_random_wilds(
    grid: Grid,
    symbol_id: str,
    count: int,
    rng: SlotRNG,
    exclude_reels: Sequence[int] = (),
    protected_symbols: Sequence[str] = (),
) -> List[Position]:
    """在网格中随机挑选 `count` 个可覆盖位置替换为 Wild。

    * 只覆盖普通位置：已经是 Wild、以及 `protected_symbols`（Scatter / 币值 / 奖池）不覆盖
    * 位置采样用 Fisher-Yates 洗牌，保证均匀且与两端引擎可复现
    """
    if count <= 0:
        return []
    protected = set(protected_symbols or ())
    protected.add(symbol_id)
    skipped = set(int(r) for r in exclude_reels or ())
    candidates = [
        (reel_idx, row)
        for reel_idx, column in enumerate(grid)
        if reel_idx not in skipped
        for row, sym in enumerate(column)
        if sym not in protected
    ]
    n = min(count, len(candidates))
    if n <= 0:
        return []
    for i in range(len(candidates) - 1, 0, -1):  # Fisher-Yates，与 JS 端一致
        j = rng.int_below(i + 1)
        candidates[i], candidates[j] = candidates[j], candidates[i]
    picked = candidates[:n]
    for reel_idx, row in picked:
        grid[reel_idx][row] = symbol_id
    return sorted(picked)


def collect_coins(grid: Grid, coin_symbols: Sequence[str]) -> List[Position]:
    """返回网格中所有币值符号的位置（按轴、行升序），用于 Cash Collect 结算。"""
    wanted = set(coin_symbols)
    return [
        (reel_idx, row)
        for reel_idx, column in enumerate(grid)
        for row, sym in enumerate(column)
        if sym in wanted
    ]


def collect_positions(grid: Grid, symbol_ids: Sequence[str]) -> List[Position]:
    wanted = set(symbol_ids)
    return [
        (reel_idx, row)
        for reel_idx, reel in enumerate(grid)
        for row, sym in enumerate(reel)
        if sym in wanted
    ]


def count_symbols(grid: Grid, symbol_ids: Sequence[str]) -> int:
    wanted = set(symbol_ids)
    return sum(1 for reel in grid for sym in reel if sym in wanted)


def expand_wild_reels(grid: Grid, symbol_id: str, reels: Sequence[int]) -> List[Position]:
    """把出现 `symbol_id` 的指定轴整列替换为 Wild。

    返回被扩展的坐标列表；若该轴本来没有该符号则不动。
    """
    if not reels:
        return []
    target_reels = set(int(r) for r in reels)
    expanded: List[Position] = []
    for reel_idx, reel in enumerate(grid):
        if reel_idx not in target_reels:
            continue
        if symbol_id not in reel:
            continue
        for row in range(len(reel)):
            grid[reel_idx][row] = symbol_id
            expanded.append((reel_idx, row))
    return expanded


def cascade_collapse(
    grid: Grid,
    strip_set: ReelStripSet,
    remove_positions: Sequence[Position],
    rng: SlotRNG,
    replacement_symbols: Optional[Sequence[str]] = None,
) -> Grid:
    """移除中奖符号后，其余符号下沉、顶部由新符号补齐。

    * `remove_positions`：(reel, row) 坐标
    * 默认从当前条带集合等概率补位；传入 `replacement_symbols` 则从中均匀取（用于 Boost 区域）
    """
    removed: Dict[int, set] = {}
    for reel_idx, row in remove_positions:
        removed.setdefault(reel_idx, set()).add(row)

    new_grid: Grid = []
    for reel_idx, reel in enumerate(grid):
        rows_to_drop = removed.get(reel_idx, set())
        survivors = [sym for row, sym in enumerate(reel) if row not in rows_to_drop]
        missing = len(reel) - len(survivors)
        if missing <= 0:
            new_grid.append(list(reel))
            continue
        padding: List[str] = []
        for _ in range(missing):
            if replacement_symbols:
                padding.append(replacement_symbols[rng.int_below(len(replacement_symbols))])
            else:
                strip = strip_set.strips[reel_idx]
                padding.append(strip.symbols[rng.int_below(strip.length)])
        new_grid.append(padding + survivors)
    return new_grid


def top_up_flat(grid: Grid, strip_set: ReelStripSet, rng: SlotRNG) -> Grid:
    """整体重掷（Hold & Win 里对未锁定格子的处理）。"""
    out: Grid = []
    for reel_idx, reel in enumerate(grid):
        strip = strip_set.strips[reel_idx]
        out.append([strip.symbols[rng.int_below(strip.length)] for _ in reel])
    return out


def positions_to_keys(positions: Sequence[Position]) -> List[str]:
    return [f"{r},{c}" for r, c in positions]


def keys_to_positions(keys: Sequence[str]) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for key in keys:
        r, _, c = key.partition(",")
        out.append((int(r), int(c)))
    return out
