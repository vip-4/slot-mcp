"""机台 5：星际远征 —— 6x4 / 4096 Ways，级联雪崩 + 递增倍率 + 免费旋转。

核心机制
* 赔付模式：全盘 4096 Ways
* 级联：每次中奖后符号消失、上方补位继续结算，倍率按 1→2→3→…→10 递增并封顶
* Scatter（🌌）3/4/5/6 个赠送 8/12/16/25 次免费旋转，免费旋转内级联倍率不重置
* 免费旋转条带 `fs` 移除 Scatter 之外的高赔符号权重提升
* 目标：RTP 96% / 高波动 / 最大约 8000x
"""

from __future__ import annotations

from ..engine.config import (
    BetConfig,
    CascadeConfig,
    Features,
    FreeSpinsConfig,
    GameConfig,
    MathModel,
    PayMode,
    Paylines,
    ReelSet,
    Symbol,
    SymbolKind,
    Theme,
)

GAME_ID = "star_expedition"

_STANDARD_IDS = ["meteor", "comet", "satellite", "planet", "ufo", "rocket"]

_SYMBOLS = {
    "meteor": Symbol("meteor", "陨石", SymbolKind.STANDARD, pays={3: 22.5, 4: 70.0, 5: 230.0, 6: 691.0}, color="#c0c6d8", glyph="☄️"),
    "comet": Symbol("comet", "彗星", SymbolKind.STANDARD, pays={3: 32.0, 4: 92.0, 5: 322.0, 6: 922.0}, color="#9be7ff", glyph="💫"),
    "satellite": Symbol("satellite", "卫星", SymbolKind.STANDARD, pays={3: 36.5, 4: 116.0, 5: 414.0, 6: 1153.0}, color="#b7e4c7", glyph="🛰️"),
    "planet": Symbol("planet", "行星", SymbolKind.STANDARD, pays={3: 47.0, 4: 151.0, 5: 510.0, 6: 1478.0}, color="#ffa8d8", glyph="🪐"),
    "ufo": Symbol("ufo", "飞碟", SymbolKind.STANDARD, pays={3: 58.5, 4: 192.0, 5: 691.0, 6: 1979.0}, color="#a1f0e0", glyph="🛸"),
    "rocket": Symbol("rocket", "火箭", SymbolKind.STANDARD, pays={3: 83.5, 4: 255.0, 5: 922.0, 6: 2534.0}, color="#ffb27a", glyph="🚀"),
    "wild": Symbol(
        "wild",
        "星门 Wild",
        SymbolKind.WILD,
        pays={3: 83.5, 4: 255.0, 5: 922.0, 6: 2534.0},
        substitutes=tuple(_STANDARD_IDS),
        color="#ffffff",
        glyph="🌟",
    ),
    # Scatter 在级联机台里只作为免费旋转触发器，不额外派彩
    "scatter": Symbol("scatter", "黑洞 Scatter", SymbolKind.SCATTER, color="#c792ff", glyph="🌌"),
}

_STRIP_ORDER = [*_STANDARD_IDS, "wild", "scatter"]

# Scatter 权重刻意压到 1/70 左右：6x4 共 24 格，不控制会出现 1/10 触发的畸形频率
_BASE_WEIGHTS = [
    {"meteor": 13, "comet": 11, "satellite": 10, "planet": 8, "ufo": 6, "rocket": 4, "wild": 3, "scatter": 1},
    {"meteor": 13, "comet": 11, "satellite": 10, "planet": 8, "ufo": 6, "rocket": 4, "wild": 3, "scatter": 1},
    {"meteor": 13, "comet": 11, "satellite": 10, "planet": 9, "ufo": 6, "rocket": 5, "wild": 3, "scatter": 1},
    {"meteor": 13, "comet": 11, "satellite": 10, "planet": 9, "ufo": 6, "rocket": 5, "wild": 3, "scatter": 1},
    {"meteor": 13, "comet": 11, "satellite": 10, "planet": 8, "ufo": 6, "rocket": 5, "wild": 3, "scatter": 1},
    {"meteor": 13, "comet": 11, "satellite": 10, "planet": 8, "ufo": 6, "rocket": 4, "wild": 3, "scatter": 1},
]

_FS_WEIGHTS = [
    {"meteor": 12, "comet": 11, "satellite": 10, "planet": 9, "ufo": 7, "rocket": 5, "wild": 4, "scatter": 1},
    {"meteor": 12, "comet": 11, "satellite": 10, "planet": 9, "ufo": 7, "rocket": 5, "wild": 5, "scatter": 1},
    {"meteor": 12, "comet": 11, "satellite": 10, "planet": 9, "ufo": 7, "rocket": 5, "wild": 5, "scatter": 1},
    {"meteor": 12, "comet": 11, "satellite": 10, "planet": 9, "ufo": 7, "rocket": 5, "wild": 5, "scatter": 1},
    {"meteor": 12, "comet": 11, "satellite": 10, "planet": 9, "ufo": 7, "rocket": 5, "wild": 5, "scatter": 1},
    {"meteor": 12, "comet": 11, "satellite": 10, "planet": 9, "ufo": 7, "rocket": 5, "wild": 4, "scatter": 1},
]


def build_config() -> GameConfig:
    return GameConfig(
        id=GAME_ID,
        name="星际远征",
        description="6x4 / 4096 Ways 太空冒险，级联倍率不断攀升，免费旋转可实现超长连锁。",
        reels=6,
        rows=4,
        pay_mode=PayMode.WAYS,
        symbols=_SYMBOLS,
        reel_sets={
            "base": ReelSet(
                name="base",
                strips=[list(_STRIP_ORDER) for _ in range(6)],
                weights=[dict(w) for w in _BASE_WEIGHTS],
            ),
            "fs": ReelSet(
                name="fs",
                strips=[list(_STRIP_ORDER) for _ in range(6)],
                weights=[dict(w) for w in _FS_WEIGHTS],
            ),
        },
        base_reel_set="base",
        paylines=Paylines(rows=4, lines=[]),
        bet=BetConfig(steps=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0], default_index=1, max_total_bet=50.0),
        features=Features(
            cascade=CascadeConfig(
                enabled=True,
                multiplier_step=1.0,
                multiplier_cap=10.0,
                reset_each_free_spin=True,
            ),
            free_spins=FreeSpinsConfig(
                trigger_symbol="scatter",
                trigger_counts={3: 8, 4: 12, 5: 16, 6: 25},
                multiplier_progression=[1, 1, 2, 3, 4, 5, 6, 8, 10],
                retrigger_counts={3: 4, 4: 6, 5: 10, 6: 20},
                reel_set="fs",
            ),
        ),
        math=MathModel(
            target_rtp=0.96, volatility="high", max_win_multiplier=2000.0, hit_frequency_target=0.81
        ),
        theme=Theme(
            id="space",
            name="深空远征",
            cabinet_color="#1b2a6b",
            background="#05060f",
            accent="#7cf6c8",
            palette={"grid": "#0a0f2b", "reel": "#141f4a", "win": "#9be7ff"},
        ),
    )


CONFIG = build_config()
