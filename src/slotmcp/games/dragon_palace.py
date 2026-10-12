"""机台 3：龙宫探宝 —— 5x4 / 50 线，高波动，免费旋转 + 递增倍率 + 再触发。

核心机制
* 赔付模式：固定 50 线（由 `paylines.generate_lines(5, 4, 50)` 确定性生成）
* Scatter（🏯）3/4/5 个分别赠送 10/14/20 次免费旋转
* 免费旋转使用独立条带 `fs`（高价值符号与 Wild 权重更高），并按
  `multiplier_progression` 逐级递增全局倍率：[1,2,3,4,4,5,6,7,9,12,15,18,22,26,32]
* 免费旋转期间落在第 3 轴的神龙 Wild 变为粘性 Wild，保留到特性结束（收益高度非线性）
* 免费旋转期间再次出现 3+ Scatter 触发再触发
* 目标：RTP 96% / 高波动 / 最大约 5000x
"""

from __future__ import annotations

from ..engine.config import (
    BetConfig,
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
from ..engine.paylines import generate_lines

GAME_ID = "dragon_palace"

_STANDARD_IDS = ["lantern", "coin", "lotus", "goldbar", "dragon_eye"]

_SYMBOLS = {
    "lantern": Symbol("lantern", "宫灯", SymbolKind.STANDARD, pays={3: 1.4, 4: 6.5, 5: 22.3}, color="#ff7b54", glyph="🏮"),
    "coin": Symbol("coin", "铜钱", SymbolKind.STANDARD, pays={3: 2.3, 4: 8.0, 5: 29.1}, color="#ffd166", glyph="🪙"),
    "lotus": Symbol("lotus", "莲花", SymbolKind.STANDARD, pays={3: 2.8, 4: 10.2, 5: 37.3}, color="#ff9ecd", glyph="🌸"),
    "goldbar": Symbol("goldbar", "金锭", SymbolKind.STANDARD, pays={3: 2.8, 4: 13.1, 5: 48.5}, color="#ffe7a3", glyph="💰"),
    "dragon_eye": Symbol("dragon_eye", "龙瞳", SymbolKind.STANDARD, pays={3: 5.1, 4: 18.9, 5: 74.7}, color="#8ef0ff", glyph="🐲"),
    "wild": Symbol(
        "wild",
        "神龙 Wild",
        SymbolKind.WILD,
        pays={3: 6.1, 4: 22.3, 5: 93.1},
        substitutes=tuple(_STANDARD_IDS),
        color="#7cf6c8",
        glyph="🐉",
    ),
    "scatter": Symbol(
        "scatter", "龙宫 Scatter", SymbolKind.SCATTER, scatter_pays={3: 1, 4: 3, 5: 10}, color="#c792ff", glyph="🏯"
    ),
}

_STRIP_ORDER = [*_STANDARD_IDS, "wild", "scatter"]

_BASE_WEIGHTS = [
    {"lantern": 22, "coin": 19, "lotus": 18, "goldbar": 14, "dragon_eye": 10, "wild": 5, "scatter": 2},
    {"lantern": 22, "coin": 19, "lotus": 18, "goldbar": 14, "dragon_eye": 10, "wild": 6, "scatter": 2},
    {"lantern": 22, "coin": 19, "lotus": 18, "goldbar": 14, "dragon_eye": 11, "wild": 6, "scatter": 2},
    {"lantern": 22, "coin": 19, "lotus": 18, "goldbar": 15, "dragon_eye": 11, "wild": 6, "scatter": 2},
    {"lantern": 22, "coin": 19, "lotus": 18, "goldbar": 14, "dragon_eye": 10, "wild": 5, "scatter": 2},
]

# 免费旋转专用条带：Wild 与高价值符号权重提高，配合递增倍率放大爆发感
_FS_WEIGHTS = [
    {"lantern": 19, "coin": 19, "lotus": 18, "goldbar": 16, "dragon_eye": 13, "wild": 8, "scatter": 2},
    {"lantern": 19, "coin": 19, "lotus": 18, "goldbar": 16, "dragon_eye": 13, "wild": 9, "scatter": 2},
    {"lantern": 19, "coin": 19, "lotus": 18, "goldbar": 16, "dragon_eye": 13, "wild": 9, "scatter": 2},
    {"lantern": 19, "coin": 19, "lotus": 18, "goldbar": 16, "dragon_eye": 13, "wild": 9, "scatter": 2},
    {"lantern": 19, "coin": 19, "lotus": 18, "goldbar": 16, "dragon_eye": 13, "wild": 8, "scatter": 2},
]


def build_config() -> GameConfig:
    return GameConfig(
        id=GAME_ID,
        name="龙宫探宝",
        description="5x4 东方神话机台，免费旋转期间倍率逐级攀升，可无限再触发。",
        reels=5,
        rows=4,
        symbols=_SYMBOLS,
        reel_sets={
            "base": ReelSet(
                name="base",
                strips=[list(_STRIP_ORDER) for _ in range(5)],
                weights=[dict(w) for w in _BASE_WEIGHTS],
            ),
            "fs": ReelSet(
                name="fs",
                strips=[list(_STRIP_ORDER) for _ in range(5)],
                weights=[dict(w) for w in _FS_WEIGHTS],
            ),
        },
        base_reel_set="base",
        paylines=Paylines(rows=4, lines=generate_lines(5, 4, 50)),
        bet=BetConfig(steps=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0], default_index=1, max_total_bet=50.0),
        features=Features(
            free_spins=FreeSpinsConfig(
                trigger_symbol="scatter",
                trigger_counts={3: 10, 4: 14, 5: 20},
                multiplier_progression=[1, 2, 3, 4, 4, 5, 6, 7, 9, 12, 15, 18, 22, 26, 32],
                retrigger_counts={3: 4, 4: 8, 5: 12},
                sticky_wild_reels=[2],
                reel_set="fs",
            )
        ),
        math=MathModel(
            target_rtp=0.96,
            volatility="high",
            max_win_multiplier=1000.0,
            hit_frequency_target=0.57,
            # 高波动机台的仿真估计方差大，10 万局级别的抽检需要更宽的容差
            rtp_tolerance=0.03,
        ),
        theme=Theme(
            id="dragon",
            name="深海龙宫",
            cabinet_color="#0f3d3e",
            background="#04131c",
            accent="#ffc857",
            palette={"grid": "#062a35", "reel": "#0b4a55", "win": "#ffe98a"},
        ),
    )


CONFIG = build_config()
