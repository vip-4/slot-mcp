"""机台 10：冰原狼踪 —— 5x4 / 50 线，高波动，行走 Wild（跨局状态算子）+ 免费旋转。

核心机制（全部由 CONFIG 描述，引擎无分支）
---------------------------------------------
* **赔付模式**：固定 50 线（`generate_lines(5, 4, 50)`），线注 = 总注 / 50
* **行走 Wild**（`walking_wild`）：免费旋转里落下的「冰狼 Wild」会**每局向左移动一列**，
  移出网格或撞到 Scatter 才消失；多个行走 Wild 可同时在场（上限 6 个）
* **免费旋转**（`free_spins`）：极光 Scatter 3/4/5 枚 → 8/12/16 次，倍率递进 [1,2,3]，
  可再触发（3/4/5 → 4/6/8 次）；免费条带里 Wild 更密，保证「行走」有源
* **目标**：RTP 96.5% / 高波动 / 最大约 800x

调参入口：`slot_set_parameter`，例如
`features.walking_wild.steps_per_spin`、`features.walking_wild.protected_symbols`。
"""

from __future__ import annotations

from ..engine.config import (
    BetConfig,
    CascadeConfig,
    Features,
    FreeSpinsConfig,
    GameConfig,
    MathModel,
    Paylines,
    ReelSet,
    Symbol,
    SymbolKind,
    Theme,
    WalkingWildConfig,
)
from ..engine.paylines import generate_lines

GAME_ID = "frost_wolf"

_STANDARD_IDS = ["axe", "shield", "horn", "ship", "rune", "flake"]

_SYMBOLS = {
    "axe": Symbol("axe", "战斧", SymbolKind.STANDARD, pays={3: 1.55, 4: 7.2, 5: 24.37}, color="#9fb4c7", glyph="🪓"),
    "shield": Symbol("shield", "盾牌", SymbolKind.STANDARD, pays={3: 1.99, 4: 8.86, 5: 29.91}, color="#8ad7ff", glyph="🛡️"),
    "horn": Symbol("horn", "号角", SymbolKind.STANDARD, pays={3: 2.54, 4: 11.08, 5: 37.66}, color="#c9a227", glyph="📯"),
    "ship": Symbol("ship", "长船", SymbolKind.STANDARD, pays={3: 3.1, 4: 14.4, 5: 48.73}, color="#b08968", glyph="⛵"),
    "rune": Symbol("rune", "卢恩石", SymbolKind.STANDARD, pays={3: 3.99, 4: 17.72, 5: 60.92}, color="#c6a4ff", glyph="🔯"),
    "flake": Symbol("flake", "雪晶", SymbolKind.STANDARD, pays={3: 5.54, 4: 21.04, 5: 75.32}, color="#e8f4ff", glyph="❄️"),
    "wolf": Symbol(
        "wolf",
        "冰狼 Wild（行走）",
        SymbolKind.WILD,
        pays={3: 6.65, 4: 24.37, 5: 99.68},
        substitutes=tuple(_STANDARD_IDS),
        color="#a8e8ff",
        glyph="🐺",
    ),
    "scatter": Symbol(
        "scatter", "极光 Scatter", SymbolKind.SCATTER, scatter_pays={3: 1.11, 4: 3.32, 5: 11.08}, color="#7cf6c8", glyph="🌌"
    ),
}

_ORDER = [*_STANDARD_IDS, "wolf", "scatter"]

_BASE_WEIGHTS = [
    {"axe": 22, "shield": 19, "horn": 18, "ship": 14, "rune": 11, "flake": 9, "wolf": 5, "scatter": 3},
    {"axe": 22, "shield": 19, "horn": 18, "ship": 14, "rune": 11, "flake": 10, "wolf": 5, "scatter": 3},
    {"axe": 22, "shield": 19, "horn": 18, "ship": 14, "rune": 12, "flake": 10, "wolf": 6, "scatter": 3},
    {"axe": 22, "shield": 19, "horn": 18, "ship": 15, "rune": 12, "flake": 10, "wolf": 5, "scatter": 3},
    {"axe": 22, "shield": 19, "horn": 18, "ship": 14, "rune": 11, "flake": 9, "wolf": 5, "scatter": 3},
]
# 免费旋转：Wild 更密（保证行走 Wild 有源），高价值符号权重同步上调
_FS_WEIGHTS = [
    {"axe": 19, "shield": 18, "horn": 18, "ship": 16, "rune": 13, "flake": 11, "wolf": 9, "scatter": 3},
    {"axe": 19, "shield": 18, "horn": 18, "ship": 16, "rune": 13, "flake": 12, "wolf": 9, "scatter": 3},
    {"axe": 19, "shield": 18, "horn": 18, "ship": 16, "rune": 14, "flake": 12, "wolf": 10, "scatter": 3},
    {"axe": 19, "shield": 18, "horn": 18, "ship": 17, "rune": 14, "flake": 12, "wolf": 9, "scatter": 3},
    {"axe": 19, "shield": 18, "horn": 18, "ship": 16, "rune": 13, "flake": 11, "wolf": 9, "scatter": 3},
]


def build_config() -> GameConfig:
    return GameConfig(
        id=GAME_ID,
        name="冰原狼踪",
        description=(
            "5x4 北欧冰原主题：免费旋转里落下的冰狼 Wild 会每局向左移动一列，"
            "直到走出网格或撞上极光才消失；极光触发 8~16 次免费旋转，倍率逐级递增。"
        ),
        reels=5,
        rows=4,
        symbols=_SYMBOLS,
        reel_sets={
            "base": ReelSet(
                name="base",
                strips=[list(_ORDER) for _ in range(5)],
                weights=[dict(w) for w in _BASE_WEIGHTS],
            ),
            "fs": ReelSet(
                name="fs",
                strips=[list(_ORDER) for _ in range(5)],
                weights=[dict(w) for w in _FS_WEIGHTS],
            ),
        },
        base_reel_set="base",
        paylines=Paylines(rows=4, lines=generate_lines(5, 4, 50)),
        bet=BetConfig(steps=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0], default_index=1, max_total_bet=50.0),
        features=Features(
            cascade=CascadeConfig(enabled=False),
            walking_wild=WalkingWildConfig(
                enabled=True,
                symbol="wolf",
                steps_per_spin=1,
                direction="left",
                # 只在免费旋转生效：基础 game 每局重置状态，行走没有意义
                phases=["free_spins"],
                max_walkers=6,
                protected_symbols=["scatter"],
            ),
            free_spins=FreeSpinsConfig(
                trigger_symbol="scatter",
                trigger_counts={3: 8, 4: 12, 5: 16},
                multiplier_progression=[1.0, 2.0, 3.0],
                retrigger_counts={3: 4, 4: 6, 5: 8},
                reel_set="fs",
            ),
        ),
        math=MathModel(
            target_rtp=0.965,
            volatility="high",
            max_win_multiplier=800.0,
            hit_frequency_target=0.30,
            rtp_tolerance=0.03,
        ),
        theme=Theme(
            id="frost",
            name="冰原狼踪",
            cabinet_color="#123243",
            background="#08161f",
            accent="#8ad7ff",
            palette={
                "grid": "#0f2531",
                "reel": "#16303f",
                "win": "#7cf6c8",
                "wild": "#a8e8ff",
                "bonus": "#8ad7ff",
            },
        ),
    )


CONFIG = build_config()
