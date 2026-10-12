# MCP 服务与 Blender 通信

## 1. 总体拓扑

```
MCP 客户端 ──stdin/stdout(JSON-RPC 2.0)──> slotmcp.mcp.server
                                              │
                                              ├─> slotmcp.mcp.tools ──> GameRegistry / Session / simulate
                                              └─> slotmcp.mcp.blender_bridge ──TCP 127.0.0.1:8765──> Blender 插件

Web 浏览器 ──HTTP──> slotmcp.ui.http_api ──┬─> 同上 tools 层
                                           └─> 同一 bridge 实例
```

两侧（MCP 与 UI）通过同一个 BlenderBridge 实例访问 Blender，因此状态一致。

## 2. MCP 协议细节

* **传输**：stdio。默认「换行分隔 JSON」；若客户端使用 LSP 风格 `Content-Length: N\r\n\r\n`，
  服务端会自动识别并以同样格式回包。
* **日志**：一律写 stderr，绝不污染 stdout。
* **方法**：

| 方法 | 返回 |
| --- | --- |
| `initialize` | `protocolVersion=2024-11-05`，capabilities 声明 tools + resources |
| `tools/list` | 15 个工具定义（含 JSON Schema 入参） |
| `tools/call` | `{content, isError, structuredContent}` |
| `resources/list` / `resources/read` | 每台机台暴露为 `slot://games/<id>`，内容为完整 JSON 配置 |
| `ping` | 空 result |
| `notifications/initialized` | 不回包（通知） |

* **错误码**：`-32700` 解析失败、`-32601` 未知方法、`-32602` 参数非法、`-32603` 内部错误（含 Blender 桥接异常）。

环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SLOT_MCP_BLENDER_HOST` | `127.0.0.1` | Blender 插件地址 |
| `SLOT_MCP_BLENDER_PORT` | `8765` | Blender 插件端口 |
| `SLOT_MCP_BLENDER_TIMEOUT` | `10` | 单条指令超时（秒） |
| `SLOT_MCP_ROOT` | 仓库根 | `configs/` 落盘根路径 |
| `SLOT_MCP_CONFIG_DIR` | `<root>/configs` | 参数落盘目录 |
| `SLOT_MCP_WEB_DIR` | `<root>/web` | 静态资源目录 |

## 3. 工具契约摘要

```
slot_list_games()                                   -> {games: [info...]}
slot_get_game(game_id)                              -> info + paytable + paylines
slot_get_config(game_id, path?)                     -> 配置或子树
slot_set_parameter(game_id, path, value, persist?)  -> 更新（非法则回滚）
slot_validate_config(game_id|config)                -> {valid, errors}
slot_spin(game_id, bet, lines?, spins?, seed?, state?) -> {spins: [...], total_bet, total_win}
slot_simulate(game_id, spins?, bet?, seed?)         -> RTP 报告
slot_session_create(session_id?, game_id, credits?) -> 会话
slot_session_spin(session_id?, bet?, bet_index?)    -> 会话 + 旋转结果
slot_session_gamble(session_id?, choice?, take?)    -> 博彩结果
slot_session_snapshot(session_id?)                  -> 快照（可持久化/恢复）
blender_status()                                    -> {connected, blender?, error?}
blender_build_cabinet(game_id, scale?)              -> 构建 3D 机台
blender_animate_spin(game_id|session_id|spin, fps?) -> 生成转轮动画
blender_exec(code)                                  -> 远端执行（需在插件面板开启）
```

约定：**任何错误都返回 `isError=true` 的结构体**，不抛异常、不断开 MCP 会话。

## 4. Blender 桥接协议

| 项 | 约定 |
| --- | --- |
| 传输 | TCP，服务端在 Blender 插件侧，默认 `127.0.0.1:8765` |
| 封帧 | `4 字节大端长度 + UTF-8 JSON`，最大 32MB |
| 请求 | `{"id": "<uuid>", "op": "...", "params": {...}}` |
| 响应 | `{"id": "<uuid>", "ok": true|false, "result": {...}, "error": "..."}` |
| 指令 | `ping` / `status` / `build_cabinet` / `animate_spin` / `exec` |

### 4.1 稳定性机制

1. **单读线程 + 请求级 Event**：连接建立后启动后台读线程统一收包并按 `id` 唤醒等待方，
   业务线程从不直接读 socket；
2. **写串行化**：所有发送在一把锁内完成，杜绝多线程交错产生半包；
3. **超时保护**：每条请求可独立设置超时（默认 10s），超时即拆除连接，避免读线程永久挂起；
4. **心跳探活**：默认 5s 一次 `ping`，对方掉线立即发现，不必等到业务请求超时；
5. **自动重连**：下一次调用发现连接不可用时会重连（默认重试 3 次、指数退避），成功后重试一次；
6. **优雅降级**：Blender 未启动时 `blender_status` 仍返回结构化状态（含原因），
   MCP/HTTP 层把它翻译成提示而不是异常；
7. **主线程约束**：Blender 侧用 `bpy.app.timers` 消费队列，
   所有会改动数据的指令都在主线程执行（多线程操作 depsgraph 是 Blender 崩溃的常见原因）。

### 4.2 典型故障与表现

| 故障 | 系统表现 |
| --- | --- |
| Blender 未启动 | `blender_status.connected=false` + `error`；游戏工具照常可用 |
| Blender 执行中崩溃 | 读线程退出 → 连接拆除 → 下次调用自动重连；本次请求返回超时错误 |
| 单条指令卡住 | 超过 `SLOT_MCP_BLENDER_TIMEOUT` 抛 `BlenderBridgeError`，连接重建 |
| `exec` 未授权 | Blender 端返回 `ok=false`，前端/工具显示「exec 指令已被禁用」 |

## 5. 与现有 MCP 服务合并的方式

若已有 MCP 服务，有三种接入粒度：

1. **进程级（推荐）**：把本项目作为独立 server 注册到同一份配置里（见 `mcp.example.json`），
   与既有 server 平级共存，互不影响；
2. **工具级**：把 `slotmcp.mcp.tools.TOOLS` 与 `handle_tool` 引入既有服务的方法分发表，
   工具名以 `slot_`/`blender_` 前缀隔离；
3. **库级**：直接在既有服务代码中 `from slotmcp.engine.game import get_registry`，
   跳过网络层使用 Python API。

## 6. 自检清单

```bash
python -m slotmcp.mcp.server --selftest      # 列出工具与机台
python tests/test_mcp.py                     # 工具契约 + 错误收敛
python tests/test_bridge.py                  # 封帧/超时/重连/降级
python tests/test_ui.py                      # REST 全链路
```
