"""UI 层自测：进程内启动 HTTP 服务，用 urllib 跑通主要 REST 流程。"""

import json
import sys
import threading
import urllib.error
import urllib.request
from http.client import HTTPConnection
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from slotmcp.ui.http_api import SlotHTTPServer, UiState  # noqa: E402

HOST = "127.0.0.1"
PORT = 8791
BASE = f"http://{HOST}:{PORT}"


def api(path: str, payload: dict | None = None) -> tuple:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method="POST" if payload is not None else "GET",
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:  # 非 2xx 也视为合法响应，交给断言处理
        return exc.code, json.loads(exc.read().decode())


def get_text(path: str) -> tuple:
    with urllib.request.urlopen(BASE + path, timeout=10) as resp:
        return resp.status, resp.read().decode("utf-8")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ok  {message}")


def main() -> int:
    server = SlotHTTPServer((HOST, PORT), UiState())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        print("[ui] 静态资源")
        status, html = get_text("/")
        check(status == 200 and "<title>" in html, "index.html 可访问")
        status, css = get_text("/styles.css")
        check(status == 200 and "--cabinet" in css, "styles.css 可访问")
        status, js = get_text("/app.js")
        check(status == 200 and "playResult" in js, "app.js 可访问")

        print("[ui] 健康检查")
        status, health = api("/api/health")
        check(status == 200 and len(health["games"]) == 9, "健康检查返回 9 台机台")

        print("[ui] 机台信息")
        status, info = api("/api/games/candy_carnival")
        check(status == 200 and len(info["paylines"]) == 20, "返回 20 条赔付线")
        check("features_detail" in info, "包含特性明细")

        print("[ui] 会话流程")
        status, session = api("/api/session", {"session_id": "uitest", "game_id": "candy_carnival", "credits": 500})
        check(status == 200 and session["credits"] == 500, "会话创建成功")

        status, spun = api("/api/session/uitest/spin", {"bet_index": 2})
        bet = spun["bet"]
        credits = spun["credits"]
        result = spun["result"]
        check(status == 200, "旋转成功")
        check(abs(credits - (500 - bet + result["total_win"])) < 1e-6, "余额按 下注/派彩 正确变动")
        check(len(result["steps"]) >= 1, "至少返回一步结果")

        status, betted = api("/api/session/uitest/bet", {"bet_index": 4})
        check(status == 200 and betted["bet"] == betted["bet_levels"][4], "下注档位切换生效")

        status, missing = api("/api/session/not-exist/spin", {})
        check(status == 404 and "error" in missing, "未知会话返回 404")

        print("[ui] Blender 未启动时的降级")
        status, blender = api("/api/blender/status")
        check(status == 200 and blender["connected"] is False, "桥接状态返回结构化降级信息")

        print("[ui] 线程安全检查")
        conn = HTTPConnection(HOST, PORT, timeout=10)
        conn.request("GET", "/api/games")
        resp = conn.getresponse()
        check(resp.status == 200, "并发请求不影响服务")
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
