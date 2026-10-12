"""机台 7：雷霆神殿 —— 5x3 / 20 线，高波动，倍率 Wild + Pick'em 选雷石 + 免费旋转。

核心机制（全部由 CONFIG 描述，引擎无分支）
---------------------------------------------
* **赔付模式**：固定 20 线（`LINES_20_5x3`），线注 = 总注 / 20
* **倍率 Wild**（`multiplier_wild`）：雷锤 Wild 自带倍率（×2 / ×3），
  参与替代时按配置合并（本台为 `sum`：×2 + ×3 → ×4），线与 Ways 都生效
* **Pick'em 选雷石**（`pick_bonus`）：雷石 3/4/5 枚 → 可挑 3/4/5 次，
  无放回抽取奖品（2x / 5x / 15x / 50x 总注），累计派奖
* **免费旋转**（`free_spins`）：神殿之门 Scatter 3/4/5 枚 → 10/15/20 次，
  倍率递进 [1,2,3,5]，可再触发

调参入口：`slot_set_parameter`，例如
`features.multiplier_wild.combine`、`features.pick_bonus.prize_pool.雷神之怒`。
"""

from __future__ import annotations

from ..engine.config import (
    BetConfig,
    CascadeConfig,
    Features,
    FreeSpinsConfig,
    GameConfig,
    MathModel,
    MultiplierWildConfig,
    Paylines,
    PickBonusConfig,
    ReelSet,
    Symbol,
    SymbolKind,
    Theme,
)
from ..engine.paylines import LINES_20_5x3

GAME_ID = "thunder_temple"

_STANDARD_IDS = ["eagle", "wolf", "raven", "spear", "shield", "rune"]
_WILD_IDS = ["wild_x2", "wild_x3"]

_ORDER = [*_STANDARD_IDS, "wild_x2", "wild_x3", "scatter", "totem"]

_SYMBOLS = {
    "eagle": Symbol("eagle", "雷鹰", SymbolKind.STANDARD, pays={3: 3.69, 4: 11.27, 5: 29.72}, color="#bfe6ff", glyph="🦅"),
    "wolf": Symbol("wolf", "苍狼", SymbolKind.STANDARD, pays={3: 2.77, 4: 8.4, 5: 22.55}, color="#cfd8e3", glyph="🐺"),
    "raven": Symbol("raven", "渡鸦", SymbolKind.STANDARD, pays={3: 2.36, 4: 6.56, 5: 16.81}, color="#a08cff", glyph="🐦"),
    "spear": Symbol("spear", "长矛", SymbolKind.STANDARD, pays={3: 1.84, 4: 5.64, 5: 13.94}, color="#9ad1ff", glyph="🔱"),
    "shield": Symbol("shield", "盾牌", SymbolKind.STANDARD, pays={3: 1.49, 4: 4.2, 5: 10.25}, color="#ffd9a0", glyph="🛡️"),
    "rune": Symbol("rune", "符文", SymbolKind.STANDARD, pays={3: 1.13, 4: 3.28, 5: 7.48}, color="#c9f7d0", glyph="🔯"),
    "wild_x2": Symbol(
        "wild_x2", "雷锤 Wild ×2", SymbolKind.WILD, pays={3: 4.61, 4: 13.94, 5: 36.9},
        substitutes=tuple(_STANDARD_IDS), multiplier=2.0, color="#ffe066", glyph="🔨",
    ),
    "wild_x3": Symbol(
        "wild_x3", "雷锤 Wild ×3", SymbolKind.WILD, pays={3: 5.64, 4: 16.81, 5: 45.1},
        substitutes=tuple(_STANDARD_IDS), multiplier=3.0, color="#ff9d3d", glyph="⚡",
    ),
    "scatter": Symbol(
        "scatter", "神殿之门 Scatter", SymbolKind.SCATTER, scatter_pays={3: 1.58, 4: 6.3, 5: 26.26},
        color="#ffd9ec", glyph="🏛️",
    ),
    "totem": Symbol("totem", "雷石（选宝触发）", SymbolKind.BONUS, color="#8fe3ff", glyph="🗿"),
}

_BASE_WEIGHTS = [
    {"eagle": 6, "wolf": 7, "raven": 8, "spear": 9, "shield": 10, "rune": 11,
     "wild_x2": 2, "wild_x3": 1, "scatter": 2, "totem": 3},
    {"eagle": 6, "wolf": 7, "raven": 8, "spear": 9, "shield": 10, "rune": 11,
     "wild_x2": 2, "wild_x3": 1, "scatter": 2, "totem": 3},
    {"eagle": 6, "wolf": 7, "raven": 8, "spear": 9, "shield": 10, "rune": 11,
     "wild_x2": 3, "wild_x3": 1, "scatter": 3, "totem": 3},
    {"eagle": 7, "wolf": 7, "raven": 8, "spear": 9, "shield": 10, "rune": 10,
     "wild_x2": 2, "wild_x3": 1, "scatter": 2, "totem": 3},
    {"eagle": 6, "wolf": 7, "raven": 8, "spear": 9, "shield": 10, "rune": 11,
     "wild_x2": 2, "wild_x3": 1, "scatter": 2, "totem": 3},
]
_FREE_WEIGHTS = [
    {"eagle": 5, "wolf": 6, "raven": 7, "spear": 8, "shield": 8, "rune": 9,
     "wild_x2": 3, "wild_x3": 2, "scatter": 2, "totem": 2},
    {"eagle": 5, "wolf": 6, "raven": 7, "spear": 8, "shield": 8, "rune": 9,
     "wild_x2": 3, "wild_x3": 2, "scatter": 2, "totem": 2},
    {"eagle": 5, "wolf": 6, "raven": 7, "spear": 8, "shield": 8, "rune": 9,
     "wild_x2": 4, "wild_x3": 2, "scatter": 3, "totem": 2},
    {"eagle": 6, "wolf": 6, "raven": 7, "spear": 8, "shield": 8, "rune": 8,
     "wild_x2": 3, "wild_x3": 2, "scatter": 2, "totem": 2},
    {"eagle": 5, "wolf": 6, "raven": 7, "spear": 8, "shield": 8, "rune": 9,
     "wild_x2": 3, "wild_x3": 2, "scatter": 2, "totem": 2},
]


def build_config() -> GameConfig:
    return GameConfig(
        id=GAME_ID,
        name="雷霆神殿",
        description=(
            "5x3 北欧神殿：雷锤 Wild 自带 ×2 / ×3 倍率并在同一命中里相加，"
            "雷石 3 枚起开启「选雷石」Pick'em 奖励，神殿之门触发 10~20 次免费旋转。"
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
            multiplier_wild=MultiplierWildConfig(
                enabled=True,
                symbols={"wild_x2": 2.0, "wild_x3": 3.0},
                combine="sum",
                apply_to=["line", "ways"],
            ),
            pick_bonus=PickBonusConfig(
                enabled=True,
                trigger_symbol="totem",
                trigger_counts={3: 3, 4: 4, 5: 5},
                # 有放回抽取：奖品可重复，单次挑选的期望 ≈1.66x 总注
                prize_pool={"火花": 0.5, "雷石": 1.5, "雷霆": 4.0, "雷神之怒": 15.0},
                weights={"火花": 55, "雷石": 30, "雷霆": 12, "雷神之怒": 3},
                unique=False,
                award_multiplier=1.0,
            ),
            free_spins=FreeSpinsConfig(
                trigger_symbol="scatter",
                trigger_counts={3: 10, 4: 15, 5: 20},
                multiplier_progression=[1.0, 2.0, 3.0, 5.0],
                retrigger_counts={3: 5, 4: 8, 5: 12},
                reel_set="free",
            ),
        ),
        math=MathModel(
            target_rtp=0.965,
            volatility="high",
            max_win_multiplier=800.0,
            hit_frequency_target=0.30,
            rtp_tolerance=0.025,
        ),
        theme=Theme(
            id="thunder",
            name="雷霆神殿",
            cabinet_color="#1d2340",
            background="#080b18",
            accent="#ffd166",
            palette={
                "grid": "#141a33",
                "reel": "#1c2442",
                "win": "#ffd166",
                "wild": "#ffe066",
                "bonus": "#8fe3ff",
            },
        ),
    )


CONFIG = build_config()
