"""Blender 端插件：SLOT MCP Bridge

安装
----
Blender → 编辑 → 偏好设置 → 附加组件 → 安装… → 选择本文件 → 勾选启用。
启用后在 3D 视图右侧 N 面板出现 `SLOT` 标签页，点击「启动桥接」即可。

职责
----
* 在本地回环地址开启 TCP 服务（默认 `127.0.0.1:8765`），接收来自 MCP 服务端的指令
* 所有会改动 Blender 数据的操作都在**主线程**执行（通过 `bpy.app.timers` 消费队列），
  避免多线程直接操作 depsgraph 引发崩溃
* 支持 `ping / status / build_cabinet / animate_spin / exec` 五类指令

安全边界
--------
* 只监听 127.0.0.1，不对外暴露
* `exec` 指令可在面板中一键关闭；关闭后任何代码都不会被执行
"""

from __future__ import annotations

import contextlib
import io
import json
import queue
import socket
import struct
import threading
import time
from typing import Any, Dict, Optional

import bpy
import bpy.types

bl_info = {
    "name": "Slot MCP Bridge",
    "author": "Blender Slot MCP",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > SLOT",
    "description": "接收 MCP 服务端指令，构建并老虎机机台与转轮动画",
    "category": "Object",
}

DEFAULT_PORT = 8765
MAX_FRAME = 32 * 1024 * 1024

_STATE: Dict[str, Any] = {
    "server": None,
    "queue": queue.Queue(),
    "running": False,
    "last_error": "",
}

_SLOT_COLLECTION = "Slot_Machines"


# --------------------------------------------------------------------------- 帧协议
def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            return b""
        chunks.extend(chunk)
    return bytes(chunks)


def _send_json(sock: socket.socket, payload: Dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        sock.sendall(struct.pack(">I", len(raw)) + raw)
    except OSError:
        pass


def _read_request(sock: socket.socket) -> Optional[Dict[str, Any]]:
    header = _recv_exact(sock, 4)
    if not header:
        return None
    (length,) = struct.unpack(">I", header)
    if length <= 0 or length > MAX_FRAME:
        return None
    body = _recv_exact(sock, length)
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------- 服务端线程
class _BridgeServer(threading.Thread):
    def __init__(self, host: str, port: int):
        super().__init__(name="slot-bridge-server", daemon=True)
        self.host = host
        self.port = port
        self._sock: Optional[socket.socket] = None

    def run(self) -> None:
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(8)
            self._sock = server
        except OSError as exc:
            _STATE["last_error"] = f"监听失败: {exc}"
            _STATE["running"] = False
            return

        _STATE["running"] = True
        while _STATE["running"]:
            try:
                conn, _addr = server.accept()
            except OSError:
                break
            handler = threading.Thread(
                target=self._serve_connection, args=(conn,), daemon=True
            )
            handler.start()

    def _serve_connection(self, conn: socket.socket) -> None:
        with conn:
            while _STATE["running"]:
                request = _read_request(conn)
                if request is None:
                    return
                event = threading.Event()
                item = {
                    "id": request.get("id"),
                    "op": request.get("op"),
                    "params": request.get("params") or {},
                    "event": event,
                    "result": None,
                    "error": None,
                }
                _STATE["queue"].put(item)
                if not event.wait(timeout=120):
                    _send_json(
                        conn,
                        {"id": item["id"], "ok": False, "result": None, "error": "处理超时"},
                    )
                    continue
                _send_json(
                    conn,
                    {
                        "id": item["id"],
                        "ok": item["error"] is None,
                        "result": item["result"],
                        "error": item["error"],
                    },
                )

    def stop(self) -> None:
        _STATE["running"] = False
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


# --------------------------------------------------------------------------- 命令执行（主线程）
def _ensure_collection() -> bpy.types.Collection:
    collection = bpy.data.collections.get(_SLOT_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(_SLOT_COLLECTION)
        bpy.context.scene.collection.children.link(collection)
    return collection


def _material_for(name: str, color_hex: str) -> bpy.types.Material:
    material = bpy.data.materials.get(name)
    if material is not None:
        return material
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = _hex_to_rgba(color_hex)
    return material


def _hex_to_rgba(value: str) -> tuple:
    text = (value or "#ffffff").lstrip("#")
    if len(text) == 6:
        r, g, b = (int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
        return (r, g, b, 1.0)
    return (1.0, 1.0, 1.0, 1.0)


def _clear_slot(name: str) -> None:
    target = bpy.data.objects.get(name)
    if target is None:
        return
    for child in list(target.children):
        bpy.data.objects.remove(child, do_unlink=True)
    bpy.data.objects.remove(target, do_unlink=True)


def op_ping(params: Dict[str, Any]) -> Dict[str, Any]:
    return {"pong": True, "time": time.time()}


def op_status(params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "blender": bpy.app.version_string,
        "scene": bpy.context.scene.name,
        "objects": len(bpy.data.objects),
        "collections": [c.name for c in bpy.data.collections],
        "exec_allowed": bool(getattr(bpy.context.scene, "slot_allow_exec", False)),
    }


def op_build_cabinet(params: Dict[str, Any]) -> Dict[str, Any]:
    """按主题搭建机台：底座 + 屏幕背板 + 每轴的符号格子（用于后续动画）。"""
    game_id = params.get("game_id", "slot")
    theme = params.get("theme") or {}
    reels = int(params.get("reels", 5))
    rows = int(params.get("rows", 3))
    scale = float(params.get("scale", 1.0))
    symbols = params.get("symbols") or {}

    collection = _ensure_collection()
    root_name = f"Slot_{game_id}"
    _clear_slot(root_name)

    root = bpy.data.objects.new(root_name, None)
    collection.objects.link(root)

    cabinet = _box(f"{root_name}_Cabinet", theme.get("cabinet_color", "#20143a"))
    cabinet.scale = (reels * 1.2 * scale, rows * 1.1 * scale, 0.6 * scale)
    cabinet.location = (0.0, 0.0, -rows * 0.55 * scale)
    cabinet.parent = root
    collection.objects.link(cabinet)

    screen = _plane(f"{root_name}_Screen", theme.get("background", "#0b0714"))
    screen.scale = (reels * 1.05 * scale, rows * 0.95 * scale, 1.0)
    screen.location = (0.0, 0.2 * scale, 0.0)
    screen.parent = root
    collection.objects.link(screen)

    visible_cells = rows + 2  # 多两格用于滚动时的填充
    for reel_index in range(reels):
        reel_empty = bpy.data.objects.new(f"{root_name}_Reel{reel_index}", None)
        reel_empty.location = ((reel_index - (reels - 1) / 2) * 1.2 * scale, 0.0, 0.0)
        reel_empty.parent = root
        collection.objects.link(reel_empty)

        for row in range(visible_cells):
            symbol_id, color = _pick_symbol(symbols, reel_index, row)
            cell = _box(f"{root_name}_C{reel_index}_{row}", color)
            cell.scale = (0.42 * scale, 1.0 * scale, 0.42 * scale)
            cell.location = (0.0, 0.0, (rows / 2 - row) * 1.0 * scale)
            cell.parent = reel_empty
            cell["slot_symbol"] = symbol_id
            collection.objects.link(cell)

    bpy.context.view_layer.update()
    return {
        "game_id": game_id,
        "root": root_name,
        "reels": reels,
        "rows": rows,
        "cells_per_reel": visible_cells,
        "scale": scale,
    }


def _pick_symbol(symbols: Dict[str, Any], reel_index: int, row: int) -> tuple:
    if not symbols:
        return ("blank", "#202020")
    keys = sorted(symbols)
    symbol_id = keys[(reel_index * 7 + row) % len(keys)]
    info = symbols[symbol_id] or {}
    return (symbol_id, info.get("color", "#cccccc"))


def _box(name: str, color: str) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(_material_for(f"MAT_{name}", color))
    return obj


def _plane(name: str, color: str) -> bpy.types.Object:
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, 0.0, 0.0))
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(_material_for(f"MAT_{name}", color))
    return obj


def op_animate_spin(params: Dict[str, Any]) -> Dict[str, Any]:
    """把一次旋转结果做成逐轴错峰停轮动画。"""
    spin = params.get("spin") or {}
    game_id = params.get("game_id") or spin.get("game_id") or "slot"
    fps = int(params.get("fps", 24))
    steps = spin.get("steps") or []
    if not steps:
        raise ValueError("spin.steps 为空，无法生成动画")

    root_name = f"Slot_{game_id}"
    root = bpy.data.objects.get(root_name)
    if root is None:
        raise RuntimeError(f"场景中没有 {root_name}，请先调用 build_cabinet")

    scene = bpy.context.scene
    scene.render.fps = fps
    frame_start = scene.frame_start
    start = 1
    scene.frame_start = start
    cursor = start

    last_grid = steps[-1]["grid"]
    reels = len(last_grid)
    rows = len(last_grid[0]) if reels else 0

    for reel_index in range(reels):
        reel_empty = bpy.data.objects.get(f"{root_name}_Reel{reel_index}")
        if reel_empty is None:
            continue
        stop_frame = cursor + 8 + reel_index * 6
        reel_empty.animation_data_clear()
        reel_empty.rotation_euler = (0.0, 0.0, 0.0)
        reel_empty.keyframe_insert(data_path="rotation_euler", frame=start)
        total_turns = 3 + reel_index
        angle = total_turns * 2 * 3.141592653589793
        reel_empty.rotation_euler = (angle, 0.0, 0.0)
        reel_empty.keyframe_insert(data_path="rotation_euler", frame=stop_frame)
        cursor = stop_frame

    # 最终网格：把可见格子的颜色与符号 ID 写回物体自定义属性
    for reel_index, column in enumerate(last_grid):
        for row, symbol_id in enumerate(column):
            cell = bpy.data.objects.get(f"{root_name}_C{reel_index}_{row}")
            if cell is None:
                continue
            cell["slot_symbol"] = symbol_id
            color = _symbol_color(params, symbol_id)
            cell.data.materials.clear()
            cell.data.materials.append(_material_for(f"MAT_{symbol_id}", color))

    # 特性高亮：把事件命中的格子单独上色，便于在 Blender 里一眼看到
    # 随机 Wild 落点 / 被收集的金币 / 扩展 Wild / Hold & Win 锁定格
    highlights = _apply_highlights(params, steps, last_grid, root_name)

    scene.frame_end = max(cursor + 12, getattr(scene, "frame_end", cursor + 12))
    _ = frame_start  # 保持接口稳定，不做额外处理
    return {
        "game_id": game_id,
        "frame_start": start,
        "frame_end": int(scene.frame_end),
        "reels": reels,
        "rows": rows,
        "steps": len(steps),
        "highlights": highlights,
    }


# 事件类型 -> 高亮用途（只挑有明确落点的事件，其余保持原样）
_EVENT_KINDS = ("random_wild", "collect", "expanding_wild", "hold_win")


def _apply_highlights(
    params: Dict[str, Any], steps: Any, last_grid: Any, root_name: str
) -> Dict[str, int]:
    """把各步骤事件涉及的格子打上 `slot_event` 标记并换成高亮材质。"""
    theme = params.get("theme") or {}
    accent = theme.get("accent") or "#ffd45c"
    counts: Dict[str, int] = {}

    for step in steps or []:
        for ev in step.get("events") or []:
            kind = ev.get("type")
            if kind not in _EVENT_KINDS:
                continue
            positions = ev.get("positions") or []
            if kind == "collect":
                # 收集事件只带金币数量，落点用中奖位置（WinEvent.positions）表达
                for win in step.get("wins") or []:
                    if win.get("kind") == "collect":
                        positions = list(positions) + list(win.get("positions") or [])
            for pos in positions:
                if not isinstance(pos, (list, tuple)) or len(pos) != 2:
                    continue
                cell = bpy.data.objects.get(f"{root_name}_C{int(pos[0])}_{int(pos[1])}")
                if cell is None:
                    continue
                cell["slot_event"] = kind
                cell.data.materials.clear()
                cell.data.materials.append(_material_for(f"MAT_EV_{kind}", accent))
                counts[kind] = counts.get(kind, 0) + 1
    return counts


def _symbol_color(params: Dict[str, Any], symbol_id: str) -> str:
    symbols = params.get("theme", {}).get("palette") or {}
    if symbol_id in symbols:
        return symbols[symbol_id]
    return "#ffffff"


def op_exec(params: Dict[str, Any]) -> Dict[str, Any]:
    code = params.get("code", "")
    if not getattr(bpy.context.scene, "slot_allow_exec", False):
        raise PermissionError("exec 指令已被禁用（可在 SLOT 面板开启）")
    if not code.strip():
        raise ValueError("code 为空")
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            exec(compile(code, "<slot-mcp>", "exec"), {"bpy": bpy, "json": json})  # noqa: S102
    except Exception as exc:  # noqa: BLE001 - 需要把异常回传给调用方
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
    return {"stdout": buffer.getvalue()}


_OPERATIONS = {
    "ping": op_ping,
    "status": op_status,
    "build_cabinet": op_build_cabinet,
    "animate_spin": op_animate_spin,
    "exec": op_exec,
}


def _process_queue() -> Optional[float]:
    """主线程定时器回调：消费队列并执行（保证线程安全）。"""
    while True:
        try:
            item = _STATE["queue"].get_nowait()
        except queue.Empty:
            break
        handler = _OPERATIONS.get(item["op"])
        try:
            if handler is None:
                raise KeyError(f"未知指令: {item['op']}")
            item["result"] = handler(item["params"])
        except Exception as exc:  # noqa: BLE001
            item["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            item["event"].set()
    return 0.1 if _STATE["running"] else None


# --------------------------------------------------------------------------- 操作符 / 面板
class SLOT_OT_start_bridge(bpy.types.Operator):
    bl_idname = "slot.start_bridge"
    bl_label = "启动桥接"
    bl_description = "在 127.0.0.1 上启动 SLOT MCP 桥接服务"

    def execute(self, context):  # noqa: D102
        if _STATE["running"]:
            self.report({"INFO"}, "桥接已在运行")
            return {"FINISHED"}
        port = int(getattr(context.scene, "slot_port", DEFAULT_PORT) or DEFAULT_PORT)
        _STATE["last_error"] = ""
        _STATE["server"] = _BridgeServer("127.0.0.1", port)
        _STATE["server"].start()
        bpy.app.timers.register(_process_queue, first_interval=0.05, persistent=True)
        self.report({"INFO"}, f"桥接已启动：127.0.0.1:{port}")
        return {"FINISHED"}


class SLOT_OT_stop_bridge(bpy.types.Operator):
    bl_idname = "slot.stop_bridge"
    bl_label = "停止桥接"
    bl_description = "停止 SLOT MCP 桥接服务"

    def execute(self, context):  # noqa: D102
        server = _STATE.get("server")
        if server is not None:
            server.stop()
        _STATE["server"] = None
        _STATE["running"] = False
        self.report({"INFO"}, "桥接已停止")
        return {"FINISHED"}


class SLOT_PT_panel(bpy.types.Panel):
    bl_label = "SLOT MCP"
    bl_idname = "SLOT_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SLOT"

    def draw(self, context):  # noqa: D102
        layout = self.layout
        layout.prop(context.scene, "slot_port")
        layout.prop(context.scene, "slot_allow_exec")
        layout.operator("slot.start_bridge")
        layout.operator("slot.stop_bridge")
        layout.separator()
        layout.label(text="运行中" if _STATE["running"] else "已停止")
        if _STATE["last_error"]:
            layout.label(text=_STATE["last_error"], icon="ERROR")


_CLASSES = (SLOT_OT_start_bridge, SLOT_OT_stop_bridge, SLOT_PT_panel)


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.slot_port = bpy.props.IntProperty(
        name="端口", default=DEFAULT_PORT, min=1024, max=65535
    )
    bpy.types.Scene.slot_allow_exec = bpy.props.BoolProperty(
        name="允许远程执行代码", default=False
    )


def unregister() -> None:
    server = _STATE.get("server")
    if server is not None:
        server.stop()
    _STATE["server"] = None
    _STATE["running"] = False
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.slot_allow_exec
    del bpy.types.Scene.slot_port


if __name__ == "__main__":
    register()
