"""机台 9：凤凰涅槃 —— 5x3 / 20 线，中高波动，神秘符号（揭示为同一符号）+ 免费旋转。

核心机制（全部由 CONFIG 描述，引擎无分支）
---------------------------------------------
* **赔付模式**：固定 20 线（`LINES_20_5x3`），线注 = 总注 / 20
* **神秘符号**（`mystery`）：屏上出现的「凤凰蛋」在结算前统一揭示为同一符号
  （火羽 / 赤玉 / 青铜镜 / 卷轴 / 香炉，或 Wild），免费旋转里蛋更密且更容易揭示为 Wild
* **免费旋转**（`free_spins`）：神木 Scatter 3/4/5 枚 → 8/12/16 次，倍率递进 [1,2,3]
* **目标**：RTP 96.5% / 中高波动 / 最大约 500x

调参入口：`slot_set_parameter`，例如
`features.mystery.reveal_symbols.wild`、`features.mystery.reveal_all_same`。
"""

from __future__ import annotations

from ..engine.config import (
    BetConfig,
    CascadeConfig,
    Features,
    FreeSpinsConfig,
    GameConfig,
    MathModel,
    MysterySymbolConfig,
    Paylines,
    ReelSet,
    Symbol,
    SymbolKind,
    Theme,
)
from ..engine.paylines import LINES_20_5x3

GAME_ID = "phoenix_rebirth"

_STANDARD_IDS = ["plume", "jade", "mirror", "scroll", "censer", "ash"]

_SYMBOLS = {
    "plume": Symbol("plume", "火羽", SymbolKind.STANDARD, pays={3: 17.5, 4: 55.43, 5: 145.87}, color="#ff9d5c", glyph="🪶"),
    "jade": Symbol("jade", "赤玉", SymbolKind.STANDARD, pays={3: 12.25, 4: 38.51, 5: 99.19}, color="#ff6b6b", glyph="🔴"),
    "mirror": Symbol("mirror", "青铜镜", SymbolKind.STANDARD, pays={3: 9.34, 4: 28.59, 5: 72.94}, color="#c9a227", glyph="🪞"),
    "scroll": Symbol("scroll", "卷轴", SymbolKind.STANDARD, pays={3: 7.29, 4: 21.59, 5: 54.85}, color="#e8d8b0", glyph="📜"),
    "censer": Symbol("censer", "香炉", SymbolKind.STANDARD, pays={3: 5.83, 4: 16.92, 5: 42.01}, color="#b08968", glyph="🪔"),
    "ash": Symbol("ash", "余烬", SymbolKind.STANDARD, pays={3: 4.38, 4: 12.84, 5: 31.51}, color="#9a8f80", glyph="🌫️"),
    "wild": Symbol(
        "wild",
        "涅槃之火 Wild",
        SymbolKind.WILD,
        pays={3: 21.01, 4: 64.18, 5: 169.21},
        substitutes=tuple(_STANDARD_IDS),
        color="#ffe9a8",
        glyph="🔥",
    ),
    "scatter": Symbol(
        "scatter", "神木 Scatter", SymbolKind.SCATTER, scatter_pays={3: 1.51, 4: 6.04, 5: 22.13}, color="#8ad7ff", glyph="🌳"
    ),
    # 占位符号：本身不参与线赔，结算前统一揭示
    "egg": Symbol("egg", "凤凰蛋（神秘符号）", SymbolKind.BONUS, color="#ffd45c", glyph="🥚"),
}

_ORDER = [*_STANDARD_IDS, "egg", "wild", "scatter"]

_BASE_WEIGHTS = [
    {"plume": 6, "jade": 7, "mirror": 8, "scroll": 9, "censer": 10, "ash": 11, "egg": 3, "wild": 2, "scatter": 2},
    {"plume": 6, "jade": 7, "mirror": 8, "scroll": 9, "censer": 10, "ash": 11, "egg": 3, "wild": 2, "scatter": 2},
    {"plume": 6, "jade": 7, "mirror": 8, "scroll": 9, "censer": 10, "ash": 11, "egg": 4, "wild": 3, "scatter": 3},
    {"plume": 7, "jade": 7, "mirror": 8, "scroll": 9, "censer": 10, "ash": 10, "egg": 3, "wild": 2, "scatter": 2},
    {"plume": 6, "jade": 7, "mirror": 8, "scroll": 9, "censer": 10, "ash": 11, "egg": 3, "wild": 2, "scatter": 2},
]
# 免费旋转：蛋明显更密
_FREE_WEIGHTS = [
    {"plume": 5, "jade": 6, "mirror": 7, "scroll": 8, "censer": 8, "ash": 9, "egg": 7, "wild": 3, "scatter": 2},
    {"plume": 5, "jade": 6, "mirror": 7, "scroll": 8, "censer": 8, "ash": 9, "egg": 7, "wild": 3, "scatter": 2},
    {"plume": 5, "jade": 6, "mirror": 7, "scroll": 8, "censer": 8, "ash": 9, "egg": 8, "wild": 4, "scatter": 3},
    {"plume": 6, "jade": 6, "mirror": 7, "scroll": 8, "censer": 8, "ash": 8, "egg": 7, "wild": 3, "scatter": 2},
    {"plume": 5, "jade": 6, "mirror": 7, "scroll": 8, "censer": 8, "ash": 9, "egg": 7, "wild": 3, "scatter": 2},
]


def build_config() -> GameConfig:
    return GameConfig(
        id=GAME_ID,
        name="凤凰涅槃",
        description=(
            "5x3 神话主题：屏上的凤凰蛋会在结算前统一揭示为同一符号（火羽 / 赤玉 / 青铜镜 / 卷轴 / 香炉，"
            "或涅槃之火 Wild），神木触发 8~16 次免费旋转，免费旋转内蛋更密、倍率逐级递增。"
        ),
        reels=5,
        rows=3,
        symbols=_SYMBOLS,
        reel_sets={
            "base": ReelSet(
                name="base",
                strips=[list(_ORDER) for _ in range(5)],
                weights=[dict(w) for w in _BASE_WEIGHTS],
            ),
            "free": ReelSet(
                name="free",
                strips=[list(_ORDER) for _ in range(5)],
                weights=[dict(w) for w in _FREE_WEIGHTS],
            ),
        },
        base_reel_set="base",
        paylines=Paylines(rows=3, lines=[list(x) for x in LINES_20_5x3]),
        bet=BetConfig(steps=[0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0], default_index=2, max_total_bet=20.0),
        features=Features(
            cascade=CascadeConfig(enabled=False),
            mystery=MysterySymbolConfig(
                enabled=True,
                symbol="egg",
                # 揭示目标：以标准符号为主，Wild 权重可控（越高越容易成片替代）
                reveal_symbols={"plume": 18, "jade": 22, "mirror": 26, "scroll": 22, "censer": 12, "wild": 10},
                reveal_all_same=True,
                phases=["base", "free_spins"],
            ),
            free_spins=FreeSpinsConfig(
                trigger_symbol="scatter",
                trigger_counts={3: 8, 4: 12, 5: 16},
                multiplier_progression=[1.0, 2.0, 3.0],
                retrigger_counts={3: 4, 4: 6, 5: 8},
                reel_set="free",
            ),
        ),
        math=MathModel(
            target_rtp=0.965,
            volatility="medium-high",
            max_win_multiplier=500.0,
            hit_frequency_target=0.34,
            rtp_tolerance=0.025,
        ),
        theme=Theme(
            id="phoenix",
            name="凤凰涅槃",
            cabinet_color="#4a1410",
            background="#180806",
            accent="#ff8c42",
            palette={
                "grid": "#2a0f0c",
                "reel": "#3a1712",
                "win": "#ffd45c",
                "wild": "#ffe9a8",
                "bonus": "#ff8c42",
            },
        ),
    )


CONFIG = build_config()
