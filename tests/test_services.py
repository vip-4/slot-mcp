"""外部服务客户端自测：用本地桩服务验证请求形态、幂等 upsert 与降级路径（不发真实网络请求）。"""

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from slotmcp.services.agentmail import AgentMailClient  # noqa: E402
from slotmcp.services.cronjob import CronJobClient, every_n_minutes  # noqa: E402
from slotmcp.services.playcanvas import PlayCanvasClient, build_scene_descriptor  # noqa: E402

FAILS = 0
TESTS = 0

STATE = {"jobs": [], "sent": [], "next_id": 1001}


def check(cond: bool, msg: str) -> None:
    global FAILS, TESTS
    TESTS += 1
    print(f"  [{'OK' if cond else 'NG'}] {msg}")
    if not cond:
        FAILS += 1


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}") if length else {}

    def do_GET(self):
        p = self.path
        if p.startswith("/inboxes/") and p.endswith("/messages"):
            return self._json(200, {"count": 0, "messages": []})
        if p == "/inboxes":
            return self._json(200, {"count": 1, "inboxes": [{"inbox_id": "a@agentmail.to"}]})
        if p == "/jobs":
            return self._json(200, {"jobs": STATE["jobs"]})
        if p.endswith("/scenes"):
            return self._json(200, {"result": [{"id": 1, "name": "Main Scene"}]})
        if p.endswith("/assets"):
            return self._json(200, {"result": [{"id": 2, "type": "material"}, {"id": 3, "type": "texture"}]})
        if p.startswith("/projects/"):
            return self._json(403, {"error": "Token does not have required scope"})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        body = self._read()
        p = self.path
        if p.endswith("/messages/send"):
            STATE["sent"].append(body)
            return self._json(200, {"message_id": "<stub>", "thread_id": "t-1"})
        self._json(404, {"error": "not found"})

    def do_PUT(self):
        body = self._read()
        if self.path == "/jobs":
            job = dict(body.get("job", {}))
            job["jobId"] = STATE["next_id"]
            STATE["next_id"] += 1
            STATE["jobs"].append(job)
            return self._json(200, {"jobId": job["jobId"]})
        self._json(404, {"error": "not found"})

    def do_DELETE(self):
        parts = self.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "jobs":
            job_id = int(parts[1])
            before = len(STATE["jobs"])
            STATE["jobs"] = [j for j in STATE["jobs"] if j.get("jobId") != job_id]
            return self._json(200, {"deleted": before - len(STATE["jobs"])})
        self._json(404, {"error": "not found"})

    def do_PATCH(self):
        body = self._read()
        parts = self.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "jobs":
            job_id = int(parts[1])
            for job in STATE["jobs"]:
                if job.get("jobId") == job_id:
                    job.update(body.get("job", {}))
                    return self._json(200, {"jobId": job_id})
        self._json(404, {"error": "not found"})


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    try:
        print("== AgentMail ==")
        am = AgentMailClient("stub-key", "a@agentmail.to", base_url=base)
        ok, status, payload = am.list_inboxes()
        check(ok and payload["count"] == 1, f"列出邮箱（HTTP {status}）")
        ok, status, payload = am.send(to=["b@agentmail.to"], subject="s", text="body")
        check(ok and payload.get("message_id"), f"发送成功并返回 message_id（HTTP {status}）")
        check(
            STATE["sent"] and STATE["sent"][-1]["to"] == ["b@agentmail.to"] and STATE["sent"][-1]["subject"] == "s",
            "请求体包含 to / subject / text",
        )

        print("== cron-job.org ==")
        cj = CronJobClient("stub-key", base_url=base)
        schedule = every_n_minutes(30)
        check(schedule["minutes"] == [0, 30] and schedule["hours"] == [-1], "每 30 分钟 → minutes=[0,30], hours=[-1]")
        check(every_n_minutes(60)["hours"] == list(range(24)), "每 60 分钟 → hours 全量、minutes=[0]")
        try:
            every_n_minutes(7)
            check(False, "非 60 约数应报错")
        except ValueError:
            check(True, "非 60 约数拒绝并提示")

        res = cj.upsert(title="巡检", url="https://example.com/", schedule=schedule)
        check(res["state"] == "created" and len(STATE["jobs"]) == 1, "首次 upsert 创建任务")
        res2 = cj.upsert(title="巡检", url="https://example.com/v2", schedule=schedule)
        check(res2["state"] == "updated" and len(STATE["jobs"]) == 1, "重复 upsert 走更新且仍只有 1 条")
        check(STATE["jobs"][0]["url"] == "https://example.com/v2", "更新后 URL 已生效")
        check(cj.find_by_title("巡检") is not None, "find_by_title 可命中")
        check(cj.find_by_title("不存在") is None, "find_by_title 未命中返回 None")
        ok, status, payload = cj.delete_job(STATE["jobs"][0]["jobId"])
        check(ok and not STATE["jobs"], "delete_job 可删除任务（实测接口为 DELETE /jobs/{id}）")

        print("== PlayCanvas ==")
        pc = PlayCanvasClient("stub-key", base_url=base)
        summary = pc.summary(1583126)
        check(summary["scenes"] == 1 and summary["assets"] == 2, f"汇总场景/资产数量（{summary['scenes']}/{summary['assets']}）")
        check(summary["asset_types"] == {"material": 1, "texture": 1}, "按类型统计资产")
        ok, status, payload = pc.project(1583126)
        check(not ok and status == 403, "项目详情 403 时不抛异常而是返回结构化失败")
        ok, _, scenes = pc.list_scenes(999)
        check(ok, "list_scenes 正常返回")

        print("== 场景描述导出 ==")
        desc = build_scene_descriptor(
            project_id=1583126,
            games=[
                {
                    "id": "demo",
                    "name": "演示机台",
                    "reels": 5,
                    "rows": 3,
                    "pay_mode": "lines",
                    "theme": {"accent": "#ffcc33"},
                    "symbols": {"cherry": {"name": "樱桃", "kind": "standard", "color": "#f66", "glyph": "🍒"}},
                    "features": {"free_spins": {"trigger_symbol": "scatter"}},
                }
            ],
        )
        check(desc["schema"] == "slotmcp.scene/1", "场景描述带 schema 版本")
        check(desc["machines"][0]["symbols"][0]["id"] == "cherry", "符号表被正确导出")
        check(desc["animation"]["spin_ms"] == 420, "动画参数进入场景描述")

        print("== 报告渲染 ==")
        text = AgentMailClient.render_report(
            site_url="https://example.com", pages=6, games=["A", "B"],
            checks=[{"ok": True, "status": 200, "seconds": 0.12, "url": "https://example.com/"}],
            cron=[{"state": "created", "title": "巡检", "url": "https://example.com/", "schedule": "每 30 分钟"}],
            playcanvas={"project": "1583126", "scenes": 1, "assets": 2, "error": ""},
        )
        check("站点地址: https://example.com" in text and "机台数量: 2" in text, "报告含站点与机台事实")
        check("[OK ]" in text and "[NG ]" not in text, "健康检查状态进入报告正文")
    finally:
        server.shutdown()

    print()
    print(f"服务层自测：{TESTS - FAILS}/{TESTS} 通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
