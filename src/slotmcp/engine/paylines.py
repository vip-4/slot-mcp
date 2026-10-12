"""赔付线工具：内置经典线组 + 任意 (reels, rows) 的确定性线生成器。

线的表示：长度为 `reels` 的行号列表，索引即转轮序号。
例如 5x3 的经典 `LINE_INDEX_20` 中 `(1,1,1,1,1)` 是中间那条水平线。
"""

from __future__ import annotations

from itertools import product
from typing import List, Tuple

__all__ = [
    "LINES_5_3x3",
    "LINES_20_5x3",
    "generate_lines",
    "get_lines",
    "count_direction_changes",
]

# ----------------------------------------------------------------- 经典线组
#: 3x3 水果机的 5 条线（3 横 + 2 斜）
LINES_5_3x3: List[Tuple[int, ...]] = [
    (1, 1, 1),
    (0, 0, 0),
    (2, 2, 2),
    (0, 1, 2),
    (2, 1, 0),
]

#: 5x3 经典 20 线
LINES_20_5x3: List[Tuple[int, ...]] = [
    (1, 1, 1, 1, 1),
    (0, 0, 0, 0, 0),
    (2, 2, 2, 2, 2),
    (0, 1, 2, 1, 0),
    (2, 1, 0, 1, 2),
    (0, 0, 1, 2, 2),
    (2, 2, 1, 0, 0),
    (1, 0, 0, 0, 1),
    (1, 2, 2, 2, 1),
    (0, 1, 1, 1, 0),
    (2, 1, 1, 1, 2),
    (1, 0, 1, 2, 1),
    (1, 2, 1, 0, 1),
    (0, 1, 0, 1, 0),
    (2, 1, 2, 1, 2),
    (1, 1, 0, 1, 1),
    (1, 1, 2, 1, 1),
    (0, 2, 0, 2, 0),
    (2, 0, 2, 0, 2),
    (1, 0, 2, 0, 1),
]


def count_direction_changes(line: Tuple[int, ...]) -> int:
    """统计方向变化次数，用于给候选线排序：越“平直”的线排得越靠前。"""
    changes = 0
    prev = 0
    for i in range(1, len(line)):
        delta = line[i] - line[i - 1]
        if delta == 0:
            continue
        direction = 1 if delta > 0 else -1
        if prev != 0 and direction != prev:
            changes += 1
        prev = direction
    return changes


def generate_lines(reels: int, rows: int, count: int) -> List[List[int]]:
    """为任意尺寸生成确定性的 `count` 条赔付线。

    算法：枚举全部 `rows ** reels` 候选线，按 `(曲折程度, 字典序)` 升序排序后取前 N 条。
    结果是确定性的（不依赖随机），同一尺寸永远得到同一组线，便于复盘与 RTP 复核。
    """
    if rows ** reels < count:
        raise ValueError(f"{reels}x{rows} 最多只有 {rows ** reels} 条候选线，无法生成 {count} 条")

    candidates = sorted(
        product(range(rows), repeat=reels),
        key=lambda line: (count_direction_changes(line), line),
    )
    return [list(line) for line in candidates[:count]]


_REGISTRY: dict = {
    (3, 3, 5): [list(x) for x in LINES_5_3x3],
    (5, 3, 20): [list(x) for x in LINES_20_5x3],
    (5, 4, 50): generate_lines(5, 4, 50),
}


def get_lines(reels: int, rows: int, count: int) -> List[List[int]]:
    """优先返回内置经典线组，否则即时生成并缓存。"""
    key = (reels, rows, count)
    if key not in _REGISTRY:
        _REGISTRY[key] = generate_lines(reels, rows, count)
    return [list(x) for x in _REGISTRY[key]]
