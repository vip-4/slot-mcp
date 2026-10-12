"""机台 1：幸运水果机 —— 3x3 / 5 线经典水果机，低波动 + 博彩。

核心机制
* 赔付模式：固定 5 线（`LINES_5_3x3`）
* 特殊符号：Wild（⭐）替代所有标准符号并自带最高赔付
* 特性：Gamble 二选一翻倍（最多 5 次，上限 1000x 总注）
* 目标：RTP 96% / 低波动 / 中奖金 multiplier 约 120x
"""

from __future__ import annotations

from ..engine.config import (
    BetConfig,
    Features,
    GameConfig,
    GambleConfig,
    MathModel,
    Paylines,
    ReelSet,
    Symbol,
    SymbolKind,
    Theme,
)
from ..engine.paylines import LINES_5_3x3

GAME_ID = "lucky_fruits"

_SYMBOLS = {
    "cherry": Symbol("cherry", "樱桃", SymbolKind.STANDARD, pays={2: 1, 3: 5}, color="#ff5570", glyph="🍒"),
    "lemon": Symbol("lemon", "柠檬", SymbolKind.STANDARD, pays={2: 1, 3: 8}, color="#ffe45c", glyph="🍋"),
    "watermelon": Symbol("watermelon", "西瓜", SymbolKind.STANDARD, pays={2: 2, 3: 11}, color="#5ad07a", glyph="🍉"),
    "plum": Symbol("plum", "李子", SymbolKind.STANDARD, pays={3: 19}, color="#b57cff", glyph="🍇"),
    "bell": Symbol("bell", "铃铛", SymbolKind.STANDARD, pays={3: 24}, color="#ffd166", glyph="🔔"),
    "seven": Symbol("seven", "幸运 7", SymbolKind.STANDARD, pays={3: 30}, color="#ff8c42", glyph="7️⃣"),
    "wild": Symbol(
        "wild",
        "幸运星 Wild",
        SymbolKind.WILD,
        pays={3: 60},
        substitutes=("cherry", "lemon", "watermelon", "plum", "bell", "seven"),
        color="#fffacd",
        glyph="⭐",
    ),
}

# 每轴权重（虚拟映射）：strip 列出参与的符号各一次，weights 决定出现占比
_STRIP_ORDER = ["cherry", "lemon", "watermelon", "plum", "bell", "seven", "wild"]
_WEIGHTS = [
    {"cherry": 6, "lemon": 5, "watermelon": 4, "plum": 3, "bell": 2, "seven": 1, "wild": 1},
    {"cherry": 5, "lemon": 5, "watermelon": 4, "plum": 3, "bell": 2, "seven": 1, "wild": 2},
    {"cherry": 6, "lemon": 5, "watermelon": 4, "plum": 3, "bell": 3, "seven": 1, "wild": 1},
]


def build_config() -> GameConfig:
    return GameConfig(
        id=GAME_ID,
        name="幸运水果机",
        description="3x3 经典水果机，低波动频繁小奖，中奖后可挑战红黑翻倍。",
        reels=3,
        rows=3,
        symbols=_SYMBOLS,
        reel_sets={
            "base": ReelSet(
                name="base",
                strips=[list(_STRIP_ORDER) for _ in range(3)],
                weights=[dict(w) for w in _WEIGHTS],
            )
        },
        base_reel_set="base",
        paylines=Paylines(rows=3, lines=[list(x) for x in LINES_5_3x3]),
        bet=BetConfig(steps=[0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0], default_index=3, max_total_bet=10.0),
        features=Features(
            gamble=GambleConfig(enabled=True, max_steps=5, max_win_multiplier=1000.0, win_probability=0.5)
        ),
        math=MathModel(
            target_rtp=0.96, volatility="low", max_win_multiplier=60.0, hit_frequency_target=0.75
        ),
        theme=Theme(
            id="retro_fruit",
            name="复古水果",
            cabinet_color="#7a1220",
            background="#20060a",
            accent="#ffcc33",
            palette={"grid": "#2a0a10", "reel": "#3d1420", "win": "#ffe98a"},
        ),
    )


CONFIG = build_config()
