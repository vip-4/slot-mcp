# Blender Slot MCP —— SLOT 游戏合集

在现有 **Blender MCP** 框架中用同一套 **CONFIG 引擎** 驱动 **5 款热门 SLOT 机台**，
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
│   │   ├── features.py           #   扩展 Wild / 级联 / Hold&Win 算子
│   │   ├── game.py               #   状态机主循环 + 机台注册表（统一入口）
│   │   ├── session.py            #   玩家钱包、下注档位、博彩
│   │   └── simulator.py          #   RTP / 波动率蒙特卡洛仿真
│   ├── games/                    # 5 款机台：唯一的差异来源
│   │   ├── lucky_fruits.py       #   3x3  ·  5 线    · 低波动 · 红黑博彩
│   │   ├── candy_carnival.py     #   5x3  · 20 线   · 中波动 · 扩展 Wild + 重转
│   │   ├── dragon_palace.py      #   5x4  · 50 线   · 高波动 · 免费旋转 + 粘性 Wild
│   │   ├── pharaoh_tomb.py       #   5x3  · 243 Ways· 中高波 · Hold & Win 奖池
│   │   └── star_expedition.py    #   6x4  · 4096Ways· 高波动 · 级联倍率 + 免费旋转
│   ├── mcp/
│   │   ├── server.py             #   stdio JSON-RPC 2.0 服务端
│   │   ├── tools.py              #   15 个 MCP 工具 + 会话仓库
│   │   └── blender_bridge.py     #   Blender TCP 桥接（封帧/超时/心跳/重连）
│   ├── ui/http_api.py            #   纯标准库 REST + 静态资源托管
│   └── tools/verify_rtp.py       #   RTP 回归验证（可作 CI 门槛）
│
├── blender_addon/slot_mcp_bridge.py   # Blender 侧插件：机台搭建 + 转轮动画
├── web/{index.html,styles.css,app.js} # 前端界面
└── tests/                             # 引擎 / MCP / 桥接 / UI 四套自测
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

## 5. 五款机台的实测量化（20 万局 / bet=1）

| 机台 | 结构 | 核心机制 | RTP | 命中率 | 波动率 | 最大倍率 | 特性触发 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| lucky_fruits | 3x3 · 5 线 | 经典符号 + 红黑博彩 | 97.08% | 75.4% | 1.47 | 18.4x | — |
| candy_carnival | 5x3 · 20 线 | 扩展 Wild 锁轴重转 + Scatter 派彩 | 97.04% | 67.5% | 1.61 | 50.1x | — |
| dragon_palace | 5x4 · 50 线 | 免费旋转 + 递增倍率 + 粘性 Wild | 97.20% | 58.4% | 8.79 | 718.4x | 1/167 局 |
| pharaoh_tomb | 5x3 · 243 Ways | Hold & Win 重转 + MINI~MAJOR + 全屏大奖 | 95.40% | 49.8% | 8.53 | 519.2x | 1/346 局 |
| star_expedition | 6x4 · 4096 Ways | 级联倍率 + 免费旋转 | 95.78% | 80.7% | 4.21 | 244.7x | 1/170 局 |

目标 RTP 统一 96%，容差默认 ±2%（dragon_palace 因高波动设为 ±3%）。

## 6. 新增一台机台（不需要改任何引擎代码）

1. 在 `src/slotmcp/games/` 下新建 `my_game.py`，实现 `build_config() -> GameConfig`；
2. 在 `src/slotmcp/games/__init__.py` 的 `_BUILDERS` 里登记一行；
3. 用 MCP 工具 `slot_validate_config` 校验（或 `GameConfig.validate()`）；
4. `python -m slotmcp.tools.verify_rtp -g my_game -n 200000` 校核 RTP。

引擎侧零改动：`SlotMachine.spin()` 已经是唯一的通用入口，UI / MCP / Blender 自动可用。

## 7. 稳定性设计要点

* **无界循环防护**：单次下注最多 300 轮、400 步、40 层级联，免费旋转累计上限 200 次（可防无限再触发）
* **Blender 桥接**：4 字节长度封帧、请求级超时、心跳探活、下一次调用自动重连并重试一次；Blender 未启动时 `status()` 返回结构化降级信息而不是崩溃
* **错误不穿透**：MCP / HTTP 边界统一收敛为结构化错误，单个请求失败不会中断会话
* **可复现**：`slot_spin(seed=...)` 可 1:1 复盘异常局，便于审计
* **主线程约束**：Blender 侧所有改数据的操作都在主线程（`bpy.app.timers`）执行

更多细节见 `docs/REQUIREMENTS.md`（需求说明）、`docs/ARCHITECTURE.md`（架构）、
`docs/MCP_INTEGRATION.md`（MCP 与 Blender 通信）。
