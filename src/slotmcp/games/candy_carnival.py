"""机台 2：糖果狂欢 —— 5x3 / 20 线，中等波动，扩展 Wild + 重转。

核心机制
* 赔付模式：固定 20 线（`LINES_20_5x3`）
* 特殊符号：Wild（🌈）落在第 3 轴时整轴扩展为 Wild，并赠送 1 次锁轴重转
* Scatter（🧁）全盘计数直接赔付（2x/10x/50x 总注）
* 目标：RTP 96% / 中波动 / 最大约 1500x
"""

from __future__ import annotations

from ..engine.config import (
    BetConfig,
    CascadeConfig,
    ExpandingWildConfig,
    Features,
    GameConfig,
    MathModel,
    Paylines,
    ReelSet,
    Symbol,
    SymbolKind,
    Theme,
)
from ..engine.paylines import LINES_20_5x3

GAME_ID = "candy_carnival"

_STANDARD_IDS = ["lollipop", "candy", "donut", "choco", "cake", "gift"]

_SYMBOLS = {
    "lollipop": Symbol("lollipop", "棒棒糖", SymbolKind.STANDARD, pays={3: 2, 4: 7, 5: 17}, color="#ff8ab5", glyph="🍭"),
    "candy": Symbol("candy", "软糖", SymbolKind.STANDARD, pays={3: 2, 4: 9, 5: 21}, color="#9be7ff", glyph="🍬"),
    "donut": Symbol("donut", "甜甜圈", SymbolKind.STANDARD, pays={3: 3, 4: 10, 5: 25}, color="#ffb27a", glyph="🍩"),
    "choco": Symbol("choco", "巧克力", SymbolKind.STANDARD, pays={3: 3, 4: 12, 5: 34}, color="#a9714b", glyph="🍫"),
    "cake": Symbol("cake", "纸杯蛋糕", SymbolKind.STANDARD, pays={3: 4, 4: 17, 5: 42}, color="#ffd6e8", glyph="🍰"),
    "gift": Symbol("gift", "礼物盒", SymbolKind.STANDARD, pays={3: 7, 4: 25, 5: 67}, color="#ffe066", glyph="🎁"),
    "wild": Symbol(
        "wild",
        "彩虹 Wild",
        SymbolKind.WILD,
        pays={3: 7, 4: 25, 5: 67},
        substitutes=tuple(_STANDARD_IDS),
        color="#ffffff",
        glyph="🌈",
    ),
    "scatter": Symbol(
        "scatter", "糖果杯 Scatter", SymbolKind.SCATTER, scatter_pays={3: 2, 4: 10, 5: 50}, color="#ff70a6", glyph="🧁"
    ),
}

_STRIP_ORDER = [*_STANDARD_IDS, "wild", "scatter"]
_WEIGHTS = [
    {"lollipop": 6, "candy": 5, "donut": 4, "choco": 3, "cake": 2, "gift": 1, "wild": 1, "scatter": 1},
    {"lollipop": 6, "candy": 5, "donut": 4, "choco": 3, "cake": 2, "gift": 1, "wild": 2, "scatter": 1},
    {"lollipop": 6, "candy": 5, "donut": 4, "choco": 3, "cake": 2, "gift": 1, "wild": 2, "scatter": 1},
    {"lollipop": 6, "candy": 5, "donut": 4, "choco": 3, "cake": 2, "gift": 2, "wild": 1, "scatter": 1},
    {"lollipop": 6, "candy": 5, "donut": 4, "choco": 3, "cake": 2, "gift": 1, "wild": 1, "scatter": 1},
]


def build_config() -> GameConfig:
    return GameConfig(
        id=GAME_ID,
        name="糖果狂欢",
        description="5x3 甜品世界，彩虹 Wild 落到中间轴整列扩展并赠送一次锁轴重转。",
        reels=5,
        rows=3,
        symbols=_SYMBOLS,
        reel_sets={
            "base": ReelSet(
                name="base",
                strips=[list(_STRIP_ORDER) for _ in range(5)],
                weights=[dict(w) for w in _WEIGHTS],
            )
        },
        base_reel_set="base",
        paylines=Paylines(rows=3, lines=[list(x) for x in LINES_20_5x3]),
        bet=BetConfig(steps=[0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0], default_index=2, max_total_bet=20.0),
        features=Features(
            cascade=CascadeConfig(enabled=False),
            expanding_wild=ExpandingWildConfig(symbol="wild", reels=[2], respins=1),
        ),
        math=MathModel(
            target_rtp=0.96, volatility="medium", max_win_multiplier=60.0, hit_frequency_target=0.68
        ),
        theme=Theme(
            id="candy",
            name="糖果乐园",
            cabinet_color="#ff6f91",
            background="#2a0c2b",
            accent="#ffe066",
            palette={"grid": "#3d1039", "reel": "#64246b", "win": "#ffd6e8"},
        ),
    )


CONFIG = build_config()
