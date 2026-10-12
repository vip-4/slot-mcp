"""Blender 桥接自测：用本地假服务端验证封帧、超时、错误传播与自动重连。

这样即使机器上没有安装 Blender，也能保证「一条通信链路」的稳定性逻辑被验证到。
"""

import socket
import struct
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from slotmcp.mcp.blender_bridge import BlenderBridge, BlenderBridgeError  # noqa: E402

HOST = "127.0.0.1"
PORT = 8799


class FakeBlender:
    """实现与 Blender 插件相同的封帧协议；`hang` 指令故意不回复用于验证超时。"""

    def __init__(self, host: str, port: int):
        self.port = port
        self.host = host
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(16)
        self.connections = []
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.connections.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        # 测试会主动 kill 连接，这里把连接被中止当作正常退出处理，避免噪声堆栈
        try:
            self._serve_inner(conn)
        except OSError:
            return

    def _serve_inner(self, conn: socket.socket) -> None:
        with conn:
            while self.running:
                header = conn.recv(4)
                if len(header) < 4:
                    return
                (length,) = struct.unpack(">I", header)
                body = b""
                while len(body) < length:
                    chunk = conn.recv(length - len(body))
                    if not chunk:
                        return
                    body += chunk
                import json

                message = json.loads(body.decode("utf-8"))
                op = message.get("op")
                if op == "hang":
                    continue  # 故意不回复
                if op == "boom":
                    payload = {"id": message["id"], "ok": False, "result": None, "error": "boom"}
                elif op == "status":
                    payload = {
                        "id": message["id"],
                        "ok": True,
                        "result": {"blender": "4.0.0 (fake)", "objects": 3},
                        "error": None,
                    }
                else:
                    payload = {
                        "id": message["id"],
                        "ok": True,
                        "result": {"pong": True, "op": op},
                        "error": None,
                    }
                raw = __import__("json").dumps(payload).encode("utf-8")
                conn.sendall(struct.pack(">I", len(raw)) + raw)

    def kill_connections(self) -> None:
        for conn in self.connections:
            try:
                conn.close()
            except OSError:
                pass
        self.connections.clear()

    def stop(self) -> None:
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass
        self.kill_connections()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ok  {message}")


def main() -> int:
    fake = FakeBlender(HOST, PORT)
    bridge = BlenderBridge(host=HOST, port=PORT, timeout=1.5, heartbeat_interval=0)
    try:
        print("[bridge] 基础通信")
        bridge.connect()
        check(bridge.is_connected(), "连接成功")
        pong = bridge.request("ping")
        check(pong.get("pong") is True, "ping 往返成功")
        status = bridge.request("status")
        check(status.get("blender") == "4.0.0 (fake)", "业务指令返回结构化结果")
        check(bridge.ping(), "ping() 便捷方法可用")

        print("[bridge] 错误传播")
        try:
            bridge.request("boom")
            raise AssertionError("应抛出 BlenderBridgeError")
        except BlenderBridgeError as exc:
            check("boom" in str(exc), "Blender 端错误被转换为 BlenderBridgeError")

        print("[bridge] 超时保护")
        started = time.time()
        try:
            bridge.request("hang", timeout=1.0)
            raise AssertionError("应触发超时")
        except BlenderBridgeError as exc:
            elapsed = time.time() - started
            check("超时" in str(exc), f"超时按预期抛出（{elapsed:.2f}s）")
            check(elapsed < 3.0, "超时不会无限阻塞")

        print("[bridge] 自动重连")
        bridge.close()
        bridge2 = BlenderBridge(host=HOST, port=PORT, timeout=2.0, heartbeat_interval=0)
        bridge2.connect()
        check(bridge2.request("ping").get("pong") is True, "新连接可用")
        fake.kill_connections()
        time.sleep(0.2)
        check(bridge2.request("ping", auto_reconnect=True).get("pong") is True, "对方断开后自动重连成功")

        print("[bridge] 未启动时的降级")
        fake.stop()
        time.sleep(0.2)
        orphan = BlenderBridge(host=HOST, port=PORT + 1, timeout=1.0, heartbeat_interval=0)
        status_down = orphan.status()
        check(status_down["connected"] is False, "status() 在未连接时返回结构化状态而非抛异常")
        check("error" in status_down, "状态中携带错误原因")
    finally:
        fake.stop()
        bridge.close()
    print("\n[bridge] 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
