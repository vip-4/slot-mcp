"""机台 8：巨神遗迹 —— 5x3 / 20 线，中高波动，巨符号（2×2 / 3×3）+ 免费旋转。

核心机制（全部由 CONFIG 描述，引擎无分支）
---------------------------------------------
* **赔付模式**：固定 20 线（`LINES_20_5x3`），线注 = 总注 / 20
* **巨符号**（`colossal`）：每局先在网格里投放一个 2×2 或 3×3 的同符号方块，
  再进入线赔结算；方块可落在第 1~3 轴（3×3 时只能落在第 1~2 轴），
  免费旋转里更常出现 3×3，且允许把 Wild 也做成巨符号
* **免费旋转**（`free_spins`）：图腾 Scatter 3/4/5 枚 → 8/12/16 次，倍率递进 [1,2,3]
* **目标**：RTP 96.5% / 中高波动 / 最大约 500x

调参入口：`slot_set_parameter`，例如
`features.colossal.size_weights.3`、`features.colossal.symbols.石像`。
"""

from __future__ import annotations

from ..engine.config import (
    BetConfig,
    CascadeConfig,
    ColossalSymbolConfig,
    Features,
    FreeSpinsConfig,
    GameConfig,
    MathModel,
    Paylines,
    ReelSet,
    Symbol,
    SymbolKind,
    Theme,
)
from ..engine.paylines import LINES_20_5x3

GAME_ID = "colossal_ruins"

_STANDARD_IDS = ["idol", "jaguar", "mask", "torch", "vase", "leaf"]

_SYMBOLS = {
    "idol": Symbol("idol", "石像", SymbolKind.STANDARD, pays={3: 3.31, 4: 10.57, 5: 27.77}, color="#c9a227", glyph="🗿"),
    "jaguar": Symbol("jaguar", "美洲豹", SymbolKind.STANDARD, pays={3: 2.32, 4: 7.28, 5: 18.51}, color="#e8b04b", glyph="🐆"),
    "mask": Symbol("mask", "黄金面具", SymbolKind.STANDARD, pays={3: 1.72, 4: 5.29, 5: 13.23}, color="#ffd45c", glyph="🎭"),
    "torch": Symbol("torch", "火把", SymbolKind.STANDARD, pays={3: 1.33, 4: 3.97, 5: 9.92}, color="#ff8c42", glyph="🔥"),
    "vase": Symbol("vase", "陶罐", SymbolKind.STANDARD, pays={3: 1.06, 4: 2.97, 5: 7.28}, color="#b08968", glyph="🏺"),
    "leaf": Symbol("leaf", "藤叶", SymbolKind.STANDARD, pays={3: 0.8, 4: 2.25, 5: 5.29}, color="#7cc47f", glyph="🍃"),
    "wild": Symbol(
        "wild",
        "图腾 Wild",
        SymbolKind.WILD,
        pays={3: 3.97, 4: 11.9, 5: 33.06},
        substitutes=tuple(_STANDARD_IDS),
        color="#ffe9a8",
        glyph="🌞",
    ),
    "scatter": Symbol(
        "scatter", "遗迹之门 Scatter", SymbolKind.SCATTER, scatter_pays={3: 1.33, 4: 5.29, 5: 19.83}, color="#9fe3ff", glyph="🚪"
    ),
}

_ORDER = [*_STANDARD_IDS, "wild", "scatter"]

_BASE_WEIGHTS = [
    {"idol": 6, "jaguar": 7, "mask": 8, "torch": 9, "vase": 10, "leaf": 11, "wild": 2, "scatter": 2},
    {"idol": 6, "jaguar": 7, "mask": 8, "torch": 9, "vase": 10, "leaf": 11, "wild": 2, "scatter": 2},
    {"idol": 6, "jaguar": 7, "mask": 8, "torch": 9, "vase": 10, "leaf": 11, "wild": 3, "scatter": 3},
    {"idol": 7, "jaguar": 7, "mask": 8, "torch": 9, "vase": 10, "leaf": 10, "wild": 2, "scatter": 2},
    {"idol": 6, "jaguar": 7, "mask": 8, "torch": 9, "vase": 10, "leaf": 11, "wild": 2, "scatter": 2},
]
_FREE_WEIGHTS = [
    {"idol": 5, "jaguar": 6, "mask": 7, "torch": 8, "vase": 8, "leaf": 9, "wild": 3, "scatter": 2},
    {"idol": 5, "jaguar": 6, "mask": 7, "torch": 8, "vase": 8, "leaf": 9, "wild": 3, "scatter": 2},
    {"idol": 5, "jaguar": 6, "mask": 7, "torch": 8, "vase": 8, "leaf": 9, "wild": 4, "scatter": 3},
    {"idol": 6, "jaguar": 6, "mask": 7, "torch": 8, "vase": 8, "leaf": 8, "wild": 3, "scatter": 2},
    {"idol": 5, "jaguar": 6, "mask": 7, "torch": 8, "vase": 8, "leaf": 9, "wild": 3, "scatter": 2},
]


def build_config() -> GameConfig:
    return GameConfig(
        id=GAME_ID,
        name="巨神遗迹",
        description=(
            "5x3 丛林遗迹：每局先落下一个 2×2 或 3×3 的巨型符号（石像 / 美洲豹 / 面具 / Wild）再结算，"
            "遗迹之门触发 8~16 次免费旋转，免费旋转内倍率逐级递增。"
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
            colossal=ColossalSymbolConfig(
                enabled=True,
                # 尺寸权重：约 25% 不投放、55% 2×2、20% 3×3
                size_weights={0: 25, 2: 55, 3: 20},
                symbols={"idol": 12, "jaguar": 10, "mask": 8, "wild": 3},
                reels=[0, 1, 2],
                rows=[0, 1],
                phases=["base", "free_spins"],
                protected_symbols=["scatter"],
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
            hit_frequency_target=0.32,
            rtp_tolerance=0.025,
        ),
        theme=Theme(
            id="ruins",
            name="巨神遗迹",
            cabinet_color="#3a2a18",
            background="#14100a",
            accent="#ffd45c",
            palette={
                "grid": "#241a10",
                "reel": "#33261a",
                "win": "#ffd45c",
                "wild": "#ffe9a8",
                "bonus": "#9fe3ff",
            },
        ),
    )


CONFIG = build_config()
