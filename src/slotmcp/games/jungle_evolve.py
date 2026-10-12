"""机台 12：丛林进化 —— 5x3 / 20 线，中高波动，级联 + 符号升级（Symbol Upgrade）。

核心机制（全部由 CONFIG 描述，引擎无分支）
---------------------------------------------
* **赔付模式**：固定 20 线（`LINES_20_5x3`），线注 = 总注 / 20
* **级联**（`cascade`）：命中消除后上方符号坠落补位，倍率逐级递增（步 1、上限 5）
* **符号升级**（`symbol_upgrade`）：参与命中的符号沿阶梯升一档并**保留在屏上**，
  下一轮级联以更高赔付继续结算 —— 阶梯为
  🌱种子 → 🌿嫩芽 → 🍃藤蔓 → 🌸花朵 → 🐆猛兽 → 👑兽王
  升到顶端（兽王）后才参与消除补位，因此单次旋转可能出现连续的「进化链」
* **免费旋转**（`free_spins`）：遗迹 Scatter 3/4/5 枚 → 8/12/16 次，倍率递进 [1,2,3]
* **目标**：RTP 96.5% / 中高波动 / 最大约 700x

调参入口：`slot_set_parameter`，例如
`features.symbol_upgrade.ladder.beast`、`features.cascade.multiplier_cap`。
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
    SymbolUpgradeConfig,
    Theme,
)
from ..engine.paylines import LINES_20_5x3

GAME_ID = "jungle_evolve"

_STANDARD_IDS = ["seed", "sprout", "vine", "bloom", "beast", "king"]

_SYMBOLS = {
    "seed": Symbol("seed", "种子", SymbolKind.STANDARD, pays={3: 0.55, 4: 1.86, 5: 4.64}, color="#b08968", glyph="🌱"),
    "sprout": Symbol("sprout", "嫩芽", SymbolKind.STANDARD, pays={3: 0.84, 4: 2.78, 5: 7.43}, color="#7cf6c8", glyph="🌿"),
    "vine": Symbol("vine", "藤蔓", SymbolKind.STANDARD, pays={3: 1.2, 4: 4.08, 5: 11.13}, color="#4caf50", glyph="🍃"),
    "bloom": Symbol("bloom", "花朵", SymbolKind.STANDARD, pays={3: 1.67, 4: 5.57, 5: 15.77}, color="#ff9ec4", glyph="🌸"),
    "beast": Symbol("beast", "猛兽", SymbolKind.STANDARD, pays={3: 2.32, 4: 7.88, 5: 22.27}, color="#ffd45c", glyph="🐆"),
    "king": Symbol("king", "兽王", SymbolKind.STANDARD, pays={3: 3.25, 4: 11.13, 5: 31.54}, color="#ff8c42", glyph="👑"),
    "wild": Symbol(
        "wild",
        "图腾 Wild",
        SymbolKind.WILD,
        pays={3: 3.71, 4: 12.98, 5: 37.11},
        substitutes=tuple(_STANDARD_IDS),
        color="#f0f8ff",
        glyph="🗿",
    ),
    "scatter": Symbol(
        "scatter", "遗迹 Scatter", SymbolKind.SCATTER, scatter_pays={3: 1.39, 4: 5.57, 5: 20.41}, color="#c6a4ff", glyph="🏛️"
    ),
}

_ORDER = [*_STANDARD_IDS, "wild", "scatter"]

_BASE_WEIGHTS = [
    {"seed": 20, "sprout": 18, "vine": 16, "bloom": 13, "beast": 10, "king": 7, "wild": 3, "scatter": 3},
    {"seed": 20, "sprout": 18, "vine": 16, "bloom": 13, "beast": 10, "king": 8, "wild": 3, "scatter": 3},
    {"seed": 20, "sprout": 18, "vine": 16, "bloom": 14, "beast": 11, "king": 8, "wild": 4, "scatter": 3},
    {"seed": 20, "sprout": 18, "vine": 17, "bloom": 14, "beast": 11, "king": 8, "wild": 3, "scatter": 3},
    {"seed": 20, "sprout": 18, "vine": 16, "bloom": 13, "beast": 10, "king": 7, "wild": 3, "scatter": 3},
]
# 免费旋转：高档符号更密，配合级联 + 升级形成进化链
_FREE_WEIGHTS = [
    {"seed": 16, "sprout": 16, "vine": 16, "bloom": 14, "beast": 12, "king": 9, "wild": 5, "scatter": 3},
    {"seed": 16, "sprout": 16, "vine": 16, "bloom": 14, "beast": 12, "king": 10, "wild": 5, "scatter": 3},
    {"seed": 16, "sprout": 16, "vine": 17, "bloom": 15, "beast": 13, "king": 10, "wild": 6, "scatter": 3},
    {"seed": 16, "sprout": 16, "vine": 17, "bloom": 15, "beast": 13, "king": 10, "wild": 5, "scatter": 3},
    {"seed": 16, "sprout": 16, "vine": 16, "bloom": 14, "beast": 12, "king": 9, "wild": 5, "scatter": 3},
]


def build_config() -> GameConfig:
    return GameConfig(
        id=GAME_ID,
        name="丛林进化",
        description=(
            "5x3 丛林进化主题：命中的符号会沿「种子 → 嫩芽 → 藤蔓 → 花朵 → 猛兽 → 兽王」阶梯升一档"
            "并保留在屏上，配合级联倍率递增形成连续的进化链；遗迹触发 8~16 次免费旋转。"
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
            cascade=CascadeConfig(enabled=True, multiplier_step=1.0, multiplier_cap=5.0),
            symbol_upgrade=SymbolUpgradeConfig(
                enabled=True,
                ladder={
                    "seed": "sprout",
                    "sprout": "vine",
                    "vine": "bloom",
                    "bloom": "beast",
                    "beast": "king",
                },
                phases=["base", "free_spins"],
                require_cascade=True,
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
            max_win_multiplier=700.0,
            hit_frequency_target=0.32,
            rtp_tolerance=0.025,
        ),
        theme=Theme(
            id="jungle",
            name="丛林进化",
            cabinet_color="#123021",
            background="#07160d",
            accent="#7cf6c8",
            palette={
                "grid": "#193d24",
                "reel": "#1f4a2c",
                "win": "#ffd45c",
                "wild": "#f0f8ff",
                "bonus": "#c6a4ff",
            },
        ),
    )


CONFIG = build_config()
