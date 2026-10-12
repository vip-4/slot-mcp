"""外部服务客户端自测：用本地桩服务验证请求形态、幂等 upsert 与降级路径（不发真实网络请求）。"""

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from slotmcp.services.agentmail import AgentMailClient  # noqa: E402
from slotmcp.services.cloudflare import (  # noqa: E402
    CloudflareClient,
    build_manifest,
    build_multipart,
    collect_files,
)
from slotmcp.services.cronjob import CronJobClient, every_n_minutes  # noqa: E402
from slotmcp.services.github import GitHubClient  # noqa: E402
from slotmcp.services.media import (  # noqa: E402
    THEME_QUERIES,
    PixabayClient,
    PexelsClient,
)
from slotmcp.services.metaso import MetasoClient  # noqa: E402
from slotmcp.services.neon import NeonClient  # noqa: E402
from slotmcp.services.supabase import SupabaseClient  # noqa: E402
from slotmcp.services.playcanvas import PlayCanvasClient, build_scene_descriptor  # noqa: E402

FAILS = 0
TESTS = 0

STATE = {
    "jobs": [], "sent": [], "next_id": 1001, "sql": [], "neon_headers": {},
    "supa_body": None, "last_get": "", "multipart": b"", "deploy_files": 0,
    "pages_body": None, "cf_created": None,
}


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
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith("multipart/form-data"):  # Cloudflare 直传
            STATE["multipart"] = raw
            return {"__raw__": True}
        return json.loads(raw)

    def do_GET(self):
        p = self.path
        if p.startswith("/inboxes/") and p.endswith("/messages"):
            return self._json(200, {"count": 0, "messages": []})
        if p == "/inboxes":
            return self._json(200, {"count": 1, "inboxes": [{"inbox_id": "a@agentmail.to"}]})
        if p == "/jobs":
            return self._json(200, {"jobs": STATE["jobs"]})
        if p == "/user":  # GitHub
            return self._json(200, {"login": "vip-4", "id": 1})
        if p.endswith("/pages") and "/repos/" in p:  # GitHub Pages 状态
            return self._json(200, {"status": "built", "html_url": "https://vip-4.github.io/slot-games/"})
        if "/repos/" in p:
            return self._json(200, {"full_name": p.split("/repos/")[-1], "html_url": "https://github.com/x"})
        if p == "/inboxes-meta":
            return self._json(200, {"ok": True})
        if p.startswith("/rest/v1/"):  # Supabase（PostgREST）
            table = p.split("/")[-1].split("?")[0]
            STATE["last_get"] = p
            if table == "slot_scores":
                return self._json(200, [{"game_id": "lucky_fruits", "best_multiplier": 18.4}])
            return self._json(200, [{"ok": 1}])
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
        if p == "/search":  # Metaso
            return self._json(
                200,
                {
                    "webpages": [
                        {"title": "本站首页", "link": "https://vip882.gitee.io/slot-games/index.html", "snippet": "五款机台"},
                        {"title": "其它站点", "link": "https://example.com/x", "snippet": "无关"},
                    ],
                    "summary": "这是 AI 摘要",
                },
            )
        if p.endswith("/messages/send"):
            STATE["sent"].append(body)
            return self._json(200, {"message_id": "<stub>", "thread_id": "t-1"})
        if p == "/sql":  # Neon HTTP SQL
            query = body.get("query", "")
            STATE["sql"].append(query)
            STATE["neon_headers"] = dict(self.headers)
            if "boom" in query:
                return self._json(400, {"code": "42601", "message": "syntax error"})
            if query.strip().lower().startswith("select version"):
                return self._json(200, {"rows": [{"version": "PostgreSQL 16.3"}]})
            return self._json(200, {"command": "OK", "rows": [], "rowCount": 1})
        if p.startswith("/rest/v1/"):  # Supabase 写入
            STATE["supa_body"] = body
            return self._json(201, [dict(body, id=1)])
        if p == "/user/repos":  # GitHub 建仓
            return self._json(201, {"full_name": f"vip-4/{body.get('name')}", "html_url": "https://github.com/vip-4/x"})
        if "/repos/" in p and p.endswith("/pages"):  # GitHub 开启 Pages
            STATE["pages_body"] = body
            return self._json(201, {"status": "queued"})
        # Cloudflare Pages（base_url 指向桩服务，路径形如 /accounts/<id>/pages/...）
        if p.endswith("/pages/projects"):
            STATE["cf_created"] = body
            return self._json(200, {"success": True, "result": {"name": body.get("name"), "subdomain": f"{body.get('name')}.pages.dev"}})
        if "/pages/projects/" in p and p.endswith("/deployments"):
            raw = STATE.get("multipart", b"")
            STATE["deploy_files"] = raw.count(b'name="')
            return self._json(200, {"success": True, "result": {"id": "dep-1", "url": "https://slot-games.pages.dev"}})
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

        print("== 图片素材（离线解析） ==")
        pexels = PexelsClient("k")
        item = pexels.normalize(
            {
                "id": 1,
                "url": "https://www.pexels.com/photo/x/",
                "photographer": "A",
                "photographer_url": "https://www.pexels.com/@a",
                "src": {"original": "https://images.pexels.com/photos/1/x.jpeg"},
            }
        )
        check(item["provider"] == "pexels" and item["author"] == "A", "Pexels 结果归一化")
        check(
            pexels.crop(item["raw"], 1200, 630)
            == "https://images.pexels.com/photos/1/x.jpeg?auto=compress&cs=tinysrgb&fit=crop&w=1200&h=630",
            "Pexels 用 imgix 参数裁剪出 1200×630 OG 图",
        )
        pix = PixabayClient("k").normalize({"id": 2, "pageURL": "u", "user": "B", "largeImageURL": "https://cdn/x.jpg"})
        check(pix["provider"] == "pixabay" and pix["raw"].endswith("x.jpg"), "Pixabay 结果归一化")
        check(len(THEME_QUERIES) == 5 and all("alt" in v for v in THEME_QUERIES.values()), "5 款机台都有检索词与中文 alt")

        print("== Neon（HTTP SQL） ==")
        neon = NeonClient("postgresql://u:p@ep-demo.eu.neon.tech/db", base_url=f"{base}/sql")
        ok, rows, err = neon.sql("select version()")
        check(ok and rows[0]["version"].startswith("PostgreSQL"), f"执行 SQL 并解析 rows：{rows}")
        check(
            STATE["neon_headers"].get("Neon-Connection-String", "").startswith("postgresql://"),
            "请求头带 Neon-Connection-String（无需本地驱动）",
        )
        ok, err = neon.execute("insert into t values (1) boom")
        check(not ok and "syntax error" in err, f"错误按结构化返回而非抛异常：{err[:40]}")
        results = neon.ensure_schema(["create table if not exists a (id int)", "create index if not exists b"])
        check(all(r[1] for r in results) and len(results) == 2, "建表语句逐条执行")
        ok_insert, _ = neon.insert("slot_scores", {"game_id": "lucky_fruits", "player": "o'brien", "best_multiplier": 3.5})
        check(ok_insert and "o''brien" in STATE["sql"][-1], f"字面量转义单引号：{STATE['sql'][-1][:70]}")

        print("== Supabase（PostgREST） ==")
        sb = SupabaseClient(base, "sb_publishable_x")
        ok, detail = sb.ping()
        check(ok, f"REST 探活：{detail}")
        ok, data, _ = sb.select("slot_scores", "select=game_id&order=best_multiplier.desc&limit=5")
        check(ok and data[0]["best_multiplier"] == 18.4, f"查询排行榜：{data}")
        ok, data, _ = sb.insert("slot_scores", {"game_id": "lucky_fruits", "player": "p", "best_multiplier": 9})
        check(ok and data[0]["id"] == 1, f"写入成绩：{data}")
        down = SupabaseClient("http://127.0.0.1:9", "k")  # 关闭端口模拟「项目已暂停」
        ok, detail = down.ping()
        check(not ok and "不可达" in detail, f"项目暂停时降级为不可达提示：{detail[:30]}")

        print("== Cloudflare Pages 直传 ==")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "site"
            (root / "games").mkdir(parents=True)
            (root / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
            (root / "games" / "a.html").write_text("x", encoding="utf-8")
            (root / "games" / "b.html").write_text("y", encoding="utf-8")
            files = collect_files(root)
            check(set(files) == {"index.html", "games/a.html", "games/b.html"}, f"收集目录文件：{sorted(files)}")
            manifest = build_manifest(files)
            check(all(k.startswith("/") for k in manifest), "manifest 以 / 开头的路径为键")
            ctype, body = build_multipart(files, manifest)
            check(ctype.startswith("multipart/form-data; boundary="), "multipart 头带 boundary")
            check(b'name="manifest"' in body and b'filename="index.html"' in body, "包含 manifest 与文件部件")

        cf = CloudflareClient("cfat_x", "acct1", base_url=base)
        project, state = cf.ensure_project("slot-games")
        check(state == "created" and project["name"] == "slot-games", f"ensure_project 创建：{state}")
        ok, status, payload = cf.deploy("slot-games", {"index.html": b"<h1>hi</h1>"})
        check(ok and payload["result"]["id"] == "dep-1", f"直传部署返回部署 ID：{payload.get('result')}")
        check(STATE.get("deploy_files", 0) >= 2, f"multipart 含 manifest + 文件部件（{STATE.get('deploy_files')}）")
        check(
            CloudflareClient.project_url({"name": "slot-games", "subdomain": "slot-games.pages.dev"})
            == "https://slot-games.pages.dev",
            "项目地址取自 subdomain",
        )

        print("== GitHub Pages ==")
        gh = GitHubClient("ghp_x", base_url=base)
        check(gh.login() == "vip-4", f"读取账号：{gh.login()}")
        repo, state = gh.ensure_repo("slot-games")
        check(state == "exists" and repo["full_name"].endswith("/slot-games"), f"ensure_repo：{state}")
        ok, status, payload = gh.enable_pages("vip-4/slot-games", "main", "/")
        check(ok and STATE["pages_body"]["source"]["branch"] == "main", f"开启 Pages 请求体：{STATE['pages_body']}")
        check(GitHubClient.pages_url("Vip-4", "slot-games") == "https://vip-4.github.io/slot-games/", "Pages 地址小写化")

        print("== Metaso GEO 监测 ==")
        ms = MetasoClient("k", base_url=base)
        report = ms.site_report("https://vip882.gitee.io/slot-games", "测试")
        check(report["indexed"] is True and report["matched"] == 1, "识别出本站命中条目")
        check(report["total"] == 2 and report["summary"] == "这是 AI 摘要", "统计总条数与 AI 摘要")
        bad = ms.site_report("https://other.example", "测试")
        check(bad["indexed"] is False and bad["matched"] == 0, "未命中本站时 indexed=False")
        broken = MetasoClient("k", base_url=f"{base}/nope")
        err = broken.site_report("https://x.example", "测试")
        check(err["error"] != "", "接口失败时返回结构化错误而非抛异常")

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
