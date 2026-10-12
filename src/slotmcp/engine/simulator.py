"""RTP / 波动率模拟器（蒙特卡洛）。

与线上对局共用 `SlotMachine.spin()`，因此仿真的 RTP 与实际发放的期望值一致，
可在 CI 中作为回归门槛使用（见 `tools/verify_rtp.py`）。
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .game import PHASE_BASE, PHASE_FREE, PHASE_HOLD, SlotMachine
from .rng import SlotRNG

__all__ = ["SimulationReport", "simulate"]


@dataclass
class SimulationReport:
    game_id: str
    spins: int
    bet: float
    total_bet: float
    total_win: float
    rtp: float
    base_rtp: float
    feature_rtp: float
    hit_rate: float
    volatility: float
    max_win: float
    max_win_multiplier: float
    target_rtp: float
    within_tolerance: bool
    feature_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "game_id": self.game_id,
            "spins": self.spins,
            "bet": self.bet,
            "total_bet": round(self.total_bet, 4),
            "total_win": round(self.total_win, 4),
            "rtp": round(self.rtp, 6),
            "base_rtp": round(self.base_rtp, 6),
            "feature_rtp": round(self.feature_rtp, 6),
            "hit_rate": round(self.hit_rate, 6),
            "volatility": round(self.volatility, 4),
            "max_win": round(self.max_win, 4),
            "max_win_multiplier": round(self.max_win_multiplier, 2),
            "target_rtp": self.target_rtp,
            "within_tolerance": self.within_tolerance,
            "feature_stats": self.feature_stats,
        }

    @property
    def verdict(self) -> str:
        if self.within_tolerance:
            return "PASS"
        delta = self.rtp - self.target_rtp
        return f"FAIL (偏差 {delta:+.4f})"


def simulate(
    machine: SlotMachine,
    spins: int = 100_000,
    bet: float = 1.0,
    seed: Optional[int | str] = 20240604,
    active_lines: int = 0,
    progress_callback=None,
) -> SimulationReport:
    """对一台机台做 N 次旋转的蒙特卡洛仿真。

    `spins` 指付费旋转次数；免费旋转 / 级联 / 重转包含在同一次 purchase 内，
    不额外计费，因此 RTP 可超过 100% 的误解不会出现。
    """
    if spins <= 0:
        raise ValueError("spins 必须为正整数")

    machine.rng = SlotRNG(seed)
    wins: List[float] = []
    total_win = 0.0
    base_win = 0.0
    feature_win = 0.0
    hits = 0
    max_win = 0.0
    feature_counts: Dict[str, int] = {}
    feature_wins: Dict[str, float] = {}

    for i in range(spins):
        result = machine.spin(total_bet=bet, active_lines=active_lines)
        win = result.total_win
        total_win += win
        wins.append(win)
        if win > 0:
            hits += 1
        if win > max_win:
            max_win = win

        base_step_win = 0.0
        feature_step_win = 0.0
        for step in result.steps:
            if step.phase == PHASE_BASE:
                base_step_win += step.step_win
            else:
                feature_step_win += step.step_win
        base_win += base_step_win
        feature_win += feature_step_win

        for event in result.events:
            etype = event["type"]
            feature_counts[etype] = feature_counts.get(etype, 0) + 1

        if result.state.phase == PHASE_BASE and any(
            s.phase == PHASE_FREE for s in result.steps
        ):
            for s in result.steps:
                if s.phase == PHASE_FREE:
                    feature_wins["free_spins"] = feature_wins.get("free_spins", 0.0) + s.step_win
        if any(s.phase == PHASE_HOLD for s in result.steps):
            feature_wins["hold_win"] = feature_wins.get("hold_win", 0.0) + sum(
                s.step_win for s in result.steps if s.phase == PHASE_HOLD
            )

        if progress_callback and (i + 1) % 10_000 == 0:
            progress_callback(i + 1, spins)

    total_bet = float(spins * bet)
    rtp = total_win / total_bet if total_bet else 0.0
    target = machine.config.math.target_rtp
    tolerance = machine.config.math.rtp_tolerance

    volatility = statistics.pstdev(wins) / bet if bet > 0 else 0.0
    feature_stats: Dict[str, Dict[str, float]] = {}
    for etype, count in feature_counts.items():
        stats: Dict[str, float] = {
            "count": float(count),
            "frequency": count / spins,
            "one_in": spins / count if count else float("inf"),
        }
        if etype in feature_wins:
            stats["rtp_contribution"] = feature_wins[etype] / total_bet
        feature_stats[etype] = stats

    return SimulationReport(
        game_id=machine.config.id,
        spins=spins,
        bet=bet,
        total_bet=total_bet,
        total_win=total_win,
        rtp=rtp,
        base_rtp=base_win / total_bet if total_bet else 0.0,
        feature_rtp=feature_win / total_bet if total_bet else 0.0,
        hit_rate=hits / spins,
        volatility=volatility,
        max_win=max_win,
        max_win_multiplier=max_win / bet if bet else 0.0,
        target_rtp=target,
        within_tolerance=math.isclose(rtp, target, abs_tol=tolerance),
        feature_stats=feature_stats,
    )
