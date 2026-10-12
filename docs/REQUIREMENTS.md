# SLOT 游戏合集 —— 开发任务说明（完善版）

> 目标：在现有 **Blender MCP** 框架中，把「老虎机能力」扩展为一个 **5 款 SLOT 游戏合集**，
> 并且让多主题机台**共用同一套 CONFIG 引擎**。本文档在原需求基础上补充了功能范围、
> 非功能约束、实现方向与验收标准，使其可直接作为开发任务拆解的依据。

---

## 0. 原需求回顾（保持不变的核心意图）

1. 在现有 Blender MCP 框架中扩展老虎机游戏模块，保持与已部署模块一致的架构与接口；
2. 新增至少一款热门 SLOT 游戏，定义其核心机制（转轮逻辑、赔率、中奖判定、奖励触发、特殊符号）；
3. 所有游戏通过统一入口调用，并支持参数配置以便后续调整；
4. 提供文件结构、依赖说明、集成步骤，说明如何与现有 MCP 服务通信并保证运行稳定性；
5. 如涉及前端展示，需描述界面元素与响应逻辑。

在此之上追加的关键约束：**多主题机台共用同一套 CONFIG 引擎**，而不是每台机台一套运算代码。

---

## 1. 目标与非目标

### 1.1 目标（In Scope）

| 编号 | 目标 | 验收方式 |
| --- | --- | --- |
| G1 | 新增 5 款主题各异的 SLOT 机台 | `slot_list_games` 返回 5 台，各自 id 独立：`lucky_fruits / candy_carnival / dragon_palace / pharaoh_tomb / star_expedition` |
| G2 | 机台之间复用一套 CONFIG 引擎 | 引擎目录内不存在任何按 `game_id` 的分支；新增机台只加配置文件 |
| G3 | 覆盖主流机制：固定线 / Ways / 级联 / 扩展 Wild / 免费旋转 / Hold&Win / 博彩 | 每台至少启用一种特性；机制分布见 `docs/GAMES.md` |
| G4 | 统一入口 + 可配置参数 | `SlotMachine.spin()` 唯一入口；`config.set_parameter()` 支持点号路径热更新 |
| G5 | 统一 RTP 目标 96% | `verify_rtp` 20 万局全部在容差内（默认 ±2%，高波动 ±3%） |
| G6 | 通过 MCP 服务暴露全部能力 | 15 个工具可调用，错误收敛不中断会话 |
| G7 | 与 Blender 端通信稳定 | 桥接具备封帧、超时、心跳、自动重连；Blender 未启动时降级而非崩溃 |
| G8 | 提供可用的 Web 前端 | 一套界面玩全部机台，主题随切换变化 |

### 1.2 非目标（Out of Scope）

* 真实资金、账号体系、KYC、支付通道
* 服务器端持久化存储（会话默认在进程内，提供 `snapshot/restore` 接口给外部存储）
* Blender 复杂材质/光照/渲染出图（当前插件只负责机台搭建与停轮动画）
* 多语言国际化文案、合规文案与审计级日志留存

---

## 2. 功能范围

### 2.1 CONFIG 引擎（共用层）

| 模块 | 职责 | 关键约定 |
| --- | --- | --- |
| `config.py` | 机台配置模型、JSON 双向序列化、结构化校验、点号路径热更新 | `pays[n]` = **单线注**倍数；`scatter_pays[n]` = **总注**倍数 |
| `rng.py` | 可复现随机数与安全并发 | 同种子 ⇒ 同结果；每实例独立锁，便于仿真并发 |
| `reels.py` | 物理条带 / 虚拟映射权重、停位、窗口采样 | 坐标 `grid[reel][row]`，`row=0` 为顶部；权重展开后做**确定性洗牌** |
| `paylines.py` | 经典线组（3x3/5 线、5x3/20 线） + 任意尺寸确定性生成 | 生成算法按「曲折程度 + 字典序」排序，保证可复算 |
| `evaluator.py` | 赔付线 / Ways / Scatter 三种结算 | 统一返回 `WinEvent`，含 kind/symbol/count/positions/amount |
| `features.py` | 扩展 Wild、级联坠落、Hold&Win 网格算子 | 均为输入网格 → 输出网格 + 事件的纯函数 |
| `game.py` | **统一入口**：状态机主循环、机台注册表 | 一次 `spin()` 跑完级联/重转/免费旋转/Hold&Win，以 `steps` 有序返回 |
| `session.py` | 钱包、下注档位、博彩 | 与实际对局共用同一 `spin()`，确保 RTP 口径一致 |
| `simulator.py` | RTP / 波动率 / 命中率 / 特性频率仿真 | 直接复用线上代码路径，避免「仿真与实测两套数学」 |

### 2.2 五款机台（配置层）

| 机台 | 结构 | 特殊符号 | 奖励触发 | 目标 RTP / 波动 |
| --- | --- | --- | --- | --- |
| 幸运水果机 `lucky_fruits` | 3x3 · 5 线 | Wild 替代并自带最高赔付 | 中奖后可红黑翻倍（≤5 次，上限 1000x） | 96% / 低 |
| 糖果狂欢 `candy_carnival` | 5x3 · 20 线 | Scatter 全盘派彩；Wild 落第 3 轴整轴扩展 | 扩展后锁轴重转 1 次 | 96% / 中 |
| 龙宫探宝 `dragon_palace` | 5x4 · 50 线 | Scatter 触发；神龙 Wild 在第 3 轴粘性保留 | 3/4/5 个 Scatter → 10/14/20 次免费旋转，倍率递增 | 96% / 高 |
| 法老之墓 `pharaoh_tomb` | 5x3 · 243 Ways | BONUS 金币不参与 Ways；MINI/MINOR/MAJOR 奖池 | 8 个赏金符号 → 宝箱重转，新符号重置计数 | 96% / 中高 |
| 星际远征 `star_expedition` | 6x4 · 4096 Ways | 黑洞 Scatter 触发；星门 Wild | 级联倍率递增（封顶 10x）+ 免费旋转 | 96% / 高 |

### 2.3 平台能力

* **MCP 服务端**：stdio JSON-RPC 2.0，自动识别换行分隔帧与 LSP `Content-Length` 帧
* **MCP 工具层**：15 个工具；所有异常在边界收敛为结构化错误
* **Blender 插件**：主线程执行、TCP 桥接、`build_cabinet` / `animate_spin` / `exec`
* **Web 前端**：机台切换、下注档位、SPIN / AUTO、级联分步回放、博彩弹窗、Blender 联动

---

## 3. 非功能约束

| 类别 | 约束 | 落地实现 |
| --- | --- | --- |
| 依赖 | 核心零第三方依赖 | 只用标准库；`requirements.txt` 为空集，`requirements-optional.txt` 提供选装 |
| 可复现 | 同种子同结果 | `SlotRNG` + `slot_spin(seed=...)` |
| 有界性 | 单局必须收敛 | 单局 ≤300 轮 / ≤400 步 / 级联 ≤40 层；单次下注免费旋转 ≤200 次 |
| 可用性 | Blender 掉线不能拖垮服务 | 桥接超时后自动重连并重试一次；`status()` 返回结构化降级 |
| 正确性 | 仿真与实际同源 | `simulate()` 复用 `SlotMachine.spin()` |
| 安全 | 远程执行受控 | Blender 插件 `exec` 默认关闭，且只监听 `127.0.0.1` |
| 线程安全 | 多线程调用不产生半包 | 桥接单写锁 + 后台单读线程 + 请求级 `Event` |
| 兼容性 | Python ≥ 3.10，Blender ≥ 3.0 | 语法与 API 均在此基线之上 |

---

## 4. 实现方向（关键决策）

**D1. 配置即数据，而非代码分支。**
所有机台差异（条带、赔率表、线数、特性开关与数值）落在 `GameConfig`；
`SlotMachine.spin()` 里不存在 `if game_id == ...`。这样新增机台不需要回归修改引擎。

**D2. 一次下注返回有序步骤序列。**
级联、锁轴重转、免费旋转、Hold&Win 都是「同一注内的多个结算」，
统一编码为 `SpinResult.steps`，前端与 Blender 只需按序播放，无需理解具体机制。

**D3. 只有「新鲜网格」能触发特性。**
级联/重转派生的网格不参与 Scatter 与赏金符号计数：
否则触发频率会随级联链长度线性膨胀，`trigger_counts` 将失去可调性（实测偏差可达 5 倍）。

**D4. 固定上界，防止不可收敛。**
免费旋转累计上限、单局步数上限、级联层数上限共同构成三重保险，任何配置异常都能被夹住。

**D5. 仿真与实际共用一条计算路径。**
避免「调 RTP 的人」和「跑线上的人」看两份数学；`verify_rtp` 可直接作为 CI 门槛。

**D6. 三层接口保持一致：**
`GameRegistry.spin`（Python 库）≡ `slot_spin`（MCP 工具）≡ `POST /api/session/{id}/spin`（HTTP），
返回结构为同一份 `SpinResult.to_dict()`。

---

## 5. 交付物清单

1. `src/slotmcp/engine/*`：共用 CONFIG 引擎（9 个模块）
2. `src/slotmcp/games/*`：5 款机台配置 + 注册表
3. `src/slotmcp/mcp/*`：stdio 服务端、15 个工具、Blender 桥接
4. `src/slotmcp/ui/http_api.py`：REST + 静态托管
5. `blender_addon/slot_mcp_bridge.py`：Blender 插件
6. `web/*`：前端三件套
7. `tests/*`：引擎 / MCP / 桥接 / UI 四套自测 + `run_tests.py` 一键入口
8. 文档：`README.md`、`docs/ARCHITECTURE.md`、`docs/MCP_INTEGRATION.md`、`docs/GAMES.md`

---

## 6. 验收标准（Acceptance Criteria）

| # | 标准 | 判定方式 |
| --- | --- | --- |
| A1 | 5 台机台配置全部通过校验 | `validate()` 无错误（测试覆盖） |
| A2 | 引擎内无机台分支 | 代码审查 + 新增机台零改动验证 |
| A3 | 5 台 RTP 均落在目标 ±容差 | `python -m slotmcp.tools.verify_rtp -n 200000` |
| A4 | 特性可触发且能正确回到基础阶段 | 引擎自测（种子搜索触发 FS / Hold&Win） |
| A5 | 赔付判定正确 | 手工构造网格验证 Wild 替代、左侧连续性、Ways 计数 |
| A6 | 会话余额结算正确 | 余额 = 初始 − 下注 + 派彩；余额不足拒绝旋转 |
| A7 | 参数热更新可用且非法值回滚 | `slot_set_parameter` 正/反用例 |
| A8 | MCP 工具可用且错误不穿透 | `test_mcp.py` 全绿 |
| A9 | 桥接稳定性 | `test_bridge.py` 覆盖封帧/超时/错误/自动重连/降级 |
| A10 | Web 前端可用 | `test_ui.py` 覆盖静态资源与全部 REST 流程 |
| A11 | 同种子可复现 | `test_engine.py` 断言 |

---

## 7. 里程碑建议

| 阶段 | 内容 | 产出 |
| --- | --- | --- |
| M1 | CONFIG 引擎建模 + 校验 + 赔付/转轮基础 | engine 前 6 个模块 + 单测 |
| M2 | 状态机主循环 + 会话 + 仿真器 | `spin()` 通用入口、RTP 可测 |
| M3 | 第 1 台样机（糖果狂欢）打通全链路 | 验证「配置驱动」假设成立 |
| M4 | 补齐另外 4 台并完成 RTP 调参 | 5 台均在容差内 |
| M5 | MCP 服务层 + Blender 桥接 | 15 个工具、插件可用 |
| M6 | Web 前端 + 稳定性加固 + 文档 | 全量测试通过、README/ARCH 完整 |

---

## 8. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 高波动机台 RTP 估计方差大 | 抽检误判超标 | 提高仿真局数；为高波动机台单独设置容差 |
| 级联机台链过长导致单局过重 | 响应变慢 | 级联层数上限 40 + 单局步数上限 400 |
| Blender 端崩溃/掉线 | MCP 调用挂起 | 请求级超时 + 心跳探活 + 自动重连一次 |
| 配置误改导致机台不可用 | 线上故障 | 写入前先 `validate()`，非法则回滚 |
| Ways + 级联机台的赔付量纲难标定 | 初学者易把赔付定成数十倍偏差 | 统一口径 `bet_per_way = 总注 / ways`，再用 `verify_rtp` 迭代标定 |
