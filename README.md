# Blender Slot MCP —— SLOT 游戏合集

在现有 **Blender MCP** 框架中用同一套 **CONFIG 引擎** 驱动 **11 款热门 SLOT 机台**，
机台之间互不复制代码：差异全部落在配置里，引擎、MCP 工具、Blender 插件、Web 前端共用一套接口。

```
CONFIG(纯数据) → SlotMachine(统一入口) → MCP 工具层 → Blender 3D / Web 前端
```

---

## 1. 目录结构

```
blender-slot-mcp/
├── README.md
├── requirements.txt              # 零第三方依赖，仅需 Python ≥ 3.10
├── requirements-optional.txt     # 可选：numpy / mcp SDK / uvicorn
├── pyproject.toml                # pip install -e . + 三个命令行入口
├── mcp.example.json              # MCP 客户端配置样例
│
├── src/slotmcp/
│   ├── engine/                   # 共用 CONFIG 引擎（与具体机台无关）
│   │   ├── config.py             #   配置模型 + 序列化 + 校验 + 点号路径热更新
│   │   ├── rng.py                #   可复现随机数（线程安全）
│   │   ├── reels.py              #   物理/虚拟条带、停位与窗口采样
│   │   ├── paylines.py           #   经典线组 + 任意尺寸确定性生成器
│   │   ├── evaluator.py          #   赔付线 / Ways / Scatter 三种结算
│   │   ├── features.py           #   扩展 Wild / 级联 / Hold&Win / 随机 Wild / 币值收集 算子
│   │   ├── game.py               #   状态机主循环 + 机台注册表（统一入口）
│   │   ├── session.py            #   玩家钱包、下注档位、博彩
│   │   └── simulator.py          #   RTP / 波动率蒙特卡洛仿真
│   ├── games/                    # 11 款机台：唯一的差异来源
│   │   ├── lucky_fruits.py       #   3x3  ·  5 线    · 低波动 · 红黑博彩
│   │   ├── candy_carnival.py     #   5x3  · 20 线   · 中波动 · 扩展 Wild + 重转
│   │   ├── dragon_palace.py      #   5x4  · 50 线   · 高波动 · 免费旋转 + 粘性 Wild
│   │   ├── pharaoh_tomb.py       #   5x3  · 243 Ways· 中高波 · Hold & Win 奖池
│   │   ├── star_expedition.py    #   6x4  · 4096Ways· 高波动 · 级联倍率 + 免费旋转
│   │   ├── fortune_koi.py        #   5x3  · 20 线   · 中高波 · 随机 Wild + Cash Collect
│   │   ├── thunder_temple.py     #   5x3  · 20 线   · 高波动 · 倍率 Wild + Pick'em 选宝
│   │   ├── colossal_ruins.py     #   5x3  · 20 线   · 中高波 · 巨符号 2×2/3×3
│   │   ├── phoenix_rebirth.py    #   5x3  · 20 线   · 中高波 · 神秘符号揭示
│   │   ├── frost_wolf.py         #   5x4  · 50 线   · 高波动 · 行走 Wild（跨局状态）
│   │   └── neon_twins.py         #   5x3  · 20 线   · 中高波 · 同步轴（Twin Reels）
│   ├── mcp/
│   │   ├── server.py             #   stdio JSON-RPC 2.0 服务端
│   │   ├── tools.py              #   15 个 MCP 工具 + 会话仓库
│   │   └── blender_bridge.py     #   Blender TCP 桥接（封帧/超时/心跳/重连）
│   ├── ui/http_api.py            #   纯标准库 REST + 静态资源托管
│   └── tools/verify_rtp.py       #   RTP 回归验证（可作 CI 门槛）
│
├── blender_addon/slot_mcp_bridge.py   # Blender 侧插件：机台搭建 + 转轮动画
├── web/{index.html,styles.css,app.js} # 前端界面（依赖 Python HTTP API）
│
├── web_static/                        # 静态站手写源码（无后端依赖）
│   ├── js/engine.js                   #   纯前端引擎（与 Python 引擎语义等价）
│   ├── js/app.js                      #   交互层：加载配置 → 跑一局 → 播放动画
│   └── assets/styles.css
├── tools/build_static.py              # 静态站生成器（SEO / GEO / 结构化数据）
├── static/                            # 生成产物：可直接托管的静态站（站点根）
│   ├── index.html                     #   首页（含要点速览 / 对比表 / 术语表 / FAQ）
│   ├── games/<id>.html                #   5 个机台详情页
│   ├── data/games.json                #   机台配置（含与 Python 一致的虚拟条带）
│   ├── robots.txt / sitemap.xml / llms.txt / manifest.webmanifest / 404.html
│   └── assets/{styles.css,favicon.svg,og-image.png,icon-*.png}
└── tests/                             # 引擎 / MCP / 桥接 / UI / 静态站 五套自测
```

## 2. 安装与启动

```bash
# 方式一：可编辑安装（推荐）
pip install -e .

# 方式二：不安装，直接把源码目录加入 PYTHONPATH
export PYTHONPATH="$(pwd)/src"          # Windows PowerShell: $env:PYTHONPATH="$PWD\src"
```

| 能力 | 命令 |
| --- | --- |
| MCP 服务端（stdio，给各类 MCP 客户端调用） | `python -m slotmcp.mcp.server` |
| MCP 服务端自检 | `python -m slotmcp.mcp.server --selftest` |
| Web UI（默认 8787） | `python -m slotmcp.ui.http_api --port 8787` |
| RTP 回归验证 | `python -m slotmcp.tools.verify_rtp -n 200000` |
| 全部自测 | `python tests/run_tests.py` |
| 单套自测 | `python tests/test_engine.py` / `test_mcp.py` / `test_bridge.py` / `test_ui.py` |

Blender 侧：偏好设置 → 附加组件 → 安装 `blender_addon/slot_mcp_bridge.py` → 勾选启用 →
3D 视图右侧 `SLOT` 面板 → **启动桥接**（监听 `127.0.0.1:8765`）。

## 3. MCP 接入

把下面这段写进 MCP 客户端配置（Claude Desktop 的 `claude_desktop_config.json`、
CodeBuddy / Continue / Cline 各自的配置，原理完全一致）：

```json
{
  "mcpServers": {
    "blender-slot": {
      "command": "python",
      "args": ["-m", "slotmcp.mcp.server"],
      "env": {
        "PYTHONPATH": "<仓库路径>/src",
        "SLOT_MCP_BLENDER_HOST": "127.0.0.1",
        "SLOT_MCP_BLENDER_PORT": "8765"
      }
    }
  }
}
```

暴露的 15 个工具：

| 类别 | 工具 |
| --- | --- |
| 元信息 | `slot_list_games` `slot_get_game` `slot_get_config` `slot_validate_config` |
| 数学/simulation | `slot_spin` `slot_simulate` `slot_set_parameter` |
| 会话 | `slot_session_create` `slot_session_spin` `slot_session_gamble` `slot_session_snapshot` |
| Blender | `blender_status` `blender_build_cabinet` `blender_animate_spin` `blender_exec` |

最小的驱动链路：

```
slot_list_games → slot_spin(game_id, bet) → blender_build_cabinet(game_id) → blender_animate_spin(session_id)
```

## 4. Web 前端

```bash
python -m slotmcp.ui.http_api --port 8787
# 浏览器打开 http://127.0.0.1:8787
```

界面元素与响应逻辑见 `docs/ARCHITECTURE.md` 第 5 节，API 契约见下一节表。

| REST | 说明 |
| --- | --- |
| `GET /api/games` | 机台列表（含目标 RTP、波动、theme） |
| `GET /api/games/{id}` | 单台详情：符号表、赔率表、赔付线、特性明细 |
| `POST /api/session` | 建会话（默认 1000 信用额） |
| `POST /api/session/{id}/spin` | 旋转一次，自动扣注入账 |
| `POST /api/session/{id}/bet` | 切换下注档位 |
| `POST /api/session/{id}/gamble` | 红黑翻倍 / 收下奖金 |
| `POST /api/session/{id}/auto` | 自动旋转（后台线程，可 stop） |
| `POST /api/simulate` | 触发一次 RTP 仿真 |
| `POST /api/blender/build` `/api/blender/animate` | 转发给 Blender 插件 |

## 5. 十一款机台的实测量化（20 万局 / bet=1）

| 机台 | 结构 | 核心机制 | RTP | 命中率 | 波动率 | 最大倍率 | 特性触发 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| lucky_fruits | 3x3 · 5 线 | 经典符号 + 红黑博彩 | 97.08% | 75.4% | 1.47 | 18.4x | — |
| candy_carnival | 5x3 · 20 线 | 扩展 Wild 锁轴重转 + Scatter 派彩 | 97.04% | 67.5% | 1.61 | 50.1x | — |
| dragon_palace | 5x4 · 50 线 | 免费旋转 + 递增倍率 + 粘性 Wild | 97.20% | 58.4% | 8.79 | 718.4x | 1/167 局 |
| pharaoh_tomb | 5x3 · 243 Ways | Hold & Win 重转 + MINI~MAJOR + 全屏大奖 | 95.40% | 49.8% | 8.53 | 519.2x | 1/346 局 |
| star_expedition | 6x4 · 4096 Ways | 级联倍率 + 免费旋转 | 95.78% | 80.7% | 4.21 | 244.7x | 1/170 局 |
| **fortune_koi** | 5x3 · 20 线 | **随机 Wild 投放 + Cash Collect 金币收集** + 免费旋转（收集 ×2） | **96.76%** | 67.9% | 4.70 | 188.9x | 1/62.6 局 |
| **thunder_temple** | 5x3 · 20 线 | **倍率 Wild（×2/×3 相加） + Pick'em 选雷石** + 免费旋转 | **96.99%** | 51.5% | 6.03 | 358.9x | 1/137 局 |
| **colossal_ruins** | 5x3 · 20 线 | **巨符号 2×2 / 3×3** + 免费旋转 | **96.31%** | 49.0% | 3.56 | 165.5x | 1/74.7 局 |
| **phoenix_rebirth** | 5x3 · 20 线 | **神秘符号揭示**（凤凰蛋 → 同一符号）+ 免费旋转 | **96.92%** | 51.3% | 4.03 | 186.8x | 1/91.4 局 |
| **frost_wolf** | 5x4 · 50 线 | **行走 Wild**（每局左移一列，跨局状态）+ 免费旋转 | **96.44%** | 46.1% | 6.66 | 244.2x | 1/71.2 局 |
| **neon_twins** | 5x3 · 20 线 | **同步轴**（2~5 个相邻轴显示相同符号）+ 免费旋转 | **96.32%** | 71.8% | 4.32 | 252.6x | 1/54.7 局 |

目标 RTP 统一 96%，容差默认 ±2%（dragon_palace 因高波动设为 ±3%）。
`fortune_koi` 的贡献拆分：线赔 ≈47% / 收集 ≈43% / Scatter 直付 ≈6%；
`thunder_temple` 为线赔 ≈79% / 选宝 ≈15% / Scatter ≈6%。

## 6. 新增一台机台（不需要改任何引擎代码）

1. 在 `src/slotmcp/games/` 下新建 `my_game.py`，实现 `build_config() -> GameConfig`；
2. 在 `src/slotmcp/games/__init__.py` 的 `_BUILDERS` 里登记一行；
3. 用 MCP 工具 `slot_validate_config` 校验（或 `GameConfig.validate()`）；
4. `python -m slotmcp.tools.verify_rtp -g my_game -n 200000` 校核 RTP。

引擎侧零改动：`SlotMachine.spin()` 已经是唯一的通用入口，UI / MCP / Blender 自动可用。

## 7. 静态站（生产部署形态，零后端）

`static/` 是**可直接托管的站点根**：无服务端、无接口、无第三方依赖，扔到任意静态托管
（Gitee Pages / AtomGit Pages / GitHub Pages / Nginx / OSS）即可上线。

```bash
# 生成（--site-url 决定 canonical / OG / sitemap 的绝对地址）
python tools/build_static.py --site-url https://vip882.gitee.io/slot-games

# 本地预览
python -m http.server 8080 --directory static   # 打开 http://127.0.0.1:8080
```

**前后端数学一致**：Python 侧把「已展开 + 已洗牌」的虚拟条带随配置一起导出，
前端引擎直接复用同一份条带——洗牌排布不同会改变 Scatter 聚集度、进而改变触发频率与 RTP。
`web_static/js/engine.js` 是 Python 引擎的等价端口，实测两侧 RTP 在统计误差内一致。

### 7.1 SEO

| 项 | 内容 |
| --- | --- |
| 基础 meta | `title` / `description` / `keywords` / `robots(max-image-preview:large)` / `author` / `theme-color` |
| Open Graph | `og:type` `og:site_name` `og:locale` `og:title` `og:description` `og:url` `og:image(1200×630)` `og:image:alt` |
| Twitter Card | `summary_large_image` + title / description / image / image:alt |
| 结构化数据 | `WebSite` `Organization` `ItemList` `SoftwareApplication` `FAQPage` `BreadcrumbList` `HowTo`（详情页） |
| 站点配套 | `robots.txt`（含 Sitemap 声明）、`sitemap.xml`（6 条 URL）、`manifest.webmanifest`、`404.html` |

### 7.2 GEO（生成式引擎优化）

面向 AI 摘要与引用：**所有事实都以静态 HTML 输出**，不执行 JS 也能读到完整内容。

* 「要点速览」结论式列表 + 机台参数对比**表格**（结构化、易被引用）
* 术语表（`<dl>`）逐条定义 RTP / 波动率 / Ways / Hold & Win / 级联
* 7 条 FAQ 同时输出为可见文本与 `FAQPage` 结构化数据
* `llms.txt`：关键事实 + 机台清单 + 问答的纯文本摘要，供 AI 直接抓取
* 每个机台详情页独立 canonical + `SoftwareApplication`/`HowTo`，便于按主题被检索

### 7.3 性能与可访问性

* 单 CSS + 两个 `defer` 脚本，零外部请求；数据仅 37 KB JSON（可预加载）；主题图为本地静态资源（每张 30–130 KB）
* 语义化结构：`header/nav/main/article/section/footer`、`h1→h2→h3` 层级、`<table>`+`caption`+`scope`、`aria-current`
* 可访问性：跳转链接、`aria-live` 播报中奖与特性、`role="img"+aria-label` 标注符号、键盘空格旋转、`:focus-visible` 焦点环
* `prefers-reduced-motion` 下关闭动画与过渡

## 8. 稳定性设计要点

* **无界循环防护**：单次下注最多 300 轮、400 步、40 层级联，免费旋转累计上限 200 次（可防无限再触发）
* **Blender 桥接**：4 字节长度封帧、请求级超时、心跳探活、下一次调用自动重连并重试一次；Blender 未启动时 `status()` 返回结构化降级信息而不是崩溃
* **错误不穿透**：MCP / HTTP 边界统一收敛为结构化错误，单个请求失败不会中断会话
* **可复现**：`slot_spin(seed=...)` 可 1:1 复盘异常局，便于审计
* **主线程约束**：Blender 侧所有改数据的操作都在主线程（`bpy.app.timers`）执行
* **静态站一致性**：`tests/test_static_site.py` 校验导出配置可校验、条带带 `expanded`、六类 meta/JSON-LD 齐全、内链无 404（配合本地 HTTP 冒烟）

## 9. 部署运维（邮件 / 定时任务 / 三维同步）

```bash
python -m slotmcp.tools.deploy_ops --all          # 巡检 + 定时任务 + 三维同步 + 邮件报告
python -m slotmcp.tools.deploy_ops --all --dry-run # 只打印计划动作
```

| 服务 | 用途 | 关键点 |
| --- | --- | --- |
| AgentMail | 部署报告 / 健康告警邮件 | Base `https://api.agentmail.to`（无 /v1）；`POST /inboxes/{inbox}/messages/send` |
| cron-job.org | 站点可用性巡检（每 30 分钟） | 创建用 `PUT /jobs`；按标题幂等 upsert；站点未上线时创建为停用以降噪 |
| PlayCanvas | 三维机台场景同步 | `GET /projects/{id}/scenes|assets`；项目详情 403 时降级不抛异常；`--sync-scene` 导出 `deploy/playcanvas_scene.json` |
| Pexels / Pixabay | 机台主题配图 | `python -m slotmcp.tools.fetch_media`；两服务都需浏览器 UA，Pexels CDN 直接裁剪 1200×630 作 OG 图；素材清单 `deploy/media.json` + 署名 `CREDITS.md` |
| Metaso | GEO 收录与 AI 摘要监测 | `--geo`：`POST /api/v1/search`，判断 AI 搜索是否命中本站、摘要内容 |
| Neon（主 + 镜像） | 部署审计 / RTP 回归 / 统计快照 | `python -m slotmcp.tools.db_sync --init/--rtp/--snapshot`；HTTP SQL 无需本地驱动；聚合结果静态注入页面，**站点运行时不查库** |
| Supabase | 排行榜（可选增强） | 项目当前 `INACTIVE`，客户端已实现 `ping/select/insert` 并在不可达时降级；恢复后前端可用 publishable key 直连 |
| Cloudflare Pages | 静态站直传发布 | `python -m slotmcp.tools.deploy_pages --cloudflare`；multipart 直传，无需 wrangler。**当前账号项目配额已满（10/10）**，需先用 `--project <已有项目>` 或删除闲置项目 |
| GitHub Pages | 生产站点（已上线） | `python -m slotmcp.tools.deploy_pages --github`；建仓 → 推送 → 开启 Pages，地址 `https://vip-4.github.io/slot-games/` |
| CARTO / Pirate Weather / marketstack | 外部数据源体检 | `--sources` 进部署报告；CARTO 账号已停用、天气网关返回 HTML，marketstack 可用。**均不写入站点内容**（主题无关，会稀释 SEO 焦点） |

### 9.1 一键发布

```bash
python tools/build_static.py --site-url https://vip-4.github.io/slot-games/   # canonical / sitemap 对齐
python -m slotmcp.tools.deploy_pages --all --dir static                       # Cloudflare + GitHub
python -m slotmcp.tools.deploy_ops --all --site-url https://vip-4.github.io/slot-games/
```

凭证只从环境变量或 `deploy/services.local.json`（已 gitignore）读取，绝不入库。
详见 `docs/DEPLOY_OPS.md`。

更多细节见 `docs/REQUIREMENTS.md`（需求说明）、`docs/ARCHITECTURE.md`（架构）、
`docs/MCP_INTEGRATION.md`（MCP 与 Blender 通信）、`docs/STATIC_SITE.md`（静态站与 SEO/GEO）、
`docs/DEPLOY_OPS.md`（邮件 / 定时任务 / PlayCanvas 运维）。
