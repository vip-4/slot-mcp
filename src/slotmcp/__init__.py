"""Blender Slot MCP —— 多主题 SLOT 游戏合集。

分层结构::

    engine/  CONFIG 引擎（与具体机台无关的数学模型）
    games/   5 款机台的纯配置
    mcp/     MCP 服务层（stdio JSON-RPC 工具 + Blender 桥接）
    ui/      纯标准库 HTTP 服务，为前端提供 REST API

对外最常用入口::

    from slotmcp import get_registry, play

    registry = get_registry()
    result = registry.spin("candy_carnival", total_bet=1.0)
"""

from .engine import (
    GameConfig,
    GameRegistry,
    GameState,
    SlotMachine,
    SlotSession,
    SpinResult,
    get_registry,
    simulate,
)

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "GameConfig",
    "GameRegistry",
    "GameState",
    "SlotMachine",
    "SlotSession",
    "SpinResult",
    "get_registry",
    "simulate",
    "play",
]


def play(game_id: str, total_bet: float = 1.0, active_lines: int = 0, seed: int | str | None = None):
    """一行式调试入口：直接返回 `SpinResult`。"""
    machine = get_registry().get(game_id)
    if seed is not None:
        from .engine.rng import SlotRNG

        machine.rng = SlotRNG(seed)
    return machine.spin(total_bet=total_bet, active_lines=active_lines)
