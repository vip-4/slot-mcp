"""抓取机台主题配图（Pexels 优先，Pixabay 回退）。

    python -m slotmcp.tools.fetch_media                # 抓取全部机台
    python -m slotmcp.tools.fetch_media --only lucky_fruits dragon_palace
    python -m slotmcp.tools.fetch_media --dry-run      # 只打印将抓取的检索词

产物：
    static/assets/img/<game>-hero.jpg   960×540  页面主图 / 列表缩略图
    static/assets/img/<game>-og.jpg    1200×630 Open Graph / Twitter Card
    deploy/media.json                   素材清单（来源、作者、许可、尺寸、字节数）
    static/assets/img/CREDITS.md        署名与许可声明（随站点一起发布）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from slotmcp.services.media import (  # noqa: E402
    HERO_SIZE,
    OG_SIZE,
    PixabayClient,
    PexelsClient,
    THEME_QUERIES,
    fetch_theme_image,
)

# 写入 web_static（手写源码目录），构建时随其它源码一起拷入 static/，保证 static/ 可一键重建
IMG_DIR = ROOT / "web_static" / "assets" / "img"
MANIFEST = ROOT / "deploy" / "media.json"


def load_keys() -> Dict[str, str]:
    keys = {"pexels": os.getenv("PEXELS_API_KEY", ""), "pixabay": os.getenv("PIXABAY_API_KEY", "")}
    for name in ("deploy/services.json", "deploy/services.local.json"):
        path = ROOT / name
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            media = raw.get("media", {}) or {}
            keys["pexels"] = keys["pexels"] or media.get("pexels_api_key", "")
            keys["pixabay"] = keys["pixabay"] or media.get("pixabay_api_key", "")
    return keys


def game_ids() -> List[str]:
    data_file = ROOT / "static" / "data" / "games.json"
    if not data_file.is_file():
        return list(THEME_QUERIES)
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    return [g["id"] for g in payload.get("games", [])] or list(THEME_QUERIES)


def write_credits(entries: List[Dict[str, Any]], path: Path) -> None:
    lines = [
        "# 图片素材署名",
        "",
        "本站机台主题配图来自 Pexels / Pixabay，均遵循各自的免费商用许可。",
        "若你是素材作者且不希望被使用，请通过仓库 Issue 联系，我们会立即下架。",
        "",
        "| 机台 | 用途 | 作者 | 来源 | 许可 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for e in entries:
        for kind, info in (e.get("files") or {}).items():
            lines.append(
                f"| {e['game']} | {kind} | {e.get('author') or '—'} | {e.get('page_url','')} | {e.get('license','')} |"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="抓取机台主题配图")
    ap.add_argument("--only", nargs="*", default=None, help="只抓取指定机台")
    ap.add_argument("--dry-run", action="store_true", help="只打印检索词，不下载")
    ap.add_argument("--out", default=str(IMG_DIR), help="图片输出目录")
    ap.add_argument("--manifest", default=str(MANIFEST), help="素材清单路径")
    args = ap.parse_args()

    keys = load_keys()
    ids = [g for g in game_ids() if not args.only or g in args.only]
    print(f"== 主题配图（输出 {args.out}） ==")

    if args.dry_run:
        for gid in ids:
            theme = THEME_QUERIES.get(gid, {})
            print(f"  [DRY] {gid}: pexels='{theme.get('pexels','')}' pixabay='{theme.get('pixabay','')}'")
        return 0

    if not keys["pexels"] and not keys["pixabay"]:
        print("  [NG] 未配置 PEXELS_API_KEY / PIXABAY_API_KEY（或 deploy/services.local.json 的 media 段）")
        return 1

    pexels = PexelsClient(keys["pexels"]) if keys["pexels"] else None
    pixabay = PixabayClient(keys["pixabay"]) if keys["pixabay"] else None
    out_dir = Path(args.out)

    entries: List[Dict[str, Any]] = []
    for gid in ids:
        entry = fetch_theme_image(gid, pexels=pexels, pixabay=pixabay, out_dir=out_dir)
        if not entry:
            print(f"  [NG] {gid}: 未获取到素材，页面将回退到程序生成图")
            continue
        sizes = "、".join(f"{k}={v['bytes'] // 1024}KB" for k, v in entry["files"].items())
        print(f"  [OK] {gid}: {entry['provider']} / {entry['author']}（{sizes}）")
        entries.append(entry)

    if entries:
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema": "slotmcp.media/1",
                    "hero": {"width": HERO_SIZE[0], "height": HERO_SIZE[1]},
                    "og": {"width": OG_SIZE[0], "height": OG_SIZE[1]},
                    "entries": entries,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        write_credits(entries, out_dir / "CREDITS.md")
        print(f"\n[OK] 素材清单 {manifest_path.relative_to(ROOT)}，署名表 {out_dir.name}/CREDITS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
