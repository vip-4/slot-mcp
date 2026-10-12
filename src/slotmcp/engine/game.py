"""统一入口：状态机主循环 + 机台注册表。

* `SlotMachine.spin()` 是唯一的对局入口，任何机台都通过「配置 + 本文件」运行，
  引擎内不存在按机台 id 的分支逻辑。
* 一次 `spin()` 会把级联、重转、免费旋转、Hold & Win 等过程全部跑完，
  以 `steps` 有序返回，前端与 Blender 侧按 steps 顺序播放动画即可。
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .config import ConfigError, GameConfig, PayMode
from .evaluator import WinEvent, count_symbol, evaluate_grid
from .features import (
    cascade_collapse,
    collect_coins,
    collect_positions,
    count_symbols,
    keys_to_positions,
    place_colossal_symbol,
    place_random_wilds,
    resolve_pick_bonus,
    apply_symbol_upgrade,
    reveal_mystery_symbols,
    sync_reels,
    walk_wilds,
)
from .reels import Grid, ReelStripSet
from .rng import SlotRNG

__all__ = [
    "PHASE_BASE",
    "PHASE_FREE",
    "PHASE_HOLD",
    "GameState",
    "SpinStep",
    "SpinResult",
    "BetContext",
    "SlotMachine",
    "GameRegistry",
    "get_registry",
]

PHASE_BASE = "base"
PHASE_FREE = "free_spins"
PHASE_HOLD = "hold_win"

# 单局硬上限，防止配置异常（或极端运气）时出现不可收敛的循环
MAX_TURNS_PER_SPIN = 300
MAX_STEPS_PER_SPIN = 400
MAX_CASCADES_PER_SPIN = 40
# 单次下注最多可派发的免费旋转总数（行业惯例：防止无限再触发）
MAX_FREE_SPINS_PER_PURCHASE = 200


@dataclass
class GameState:
    """跨 spin 的对局状态（免费旋转余额、粘性 Wild、Hold & Win 进度等）。

    完全可 JSON 序列化，便于会话持久化与分布式恢复。
    """

    phase: str = PHASE_BASE
    free_spins_left: int = 0
    free_spins_played: int = 0
    free_spins_total: int = 0
    purchase_free_spins: int = 0  # 本次下注已派发的免费旋转数，用于上限控制
    fs_multiplier: float = 1.0
    cascade_multiplier: float = 1.0
    sticky_keys: Dict[str, str] = field(default_factory=dict)  # "reel,row" -> symbol_id
    walking_wilds: List[List[int]] = field(default_factory=list)  # 行走 Wild 落点 [[reel,row], ...]
    respins_left: int = 0
    hold_grid: Optional[Grid] = None
    hold_locked_keys: List[str] = field(default_factory=list)
    hold_return_phase: str = PHASE_BASE  # Hold & Win 结束后回到的阶段
    hold_initial_awarded: bool = False
    hold_pot: float = 0.0  # 累计赏金，单位：总注倍数
    total_win: float = 0.0
    spin_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "free_spins_left": self.free_spins_left,
            "free_spins_played": self.free_spins_played,
            "free_spins_total": self.free_spins_total,
            "purchase_free_spins": self.purchase_free_spins,
            "fs_multiplier": self.fs_multiplier,
            "cascade_multiplier": self.cascade_multiplier,
            "sticky_keys": dict(self.sticky_keys),
            "walking_wilds": [list(p) for p in self.walking_wilds],
            "respins_left": self.respins_left,
            "hold_grid": copy.deepcopy(self.hold_grid),
            "hold_locked_keys": list(self.hold_locked_keys),
            "hold_return_phase": self.hold_return_phase,
            "hold_initial_awarded": self.hold_initial_awarded,
            "hold_pot": round(self.hold_pot, 6),
            "total_win": round(self.total_win, 6),
            "spin_count": self.spin_count,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GameState":
        return GameState(
            phase=d.get("phase", PHASE_BASE),
            free_spins_left=int(d.get("free_spins_left", 0)),
            free_spins_played=int(d.get("free_spins_played", 0)),
            free_spins_total=int(d.get("free_spins_total", 0)),
            purchase_free_spins=int(d.get("purchase_free_spins", 0)),
            fs_multiplier=float(d.get("fs_multiplier", 1.0)),
            cascade_multiplier=float(d.get("cascade_multiplier", 1.0)),
            sticky_keys=dict(d.get("sticky_keys", {})),
            walking_wilds=[list(p) for p in d.get("walking_wilds", [])],
            respins_left=int(d.get("respins_left", 0)),
            hold_grid=copy.deepcopy(d.get("hold_grid")),
            hold_locked_keys=list(d.get("hold_locked_keys", [])),
            hold_return_phase=d.get("hold_return_phase", PHASE_BASE),
            hold_initial_awarded=bool(d.get("hold_initial_awarded", False)),
            hold_pot=float(d.get("hold_pot", 0.0)),
            total_win=float(d.get("total_win", 0.0)),
            spin_count=int(d.get("spin_count", 0)),
        )

    def clone(self) -> "GameState":
        return GameState.from_dict(self.to_dict())

    @property
    def awaiting_feature(self) -> bool:
        return self.phase != PHASE_BASE


@dataclass
class BetContext:
    total_bet: float
    line_bet: float
    active_lines: int
    lines: List[List[int]]


@dataclass
class SpinStep:
    """一次网格结算（基础旋转、级联、重转、免费旋转、Hold & Win 各占一步）。"""

    index: int
    phase: str
    grid: Grid
    stops: List[int]
    wins: List[WinEvent]
    step_win: float
    multiplier: float = 1.0
    free_spin_remaining: int = 0
    is_fresh: bool = True  # True = 该轮的新鲜网格；False = 级联/重转/Hold&Win 派生网格
    events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "phase": self.phase,
            "is_fresh": self.is_fresh,
            "grid": [list(col) for col in self.grid],
            "stops": list(self.stops),
            "wins": [w.to_dict() for w in self.wins],
            "step_win": round(self.step_win, 6),
            "multiplier": self.multiplier,
            "free_spin_remaining": self.free_spin_remaining,
            "events": list(self.events),
        }


@dataclass
class SpinResult:
    spin_id: str
    game_id: str
    total_bet: float
    line_bet: float
    active_lines: int
    steps: List[SpinStep]
    total_win: float
    state: GameState
    events: List[Dict[str, Any]]
    seed: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spin_id": self.spin_id,
            "game_id": self.game_id,
            "total_bet": round(self.total_bet, 6),
            "line_bet": round(self.line_bet, 6),
            "active_lines": self.active_lines,
            "steps": [s.to_dict() for s in self.steps],
            "total_win": round(self.total_win, 6),
            "state": self.state.to_dict(),
            "events": list(self.events),
            "seed": self.seed,
        }

    @property
    def first_grid(self) -> Grid:
        return self.steps[0].grid if self.steps else []

    @property
    def net_result(self) -> float:
        return self.total_win - self.total_bet


class SlotMachine:
    """一台具体的 SLOT 机台：配置 + RNG + 主循环。"""

    def __init__(self, config: GameConfig, rng: Optional[SlotRNG] = None):
        errors = config.validate()
        if errors:
            raise ConfigError(errors)
        self.config = config
        self.rng = rng or SlotRNG()
        self._strip_sets: Dict[str, ReelStripSet] = {
            name: ReelStripSet(rs, config.rows, name) for name, rs in config.reel_sets.items()
        }

    # ------------------------------------------------------------------ 元信息
    @property
    def info(self) -> Dict[str, Any]:
        cfg = self.config
        return {
            "id": cfg.id,
            "name": cfg.name,
            "description": cfg.description,
            "reels": cfg.reels,
            "rows": cfg.rows,
            "pay_mode": cfg.pay_mode.value,
            "lines": len(cfg.paylines.lines) if cfg.pay_mode == PayMode.LINES else cfg.ways(),
            "target_rtp": cfg.math.target_rtp,
            "volatility": cfg.math.volatility,
            "max_win_multiplier": cfg.math.max_win_multiplier,
            "features": [k for k, v in cfg.features.to_dict().items() if v],
            "bet_steps": cfg.bet.steps,
            "theme": cfg.theme.to_dict(),
            "symbols": {k: v.to_dict() for k, v in cfg.symbols.items()},
        }

    def payline_layout(self) -> List[List[int]]:
        return [list(x) for x in self.config.paylines.lines]

    # ------------------------------------------------------------------ 下注上下文
    def build_context(self, total_bet: float, active_lines: int = 0) -> BetContext:
        cfg = self.config
        if total_bet <= 0:
            raise ValueError("total_bet 必须为正数")
        if cfg.pay_mode == PayMode.LINES:
            lines = cfg.paylines.lines
            n = len(lines) if active_lines <= 0 else min(active_lines, len(lines))
            return BetContext(
                total_bet=float(total_bet),
                line_bet=float(total_bet) / n,
                active_lines=n,
                lines=lines,
            )
        return BetContext(
            total_bet=float(total_bet), line_bet=0.0, active_lines=0, lines=[]
        )

    # ------------------------------------------------------------------ 主入口
    def spin(
        self,
        *,
        total_bet: float,
        active_lines: int = 0,
        state: Optional[GameState] = None,
    ) -> SpinResult:
        cfg = self.config
        ctx = self.build_context(total_bet, active_lines)
        st = state.clone() if state else GameState()
        st.total_win = 0.0
        st.spin_count += 1

        steps: List[SpinStep] = []
        events: List[Dict[str, Any]] = []
        turns = 0
        st.purchase_free_spins = 0

        while turns < MAX_TURNS_PER_SPIN and len(steps) < MAX_STEPS_PER_SPIN:
            turns += 1
            produced = self._run_turn(st, ctx)
            if not produced:
                break
            steps.extend(produced)
            self._apply_triggers(st, produced, events)
            if st.phase == PHASE_BASE:
                break

        total_win = sum(s.step_win for s in steps)
        return SpinResult(
            spin_id=uuid.uuid4().hex[:12],
            game_id=cfg.id,
            total_bet=ctx.total_bet,
            line_bet=ctx.line_bet,
            active_lines=ctx.active_lines,
            steps=steps,
            total_win=round(total_win, 6),
            state=st,
            events=events,
            seed=self.rng.snapshot(),
        )

    # ------------------------------------------------------------------ 单轮
    def _run_turn(self, st: GameState, ctx: BetContext) -> List[SpinStep]:
        if st.phase == PHASE_HOLD:
            return self._run_hold_win(st, ctx)
        return self._run_spin(st, ctx)

    def _current_strip_set(self, st: GameState) -> ReelStripSet:
        name = self.config.base_reel_set
        if st.phase == PHASE_FREE:
            fs = self.config.features.free_spins
            if fs and fs.reel_set:
                name = fs.reel_set
        return self._strip_sets[name]

    def _roll(self, st: GameState, strip_set: ReelStripSet) -> tuple:
        grid, stops = strip_set.spin(self.rng)
        if st.sticky_keys:
            for key, sym in st.sticky_keys.items():
                reel_str, _, row_str = key.partition(",")
                grid[int(reel_str)][int(row_str)] = sym
        return grid, stops

    def _run_spin(self, st: GameState, ctx: BetContext) -> List[SpinStep]:
        cfg = self.config
        steps: List[SpinStep] = []
        step_events: List[Dict[str, Any]] = []

        if st.phase == PHASE_FREE:
            fs = cfg.features.free_spins
            st.free_spins_left -= 1
            st.free_spins_played += 1
            if cfg.features.cascade and cfg.features.cascade.reset_each_free_spin:
                st.cascade_multiplier = 1.0
            if fs:
                prog = fs.multiplier_progression or [1.0]
                st.fs_multiplier = prog[min(st.free_spins_played - 1, len(prog) - 1)]
            strip_set = self._current_strip_set(st)
        else:
            st.phase = PHASE_BASE
            st.cascade_multiplier = 1.0
            st.fs_multiplier = 1.0
            strip_set = self._current_strip_set(st)

        grid, stops = self._roll(st, strip_set)

        # 同步轴：紧跟采样之后，保证后面所有算子都在「已同步」的网格上工作
        sr = cfg.features.sync_reels
        if sr and sr.enabled:
            synced = sync_reels(grid, sr, self.rng, st.phase)
            if synced:
                step_events.append(synced)

        # 巨符号：在其它网格改写算子之前投放，保证后续 Wild/触发判定看到的是最终网格
        cs = cfg.features.colossal
        if cs and cs.enabled:
            block = place_colossal_symbol(grid, cfg, cs, self.rng, st.phase)
            if block:
                step_events.append(block)

        # 神秘符号揭示：在巨符号之后、随机 Wild 之前，保证后续判定看到最终网格
        ms = cfg.features.mystery
        if ms and ms.enabled:
            revealed = reveal_mystery_symbols(grid, ms, self.rng, st.phase)
            if revealed:
                step_events.append(revealed)

        # 行走 Wild：先移动已有的（写回网格），再登记本局新落下的（下一局开始走）
        wwc = cfg.features.walking_wild
        if wwc and wwc.enabled and st.phase in (wwc.phases or [PHASE_FREE]):
            st.walking_wilds, walked = walk_wilds(grid, wwc, st.walking_wilds, st.phase)
            if walked:
                step_events.append(walked)
        elif wwc and wwc.enabled:
            st.walking_wilds = []

        # 随机 Wild 投放：必须在「替代计算之前、触发判定之前」完成，
        # 这样它既能参与线赔，也能影响 Scatter/币值的可见性（但不会覆盖受保护符号）。
        rw = cfg.features.random_wild
        if rw and rw.enabled and st.phase in (rw.phases or [PHASE_BASE]):
            placed = self._place_random_wilds(grid, rw)
            if placed:
                step_events.append(
                    {
                        "type": "random_wild",
                        "symbol": rw.symbol,
                        "count": len(placed),
                        "positions": [[r, c] for r, c in placed],
                    }
                )

        ew = cfg.features.expanding_wild
        if ew and st.phase == PHASE_BASE:
            target_reels = ew.reels or list(range(cfg.reels))
            expanded = _expand_wild(grid, ew.symbol, target_reels)
            if expanded:
                for reel_idx, row in expanded:
                    st.sticky_keys[f"{reel_idx},{row}"] = ew.symbol
                st.respins_left = max(0, ew.respins)
                step_events.append(
                    {
                        "type": "expanding_wild",
                        "symbol": ew.symbol,
                        "reels": sorted({r for r, _ in expanded}),
                        "respins": st.respins_left,
                        "positions": [[r, c] for r, c in expanded],
                    }
                )

        if st.phase == PHASE_FREE:
            fs = cfg.features.free_spins
            if fs and fs.sticky_wild_reels:
                wild_ids = cfg.wild_ids()
                for reel_idx in fs.sticky_wild_reels:
                    for row, sym in enumerate(grid[reel_idx]):
                        if sym in wild_ids:
                            st.sticky_keys[f"{reel_idx},{row}"] = sym

        label = "免费旋转" if st.phase == PHASE_FREE else "基础旋转"
        self._settle(st, ctx, grid, stops, steps, extra_events=step_events if not steps else None)

        while st.respins_left > 0 and len(steps) < MAX_STEPS_PER_SPIN:
            st.respins_left -= 1
            grid, stops = self._roll(st, strip_set)
            self._settle(
                st,
                ctx,
                grid,
                stops,
                steps,
                extra_events=[{"type": "respin", "remaining": st.respins_left}],
            )

        # 扩展 Wild 的锁轴只在本次特性内有效：重转用尽后必须解锁，
        # 否则 sticky_keys 会跨 spin 累积，导致后续每一局都带着上一次的粘性 Wild。
        if st.phase == PHASE_BASE and st.respins_left <= 0:
            st.sticky_keys = {}

        if st.phase == PHASE_FREE:
            for step in steps:
                step.free_spin_remaining = st.free_spins_left
        return steps

    def _place_random_wilds(self, grid: Grid, rw) -> List[tuple]:
        """按权重抽样投放个数，再随机落点。"""
        keys = sorted(int(k) for k in rw.counts)
        weights = [float(rw.counts[k]) for k in keys]
        total = sum(weights)
        if total <= 0:
            return []
        target = self.rng.random() * total
        chosen = keys[-1]
        acc = 0.0
        for key, weight in zip(keys, weights):
            acc += weight
            if target < acc:
                chosen = key
                break
        return place_random_wilds(
            grid,
            rw.symbol,
            chosen,
            self.rng,
            exclude_reels=rw.exclude_reels,
            protected_symbols=rw.protected_symbols,
        )

    def _collect_award(
        self, cfg, st: GameState, ctx: BetContext, grid: Grid
    ) -> Optional[WinEvent]:
        """Cash Collect：收集者 + 币值符号同时出现时，一次性收入全部币值。"""
        col = cfg.features.collect
        if not col or not col.enabled:
            return None
        if not any(col.collector in column for column in grid):
            return None
        coins = collect_coins(grid, col.coin_symbols)
        if not coins:
            return None
        multiplier = col.free_award_multiplier if st.phase == PHASE_FREE else col.award_multiplier
        pot = sum(col.coin_values.get(grid[r][c], 0.0) for r, c in coins)
        has_jackpot = bool(col.jackpot_symbol) and any(
            col.jackpot_symbol == grid[r][c] for r, c in coins
        )
        if has_jackpot:
            pot += col.jackpot_value
        if pot <= 0:
            return None
        amount = pot * multiplier * ctx.total_bet
        return WinEvent(
            kind="collect",
            symbol=col.collector,
            count=len(coins),
            positions=coins,
            base_amount=round(pot * ctx.total_bet, 6),
            amount=round(amount, 6),
            label=f"收集 {len(coins)} 枚金币 ×{multiplier:g}",
        )

    def _pick_bonus_award(
        self, cfg, ctx: BetContext, grid: Grid
    ) -> Optional[Tuple[WinEvent, List[str]]]:
        """Pick'em：触发符号达到个数后连续挑选奖品并累计奖励（总注倍数）。"""
        pb = cfg.features.pick_bonus
        if not pb or not pb.enabled:
            return None
        count = sum(1 for column in grid for sym in column if sym == pb.trigger_symbol)
        picks = pb.picks_for(count)
        if picks <= 0:
            return None
        chosen, total = resolve_pick_bonus(cfg, pb, picks, self.rng)
        if total <= 0:
            return None
        amount = round(total * ctx.total_bet, 6)
        return (
            WinEvent(
                kind="pick_bonus",
                symbol=pb.trigger_symbol,
                count=len(chosen),
                positions=[],
                base_amount=amount,
                amount=amount,
                label=f"选宝 {len(chosen)} 次：{' / '.join(chosen)}",
            ),
            chosen,
        )

    def _settle(
        self,
        st: GameState,
        ctx: BetContext,
        grid: Grid,
        stops: Sequence[int],
        steps: List[SpinStep],
        extra_events: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """对一次网格做结算，并按配置继续级联，直到无新中奖为止。"""
        cfg = self.config
        strip_set = self._current_strip_set(st)
        cascade = cfg.features.cascade
        guard = 0
        upgraded_cells: set = set()  # 本局已升级过的格子（once_per_cell 的边界）

        while True:
            multiplier = st.fs_multiplier * st.cascade_multiplier
            wins = evaluate_grid(
                cfg,
                grid,
                total_bet=ctx.total_bet,
                line_bet=ctx.line_bet,
                base_multiplier=multiplier,
                lines=ctx.lines,
                active_lines=ctx.active_lines,
            )
            events: List[Dict[str, Any]] = list(extra_events or []) if guard == 0 else []
            # Cash Collect / Pick'em 只对「新鲜网格」结算：
            # 级联派生网格会让同一枚币或同一次选择奖励被重复派发
            if guard == 0:
                award = self._collect_award(cfg, st, ctx, grid)
                if award is not None:
                    wins.append(award)
                    events.append(
                        {
                            "type": "collect",
                            "collector": cfg.features.collect.collector,
                            "coins": len(award.positions),
                            "amount": award.amount,
                        }
                    )
                pick = self._pick_bonus_award(cfg, ctx, grid)
                if pick is not None:
                    wins.append(pick[0])
                    events.append(
                        {
                            "type": "pick_bonus",
                            "picks": pick[1],
                            "award": pick[0].amount,
                        }
                    )
            step_win = round(sum(w.amount for w in wins), 6)
            steps.append(
                SpinStep(
                    index=len(steps),
                    phase=st.phase,
                    grid=copy.deepcopy(grid),
                    stops=list(stops),
                    wins=wins,
                    step_win=step_win,
                    multiplier=multiplier,
                    free_spin_remaining=st.free_spins_left,
                    is_fresh=(guard == 0),
                    events=events,
                )
            )

            if not cascade or not cascade.enabled or step_win <= 0:
                break
            positions = sorted({p for w in wins if w.kind in ("line", "ways") for p in w.positions})
            if not positions:
                break
            guard += 1
            if guard >= MAX_CASCADES_PER_SPIN:
                break
            st.cascade_multiplier = min(
                cascade.multiplier_cap, st.cascade_multiplier + cascade.multiplier_step
            )

            # 符号升级：命中的符号升一档并保留在屏上，其余格才消除补位
            remaining = list(positions)
            su = cfg.features.symbol_upgrade
            if su and su.enabled and st.phase in (su.phases or [PHASE_BASE, PHASE_FREE]):
                upgraded = apply_symbol_upgrade(grid, su, positions, st.phase, upgraded_cells)
                if upgraded:
                    steps[-1].events.append(upgraded)
                    keep = {tuple(p) for p in upgraded["positions"]}
                    remaining = [p for p in positions if tuple(p) not in keep]
            if remaining:
                grid = cascade_collapse(grid, strip_set, remaining, self.rng)
                stops = [-1] * len(grid)

    # ------------------------------------------------------------------ 触发器
    def _apply_triggers(
        self, st: GameState, steps: List[SpinStep], events: List[Dict[str, Any]]
    ) -> None:
        cfg = self.config

        if st.phase == PHASE_FREE:
            self._maybe_retrigger(st, [s for s in steps if s.phase == PHASE_FREE], events)
            if st.free_spins_left <= 0:
                self._leave_free_spins(st, events)
            return

        if st.phase == PHASE_HOLD:
            return

        fs = cfg.features.free_spins
        hw = cfg.features.hold_win
        # 只有「本轮新鲜网格」可以做一次触发判定：
        # 1) Hold & Win 结束后网格必然堆满赏金符号，允许其自身再次触发会无限套娃；
        # 2) 级联步骤若参与 Scatter 计数，会让触发频率随级联链长度线性膨胀，
        #    使 `trigger_counts` 失去可调性（实测可达 5 倍偏差）。
        steps = [s for s in steps if s.phase == PHASE_BASE and s.is_fresh]
        if not steps:
            return

        if fs:
            best_count = 0
            awarded = 0
            for step in steps:
                cnt = count_symbol(step.grid, fs.trigger_symbol)
                if cnt > best_count:
                    best_count = cnt
            for trigger_count in sorted(fs.trigger_counts, reverse=True):
                if best_count >= trigger_count:
                    awarded = fs.trigger_counts[trigger_count]
                    break
            if awarded:
                granted = max(
                    0, min(awarded, MAX_FREE_SPINS_PER_PURCHASE - st.purchase_free_spins)
                )
                if granted == 0:
                    events.append(
                        {"type": "free_spins_cap_reached", "requested": awarded, "count": best_count}
                    )
                    return
                st.phase = PHASE_FREE
                st.free_spins_left += granted
                st.free_spins_total += granted
                st.purchase_free_spins += granted
                st.sticky_keys = {}
                st.walking_wilds = []
                events.append(
                    {
                        "type": "free_spins_trigger",
                        "symbol": fs.trigger_symbol,
                        "count": best_count,
                        "spins": granted,
                    }
                )
                return

        if hw:
            candidate_ids = [hw.trigger_symbol, *hw.prize_symbols, *hw.jackpot_symbols]
            best = 0
            source_grid = steps[0].grid
            for step in steps:
                cnt = count_symbols(step.grid, candidate_ids)
                if cnt > best:
                    best = cnt
                    source_grid = step.grid
            if best >= hw.trigger_count:
                self._enter_hold_win(st, source_grid, events)

    def _maybe_retrigger(
        self, st: GameState, steps: List[SpinStep], events: List[Dict[str, Any]]
    ) -> None:
        """再触发判定：只针对「新开一轮」网格，级联步骤不参与，且每轮至多一次。"""
        fs = self.config.features.free_spins
        if not fs or not fs.retrigger_counts:
            return
        for step in steps:
            if not step.is_fresh:
                continue
            cnt = count_symbol(step.grid, fs.trigger_symbol)
            extra = fs.retrigger_counts.get(cnt)
            if not extra:
                return
            granted = max(0, min(extra, MAX_FREE_SPINS_PER_PURCHASE - st.purchase_free_spins))
            if granted == 0:
                events.append({"type": "free_spins_cap_reached", "requested": extra, "count": cnt})
                return
            st.free_spins_left += granted
            st.free_spins_total += granted
            st.purchase_free_spins += granted
            events.append({"type": "free_spins_retrigger", "count": cnt, "spins": granted})
            return

    def _leave_free_spins(self, st: GameState, events: List[Dict[str, Any]]) -> None:
        st.phase = PHASE_BASE
        st.sticky_keys = {}
        st.walking_wilds = []
        st.fs_multiplier = 1.0
        st.cascade_multiplier = 1.0
        events.append(
            {
                "type": "free_spins_end",
                "played": st.free_spins_played,
                "remaining": 0,
            }
        )
        st.free_spins_played = 0

    # ------------------------------------------------------------------ Hold & Win
    def _enter_hold_win(self, st: GameState, grid: Grid, events: List[Dict[str, Any]]) -> None:
        hw = self.config.features.hold_win
        if not hw:
            return
        candidate_ids = [hw.trigger_symbol, *hw.prize_symbols, *hw.jackpot_symbols]
        locked = collect_positions(grid, candidate_ids)
        st.hold_return_phase = st.phase if st.phase == PHASE_FREE else PHASE_BASE
        st.phase = PHASE_HOLD
        st.hold_grid = copy.deepcopy(grid)
        st.hold_locked_keys = [f"{r},{c}" for r, c in locked]
        st.hold_pot = 0.0
        st.hold_initial_awarded = False
        st.respins_left = hw.respins
        events.append(
            {
                "type": "hold_win_trigger",
                "locked": len(locked),
                "respins": hw.respins,
                "positions": [[r, c] for r, c in locked],
            }
        )

    def _run_hold_win(self, st: GameState, ctx: BetContext) -> List[SpinStep]:
        hw = self.config.features.hold_win
        if not hw or st.hold_grid is None:
            st.phase = PHASE_BASE
            return []

        grid: Grid = copy.deepcopy(st.hold_grid)
        strip_set = self._strip_sets[self.config.base_reel_set]
        steps: List[SpinStep] = []
        locked = keys_to_positions(st.hold_locked_keys)
        pool = hw.prize_symbols or [hw.trigger_symbol]
        fillers = hw.filler_symbols or [s for s in self.config.standard_ids()] or [pool[0]]
        locked_at_start = list(locked)
        guard = 0
        guard_limit = min(MAX_STEPS_PER_SPIN, 120)

        while guard < guard_limit:
            guard += 1
            prize_names = {hw.trigger_symbol, *hw.prize_symbols, *hw.jackpot_symbols}
            for reel_idx, column in enumerate(grid):
                for row in range(len(column)):
                    if (reel_idx, row) in locked:
                        continue
                    if self.rng.random() < hw.hit_probability:
                        column[row] = pool[self.rng.int_below(len(pool))]
                    else:
                        column[row] = fillers[self.rng.int_below(len(fillers))]

            locked_now = set(locked)
            newly: List[tuple] = []
            for pos, sym in sorted(
                ((p, grid[p[0]][p[1]]) for p in collect_positions(grid, list(prize_names)))
            ):
                if pos in locked_now:
                    continue
                newly.append(pos)
                locked_now.add(pos)
                value = hw.prizes.get(sym, 0.0) or hw.jackpots.get(sym, 0.0)
                st.hold_pot += value

            locked = sorted(locked_now)
            st.hold_locked_keys = [f"{r},{c}" for r, c in locked]
            st.hold_grid = copy.deepcopy(grid)
            st.respins_left -= 1

            wins: List[WinEvent] = []
            step_win = 0.0

            # 第一轮把进入特性时已锁定的符号一并结算，避免初始锁定被漏付
            initial: List[tuple] = []
            if guard == 1 and not st.hold_initial_awarded:
                initial = locked_at_start
                st.hold_initial_awarded = True
                for pos in initial:
                    sym = grid[pos[0]][pos[1]]
                    st.hold_pot += hw.prizes.get(sym, 0.0) or hw.jackpots.get(sym, 0.0)
            for pos in [*initial, *newly]:
                sym = grid[pos[0]][pos[1]]
                is_jackpot = sym in hw.jackpot_symbols
                value = (hw.jackpots if is_jackpot else hw.prizes).get(sym, 0.0)
                if sym not in self.config.symbols:
                    continue
                amount = value * ctx.total_bet
                wins.append(
                    WinEvent(
                        kind="jackpot" if is_jackpot else "hold_win",
                        symbol=sym,
                        count=1,
                        positions=[pos],
                        base_amount=amount,
                        amount=amount,
                        label=f"{self.config.symbols[sym].name}",
                    )
                )
                step_win += amount

            events: List[Dict[str, Any]] = [
                {
                    "type": "hold_win_respin",
                    "new_locked": len(newly),
                    "remaining": max(0, st.respins_left),
                    "pot": round(st.hold_pot, 4),
                }
            ]
            if newly:
                st.respins_left = hw.respins

            steps.append(
                SpinStep(
                    index=len(steps),
                    phase=PHASE_HOLD,
                    grid=copy.deepcopy(grid),
                    stops=[-1] * len(grid),
                    wins=wins,
                    step_win=round(step_win, 6),
                    multiplier=1.0,
                    is_fresh=False,
                    events=events,
                )
            )

            total_cells = len(grid) * len(grid[0])
            if st.respins_left <= 0 or len(locked) >= total_cells:
                break

        # 结算：pot 已在逐步过程中发放；额外发放全屏奖励
        total_cells = len(grid) * len(grid[0])
        if hw.full_grid_bonus > 0 and len(locked) >= total_cells:
            bonus = hw.full_grid_bonus * ctx.total_bet
            steps[-1].wins.append(
                WinEvent(
                    kind="jackpot",
                    symbol="full_grid",
                    count=total_cells,
                    base_amount=bonus,
                    amount=bonus,
                    label="全屏大奖",
                )
            )
            steps[-1].step_win = round(steps[-1].step_win + bonus, 6)
            steps[-1].events.append({"type": "full_grid_bonus", "amount": round(bonus, 4)})

        st.phase = st.hold_return_phase or PHASE_BASE
        st.hold_return_phase = PHASE_BASE
        st.hold_grid = None
        st.hold_locked_keys = []
        st.hold_pot = 0.0
        st.respins_left = 0
        return steps


def _expand_wild(grid: Grid, symbol_id: str, target_reels: Sequence[int]) -> List[tuple]:
    expanded: List[tuple] = []
    targets = set(int(r) for r in target_reels)
    for reel_idx, column in enumerate(grid):
        if reel_idx not in targets or symbol_id not in column:
            continue
        for row in range(len(column)):
            column[row] = symbol_id
            expanded.append((reel_idx, row))
    return expanded


class GameRegistry:
    """机台注册表：MCP 工具层与 Web 层统一通过它拿到 `SlotMachine`。"""

    def __init__(self) -> None:
        self._machines: Dict[str, SlotMachine] = {}

    def register(self, config: GameConfig, *, replace: bool = False) -> SlotMachine:
        if config.id in self._machines and not replace:
            raise ValueError(f"机台已注册: {config.id}")
        machine = SlotMachine(config)
        self._machines[config.id] = machine
        return machine

    def register_file(self, path: str, *, replace: bool = False) -> SlotMachine:
        return self.register(GameConfig.from_file(path), replace=replace)

    def get(self, game_id: str) -> SlotMachine:
        if game_id not in self._machines:
            known = ", ".join(sorted(self._machines))
            raise KeyError(f"未注册的机台: {game_id}（可用: {known or '无'}）")
        return self._machines[game_id]

    def ids(self) -> List[str]:
        return sorted(self._machines)

    def list_info(self) -> List[Dict[str, Any]]:
        return [self._machines[i].info for i in self.ids()]

    def all_machines(self) -> Dict[str, SlotMachine]:
        return dict(self._machines)

    def spin(
        self,
        game_id: str,
        *,
        total_bet: float,
        active_lines: int = 0,
        state: Optional[GameState] = None,
    ) -> SpinResult:
        return self.get(game_id).spin(total_bet=total_bet, active_lines=active_lines, state=state)


_REGISTRY: Optional[GameRegistry] = None


def get_registry(reload: bool = False) -> GameRegistry:
    """默认注册表单例：懒加载内置 6 款机台。"""
    global _REGISTRY
    if _REGISTRY is None or reload:
        registry = GameRegistry()
        from ..games import iter_game_configs  # 延迟导入，避免循环依赖

        for cfg in iter_game_configs():
            registry.register(cfg, replace=True)
        _REGISTRY = registry
    return _REGISTRY
