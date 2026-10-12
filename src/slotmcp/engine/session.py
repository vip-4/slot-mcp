"""玩家会话：余额、下注档位、博彩（Gamble）与历史记录。

会话只做「钱包 + 状态机驱动」两件事，所有数学结果都来自 `SlotMachine.spin()`，
因此 RTP 核算与实际对局共用同一份代码路径。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import GameConfig
from .game import GameState, SlotMachine, SpinResult
from .rng import SlotRNG

__all__ = ["SlotSession", "SessionSnapshot"]


@dataclass
class SessionSnapshot:
    session_id: str
    game_id: str
    credits: float
    bet_index: int
    last_result: Optional[SpinResult]
    history: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "game_id": self.game_id,
            "credits": round(self.credits, 4),
            "bet_index": self.bet_index,
            "last_result": self.last_result.to_dict() if self.last_result else None,
            "history": list(self.history),
        }


class SlotSession:
    """一个玩家在一台机台上的会话。"""

    def __init__(
        self,
        machine: SlotMachine,
        session_id: str = "default",
        credits: float = 1000.0,
        bet_index: Optional[int] = None,
        rng: Optional[SlotRNG] = None,
        history_size: int = 50,
    ):
        self.machine = machine
        self.session_id = session_id
        self.credits = float(credits)
        self.state = GameState()
        self.rng = rng
        self.history_size = history_size
        self._history: List[Dict[str, Any]] = []
        self._gamble_stake: float = 0.0
        self._gamble_steps: int = 0
        self.pending_gamble: bool = False
        cfg: GameConfig = machine.config
        self.bet_index = bet_index if bet_index is not None else cfg.bet.default_index
        self.bet_index = max(0, min(self.bet_index, len(cfg.bet.steps) - 1))

    # ------------------------------------------------------------------ 下注
    @property
    def bet_levels(self) -> List[float]:
        return list(self.machine.config.bet.steps)

    @property
    def current_bet(self) -> float:
        return self.bet_levels[self.bet_index]

    def set_bet_index(self, index: int) -> float:
        if not (0 <= index < len(self.bet_levels)):
            raise IndexError(f"下注档位越界: {index}")
        self.bet_index = index
        return self.current_bet

    def step_bet(self, delta: int) -> float:
        return self.set_bet_index(
            max(0, min(self.bet_index + delta, len(self.bet_levels) - 1))
        )

    # ------------------------------------------------------------------ 旋转
    def can_spin(self) -> bool:
        return self.credits >= self.current_bet and not self.pending_gamble

    def spin(self, active_lines: int = 0) -> SpinResult:
        if self.pending_gamble:
            raise RuntimeError("存在未结算的博彩，请先调用 take_gamble / gamble")
        bet = self.current_bet
        if self.credits < bet:
            raise RuntimeError(f"余额不足: credits={self.credits}, bet={bet}")
        self.credits -= bet
        result = self.machine.spin(
            total_bet=bet, active_lines=active_lines, state=self.state
        )
        self.state = result.state
        self.credits += result.total_win
        self._record(result)

        gamble_cfg = self.machine.config.features.gamble
        if gamble_cfg and gamble_cfg.enabled and result.total_win > 0:
            self._gamble_stake = result.total_win
            self._gamble_steps = 0
            self.pending_gamble = True
        return result

    def _record(self, result: SpinResult) -> None:
        self._history.append(
            {
                "spin_id": result.spin_id,
                "bet": result.total_bet,
                "win": result.total_win,
                "steps": len(result.steps),
                "events": [e["type"] for e in result.events],
            }
        )
        if len(self._history) > self.history_size:
            self._history = self._history[-self.history_size :]

    # ------------------------------------------------------------------ 博彩
    def gamble(self, choice: str) -> Dict[str, Any]:
        """半/双倍 guessing 游戏：choice 取 `red|black`。赢则奖金翻倍并可继续。"""
        cfg = self.machine.config.features.gamble
        if not (cfg and cfg.enabled):
            raise RuntimeError("该机台未启用博彩特性")
        if not self.pending_gamble:
            raise RuntimeError("当前无可博彩金额")
        if choice not in ("red", "black"):
            raise ValueError("choice 只能是 red / black")

        rng = self.rng or self.machine.rng
        cap = cfg.max_win_multiplier * self.current_bet
        self._gamble_steps += 1
        win = rng.random() < cfg.win_probability
        if win:
            doubled = self._gamble_stake * 2
            if doubled > cap:
                doubled = cap
            self._gamble_stake = doubled
            reached_cap = self._gamble_steps >= cfg.max_steps or doubled >= cap
            if reached_cap:
                return self._finish_gamble(self._gamble_stake, collected=True)
            return {
                "win": True,
                "stake": round(self._gamble_stake, 4),
                "step": self._gamble_steps,
                "max_steps": cfg.max_steps,
                "finished": False,
                "credits": round(self.credits, 4),
            }
        return self._finish_gamble(0.0, collected=False)

    def take_gamble(self) -> Dict[str, Any]:
        """收下当前博彩奖金，结束博彩流程。"""
        if not self.pending_gamble:
            raise RuntimeError("当前无可博彩金额")
        return self._finish_gamble(self._gamble_stake, collected=True)

    def _finish_gamble(self, amount: float, collected: bool) -> Dict[str, Any]:
        self.credits += amount
        self.pending_gamble = False
        stake = self._gamble_stake
        self._gamble_stake = 0.0
        self._gamble_steps = 0
        return {
            "win": collected,
            "stake": round(stake, 4),
            "credits": round(self.credits, 4),
            "finished": True,
            "collected": round(amount, 4),
        }

    # ------------------------------------------------------------------ 快照
    def snapshot(self, last_result: Optional[SpinResult] = None) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=self.session_id,
            game_id=self.machine.config.id,
            credits=self.credits,
            bet_index=self.bet_index,
            last_result=last_result,
            history=list(self._history),
        )

    def to_dict(self, last_result: Optional[SpinResult] = None) -> Dict[str, Any]:
        snapshot = self.snapshot(last_result).to_dict()
        snapshot.update(
            {
                "bet": self.current_bet,
                "bet_levels": self.bet_levels,
                "state": self.state.to_dict(),
                "pending_gamble": self.pending_gamble,
                "gamble_stake": round(self._gamble_stake, 4),
            }
        )
        return snapshot

    def restore_state(self, state: Dict[str, Any]) -> None:
        if state:
            self.state = GameState.from_dict(state)

    @property
    def history(self) -> List[Dict[str, Any]]:
        return list(self._history)
