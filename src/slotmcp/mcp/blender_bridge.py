"""Blender 桥接客户端：负责 MCP 服务与 Blender 插件之间的稳定通信。

通信协议
--------
* 传输：TCP（默认 `127.0.0.1:8765`，可用环境变量覆盖）
* 封帧：`4 字节大端长度 + UTF-8 JSON`，避免粘包
* 请求：`{"id": "...", "op": "...", "params": {...}}`
* 响应：`{"id": "...", "ok": true|false, "result": {...}, "error": "..."}`

稳定性设计
----------
* 后台读线程统一收包，按 `id` 唤醒等待方（`threading.Event`），调用方不直接读 socket
* 每次请求带超时；超时后标记连接失效，下一次调用自动重连并重试一次
* 心跳线程定期 `ping`，对方掉线能立刻发现而不是等到业务请求超时
* 所有写操作串行化（一把锁），保证多线程调用不会交错产生半包
"""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time
import uuid
from typing import Any, Dict, Optional

__all__ = ["BlenderBridge", "BlenderBridgeError", "bridge_from_env"]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class BlenderBridgeError(RuntimeError):
    """桥接不可用或 Blender 端返回业务错误。"""


class BlenderBridge:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = 10.0,
        heartbeat_interval: float = 5.0,
        max_frame_bytes: int = 32 * 1024 * 1024,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.heartbeat_interval = heartbeat_interval
        self.max_frame_bytes = max_frame_bytes

        self._sock: Optional[socket.socket] = None
        self._reader: Optional[threading.Thread] = None
        self._heartbeat: Optional[threading.Thread] = None
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._conn_lock = threading.Lock()
        self._closed = False

    # ---------------------------------------------------------------- 生命周期
    @property
    def address(self) -> tuple:
        return (self.host, self.port)

    def is_connected(self) -> bool:
        return self._sock is not None and self._reader is not None and self._reader.is_alive()

    def connect(self, retry: int = 3, delay: float = 0.4) -> bool:
        """建立连接并启动读线程；失败时按指数退避重试。"""
        with self._conn_lock:
            if self.is_connected():
                return True
            last_error: Optional[Exception] = None
            for attempt in range(max(1, retry)):
                try:
                    sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
                    sock.settimeout(None)
                    self._sock = sock
                    self._closed = False
                    self._reader = threading.Thread(
                        target=self._read_loop, name="blender-bridge-reader", daemon=True
                    )
                    self._reader.start()
                    if self.heartbeat_interval > 0:
                        self._heartbeat = threading.Thread(
                            target=self._heartbeat_loop, name="blender-bridge-hb", daemon=True
                        )
                        self._heartbeat.start()
                    return True
                except OSError as exc:  # pragma: no cover - 依赖运行环境
                    last_error = exc
                    time.sleep(delay * (2**attempt))
            self._teardown_socket()
            raise BlenderBridgeError(
                f"无法连接 Blender 插件 {self.host}:{self.port}: {last_error}"
            )

    def close(self) -> None:
        self._closed = True
        self._teardown_socket()

    def _teardown_socket(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        with self._pending_lock:
            waiting = list(self._pending.values())
            self._pending.clear()
        for item in waiting:
            item["error"] = "连接已关闭"
            item["event"].set()

    # ---------------------------------------------------------------- 收发
    def request(
        self,
        op: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        auto_reconnect: bool = True,
    ) -> Dict[str, Any]:
        """向 Blender 发送一条指令并等待结果。"""
        if not self.is_connected() and not self.connect():
            raise BlenderBridgeError("Blender 桥接未连接")
        deadline_timeout = self.timeout if timeout is None else timeout

        for attempt in (0, 1):
            request_id = uuid.uuid4().hex
            payload = {"id": request_id, "op": op, "params": params or {}}
            event = threading.Event()
            slot = {"event": event, "response": None, "error": None}
            with self._pending_lock:
                self._pending[request_id] = slot
            try:
                self._send(payload)
            except BlenderBridgeError:
                self._teardown_socket()
                if attempt == 0 and auto_reconnect:
                    self.connect(retry=1)
                    continue
                raise

            if not event.wait(deadline_timeout):
                with self._pending_lock:
                    self._pending.pop(request_id, None)
                self._teardown_socket()
                raise BlenderBridgeError(f"指令超时（{deadline_timeout}s）: {op}")

            if slot["error"]:
                raise BlenderBridgeError(str(slot["error"]))
            response = slot["response"] or {}
            if not response.get("ok"):
                raise BlenderBridgeError(f"Blender 端错误: {response.get('error')}")
            return dict(response.get("result") or {})

        raise BlenderBridgeError(f"指令失败: {op}")

    def _send(self, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(raw) > self.max_frame_bytes:
            raise BlenderBridgeError("请求体过大")
        frame = struct.pack(">I", len(raw)) + raw
        with self._write_lock:
            sock = self._sock
            if sock is None:
                raise BlenderBridgeError("套接字未就绪")
            try:
                sock.sendall(frame)
            except OSError as exc:
                raise BlenderBridgeError(f"发送失败: {exc}") from exc

    def _read_loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        try:
            while not self._closed:
                header = self._recv_exact(sock, 4)
                if not header:
                    break
                (length,) = struct.unpack(">I", header)
                if length <= 0 or length > self.max_frame_bytes:
                    break
                body = self._recv_exact(sock, length)
                if not body:
                    break
                self._dispatch(body)
        except OSError:
            pass
        finally:
            self._teardown_socket()

    def _recv_exact(self, sock: socket.socket, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = sock.recv(size - len(chunks))
            if not chunk:
                return b""
            chunks.extend(chunk)
        return bytes(chunks)

    def _dispatch(self, body: bytes) -> None:
        try:
            message = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        request_id = message.get("id")
        if not request_id:
            return
        with self._pending_lock:
            slot = self._pending.pop(request_id, None)
        if slot is None:
            return
        slot["response"] = message
        slot["event"].set()

    def _heartbeat_loop(self) -> None:
        while not self._closed and self.is_connected():
            time.sleep(self.heartbeat_interval)
            try:
                self.request("ping", timeout=min(3.0, self.timeout), auto_reconnect=False)
            except BlenderBridgeError:
                self._teardown_socket()
                return

    # ---------------------------------------------------------------- 便捷封装
    def ping(self) -> bool:
        try:
            self.request("ping", timeout=3.0)
            return True
        except BlenderBridgeError:
            return False

    def status(self) -> Dict[str, Any]:
        """返回桥接状态；Blender 未启动时返回结构化信息而不是抛异常。"""
        info = {
            "host": self.host,
            "port": self.port,
            "connected": self.is_connected(),
            "blender": None,
        }
        try:
            info["blender"] = self.request("status", timeout=5.0)
        except BlenderBridgeError as exc:
            info["error"] = str(exc)
        return info


def bridge_from_env() -> BlenderBridge:
    host = os.getenv("SLOT_MCP_BLENDER_HOST", DEFAULT_HOST)
    port = int(os.getenv("SLOT_MCP_BLENDER_PORT", str(DEFAULT_PORT)))
    timeout = float(os.getenv("SLOT_MCP_BLENDER_TIMEOUT", "10"))
    return BlenderBridge(host=host, port=port, timeout=timeout)
