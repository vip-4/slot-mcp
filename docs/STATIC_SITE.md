# 静态站部署说明（SEO + GEO）

`static/` 是站点的**根目录**：把它的内容原样推到任意静态托管即可上线，不需要 Node、不需要后端、不需要构建流水线。

## 1. 构建

```bash
python tools/build_static.py --site-url https://vip882.gitee.io/slot-games
```

| 参数 | 说明 |
| --- | --- |
| `--site-url` | 站点绝对地址，决定 canonical / og:url / sitemap / llms.txt 链接；默认 `https://vip882.gitee.io/slot-games` |
| `--out` | 输出目录，默认 `static/` |

产物：

```
static/
├── index.html                # 首页：要点速览 / 机台卡片 / 对比表 / 玩法 / 赔付表 / 术语表 / FAQ
├── games/<id>.html           # 5 个机台详情页（独立 canonical + JSON-LD）
├── data/games.json           # 9 款配置 + Python 侧已洗牌的虚拟条带
├── js/{engine.js,app.js}     # 纯前端引擎与交互（来自 web_static/）
├── assets/{styles.css,favicon.svg,og-image.png,icon-192.png,icon-512.png}
├── robots.txt / sitemap.xml / llms.txt / manifest.webmanifest / 404.html
```

手写源码放在 `web_static/`，构建时原样拷入；`static/` 是纯生成产物。

## 2. 前端引擎与 Python 引擎的一致性

风险点：权重展开后的虚拟条带需要洗牌，**洗牌排布不同会改变符号聚集度**，
进而改变 Scatter / 赏金符号的触发频率（实测龙宫探宝触发率曾相差 2.4 倍，RTP 相差 88%）。

对策：构建时由 Python 侧用 `ReelStripSet` 生成条带并写入 `reel_sets.<name>.expanded`，
前端 `engine.js` 发现 `expanded` 就直接复用，不再自行洗牌。校验方式：

```bash
# Python 侧
python -m slotmcp.tools.verify_rtp -n 100000
# 前端侧（需 node）
node tools/check_static_engine.js 100000     # 见下
```

两侧 RTP 应在统计误差内一致（低波动机台 50 万局偏差 < 0.3%）。

## 3. SEO 清单

| 类别 | 落地内容 |
| --- | --- |
| 基础 | `<html lang="zh-CN">`、`title`、`description`、`keywords`、`robots`（`index,follow,max-image-preview:large,max-snippet:-1`）、`canonical`、`author`、`theme-color` |
| Open Graph | `og:type/site_name/locale/title/description/url/image/image:width/image:height/image:alt`（1200×630 PNG） |
| Twitter | `twitter:card=summary_large_image` + title / description / image / image:alt |
| 结构化数据 | 首页：`WebSite` `Organization` `ItemList` `SoftwareApplication` `FAQPage` `BreadcrumbList`；详情页：`BreadcrumbList` `SoftwareApplication` `HowTo` |
| 站点配套 | `robots.txt`（含 Sitemap）、`sitemap.xml`（6 条 URL + lastmod）、`manifest.webmanifest`、`404.html`、`favicon.svg` + PNG 图标 |

结构化数据以 `<script type="application/ld+json">` 内联，自测会解析校验。

## 4. GEO（生成式引擎优化）清单

目标是让 AI 摘要/引用能读到**确定、可核对的事实**：

1. **结论式要点**：首页「要点速览」用短句给出机台数、RTP 区间、赔付体系、特性覆盖、部署形态。
2. **表格化数据**：机台参数对比表（网格 / 赔付方式 / 波动率 / 目标 RTP / 实测 RTP / 特性 / 最高倍率），
   以及每款机台的赔付表与符号表——表格比段落更容易被抽取。
3. **术语表**：`<dl>` 逐条定义 RTP、波动率、赔付线、Ways、Wild、Scatter、Hold & Win、级联。
4. **FAQ**：7 条问答同时以可见文本与 `FAQPage` 输出，答案里带具体数值。
5. **`llms.txt`**：关键事实 + 机台清单 + 问答的纯文本摘要，供 AI 抓取。
6. **每机台独立页面**：独立 canonical 与描述，便于按主题被检索与引用。
7. **零 JS 可读**：要点、表格、FAQ、赔付表全部服务端渲染，爬虫不执行 JS 也能取到完整事实。

## 5. 部署到 Gitee / AtomGit

仓库根目录即站点内容（这样 Pages 无需指定子目录）：

```bash
cd static
git init -b main && git add -A && git commit -m "deploy: static site"
git remote add origin https://<user>:<token>@gitee.com/<user>/slot-games.git
git push -u origin main
```

* **Gitee**：仓库 → 服务 → Gitee Pages，分支 `main`、部署目录 `/`，开启后得到
  `https://<user>.gitee.io/slot-games`；用该地址重跑一次 `--site-url` 再推送，保证 canonical 与 sitemap 正确。
* **AtomGit**：仓库 → Pages（或「服务」）中同样选择 `main` + 根目录；
  API 未提供 Pages 开关，需在网页端启用。
* 换域名/换平台时，只需改 `--site-url` 重新生成并推送。

## 6. 主题配图与图片 SEO

`tools/fetch_media.py` 从 Pexels（失败回退 Pixabay）抓取每款机台的主题图，
产物写入 `web_static/assets/img/`，构建时随源码拷入 `static/`：

| 文件 | 尺寸 | 用途 |
| --- | --- | --- |
| `<game>-hero.jpg` | 960×540 | 详情页主图 + 首页列表缩略图 |
| `<game>-og.jpg` | 1200×630 | 该机台页的 `og:image` / `twitter:image` |

页面侧处理：`alt` 中文描述、`width/height` 防 CLS、列表 `loading="lazy"`、
主图 `fetchpriority="high"` + `preload`、`<figure>/<figcaption>` 说明与署名、
`SoftwareApplication.image` 结构化数据；`assets/img/CREDITS.md` 提供来源与许可。
未抓到素材时自动回退到程序生成的 `og-image.png`。

## 7. 性能与可访问性

| 项 | 做法 |
| --- | --- |
| 请求数 | 1 个 CSS + 2 个 `defer` 脚本 + 1 个 37 KB JSON；无字体、无图片库、无第三方 CDN |
| 渲染 | CSS 内联关键样式不多，首屏无需 JS 即可读到全部正文；游戏区由 JS 渐进增强 |
| 语义化 | `header/nav/main/article/section/footer`、`h1→h2→h3`、`table+caption+scope`、`dl` 术语表、`aria-current` |
| 键盘/读屏 | 跳转链接、`aria-live="polite"` 播报中奖与特性、`role="img"+aria-label` 标注每个符号、空格键旋转 |
| 动效 | `prefers-reduced-motion: reduce` 下关闭过渡与动画延迟 |
| 适配 | 移动端优先布局，转轮用 `aspect-ratio` 自适应，表格横向滚动 |

## 7. 验收清单

```bash
python tests/test_static_site.py     # 75 项：元数据 / JSON-LD / 内链 / 配置 / PNG / sitemap
python tests/run_tests.py            # 全量自测（含静态站）
```

冒烟（本地起服务后按页面基准解析所有内链，确认无 404）：

```bash
python -m http.server 8080 --directory static
# 逐个访问 index.html / games/*.html / 404.html，检查引用资源与链接可达
```
