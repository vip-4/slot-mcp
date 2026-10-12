"""MCP 服务端：stdio 传输的 JSON-RPC 2.0 服务。

启动方式::

    python -m slotmcp.mcp.server          # 由 MCP 客户端（host 进程）拉起
    python -m slotmcp.mcp.server --help

传输约定
--------
* 默认使用 MCP 标准的「换行分隔 JSON」帧；
* 若客户端使用 LSP 风格（`Content-Length: N\\r\\n\\r\\n`）封帧，服务端会自动识别并以同样格式回包。
* 日志一律写 stderr，**绝不污染 stdout**，否则会破坏 JSON-RPC 帧。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from typing import Any, Dict, Optional

from ..engine.game import get_registry
from . import blender_bridge
from .blender_bridge import BlenderBridge, BlenderBridgeError
from .tools import TOOLS, handle_tool

__all__ = ["SlotMCPServer", "main"]

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "blender-slot-mcp", "version": "1.0.0"}

JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603


class SlotMCPServer:
    def __init__(self, bridge: Optional[BlenderBridge] = None):
        self.bridge = bridge if bridge is not None else blender_bridge.bridge_from_env()
        self._framed = False  # 客户端是否使用 Content-Length 封帧
        self._stop = threading.Event()

    # ---------------------------------------------------------------- 帧读写
    def _read_message(self) -> Optional[Dict[str, Any]]:
        stdin = sys.stdin.buffer
        first = stdin.readline()
        if not first:
            return None
        head = first.strip()
        if head.lower().startswith(b"content-length:"):
            length = int(head.split(b":", 1)[1].strip())
            while True:
                line = stdin.readline()
                if not line or line in (b"\r\n", b"\n"):
                    break
            body = stdin.read(length) if length else b""
            self._framed = True
        else:
            body = head
        if not body.strip():
            return {"_skip": True}
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return {"_parse_error": True}

    def _write(self, message: Dict[str, Any]) -> None:
        raw = json.dumps(message, ensure_ascii=False).encode("utf-8")
        out = sys.stdout.buffer
        if self._framed:
            out.write(b"Content-Length: " + str(len(raw)).encode() + b"\r\n\r\n")
            out.write(raw)
        else:
            out.write(raw + b"\n")
        out.flush()

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id if request_id is not None else None,
            "error": {"code": code, "message": message},
        }

    # ---------------------------------------------------------------- 分派
    def handle(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if message.get("_parse_error"):
            return self._error(None, JSONRPC_PARSE_ERROR, "无法解析 JSON")
        if message.get("_skip"):
            return None

        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": SERVER_INFO,
                    "instructions": "使用 slot_* 工具操作老虎机，使用 blender_* 工具驱动 Blender 3D 场景。",
                },
            }
        if method in ("notifications/initialized", "initialized"):
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
        if method == "resources/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": self._resources()}}
        if method == "resources/read":
            uri = params.get("uri", "")
            return self._read_resource(request_id, uri)
        if method == "tools/call":
            return self._call_tool(request_id, params)
        if request_id is None:
            return None
        return self._error(request_id, JSONRPC_METHOD_NOT_FOUND, f"未知方法: {method}")

    def _call_tool(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not name:
            return self._error(request_id, JSONRPC_INVALID_PARAMS, "缺少工具名")
        outcome = handle_tool(name, arguments, self.bridge)
        result: Dict[str, Any] = {
            "content": outcome.get("content", []),
            "isError": bool(outcome.get("isError")),
        }
        if "structuredContent" in outcome:
            result["structuredContent"] = outcome["structuredContent"]
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _resources(self) -> list:
        registry = get_registry()
        return [
            {
                "uri": f"slot://games/{game_id}",
                "name": f"{game_id} 机台配置",
                "mimeType": "application/json",
                "description": registry.get(game_id).config.description,
            }
            for game_id in registry.ids()
        ]

    def _read_resource(self, request_id: Any, uri: str) -> Dict[str, Any]:
        prefix = "slot://games/"
        if not uri.startswith(prefix):
            return self._error(request_id, JSONRPC_INVALID_PARAMS, f"不支持的资源: {uri}")
        game_id = uri[len(prefix) :]
        try:
            config = get_registry().get(game_id).config
        except KeyError as exc:
            return self._error(request_id, JSONRPC_INVALID_PARAMS, str(exc))
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": config.to_json(),
                    }
                ]
            },
        }

    # ---------------------------------------------------------------- 主循环
    def serve(self) -> int:
        while not self._stop.is_set():
            try:
                message = self._read_message()
            except KeyboardInterrupt:
                break
            except Exception as exc:  # noqa: BLE001
                self._log(f"读取异常: {exc}")
                break
            if message is None:
                break
            try:
                response = self.handle(message)
            except BlenderBridgeError as exc:
                response = self._error(message.get("id"), JSONRPC_INTERNAL_ERROR, str(exc))
            except Exception as exc:  # noqa: BLE001
                response = self._error(
                    message.get("id"), JSONRPC_INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"
                )
            if response is not None:
                self._write(response)
        self.shutdown()
        return 0

    def shutdown(self) -> None:
        self._stop.set()
        try:
            self.bridge.close()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _log(text: str) -> None:
        print(f"[slot-mcp] {text}", file=sys.stderr, flush=True)


def _configure_console() -> None:
    """日志走 stderr，统一 UTF-8，避免 Windows GBK 控制台抛编码异常。"""
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass


def main(argv: Optional[list] = None) -> int:
    _configure_console()
    parser = argparse.ArgumentParser(description="Blender SLOT MCP 服务端")
    parser.add_argument("--host", default=blender_bridge.DEFAULT_HOST, help="Blender 插件地址")
    parser.add_argument("--port", type=int, default=blender_bridge.DEFAULT_PORT, help="Blender 插件端口")
    parser.add_argument("--timeout", type=float, default=10.0, help="桥接超时（秒）")
    parser.add_argument("--selftest", action="store_true", help="自检：列出工具后退出")
    args = parser.parse_args(argv)

    server = SlotMCPServer(
        BlenderBridge(host=args.host, port=args.port, timeout=args.timeout)
    )

    if args.selftest:
        print(json.dumps({"tools": [t["name"] for t in TOOLS]}, ensure_ascii=False, indent=2))
        print(json.dumps({"games": get_registry().ids()}, ensure_ascii=False))
        return 0
    return server.serve()


if __name__ == "__main__":
    raise SystemExit(main())
