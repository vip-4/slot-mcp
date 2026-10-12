"""Web UI 后端：纯标准库 HTTP 服务，为前端提供 REST API 并托管静态资源。

不引入任何第三方依赖，保证 `pip install -e .` 之后即可运行；
同时刻意与 MCP 工具层共用同一份 `SessionStore`，两边对同一会话的操作保持一致。

启动::

    python -m slotmcp.ui.http_api --port 8787
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from ..engine.game import get_registry
from ..engine.simulator import simulate
from ..mcp.blender_bridge import BlenderBridge, BlenderBridgeError, bridge_from_env
from ..mcp.tools import sessions

__all__ = ["SlotHTTPServer", "UiState", "main"]

# 目录层级：.../src/slotmcp/ui/http_api.py → parents[3] 即工程根目录
STATIC_DIR = Path(os.getenv("SLOT_MCP_WEB_DIR", Path(__file__).resolve().parents[3] / "web"))


class UiState:
    """进程内的 UI 侧上下文：Blender 桥接 + 自动旋转任务。"""

    def __init__(self, bridge: Optional[BlenderBridge] = None):
        self.bridge = bridge if bridge is not None else bridge_from_env()
        self._auto: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 自动旋转
    def start_auto(self, session_id: str, spins: int, interval: float) -> None:
        with self._lock:
            if session_id in self._auto:
                return
            stopper = threading.Event()
            self._auto[session_id] = {"total": spins, "done": 0, "stop": stopper}
            thread = threading.Thread(
                target=self._auto_worker,
                args=(session_id, spins, interval, stopper),
                daemon=True,
            )
            thread.start()

    def stop_auto(self, session_id: str) -> bool:
        with self._lock:
            record = self._auto.get(session_id)
            if record:
                record["stop"].set()
            return record is not None

    def auto_status(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            record = self._auto.get(session_id)
            if not record:
                return {"running": False, "total": 0, "done": 0}
            return {"running": True, "total": record["total"], "done": record["done"]}

    def _auto_worker(self, session_id: str, spins: int, interval: float, stopper: threading.Event) -> None:
        import time

        for _ in range(spins):
            if stopper.is_set():
                break
            try:
                session = sessions.get(session_id)
                if not session.can_spin():
                    break
                session.spin()
            except Exception:  # noqa: BLE001 - 自动任务不应拖垮服务
                break
            finally:
                with self._lock:
                    record = self._auto.get(session_id)
                    if record:
                        record["done"] += 1
            time.sleep(max(0.05, interval))
        with self._lock:
            self._auto.pop(session_id, None)


class _Handler(BaseHTTPRequestHandler):
    server: "SlotHTTPServer"  # 便于类型提示

    # ---------------------------------------------------------------- 基础
    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[ui] {self.address_string()} {fmt % args}", flush=True)

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or path.is_dir():
            self.send_error(404, "Not Found")
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # ---------------------------------------------------------------- 路由
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        if route == "/":
            self._send_file(STATIC_DIR / "index.html")
            return
        if route.startswith("/api/"):
            self._api_get(route, parse_qs(parsed.query))
            return
        candidate = (STATIC_DIR / route.lstrip("/")).resolve()
        if candidate.is_file() and STATIC_DIR in candidate.parents:
            self._send_file(candidate)
            return
        self.send_error(404, "Not Found")

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path.rstrip("/")
        self._api_post(route, self._body())

    # ---------------------------------------------------------------- GET API
    def _api_get(self, route: str, query: Dict[str, Any]) -> None:
        registry = get_registry()
        if route == "/api/health":
            self._send_json(
                {
                    "ok": True,
                    "games": registry.ids(),
                    "blender": self.server.state.bridge.status().get("connected", False),
                }
            )
            return
        if route == "/api/games":
            self._send_json({"games": registry.list_info()})
            return
        if route.startswith("/api/games/"):
            game_id = route[len("/api/games/") :]
            try:
                machine = registry.get(game_id)
            except KeyError as exc:
                self._send_json({"error": str(exc)}, 404)
                return
            info = machine.info
            info["paylines"] = machine.payline_layout()
            info["features_detail"] = machine.config.features.to_dict()
            self._send_json(info)
            return
        if route.startswith("/api/session/"):
            parts = route.split("/")
            session_id = parts[3] if len(parts) > 3 else "default"
            if len(parts) > 4 and parts[4] == "auto":
                self._send_json(self.server.state.auto_status(session_id))
                return
            try:
                session = sessions.get(session_id)
            except KeyError as exc:
                self._send_json({"error": str(exc)}, 404)
                return
            self._send_json(session.to_dict())
            return
        if route == "/api/blender/status":
            self._send_json(self.server.state.bridge.status())
            return
        self._send_json({"error": f"未知路径: {route}"}, 404)

    # ---------------------------------------------------------------- POST API
    def _api_post(self, route: str, payload: Dict[str, Any]) -> None:
        registry = get_registry()

        if route == "/api/session":
            session_id = payload.get("session_id") or "default"
            try:
                session = sessions.create(
                    session_id,
                    payload["game_id"],
                    credits=float(payload.get("credits", 1000.0)),
                    bet_index=payload.get("bet_index"),
                )
            except KeyError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json(session.to_dict())
            return

        if route.startswith("/api/session/"):
            parts = route.split("/")
            session_id = parts[3] if len(parts) > 3 else "default"
            action = parts[4] if len(parts) > 4 else ""
            try:
                session = sessions.get(session_id)
            except KeyError as exc:
                self._send_json({"error": str(exc)}, 404)
                return

            if action == "spin":
                if payload.get("bet_index") is not None:
                    session.set_bet_index(int(payload["bet_index"]))
                try:
                    result = session.spin(active_lines=int(payload.get("lines", 0)))
                except RuntimeError as exc:
                    self._send_json({"error": str(exc)}, 400)
                    return
                self._send_json({**session.to_dict(result), "result": result.to_dict()})
                return
            if action == "bet":
                session.set_bet_index(int(payload.get("bet_index", session.bet_index)))
                self._send_json(session.to_dict())
                return
            if action == "gamble":
                try:
                    outcome = (
                        session.take_gamble()
                        if payload.get("take")
                        else session.gamble(str(payload.get("choice", "red")))
                    )
                except RuntimeError as exc:
                    self._send_json({"error": str(exc)}, 400)
                    return
                self._send_json({**session.to_dict(), "gamble": outcome})
                return
            if action == "auto":
                if payload.get("stop"):
                    self.server.state.stop_auto(session_id)
                else:
                    self.server.state.start_auto(
                        session_id,
                        int(payload.get("spins", 10)),
                        float(payload.get("interval", 0.6)),
                    )
                self._send_json(self.server.state.auto_status(session_id))
                return
            if action == "restore":
                try:
                    sessions.restore(session_id, payload)
                except KeyError as exc:
                    self._send_json({"error": str(exc)}, 400)
                    return
                self._send_json(sessions.get(session_id).to_dict())
                return

        if route == "/api/simulate":
            game_id = payload.get("game_id")
            try:
                machine = registry.get(game_id)
            except KeyError as exc:
                self._send_json({"error": str(exc)}, 404)
                return
            report = simulate(
                machine,
                spins=int(payload.get("spins", 50_000)),
                bet=float(payload.get("bet", 1.0)),
                seed=payload.get("seed"),
            )
            self._send_json(report.to_dict())
            return

        if route == "/api/blender/build":
            self._blender_forward("build_cabinet", payload)
            return
        if route == "/api/blender/animate":
            if "spin" not in payload:
                try:
                    snapshot = sessions.get(str(payload.get("session_id", "default"))).snapshot()
                    payload["spin"] = (
                        snapshot.last_result.to_dict() if snapshot.last_result else None
                    )
                except KeyError as exc:
                    self._send_json({"error": str(exc)}, 404)
                    return
            self._blender_forward("animate_spin", payload)
            return

        self._send_json({"error": f"未知路径: {route}"}, 404)

    def _blender_forward(self, op: str, payload: Dict[str, Any]) -> None:
        bridge = self.server.state.bridge
        try:
            if not bridge.is_connected():
                bridge.connect()
            result = bridge.request(op, payload, timeout=30.0)
        except BlenderBridgeError as exc:
            self._send_json({"error": str(exc), "op": op}, 502)
            return
        self._send_json({"ok": True, "op": op, "result": result})


class SlotHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple, state: Optional[UiState] = None):
        self.state = state or UiState()
        super().__init__(address, _Handler)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="SLOT Web UI 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--blender-host", default=os.getenv("SLOT_MCP_BLENDER_HOST", "127.0.0.1"))
    parser.add_argument("--blender-port", type=int, default=8765)
    args = parser.parse_args(argv)

    from ..mcp.blender_bridge import BlenderBridge

    state = UiState(BlenderBridge(host=args.blender_host, port=args.blender_port))
    server = SlotHTTPServer((args.host, args.port), state)
    print(f"[ui] 服务已启动: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        state.bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
