"""机台 13：黄金矿脉 —— 5x3 / 20 线，中高波动，累积奖池（Progressive Jackpot）+ 免费旋转。

核心机制（全部由 CONFIG 描述，引擎无分支）
---------------------------------------------
* **赔付模式**：固定 20 线（`LINES_20_5x3`），线注 = 总注 / 20
* **累积奖池**（`jackpot`，`mode=progressive`）：每注抽取 **2%** 注入四档奖池
  （Mini / Minor / Major / Grand，按 `contribution_share` 60/25/11/4 分摊），
  命中时派发该档**当前累积额**并把该档重置为 `seed`
  —— 长期 RTP 分量 ≈ `contribution_rate`（贡献守恒），短期则随大奖池被抽走而剧烈波动
* **免费旋转**（`free_spins`）：矿洞 Scatter 3/4/5 枚 → 8/12/16 次，倍率递进 [1,2,3]
* **目标**：RTP 96.5% / 中高波动 / 最大约 900x（大奖池被抽中的那一下）

调参入口：`slot_set_parameter`，例如
`features.jackpot.hit_chance`、`features.jackpot.contribution_rate`、
`features.jackpot.levels`（档位金额 / 权重 / 种子）。
"""

from __future__ import annotations

from ..engine.config import (
    BetConfig,
    Features,
    FreeSpinsConfig,
    GameConfig,
    JackpotConfig,
    JackpotLevel,
    MathModel,
    Paylines,
    ReelSet,
    Symbol,
    SymbolKind,
    Theme,
)
from ..engine.paylines import LINES_20_5x3

GAME_ID = "gold_vein"

_STANDARD_IDS = ["rubble", "pick", "cart", "lantern", "gem", "gold"]

_SYMBOLS = {
    "rubble": Symbol("rubble", "碎石", SymbolKind.STANDARD, pays={3: 5.12, 4: 15.36, 5: 40.96}, color="#8d8577", glyph="🪨"),
    "pick": Symbol("pick", "鹤嘴镐", SymbolKind.STANDARD, pays={3: 7.17, 4: 22.53, 5: 61.43}, color="#b0bec5", glyph="⛏️"),
    "cart": Symbol("cart", "矿车", SymbolKind.STANDARD, pays={3: 9.22, 4: 30.72, 5: 92.17}, color="#a1887f", glyph="🛒"),
    "lantern": Symbol("lantern", "矿灯", SymbolKind.STANDARD, pays={3: 12.29, 4: 40.96, 5: 122.89}, color="#ffd166", glyph="🔦"),
    "gem": Symbol("gem", "宝石", SymbolKind.STANDARD, pays={3: 16.39, 4: 56.32, 5: 174.09}, color="#7ee8fa", glyph="💎"),
    "gold": Symbol("gold", "金块", SymbolKind.STANDARD, pays={3: 22.53, 4: 76.81, 5: 245.77}, color="#ffc300", glyph="🪙"),
    "wild": Symbol(
        "wild",
        "矿脉 Wild",
        SymbolKind.WILD,
        pays={3: 28.67, 4: 97.29, 5: 307.21},
        substitutes=tuple(_STANDARD_IDS),
        color="#ffe9a8",
        glyph="🔶",
    ),
    "scatter": Symbol(
        "scatter", "矿洞 Scatter", SymbolKind.SCATTER, scatter_pays={3: 1.99, 4: 6.97, 5: 24.92}, color="#c6a4ff", glyph="🕳️"
    ),
}

_ORDER = [*_STANDARD_IDS, "wild", "scatter"]

_BASE_WEIGHTS = [
    {"rubble": 20, "pick": 18, "cart": 16, "lantern": 13, "gem": 10, "gold": 7, "wild": 3, "scatter": 3},
    {"rubble": 20, "pick": 18, "cart": 16, "lantern": 13, "gem": 10, "gold": 8, "wild": 3, "scatter": 3},
    {"rubble": 20, "pick": 18, "cart": 16, "lantern": 14, "gem": 11, "gold": 8, "wild": 4, "scatter": 3},
    {"rubble": 20, "pick": 18, "cart": 17, "lantern": 14, "gem": 11, "gold": 8, "wild": 3, "scatter": 3},
    {"rubble": 20, "pick": 18, "cart": 16, "lantern": 13, "gem": 10, "gold": 7, "wild": 3, "scatter": 3},
]
# 免费旋转：高档符号更密
_FREE_WEIGHTS = [
    {"rubble": 16, "pick": 16, "cart": 16, "lantern": 14, "gem": 12, "gold": 9, "wild": 5, "scatter": 3},
    {"rubble": 16, "pick": 16, "cart": 16, "lantern": 14, "gem": 12, "gold": 10, "wild": 5, "scatter": 3},
    {"rubble": 16, "pick": 16, "cart": 17, "lantern": 15, "gem": 13, "gold": 10, "wild": 6, "scatter": 3},
    {"rubble": 16, "pick": 16, "cart": 17, "lantern": 15, "gem": 13, "gold": 10, "wild": 5, "scatter": 3},
    {"rubble": 16, "pick": 16, "cart": 16, "lantern": 14, "gem": 12, "gold": 9, "wild": 5, "scatter": 3},
]


def build_config() -> GameConfig:
    return GameConfig(
        id=GAME_ID,
        name="黄金矿脉",
        description=(
            "5x3 黄金矿脉主题：每注抽取 2% 注入 Mini / Minor / Major / Grand 四档累积奖池，"
            "命中即派发该档当前累积额并重置为种子值；矿洞 Scatter 触发 8~16 次免费旋转，倍率递增。"
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
            jackpot=JackpotConfig(
                enabled=True,
                mode="progressive",
                levels=[
                    JackpotLevel(name="Mini", amount=25.0, weight=60.0, seed=5.0, contribution_share=60.0),
                    JackpotLevel(name="Minor", amount=75.0, weight=28.0, seed=15.0, contribution_share=25.0),
                    JackpotLevel(name="Major", amount=300.0, weight=10.0, seed=60.0, contribution_share=11.0),
                    JackpotLevel(name="Grand", amount=1500.0, weight=2.0, seed=250.0, contribution_share=4.0),
                ],
                hit_chance=1.0 / 1500.0,
                contribution_rate=0.02,
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
            max_win_multiplier=900.0,
            hit_frequency_target=0.33,
            rtp_tolerance=0.025,
        ),
        theme=Theme(
            id="mine",
            name="黄金矿脉",
            cabinet_color="#3a2a12",
            background="#150f06",
            accent="#ffc300",
            palette={
                "grid": "#2b2010",
                "reel": "#3a2a12",
                "win": "#ffc300",
                "wild": "#ffe9a8",
                "bonus": "#c6a4ff",
            },
        ),
    )


CONFIG = build_config()
