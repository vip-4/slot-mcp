"""机台 11：霓虹双子 —— 5x3 / 20 线，中高波动，同步轴（Twin Reels）+ 免费旋转。

核心机制（全部由 CONFIG 描述，引擎无分支）
---------------------------------------------
* **赔付模式**：固定 20 线（`LINES_20_5x3`），线注 = 总注 / 20
* **同步轴**（`sync_reels`）：每局随机挑选 2~5 个**相邻轴**显示完全相同的符号
  （权重 2:55 / 3:30 / 4:12 / 5:3），同步后的网格才进入后续结算
* **免费旋转**（`free_spins`）：双子门 Scatter 3/4/5 枚 → 8/12/16 次，倍率递进 [1,2,3]，
  可再触发（3/4/5 → 4/6/8 次）
* **目标**：RTP 96.5% / 中高波动 / 最大约 600x

调参入口：`slot_set_parameter`，例如
`features.sync_reels.widths.5`、`features.sync_reels.phases`。
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
    SyncReelsConfig,
    Theme,
)
from ..engine.paylines import LINES_20_5x3

GAME_ID = "neon_twins"

_STANDARD_IDS = ["heart", "disc", "phones", "guitar", "dice", "star"]

_SYMBOLS = {
    "heart": Symbol("heart", "霓虹心", SymbolKind.STANDARD, pays={3: 2.14, 4: 7.52, 5: 21.49}, color="#ff6b9d", glyph="💖"),
    "disc": Symbol("disc", "唱片", SymbolKind.STANDARD, pays={3: 1.93, 4: 6.66, 5: 18.27}, color="#b8a4ff", glyph="💿"),
    "phones": Symbol("phones", "耳机", SymbolKind.STANDARD, pays={3: 1.61, 4: 5.37, 5: 14.5}, color="#8ad7ff", glyph="🎧"),
    "guitar": Symbol("guitar", "吉他", SymbolKind.STANDARD, pays={3: 1.29, 4: 4.3, 5: 11.28}, color="#ffd45c", glyph="🎸"),
    "dice": Symbol("dice", "骰子", SymbolKind.STANDARD, pays={3: 0.97, 4: 3.22, 5: 8.6}, color="#c6a4ff", glyph="🎲"),
    "star": Symbol("star", "星标", SymbolKind.STANDARD, pays={3: 0.74, 4: 2.48, 5: 6.44}, color="#7cf6c8", glyph="⭐"),
    "wild": Symbol(
        "wild",
        "棱镜 Wild",
        SymbolKind.WILD,
        pays={3: 2.69, 4: 9.67, 5: 26.87},
        substitutes=tuple(_STANDARD_IDS),
        color="#f0f8ff",
        glyph="🔷",
    ),
    "scatter": Symbol(
        "scatter", "双子门 Scatter", SymbolKind.SCATTER, scatter_pays={3: 1.61, 4: 6.44, 5: 23.64}, color="#ff9ecd", glyph="🚪"
    ),
}

_ORDER = [*_STANDARD_IDS, "wild", "scatter"]

_BASE_WEIGHTS = [
    {"heart": 8, "disc": 10, "phones": 12, "guitar": 14, "dice": 16, "star": 18, "wild": 3, "scatter": 1},
    {"heart": 8, "disc": 10, "phones": 12, "guitar": 14, "dice": 16, "star": 18, "wild": 3, "scatter": 1},
    {"heart": 9, "disc": 11, "phones": 12, "guitar": 14, "dice": 16, "star": 18, "wild": 4, "scatter": 1},
    {"heart": 8, "disc": 10, "phones": 12, "guitar": 14, "dice": 16, "star": 17, "wild": 3, "scatter": 1},
    {"heart": 8, "disc": 10, "phones": 12, "guitar": 14, "dice": 16, "star": 18, "wild": 3, "scatter": 1},
]
_FREE_WEIGHTS = [
    {"heart": 10, "disc": 11, "phones": 12, "guitar": 13, "dice": 14, "star": 15, "wild": 5, "scatter": 1},
    {"heart": 10, "disc": 11, "phones": 12, "guitar": 13, "dice": 14, "star": 15, "wild": 5, "scatter": 1},
    {"heart": 11, "disc": 12, "phones": 12, "guitar": 13, "dice": 14, "star": 15, "wild": 6, "scatter": 1},
    {"heart": 10, "disc": 11, "phones": 12, "guitar": 13, "dice": 14, "star": 14, "wild": 5, "scatter": 1},
    {"heart": 10, "disc": 11, "phones": 12, "guitar": 13, "dice": 14, "star": 15, "wild": 5, "scatter": 1},
]


def build_config() -> GameConfig:
    return GameConfig(
        id=GAME_ID,
        name="霓虹双子",
        description=(
            "5x3 赛博霓虹主题：每局随机挑选 2~5 个相邻轴显示完全相同的符号，"
            "同步后的网格再进入结算；双子门触发 8~16 次免费旋转，倍率逐级递增。"
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
            sync_reels=SyncReelsConfig(
                enabled=True,
                # 相邻轴同步数 -> 权重（权重 0 即该宽度不出现）
                widths={2: 55, 3: 30, 4: 12, 5: 3},
                phases=["base", "free_spins"],
                copy_from="first",
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
            max_win_multiplier=600.0,
            hit_frequency_target=0.34,
            rtp_tolerance=0.025,
        ),
        theme=Theme(
            id="neon",
            name="霓虹双子",
            cabinet_color="#1b1035",
            background="#0a0618",
            accent="#ff6b9d",
            palette={
                "grid": "#241546",
                "reel": "#2f1a58",
                "win": "#7cf6c8",
                "wild": "#f0f8ff",
                "bonus": "#ff9ecd",
            },
        ),
    )


CONFIG = build_config()
