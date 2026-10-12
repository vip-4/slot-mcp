"""MCP 工具集：把「SLOT 游戏 + Blender 渲染」能力暴露为标准化工具。

新增一台机台或一个参数并不需要改这里的代码——工具层只做三件事：
1. 把外部调用转发到 `GameRegistry` / `SlotSession` / `simulate`
2. 把结果统一序列化为 JSON（`to_dict()` 契约）
3. 把需要 3D 呈现的结果转发给 Blender 插件
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..engine.config import ConfigError, GameConfig, set_parameter
from ..engine.game import GameState, SlotMachine, get_registry
from ..engine.rng import SlotRNG
from ..engine.session import SlotSession
from ..engine.simulator import simulate

__all__ = ["TOOLS", "handle_tool", "SessionStore", "sessions"]


# --------------------------------------------------------------------------- 会话
class SessionStore:
    """进程内会话仓库。生产环境可替换为 Redis / DB 实现同样的接口。"""

    def __init__(self) -> None:
        self._sessions: Dict[str, SlotSession] = {}

    def create(
        self, session_id: str, game_id: str, credits: float = 1000.0, bet_index: Optional[int] = None
    ) -> SlotSession:
        machine = get_registry().get(game_id)
        session = SlotSession(machine, session_id=session_id, credits=credits, bet_index=bet_index)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> SlotSession:
        if session_id not in self._sessions:
            raise KeyError(f"未创建的会话: {session_id}")
        return self._sessions[session_id]

    def drop(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def ids(self) -> List[str]:
        return sorted(self._sessions)

    def restore(self, session_id: str, payload: Dict[str, Any]) -> SlotSession:
        """从快照恢复（含免费旋转余额等未完成状态）。"""
        game_id = payload["game_id"]
        session = self.create(session_id, game_id, credits=payload.get("credits", 1000.0))
        session.credits = float(payload.get("credits", 1000.0))
        if payload.get("bet_index") is not None:
            session.set_bet_index(int(payload["bet_index"]))
        session.restore_state(payload.get("state"))
        return session


sessions = SessionStore()


# --------------------------------------------------------------------------- 工具声明
TOOLS: List[Dict[str, Any]] = [
    {
        "name": "slot_list_games",
        "description": "列出全部已注册的 SLOT 机台及其核心参数（尺寸、线数、目标 RTP、启用的特性）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "slot_get_game",
        "description": "获取单台机台的完整信息：符号表、赔率表、赔付线/通路、下注档位、特性配置、主题。",
        "inputSchema": {
            "type": "object",
            "properties": {"game_id": {"type": "string"}},
            "required": ["game_id"],
        },
    },
    {
        "name": "slot_get_config",
        "description": "读取某台机台的原始配置（可只取子树）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "game_id": {"type": "string"},
                "path": {"type": "string", "description": "点号路径，如 features.free_spins"},
            },
            "required": ["game_id"],
        },
    },
    {
        "name": "slot_set_parameter",
        "description": "运行时调整配置参数（赔率、权重、触发次数等），可选落盘到 configs/ 目录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "game_id": {"type": "string"},
                "path": {"type": "string", "description": "如 symbols.gift.pays.5"},
                "value": {},
                "persist": {"type": "boolean", "default": False},
            },
            "required": ["game_id", "path", "value"],
        },
    },
    {
        "name": "slot_validate_config",
        "description": "校验机台配置是否合法（条带长度、赔付线越界、符号引用缺失等）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "game_id": {"type": "string"},
                "config": {"description": "可选的完整配置对象，不传则校验内置配置"},
            },
        },
    },
    {
        "name": "slot_spin",
        "description": "执行一次或多次旋转，返回网格、中奖明细、特性事件与结束后的状态机快照。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "game_id": {"type": "string"},
                "bet": {"type": "number", "default": 1.0},
                "lines": {"type": "integer", "default": 0, "description": "0 表示全部线"},
                "spins": {"type": "integer", "default": 1},
                "seed": {"description": "指定种子可复现同一局"},
                "state": {"type": "object", "description": "续用的状态机快照"},
            },
            "required": ["game_id"],
        },
    },
    {
        "name": "slot_simulate",
        "description": "蒙特卡洛仿真校核 RTP / 命中率 / 波动率 / 特性触发频率。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "game_id": {"type": "string"},
                "spins": {"type": "integer", "default": 100000},
                "bet": {"type": "number", "default": 1.0},
                "seed": {},
            },
            "required": ["game_id"],
        },
    },
    {
        "name": "slot_session_create",
        "description": "创建一个带余额的玩家会话（用于多轮自动扣币与免费旋转续玩）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "default": "default"},
                "game_id": {"type": "string"},
                "credits": {"type": "number", "default": 1000.0},
                "bet_index": {"type": "integer"},
            },
            "required": ["game_id"],
        },
    },
    {
        "name": "slot_session_spin",
        "description": "会话级别的旋转：自动扣注、入账，返回余额与完整旋转结果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "default": "default"},
                "bet": {"type": "number"},
                "bet_index": {"type": "integer"},
                "lines": {"type": "integer", "default": 0},
            },
        },
    },
    {
        "name": "slot_session_gamble",
        "description": "会话内的红黑博彩：choice=red|black，take=True 表示直接收下奖金。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "default": "default"},
                "choice": {"type": "string"},
                "take": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "slot_session_snapshot",
        "description": "导出会话快照（余额、状态机、历史），可用于持久化与故障恢复。",
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string", "default": "default"}},
        },
    },
    {
        "name": "blender_status",
        "description": "检查 Blender 插件桥接是否可用，并返回 Blender 版本与场景信息。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "blender_build_cabinet",
        "description": "按机台主题在 Blender 中搭建 3D 机台 Cabinet（含转轮条带材质占位）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "game_id": {"type": "string"},
                "scale": {"type": "number", "default": 1.0},
            },
            "required": ["game_id"],
        },
    },
    {
        "name": "blender_animate_spin",
        "description": "把一次旋转结果渲染为 Blender 动画（逐轴错峰停轮 + 中奖高亮）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "game_id": {"type": "string"},
                "spin": {"type": "object", "description": "slot_spin 返回的单个结果"},
                "session_id": {"type": "string"},
                "fps": {"type": "integer", "default": 24},
            },
        },
    },
    {
        "name": "blender_exec",
        "description": "在 Blender 中执行一段受控 Python 代码（需先安装并启用插件）。",
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
]


# --------------------------------------------------------------------------- 辅助
def _ok(text: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }
    if data is not None:
        payload["data"] = data
        payload["structuredContent"] = data
    return payload


def _fail(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _config_dir() -> Path:
    # 目录层级：.../src/slotmcp/mcp/tools.py → parents[3] 即工程根目录
    root = Path(os.getenv("SLOT_MCP_ROOT", Path(__file__).resolve().parents[3]))
    target = Path(os.getenv("SLOT_MCP_CONFIG_DIR", root / "configs"))
    target.mkdir(parents=True, exist_ok=True)
    return target


def _machine(game_id: str) -> SlotMachine:
    return get_registry().get(game_id)


def _resolve_spin_source(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """支持直接传结果对象，或从会话最近一次旋转取结果。"""
    if arguments.get("spin"):
        return arguments["spin"]
    session_id = arguments.get("session_id")
    if not session_id:
        raise KeyError("需要提供 spin 或 session_id")
    session = sessions.get(session_id)
    snapshot = session.snapshot()
    if not snapshot.last_result:
        raise KeyError("会话尚无旋转结果，请先调用 slot_session_spin")
    return snapshot.last_result.to_dict()


# --------------------------------------------------------------------------- 实现
def _list_games(_: Dict[str, Any], __: Any) -> Dict[str, Any]:
    registry = get_registry()
    games = registry.list_info()
    lines = []
    for game in games:
        lines.append(
            f"- {game['id']:<18} {game['name']:<10} {game['reels']}x{game['rows']} "
            f"{game['lines']}{' Ways' if game['pay_mode'] == 'ways' else ' 线'} "
            f"RTP={game['target_rtp']:.0%} {game['volatility']:<12} "
            f"特性: {', '.join(game['features']) or '无'}"
        )
    return _ok("已注册机台：\n" + "\n".join(lines), {"games": games})


def _get_game(args: Dict[str, Any], __: Any) -> Dict[str, Any]:
    info = _machine(args["game_id"]).info
    paytable = {
        sid: {"pays": sym["pays"], "scatter_pays": sym["scatter_pays"], "kind": sym["kind"]}
        for sid, sym in info["symbols"].items()
    }
    layout = []
    if info["pay_mode"] == "lines":
        machine = _machine(args["game_id"])
        layout = machine.payline_layout()
    return _ok(
        json.dumps(info, ensure_ascii=False, indent=2),
        {
            **info,
            "paytable": paytable,
            "paylines": layout,
            "features_detail": info.get("features"),
        },
    )


def _get_config(args: Dict[str, Any], __: Any) -> Dict[str, Any]:
    machine = _machine(args["game_id"])
    data = machine.config.to_dict()
    path = args.get("path")
    if path:
        node: Any = data
        for part in path.split("."):
            node = node[int(part)] if isinstance(node, list) else node[part]
        return _ok(json.dumps(node, ensure_ascii=False, indent=2), {"value": node})
    return _ok(json.dumps(data, ensure_ascii=False, indent=2), {"config": data})


def _set_parameter(args: Dict[str, Any], __: Any) -> Dict[str, Any]:
    game_id = args["game_id"]
    old_machine = _machine(game_id)
    cfg = old_machine.config.clone()
    set_parameter(cfg, args["path"], args["value"])
    errors = cfg.validate()
    if errors:
        return _fail("配置非法，已回滚：\n- " + "\n- ".join(errors))

    get_registry().register(cfg, replace=True)
    note = "已在内存中生效"
    if args.get("persist"):
        target = _config_dir() / f"{game_id}.json"
        target.write_text(cfg.to_json(), encoding="utf-8")
        note += f"，并写入 {target}"
    return _ok(
        f"{game_id} 的 {args['path']} 已更新为 {args['value']}（{note}）",
        {
            "game_id": game_id,
            "path": args["path"],
            "value": args["value"],
            "persisted": bool(args.get("persist")),
        },
    )


def _validate_config(args: Dict[str, Any], __: Any) -> Dict[str, Any]:
    if args.get("config"):
        cfg = GameConfig.from_dict(args["config"])
        label = args.get("game_id") or cfg.id or "<inline>"
    else:
        cfg = _machine(args["game_id"]).config
        label = args["game_id"]
    errors = cfg.validate()
    return _ok(
        f"{label} 校验通过" if not errors else f"{label} 存在 {len(errors)} 个问题",
        {"game_id": label, "valid": not errors, "errors": errors},
    )


def _spin(args: Dict[str, Any], __: Any) -> Dict[str, Any]:
    machine = _machine(args["game_id"])
    if args.get("seed") is not None:
        machine.rng = SlotRNG(args["seed"])
    state = GameState.from_dict(args["state"]) if args.get("state") else None

    results = []
    total_win = 0.0
    total_bet = 0.0
    spins = max(1, int(args.get("spins", 1)))
    bet = float(args.get("bet", 1.0))
    lines = int(args.get("lines", 0))
    for _ in range(spins):
        result = machine.spin(total_bet=bet, active_lines=lines, state=state)
        state = None  # 后续旋转沿用上一次结果里的状态机
        results.append(result.to_dict())
        total_win += result.total_win
        total_bet += result.total_bet
    summary = (
        f"{args['game_id']} 旋转 {spins} 次：总注 {total_bet:.2f}，"
        f"总返奖 {total_win:.2f}，本轮 RTP = {total_win / total_bet:.4f}"
        if total_bet
        else ""
    )
    return _ok(summary, {"spins": results, "total_bet": total_bet, "total_win": total_win})


def _simulate(args: Dict[str, Any], __: Any) -> Dict[str, Any]:
    machine = _machine(args["game_id"])
    report = simulate(
        machine,
        spins=int(args.get("spins", 100_000)),
        bet=float(args.get("bet", 1.0)),
        seed=args.get("seed"),
    )
    summary = (
        f"{report.game_id} 仿真 {report.spins} 局：RTP={report.rtp:.4f}"
        f"（目标 {report.target_rtp:.2f}，{'达标' if report.within_tolerance else '超标'}）"
        f" 基础 {report.base_rtp:.4f} / 特性 {report.feature_rtp:.4f}"
        f" 命中率 {report.hit_rate:.2%} 波动率 {report.volatility:.2f}"
        f" 最大 {report.max_win_multiplier:.1f}x"
    )
    return _ok(summary, report.to_dict())


def _session_create(args: Dict[str, Any], __: Any) -> Dict[str, Any]:
    session_id = args.get("session_id") or "default"
    session = sessions.create(
        session_id,
        args["game_id"],
        credits=float(args.get("credits", 1000.0)),
        bet_index=args.get("bet_index"),
    )
    return _ok(
        f"会话 {session_id} 已创建：{args['game_id']}，余额 {session.credits:.2f}",
        session.to_dict(),
    )


def _session_spin(args: Dict[str, Any], __: Any) -> Dict[str, Any]:
    session_id = args.get("session_id") or "default"
    if session_id not in sessions.ids():
        raise KeyError(f"会话不存在：{session_id}，请先调用 slot_session_create")
    session = sessions.get(session_id)
    if args.get("bet") is not None:
        bet_value = float(args["bet"])
        if bet_value not in session.bet_levels:
            session.set_bet_index(
                min(
                    range(len(session.bet_levels)),
                    key=lambda i: abs(session.bet_levels[i] - bet_value),
                )
            )
    if args.get("bet_index") is not None:
        session.set_bet_index(int(args["bet_index"]))
    result = session.spin(active_lines=int(args.get("lines", 0)))
    return _ok(
        f"{session.machine.config.name} 下注 {result.total_bet:.2f}，"
        f"中奖 {result.total_win:.2f}，余额 {session.credits:.2f}",
        {**session.to_dict(result), "result": result.to_dict()},
    )


def _session_gamble(args: Dict[str, Any], __: Any) -> Dict[str, Any]:
    session = sessions.get(args.get("session_id") or "default")
    if args.get("take"):
        outcome = session.take_gamble()
    else:
        outcome = session.gamble(args.get("choice", "red"))
    return _ok(json.dumps(outcome, ensure_ascii=False), outcome)


def _session_snapshot(args: Dict[str, Any], __: Any) -> Dict[str, Any]:
    session = sessions.get(args.get("session_id") or "default")
    return _ok(json.dumps(session.to_dict(), ensure_ascii=False), session.to_dict())


def _blender_status(_: Dict[str, Any], bridge: Any) -> Dict[str, Any]:
    if bridge is None:
        return _fail("未注入 Blender 桥接")
    status = bridge.status()
    return _ok(
        "Blender 已连接" if status.get("connected") else "Blender 未连接",
        status,
    )


def _blender_build_cabinet(args: Dict[str, Any], bridge: Any) -> Dict[str, Any]:
    if bridge is None:
        return _fail("未注入 Blender 桥接")
    machine = _machine(args["game_id"])
    payload = {
        "game_id": machine.config.id,
        "theme": machine.config.theme.to_dict(),
        "reels": machine.config.reels,
        "rows": machine.config.rows,
        "symbols": {k: v.to_dict() for k, v in machine.config.symbols.items()},
        "scale": float(args.get("scale", 1.0)),
    }
    result = bridge.request("build_cabinet", payload, timeout=30.0)
    return _ok(f"机台 {machine.config.id} 已在 Blender 中构建", result)


def _blender_animate_spin(args: Dict[str, Any], bridge: Any) -> Dict[str, Any]:
    if bridge is None:
        return _fail("未注入 Blender 桥接")
    if "spin" not in args and "session_id" in args:
        args = {**args, "spin": _resolve_spin_source(args)}
    spin = args.get("spin") or _resolve_spin_source(args)
    payload = {
        "game_id": args.get("game_id") or spin.get("game_id"),
        "spin": spin,
        "fps": int(args.get("fps", 24)),
        "theme": _machine(args.get("game_id") or spin["game_id"]).config.theme.to_dict(),
    }
    result = bridge.request("animate_spin", payload, timeout=60.0)
    return _ok("已在 Blender 中生成转轮动画", result)


def _blender_exec(args: Dict[str, Any], bridge: Any) -> Dict[str, Any]:
    if bridge is None:
        return _fail("未注入 Blender 桥接")
    result = bridge.request("exec", {"code": args["code"]}, timeout=60.0)
    return _ok("执行完成", result)


_HANDLERS: Dict[str, Callable[[Dict[str, Any], Any], Dict[str, Any]]] = {
    "slot_list_games": _list_games,
    "slot_get_game": _get_game,
    "slot_get_config": _get_config,
    "slot_set_parameter": _set_parameter,
    "slot_validate_config": _validate_config,
    "slot_spin": _spin,
    "slot_simulate": _simulate,
    "slot_session_create": _session_create,
    "slot_session_spin": _session_spin,
    "slot_session_gamble": _session_gamble,
    "slot_session_snapshot": _session_snapshot,
    "blender_status": _blender_status,
    "blender_build_cabinet": _blender_build_cabinet,
    "blender_animate_spin": _blender_animate_spin,
    "blender_exec": _blender_exec,
}


def handle_tool(name: str, arguments: Dict[str, Any], bridge: Any = None) -> Dict[str, Any]:
    """统一的分发入口；所有异常在这里收敛为结构化错误，保证 MCP 会话不中断。"""
    handler = _HANDLERS.get(name)
    if handler is None:
        return _fail(f"未知工具: {name}")
    try:
        return handler(arguments or {}, bridge)
    except KeyError as exc:
        return _fail(f"参数或资源缺失: {exc}")
    except ConfigError as exc:
        return _fail("配置非法：" + "; ".join(exc.errors))
    except ValueError as exc:
        return _fail(f"参数取值非法: {exc}")
    except Exception as exc:  # noqa: BLE001 - MCP 边界必须兜住所有异常
        return _fail(f"{type(exc).__name__}: {exc}")
