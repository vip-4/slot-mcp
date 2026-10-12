"""内置 12 款 SLOT 机台。

新增机台只需两步：
1. 在本包下新建 `<game_id>.py`，实现 `build_config() -> GameConfig`（可导出 `CONFIG`）；
2. 在下方 `_BUILDERS` 中登记。

引擎侧不需要任何改动。
"""

from __future__ import annotations

from typing import Callable, Dict, Iterator, List

from ..engine.config import GameConfig

from . import (
    candy_carnival,
    colossal_ruins,
    dragon_palace,
    fortune_koi,
    frost_wolf,
    jungle_evolve,
    lucky_fruits,
    neon_twins,
    pharaoh_tomb,
    phoenix_rebirth,
    star_expedition,
    thunder_temple,
)

__all__ = [
    "build_config",
    "build_all",
    "iter_game_configs",
    "game_ids",
    "export_config_json",
    "candy_carnival",
    "colossal_ruins",
    "dragon_palace",
    "fortune_koi",
    "frost_wolf",
    "jungle_evolve",
    "lucky_fruits",
    "neon_twins",
    "pharaoh_tomb",
    "phoenix_rebirth",
    "star_expedition",
    "thunder_temple",
]

_BUILDERS: Dict[str, Callable[[], GameConfig]] = {
    lucky_fruits.GAME_ID: lucky_fruits.build_config,
    candy_carnival.GAME_ID: candy_carnival.build_config,
    dragon_palace.GAME_ID: dragon_palace.build_config,
    pharaoh_tomb.GAME_ID: pharaoh_tomb.build_config,
    star_expedition.GAME_ID: star_expedition.build_config,
    fortune_koi.GAME_ID: fortune_koi.build_config,
    thunder_temple.GAME_ID: thunder_temple.build_config,
    colossal_ruins.GAME_ID: colossal_ruins.build_config,
    phoenix_rebirth.GAME_ID: phoenix_rebirth.build_config,
    frost_wolf.GAME_ID: frost_wolf.build_config,
    neon_twins.GAME_ID: neon_twins.build_config,
    jungle_evolve.GAME_ID: jungle_evolve.build_config,
}


def game_ids() -> List[str]:
    return sorted(_BUILDERS)


def build_config(game_id: str) -> GameConfig:
    if game_id not in _BUILDERS:
        raise KeyError(f"未知机台: {game_id}（可用: {', '.join(game_ids())}）")
    return _BUILDERS[game_id]()


def build_all() -> Dict[str, GameConfig]:
    return {gid: builder() for gid, builder in _BUILDERS.items()}


def iter_game_configs() -> Iterator[GameConfig]:
    for gid in game_ids():
        yield _BUILDERS[gid]()


def export_config_json(indent: int = 2) -> str:
    """导出全部机台配置为 JSON 数组，便于落盘到 `configs/` 目录做版本管理。"""
    import json

    return json.dumps(
        [cfg.to_dict() for cfg in iter_game_configs()], ensure_ascii=False, indent=indent
    )
