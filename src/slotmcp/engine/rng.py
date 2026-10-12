"""随机数发生器：可复现、线程安全，隔离业务 RNG 与系统 RNG。

* 默认使用 `random.Random`（Mersenne Twister），`seed` 固定时结果完全可复现，
  便于 MCP 工具 `slot_spin(seed=...)` 复现一次异常旋转。
* 线程隔离：模拟量大的时候每个 worker 持有独立实例，避免共享状态导致的锁竞争。
"""

from __future__ import annotations

import os
import random
import threading
from typing import Any, List, Optional, Sequence

__all__ = ["SlotRNG", "seed_from_config"]


class SlotRNG:
    """统一封装的随机数发生器。"""

    def __init__(self, seed: Optional[int | str] = None):
        self.seed_value = self._normalize(seed) if seed is not None else int.from_bytes(
            os.urandom(8), "big"
        )
        self._rng = random.Random(self.seed_value)
        self._lock = threading.Lock()

    @staticmethod
    def _normalize(seed: int | str) -> int:
        if isinstance(seed, int):
            return seed & ((1 << 64) - 1)
        # 字符串种子做稳定哈希，保证跨进程一致
        h = 0xCBF29CE484222325
        for ch in seed.encode("utf-8"):
            h ^= ch
            h = (h * 0x100000001B3) & ((1 << 64) - 1)
        return h

    # ---------------------------------------------------------------- 基本算子
    def int_below(self, n: int) -> int:
        with self._lock:
            return self._rng.randrange(n)

    def random(self) -> float:
        with self._lock:
            return self._rng.random()

    def next_float(self, low: float, high: float) -> float:
        return low + (high - low) * self.random()

    def choice(self, seq: Sequence[Any]) -> Any:
        return seq[self.int_below(len(seq))]

    def shuffle(self, items: List[Any]) -> List[Any]:
        with self._lock:
            self._rng.shuffle(items)
        return items

    def weighted_index(self, weights: Sequence[float]) -> int:
        """给定非负权重列表，返回抽样下标（线性扫描，线上配置规模下足够快）。"""
        total = float(sum(weights))
        if total <= 0:
            raise ValueError("权重之和必须为正")
        threshold = self.random() * total
        acc = 0.0
        for i, w in enumerate(weights):
            acc += float(w)
            if threshold < acc:
                return i
        return len(weights) - 1

    def snapshot(self) -> int:
        """对外暴露当前种子，便于审计日志记录。"""
        return self.seed_value


def seed_from_config(seed: Optional[int | str] = None) -> SlotRNG:
    return SlotRNG(seed)
