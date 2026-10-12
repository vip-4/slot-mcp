# 部署运维：邮件通知 · 定时巡检 · PlayCanvas 三维同步

静态站上线之后还需要三件事：**知道它是否还活着**、**出问题时有人收到通知**、
**三维场景与机台配置保持同源**。这三件事分别由 AgentMail、cron-job.org、PlayCanvas 承担，
统一入口是：

```bash
python -m slotmcp.tools.deploy_ops --all
```

## 1. 凭证配置

读取顺序：**环境变量 > `deploy/services.local.json` > `deploy/services.json`**。
两个 JSON 都已在 `.gitignore` 中，仓库只保留 `deploy/services.example.json` 模板。

| 环境变量 | 说明 |
| --- | --- |
| `SLOT_SITE_URL` | 站点绝对地址（canonical / sitemap / 健康检查基准） |
| `AGENTMAIL_API_KEY` / `AGENTMAIL_INBOX` / `AGENTMAIL_TO` | 邮件：密钥、发件邮箱、收件人（逗号分隔） |
| `CRONJOB_API_KEY` / `CRONJOB_INTERVAL` | cron-job.org 密钥与巡检间隔（分钟） |
| `PLAYCANVAS_TOKEN` / `PLAYCANVAS_PROJECT_ID` | 三维项目令牌与项目 ID |

```powershell
$env:AGENTMAIL_API_KEY = "am_us_..."
$env:AGENTMAIL_INBOX   = "hermes-h5@agentmail.to"
$env:AGENTMAIL_TO      = "vip880@agentmail.to,vip881@agentmail.to"
$env:CRONJOB_API_KEY   = "..."
$env:PLAYCANVAS_TOKEN  = "..."
python -m slotmcp.tools.deploy_ops --all
```

常用参数：`--check` `--cron --interval 30` `--email a@x.com` `--playcanvas --sync-scene`
`--site-url https://...` `--dry-run`（只打印计划动作，不调用外部服务）。

## 2. 健康检查

对 首页 / `sitemap.xml` / `robots.txt` 做 GET，输出状态码与耗时，结果进入邮件报告：

```
[OK] 首页     https://.../index.html -> 200 (0.42s)
[NG] 站点地图 https://.../sitemap.xml -> 404 (0.38s)
```

## 3. 定时巡检（cron-job.org）

`upsert` 按**标题幂等**：已存在则 PATCH 更新，不存在则创建，因此可反复执行、不会产生重复任务。

| 任务 | URL | 周期 |
| --- | --- | --- |
| SLOT 静态站可用性巡检 | `{site}/index.html` | 每 30 分钟（可 `--interval` 调整） |
| SLOT 静态站 sitemap 巡检 | `{site}/sitemap.xml` | 每 30 分钟 |

**降噪设计**：若创建时首页不可达（例如 Pages 尚未开启），任务会被创建为**停用**状态；
站点上线后再执行一次本命令即自动启用，避免上线前持续告警。

接口要点（实测）：`GET /jobs`、`PUT /jobs`（创建，**不是 POST**）、`PATCH /jobs/{id}`、`DELETE /jobs/{id}`；
schedule 中 `-1` 表示「任意」。

## 4. 邮件报告（AgentMail）

接口要点（实测）：Base 为 `https://api.agentmail.to`（**无 /v1 前缀**），
`POST /inboxes/{inbox_id}/messages/send`，body 为 `{"to": [...], "subject": ..., "text": ...}`。

报告正文包含：站点地址、页面数、机台清单、健康检查逐项结果、定时任务状态、
PlayCanvas 项目概况——纯文本、结构化，便于人读也便于再次被程序解析。

## 5. 主题配图（Pexels / Pixabay）

```bash
$env:PEXELS_API_KEY  = "..."
$env:PIXABAY_API_KEY = "..."
python -m slotmcp.tools.fetch_media            # 抓取 12 款机台主题图
python -m slotmcp.tools.fetch_media --only lucky_fruits --dry-run
```

| 产物 | 尺寸 | 用途 |
| --- | --- | --- |
| `web_static/assets/img/<game>-hero.jpg` | 960×540 | 机台详情页主图 + 首页列表缩略图 |
| `web_static/assets/img/<game>-og.jpg` | 1200×630 | 该机台页的 `og:image` / `twitter:image` |
| `deploy/media.json` | — | 素材清单：来源、作者、许可、尺寸、字节数 |
| `web_static/assets/img/CREDITS.md` | — | 署名表（随站点发布，页脚有入口） |

接口要点（实测）：

* 两个服务都**必须带浏览器 UA**，否则 Cloudflare 返回 `error code: 1010`。
* Pexels CDN 支持 imgix 参数，直接请求裁剪尺寸即可，无需本地处理：
  `?auto=compress&cs=tinysrgb&fit=crop&w=1200&h=630`。
* Pixabay 的 `per_page` 合法区间是 **3–200**。
* Pexels 优先，失败自动回退 Pixabay；都失败时页面回退到程序生成的 `og-image.png`。

落地到页面的 SEO / 可访问性处理：显式 `width`/`height` 防 CLS、列表图 `loading="lazy" decoding="async"`、
详情页主图 `fetchpriority="high"` + `<link rel="preload" as="image">`、`alt` 为中文描述、
`<figure>` + `<figcaption>` 给出图片说明与来源署名、JSON-LD `SoftwareApplication.image`。

## 6. GEO 监测（Metaso 秘塔 AI 搜索）

SEO/GEO 做完之后需要闭环验证：AI 搜索能不能找到站点、摘要怎么描述它。

```bash
$env:METASO_API_KEY = "mk-..."
python -m slotmcp.tools.deploy_ops --geo
```

`POST https://metaso.cn/api/v1/search`（`Authorization: Bearer`），body 形如
`{"q": ..., "scope": "webpage", "size": 5, "includeSummary": true}`。
输出：检索词、是否命中本站（`indexed`）、命中条数、前几条结果、AI 摘要；
结果同时进入邮件报告，可配合 cron 做「上线后是否被收录」的长期观察。

> 上线前基线示例：`命中本站 0/5 条` —— 站点未上线时属正常，上线并收录后应转为 `≥1`。

## 7. 数据库（Neon 主库 + 镜像库 / Supabase 可选）

**原则：站点运行时不访问任何数据库。** 数据库只服务构建期与运维期，聚合结果以
静态 JSON 注入页面，因此发布产物仍是零后端依赖的纯静态站。

```bash
$env:NEON_DATABASE_URL   = "postgresql://..."   # 主库
$env:NEON_DATABASE_URL_2 = "postgresql://..."   # 镜像库（异地）
python -m slotmcp.tools.db_sync --status        # 连通性（含 Supabase 项目状态）
python -m slotmcp.tools.db_sync --init          # 两库建表
python -m slotmcp.tools.db_sync --rtp 20000     # 仿真 RTP 回归写库
python -m slotmcp.tools.db_sync --snapshot      # 聚合 -> deploy/stats.json
python -m slotmcp.tools.deploy_ops --db         # 写一条部署审计
```

| 表 | 内容 |
| --- | --- |
| `slot_deploy_log` | 每次运维的站点地址、检查结果、是否通过 |
| `slot_rtp_runs` | 每款机台的仿真局数 / 实测 RTP / 命中率 |
| `slot_scores` | 社区成绩（玩家、机台、最高倍率） |

Neon 走 HTTP SQL（`POST https://<pooler-host>/sql` + `Neon-Connection-String` 头），
**不需要 psycopg 之类的本地驱动**，与项目「零第三方依赖」一致。

Supabase 项目当前状态为 `INACTIVE`（REST 域名无法解析），客户端已实现
`ping/select/insert` 并在不可达时降级为「项目可能已暂停」的提示——项目恢复后
即可用 publishable key 直接从前端读写排行榜，无需自建后端。

## 8. PlayCanvas 三维同步

可用作用域（实测）：`GET /projects/{id}/scenes` 与 `GET /projects/{id}/assets` 返回 200；
`GET /projects/{id}` 返回 403（Token 缺 project 作用域），客户端对此**降级但不抛异常**。

`--sync-scene` 由 `static/data/games.json` 生成 `deploy/playcanvas_scene.json`：

```json
{
  "schema": "slotmcp.scene/1",
  "project_id": 1583126,
  "scene": "Main Scene",
  "animation": {"spin_ms": 420, "cascade_ms": 340, "hold_win_ms": 620, "stop_stagger_ms": 90},
  "machines": [{"id": "...", "reels": 5, "rows": 3, "symbols": [...], "features": [...]}]
}
```

即三维侧与网页侧共用同一份 CONFIG：符号颜色 / 类型、网格尺寸、特性清单、动画节奏都来自配置，
改配置 → 重新生成 → 三维与网页同步，不需要在两处维护。

> 当前项目实测：1 个场景（Main Scene）、16 个资产。

## 8. 让站点真正上线（需网页端一次点击）

两个平台的 Pages 开关**没有开放 API**（Gitee 返回 405，AtomGit 返回 404），需要手动开启一次：

1. Gitee：`vip882/slot-games` → 服务 → Gitee Pages → 分支 `main`、部署目录 `/` → 开启
   → 得到 `https://vip882.gitee.io/slot-games`
2. AtomGit：`zzw1208/slot-games` → Pages（服务）→ 同样选择 `main` + 根目录
3. 用最终地址重跑：
   ```bash
   python tools/build_static.py --site-url https://实际地址
   python -m slotmcp.tools.deploy_ops --all       # 巡检任务自动转为启用
   ```
   并重新推送 `static/`（canonical 与 sitemap 会随地址更新）。

仓库根目录即站点内容，所以 Pages 不需要指定子目录。

## 9. 发布通道（Cloudflare Pages / GitHub Pages）

```bash
python -m slotmcp.tools.deploy_pages --cloudflare   # 直传 static/（multipart，无需 wrangler）
python -m slotmcp.tools.deploy_pages --github       # 建仓 → 推送 → 开启 Pages
python -m slotmcp.tools.deploy_pages --all --dry-run
```

| 通道 | 状态 | 说明 |
| --- | --- | --- |
| GitHub Pages | **已上线** | 仓库 `vip-4/slot-games`，地址 `https://vip-4.github.io/slot-games/`；首次开启后重复执行会命中 409 并视为成功 |
| Cloudflare Pages | 受限 | 账号 `8eb2b953…` 项目数已达上限（10/10，`code 8000027`）。可用 `--project <已有项目>` 复写指定项目，或删除闲置项目后再建 `slot-games` |
| Cloudflare R2 | 不可用 | 本机到 `*.r2.cloudflarestorage.com` 的 TLS 握手失败（Python 与 WinHTTP 均失败），且该 token 无 R2 权限（`/r2/buckets` 403） |

推送用 `git`，并且**先 `fetch` + `reset --soft` 对齐远端历史**——否则每次用临时仓库推送都会因无关历史被拒
（`non-fast-forward`）。内容推送与 Pages 开启解耦：推送失败不会误判为 Pages 未开启。

## 10. 外部数据源监测（CARTO / 天气 / marketstack）

```bash
python -m slotmcp.tools.deploy_ops --sources
```

| 数据源 | 实测结果 | 处理 |
| --- | --- | --- |
| CARTO（`gcp-us-east1`） | **账号已停用**（401 `Account suspended`，account `ac_lv1128s9`） | 降级为说明，不抛异常 |
| Pirate Weather（apiable.io 网关） | **不可用**：所有路径都返回门户 HTML（`text/html`）而非 JSON | 客户端识别「网关返回非 JSON」并降级 |
| marketstack（APILayer） | **可用**：`GET https://api.apilayer.net/marketstack/v2/eod` + 头 `apikey`（直连 `api.marketstack.com?access_key=` 会 401） | 取 AAPL 收盘价作为探活样本 |

**这些数据不写入站点内容**——地图 / 天气 / 行情与机台主题无关，混进页面会稀释
SEO/GEO 焦点、增加无谓的正文噪声；它们只作为运维依赖体检进入部署报告。

## 11. 自测

`tests/test_services.py` 用**本地桩服务**（不发真实请求）验证 57 项：请求体形态、
`schedule` 换算与非法间隔拒绝、upsert 幂等（创建→更新→仍只有一条）、
403 降级、图片结果归一化与裁剪 URL、Metaso 命中判定与错误降级、
Neon HTTP SQL（含字面量转义与结构化错误）、Supabase REST 读写与暂停降级、
Cloudflare 目录收集 / manifest / multipart 构造 / 项目与部署请求、GitHub 建仓与 Pages 请求体、
CARTO SQL 与「账号停用」降级、天气网关返回 HTML 时的降级、marketstack 取价与鉴权失败、场景导出、报告渲染。

```bash
python tests/run_tests.py services
```
