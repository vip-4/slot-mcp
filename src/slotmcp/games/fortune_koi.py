"""机台 6：锦鲤纳福 —— 5x3 / 20 线，中高波动，Cash Collect + 随机 Wild + 免费旋转。

核心机制（全部由 CONFIG 描述，引擎无 branch）
---------------------------------------------
* **赔付模式**：固定 20 线（`LINES_20_5x3`），线注 = 总注 / 20
* **随机 Wild 投放**（`random_wild`）：每局新鲜网格按权重投放 0~3 枚「锦鲤 Wild」，
  免费旋转里投放权重整体提高；不覆盖 Scatter 与币值符号
* **Cash Collect**（`collect`）：屏上出现锦鲤 Wild 时，收集全部金币面值
  （铜钱 1x / 银锭 5x / 金元宝 25x / 福袋 200x），免费旋转里收集倍率 ×2
* **免费旋转**（`free_spins`）：莲花 Scatter 3/4/5 枚 → 8/12/16 次，
  倍率递进 [1,2,3,5]，可再触发
* **目标**：RTP 96.5% / 中高波动 / 最大约 1200x

调参入口：`slot_set_parameter`，例如
`features.collect.free_award_multiplier`、`features.random_wild.counts.2`。
"""

from __future__ import annotations

from ..engine.config import (
    BetConfig,
    CascadeConfig,
    CollectConfig,
    Features,
    FreeSpinsConfig,
    GameConfig,
    MathModel,
    Paylines,
    RandomWildConfig,
    ReelSet,
    Symbol,
    SymbolKind,
    Theme,
)
from ..engine.paylines import LINES_20_5x3

GAME_ID = "fortune_koi"

_STANDARD_IDS = ["carp", "ingot", "lantern", "fan", "knot", "coin_purse"]
_COIN_IDS = ["coin_b", "coin_s", "coin_g", "coin_jp"]

_SYMBOLS = {
    "carp": Symbol("carp", "锦鲤", SymbolKind.STANDARD, pays={3: 5, 4: 17, 5: 48}, color="#ff9d5c", glyph="🐟"),
    "ingot": Symbol("ingot", "金元宝", SymbolKind.STANDARD, pays={3: 3.5, 4: 12, 5: 34}, color="#ffd45c", glyph="🪙"),
    "lantern": Symbol("lantern", "灯笼", SymbolKind.STANDARD, pays={3: 2.5, 4: 9.5, 5: 24}, color="#ff6b6b", glyph="🏮"),
    "fan": Symbol("fan", "折扇", SymbolKind.STANDARD, pays={3: 2.4, 4: 7.2, 5: 19}, color="#8ad7ff", glyph="🪭"),
    "knot": Symbol("knot", "中国结", SymbolKind.STANDARD, pays={3: 1.8, 4: 6, 5: 14}, color="#ff9ec4", glyph="🎀"),
    "coin_purse": Symbol("coin_purse", "福袋", SymbolKind.STANDARD, pays={3: 1.2, 4: 4.2, 5: 11}, color="#c6a4ff", glyph="🎴"),
    "wild": Symbol(
        "wild",
        "锦鲤 Wild（收集者）",
        SymbolKind.WILD,
        pays={3: 7, 4: 24, 5: 72},
        substitutes=tuple(_STANDARD_IDS),
        color="#ffe9a8",
        glyph="🌊",
    ),
    "scatter": Symbol(
        "scatter", "莲花 Scatter", SymbolKind.SCATTER, scatter_pays={3: 2, 4: 10, 5: 40}, color="#ffd9ec", glyph="🪷"
    ),
    # 币值符号：只在被锦鲤 Wild 收集时才有价值，本身不参与线赔
    "coin_b": Symbol("coin_b", "铜钱", SymbolKind.BONUS, color="#c98b4b", glyph="🟤"),
    "coin_s": Symbol("coin_s", "银锭", SymbolKind.BONUS, color="#d7e3ff", glyph="⚪"),
    "coin_g": Symbol("coin_g", "金元宝币", SymbolKind.BONUS, color="#ffcc33", glyph="🟡"),
    "coin_jp": Symbol("coin_jp", "福袋大奖", SymbolKind.BONUS, color="#ff5577", glyph="🎁"),
}

# 物理条带（权重展开为虚拟条带，顺序只影响聚集度，不影响概率）
_STRIP_ORDER = [*_STANDARD_IDS, "wild", "scatter", *_COIN_IDS]
_BASE_WEIGHTS = [
    {"carp": 5, "ingot": 6, "lantern": 7, "fan": 8, "knot": 9, "coin_purse": 10,
     "wild": 2, "scatter": 2, "coin_b": 2, "coin_s": 0, "coin_g": 0, "coin_jp": 0},
    {"carp": 5, "ingot": 6, "lantern": 7, "fan": 8, "knot": 9, "coin_purse": 10,
     "wild": 3, "scatter": 2, "coin_b": 2, "coin_s": 1, "coin_g": 0, "coin_jp": 0},
    {"carp": 5, "ingot": 6, "lantern": 7, "fan": 8, "knot": 9, "coin_purse": 10,
     "wild": 3, "scatter": 3, "coin_b": 2, "coin_s": 1, "coin_g": 1, "coin_jp": 0},
    {"carp": 6, "ingot": 7, "lantern": 7, "fan": 8, "knot": 9, "coin_purse": 9,
     "wild": 2, "scatter": 2, "coin_b": 2, "coin_s": 1, "coin_g": 0, "coin_jp": 0},
    {"carp": 5, "ingot": 6, "lantern": 8, "fan": 8, "knot": 9, "coin_purse": 10,
     "wild": 2, "scatter": 2, "coin_b": 2, "coin_s": 0, "coin_g": 0, "coin_jp": 0},
]
# 免费旋转条带：币值更密、收集者更多（福袋大奖只在这里出现）
_FREE_WEIGHTS = [
    {"carp": 4, "ingot": 5, "lantern": 6, "fan": 7, "knot": 7, "coin_purse": 8,
     "wild": 5, "scatter": 2, "coin_b": 4, "coin_s": 1, "coin_g": 0, "coin_jp": 0},
    {"carp": 4, "ingot": 5, "lantern": 6, "fan": 7, "knot": 7, "coin_purse": 8,
     "wild": 6, "scatter": 2, "coin_b": 4, "coin_s": 2, "coin_g": 0, "coin_jp": 0},
    {"carp": 4, "ingot": 5, "lantern": 6, "fan": 7, "knot": 7, "coin_purse": 8,
     "wild": 6, "scatter": 3, "coin_b": 4, "coin_s": 2, "coin_g": 1, "coin_jp": 1},
    {"carp": 5, "ingot": 6, "lantern": 6, "fan": 7, "knot": 7, "coin_purse": 7,
     "wild": 5, "scatter": 2, "coin_b": 4, "coin_s": 2, "coin_g": 0, "coin_jp": 0},
    {"carp": 4, "ingot": 5, "lantern": 7, "fan": 7, "knot": 7, "coin_purse": 8,
     "wild": 5, "scatter": 2, "coin_b": 4, "coin_s": 1, "coin_g": 0, "coin_jp": 0},
]


def build_config() -> GameConfig:
    return GameConfig(
        id=GAME_ID,
        name="锦鲤纳福",
        description=(
            "5x3 国风池塘：锦鲤 Wild 随机跃入水面并收集屏上全部金币面值，"
            "莲花 Scatter 触发最多 16 次免费旋转，免费旋转内收集倍率翻倍。"
        ),
        reels=5,
        rows=3,
        symbols=_SYMBOLS,
        reel_sets={
            "base": ReelSet(
                name="base",
                strips=[list(_STRIP_ORDER) for _ in range(5)],
                weights=[dict(w) for w in _BASE_WEIGHTS],
            ),
            "free": ReelSet(
                name="free",
                strips=[list(_STRIP_ORDER) for _ in range(5)],
                weights=[dict(w) for w in _FREE_WEIGHTS],
            ),
        },
        base_reel_set="base",
        paylines=Paylines(rows=3, lines=[list(x) for x in LINES_20_5x3]),
        bet=BetConfig(steps=[0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0], default_index=2, max_total_bet=20.0),
        features=Features(
            cascade=CascadeConfig(enabled=False),
            random_wild=RandomWildConfig(
                enabled=True,
                symbol="wild",
                # 投放个数 -> 权重：约 62% 不放、28% 放 1 枚、8% 放 2 枚、2% 放 3 枚
                counts={0: 62, 1: 28, 2: 8, 3: 2},
                phases=["base", "free_spins"],
                exclude_reels=[],
                protected_symbols=["scatter", "coin_b", "coin_s", "coin_g", "coin_jp"],
            ),
            collect=CollectConfig(
                enabled=True,
                collector="wild",
                coin_symbols=list(_COIN_IDS),
                coin_values={"coin_b": 0.11, "coin_s": 0.55, "coin_g": 2.2, "coin_jp": 0.0},
                award_multiplier=1.0,
                free_award_multiplier=2.0,
                jackpot_symbol="coin_jp",
                jackpot_value=7.0,
            ),
            free_spins=FreeSpinsConfig(
                trigger_symbol="scatter",
                trigger_counts={3: 8, 4: 12, 5: 16},
                multiplier_progression=[1.0, 1.0, 2.0, 3.0, 5.0],
                retrigger_counts={3: 4, 4: 6, 5: 8},
                reel_set="free",
            ),
        ),
        math=MathModel(
            target_rtp=0.965,
            volatility="medium-high",
            max_win_multiplier=600.0,
            hit_frequency_target=0.30,
            rtp_tolerance=0.02,
        ),
        theme=Theme(
            id="koi",
            name="锦鲤池塘",
            cabinet_color="#1b4b4a",
            background="#06231f",
            accent="#ffd45c",
            palette={
                "grid": "#0d3b36",
                "reel": "#125550",
                "win": "#ffd45c",
                "wild": "#ffe9a8",
                "coin": "#ffcc33",
            },
        ),
    )


CONFIG = build_config()
