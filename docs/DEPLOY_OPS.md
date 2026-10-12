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

## 5. PlayCanvas 三维同步

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

## 6. 让站点真正上线（需网页端一次点击）

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

## 7. 自测

`tests/test_services.py` 用**本地桩服务**（不发真实请求）验证 21 项：请求体形态、
`schedule` 换算与非法间隔拒绝、upsert 幂等（创建→更新→仍只有一条）、
403 降级、场景描述导出、报告渲染。

```bash
python tests/run_tests.py services
```
