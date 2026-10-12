"""机台 4：法老之墓 —— 5x3 / 243 Ways，Hold & Win 宝箱重转 + 四档奖池。

核心机制
* 赔付模式：全盘 243 Ways（从左至右相邻轴计数，赔率单位为「每通路注」）
* BONUS 符号（🪙 金币）不参与 Ways 结算，仅用于触发 Hold & Win
* 全盘出现 ≥8 个金币类符号进入宝箱重转：锁定已有符号，3 次重转计数，
  每次出现新符号重置计数；未命中格从 `prize_symbols` 池按 `hit_probability` 补位
* JACKPOT 符号（MINI / MINOR / MAJOR）按 jackpots 表赔付，铺满 15 格额外派发全屏大奖
* 目标：RTP 96% / 中高波动 / 最大约 3000x
"""

from __future__ import annotations

from ..engine.config import (
    BetConfig,
    Features,
    GameConfig,
    HoldWinConfig,
    MathModel,
    PayMode,
    Paylines,
    ReelSet,
    Symbol,
    SymbolKind,
    Theme,
)

GAME_ID = "pharaoh_tomb"

_STANDARD_IDS = ["ankh", "eye", "scarab", "cat", "pharaoh"]

_SYMBOLS = {
    "ankh": Symbol("ankh", "生命符", SymbolKind.STANDARD, pays={3: 23.5, 4: 117.0, 5: 465.0}, color="#ffe0a3", glyph="☥"),
    "eye": Symbol("eye", "荷鲁斯之眼", SymbolKind.STANDARD, pays={3: 27.8, 4: 141.0, 5: 557.0}, color="#8ecbff", glyph="👁"),
    "scarab": Symbol("scarab", "圣甲虫", SymbolKind.STANDARD, pays={3: 37.4, 4: 187.0, 5: 699.0}, color="#7cf6c8", glyph="🪲"),
    "cat": Symbol("cat", "巴斯特猫", SymbolKind.STANDARD, pays={3: 46.1, 4: 233.0, 5: 931.0}, color="#ffb3c7", glyph="🐈"),
    "pharaoh": Symbol("pharaoh", "法老面具", SymbolKind.STANDARD, pays={3: 69.6, 4: 350.0, 5: 1395.0}, color="#ffd166", glyph="👑"),
    "wild": Symbol(
        "wild",
        "阿努比斯 Wild",
        SymbolKind.WILD,
        pays={3: 69.6, 4: 350.0, 5: 1395.0},
        substitutes=tuple(_STANDARD_IDS),
        color="#c792ff",
        glyph="🐺",
    ),
    "coin": Symbol("coin", "法老金币", SymbolKind.BONUS, color="#ffd700", glyph="🪙"),
    "mini": Symbol("mini", "MINI 奖池", SymbolKind.JACKPOT, color="#9be564", glyph="🟢"),
    "minor": Symbol("minor", "MINOR 奖池", SymbolKind.JACKPOT, color="#5ad2ff", glyph="🔵"),
    "major": Symbol("major", "MAJOR 奖池", SymbolKind.JACKPOT, color="#c792ff", glyph="🟣"),
}

_STRIP_ORDER = [*_STANDARD_IDS, "wild", "coin", "mini", "minor", "major"]

# 金币类符号整体权重：coin 占绝大多数，jackpot 极稀有
_WEIGHTS = [
    {"ankh": 9, "eye": 8, "scarab": 6, "cat": 5, "pharaoh": 3, "wild": 2, "coin": 6, "mini": 1, "minor": 1, "major": 1},
    {"ankh": 9, "eye": 8, "scarab": 6, "cat": 5, "pharaoh": 3, "wild": 2, "coin": 6, "mini": 1, "minor": 1, "major": 1},
    {"ankh": 9, "eye": 8, "scarab": 6, "cat": 5, "pharaoh": 3, "wild": 3, "coin": 6, "mini": 1, "minor": 1, "major": 1},
    {"ankh": 9, "eye": 8, "scarab": 6, "cat": 5, "pharaoh": 4, "wild": 2, "coin": 6, "mini": 1, "minor": 1, "major": 1},
    {"ankh": 9, "eye": 8, "scarab": 6, "cat": 5, "pharaoh": 3, "wild": 2, "coin": 6, "mini": 1, "minor": 1, "major": 1},
]

_FILLERS = ["ankh", "eye", "scarab", "cat"]


def build_config() -> GameConfig:
    return GameConfig(
        id=GAME_ID,
        name="法老之墓",
        description="5x3 / 243 Ways 埃及探险，收集金币进入宝箱重转，冲击 MINI~MAJOR 奖池与全屏大奖。",
        reels=5,
        rows=3,
        pay_mode=PayMode.WAYS,
        symbols=_SYMBOLS,
        reel_sets={
            "base": ReelSet(
                name="base",
                strips=[list(_STRIP_ORDER) for _ in range(5)],
                weights=[dict(w) for w in _WEIGHTS],
            )
        },
        base_reel_set="base",
        paylines=Paylines(rows=3, lines=[]),
        bet=BetConfig(steps=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0], default_index=1, max_total_bet=20.0),
        features=Features(
            hold_win=HoldWinConfig(
                trigger_symbol="coin",
                trigger_count=8,
                respins=3,
                prize_symbols=["coin"] * 8 + ["mini", "minor", "major"],
                jackpot_symbols=["mini", "minor", "major"],
                prizes={"coin": 0.9},
                jackpots={"mini": 7.8, "minor": 19.8, "major": 64.4},
                filler_symbols=_FILLERS,
                hit_probability=0.09,
                full_grid_bonus=207.0,
            )
        ),
        math=MathModel(
            target_rtp=0.96, volatility="medium-high", max_win_multiplier=1500.0, hit_frequency_target=0.50
        ),
        theme=Theme(
            id="egypt",
            name="金字塔秘境",
            cabinet_color="#7a5c14",
            background="#150f04",
            accent="#ffd166",
            palette={"grid": "#231a08", "reel": "#3b2c0e", "win": "#ffe066"},
        ),
    )


CONFIG = build_config()
