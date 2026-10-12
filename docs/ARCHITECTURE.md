# 架构说明

## 1. 分层

```
┌──────────────────────────────────────────────────────────────┐
│ 消费层    MCP 客户端(Claude/CodeBuddy/…) │ Web 浏览器 │ 脚本   │
└────────────────┬───────────────────────────┬─────────────────┘
                 │ stdio JSON-RPC            │ HTTP REST
┌────────────────▼───────────────────────────▼─────────────────┐
│ 接口层    mcp/server.py │ mcp/tools.py      │ ui/http_api.py  │
│           15 个工具（含会话仓库 SessionStore，两边共用）        │
└────────────────┬───────────────────────────┬─────────────────┘
                 │  Python API               │ Blender 指令
┌────────────────▼───────────────────────────┼─────────────────┐
│ 引擎层    engine/game.py  GameRegistry/SlotMachine           │
│           engine/{config,rng,reels,paylines,evaluator,       │
│                   features,session,simulator}.py             │
└────────────────┬─────────────────────────────────────────────┘
                 │ GameConfig（纯数据）
┌────────────────▼─────────────────────────────────────────────┐
│ 配置层    games/lucky_fruits.py / candy_carnival.py /         │
│           dragon_palace.py / pharaoh_tomb.py / star_expedition│
└──────────────────────────────────────────────────────────────┘

侧路：mcp/blender_bridge.py ──TCP(8765)──> blender_addon/slot_mcp_bridge.py ──> bpy
```

设计要点：**依赖方向单向向下**。配置层不知道引擎怎么跑，引擎不知道自己被谁调用。

## 2. 统一入口

```python
machine = get_registry().get("candy_carnival")     # 1) 拿到机台
result = machine.spin(total_bet=1.0, active_lines=0)  # 2) 唯一入口
result.to_dict()                                    # 3) 统一 JSON 契约
```

三条调用路径返回完全相同的结构：

| 路径 | 调用 | 返回 |
| --- | --- | --- |
| Python 库 | `machine.spin(total_bet=...)` | `SpinResult` |
| MCP 工具 | `slot_spin {game_id, bet, spins, seed}` | `SpinResult.to_dict()` |
| HTTP REST | `POST /api/session/{id}/spin` | `{result: SpinResult.to_dict(), credits, state}` |

## 3. 一次旋转的内部流程

```
SlotMachine.spin()
 ├─ 阶段判定：base / free_spins / hold_win
 ├─ _run_spin：选择条带集合 → 采样网格 → 套用粘性 Wild → 可选扩展 Wild
 │            └─ _settle：结算 →（级联则移除中奖格、下沉补位、倍率+1 → 重新结算）
 │            └─ 重转循环（扩展 Wild 配置了 respins 时）
 ├─ _apply_triggers：仅“新鲜网格”参与计数 → 触发免费旋转 / Hold&Win
 └─ 循环直到阶段回到 base 或触碰上限
```

状态机（`GameState`）字段全部可 JSON 序列化，因此可以：

* 存进 Redis / DB 做断点续玩（`slot_session_snapshot` + `restore`）
* 复用于仿真
* 在前端展示（剩余免费旋转、当前倍率）

有界性保障常量（`engine/game.py`）：

| 常量 | 值 | 作用 |
| --- | --- | --- |
| `MAX_TURNS_PER_SPIN` | 300 | 单局最大轮次 |
| `MAX_STEPS_PER_SPIN` | 400 | 单局最大步骤数 |
| `MAX_CASCADES_PER_SPIN` | 40 | 单次结算最大级联层数 |
| `MAX_FREE_SPINS_PER_PURCHASE` | 200 | 单次下注可派发免费旋转上限 |

## 4. CONFIG 数据模型速查

```
GameConfig
├── id / name / description / provider / version
├── reels / rows / pay_mode(LINES|WAYS)
├── symbols: Dict[id, Symbol]
│     └── kind(standard|wild|scatter|bonus|jackpot)
│         pays[n]        单位：单线注（或 Ways 模式下的每通路注）
│         scatter_pays[n]单位：总注
│         substitutes    only Wild 可配
├── reel_sets: Dict[name, ReelSet]
│     └── strips[reel]  物理条带
│         weights[reel] 可选虚拟映射权重（展开后做确定性洗牌）
├── paylines: rows / lines / active_lines
├── bet: steps / default_index / max_total_bet
├── features
│     ├── FreeSpinsConfig   trigger_counts / multiplier_progression /
│     │                     retrigger_counts / sticky_wild_reels / reel_set
│     ├── HoldWinConfig     trigger_count / respins / prizes / jackpots /
│     │                     filler_symbols / hit_probability / full_grid_bonus
│     ├── CascadeConfig     multiplier_step / multiplier_cap / reset_each_free_spin
│     ├── ExpandingWildConfig symbol / reels / respins
│     └── GambleConfig      max_steps / max_win_multiplier / win_probability
├── math: target_rtp / volatility / max_win_multiplier / hit_frequency_target / rtp_tolerance
└── theme: palette / cabinet_color / background / accent
```

校验（`GameConfig.validate()`）覆盖：条带数与轴数一致、赔付线长度与行号越界、
符号引用缺失、only Wild 可 substitutes、余额/概率/次数取值合法、Ways 模式行号一致等。

## 5. 前端界面元素与响应逻辑

| 区域 | 元素 | 交互逻辑 |
| --- | --- | --- |
| 顶栏 | 机台标签、Blender 状态灯、余额 | 点击标签 → `GET /api/games/{id}` → 重绘赔率表 + 重建会话；主题写入 CSS 变量实现整体换肤；每 5s 轮询桥接状态 |
| 左栏 | 机台参数、赔率表、特性列表 | 赔率表按 `pay_mode` 切换单位文案（每线注 / 每通路注）；`赔率` 按钮折叠面板 |
| 中区 | 转轮网格 | `renderGrid` 逐轴错峰应用 `rolling` 动画（每轴延迟 70ms），中奖格追加 `win` 高亮类；多步骤结果按 `steps` 顺序播放，每步更新步骤徽标与金额 |
| 中区 | stepbar | 显示 `基础 1/3`、`免费旋转 2/8`、`Hold & Win 3/5` 与当前步倍率 |
| 中区 | 控制区 | 下注 `−/＋` 切档（同步 `POST /bet`）；`SPIN`（空格键同效）；`AUTO` 启动后台自动旋转任务并轮询进度 |
| 右栏 | 最近记录、会话状态 | 每次旋转后重绘：序列、事件标签、净盈亏着色，以及阶段/剩余免费旋转/倍率 |
| 弹窗 | 红黑翻倍 | `pending_gamble` 为真时弹出，选择红/黑或收下；结果 toast 反馈 |
| 底部 | Blender 动作 | `构建 3D 机台` → `/api/blender/build`；`播放 Blender 动画` → 推送最近一次 spin |

失败的交互（余额不足、Blender 未连、会话不存在）统一以 toast / 提示文案降级，不阻断页面。

## 6. 扩展方式

**新增机台**：`games/<id>.py` 实现 `build_config()` → 在 `games/__init__.py:_BUILDERS` 登记 →
`slot_validate_config` 校验 → `verify_rtp` 标定。其余层零改动。

**新增参数**：在对应 `Config` dataclass 加字段 + `to_dict/from_dict` + 校验规则即可，
不需要动工具层（点号路径 `features.xxx.yyy` 自动可读可写）。

**替换存储**：实现与 `SessionStore` 相同接口（create/get/drop/ids/restore）的类并注入即可；
UI 与 MCP 工具共用同一个实例，天然一致。
