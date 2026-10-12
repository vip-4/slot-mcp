"""生成可直接静态托管的站点（static/ 目录）。

设计要点
--------
* **单一数据源**：机台配置来自 Python 侧 `slotmcp.games`，导出为 `data/games.json`，
  前端 `js/engine.js` 与 Python 引擎语义等价，页面无需任何后端接口。
* **SEO**：每页具备 title / description / keywords / canonical / robots / Open Graph /
  Twitter Card，并输出 JSON-LD（WebSite + SoftwareApplication + ItemList + BreadcrumbList + FAQPage）。
* **GEO（生成式引擎优化）**：要点速览、机台对比表、术语表、FAQ 全部以**静态 HTML**输出，
  爬虫与 AI 摘要无需执行 JavaScript 即可读到完整事实；额外输出 `llms.txt` 便于 AI 引用。
* **性能 / 可访问性**：单 CSS + 两个 defer 脚本、无外部请求；语义化标签、跳转链接、
  `aria-live` 播报、`prefers-reduced-motion` 支持。

用法：
    python tools/build_static.py                    # 生成到 static/
    python tools/build_static.py --site-url https://example.com
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zlib
from datetime import date
from html import escape
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from slotmcp.engine.game import get_registry  # noqa: E402
from slotmcp.engine.reels import ReelStripSet  # noqa: E402

OUT_DIR = ROOT / "static"
# 手写前端源码（引擎 / 交互 / 样式），构建时原样拷入输出目录
SRC_DIR = ROOT / "web_static"
DEFAULT_SITE_URL = "https://vip882.gitee.io/slot-games"

SITE_NAME = "Blender SLOT 游戏合集"
SITE_TAGLINE = "6 款免费在线老虎机 · 纯静态 · 无需下载"
ORG_NAME = "Blender Slot MCP"
BUILD_DATE = date.today().isoformat()

# 实测 RTP（每机台 20 万局蒙特卡洛，由 `python -m slotmcp.tools.verify_rtp -n 200000` 得出）
MEASURED_RTP = {
    "lucky_fruits": 0.9708,
    "candy_carnival": 0.9704,
    "dragon_palace": 0.9720,
    "pharaoh_tomb": 0.9540,
    "star_expedition": 0.9578,
    "fortune_koi": 0.9676,
}

VOL_CN = {"low": "低", "medium": "中", "medium-high": "中高", "high": "高"}

FEATURE_CN = {
    "free_spins": "免费旋转",
    "hold_win": "Hold & Win 宝箱重转",
    "cascade": "级联（雪崩）连击",
    "expanding_wild": "扩展 Wild + 锁轴重转",
    "gamble": "红黑翻倍博彩",
    "random_wild": "随机 Wild 投放",
    "collect": "Cash Collect 金币收集",
}

GAME_COPY = {
    "lucky_fruits": {
        "summary": "幸运水果是最容易上手的一款：3×3 网格、5 条固定赔付线，从左至右三连即中奖，"
        "Wild 可替代任意水果符号。中奖后还能进入红黑翻倍博彩，把奖金最多连翻 5 次。",
        "best_for": "新手入门、想要低波动稳定回馈的玩家",
    },
    "candy_carnival": {
        "summary": "糖果狂欢采用 5×3 网格与 20 条赔付线。彩虹 Wild 一旦落在第 3 轴就整列扩展，"
        "并赠送一次锁轴重转，扩展后的 Wild 列保持锁定参与结算。",
        "best_for": "喜欢中等波动与整列扩展爽感的玩家",
    },
    "dragon_palace": {
        "summary": "龙宫探宝采用少见的 5×4 网格与 50 条赔付线。3 个及以上龙宫 Scatter 即可触发免费旋转，"
        "倍率随旋转次数递增；免费旋转期间第 3 轴出现的 Wild 会持续锁定到特性结束。",
        "best_for": "追求高波动、免费旋转递进倍率的玩家",
    },
    "pharaoh_tomb": {
        "summary": "法老之墓采用 5×3 与 243 Ways 全盘赔付，无需记线。全盘出现 8 个及以上金币符号时进入 "
        "Hold & Win：赏金符号被锁定，重转计数重置为 3，可开出 MINI / MINOR / MAJOR 奖池，集满全屏另有全屏大奖。",
        "best_for": "喜欢 Hold & Win 收集玩法与奖池的玩家",
    },
    "star_expedition": {
        "summary": "星际远征是体量最大的一款：6×4 网格、4096 Ways。中奖符号消除后上方符号坠落形成级联，"
        "级联倍率逐级递增；黑洞 Scatter 触发免费旋转，配合级联可在单局内叠加出高倍率。",
        "best_for": "喜欢级联连击与超多通路的玩家",
    },
    "fortune_koi": {
        "summary": "锦鲤纳福采用 5×3 网格与 20 条赔付线。锦鲤 Wild 会随机跃入水面（每局以权重投放 0~3 枚），"
        "并作为「收集者」把屏上全部金币面值一次性收入囊中；莲花 Scatter 触发 8/12/16 次免费旋转，"
        "免费旋转内币值更密且收集倍率翻倍。",
        "best_for": "喜欢 Cash Collect 收集玩法与中等偏高波动的玩家",
    },
}

FAQ = [
    {
        "q": "这些老虎机游戏是完全免费的吗？",
        "a": "是的。6 款机台全部免费、无需注册、无需下载，打开网页即可游玩，游戏内使用的是虚拟积分，不涉及任何真实货币。",
    },
    {
        "q": "RTP（返还率）是多少？",
        "a": "六款机台的目标 RTP 均为 96%。以每机台 20 万局蒙特卡洛仿真实测，实际 RTP 落在 95.40% 至 97.20% 之间，"
        "具体数值见本页「机台参数对比」表。",
    },
    {
        "q": "需要在手机上安装 App 吗？",
        "a": "不需要。站点是纯静态网页，只用到 HTML、CSS 与少量 JavaScript，桌面与移动浏览器均可直接运行，离线缓存后也可继续游玩。",
    },
    {
        "q": "游戏数据会上传到服务器吗？",
        "a": "不会。所有对局都在浏览器本地完成计算，积分保存在浏览器 localStorage 中，页面不发起任何数据上报请求。",
    },
    {
        "q": "老虎机的赔付是怎么判定的？",
        "a": "固定线机台（幸运水果、糖果狂欢、龙宫探宝、锦鲤纳福）按赔付线从左至右逐轴连续匹配；"
        "全盘 Ways 机台（法老之墓、星际远征）按相邻轴出现次数相乘得到通路数。Scatter 按全盘个数赔付，单位与总注挂钩；"
        "锦鲤纳福另有 Cash Collect：屏上出现锦鲤 Wild 时，按总注倍数收集全部金币面值。",
    },
    {
        "q": "能不能自己调整赔率或加新机台？",
        "a": "可以。全部机台由同一套 CONFIG 引擎驱动，新增一款机台只需新增一份配置（转轮条带、赔率表、线数、特性开关），"
        "引擎与前端无需改动；源码以 MIT 协议开源。",
    },
    {
        "q": "这个项目与 Blender 有什么关系？",
        "a": "同一套引擎通过 MCP（Model Context Protocol）对外暴露工具，Blender 侧插件可订阅旋转结果，"
        "在三维场景中驱动机台模型与转轮动画；网页版则是同一引擎的纯前端部署形态。",
    },
]

TERMS = [
    ("RTP（Return to Player）", "长期返还率。96% 表示理论上每投入 100 积分，长期平均返还 96 积分；单局结果仍完全随机。"),
    ("波动率（Volatility）", "描述奖金分布的离散程度。低波动小奖频繁，高波动大奖稀有但倍率高。"),
    ("赔付线（Payline）", "固定线机台上预先定义的符号连线，中奖需从最左侧轴开始连续匹配。"),
    ("Ways（全盘通路）", "不记线，只要相邻轴出现同一符号即中奖，通路数为各轴出现次数之积（如 243 Ways、4096 Ways）。"),
    ("Wild（百搭）", "可替代其它参与赔付的符号，部分机台还带有倍率或扩展、锁定效果。"),
    ("Scatter（ scatter 散落符号）", "按全盘出现个数赔付或触发免费旋转，不要求落在赔付线上。"),
    ("Hold & Win（宝箱重转）", "触发后锁定赏金符号并重置重转次数，每新增一个赏金符号都会延长重转，可开出固定奖池。"),
    ("Cash Collect（金币收集）", "屏上同时出现「收集者」（通常是 Wild）与币值符号时，一次性收取全部币值；币值以总注倍数计。"),
    ("随机 Wild 投放", "每局按权重在网格中随机投放若干 Wild，投放后仍参与线赔计算；常用于提升基础 game 的节奏感。"),
    ("级联（Cascade / 雪崩）", "中奖符号消除后上方符号坠落补位，形成一次投注多次结算，倍率逐级递增。"),
]

HOW_TO = [
    "在「机台」下拉框中选择一款主题（共 6 款）。",
    "在「每局总注」中选择投注额度，范围 0.20 至 100.00 积分。",
    "点击「旋转」或按空格键开始一局；点击「自动 10 次」可连续游玩。",
    "中奖符号会高亮，级联 / 重转 / 免费旋转 / Hold & Win 会按步骤依次播放。",
    "部分机台中奖后可进入红黑翻倍博彩，选择红或黑继续翻倍，或直接收下奖金。",
]


# --------------------------------------------------------------------------- 工具
def fmt_num(v: Any) -> str:
    f = float(v)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:.2f}"


def pay_mode_text(cfg) -> str:
    if cfg.pay_mode.value == "ways":
        return f"{cfg.ways()} Ways"
    return f"{len(cfg.paylines.lines)} 条赔付线"


def feature_names(cfg) -> List[str]:
    f = cfg.features
    out = []
    if f.free_spins:
        out.append("free_spins")
    if f.hold_win:
        out.append("hold_win")
    if f.cascade and f.cascade.enabled:
        out.append("cascade")
    if f.expanding_wild:
        out.append("expanding_wild")
    if f.gamble and f.gamble.enabled:
        out.append("gamble")
    return out


def feature_cn(cfg) -> List[str]:
    return [FEATURE_CN.get(k, k) for k in feature_names(cfg)]


def paytable_html(cfg) -> str:
    """服务端渲染赔付表，保证不执行 JS 的爬虫也能读到完整赔率。"""
    max_len = cfg.reels if cfg.pay_mode.value == "ways" else min(5, cfg.reels)
    heads = list(range(2, max_len + 1))
    rows: List[str] = []
    for sym in cfg.symbols.values():
        if sym.pays:
            cells = "".join(f"<td>{fmt_num(sym.pays.get(n, 0)) if sym.pays.get(n) else '—'}</td>" for n in heads)
            rows.append(
                f'<tr><th scope="row"><span class="sym" style="--sym:{sym.color}">{sym.glyph}</span>'
                f"{escape(sym.name)}</th>{cells}</tr>"
            )
    for sym in cfg.symbols.values():
        if sym.scatter_pays:
            cells = "".join(
                f"<td>{fmt_num(sym.scatter_pays.get(n, 0)) if sym.scatter_pays.get(n) else '—'}</td>" for n in heads
            )
            rows.append(
                f'<tr><th scope="row"><span class="sym" style="--sym:{sym.color}">{sym.glyph}</span>'
                f"{escape(sym.name)}（总注倍数）</th>{cells}</tr>"
            )
    head = "".join(f'<th scope="col">{n} 连</th>' for n in heads)
    unit = "通路注" if cfg.pay_mode.value == "ways" else "线注"
    return (
        f'<div class="table-scroll"><table class="paytable">'
        f"<caption>{escape(cfg.name)} 赔付表（单位：{unit}倍数）</caption>"
        f'<thead><tr><th scope="col">符号</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def load_media() -> Dict[str, Dict[str, Any]]:
    """读取 `deploy/media.json`（由 tools/fetch_media.py 生成）中的图片素材条目。"""
    path = ROOT / "deploy" / "media.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return {e["game"]: e for e in payload.get("entries", [])}


def load_stats() -> Optional[Dict[str, Any]]:
    """读取 `deploy/stats.json`（由 tools/db_sync.py 从数据库聚合而来）。"""
    path = ROOT / "deploy" / "stats.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def stats_section(stats: Optional[Dict[str, Any]], names: Dict[str, str]) -> str:
    """把数据库聚合结果渲染为**静态**事实段落（构建期注入，站点运行时不查库）。"""
    if not stats or not stats.get("rtp"):
        return ""
    rows = "".join(
        f"<tr><th scope=\"row\">{escape(names.get(r['game_id'], r['game_id']))}</th>"
        f"<td>{r['spins']:,}</td><td>{float(r['rtp']) * 100:.2f}%</td><td>{r['runs']}</td></tr>"
        for r in stats["rtp"]
    )
    tops = "".join(
        f"<li>{escape(s['player'])} · {escape(names.get(s['game_id'], s['game_id']))} · "
        f"{float(s['best_multiplier']):.1f}x</li>"
        for s in (stats.get("top_scores") or [])
    )
    generated = escape(str(stats.get("generated", "")))
    return f"""<section id="stats" aria-labelledby="stats-title">
  <h2 id="stats-title">验证与社区数据</h2>
  <p>以下数据由构建流水线从数据库聚合后<strong>静态注入</strong>页面（最近更新：<time>{generated}</time>），
     页面本身不会在运行时访问数据库。</p>
  <div class="table-scroll"><table>
    <caption>各机台仿真验证结果（累计 {stats.get('sim_spins', 0):,} 局）</caption>
    <thead><tr><th scope="col">机台</th><th scope="col">仿真局数</th><th scope="col">实测 RTP</th><th scope="col">批次</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  {f'<h3>社区最高倍率</h3><ol>{tops}</ol>' if tops else ''}
</section>"""


def media_image(entry: Optional[Dict[str, Any]], kind: str) -> Optional[Dict[str, Any]]:
    if not entry:
        return None
    return (entry.get("files") or {}).get(kind)


def jsonld(blocks: List[Dict[str, Any]]) -> str:
    return '<script type="application/ld+json">\n' + json.dumps(blocks, ensure_ascii=False, indent=2) + "\n</script>"


# --------------------------------------------------------------------------- 页面骨架
def head_html(
    *,
    title: str,
    description: str,
    keywords: str,
    canonical: str,
    og_image: str,
    jsonld_blocks: List[Dict[str, Any]],
    og_type: str = "website",
    body_class: str = "",
    prefix: str = "",
    preload_image: str = "",
    og_image_alt: str = "",
) -> str:
    image_alt = og_image_alt or SITE_TAGLINE
    site_url = canonical.rsplit("/", 1)[0] if canonical.endswith(".html") else canonical
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
<meta name="keywords" content="{escape(keywords)}">
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">
<meta name="author" content="{escape(ORG_NAME)}">
<meta name="theme-color" content="#0b0714">
<link rel="canonical" href="{canonical}">
<link rel="icon" href="{prefix}assets/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="{prefix}assets/icon-192.png">
<link rel="manifest" href="{prefix}manifest.webmanifest">
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="{escape(SITE_NAME)}">
<meta property="og:locale" content="zh_CN">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{og_image}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{escape(image_alt)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{escape(title)}">
<meta name="twitter:description" content="{escape(description)}">
<meta name="twitter:image" content="{og_image}">
<meta name="twitter:image:alt" content="{escape(image_alt)}">
<link rel="preload" href="{prefix}data/games.json" as="fetch" crossorigin="anonymous">
{f'<link rel="preload" as="image" href="{prefix}{preload_image}" fetchpriority="high">' if preload_image else ''}
<link rel="stylesheet" href="{prefix}assets/styles.css">
{jsonld(jsonld_blocks)}
</head>
<body{f' class="{body_class}"' if body_class else ''}>"""


def header_html(active_id: str, games: List[Dict[str, Any]], site_url: str, prefix: str = "") -> str:
    links = "".join(
        f'<li><a href="{prefix}games/{g["id"]}.html"{f" aria-current=\"page\"" if g["id"] == active_id else ""}>'
        f'{escape(g["name"])}</a></li>'
        for g in games
    )
    return f"""<a class="skip-link" href="#main">跳到主要内容</a>
<header class="site-header">
  <div class="wrap">
    <a class="brand" href="{prefix}index.html">
      <img src="{prefix}assets/favicon.svg" alt="" width="30" height="30">
      <span>SLOT 合集 · Blender MCP</span>
    </a>
    <nav class="nav" aria-label="主导航">
      <ul>
        <li><a href="{prefix}index.html"{' aria-current="page"' if active_id == "" else ""}>首页</a></li>
        {links}
      </ul>
    </nav>
  </div>
</header>"""


def footer_html(site_url: str = "", prefix: str = "") -> str:
    home = f"{prefix}index.html"
    return f"""<footer class="site-footer">
  <div class="wrap">
    <p><strong>{escape(SITE_NAME)}</strong> · {escape(SITE_TAGLINE)}。全部机台由同一套 CONFIG 引擎驱动，源码以 MIT 协议开源。</p>
    <ul>
      <li><a href="{home}">首页</a></li>
      <li><a href="{prefix}sitemap.xml">站点地图</a></li>
      <li><a href="{prefix}llms.txt">AI 摘要（llms.txt）</a></li>
      <li><a href="{prefix}robots.txt">robots.txt</a></li>
      <li><a href="{prefix}assets/img/CREDITS.md">图片署名</a></li>
    </ul>
    <p class="small">免责声明：本站为面向成年人的休闲娱乐与技术演示项目，使用虚拟积分，不涉及真实货币投注、充值或兑奖。</p>
    <p class="small">最后更新：<time datetime="{BUILD_DATE}">{BUILD_DATE}</time></p>
  </div>
</footer>"""


def cabinet_html(games: List[Dict[str, Any]], current_id: str) -> str:
    options = "".join(
        f'<option value="{g["id"]}"{" selected" if g["id"] == current_id else ""}>{escape(g["name"])}</option>'
        for g in games
    )
    return f"""<section id="play" aria-labelledby="play-title">
  <h2 id="play-title">开始游戏：<span id="play-game-name">—</span></h2>
  <div class="cabinet">
    <div class="cabinet-top">
      <p class="badge" id="feature-badge" role="status">基础旋转</p>
      <p>
        <label for="game-select">机台</label>
        <select id="game-select">{options}</select>
      </p>
    </div>
    <div id="reels" class="reels" aria-label="转轮网格" role="group"></div>
    <p id="win-line" class="win-line" aria-live="polite">正在加载机台配置…</p>
    <div class="controls">
      <label for="bet-select">每局总注</label>
      <select id="bet-select"></select>
      <button id="btn-spin" class="primary" type="button">旋转（空格）</button>
      <button id="btn-auto" type="button">自动 10 次</button>
      <button id="btn-reset" class="ghost" type="button">重置积分</button>
    </div>
    <dl class="hud">
      <div><dt>剩余积分</dt><dd id="credits">1000.00</dd></div>
      <div><dt>本局中奖</dt><dd id="round-win">0.00</dd></div>
      <div><dt>免费旋转剩余</dt><dd id="fs-left">0</dd></div>
      <div><dt>当前倍率</dt><dd id="mult">x1</dd></div>
    </dl>
    <div class="gamble-panel" id="gamble-panel" hidden>
      <p>红黑翻倍：当前奖金 <strong id="gamble-stake">0.00</strong></p>
      <div class="gamble-buttons">
        <button class="red" id="gamble-red" type="button">红 ♥</button>
        <button class="black" id="gamble-black" type="button">黑 ♠</button>
        <button class="ghost" id="gamble-take" type="button">收下奖金</button>
      </div>
    </div>
  </div>
</section>"""


def faq_html() -> str:
    items = "".join(
        f"<details open><summary>{escape(x['q'])}</summary><p>{escape(x['a'])}</p></details>" for x in FAQ
    )
    return f'<section id="faq" class="faq" aria-labelledby="faq-title"><h2 id="faq-title">常见问题</h2>{items}</section>'


def terms_html() -> str:
    items = "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in TERMS)
    return f'<section id="terms" aria-labelledby="terms-title"><h2 id="terms-title">术语表</h2><dl class="terms">{items}</dl></section>'


def how_html() -> str:
    items = "".join(f"<li>{escape(x)}</li>" for x in HOW_TO)
    return f'<section id="how" aria-labelledby="how-title"><h2 id="how-title">玩法说明</h2><ol>{items}</ol></section>'


def compare_table(games: List[Dict[str, Any]]) -> str:
    rows = "".join(
        f"<tr><th scope=\"row\"><a href=\"games/{g['id']}.html\">{escape(g['name'])}</a></th>"
        f"<td>{g['grid']}</td><td>{escape(g['pay_mode'])}</td><td>{escape(g['volatility'])}</td>"
        f"<td>{g['rtp']}%</td><td>{g['measured_rtp']}%</td><td>{escape('、'.join(g['features']) or '基础赔付')}</td>"
        f"<td>{fmt_num(g['max_win'])}x</td></tr>"
        for g in games
    )
    return f"""<div class="table-scroll"><table>
<caption>{len(games)} 款机台参数对比（实测 RTP 为每机台 20 万局蒙特卡洛仿真结果）</caption>
<thead><tr><th scope="col">机台</th><th scope="col">网格</th><th scope="col">赔付方式</th>
<th scope="col">波动率</th><th scope="col">目标 RTP</th><th scope="col">实测 RTP</th>
<th scope="col">特性</th><th scope="col">最高倍率</th></tr></thead>
<tbody>{rows}</tbody></table></div>"""


def cards_html(games: List[Dict[str, Any]]) -> str:
    out = []
    for g in games:
        feats = "".join(f"<span>{escape(f)}</span>" for f in g["features"]) or "<span>基础赔付</span>"
        img = media_image(g.get("media"), "hero")
        img_html = (
            f'<img class="card-img" src="assets/img/{img["path"]}" width="{img["width"]}" '
            f'height="{img["height"]}" loading="lazy" decoding="async" alt="{escape(g["media"].get("alt", "")) or escape(g["name"]) + " 主题配图"}">'
            if img
            else ""
        )
        out.append(
            f"""<li class="card">
  {img_html}
  <h3><a href="games/{g['id']}.html">{escape(g['name'])}</a></h3>
  <p class="meta"><span>{g['grid']}</span><span>{escape(g['pay_mode'])}</span>
  <span>波动 {escape(g['volatility'])}</span><span>目标 RTP {g['rtp']}%</span></p>
  <p>{escape(g['summary'])}</p>
  <p class="meta">{feats}</p>
</li>"""
        )
    return f'<ul class="cards">{"".join(out)}</ul>'


# --------------------------------------------------------------------------- 页面
def build_index(games: List[Dict[str, Any]], site_url: str) -> str:
    default = games[0]
    stats = load_stats()
    names = {g["id"]: g["name"] for g in games}
    rtp_values = [MEASURED_RTP.get(g["id"], g["rtp_num"]) for g in games]
    facts = f"""<ul class="fact-list">
  <li>共 {len(games)} 款主题机台：{'、'.join(names[g['id']] for g in games)}，全部共用一套 CONFIG 引擎。</li>
  <li>目标 RTP 96%，20 万局实测 RTP 区间 {min(rtp_values) * 100:.2f}% – {max(rtp_values) * 100:.2f}%。</li>
  <li>赔付方式覆盖 5 / 20 / 50 条固定线与 243 / 4096 Ways 全盘两种体系。</li>
  <li>特性覆盖免费旋转、Hold &amp; Win 宝箱重转、级联连击、扩展 Wild 锁轴重转、随机 Wild 投放、Cash Collect 金币收集与红黑翻倍博彩。</li>
  <li>纯静态网页：无后端接口、无注册、无下载，移动端自适应，积分保存在浏览器本地。</li>
  <li>同一引擎可通过 MCP 供 Blender 侧驱动三维机台动画，源码以 MIT 协议开源。</li>
</ul>"""
    blocks = [
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "@id": f"{site_url}/index.html#website",
            "url": f"{site_url}/index.html",
            "name": SITE_NAME,
            "description": SITE_DESCRIPTION,
            "inLanguage": "zh-CN",
            "publisher": {"@id": f"{site_url}/index.html#org"},
        },
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "@id": f"{site_url}/index.html#org",
            "name": ORG_NAME,
            "url": site_url,
        },
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": f"{len(games)} 款免费在线老虎机",
            "numberOfItems": len(games),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "url": f"{site_url}/games/{g['id']}.html",
                    "name": g["name"],
                }
                for i, g in enumerate(games)
            ],
        },
        {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": SITE_NAME,
            "applicationCategory": "GameApplication",
            "applicationSubCategory": "Slot Machine Simulator",
            "operatingSystem": "Any (Web Browser)",
            "url": f"{site_url}/index.html",
            "inLanguage": "zh-CN",
            "isAccessibleForFree": True,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            "featureList": [FEATURE_CN[k] for k in FEATURE_CN],
            "description": SITE_DESCRIPTION,
        },
        {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": x["q"], "acceptedAnswer": {"@type": "Answer", "text": x["a"]}}
                for x in FAQ
            ],
        },
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "首页", "item": f"{site_url}/index.html"}
            ],
        },
    ]
    head = head_html(
        title=f"{SITE_NAME}｜{len(games)} 款免费在线老虎机（免下载 · 纯静态）",
        description=SITE_DESCRIPTION,
        keywords=SITE_KEYWORDS,
        canonical=f"{site_url}/index.html",
        og_image=f"{site_url}/assets/og-image.png",
        jsonld_blocks=blocks,
    )
    return f"""{head}
{header_html("", games, site_url)}
<main id="main" class="wrap">
<article>
  <header class="hero">
    <p class="small muted">免费 · 纯静态网页 · 无需注册与下载</p>
    <h1>{len(games)} 款免费在线老虎机：一套 CONFIG 引擎驱动的 SLOT 合集</h1>
    <p class="lead">{escape(SITE_DESCRIPTION)}</p>
    <h2 id="facts-title">要点速览</h2>
    {facts}
  </header>

  {cabinet_html(games, default["id"])}

  <section id="games" aria-labelledby="games-title">
    <h2 id="games-title">{len(games)} 款机台一览</h2>
    {cards_html(games)}
  </section>

  <section id="compare" aria-labelledby="compare-title">
    <h2 id="compare-title">机台参数对比</h2>
    {compare_table(games)}
  </section>

  {how_html()}

  <section id="paytable" aria-labelledby="paytable-title">
    <h2 id="paytable-title">当前机台赔付表</h2>
    <p class="small muted">切换机台后下表会同步更新；完整符号与赔率以各机台详情页为准。</p>
    <div id="paytable">{paytable_html(default["cfg"])}</div>
  </section>

  {stats_section(stats, names)}

  {terms_html()}
  {faq_html()}
</article>
</main>
{footer_html(site_url)}
<script src="js/engine.js" defer></script>
<script src="js/app.js" defer></script>
</body>
</html>
"""


def build_game_page(g: Dict[str, Any], games: List[Dict[str, Any]], site_url: str) -> str:
    cfg = g["cfg"]
    url = f"{site_url}/games/{g['id']}.html"
    og_img = media_image(g.get("media"), "og")
    hero_img = media_image(g.get("media"), "hero")
    og_url = f"{site_url}/assets/img/{og_img['path']}" if og_img else f"{site_url}/assets/og-image.png"
    title = f"{g['name']}｜{g['grid']} {g['pay_mode']} 免费在线老虎机"
    desc = f"{g['name']}：{g['grid']} 网格、{g['pay_mode']}，{g['summary']}目标 RTP {g['rtp']}%，纯静态网页免下载即玩。"
    blocks = [
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "@id": f"{site_url}/index.html#website",
            "url": f"{site_url}/index.html",
            "name": SITE_NAME,
            "inLanguage": "zh-CN",
        },
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "首页", "item": f"{site_url}/index.html"},
                {"@type": "ListItem", "position": 2, "name": g["name"], "item": url},
            ],
        },
        {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": g["name"],
            "applicationCategory": "GameApplication",
            "applicationSubCategory": "Slot Machine Simulator",
            "operatingSystem": "Any (Web Browser)",
            "url": url,
            "inLanguage": "zh-CN",
            "isAccessibleForFree": True,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            "featureList": g["features"] or ["基础赔付"],
            "description": desc,
            "image": og_url,
            "screenshot": {"@type": "ImageObject", "url": og_url, "caption": g["name"] + " 主题配图"},
        },
        {
            "@context": "https://schema.org",
            "@type": "HowTo",
            "name": f"如何游玩{g['name']}",
            "step": [
                {"@type": "HowToStep", "position": i + 1, "text": s} for i, s in enumerate(HOW_TO)
            ],
        },
    ]
    head = head_html(
        title=title,
        description=desc,
        keywords=f"{g['name']},免费老虎机,在线老虎机,{g['pay_mode']},RTP,SLOT,{SITE_KEYWORDS}",
        canonical=url,
        og_image=og_url,
        jsonld_blocks=blocks,
        body_class=f"game-{g['id']}",
        prefix="../",
        preload_image=f"assets/img/{hero_img['path']}" if hero_img else "",
        og_image_alt=(g["media"].get("alt") if g.get("media") else "") or f"{g['name']} 主题配图",
    )
    feats = "".join(f"<li>{escape(f)}</li>" for f in g["features"]) or "<li>基础赔付</li>"
    # 主图：显式 width/height 防 CLS，fetchpriority 提升 LCP，figcaption 提供可索引的文本说明
    if hero_img:
        alt = g["media"].get("alt") or f"{g['name']} 主题配图"
        credit = " · ".join(
            x
            for x in [
                f"来源 {g['media'].get('provider', '')}",
                g["media"].get("author", ""),
                g["media"].get("license", ""),
            ]
            if x
        )
        figure = (
            f'<figure class="game-hero">'
            f'<img src="../assets/img/{hero_img["path"]}" width="{hero_img["width"]}" '
            f'height="{hero_img["height"]}" alt="{escape(alt)}" fetchpriority="high" decoding="async">'
            f'<figcaption>{escape(alt)}（{escape(credit)}）</figcaption></figure>'
        )
    else:
        figure = ""
    symbols = "".join(
        f'<tr><th scope="row"><span class="sym" style="--sym:{s.color}">{s.glyph}</span>{escape(s.name)}</th>'
        f"<td>{escape({'standard': '标准符号', 'wild': 'Wild 百搭', 'scatter': 'Scatter 散落', 'bonus': 'BONUS 赏金', 'jackpot': '奖池符号'}.get(s.kind.value, s.kind.value))}</td>"
        f"<td>{fmt_num(v)}</td></tr>"
        for s, v in _symbol_pays(cfg)
    )
    return f"""{head}
{header_html(g["id"], games, site_url, "../")}
<main id="main" class="wrap">
<article>
  <header class="hero">
    <p class="small muted"><a href="{site_url}/index.html">首页</a> · 机台详情</p>
    <h1>{escape(g['name'])}：{g['grid']} {escape(g['pay_mode'])} 免费在线老虎机</h1>
    <p class="lead">{escape(g['summary'])}</p>
    <ul class="fact-list">
      <li>网格与赔付：{g['grid']}，{escape(g['pay_mode'])}。</li>
      <li>目标 RTP {g['rtp']}%，20 万局实测 {g['measured_rtp']}%，波动率：{escape(g['volatility'])}。</li>
      <li>单局最高可命中 {fmt_num(g['max_win'])} 倍总注。</li>
      <li>适合：{escape(g['best_for'])}。</li>
    </ul>
  </header>

  {figure}

  {cabinet_html(games, g['id'])}

  <section id="features" aria-labelledby="features-title">
    <h2 id="features-title">{escape(g['name'])} 的特性</h2>
    <ul>{feats}</ul>
    <p class="small muted">{escape(g['feature_note'])}</p>
  </section>

  <section id="paytable" aria-labelledby="paytable-title">
    <h2 id="paytable-title">{escape(g['name'])} 赔付表</h2>
    {paytable_html(cfg)}
  </section>

  <section id="symbols" aria-labelledby="symbols-title">
    <h2 id="symbols-title">符号与最高赔率</h2>
    <div class="table-scroll"><table>
      <caption>符号类型与 5 连（或满轴）最高赔率</caption>
      <thead><tr><th scope="col">符号</th><th scope="col">类型</th><th scope="col">最高赔率</th></tr></thead>
      <tbody>{symbols}</tbody></table></div>
  </section>

  {how_html()}
  {terms_html()}
  {faq_html()}
</article>
</main>
{footer_html(site_url, "../")}
<script src="../js/engine.js" defer></script>
<script src="../js/app.js" defer></script>
</body>
</html>
"""


def _symbol_pays(cfg):
    out = []
    for sym in cfg.symbols.values():
        values = [float(v) for v in sym.pays.values()] or [float(v) for v in sym.scatter_pays.values()]
        out.append((sym, max(values) if values else 0.0))
    return out


# --------------------------------------------------------------------------- 资源
def write_png(path: Path, width: int, height: int, kind: str) -> None:
    """零依赖 PNG 生成器：绘制品牌渐变 + 转轮窗口，供 og:image 与图标使用。"""
    gold = (255, 204, 51)
    deep = (18, 10, 34)

    def gradient_row(y: int) -> bytearray:
        t = y / max(1, height - 1)
        r = int(27 + (61 - 27) * t)
        g = int(14 + (28 - 14) * t)
        b = int(53 + (107 - 53) * t)
        return bytearray(bytes((r, g, b)) * width)

    rows = [gradient_row(y) for y in range(height)]

    def rect(x0: int, y0: int, x1: int, y1: int, radius: int, thickness: int, fill) -> None:
        for y in range(max(0, y0), min(height, y1)):
            row = rows[y]
            for x in range(max(0, x0), min(width, x1)):
                dx = min(x - x0, x1 - 1 - x)
                dy = min(y - y0, y1 - 1 - y)
                if dx < radius and dy < radius:
                    d = ((radius - dx) ** 2 + (radius - dy) ** 2) ** 0.5
                    border = abs(d - radius) <= thickness / 2
                else:
                    border = min(dx, dy) <= thickness / 2
                r, g, b = gold if border else fill
                i = x * 3
                row[i] = r
                row[i + 1] = g
                row[i + 2] = b

    if kind == "og":
        cols, gap = 5, 28
        total = width - gap * (cols + 1)
        cw = total // cols
        top = int(height * 0.26)
        bottom = int(height * 0.78)
        radius = 34
        for i in range(cols):
            x0 = gap + i * (cw + gap)
            rect(x0, top, x0 + cw, bottom, radius, 10, deep)
        rect(int(width * 0.18), int(height * 0.88), int(width * 0.82), int(height * 0.92), 12, 0, gold)
    else:
        cols, gap = 3, max(8, width // 16)
        total = width - gap * (cols + 1)
        cw = total // cols
        top = int(height * 0.22)
        bottom = int(height * 0.78)
        for i in range(cols):
            x0 = gap + i * (cw + gap)
            rect(x0, top, x0 + cw, bottom, max(10, width // 22), max(6, width // 60), deep)

    raw = bytearray()
    for row in rows:
        raw.append(0)
        raw += row

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            len(data).to_bytes(4, "big")
            + tag
            + data
            + zlib.crc32(tag + data).to_bytes(4, "big")
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes((8, 2, 0, 0, 0)))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="SLOT">
  <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#3d1c6b"/><stop offset="1" stop-color="#150d26"/>
  </linearGradient></defs>
  <rect x="4" y="4" width="56" height="56" rx="12" fill="url(#g)" stroke="#ffcc33" stroke-width="3"/>
  <rect x="13" y="18" width="12" height="28" rx="4" fill="#0d0819" stroke="#ffcc33" stroke-width="2"/>
  <rect x="26" y="18" width="12" height="28" rx="4" fill="#0d0819" stroke="#ffcc33" stroke-width="2"/>
  <rect x="39" y="18" width="12" height="28" rx="4" fill="#0d0819" stroke="#ffcc33" stroke-width="2"/>
  <circle cx="19" cy="32" r="4" fill="#ff6b81"/>
  <circle cx="32" cy="32" r="4" fill="#7cf6c8"/>
  <circle cx="45" cy="32" r="4" fill="#ffcc33"/>
</svg>
"""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --------------------------------------------------------------------------- 主流程
SITE_DESCRIPTION = (
    "6 款免费在线老虎机（幸运水果、糖果狂欢、龙宫探宝、法老之墓、星际远征、锦鲤纳福）"
    "共用一套 CONFIG 引擎：固定线与 243/4096 Ways 两种赔付体系，含免费旋转、Hold & Win、"
    "级联连击、扩展 Wild、随机 Wild 投放、Cash Collect 金币收集与红黑翻倍。"
    "纯静态网页，免下载免注册，移动端可玩。"
)
SITE_KEYWORDS = (
    "在线老虎机,免费老虎机,SLOT,老虎机游戏,水果机,免费旋转,Hold and Win,级联,Cash Collect,"
    "老虎机模拟器,RTP,静态网页游戏,开源老虎机,Blender MCP"
)


def collect_games() -> List[Dict[str, Any]]:
    registry = get_registry()
    media = load_media()
    games = []
    for gid in registry.ids():
        machine = registry.get(gid)
        cfg = machine.config
        copy = GAME_COPY.get(gid, {})
        feats = feature_cn(cfg)
        games.append(
            {
                "id": gid,
                "name": cfg.name,
                "cfg": cfg,
                "grid": f"{cfg.reels}×{cfg.rows}",
                "pay_mode": pay_mode_text(cfg),
                "rtp": f"{cfg.math.target_rtp * 100:.0f}",
                "rtp_num": cfg.math.target_rtp,
                "measured_rtp": f"{MEASURED_RTP.get(gid, cfg.math.target_rtp) * 100:.2f}",
                "volatility": VOL_CN.get(cfg.math.volatility, cfg.math.volatility),
                "max_win": cfg.math.max_win_multiplier,
                "features": feats,
                "summary": copy.get("summary", cfg.description),
                "best_for": copy.get("best_for", "所有玩家"),
                "media": media.get(gid),
                "feature_note": (
                    "特性参数（触发个数、赠送次数、倍率曲线、重转次数、赏金与奖池）"
                    "全部写在配置里，可通过 MCP 工具 slot_set_parameter 热更新，无需改动引擎代码。"
                ),
            }
        )
    return games


def main() -> int:
    ap = argparse.ArgumentParser(description="生成静态站点")
    ap.add_argument("--site-url", default=os.getenv("SITE_URL", DEFAULT_SITE_URL))
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()

    site_url = args.site_url.rstrip("/")
    out = Path(args.out)
    games = collect_games()

    # 0) 拷贝手写前端源码（js/engine.js、js/app.js、assets/styles.css）
    copied = []
    for src in sorted(SRC_DIR.rglob("*")):
        if src.is_file():
            dst = out / src.relative_to(SRC_DIR)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            copied.append(str(src.relative_to(SRC_DIR)))

    # 1) 配置数据（前端引擎的唯一数据源）
    #    额外导出 Python 侧「已展开 + 已洗牌」的虚拟条带，确保前端与 Python 的数学完全一致
    #    （洗牌排布会影响 Scatter / 赏金符号的聚集程度，进而影响触发频率与 RTP）。
    payload_games = []
    for g in games:
        cfg = g["cfg"]
        raw = cfg.to_dict()
        for name, rs in cfg.reel_sets.items():
            strip_set = ReelStripSet(rs, cfg.rows, name)
            raw["reel_sets"][name]["expanded"] = [list(s.symbols) for s in strip_set.strips]
        payload_games.append(raw)

    data = {
        "meta": {
            "site_name": SITE_NAME,
            "site_url": site_url,
            "generated": BUILD_DATE,
            "engine": "SlotEngine.js (pure front-end port of slotmcp.engine)",
        },
        "games": payload_games,
    }
    write_text(out / "data" / "games.json", json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    # 2) 页面
    write_text(out / "index.html", build_index(games, site_url))
    for g in games:
        write_text(out / "games" / f"{g['id']}.html", build_game_page(g, games, site_url))

    # 3) 爬虫与 AI 配套文件
    urls = [(f"{site_url}/index.html", "1.0", "weekly")]
    urls += [(f"{site_url}/games/{g['id']}.html", "0.8", "monthly") for g in games]
    sitemap = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, pri, freq in urls:
        sitemap.append(
            f"  <url><loc>{escape(loc)}</loc><lastmod>{BUILD_DATE}</lastmod>"
            f"<changefreq>{freq}</changefreq><priority>{pri}</priority></url>"
        )
    sitemap.append("</urlset>")
    write_text(out / "sitemap.xml", "\n".join(sitemap) + "\n")

    write_text(
        out / "robots.txt",
        "User-agent: *\nAllow: /\n\n"
        "# 纯静态站点：所有页面均可被抓取，游戏内容同时以静态 HTML 输出，无需执行 JavaScript\n"
        f"Sitemap: {site_url}/sitemap.xml\n",
    )

    stats = load_stats()
    names = {g["id"]: g["name"] for g in games}
    llms = [
        f"# {SITE_NAME}",
        "",
        f"> {SITE_DESCRIPTION}",
        "",
        "本文件为生成式引擎（AI 摘要 / 引用）准备的事实清单，内容与页面正文一致。",
        "",
        "## 关键事实",
        f"- 机台数量：{len(games)} 款（{' / '.join(names[g['id']] for g in games)}）",
        "- 部署形态：纯静态网页，无后端接口、无需注册与下载",
        f"- 引擎：{len(games)} 款机台共用同一套 CONFIG 引擎；新增机台只需新增一份配置",
        f"- RTP：目标 96%，20 万局实测区间 {min(MEASURED_RTP.values()) * 100:.2f}% – {max(MEASURED_RTP.values()) * 100:.2f}%",
        "- 开源协议：MIT；积分保存在浏览器 localStorage，不上传服务器",
        "",
        "## 机台",
    ]
    for g in games:
        llms.append(
            f"- [{g['name']}]({site_url}/games/{g['id']}.html)：{g['grid']}，{g['pay_mode']}，"
            f"波动{g['volatility']}，目标 RTP {g['rtp']}%（实测 {g['measured_rtp']}%），"
            f"特性：{'、'.join(g['features']) or '基础赔付'}"
        )
    if stats and stats.get("rtp"):
        llms += [
            "",
            "## 验证数据（构建期由数据库聚合后静态注入）",
            f"- 累计仿真 {stats.get('sim_spins', 0)} 局，最近更新 {stats.get('generated', '')}",
        ]
        for r in stats["rtp"]:
            llms.append(f"- {names.get(r['game_id'], r['game_id'])}：{r['spins']} 局，实测 RTP {float(r['rtp']) * 100:.2f}%")
    llms += ["", "## 常见问答"]
    for x in FAQ:
        llms.append(f"Q：{x['q']}\nA：{x['a']}")
    write_text(out / "llms.txt", "\n".join(llms) + "\n")

    write_text(
        out / "manifest.webmanifest",
        json.dumps(
            {
                "name": SITE_NAME,
                "short_name": "SLOT 合集",
                "description": SITE_DESCRIPTION,
                "start_url": "./index.html",
                "scope": "./",
                "display": "standalone",
                "background_color": "#0b0714",
                "theme_color": "#0b0714",
                "lang": "zh-CN",
                "icons": [
                    {"src": "assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
                    {"src": "assets/icon-512.png", "sizes": "512x512", "type": "image/png"},
                    {"src": "assets/favicon.svg", "sizes": "any", "type": "image/svg+xml"},
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )

    write_text(
        out / "404.html",
        head_html(
            title="页面不存在 · SLOT 合集",
            description=f"页面不存在，返回 {len(games)} 款免费在线老虎机首页。",
            keywords=SITE_KEYWORDS,
            canonical=f"{site_url}/404.html",
            og_image=f"{site_url}/assets/og-image.png",
            jsonld_blocks=[],
        )
        + header_html("", games, site_url)
        + '<main id="main" class="wrap"><article><header class="hero">'
        + f"<h1>404 · 页面不存在</h1><p>你访问的地址可能已移动。下面是可直接游玩的 {len(games)} 款机台：</p></header>"
        + cards_html(games)
        + f'<p><a class="skip-link" href="{site_url}/index.html" style="position:static;display:inline-block">返回首页</a></p>'
        + "</article></main>"
        + footer_html(site_url)
        + "</body>\n</html>\n",
    )

    # 4) 图像资源
    write_text(out / "assets" / "favicon.svg", FAVICON_SVG)
    write_png(out / "assets" / "og-image.png", 1200, 630, "og")
    write_png(out / "assets" / "icon-512.png", 512, 512, "icon")
    write_png(out / "assets" / "icon-192.png", 192, 192, "icon")

    print(f"[OK] 静态站点已生成: {out}")
    print(f"     源码: {', '.join(copied)}")
    print(f"     页面: index.html + {len(games)} 个机台页 + 404.html")
    print(f"     数据: data/games.json ({len(data['games'])} 款配置)")
    print("     配套: robots.txt / sitemap.xml / llms.txt / manifest.webmanifest / og-image.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
