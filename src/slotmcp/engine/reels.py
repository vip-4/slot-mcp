"""转轮：物理条带 / 虚拟映射条带、停位与窗口采样。

坐标约定：`grid[reel][row]`，`row = 0` 为顶部。
"""

from __future__ import annotations

from typing import List, Tuple

from .config import ReelSet
from .rng import SlotRNG

__all__ = ["Grid", "ReelStrip", "ReelStripSet"]

Grid = List[List[str]]


class ReelStrip:
    """单轴循环条带。"""

    def __init__(self, symbols: List[str], index: int = 0, name: str = ""):
        if not symbols:
            raise ValueError(f"第 {index} 轴条带为空")
        self.symbols = list(symbols)
        self.index = index
        self.name = name
        self.length = len(symbols)

    def random_stop(self, rng: SlotRNG) -> int:
        """等概率停位（物理条带）。"""
        return rng.int_below(self.length)

    def window(self, stop: int, rows: int) -> List[str]:
        """以 `stop` 作为窗口顶行，向下卷绕取 `rows` 个符号。"""
        return [self.symbols[(stop + r) % self.length] for r in range(rows)]


class ReelStripSet:
    """一组轴组成的转轮集合，负责产出完整网格。"""

    def __init__(self, reel_set: ReelSet, rows: int, name: str = ""):
        self.name = reel_set.name or name
        expanded = reel_set.expanded(rows)
        if reel_set.weights is not None:
            # 权重展开后的虚拟条带会成簇，这里做确定性洗牌：
            # 同一种子永远产出同一条带，既保留调优便利性，又保证 RTP 可复算。
            for idx, symbols in enumerate(expanded):
                SlotRNG(f"{self.name}#{idx}").shuffle(symbols)
        self.rows = rows
        self.strips: List[ReelStrip] = [
            ReelStrip(symbols, index=i, name=self.name) for i, symbols in enumerate(expanded)
        ]

    @property
    def reel_count(self) -> int:
        return len(self.strips)

    @property
    def total_positions(self) -> int:
        total = 1
        for strip in self.strips:
            total *= strip.length
        return total

    def spin(self, rng: SlotRNG) -> Tuple[Grid, List[int]]:
        """返回 (grid, stops)，grid 为 `[reel][row]` 二维列表。"""
        stops = [strip.random_stop(rng) for strip in self.strips]
        grid = [strip.window(stops[i], self.rows) for i, strip in enumerate(self.strips)]
        return grid, stops
