"""数据库同步 CLI：建表 / 记录部署审计 / 记录 RTP 回归 / 生成社区统计快照。

    python -m slotmcp.tools.db_sync --status            # 连通性（Neon + Supabase）
    python -m slotmcp.tools.db_sync --init              # 在两个 Neon 库建表
    python -m slotmcp.tools.db_sync --demo              # 写入一条示例数据验证链路
    python -m slotmcp.tools.db_sync --rtp 20000         # 跑仿真并把 RTP 结果写入库
    python -m slotmcp.tools.db_sync --snapshot          # 聚合 -> deploy/stats.json（构建期注入页面）

设计约束：**站点运行时不访问数据库**。数据库只服务于构建期与运维期，
聚合结果以静态 JSON 注入页面，因此发布产物依然是零后端依赖的纯静态站。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from slotmcp.services.neon import SCHEMA_STATEMENTS, NeonClient  # noqa: E402
from slotmcp.services.supabase import SupabaseClient, project_status  # noqa: E402

STATS_PATH = ROOT / "deploy" / "stats.json"


def load_db_config() -> Dict[str, str]:
    cfg = {
        "neon_url": os.getenv("NEON_DATABASE_URL", ""),
        "neon_mirror": os.getenv("NEON_DATABASE_URL_2", ""),
        "supabase_url": os.getenv("SUPABASE_URL", ""),
        "supabase_key": os.getenv("SUPABASE_KEY", ""),
        "supabase_ref": os.getenv("SUPABASE_REF", ""),
        "supabase_token": os.getenv("SUPABASE_ACCESS_TOKEN", ""),
    }
    for name in ("deploy/services.json", "deploy/services.local.json"):
        path = ROOT / name
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        neon = raw.get("neon", {}) or {}
        sb = raw.get("supabase", {}) or {}
        cfg["neon_url"] = cfg["neon_url"] or neon.get("database_url", "")
        cfg["neon_mirror"] = cfg["neon_mirror"] or neon.get("mirror_url", "")
        cfg["supabase_url"] = cfg["supabase_url"] or sb.get("url", "")
        cfg["supabase_key"] = cfg["supabase_key"] or sb.get("key", "")
        cfg["supabase_ref"] = cfg["supabase_ref"] or sb.get("ref", "")
        cfg["supabase_token"] = cfg["supabase_token"] or sb.get("access_token", "")
    return cfg


def neon_clients(cfg: Dict[str, str]) -> List[Tuple[str, NeonClient]]:
    out = []
    if cfg["neon_url"]:
        out.append(("primary", NeonClient(cfg["neon_url"])))
    if cfg["neon_mirror"]:
        out.append(("mirror", NeonClient(cfg["neon_mirror"])))
    return out


def record_deploy(site_url: str, checks: List[Dict[str, Any]], ok: bool, detail: str = "") -> List[str]:
    """把一次运维结果写入所有可用 Neon 库（部署审计）。"""
    cfg = load_db_config()
    payload = json.dumps(checks, ensure_ascii=False)[:2000]
    notes = []
    for label, client in neon_clients(cfg):
        ok_insert, err = client.insert(
            "slot_deploy_log",
            {
                "site_url": site_url,
                "checks": payload,
                "ok": ok,
                "detail": detail[:400],
            },
        )
        notes.append(f"{label}: {'已记录' if ok_insert else '失败 ' + err[:80]}")
    return notes


def run_rtp(spins: int) -> List[str]:
    """跑仿真并把每款机台的 RTP / 命中率写入库。"""
    from slotmcp.engine.game import get_registry

    cfg = load_db_config()
    registry = get_registry()
    notes = []
    results = []
    for gid in registry.ids():
        machine = registry.get(gid)
        total = 0.0
        hits = 0
        for _ in range(spins):
            res = machine.spin(total_bet=1.0)
            total += res.total_win
            if res.total_win > 0:
                hits += 1
        results.append({"game_id": gid, "spins": spins, "rtp": total / spins, "hit_rate": hits / spins})
    for label, client in neon_clients(cfg):
        done = 0
        for row in results:
            ok_insert, _ = client.insert(
                "slot_rtp_runs",
                {
                    "game_id": row["game_id"],
                    "spins": row["spins"],
                    "rtp": round(row["rtp"], 5),
                    "hit_rate": round(row["hit_rate"], 5),
                    "source": "python-sim",
                },
            )
            done += 1 if ok_insert else 0
        notes.append(f"{label}: 写入 {done}/{len(results)} 条 RTP 记录")
    return notes


def snapshot() -> Optional[Dict[str, Any]]:
    """聚合并写出 `deploy/stats.json`；无可用数据库时返回 None。"""
    cfg = load_db_config()
    clients = neon_clients(cfg)
    if not clients:
        return None
    label, client = clients[0]

    out: Dict[str, Any] = {
        "schema": "slotmcp.stats/1",
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": f"neon:{label}",
        "rtp": [],
        "top_scores": [],
        "players": 0,
        "deploy_runs": 0,
        "last_deploy": None,
        "sim_spins": 0,
    }

    ok, rows, _ = client.select(
        "select game_id, count(*) as runs, sum(spins) as spins, avg(rtp) as rtp "
        "from slot_rtp_runs group by game_id order by game_id"
    )
    if ok:
        for r in rows:
            out["rtp"].append(
                {
                    "game_id": r["game_id"],
                    "runs": int(r["runs"]),
                    "spins": int(r["spins"]),
                    "rtp": round(float(r["rtp"]), 4),
                }
            )
            out["sim_spins"] += int(r["spins"])

    ok, rows, _ = client.select(
        "select game_id, player, best_multiplier from slot_scores "
        "order by best_multiplier desc limit 5"
    )
    if ok:
        out["top_scores"] = [
            {
                "game_id": r["game_id"],
                "player": r["player"],
                "best_multiplier": float(r["best_multiplier"]),
            }
            for r in rows
        ]

    ok, rows, _ = client.select("select count(distinct player) as players from slot_scores")
    if ok and rows:
        out["players"] = int(rows[0]["players"])

    ok, rows, _ = client.select(
        "select site_url, ok, created_at from slot_deploy_log order by created_at desc limit 1"
    )
    if ok and rows:
        out["last_deploy"] = {
            "site_url": rows[0]["site_url"],
            "ok": bool(rows[0]["ok"]),
            "created_at": str(rows[0]["created_at"]),
        }
    ok, rows, _ = client.select("select count(*) as n from slot_deploy_log")
    if ok and rows:
        out["deploy_runs"] = int(rows[0]["n"])

    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def demo_data() -> List[str]:
    cfg = load_db_config()
    notes = []
    for label, client in neon_clients(cfg):
        ok, err = client.insert(
            "slot_scores",
            {"game_id": "lucky_fruits", "player": "pilot", "best_multiplier": 18.4},
        )
        notes.append(f"{label}: 示例成绩 {'已写入' if ok else '写入失败 ' + err[:80]}")
    return notes


def status() -> int:
    cfg = load_db_config()
    print("== Neon ==")
    for label, client in neon_clients(cfg):
        ok, rows, err = client.sql("select version()")
        version = rows[0]["version"][:40] if ok and rows else err[:80]
        print(f"  [{'OK' if ok else 'NG'}] {label}: {version}")
    if not neon_clients(cfg):
        print("  [!] 未配置 NEON_DATABASE_URL")

    print("== Supabase ==")
    if cfg["supabase_url"] and cfg["supabase_key"]:
        sb = SupabaseClient(cfg["supabase_url"], cfg["supabase_key"])
        ok, detail = sb.ping()
        print(f"  [{'OK' if ok else 'NG'}] REST: {detail}")
    else:
        print("  [!] 未配置 SUPABASE_URL / SUPABASE_KEY")
    if cfg["supabase_ref"] and cfg["supabase_token"]:
        ok, payload, err = project_status(cfg["supabase_ref"], cfg["supabase_token"])
        if ok:
            print(f"  [OK] 项目 {payload.get('name')} 状态 {payload.get('status')}（区域 {payload.get('region')}）")
        else:
            print(f"  [NG] 项目查询失败: {err}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="数据库同步：建表 / 审计 / RTP 回归 / 统计快照")
    ap.add_argument("--status", action="store_true", help="检查 Neon / Supabase 连通性")
    ap.add_argument("--init", action="store_true", help="在 Neon 库中建表")
    ap.add_argument("--demo", action="store_true", help="写入一条示例成绩")
    ap.add_argument("--rtp", type=int, nargs="?", const=20000, default=None, help="跑仿真并写入 RTP 记录")
    ap.add_argument("--snapshot", action="store_true", help="生成 deploy/stats.json")
    args = ap.parse_args()

    if args.status:
        return status()

    if args.init:
        for label, client in neon_clients(load_db_config()):
            print(f"== 建表 {label} ==")
            for stmt, ok, err in client.ensure_schema(SCHEMA_STATEMENTS):
                print(f"  [{'OK' if ok else 'NG'}] {stmt} {'' if ok else err[:60]}")
        return 0

    if args.demo:
        for note in demo_data():
            print(f"  {note}")
        return 0

    if args.rtp:
        for note in run_rtp(args.rtp):
            print(f"  {note}")
        return 0

    if args.snapshot:
        data = snapshot()
        if not data:
            print("  [NG] 未配置数据库（NEON_DATABASE_URL）")
            return 1
        print(f"  [OK] {STATS_PATH.relative_to(ROOT)}：仿真 {data['sim_spins']} 局 / "
              f"玩家 {data['players']} / 部署记录 {data['deploy_runs']}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
