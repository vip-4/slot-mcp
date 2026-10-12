"""共用 CONFIG 引擎：统一的转轮逻辑、赔率表、中奖判定与特性调度。"""

from .config import (
    BetConfig,
    CascadeConfig,
    ConfigError,
    ExpandingWildConfig,
    FreeSpinsConfig,
    Features,
    GameConfig,
    GambleConfig,
    HoldWinConfig,
    MathModel,
    Paylines,
    PayMode,
    ReelSet,
    Symbol,
    SymbolKind,
    Theme,
    set_parameter,
)
from .evaluator import WinEvent, evaluate_grid
from .features import cascade_collapse, collect_positions, count_symbols, expand_wild_reels
from .game import (
    PHASE_BASE,
    PHASE_FREE,
    PHASE_HOLD,
    GameRegistry,
    GameState,
    SlotMachine,
    SpinResult,
    SpinStep,
    get_registry,
)
from .paylines import generate_lines, get_lines
from .reels import Grid, ReelStrip, ReelStripSet
from .rng import SlotRNG
from .session import SlotSession
from .simulator import SimulationReport, simulate

__all__ = [
    "BetConfig",
    "CascadeConfig",
    "ConfigError",
    "ExpandingWildConfig",
    "FreeSpinsConfig",
    "Features",
    "GameConfig",
    "GambleConfig",
    "HoldWinConfig",
    "MathModel",
    "Paylines",
    "PayMode",
    "ReelSet",
    "Symbol",
    "SymbolKind",
    "Theme",
    "set_parameter",
    "WinEvent",
    "evaluate_grid",
    "cascade_collapse",
    "collect_positions",
    "count_symbols",
    "expand_wild_reels",
    "PHASE_BASE",
    "PHASE_FREE",
    "PHASE_HOLD",
    "GameRegistry",
    "GameState",
    "SlotMachine",
    "SpinResult",
    "SpinStep",
    "get_registry",
    "generate_lines",
    "get_lines",
    "Grid",
    "ReelStrip",
    "ReelStripSet",
    "SlotRNG",
    "SlotSession",
    "SimulationReport",
    "simulate",
]
