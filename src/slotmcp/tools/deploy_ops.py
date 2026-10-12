"""静态站部署运维 CLI：健康检查 + 邮件报告 + 定时巡检 + PlayCanvas 三维同步。

用法（全部为可选动作，不带任何动作参数时只打印当前配置与站点事实）：

    python -m slotmcp.tools.deploy_ops --check
    python -m slotmcp.tools.deploy_ops --cron --interval 30
    python -m slotmcp.tools.deploy_ops --email vip880@agentmail.to
    python -m slotmcp.tools.deploy_ops --playcanvas --sync-scene
    python -m slotmcp.tools.deploy_ops --all --dry-run

凭证读取顺序：环境变量 > `deploy/services.local.json` > `deploy/services.json`。
（`services.local.json` 已在 .gitignore 中，凭证绝不入库。）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from slotmcp.services.agentmail import AgentMailClient  # noqa: E402
from slotmcp.services.carto import CartoClient  # noqa: E402
from slotmcp.services.marketstack import MarketstackClient  # noqa: E402
from slotmcp.services.weather import PirateWeatherClient  # noqa: E402
from slotmcp.services.cronjob import CronJobClient, every_n_minutes  # noqa: E402
from slotmcp.services.http import head_ok  # noqa: E402
from slotmcp.services.metaso import MetasoClient  # noqa: E402
from slotmcp.tools.db_sync import record_deploy  # noqa: E402
from slotmcp.services.playcanvas import (  # noqa: E402
    PlayCanvasClient,
    build_scene_descriptor,
    write_scene_descriptor,
)

STATIC_DIR = ROOT / "static"
DEFAULT_SITE_URL = "https://vip882.gitee.io/slot-games"

ENV_MAP = {
    "site_url": "SLOT_SITE_URL",
    "agentmail_key": "AGENTMAIL_API_KEY",
    "agentmail_inbox": "AGENTMAIL_INBOX",
    "agentmail_to": "AGENTMAIL_TO",
    "cronjob_key": "CRONJOB_API_KEY",
    "cronjob_interval": "CRONJOB_INTERVAL",
    "playcanvas_token": "PLAYCANVAS_TOKEN",
    "playcanvas_project": "PLAYCANVAS_PROJECT_ID",
    "metaso_key": "METASO_API_KEY",
    "carto_key": "CARTO_API_KEY",
    "carto_host": "CARTO_HOST",
    "weather_key": "PIRATE_WEATHER_API_KEY",
    "apilayer_key": "APILAYER_API_KEY",
}


def load_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "site_url": DEFAULT_SITE_URL,
        "agentmail_key": "",
        "agentmail_inbox": "hermes-h5@agentmail.to",
        "agentmail_to": [],
        "cronjob_key": "",
        "cronjob_interval": 30,
        "playcanvas_token": "",
        "playcanvas_project": 1583126,
        "playcanvas_scene": "Main Scene",
        "metaso_key": "",
        "metaso_query": "11 款免费在线老虎机 SLOT 合集 静态站",
        "carto_key": "",
        "carto_host": "https://gcp-us-east1.api.carto.com",
        "weather_key": "",
        "apilayer_key": "",
    }
    for name in ("deploy/services.json", "deploy/services.local.json"):
        path = ROOT / name
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            cfg["site_url"] = raw.get("site_url", cfg["site_url"])
            am = raw.get("agentmail", {}) or {}
            cfg["agentmail_key"] = am.get("api_key", cfg["agentmail_key"])
            cfg["agentmail_inbox"] = am.get("inbox", cfg["agentmail_inbox"])
            cfg["agentmail_to"] = am.get("to", cfg["agentmail_to"])
            cj = raw.get("cronjob", {}) or {}
            cfg["cronjob_key"] = cj.get("api_key", cfg["cronjob_key"])
            cfg["cronjob_interval"] = cj.get("interval_minutes", cfg["cronjob_interval"])
            pc = raw.get("playcanvas", {}) or {}
            cfg["playcanvas_token"] = pc.get("token", cfg["playcanvas_token"])
            cfg["playcanvas_project"] = pc.get("project_id", cfg["playcanvas_project"])
            cfg["playcanvas_scene"] = pc.get("scene", cfg["playcanvas_scene"])
            ms = raw.get("metaso", {}) or {}
            cfg["metaso_key"] = ms.get("api_key", cfg["metaso_key"])
            cfg["metaso_query"] = ms.get("query", cfg["metaso_query"])
            carto = raw.get("carto", {}) or {}
            cfg["carto_key"] = carto.get("api_key", cfg["carto_key"])
            cfg["carto_host"] = carto.get("host", cfg["carto_host"])
            sources = raw.get("datasources", {}) or {}
            cfg["weather_key"] = sources.get("weather_key", cfg["weather_key"])
            cfg["apilayer_key"] = sources.get("apilayer_key", cfg["apilayer_key"])

    for key, env in ENV_MAP.items():
        val = os.getenv(env)
        if val:
            if key in ("cronjob_interval", "playcanvas_project"):
                cfg[key] = int(val)
            elif key == "agentmail_to":
                cfg[key] = [x.strip() for x in val.split(",") if x.strip()]
            else:
                cfg[key] = val
    return cfg


def site_facts() -> Dict[str, Any]:
    """从已生成的静态站读取事实（页面数、机台名、数据体积）。"""
    facts: Dict[str, Any] = {"pages": 0, "games": [], "data_bytes": 0, "built": False}
    data_path = STATIC_DIR / "data" / "games.json"
    if data_path.is_file():
        facts["built"] = True
        facts["data_bytes"] = data_path.stat().st_size
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        facts["games"] = [g.get("name", g.get("id", "?")) for g in payload.get("games", [])]
    sitemap = STATIC_DIR / "sitemap.xml"
    if sitemap.is_file():
        root = ET.fromstring(sitemap.read_text(encoding="utf-8"))
        facts["pages"] = len(list(root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")))
    return facts


def run_checks(site_url: str) -> List[Dict[str, Any]]:
    targets = [
        ("首页", f"{site_url}/index.html"),
        ("站点地图", f"{site_url}/sitemap.xml"),
        ("robots", f"{site_url}/robots.txt"),
    ]
    out = []
    for label, url in targets:
        ok, status, seconds = head_ok(url)
        out.append({"label": label, "url": url, "ok": ok, "status": status, "seconds": seconds})
        print(f"  [{'OK' if ok else 'NG'}] {label:<6} {url} -> {status} ({seconds}s)")
    return out


def run_cron(cfg: Dict[str, Any], dry_run: bool, interval: Optional[int]) -> List[Dict[str, Any]]:
    minutes = int(interval or cfg["cronjob_interval"])
    schedule = every_n_minutes(minutes)
    plan = [
        {"title": "SLOT 静态站可用性巡检", "url": f"{cfg['site_url']}/index.html"},
        {"title": "SLOT 静态站 sitemap 巡检", "url": f"{cfg['site_url']}/sitemap.xml"},
    ]
    summary: List[Dict[str, Any]] = []
    if dry_run or not cfg["cronjob_key"]:
        for p in plan:
            print(f"  [DRY] {p['title']} -> {p['url']} (每 {minutes} 分钟)")
            summary.append({**p, "state": "dry-run", "schedule": f"每 {minutes} 分钟"})
        return summary

    # 站点还没上线时先创建为「停用」，避免 Pages 未开启期间持续告警；上线后再执行本命令会自动启用
    reachable, status, _ = head_ok(f"{cfg['site_url']}/index.html")
    enabled = reachable
    if not reachable:
        print(f"  [!] 首页当前不可达（HTTP {status}），巡检任务将创建为停用状态")

    client = CronJobClient(cfg["cronjob_key"])
    for p in plan:
        res = client.upsert(title=p["title"], url=p["url"], schedule=schedule, enabled=enabled)
        res = {**p, **res, "schedule": f"每 {minutes} 分钟"}
        summary.append(res)
        print(f"  [{res['state']}] {p['title']} -> {p['url']} (jobId={res.get('jobId')})")
    return summary


def run_playcanvas(cfg: Dict[str, Any], dry_run: bool, sync_scene: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {"project": str(cfg["playcanvas_project"])}
    if dry_run or not cfg["playcanvas_token"]:
        print(f"  [DRY] 读取项目 {cfg['playcanvas_project']} 的场景与资产清单")
        out["state"] = "dry-run"
    else:
        client = PlayCanvasClient(cfg["playcanvas_token"])
        out.update(client.summary(int(cfg["playcanvas_project"])))
        out["state"] = "ok" if not out.get("error") else "degraded"
        print(f"  [{out['state']}] 项目 {cfg['playcanvas_project']}: {out.get('scenes', 0)} 场景 / {out.get('assets', 0)} 资产")
        if out.get("error"):
            print(f"         降级提示: {out['error']}")

    if sync_scene:
        data_path = STATIC_DIR / "data" / "games.json"
        games = json.loads(data_path.read_text(encoding="utf-8"))["games"] if data_path.is_file() else []
        descriptor = build_scene_descriptor(
            project_id=int(cfg["playcanvas_project"]),
            games=games,
            scene_name=cfg["playcanvas_scene"],
        )
        target = ROOT / "deploy" / "playcanvas_scene.json"
        write_scene_descriptor(descriptor, target)
        out["scene_descriptor"] = str(target.relative_to(ROOT))
        out["machines"] = len(descriptor["machines"])
        print(f"  [OK] 场景描述已写入 {out['scene_descriptor']}（{len(descriptor['machines'])} 台机台）")
    return out


def run_db(cfg: Dict[str, Any], dry_run: bool, checks: List[Dict[str, Any]]) -> List[str]:
    """把本次运维结果写入 Neon（部署审计），站点本身不依赖数据库。"""
    if dry_run:
        return ["[DRY] 将记录 1 条部署审计（Neon）"]
    try:
        notes = record_deploy(
            cfg["site_url"],
            checks,
            all(c["ok"] for c in checks) if checks else True,
            f"页面 {len(checks)} 项检查",
        )
    except Exception as exc:  # noqa: BLE001
        # 数据库不可用时不能拖垮部署：记录为降级说明
        return [f"降级：数据库不可用（{type(exc).__name__}）"]
    if not notes:
        notes = ["未配置 NEON_DATABASE_URL，跳过审计记录"]
    for note in notes:
        print(f"  {note}")
    return notes


def run_sources(cfg: Dict[str, Any], dry_run: bool) -> List[Dict[str, Any]]:
    """外部数据源可用性监测（CARTO / Pirate Weather / marketstack）。

    这些数据源与机台主题无关，**不写入站点内容**（混入会稀释 SEO/GEO 焦点），
    只作为运维依赖体检，结果进部署报告。任一不可用都降级为说明，不影响部署。
    """
    plan = []
    if cfg.get("carto_key"):
        plan.append(("CARTO（空间数据）", "carto"))
    if cfg.get("weather_key"):
        plan.append(("Pirate Weather（天气）", "weather"))
    if cfg.get("apilayer_key"):
        plan.append(("marketstack（行情，APILayer）", "marketstack"))
    if not plan:
        print("  （未配置任何数据源凭证）")
        return []

    if dry_run:
        for name, _ in plan:
            print(f"  [DRY] 将检测 {name}")
        return [{"name": n, "ok": None, "detail": "dry-run"} for n, _ in plan]

    results: List[Dict[str, Any]] = []
    for name, kind in plan:
        try:
            if kind == "carto":
                client = CartoClient(cfg["carto_key"], host=cfg.get("carto_host", "") or CartoClient.DEFAULT_HOST)
                state = client.status()
                results.append({"name": name, **state})
            elif kind == "weather":
                client = PirateWeatherClient(cfg["weather_key"])
                state = client.summarize(39.9042, 116.4074)
                results.append({"name": name, **state})
            else:
                client = MarketstackClient(cfg["apilayer_key"])
                state = client.status()
                results.append({"name": name, **state})
        except Exception as exc:  # noqa: BLE001
            results.append({"name": name, "ok": False, "detail": f"客户端异常: {type(exc).__name__}"})
    for r in results:
        flag = "OK" if r.get("ok") else "NG"
        extra = f"（{r.get('close')} @ {r.get('date')}）" if r.get("ok") and r.get("close") else ""
        print(f"  [{flag}] {r['name']}: {r.get('detail','')}{extra}")
    return results


def run_geo(cfg: Dict[str, Any], dry_run: bool) -> Dict[str, Any]:
    """GEO 监测：问一次 AI 搜索，看站点是否被收录、摘要怎么描述。"""
    if dry_run or not cfg["metaso_key"]:
        print(f"  [DRY] 查询「{cfg['metaso_query']}」的收录与 AI 摘要")
        return {"query": cfg["metaso_query"], "state": "dry-run"}
    client = MetasoClient(cfg["metaso_key"])
    report = client.site_report(cfg["site_url"], cfg["metaso_query"])
    flag = "OK" if report["indexed"] else "NG"
    print(f"  [{flag}] 「{report['query']}」命中本站 {report['matched']}/{report.get('total', 0)} 条")
    for hit in report["hits"][:3]:
        mark = "*" if hit["own"] else " "
        print(f"        [{mark}] {hit['title'][:44]} -> {hit['link']}")
    if report.get("summary"):
        print(f"        AI 摘要: {report['summary'][:120]}")
    if report.get("error"):
        print(f"        失败原因: {report['error']}")
    return report


def run_email(
    cfg: Dict[str, Any],
    recipients: List[str],
    dry_run: bool,
    checks: List[Dict[str, Any]],
    cron: List[Dict[str, Any]],
    playcanvas: Dict[str, Any],
    facts: Dict[str, Any],
    geo: Optional[Dict[str, Any]] = None,
    db: Optional[List[str]] = None,
    sources: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    to = recipients or list(cfg["agentmail_to"])
    subject = f"[Slot MCP] 静态站部署报告 · {cfg['site_url']}"
    body = AgentMailClient.render_report(
        site_url=cfg["site_url"],
        pages=facts["pages"],
        games=facts["games"],
        checks=checks,
        cron=cron,
        playcanvas=playcanvas,
        geo=geo,
        db=db,
        sources=sources,
    )
    if not to:
        print("  [NG] 未指定收件人（用 --email 或配置 agentmail.to / AGENTMAIL_TO）")
        return {"state": "no-recipient"}
    if dry_run or not cfg["agentmail_key"]:
        for addr in to:
            print(f"  [DRY] {subject} -> {addr}")
        return {"state": "dry-run", "to": to}

    client = AgentMailClient(cfg["agentmail_key"], cfg["agentmail_inbox"])
    ok, status, payload = client.send(to=to, subject=subject, text=body)
    state = "sent" if ok else "failed"
    print(f"  [{state}] {subject} -> {', '.join(to)} (HTTP {status})")
    if not ok:
        print(f"         失败原因: {payload}")
    return {"state": state, "to": to, "status": status, "detail": payload if not ok else ""}


def main() -> int:
    ap = argparse.ArgumentParser(description="静态站部署运维：巡检 / 邮件 / 定时任务 / PlayCanvas")
    ap.add_argument("--site-url", default=None, help="站点绝对地址（覆盖配置）")
    ap.add_argument("--check", action="store_true", help="对首页 / sitemap / robots 做健康检查")
    ap.add_argument("--cron", action="store_true", help="幂等创建或更新 cron-job.org 巡检任务")
    ap.add_argument("--interval", type=int, default=None, help="巡检间隔（分钟，默认 30）")
    ap.add_argument("--email", nargs="*", default=None, help="发送部署报告到指定邮箱（不带值则用配置）")
    ap.add_argument("--playcanvas", action="store_true", help="读取 PlayCanvas 项目清单")
    ap.add_argument("--sync-scene", action="store_true", help="导出机台场景描述 JSON")
    ap.add_argument("--geo", action="store_true", help="用 Metaso 检查 AI 搜索收录与摘要（GEO 监测）")
    ap.add_argument("--sources", action="store_true", help="检测外部数据源可用性（CARTO / 天气 / marketstack）")
    ap.add_argument("--db", action="store_true", help="把本次运维结果写入 Neon（部署审计）")
    ap.add_argument("--all", action="store_true", help="执行全部动作")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划动作，不调用外部服务")
    args = ap.parse_args()

    cfg = load_config()
    if args.site_url:
        cfg["site_url"] = args.site_url.rstrip("/")
    do_all = args.all

    facts = site_facts()
    print("== 站点事实 ==")
    print(f"  站点地址: {cfg['site_url']}")
    print(f"  构建产物: {'已生成' if facts['built'] else '缺失（先运行 tools/build_static.py）'}")
    print(f"  页面数量: {facts['pages']}    机台: {len(facts['games'])}    数据: {facts['data_bytes']} B")

    checks: List[Dict[str, Any]] = []
    cron: List[Dict[str, Any]] = []
    playcanvas: Dict[str, Any] = {}
    geo: Dict[str, Any] = {}
    db: List[str] = []
    sources: List[Dict[str, Any]] = []

    if args.check or do_all:
        print("\n== 健康检查 ==")
        checks = run_checks(cfg["site_url"])
    if args.cron or do_all:
        print("\n== 定时任务（cron-job.org） ==")
        cron = run_cron(cfg, args.dry_run, args.interval)
    if (args.playcanvas or args.sync_scene) or do_all:
        print("\n== PlayCanvas 三维项目 ==")
        playcanvas = run_playcanvas(cfg, args.dry_run, args.sync_scene)
    if args.geo or do_all:
        print("\n== GEO 监测（Metaso） ==")
        geo = run_geo(cfg, args.dry_run)
    if args.sources or do_all:
        print("\n== 外部数据源 ==")
        sources = run_sources(cfg, args.dry_run)
    if args.db or do_all:
        print("\n== 数据库审计（Neon） ==")
        db = run_db(cfg, args.dry_run, checks)
    if args.email is not None or do_all:
        print("\n== 邮件报告（AgentMail） ==")
        run_email(cfg, args.email or [], args.dry_run, checks, cron, playcanvas, facts, geo, db, sources)

    failed = [c for c in checks if not c["ok"]] + [j for j in cron if j.get("state") == "failed"]
    print()
    print("[OK] 部署运维动作完成" if not failed else f"[NG] 存在失败项：{len(failed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
