"""特性算子：扩展 Wild、级联坠落、Hold & Win 网格处理。

每个算子都是「输入网格 -> 输出网格 + 事件描述」的纯函数（除 RNG 采样外），
便于被主循环按配置自由组合，也便于单独写单元测试。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from .config import GameConfig, PickBonusConfig
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
    "resolve_pick_bonus",
    "place_colossal_symbol",
]


def place_colossal_symbol(
    grid: Grid,
    cfg: GameConfig,
    cc: Any,
    rng: SlotRNG,
    phase: str = "base",
) -> Optional[Dict[str, Any]]:
    """投放一个 N×N 巨符号块，直接改写网格并返回事件描述。

    抽样顺序（与 JS 端一致）：块尺寸 -> 最左轴 -> 最上排 -> 符号；
    若块内存在受保护符号（Scatter / 币值等）则放弃本次投放。
    """
    if not cc or not cc.enabled:
        return None
    if phase not in (cc.phases or ["base"]):
        return None

    sizes = sorted(int(k) for k in cc.size_weights if int(k) > 0)
    if not sizes:
        return None
    size_total = sum(int(cc.size_weights[s]) for s in sizes)
    target = rng.random() * size_total
    acc = 0
    size = sizes[-1]
    for s in sizes:
        acc += int(cc.size_weights[s])
        if target < acc:
            size = s
            break
    if size <= 1:
        return None

    reels = [int(r) for r in cc.reels if 0 <= int(r) <= len(grid) - size]
    rows = [int(r) for r in cc.rows if 0 <= int(r) <= len(grid[0]) - size]
    if not reels or not rows:
        return None
    left = reels[int(rng.random() * len(reels))]
    top = rows[int(rng.random() * len(rows))]

    sym_ids = list(cc.symbols.keys())
    sym_total = sum(int(cc.symbols[s]) for s in sym_ids)
    if sym_total <= 0:
        return None
    target = rng.random() * sym_total
    acc = 0
    symbol_id = sym_ids[-1]
    for s in sym_ids:
        acc += int(cc.symbols[s])
        if target < acc:
            symbol_id = s
            break

    protected = set(cc.protected_symbols or [])
    positions: List[Position] = []
    for reel_idx in range(left, left + size):
        for row_idx in range(top, top + size):
            if grid[reel_idx][row_idx] in protected:
                return None
            positions.append((reel_idx, row_idx))
    for reel_idx in range(left, left + size):
        for row_idx in range(top, top + size):
            grid[reel_idx][row_idx] = symbol_id
    return {
        "type": "colossal",
        "symbol": symbol_id,
        "size": size,
        "reel": left,
        "row": top,
        "positions": positions,
    }


def resolve_pick_bonus(
    cfg: GameConfig, pb: PickBonusConfig, picks: int, rng: SlotRNG
) -> Tuple[List[str], float]:
    """Pick'em 选择式奖励：按权重抽取奖品并累计奖励（总注倍数）。

    返回 `(抽中的奖品列表, 累计奖励)`。`unique=True` 为无放回（抽过的奖品不再出现），
    奖品抽完即提前结束；RNG 消耗与 JS 端一致（加权轮盘 + 顺序扫描）。
    """
    prizes = list(pb.prize_pool.keys())
    weights = {p: max(0, int(pb.weights.get(p, 0))) for p in prizes}
    chosen: List[str] = []
    total = 0.0
    for _ in range(max(0, int(picks))):
        candidates = [p for p in prizes if p not in chosen] if pb.unique else list(prizes)
        remaining = sum(weights.get(p, 0) for p in candidates)
        if not candidates or remaining <= 0:
            break
        target = rng.random() * remaining
        acc = 0
        picked = candidates[-1]
        for p in candidates:
            acc += weights.get(p, 0)
            if target < acc:
                picked = p
                break
        chosen.append(picked)
        total += float(pb.prize_pool.get(picked, 0.0))
    return chosen, round(total * float(pb.award_multiplier), 6)


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
