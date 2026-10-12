"""静态生产站自测：SEO / GEO 元数据、结构化数据、可索引内容、配置数据一致性。"""

import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from slotmcp.engine.config import GameConfig  # noqa: E402

FAILS = 0
TESTS = 0


def check(cond: bool, msg: str) -> None:
    global FAILS, TESTS
    TESTS += 1
    if cond:
        print(f"  [OK] {msg}")
    else:
        FAILS += 1
        print(f"  [NG] {msg}")


def jsonld_blocks(html: str):
    """返回页面内所有 JSON-LD 节点（支持单对象与数组两种写法）。"""
    out = []
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        parsed = json.loads(m.group(1))
        if isinstance(parsed, list):
            out.extend(parsed)
        else:
            out.append(parsed)
    return out


def main() -> int:
    print("== 静态站生成 ==")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "site"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build_static.py"), "--site-url", "https://example.com", "--out", str(out)],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env={"PYTHONPATH": str(ROOT / "src"), "PATH": __import__("os").environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"},
        )
        check(proc.returncode == 0, f"build_static.py 执行成功（{proc.stderr.strip()[:120]}）")
        if proc.returncode != 0:
            return 1

        print("== 资源完整性 ==")
        for rel in [
            "index.html",
            "404.html",
            "robots.txt",
            "sitemap.xml",
            "llms.txt",
            "manifest.webmanifest",
            "data/games.json",
            "js/engine.js",
            "js/app.js",
            "assets/styles.css",
            "assets/favicon.svg",
            "assets/og-image.png",
            "assets/icon-192.png",
        ]:
            check((out / rel).is_file(), f"存在 {rel}")

        data = json.loads((out / "data" / "games.json").read_text(encoding="utf-8"))
        games = data["games"]
        check(len(games) == 11, f"导出 11 款机台配置（实际 {len(games)}）")
        bad = []
        for raw in games:
            errs = GameConfig.from_dict(raw).validate()
            if errs:
                bad.append(f"{raw['id']}: {errs[:2]}")
        check(not bad, f"导出的配置可通过校验（{bad}）")
        check(
            all("expanded" in rs for g in games for rs in g["reel_sets"].values()),
            "每条条带集合都带 expanded 虚拟条带（保证前后端数学一致）",
        )

        print("== 首页 SEO / GEO ==")
        html = (out / "index.html").read_text(encoding="utf-8")
        for token in [
            '<html lang="zh-CN">',
            'rel="canonical"',
            'name="description"',
            'name="keywords"',
            'name="robots"',
            'property="og:title"',
            'property="og:description"',
            'property="og:image"',
            'property="og:url"',
            'property="og:type"',
            'name="twitter:card"',
            'name="twitter:image"',
        ]:
            check(token in html, f"首页包含 {token}")
        for tag in ["<title>", "<h1", "<main", "<article", "<header", "<footer", "skip-link", "aria-live"]:
            check(tag in html, f"语义化结构包含 {tag}")

        types = [b.get("@type") for b in jsonld_blocks(html)]
        for t in ["WebSite", "Organization", "ItemList", "SoftwareApplication", "FAQPage", "BreadcrumbList"]:
            check(t in types, f"JSON-LD 包含 {t}")
        blocks = jsonld_blocks(html)
        faq = next(b for b in blocks if b.get("@type") == "FAQPage")
        check(len(faq["mainEntity"]) >= 5, f"FAQ 结构化数据条数 {len(faq['mainEntity'])}")

        check('loading="lazy"' in html and 'decoding="async"' in html, "列表配图使用懒加载与异步解码")
        check(html.count('alt="') >= 5, "配图均带 alt 替代文本（图片 SEO + 可访问性）")

        # 不执行 JS 即可读到的可索引事实（GEO）
        for token in ["要点速览", "机台参数对比", "术语表", "常见问题", "赔付表"]:
            check(token in html, f"静态正文包含「{token}」")
        check(html.count("<table") >= 2, "首页含静态表格（对比表 + 赔付表）")

        print("== 机台详情页 ==")
        for g in games:
            page = out / "games" / f"{g['id']}.html"
            check(page.is_file(), f"详情页存在 games/{g['id']}.html")
            text = page.read_text(encoding="utf-8")
            check(f'>{g["name"]}' in text, f"{g['id']}: 正文含机台名")
            check('rel="canonical"' in text and 'property="og:image"' in text, f"{g['id']}: canonical 与 OG 完整")
            gt = [b.get("@type") for b in jsonld_blocks(text)]
            check("SoftwareApplication" in gt and "BreadcrumbList" in gt, f"{g['id']}: JSON-LD 类型 {gt}")
            hero = out / "assets" / "img" / f"{g['id']}-og.jpg"
            if hero.is_file():
                check(f'assets/img/{g["id"]}-og.jpg' in text, f"{g['id']}: og:image 指向主题图")
                check('class="game-hero"' in text and "<figcaption" in text, f"{g['id']}: 主图带 figure + figcaption")
                check('rel="preload" as="image"' in text, f"{g['id']}: 主图 preload（优化 LCP）")
                app = next(b for b in jsonld_blocks(text) if b.get("@type") == "SoftwareApplication")
                check("image" in app, f"{g['id']}: SoftwareApplication 带 image 字段")
        check((out / "assets" / "img" / "CREDITS.md").is_file(), "存在图片署名文件 assets/img/CREDITS.md")

        print("== 爬虫配套 ==")
        robots = (out / "robots.txt").read_text(encoding="utf-8")
        check("Sitemap: https://example.com/sitemap.xml" in robots, "robots.txt 含 Sitemap 声明")
        root = ET.fromstring((out / "sitemap.xml").read_text(encoding="utf-8"))
        urls = [u.text for u in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
        check(len(urls) == 12, f"sitemap.xml 含 12 条 URL（实际 {len(urls)}）")
        llms = (out / "llms.txt").read_text(encoding="utf-8")
        check("## 关键事实" in llms and "## 机台" in llms, "llms.txt 含 AI 摘要结构")

        # 数据库统计快照（若存在）：必须静态注入，站点运行时不查库
        stats_file = ROOT / "deploy" / "stats.json"
        if stats_file.is_file():
            print("== 数据库统计快照（静态注入） ==")
            stats = json.loads(stats_file.read_text(encoding="utf-8"))
            check('id="stats"' in html and "仿真局数" in html, "统计快照以静态 HTML 注入首页")
            check("不会在运行时访问数据库" in html, "页面声明运行时不访问数据库")
            for row in stats.get("rtp", [])[:1]:
                check(f"{float(row['rtp']) * 100:.2f}%" in html, f"{row['game_id']} 实测 RTP 出现在页面中")
            check("验证数据" in llms, "llms.txt 含验证数据摘要")

        print("== PNG 资源 ==")
        png = (out / "assets" / "og-image.png").read_bytes()
        check(png[:8] == b"\x89PNG\r\n\x1a\n", "og-image.png 为合法 PNG")
        width = int.from_bytes(png[16:20], "big")
        height = int.from_bytes(png[20:24], "big")
        check((width, height) == (1200, 630), f"og-image.png 尺寸 {width}x{height}")

    print()
    print(f"静态站自测：{TESTS - FAILS}/{TESTS} 通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
