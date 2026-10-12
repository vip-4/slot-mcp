"""中奖判定：赔付线、全盘 Ways、Scatter 三种结算方式。

统一返回 `WinEvent`，上层（特性、会话、UI、Blender 动画）只读这一种结构，
因此新增机台不需要改动任何判定代码。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .config import GameConfig, PayMode, Symbol, SymbolKind
from .reels import Grid

__all__ = ["WinEvent", "evaluate_grid", "count_symbol", "iter_standard_symbols"]

Position = Tuple[int, int]


@dataclass
class WinEvent:
    """一次中奖事件，JSON 可直接序列化给前端 / Blender。"""

    kind: str  # line | ways | scatter | hold_win | jackpot | gamble
    symbol: str
    count: int = 0
    positions: List[Position] = field(default_factory=list)
    line_index: int = -1
    base_amount: float = 0.0
    multiplier: float = 1.0
    amount: float = 0.0
    label: str = ""

    def to_dict(self) -> Dict:
        return {
            "kind": self.kind,
            "symbol": self.symbol,
            "count": self.count,
            "positions": [list(p) for p in self.positions],
            "line_index": self.line_index,
            "base_amount": round(self.base_amount, 6),
            "multiplier": self.multiplier,
            "amount": round(self.amount, 6),
            "label": self.label,
        }

    @staticmethod
    def from_dict(d: Dict) -> "WinEvent":
        return WinEvent(
            kind=d["kind"],
            symbol=d["symbol"],
            count=int(d.get("count", 0)),
            positions=[tuple(p) for p in d.get("positions", [])],
            line_index=int(d.get("line_index", -1)),
            base_amount=float(d.get("base_amount", 0.0)),
            multiplier=float(d.get("multiplier", 1.0)),
            amount=float(d.get("amount", 0.0)),
            label=d.get("label", ""),
        )


def iter_standard_symbols(cfg: GameConfig) -> List[Symbol]:
    """参与赔付线结算的符号：标准符号与 Wild（Scatter / Bonus 只走Scatter与特性结算）。"""
    return [s for s in cfg.symbols.values() if s.kind in (SymbolKind.STANDARD, SymbolKind.WILD)]


def count_symbol(grid: Grid, symbol_id: str) -> int:
    return sum(1 for reel in grid for sym in reel if sym == symbol_id)


def _is_wild(cfg: GameConfig, symbol_id: str) -> bool:
    sym = cfg.symbols.get(symbol_id)
    return sym is not None and sym.kind == SymbolKind.WILD


def _pay_symbols(cfg: GameConfig) -> Dict[str, Symbol]:
    return {s.id: s for s in iter_standard_symbols(cfg)}


def _best_symbol_for_count(cfg: GameConfig, count: int) -> Optional[str]:
    candidates: List[Tuple[int, str]] = []
    for sym in iter_standard_symbols(cfg):
        pay = sym.pays.get(count)
        if pay:
            candidates.append((pay, sym.id))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][1]


def _wild_multiplier(cfg: GameConfig, seq: List[str]) -> float:
    mult = 1.0
    for sym_id in seq:
        sym = cfg.symbols[sym_id]
        if sym.kind == SymbolKind.WILD and sym.multiplier > 1.0:
            mult = max(mult, sym.multiplier)
    return mult


def evaluate_lines(
    cfg: GameConfig,
    grid: Grid,
    line_bet: float,
    lines: List[List[int]],
    active_lines: int,
    base_multiplier: float = 1.0,
) -> List[WinEvent]:
    """固定线结算：赔付 = pays[n] * line_bet * wild 倍率 * 全局倍率。"""
    events: List[WinEvent] = []
    pay_symbols = _pay_symbols(cfg)
    limit = len(lines) if active_lines <= 0 else min(active_lines, len(lines))

    for line_index in range(limit):
        line = lines[line_index]
        cells = [grid[reel][line[reel]] for reel in range(len(line))]
        base_symbol, count, seq = _scan_line(cfg, cells, pay_symbols)
        if not base_symbol or count < 2:
            continue

        symbol_obj = cfg.symbols[base_symbol]
        pay = symbol_obj.pays.get(count)
        if not pay:
            continue

        mult = _wild_multiplier(cfg, seq) * max(1.0, base_multiplier)
        amount = pay * line_bet * mult
        events.append(
            WinEvent(
                kind="line",
                symbol=base_symbol,
                count=count,
                positions=[(r, line[r]) for r in range(count)],
                line_index=line_index,
                base_amount=pay * line_bet,
                multiplier=mult,
                amount=amount,
                label=f"{cfg.symbols[base_symbol].name} x{count}",
            )
        )
    return events


def _scan_line(
    cfg: GameConfig, cells: List[str], pay_symbols: Dict[str, Symbol]
) -> Tuple[Optional[str], int, List[str]]:
    """返回 (结算符号, 命中长度, 参与符号序列)。

    规则：赔付必须从最左侧轴开始逐轴连续；Wild 可替代任意参与赔付的符号；
    整线全为 Wild 时按该长度下赔付最高的符号结算。
    """
    if not cells:
        return None, 0, []

    target: Optional[str] = next(
        (s for s in cells if s in pay_symbols and not _is_wild(cfg, s)), None
    )
    if target is None:
        if all(s in pay_symbols for s in cells):
            count = len(cells)
            return _best_symbol_for_count(cfg, count), count, list(cells)
        return None, 0, []

    count = 0
    seq: List[str] = []
    for sym in cells:
        if sym == target or (sym in pay_symbols and _is_wild(cfg, sym)):
            count += 1
            seq.append(sym)
        else:
            break
    if count == 0:
        return None, 0, []
    return target, count, seq


def evaluate_ways(cfg: GameConfig, grid: Grid, bet_per_way: float, base_multiplier: float = 1.0) -> List[WinEvent]:
    """全盘 Ways 结算：左起逐轴统计相邻列中出现次数，乘积即为通路数。"""
    events: List[WinEvent] = []
    pay_symbols = _pay_symbols(cfg)
    candidate_ids = [
        s.id for s in pay_symbols.values() if s.kind == SymbolKind.STANDARD and s.pays
    ]

    for symbol_id in candidate_ids:
        ways = 1
        hits: List[Position] = []
        matched_reels = 0
        for reel_idx, reel_symbols in enumerate(grid):
            positions = [
                (reel_idx, row)
                for row, sym in enumerate(reel_symbols)
                if sym == symbol_id or _is_wild(cfg, sym)
            ]
            if not positions:
                break
            ways *= len(positions)
            hits.extend(positions)
            matched_reels += 1
        if matched_reels < 2:
            continue
        pay = cfg.symbols[symbol_id].pays.get(matched_reels)
        if not pay:
            continue
        mult = max(1.0, base_multiplier)
        events.append(
            WinEvent(
                kind="ways",
                symbol=symbol_id,
                count=matched_reels,
                positions=hits,
                base_amount=pay * bet_per_way,
                multiplier=mult,
                amount=pay * bet_per_way * mult,
                label=f"{cfg.symbols[symbol_id].name} {matched_reels}连 x{ways}",
            )
        )
    return events


def evaluate_scatters(cfg: GameConfig, grid: Grid, total_bet: float, base_multiplier: float = 1.0) -> List[WinEvent]:
    """Scatter / Bonus 结算：按全盘出现个数赔付，单位为总注倍数。"""
    events: List[WinEvent] = []
    for sym_id, sym in cfg.symbols.items():
        if not sym.scatter_pays:
            continue
        positions = [
            (reel_idx, row)
            for reel_idx, reel in enumerate(grid)
            for row, s in enumerate(reel)
            if s == sym_id
        ]
        if not positions:
            continue
        pay = sym.scatter_pays.get(len(positions))
        if not pay:
            continue
        events.append(
            WinEvent(
                kind="scatter",
                symbol=sym_id,
                count=len(positions),
                positions=positions,
                base_amount=pay * total_bet,
                multiplier=max(1.0, base_multiplier),
                amount=pay * total_bet * max(1.0, base_multiplier),
                label=f"{sym.name} x{len(positions)}",
            )
        )
    return events


def evaluate_grid(
    cfg: GameConfig,
    grid: Grid,
    *,
    total_bet: float,
    line_bet: float = 0.0,
    base_multiplier: float = 1.0,
    lines: Optional[List[List[int]]] = None,
    active_lines: int = 0,
) -> List[WinEvent]:
    """统一入口：按 `pay_mode` 分派结算方式，返回所有中奖事件。"""
    events: List[WinEvent] = []
    if cfg.pay_mode == PayMode.WAYS:
        events.extend(evaluate_ways(cfg, grid, total_bet / max(1, cfg.ways()), base_multiplier))
    else:
        events.extend(
            evaluate_lines(
                cfg,
                grid,
                line_bet,
                lines or cfg.paylines.lines,
                active_lines,
                base_multiplier,
            )
        )
    events.extend(evaluate_scatters(cfg, grid, total_bet, base_multiplier))
    return events
