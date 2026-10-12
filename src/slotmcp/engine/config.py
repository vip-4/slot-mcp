"""CONFIG 引擎：七款多主题机台共用的一套配置模型。

设计要点
--------
1. **配置即数据**：任何一款 SLOT 的差异（转轮条带、赔率表、线数、特殊符号、
   免费旋转 / Hold & Win / 级联 / 扩展 Wild / 博彩）全部以 `GameConfig` 数据描述，
   引擎不含任何按 `game_id` 分支的业务代码。
2. **可序列化**：`to_dict()` / `from_dict()` 支持 JSON 双向转换，
   便于 MCP 工具的 `slot_get_config` / `slot_set_parameter` 远程读写。
3. **可校验**：`validate()` 返回结构化错误列表，配置改动在加载期即被发现，
   避免把非法配置带进运行环境。

赔付单位约定（全局统一）
---------------------
* `Symbol.pays[n]`        —— **单条线注** 的 n 倍，币值 = pays[n] * line_bet
* `Symbol.scatter_pays[n]`—— **总注** 的 n 倍，币值 = scatter_pays[n] * total_bet
* Hold & Win 符号赏金     —— **总注** 的倍数，见 `HoldWinConfig.prizes`
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "SymbolKind",
    "PayMode",
    "Symbol",
    "ReelSet",
    "Paylines",
    "BetConfig",
    "FreeSpinsConfig",
    "HoldWinConfig",
    "CascadeConfig",
    "ExpandingWildConfig",
    "GambleConfig",
    "RandomWildConfig",
    "CollectConfig",
    "Features",
    "MathModel",
    "Theme",
    "GameConfig",
    "ConfigError",
]


class SymbolKind(str, Enum):
    STANDARD = "standard"
    WILD = "wild"
    SCATTER = "scatter"
    BONUS = "bonus"
    JACKPOT = "jackpot"


class PayMode(str, Enum):
    """赔付模式：固定线 vs. 全盘 Ways（相邻即可，从左至右连轴计数）。"""

    LINES = "lines"
    WAYS = "ways"


class ConfigError(Exception):
    """配置非法时抛出，携带 `errors` 列表。"""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _as_pay_map(raw: Dict[Any, Any]) -> Dict[int, float]:
    """赔付表 key 统一还原为 int，value 允许浮点（Ways + 级联机台需要小于 1 的赔率）。"""
    return {int(k): float(v) for k, v in (raw or {}).items()}


def _as_count_map(raw: Dict[Any, Any]) -> Dict[int, int]:
    """触发表：key 为符号个数，value 为赠送次数，均为整数。"""
    return {int(k): int(v) for k, v in (raw or {}).items()}


@dataclass
class Symbol:
    id: str
    name: str = ""
    kind: SymbolKind = SymbolKind.STANDARD
    pays: Dict[int, float] = field(default_factory=dict)
    scatter_pays: Dict[int, float] = field(default_factory=dict)
    substitutes: Tuple[str, ...] = ()
    multiplier: float = 1.0
    color: str = "#8ea0ff"
    glyph: str = "?"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name or self.id,
            "kind": self.kind.value if isinstance(self.kind, SymbolKind) else str(self.kind),
            "pays": {str(k): v for k, v in self.pays.items()},
            "scatter_pays": {str(k): v for k, v in self.scatter_pays.items()},
            "substitutes": list(self.substitutes),
            "multiplier": self.multiplier,
            "color": self.color,
            "glyph": self.glyph,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Symbol":
        return Symbol(
            id=str(d["id"]),
            name=d.get("name", d["id"]),
            kind=SymbolKind(d.get("kind", SymbolKind.STANDARD.value)),
            pays=_as_pay_map(d.get("pays", {})),
            scatter_pays=_as_pay_map(d.get("scatter_pays", {})),
            substitutes=tuple(d.get("substitutes", ())),
            multiplier=float(d.get("multiplier", 1.0)),
            color=d.get("color", "#8ea0ff"),
            glyph=d.get("glyph", "?"),
        )


@dataclass
class ReelSet:
    """转轮条带集合。

    * `strips[reel]`：物理条带（从上到下循环），启动时允许停位窗口跨末端回绕。
    * `weights[reel]`：可选权重表 {symbol_id: weight}；提供时按权重展开为虚拟条带
      （虚拟映射的行业惯例），未提供时按物理条带等概率停位。
    """

    name: str = "base"
    strips: List[List[str]] = field(default_factory=list)
    weights: Optional[List[Dict[str, int]]] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"name": self.name, "strips": [list(s) for s in self.strips]}
        if self.weights:
            out["weights"] = [dict(w) for w in self.weights]
        return out

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ReelSet":
        return ReelSet(
            name=d.get("name", "base"),
            strips=[list(s) for s in d.get("strips", [])],
            weights=[dict(w) for w in d["weights"]] if d.get("weights") else None,
        )

    def expanded(self, rows: int) -> List[List[str]]:
        """返回可直接用于窗口采样的条带（已处理权重展开）。"""
        if self.weights is None:
            return [list(s) for s in self.strips]
        out: List[List[str]] = []
        for idx, strip in enumerate(self.strips):
            if idx >= len(self.weights):
                out.append(list(strip))
                continue
            weight_map = self.weights[idx]
            virtual: List[str] = []
            for sym_id in strip:
                # 权重 <= 0 表示该符号在该轴不出现（此前 max(1, ...) 会把 0 当成 1，
                # 导致「某轴禁用某符号」的配置失效——新机台的稀有币正是依赖这一点）
                weight = int(weight_map.get(sym_id, 1))
                if weight <= 0:
                    continue
                virtual.extend([sym_id] * weight)
            out.append(virtual)
        return [s if len(s) >= rows else s * (rows // max(1, len(s)) + 1) for s in out]


@dataclass
class Paylines:
    rows: int = 3
    lines: List[List[int]] = field(default_factory=list)
    active_lines: int = 0  # 0 表示启用全部

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rows": self.rows,
            "lines": [list(x) for x in self.lines],
            "active_lines": self.active_lines,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Paylines":
        return Paylines(
            rows=int(d.get("rows", 3)),
            lines=[list(x) for x in d.get("lines", [])],
            active_lines=int(d.get("active_lines", 0)),
        )


@dataclass
class BetConfig:
    steps: List[float] = field(
        default_factory=lambda: [0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]
    )
    default_index: int = 2
    max_total_bet: float = 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "steps": list(self.steps),
            "default_index": self.default_index,
            "max_total_bet": self.max_total_bet,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "BetConfig":
        return BetConfig(
            steps=[float(x) for x in d.get("steps", [0.2, 0.5, 1.0, 2.0, 5.0, 10.0])],
            default_index=int(d.get("default_index", 0)),
            max_total_bet=float(d.get("max_total_bet", 100.0)),
        )


@dataclass
class FreeSpinsConfig:
    trigger_symbol: str = "scatter"
    trigger_counts: Dict[int, int] = field(default_factory=dict)  # scatter 个数 -> 赠送次数
    multiplier_progression: List[float] = field(default_factory=lambda: [1.0])
    retrigger_counts: Dict[int, int] = field(default_factory=dict)
    sticky_wild_reels: List[int] = field(default_factory=list)
    reel_set: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_symbol": self.trigger_symbol,
            "trigger_counts": {str(k): v for k, v in self.trigger_counts.items()},
            "multiplier_progression": list(self.multiplier_progression),
            "retrigger_counts": {str(k): v for k, v in self.retrigger_counts.items()},
            "sticky_wild_reels": list(self.sticky_wild_reels),
            "reel_set": self.reel_set,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FreeSpinsConfig":
        return FreeSpinsConfig(
            trigger_symbol=d.get("trigger_symbol", "scatter"),
            trigger_counts=_as_count_map(d.get("trigger_counts", {})),
            multiplier_progression=[float(x) for x in d.get("multiplier_progression", [1.0])],
            retrigger_counts=_as_count_map(d.get("retrigger_counts", {})),
            sticky_wild_reels=list(d.get("sticky_wild_reels", [])),
            reel_set=d.get("reel_set", ""),
        )


@dataclass
class HoldWinConfig:
    """Hold & Win / Respin：触发后锁定已中符号，重置转轮重转计数。"""

    trigger_symbol: str = "bonus"
    trigger_count: int = 6
    respins: int = 3
    prize_symbols: List[str] = field(default_factory=list)
    jackpot_symbols: List[str] = field(default_factory=list)
    prizes: Dict[str, float] = field(default_factory=dict)  # symbol_id -> 总注倍数
    jackpots: Dict[str, float] = field(default_factory=dict)  # symbol_id -> 总注倍数
    award_on_each_new: bool = True
    filler_symbols: List[str] = field(default_factory=list)  # respin 期间的空注符号池
    hit_probability: float = 0.25  # 每个未锁定格子落赏金符号的概率
    full_grid_bonus: float = 0.0  # 网格全锁时的额外总注倍数奖励

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_symbol": self.trigger_symbol,
            "trigger_count": self.trigger_count,
            "respins": self.respins,
            "prize_symbols": list(self.prize_symbols),
            "jackpot_symbols": list(self.jackpot_symbols),
            "prizes": dict(self.prizes),
            "jackpots": dict(self.jackpots),
            "award_on_each_new": self.award_on_each_new,
            "filler_symbols": list(self.filler_symbols),
            "hit_probability": self.hit_probability,
            "full_grid_bonus": self.full_grid_bonus,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "HoldWinConfig":
        return HoldWinConfig(
            trigger_symbol=d.get("trigger_symbol", "bonus"),
            trigger_count=int(d.get("trigger_count", 6)),
            respins=int(d.get("respins", 3)),
            prize_symbols=list(d.get("prize_symbols", [])),
            jackpot_symbols=list(d.get("jackpot_symbols", [])),
            prizes={k: float(v) for k, v in d.get("prizes", {}).items()},
            jackpots={k: float(v) for k, v in d.get("jackpots", {}).items()},
            award_on_each_new=bool(d.get("award_on_each_new", True)),
            filler_symbols=list(d.get("filler_symbols", [])),
            hit_probability=float(d.get("hit_probability", 0.25)),
            full_grid_bonus=float(d.get("full_grid_bonus", 0.0)),
        )


@dataclass
class CascadeConfig:
    """级联（雪崩）：一次下注多次结算，倍率逐步递增。"""

    enabled: bool = False
    multiplier_step: float = 1.0
    multiplier_cap: float = 10.0
    remove_symbols: List[str] = field(default_factory=list)
    # True：每轮免费旋转开始时重置级联倍率（标准做法，RTP 更集中于基础 game）
    # False：级联倍率在整个免费旋转特性内持续累积（极端高波动）
    reset_each_free_spin: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "multiplier_step": self.multiplier_step,
            "multiplier_cap": self.multiplier_cap,
            "remove_symbols": list(self.remove_symbols),
            "reset_each_free_spin": self.reset_each_free_spin,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CascadeConfig":
        return CascadeConfig(
            enabled=bool(d.get("enabled", False)),
            multiplier_step=float(d.get("multiplier_step", 1.0)),
            multiplier_cap=float(d.get("multiplier_cap", 10.0)),
            remove_symbols=list(d.get("remove_symbols", [])),
            reset_each_free_spin=bool(d.get("reset_each_free_spin", True)),
        )


@dataclass
class ExpandingWildConfig:
    symbol: str = "wild"
    reels: List[int] = field(default_factory=list)
    respins: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "reels": list(self.reels),
            "respins": self.respins,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ExpandingWildConfig":
        return ExpandingWildConfig(
            symbol=d.get("symbol", "wild"),
            reels=list(d.get("reels", [])),
            respins=int(d.get("respins", 1)),
        )


@dataclass
class RandomWildConfig:
    """随机 Wild 投放：每次「新鲜网格」生成后按权重投放 N 个 Wild。

    热门机台（如各类 Random Wild / Wild Storm）的通用做法：
    基础 game 里低频投放、免费旋转里高频投放，用同一份配置表达。
    """

    enabled: bool = False
    symbol: str = "wild"
    # 投放个数 -> 权重（{0: 0.8, 1: 0.15, 2: 0.05} 表示 80% 不放、15% 放 1 个、5% 放 2 个）
    counts: Dict[int, float] = field(default_factory=dict)
    phases: List[str] = field(default_factory=lambda: ["base"])  # base / free_spins
    exclude_reels: List[int] = field(default_factory=list)
    # 不覆盖这些符号（Scatter / 币值 / 奖池落点应保持原样）
    protected_symbols: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "symbol": self.symbol,
            "counts": {str(k): v for k, v in self.counts.items()},
            "phases": list(self.phases),
            "exclude_reels": list(self.exclude_reels),
            "protected_symbols": list(self.protected_symbols),
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "RandomWildConfig":
        return RandomWildConfig(
            enabled=bool(d.get("enabled", False)),
            symbol=d.get("symbol", "wild"),
            counts={int(k): float(v) for k, v in (d.get("counts") or {}).items()},
            phases=list(d.get("phases", ["base"])),
            exclude_reels=list(d.get("exclude_reels", [])),
            protected_symbols=list(d.get("protected_symbols", [])),
        )


@dataclass
class CollectConfig:
    """Cash Collect（收钱）：屏上同时出现「收集者」与「币值符号」时，
    收集者把全部币值一次性收入囊中。

    币值符号的金额以**总注倍数**计（与 Hold & Win 赏金同一约定），
    `free_award_multiplier` 用于免费旋转里提高收集倍率。
    """

    enabled: bool = False
    collector: str = "collect"  # 收集者符号（通常为 Wild，同时具备替代功能）
    coin_symbols: List[str] = field(default_factory=list)  # 币值符号（kind=bonus）
    coin_values: Dict[str, float] = field(default_factory=dict)  # 符号 -> 总注倍数
    award_multiplier: float = 1.0  # 基础 game 收集倍率
    free_award_multiplier: float = 1.0  # 免费旋转收集倍率
    jackpot_symbol: str = ""  # 稀有币：同时被收集时额外派奖
    jackpot_value: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "collector": self.collector,
            "coin_symbols": list(self.coin_symbols),
            "coin_values": dict(self.coin_values),
            "award_multiplier": self.award_multiplier,
            "free_award_multiplier": self.free_award_multiplier,
            "jackpot_symbol": self.jackpot_symbol,
            "jackpot_value": self.jackpot_value,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CollectConfig":
        return CollectConfig(
            enabled=bool(d.get("enabled", False)),
            collector=d.get("collector", "collect"),
            coin_symbols=list(d.get("coin_symbols", [])),
            coin_values={k: float(v) for k, v in (d.get("coin_values") or {}).items()},
            award_multiplier=float(d.get("award_multiplier", 1.0)),
            free_award_multiplier=float(d.get("free_award_multiplier", 1.0)),
            jackpot_symbol=d.get("jackpot_symbol", ""),
            jackpot_value=float(d.get("jackpot_value", 0.0)),
        )


@dataclass
class MultiplierWildConfig:
    """倍率 Wild：参与替代的 Wild 自带倍率，对命中赔付相乘。

    * `symbols`：Wild 符号 -> 倍率（2.0 表示翻倍）
    * `combine`：同一条命中里出现多个倍率 Wild 时的合并方式
      `max`（取最大，最保守）/ `sum`（相加）/ `product`（相乘，最激进）
    * `apply_to`：生效的结算方式（line / ways），默认两者都生效
    """

    enabled: bool = False
    symbols: Dict[str, float] = field(default_factory=dict)
    combine: str = "max"
    apply_to: List[str] = field(default_factory=lambda: ["line", "ways"])

    COMBINE_MODES = ("max", "sum", "product")

    def multiplier_of(self, symbol_id: str) -> float:
        return float(self.symbols.get(symbol_id, 1.0))

    def combine_multipliers(self, values: List[float]) -> float:
        if not values:
            return 1.0
        if self.combine == "sum":
            return 1.0 + sum(max(0.0, v - 1.0) for v in values)
        if self.combine == "product":
            total = 1.0
            for v in values:
                total *= max(1.0, v)
            return total
        return max(values)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "symbols": dict(self.symbols),
            "combine": self.combine,
            "apply_to": list(self.apply_to),
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "MultiplierWildConfig":
        return MultiplierWildConfig(
            enabled=bool(d.get("enabled", False)),
            symbols={k: float(v) for k, v in (d.get("symbols") or {}).items()},
            combine=d.get("combine", "max"),
            apply_to=list(d.get("apply_to") or ["line", "ways"]),
        )


@dataclass
class PickBonusConfig:
    """Pick'em 选择式奖励：触发符号达到个数后，玩家连续挑选若干次并累计奖励。

    * `trigger_symbol` / `trigger_counts`：符号个数 -> 可挑次数
    * `prize_pool`：奖品 -> 奖励（**总注倍数**）
    * `weights`：奖品抽取权重（与 `prize_pool` 键一致）
    * `unique`：True 表示无放回（挑过的奖品不再出现）
    * `award_multiplier`：总奖励倍率（可用于免费旋转里加码）
    """

    enabled: bool = False
    trigger_symbol: str = ""
    trigger_counts: Dict[int, int] = field(default_factory=dict)
    prize_pool: Dict[str, float] = field(default_factory=dict)
    weights: Dict[str, int] = field(default_factory=dict)
    unique: bool = True
    award_multiplier: float = 1.0

    def picks_for(self, count: int) -> int:
        return int(self.trigger_counts.get(count, 0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "trigger_symbol": self.trigger_symbol,
            "trigger_counts": {int(k): int(v) for k, v in self.trigger_counts.items()},
            "prize_pool": dict(self.prize_pool),
            "weights": {k: int(v) for k, v in self.weights.items()},
            "unique": self.unique,
            "award_multiplier": self.award_multiplier,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PickBonusConfig":
        return PickBonusConfig(
            enabled=bool(d.get("enabled", False)),
            trigger_symbol=d.get("trigger_symbol", ""),
            trigger_counts={int(k): int(v) for k, v in (d.get("trigger_counts") or {}).items()},
            prize_pool={k: float(v) for k, v in (d.get("prize_pool") or {}).items()},
            weights={k: int(v) for k, v in (d.get("weights") or {}).items()},
            unique=bool(d.get("unique", True)),
            award_multiplier=float(d.get("award_multiplier", 1.0)),
        )


@dataclass
class ColossalSymbolConfig:
    """巨符号（Colossal Symbol）：每局在网格中投放一个 N×N 的巨型符号块。

    * `size_weights`：块尺寸 -> 权重（0 表示本局不投放）
    * `symbols`：可投放的符号 -> 权重（通常是高赔付的标准符号）
    * `reels`：允许的最左轴下标（块必须完整落在网格内）
    * `rows`：允许的最上排下标
    * `phases`：生效阶段（base / free_spins）
    * `protected_symbols`：不允许被覆盖的符号（Scatter / 币值等）
    """

    enabled: bool = False
    size_weights: Dict[int, int] = field(default_factory=dict)
    symbols: Dict[str, int] = field(default_factory=dict)
    reels: List[int] = field(default_factory=list)
    rows: List[int] = field(default_factory=list)
    phases: List[str] = field(default_factory=lambda: ["base"])
    protected_symbols: List[str] = field(default_factory=list)

    COMBINE_MODES = ("max", "sum", "product")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "size_weights": {int(k): int(v) for k, v in self.size_weights.items()},
            "symbols": dict(self.symbols),
            "reels": list(self.reels),
            "rows": list(self.rows),
            "phases": list(self.phases),
            "protected_symbols": list(self.protected_symbols),
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ColossalSymbolConfig":
        return ColossalSymbolConfig(
            enabled=bool(d.get("enabled", False)),
            size_weights={int(k): int(v) for k, v in (d.get("size_weights") or {}).items()},
            symbols={k: int(v) for k, v in (d.get("symbols") or {}).items()},
            reels=[int(x) for x in (d.get("reels") or [])],
            rows=[int(x) for x in (d.get("rows") or [])],
            phases=list(d.get("phases") or ["base"]),
            protected_symbols=list(d.get("protected_symbols") or []),
        )


@dataclass
class GambleConfig:
    enabled: bool = False
    max_steps: int = 5
    max_win_multiplier: float = 1000.0
    win_probability: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_steps": self.max_steps,
            "max_win_multiplier": self.max_win_multiplier,
            "win_probability": self.win_probability,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GambleConfig":
        return GambleConfig(
            enabled=bool(d.get("enabled", False)),
            max_steps=int(d.get("max_steps", 5)),
            max_win_multiplier=float(d.get("max_win_multiplier", 1000.0)),
            win_probability=float(d.get("win_probability", 0.5)),
        )


@dataclass
class Features:
    """所有机台共用同一组特性开关；未启用的特性为 None，引擎自动跳过。"""

    free_spins: Optional[FreeSpinsConfig] = None
    hold_win: Optional[HoldWinConfig] = None
    cascade: Optional[CascadeConfig] = None
    expanding_wild: Optional[ExpandingWildConfig] = None
    gamble: Optional[GambleConfig] = None
    random_wild: Optional[RandomWildConfig] = None
    collect: Optional[CollectConfig] = None
    multiplier_wild: Optional[MultiplierWildConfig] = None
    pick_bonus: Optional[PickBonusConfig] = None
    colossal: Optional[ColossalSymbolConfig] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "free_spins": self.free_spins.to_dict() if self.free_spins else None,
            "hold_win": self.hold_win.to_dict() if self.hold_win else None,
            "cascade": self.cascade.to_dict() if self.cascade else None,
            "expanding_wild": self.expanding_wild.to_dict() if self.expanding_wild else None,
            "gamble": self.gamble.to_dict() if self.gamble else None,
            "random_wild": self.random_wild.to_dict() if self.random_wild else None,
            "collect": self.collect.to_dict() if self.collect else None,
            "multiplier_wild": self.multiplier_wild.to_dict() if self.multiplier_wild else None,
            "pick_bonus": self.pick_bonus.to_dict() if self.pick_bonus else None,
            "colossal": self.colossal.to_dict() if self.colossal else None,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Features":
        return Features(
            free_spins=FreeSpinsConfig.from_dict(d["free_spins"]) if d.get("free_spins") else None,
            hold_win=HoldWinConfig.from_dict(d["hold_win"]) if d.get("hold_win") else None,
            cascade=CascadeConfig.from_dict(d["cascade"]) if d.get("cascade") else None,
            expanding_wild=ExpandingWildConfig.from_dict(d["expanding_wild"])
            if d.get("expanding_wild")
            else None,
            gamble=GambleConfig.from_dict(d["gamble"]) if d.get("gamble") else None,
            random_wild=RandomWildConfig.from_dict(d["random_wild"]) if d.get("random_wild") else None,
            collect=CollectConfig.from_dict(d["collect"]) if d.get("collect") else None,
            multiplier_wild=MultiplierWildConfig.from_dict(d["multiplier_wild"])
            if d.get("multiplier_wild")
            else None,
            pick_bonus=PickBonusConfig.from_dict(d["pick_bonus"]) if d.get("pick_bonus") else None,
            colossal=ColossalSymbolConfig.from_dict(d["colossal"]) if d.get("colossal") else None,
        )


@dataclass
class MathModel:
    target_rtp: float = 0.96
    volatility: str = "medium"
    max_win_multiplier: float = 5000.0
    hit_frequency_target: float = 0.25
    rtp_tolerance: float = 0.02

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_rtp": self.target_rtp,
            "volatility": self.volatility,
            "max_win_multiplier": self.max_win_multiplier,
            "hit_frequency_target": self.hit_frequency_target,
            "rtp_tolerance": self.rtp_tolerance,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "MathModel":
        return MathModel(
            target_rtp=float(d.get("target_rtp", 0.96)),
            volatility=str(d.get("volatility", "medium")),
            max_win_multiplier=float(d.get("max_win_multiplier", 5000.0)),
            hit_frequency_target=float(d.get("hit_frequency_target", 0.25)),
            rtp_tolerance=float(d.get("rtp_tolerance", 0.02)),
        )


@dataclass
class Theme:
    id: str = "default"
    name: str = ""
    palette: Dict[str, str] = field(default_factory=dict)
    cabinet_color: str = "#20143a"
    background: str = "#0b0714"
    accent: str = "#ffcc33"
    music: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "palette": dict(self.palette),
            "cabinet_color": self.cabinet_color,
            "background": self.background,
            "accent": self.accent,
            "music": self.music,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Theme":
        return Theme(
            id=d.get("id", "default"),
            name=d.get("name", ""),
            palette=dict(d.get("palette", {})),
            cabinet_color=d.get("cabinet_color", "#20143a"),
            background=d.get("background", "#0b0714"),
            accent=d.get("accent", "#ffcc33"),
            music=d.get("music", ""),
        )


@dataclass
class GameConfig:
    """一款完整的 SLOT 机台配置。新增机台 = 新增一份 GameConfig，无需改引擎。"""

    id: str = ""
    name: str = ""
    description: str = ""
    provider: str = "Blender Slot MCP"
    version: str = "1.0.0"
    reels: int = 5
    rows: int = 3
    pay_mode: PayMode = PayMode.LINES
    symbols: Dict[str, Symbol] = field(default_factory=dict)
    reel_sets: Dict[str, ReelSet] = field(default_factory=dict)
    base_reel_set: str = "base"
    paylines: Paylines = field(default_factory=Paylines)
    bet: BetConfig = field(default_factory=BetConfig)
    features: Features = field(default_factory=Features)
    math: MathModel = field(default_factory=MathModel)
    theme: Theme = field(default_factory=Theme)

    # ---------------------------------------------------------------- 序列化
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "provider": self.provider,
            "version": self.version,
            "reels": self.reels,
            "rows": self.rows,
            "pay_mode": self.pay_mode.value if isinstance(self.pay_mode, PayMode) else str(self.pay_mode),
            "symbols": {k: v.to_dict() for k, v in self.symbols.items()},
            "reel_sets": {k: v.to_dict() for k, v in self.reel_sets.items()},
            "base_reel_set": self.base_reel_set,
            "paylines": self.paylines.to_dict(),
            "bet": self.bet.to_dict(),
            "features": self.features.to_dict(),
            "math": self.math.to_dict(),
            "theme": self.theme.to_dict(),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GameConfig":
        cfg = GameConfig(
            id=str(d.get("id", "")),
            name=d.get("name", d.get("id", "")),
            description=d.get("description", ""),
            provider=d.get("provider", "Blender Slot MCP"),
            version=str(d.get("version", "1.0.0")),
            reels=int(d.get("reels", 5)),
            rows=int(d.get("rows", 3)),
            pay_mode=PayMode(d.get("pay_mode", PayMode.LINES.value)),
            symbols={k: Symbol.from_dict(v) for k, v in d.get("symbols", {}).items()},
            reel_sets={k: ReelSet.from_dict(v) for k, v in d.get("reel_sets", {}).items()},
            base_reel_set=d.get("base_reel_set", "base"),
            paylines=Paylines.from_dict(d["paylines"]) if d.get("paylines") else Paylines(),
            bet=BetConfig.from_dict(d["bet"]) if d.get("bet") else BetConfig(),
            features=Features.from_dict(d["features"]) if d.get("features") else Features(),
            math=MathModel.from_dict(d["math"]) if d.get("math") else MathModel(),
            theme=Theme.from_dict(d["theme"]) if d.get("theme") else Theme(),
        )
        return cfg

    @staticmethod
    def from_json(text: str) -> "GameConfig":
        return GameConfig.from_dict(json.loads(text))

    @staticmethod
    def from_file(path: str | Path) -> "GameConfig":
        return GameConfig.from_json(Path(path).read_text(encoding="utf-8"))

    def clone(self) -> "GameConfig":
        return copy.deepcopy(self)

    # ---------------------------------------------------------------- 取值辅助
    def reel_set(self, name: str = "") -> ReelSet:
        key = name or self.base_reel_set
        if key not in self.reel_sets:
            raise KeyError(f"[{self.id}] 未定义的条带集合: {key}")
        return self.reel_sets[key]

    def symbol(self, symbol_id: str) -> Symbol:
        if symbol_id not in self.symbols:
            raise KeyError(f"[{self.id}] 未定义的符号: {symbol_id}")
        return self.symbols[symbol_id]

    def wild_ids(self) -> Tuple[str, ...]:
        return tuple(s.id for s in self.symbols.values() if s.kind == SymbolKind.WILD)

    def standard_ids(self) -> Tuple[str, ...]:
        return tuple(s.id for s in self.symbols.values() if s.kind == SymbolKind.STANDARD)

    def ways(self) -> int:
        """Ways 模式下的总通路数量。"""
        return self.rows ** self.reels

    # ---------------------------------------------------------------- 校验
    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.id:
            errors.append("缺少必填字段: id")
        if self.reels <= 0 or self.rows <= 0:
            errors.append(f"转轮/行数必须为正整数: reels={self.reels}, rows={self.rows}")
        if not self.symbols:
            errors.append("symbols 不能为空")
        if not self.reel_sets:
            errors.append("reel_sets 不能为空")
        if self.base_reel_set not in self.reel_sets:
            errors.append(f"base_reel_set={self.base_reel_set} 不存在于 reel_sets")

        for rs_name, rs in self.reel_sets.items():
            if len(rs.strips) != self.reels:
                errors.append(f"条带集合 {rs_name}: 转轮数 {len(rs.strips)} != reels {self.reels}")
            for i, strip in enumerate(rs.strips):
                if len(strip) < self.rows:
                    errors.append(f"条带集合 {rs_name} 第 {i} 轴长度 {len(strip)} < rows {self.rows}")
                for sym in strip:
                    if sym not in self.symbols:
                        errors.append(f"条带集合 {rs_name} 第 {i} 轴引用未定义符号: {sym}")
            if rs.weights and len(rs.weights) != len(rs.strips):
                errors.append(f"条带集合 {rs_name}: weights 长度与 strips 不一致")

        for sid, sym in self.symbols.items():
            if sym.kind in (SymbolKind.STANDARD, SymbolKind.WILD):
                for cnt, mult in sym.pays.items():
                    if mult <= 0:
                        errors.append(f"符号 {sid}: pays[{cnt}] 必须为正数")
            for target in sym.substitutes:
                if target not in self.symbols:
                    errors.append(f"符号 {sid}: substitutes 引用未定义符号 {target}")
            if sym.kind != SymbolKind.WILD and sym.substitutes:
                errors.append(f"符号 {sid}: 只有 WILD 允许配置 substitutes")

        if self.pay_mode == PayMode.LINES:
            if not self.paylines.lines:
                errors.append("PayMode.LINES 模式下必须提供 paylines.lines")
            for i, line in enumerate(self.paylines.lines):
                if len(line) != self.reels:
                    errors.append(f"第 {i} 条赔付线长度 {len(line)} != reels {self.reels}")
                for r in line:
                    if not (0 <= r < self.rows):
                        errors.append(f"第 {i} 条赔付线行号 {r} 越界 (rows={self.rows})")
            if len(set(map(tuple, self.paylines.lines))) != len(self.paylines.lines):
                errors.append("赔付线集合存在重复定义")
        else:
            if self.paylines.rows != self.rows:
                errors.append("PayMode.WAYS 模式下 paylines.rows 必须等于 rows")

        if not self.bet.steps:
            errors.append("bet.steps 不能为空")
        if any(x <= 0 for x in self.bet.steps):
            errors.append("bet.steps 中必须全部为正数")
        if not (0 <= self.bet.default_index < len(self.bet.steps)):
            errors.append("bet.default_index 越界")

        cascade = self.features.cascade
        if cascade and cascade.enabled:
            if cascade.multiplier_step <= 0:
                errors.append(f"cascade.multiplier_step 必须为正: {cascade.multiplier_step}")
            if cascade.multiplier_cap < cascade.multiplier_step:
                errors.append("cascade.multiplier_cap 必须不小于 multiplier_step")

        gamble = self.features.gamble
        if gamble and gamble.enabled:
            if not 0 < gamble.win_probability <= 1:
                errors.append(f"gamble.win_probability 越界: {gamble.win_probability}")
            if gamble.max_steps < 0:
                errors.append(f"gamble.max_steps 不能为负: {gamble.max_steps}")

        fs = self.features.free_spins
        if fs:
            if fs.trigger_symbol not in self.symbols:
                errors.append(f"free_spins.trigger_symbol 未定义: {fs.trigger_symbol}")
            if not fs.trigger_counts:
                errors.append("free_spins.trigger_counts 不能为空")
            for count, spins in fs.trigger_counts.items():
                if spins <= 0:
                    errors.append(f"free_spins.trigger_counts[{count}] 必须为正: {spins}")
            for count, spins in fs.retrigger_counts.items():
                if spins <= 0:
                    errors.append(f"free_spins.retrigger_counts[{count}] 必须为正: {spins}")
            if not fs.multiplier_progression:
                errors.append("free_spins.multiplier_progression 不能为空")
            if any(x < 0 for x in fs.multiplier_progression):
                errors.append("free_spins.multiplier_progression 不能含负数")
            if fs.reel_set and fs.reel_set not in self.reel_sets:
                errors.append(f"free_spins.reel_set 不存在: {fs.reel_set}")
            for r in fs.sticky_wild_reels:
                if not (0 <= r < self.reels):
                    errors.append(f"free_spins.sticky_wild_reels 越界: {r}")

        hw = self.features.hold_win
        if hw:
            for sym_id in [hw.trigger_symbol, *hw.prize_symbols, *hw.jackpot_symbols]:
                if sym_id not in self.symbols:
                    errors.append(f"hold_win 引用未定义符号: {sym_id}")
            if hw.trigger_count <= 0 or hw.trigger_count > self.reels * self.rows:
                errors.append(f"hold_win.trigger_count 越界: {hw.trigger_count}")
            if hw.respins <= 0:
                errors.append(f"hold_win.respins 必须为正: {hw.respins}")
            if not 0 <= hw.hit_probability <= 1:
                errors.append(f"hold_win.hit_probability 越界: {hw.hit_probability}")
            if any(v < 0 for v in [*hw.prizes.values(), *hw.jackpots.values()]):
                errors.append("hold_win.prizes / jackpots 不能含负数")
            if not hw.prize_symbols:
                errors.append("hold_win.prize_symbols 不能为空")

        rw = self.features.random_wild
        if rw and rw.enabled:
            if rw.symbol not in self.symbols:
                errors.append(f"random_wild.symbol 未定义: {rw.symbol}")
            if not rw.counts:
                errors.append("random_wild.counts 不能为空")
            if any(w < 0 for w in rw.counts.values()):
                errors.append("random_wild.counts 权重不能为负")
            if any(c < 0 or c > self.reels * self.rows for c in rw.counts):
                errors.append("random_wild.counts 个数越界")
            # 用字面量而非 game.PHASE_*，避免 config -> game 的循环依赖
            for phase in rw.phases:
                if phase not in ("base", "free_spins"):
                    errors.append(f"random_wild.phases 非法阶段: {phase}（可选 base / free_spins）")
            for r in rw.exclude_reels:
                if not (0 <= r < self.reels):
                    errors.append(f"random_wild.exclude_reels 越界: {r}")

        col = self.features.collect
        if col and col.enabled:
            if col.collector not in self.symbols:
                errors.append(f"collect.collector 未定义: {col.collector}")
            if not col.coin_symbols:
                errors.append("collect.coin_symbols 不能为空")
            for sym_id in col.coin_symbols:
                if sym_id not in self.symbols:
                    errors.append(f"collect 引用未定义符号: {sym_id}")
                if sym_id not in col.coin_values:
                    errors.append(f"collect.coin_values 缺少 {sym_id} 的面值")
            if any(v < 0 for v in col.coin_values.values()):
                errors.append("collect.coin_values 不能含负数")
            if col.award_multiplier <= 0 or col.free_award_multiplier <= 0:
                errors.append("collect 倍率必须为正")
            if col.jackpot_symbol and col.jackpot_symbol not in self.symbols:
                errors.append(f"collect.jackpot_symbol 未定义: {col.jackpot_symbol}")

        mw = self.features.multiplier_wild
        if mw and mw.enabled:
            if not mw.symbols:
                errors.append("multiplier_wild.symbols 不能为空")
            for sym_id, value in mw.symbols.items():
                sym = self.symbols.get(sym_id)
                if sym is None:
                    errors.append(f"multiplier_wild 引用未定义符号: {sym_id}")
                elif sym.kind != SymbolKind.WILD:
                    errors.append(f"multiplier_wild 只能作用于 Wild: {sym_id}")
                if value < 1.0:
                    errors.append(f"multiplier_wild 倍率不能小于 1: {sym_id}={value}")
            if mw.combine not in MultiplierWildConfig.COMBINE_MODES:
                errors.append(f"multiplier_wild.combine 非法: {mw.combine}")
            for mode in mw.apply_to:
                if mode not in ("line", "ways"):
                    errors.append(f"multiplier_wild.apply_to 非法: {mode}")

        pb = self.features.pick_bonus
        if pb and pb.enabled:
            if pb.trigger_symbol not in self.symbols:
                errors.append(f"pick_bonus.trigger_symbol 未定义: {pb.trigger_symbol}")
            if not pb.trigger_counts:
                errors.append("pick_bonus.trigger_counts 不能为空")
            if any(v <= 0 for v in pb.trigger_counts.values()):
                errors.append("pick_bonus 可挑次数必须为正")
            if not pb.prize_pool:
                errors.append("pick_bonus.prize_pool 不能为空")
            if any(v < 0 for v in pb.prize_pool.values()):
                errors.append("pick_bonus 奖品不能为负")
            for prize in pb.prize_pool:
                if prize not in pb.weights or pb.weights[prize] <= 0:
                    errors.append(f"pick_bonus.weights 缺少或非法: {prize}")
            if pb.trigger_counts and pb.unique:
                max_picks = max(pb.trigger_counts.values())
                if max_picks > len(pb.prize_pool):
                    errors.append("pick_bonus 无放回时可挑次数不能超过奖品数")
            if pb.award_multiplier <= 0:
                errors.append("pick_bonus.award_multiplier 必须为正")

        cs = self.features.colossal
        if cs and cs.enabled:
            if not cs.size_weights:
                errors.append("colossal.size_weights 不能为空")
            for size in cs.size_weights:
                # 尺寸 0 表示「本局不投放」（与 random_wild.counts 的 0 同义）
                if int(size) == 0:
                    continue
                if int(size) < 2:
                    errors.append(f"colossal 块尺寸至少为 2: {size}")
                elif int(size) > min(self.reels, self.rows):
                    errors.append(
                        f"colossal 块尺寸 {size} 超过网格范围（{self.reels}x{self.rows}）"
                    )
            if not cs.symbols:
                errors.append("colossal.symbols 不能为空")
            for sym_id in cs.symbols:
                if sym_id not in self.symbols:
                    errors.append(f"colossal 引用未定义符号: {sym_id}")
                elif self.symbols[sym_id].kind not in (SymbolKind.STANDARD, SymbolKind.WILD):
                    errors.append(f"colossal 只能投放标准符号或 Wild: {sym_id}")
            if not cs.reels:
                errors.append("colossal.reels 不能为空")
            if not cs.rows:
                errors.append("colossal.rows 不能为空")
            if cs.reels and (min(cs.reels) < 0 or max(cs.reels) >= self.reels):
                errors.append("colossal.reels 超出轴范围")
            if cs.rows and (min(cs.rows) < 0 or max(cs.rows) >= self.rows):
                errors.append("colossal.rows 超出排范围")
            for phase in cs.phases or []:
                if phase not in ("base", "free_spins", "hold_win"):
                    errors.append(f"colossal.phases 非法: {phase}")

        ew = self.features.expanding_wild
        if ew:
            if ew.symbol not in self.symbols:
                errors.append(f"expanding_wild.symbol 未定义: {ew.symbol}")
            if ew.respins < 0:
                errors.append(f"expanding_wild.respins 不能为负: {ew.respins}")
            for r in ew.reels:
                if not (0 <= r < self.reels):
                    errors.append(f"expanding_wild.reels 越界: {r}")

        if not (0.5 <= self.math.target_rtp <= 1.05):
            errors.append(f"target_rtp 超出合理区间: {self.math.target_rtp}")

        return errors

    def assert_valid(self) -> "GameConfig":
        errs = self.validate()
        if errs:
            raise ConfigError(errs)
        return self


def set_parameter(cfg: GameConfig, path: str, value: Any) -> GameConfig:
    """按点号路径热更新配置，例如 `features.free_spins.trigger_counts.3`。

    供 MCP 工具 `slot_set_parameter` 与运营后台使用；路径不存在时抛出 KeyError。
    字典 key 会尝试按 int 还原（赔付表涣偿数量等），失败则保留字符串。
    """
    parts = [p for p in path.split(".") if p]
    if not parts:
        raise KeyError("配置路径为空")
    node: Any = cfg
    for part in parts[:-1]:
        if isinstance(node, dict):
            node = node[part]
        elif isinstance(node, list) and part.isdigit():
            node = node[int(part)]
        elif hasattr(node, part):
            node = getattr(node, part)
        else:
            raise KeyError(f"无效的配置路径: {path}")

    last = parts[-1]
    if isinstance(node, dict):
        key: Any = int(last) if last.isdigit() else last
        node[key] = value
    elif isinstance(node, list) and last.isdigit():
        idx = int(last)
        if idx >= len(node):
            raise IndexError(f"列表下标越界: {path}")
        node[idx] = value
    else:
        if not hasattr(node, last):
            raise KeyError(f"无效的配置路径: {path}")
        setattr(node, last, value)
    return cfg
