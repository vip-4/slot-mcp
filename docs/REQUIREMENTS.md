# SLOT 游戏合集 —— 开发任务说明（完善版）

> 目标：在现有 **Blender MCP** 框架中，把「老虎机能力」扩展为一个 **6 款 SLOT 游戏合集**，
> 并且让多主题机台**共用同一套 CONFIG 引擎**。本文档在原需求基础上补充了功能范围、
> 非功能约束、实现方向、依赖说明、集成步骤与验收标准，可直接作为开发任务拆解的依据。

---

## 0. 原需求回顾（保持不变的核心意图）

1. 在现有 Blender MCP 框架中扩展老虎机游戏模块，保持与已部署模块一致的架构与接口；
2. 新增至少一款热门 SLOT 游戏，定义其核心机制（转轮逻辑、赔率、中奖判定、奖励触发、特殊符号）；
3. 所有游戏通过统一入口调用，并支持参数配置以便后续调整；
4. 提供文件结构、依赖说明、集成步骤，说明如何与现有 MCP 服务通信并保证运行稳定性；
5. 如涉及前端展示，需描述界面元素与响应逻辑。

在此之上追加的关键约束：**多主题机台共用同一套 CONFIG 引擎**，而不是每台机台一套运算代码。

本轮已完成的新增项：**第 6 台「锦鲤纳福 `fortune_koi`」**，并借它把两个热门机制
（随机 Wild 投放、Cash Collect）沉淀为**通用配置算子**，供后续机台直接复用。

---

## 1. 目标与非目标

### 1.1 目标（In Scope）

| 编号 | 目标 | 验收方式 |
| --- | --- | --- |
| G1 | 6 款主题各异的 SLOT 机台 | `slot_list_games` 返回 6 台：`lucky_fruits / candy_carnival / dragon_palace / pharaoh_tomb / star_expedition / fortune_koi` |
| G2 | 机台之间复用一套 CONFIG 引擎 | 引擎目录内不存在任何按 `game_id` 的分支；新增机台只加配置文件 |
| G3 | 覆盖主流机制：固定线 / Ways / 级联 / 扩展 Wild / 粘性 Wild / 免费旋转 / Hold&Win / 博彩 / **随机 Wild** / **Cash Collect** | 每台至少启用一种特性；机制分布见 `docs/GAMES.md` 的覆盖矩阵 |
| G4 | 统一入口 + 可配置参数 | `SlotMachine.spin()` 唯一入口；`config.set_parameter()` 支持点号路径热更新 |
| G5 | 统一 RTP 目标 96% | `verify_rtp` 20 万局全部在容差内（默认 ±2%） |
| G6 | 通过 MCP 服务暴露全部能力 | 15 个工具可调用，错误收敛不中断会话 |
| G7 | 与 Blender 端通信稳定 | 桥接具备封帧、超时、心跳、自动重连；Blender 未启动时降级而非崩溃 |
| G8 | Web 前端 + 静态站两种形态 | 一套界面玩全部机台；`static/` 可零后端静态托管（已上线 GitHub Pages） |
| G9 | 新机制可复用 | 随机 Wild / Cash Collect 均为配置算子，任一新机台开启即可，无需改引擎 |

### 1.2 非目标（Out of Scope）

* 真实资金、账号体系、KYC、支付通道
* 服务器端持久化存储（会话默认在进程内；运维侧的数据库只服务构建期与审计，不进入站点运行时）
* Blender 复杂材质/光照/渲染出图（插件只负责机台搭建、停轮动画与特性高亮）
* 多语言国际化文案、合规文案与审计级日志留存

---

## 2. 功能范围

### 2.1 CONFIG 引擎（共用层）

| 模块 | 职责 | 关键约定 |
| --- | --- | --- |
| `config.py` | 配置模型、JSON 双向序列化、结构化校验、点号路径热更新 | `pays[n]` = **单线注**倍数；`scatter_pays[n]`、赏金/币值 = **总注**倍数 |
| `rng.py` | 可复现随机数与安全并发 | 同种子 ⇒ 同结果；每实例独立锁 |
| `reels.py` | 物理条带 / 虚拟映射权重、停位、窗口采样 | `grid[reel][row]`，`row=0` 为顶部；**权重 ≤ 0 表示该符号不在该轴出现** |
| `paylines.py` | 经典线组（3x3/5 线、5x3/20 线） + 任意尺寸确定性生成 | 按「曲折程度 + 字典序」排序，保证可复算 |
| `evaluator.py` | 赔付线 / Ways / Scatter 三种结算 | 统一返回 `WinEvent`（kind/symbol/count/positions/amount） |
| `features.py` | 扩展 Wild、级联坠落、Hold&Win、**随机 Wild 投放**、**币值收集** | 均为「输入网格 → 输出网格 + 事件」的纯函数 |
| `game.py` | **统一入口**：状态机主循环、机台注册表 | 一次 `spin()` 跑完级联/重转/免费旋转/Hold&Win，以 `steps` 有序返回 |
| `session.py` | 钱包、下注档位、博彩 | 与实际对局共用同一 `spin()`，RTP 口径一致 |
| `simulator.py` | RTP / 波动率 / 命中率 / 特性频率仿真 | 复用线上代码路径，避免「仿真与实测两套数学」 |

### 2.2 六款机台（配置层）

| 机台 | 结构 | 特殊符号 | 奖励触发 | 实测 RTP / 波动 |
| --- | --- | --- | --- | --- |
| 幸运水果机 `lucky_fruits` | 3x3 · 5 线 | Wild 替代并自带最高赔付 | 中奖后红黑翻倍（≤5 次，上限 1000x） | 97.08% / 低 |
| 糖果狂欢 `candy_carnival` | 5x3 · 20 线 | Scatter 全盘派彩；Wild 落第 3 轴整轴扩展 | 扩展后锁轴重转 1 次 | 97.04% / 中低 |
| 龙宫探宝 `dragon_palace` | 5x4 · 50 线 | 神龙 Wild 第 3 轴粘性保留 | 3/4/5 Scatter → 10/14/20 次免费旋转 + 递增倍率 | 97.20% / 高 |
| 法老之墓 `pharaoh_tomb` | 5x3 · 243 Ways | 金币赏金 + MINI/MINOR/MAJOR 奖池 | 8 个赏金符号 → 宝箱重转 | 95.40% / 高 |
| 星际远征 `star_expedition` | 6x4 · 4096 Ways | 星门 Wild；黑洞 Scatter | 级联倍率递增（封顶 10x）+ 免费旋转 | 95.78% / 中高 |
| **锦鲤纳福 `fortune_koi`** | 5x3 · 20 线 | 锦鲤 Wild **兼收集者**；莲花 Scatter；四档币值符号 | **随机 Wild 投放** + **Cash Collect** + 免费旋转（8/12/16，倍率 1/1/2/3/5） | **96.76% / 中高** |

### 2.3 新增机台的机制定义（可作为后续机台模板）

| 机制 | 配置项 | 语义 |
| --- | --- | --- |
| 随机 Wild 投放 | `features.random_wild` | `counts{个数: 权重}` 抽样投放个数；`phases` 控制生效阶段（base / free_spins）；`exclude_reels` 排除轴；`protected_symbols` 声明不可被覆盖的符号（Scatter / 币值） |
| Cash Collect | `features.collect` | `collector` 收集者（通常为 Wild）；`coin_symbols` 币值符号；`coin_values{符号: 总注倍数}`；`award_multiplier` / `free_award_multiplier` 分别控制基础与免费旋转倍率；`jackpot_symbol` + `jackpot_value` 稀有币 |
| 免费旋转 | `features.free_spins` | `trigger_counts{Scatter 数: 次数}`、`multiplier_progression`、`retrigger_counts`、专用 `reel_set` |

**结算顺序（重要）**：`roll()` → 随机 Wild 投放 → 扩展 Wild → 粘性 Wild → 结算（线/Ways/Scatter/**收集**）→ 触发判定 → 级联/重转/免费旋转。
收集只对**新鲜网格**结算，避免级联派生网格把同一枚币重复收取。

### 2.4 平台能力

* **MCP 服务端**：stdio JSON-RPC 2.0，自动识别换行分隔帧与 LSP `Content-Length` 帧；15 个工具
* **Blender 插件**：主线程执行、TCP 桥接，指令 `ping / status / build_cabinet / animate_spin / exec`；
  `animate_spin` 新增**特性高亮**（随机 Wild 落点、被收集金币、扩展 Wild、Hold&Win 锁定格）
* **Web 前端**：机台切换、下注档位、SPIN / AUTO、级联分步回放、博彩弹窗、Blender 联动
* **静态站**：`static/` 为零后端产物，含 SEO/GEO 全套元数据；已发布到 GitHub Pages

---

## 3. 非功能约束

| 类别 | 约束 | 落地实现 |
| --- | --- | --- |
| 依赖 | 核心零第三方依赖 | 只用标准库；`requirements.txt` 为空集，`requirements-optional.txt` 提供选装（含 `certifi` 等） |
| 可复现 | 同种子同结果 | `SlotRNG` + `slot_spin(seed=...)` |
| 有界性 | 单局必须收敛 | 单局 ≤300 轮 / ≤400 步 / 级联 ≤40 层；单次下注免费旋转 ≤200 次 |
| 一致性 | 前后端数学一致 | 静态站复用 Python 导出的「已展开 + 已洗牌」虚拟条带；`tools/check_static_engine.js` 可复算 |
| 可用性 | Blender 掉线不能拖垮服务 | 超时后自动重连并重试一次；`status()` 返回结构化降级 |
| 正确性 | 仿真与实际同源 | `simulate()` 复用 `SlotMachine.spin()` |
| 安全 | 远程执行受控 | Blender 插件 `exec` 默认关闭，只监听 `127.0.0.1` |
| 线程安全 | 多线程调用不产生半包 | 桥接单写锁 + 后台单读线程 + 请求级 `Event` |
| 兼容性 | Python ≥ 3.10，Blender ≥ 3.0 | 语法与 API 均在此基线之上 |

---

## 4. 实现方向（关键决策）

**D1. 配置即数据，而非代码分支。**
所有机台差异（条带、赔率表、线数、特性开关与数值）落在 `GameConfig`；
`SlotMachine.spin()` 里不存在 `if game_id == ...`。新机台（含第 6 台）只加配置文件，引擎零改动。

**D2. 一次下注返回有序步骤序列。**
级联、锁轴重转、免费旋转、Hold&Win 都是「同一注内的多个结算」，
统一编码为 `SpinResult.steps`；前端与 Blender 按序播放即可，无需理解具体机制。

**D3. 只有「新鲜网格」能触发特性与收集。**
级联/重转派生的网格不参与 Scatter 与赏金计数，也不重复收集：
否则触发频率随级联链线性膨胀，`trigger_counts` 失去可调性（实测偏差可达 5 倍）。

**D4. 固定上界，防止不可收敛。**
免费旋转累计上限、单局步数上限、级联层数上限构成三重保险。

**D5. 仿真与实际共用一条计算路径。**
`verify_rtp` 可直接作为 CI 门槛；新增机台必须先过 20 万局校验再上线。

**D6. 三层接口保持一致：**
`GameRegistry.spin`（Python 库）≡ `slot_spin`（MCP 工具）≡ `POST /api/session/{id}/spin`（HTTP），
返回结构为同一份 `SpinResult.to_dict()`。前端 JS 引擎是同一套语义的端口，用于静态托管形态。

---

## 5. 交付物清单与文件结构

```
slot-mcp/
├── src/slotmcp/
│   ├── engine/                 # 共用 CONFIG 引擎（9 个模块，无机台分支）
│   │   ├── config.py           #   含 RandomWildConfig / CollectConfig
│   │   ├── features.py         #   place_random_wilds / collect_coins
│   │   └── game.py             #   统一入口 spin()
│   ├── games/                  # 6 款机台配置 + 注册表
│   │   └── fortune_koi.py      #   第 6 台：随机 Wild + Cash Collect + 免费旋转
│   ├── mcp/                    # stdio 服务端 / 15 个工具 / Blender 桥接
│   ├── ui/http_api.py          # REST + 静态托管（动态形态）
│   ├── services/               # 外部服务客户端（邮件/定时/三维/图片/GEO/数据库/发布）
│   └── tools/                  # verify_rtp / build_static / fetch_media / deploy_ops / deploy_pages / db_sync
├── blender_addon/slot_mcp_bridge.py   # Blender 插件（含特性高亮）
├── web/                        # 动态形态前端（依赖 HTTP API）
├── web_static/                 # 静态站手写源码（engine.js / app.js / styles.css / 图片）
├── static/                     # 生成产物：站点根（可直接托管）
├── tests/                      # 引擎 / MCP / 桥接 / UI / 静态站 / 服务层 六套自测
├── deploy/                     # 凭证样例、素材清单、统计与运维快照（local 文件已 gitignore）
└── docs/                       # README / REQUIREMENTS / ARCHITECTURE / MCP_INTEGRATION / GAMES / STATIC_SITE / DEPLOY_OPS
```

---

## 6. 依赖说明

| 形态 | 依赖 | 说明 |
| --- | --- | --- |
| 引擎 / MCP / 前端 | **无**（Python ≥ 3.10 标准库） | `pip install -e .` 即可 |
| 可选（运维/发布） | `certifi`（根证书，某些精简 Python 缺失 CA）、`node`（仅用于跑 JS 引擎 RTP 校验脚本） | `requirements-optional.txt` |
| Blender 端 | Blender ≥ 3.0 内置 `bpy` | 插件零外部依赖，只监听 `127.0.0.1` |
| 静态站 | 任意静态托管 | 无构建、无服务端 |

---

## 7. 集成步骤

1. **安装**：`pip install -e .`（或把 `src` 加入 `PYTHONPATH`）。
2. **接入 MCP 客户端**：按 `mcp.example.json` 配置 `python -m slotmcp.mcp.server`，
   工具共 15 个：`slot_list_games / slot_get_config / slot_set_parameter / slot_spin / slot_simulate / slot_verify_rtp / slot_session_* / slot_blender_*`。
3. **接入 Blender**：Blender → 偏好设置 → 插件 → 安装 `blender_addon/slot_mcp_bridge.py`；
   面板点「启动服务」，MCP 侧 `slot_blender_status` 应返回 `ok`。
4. **调参与验证**：`python -m slotmcp.tools.verify_rtp -n 200000`；偏差超容差时用 `slot_set_parameter` 调（如 `features.collect.free_award_multiplier`）。
5. **发布静态站**：
   ```bash
   python tools/build_static.py --site-url https://vip-4.github.io/slot-games/
   python -m slotmcp.tools.deploy_pages --all --dir static
   python -m slotmcp.tools.deploy_ops --all --site-url https://vip-4.github.io/slot-games/
   ```
6. **（可选）动态形态**：`python -m slotmcp.ui.http_api` → `http://127.0.0.1:8787`。

### 7.1 与 MCP 服务的通信与稳定性

| 环节 | 机制 |
| --- | --- |
| 帧格式 | 4 字节长度前缀；stdio 侧兼容换行帧与 `Content-Length` 帧 |
| 超时 | 每个请求独立超时，超时即判失败并进入重连流程 |
| 重连 | 下一次调用自动重连并重试一次 |
| 心跳 | 后台心跳探活；`slot_blender_status` 返回结构化降级（Blender 未启动不崩溃） |
| 线程 | Blender 侧所有改数据操作都经 `bpy.app.timers` 回到主线程 |
| 错误处理 | MCP / HTTP 边界统一收敛为结构化错误，单请求失败不中断会话 |
| 可复现 | `slot_spin(seed=...)` 可 1:1 复盘异常局 |

### 7.2 前端界面元素与响应逻辑

| 元素 | 行为 |
| --- | --- |
| 机台选择 | 切换后按 `CONFIG` 重建网格尺寸、符号表、赔付表与主题配色 |
| 下注档位 / 线数 | 来自 `BetConfig.steps`，越界自动夹取并提示 |
| SPIN / AUTO | 调用同一 `spin()`；AUTO 按步播放，可随时中断 |
| 分步回放 | 遍历 `steps`：重绘网格 → 高亮中奖格 → 播放事件播报 → 累加本局派彩 |
| 事件播报 | `aria-live` 播报：扩展 Wild、免费旋转触发/再触发、Hold&Win、**随机 Wild 投放**、**收集金币** |
| 博彩面板 | 仅当 `features.gamble` 开启时出现，红/黑二选一 |
| 可访问性 | 跳转链接、`role="img"+aria-label` 标注符号、空格键旋转、`:focus-visible`、`prefers-reduced-motion` 关闭动效 |

---

## 8. 验收标准（Acceptance Criteria）

| # | 标准 | 判定方式 |
| --- | --- | --- |
| A1 | 6 台机台配置全部通过校验 | `validate()` 无错误（`tests/run_tests.py` 覆盖） |
| A2 | 引擎内无机台分支 | 代码审查 + 新增机台引擎零改动验证 |
| A3 | 6 台 RTP 均落在目标 ±容差 | `python -m slotmcp.tools.verify_rtp -n 200000` |
| A4 | 特性可触发且能正确回到基础阶段 | 引擎自测：随机 Wild / 收集 / 免费旋转 / Hold&Win 端到端命中 |
| A5 | 赔付与收集判定正确 | 手工构造网格验证 Wild 替代、左侧连续性、Ways 计数、收集倍率（基础 1x / 免费 2x / 大奖币） |
| A6 | 会话余额结算正确 | 余额 = 初始 − 下注 + 派彩；余额不足拒绝旋转 |
| A7 | 参数热更新可用且非法值回滚 | `slot_set_parameter` 正/反用例（含新机制的字段路径） |
| A8 | MCP 工具可用且错误不穿透 | `test_mcp.py` 全绿（列表返回 6 台） |
| A9 | 桥接稳定性 | `test_bridge.py` 覆盖封帧/超时/错误/自动重连/降级 |
| A10 | Web 前端可用 | `test_ui.py` 覆盖静态资源与全部 REST 流程 |
| A11 | 同种子可复现 | `test_engine.py` 断言 |
| A12 | 前后端数学一致 | 静态站 `data/games.json` 含 `expanded` 条带；`node tools/check_static_engine.js 200000` 与 Python 侧一致 |
| A13 | 静态站可零后端托管 | `test_static_site.py`（含 6 台页面、7 条 sitemap、SEO/GEO 元数据、内链 200） |
| A14 | 非法新特性配置被拦截 | `test_engine.py` 的 `test_feature_config_validation` |

---

## 9. 里程碑建议

| 阶段 | 内容 | 产出 |
| --- | --- | --- |
| M1 | CONFIG 引擎建模 + 校验 + 赔付/转轮基础 | engine 前 6 个模块 + 单测 |
| M2 | 状态机主循环 + 会话 + 仿真器 | `spin()` 通用入口、RTP 可测 |
| M3 | 第 1 台样机（糖果狂欢）打通全链路 | 验证「配置驱动」假设成立 |
| M4 | 补齐至 5 台并完成 RTP 调参 | 5 台均在容差内 |
| M5 | MCP 服务层 + Blender 桥接 + Web 前端 | 15 个工具、插件、界面可用 |
| M6 | 静态站形态 + SEO/GEO + 发布与运维 | `static/` 上线 GitHub Pages，巡检/邮件/审计打通 |
| M7 | **第 6 台 + 新机制通用化** | `RandomWildConfig` / `CollectConfig` 沉淀为算子；`fortune_koi` 过 20 万局校验；前后端一致 |

---

## 10. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 高波动机台 RTP 估计方差大 | 抽检误判超标 | 提高仿真局数；为高波动机台单独设置容差 |
| 级联机台链过长导致单局过重 | 响应变慢 | 级联层数上限 40 + 单局步数上限 400 |
| Blender 端崩溃/掉线 | MCP 调用挂起 | 请求级超时 + 心跳探活 + 自动重连一次 |
| 配置误改导致机台不可用 | 线上故障 | 写入前先 `validate()`，非法则回滚 |
| Ways + 级联的量纲难标定 | 赔付定成数十倍偏差 | 统一口径 `bet_per_way = 总注 / ways`，用 `verify_rtp` 迭代 |
| **收集类机台的量纲坑** | 币值以总注计、线赔以线注计，差一个数量级 | 文档与注释标明口径；首轮实测即做贡献拆分（线赔/收集/Scatter） |
| **币值符号稀释连线** | 线赔 RTP 被压低 | 币值权重与线赔一起联调（`fortune_koi` 实测 47/43/6 的拆分） |
| **前后端数学漂移** | 静态站 RTP 与后端不一致 | 复用 Python 导出的展开条带；每次构建后跑 `check_static_engine.js` |
