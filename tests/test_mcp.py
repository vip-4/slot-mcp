"""MCP 层自测（不依赖 Blender）：直接调用 `handle_tool` 验证工具契约与错误收敛。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from slotmcp.mcp.tools import TOOLS, handle_tool  # noqa: E402

EXPECTED_TOOLS = {
    "slot_list_games",
    "slot_get_game",
    "slot_get_config",
    "slot_set_parameter",
    "slot_validate_config",
    "slot_spin",
    "slot_simulate",
    "slot_session_create",
    "slot_session_spin",
    "slot_session_gamble",
    "slot_session_snapshot",
    "blender_status",
    "blender_build_cabinet",
    "blender_animate_spin",
    "blender_exec",
}


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ok  {message}")


def main() -> int:
    print("[mcp] 工具注册")
    names = {t["name"] for t in TOOLS}
    check(EXPECTED_TOOLS.issubset(names), f"工具齐全（{len(names)} 个）")
    check(all("inputSchema" in t for t in TOOLS), "每个工具都有 inputSchema")

    print("[mcp] 工具调用")
    listed = handle_tool("slot_list_games", {})
    check(not listed["isError"], "slot_list_games 成功")
    check(len(listed["data"]["games"]) == 7, "返回 7 台机台")

    spun = handle_tool("slot_spin", {"game_id": "candy_carnival", "bet": 2.0, "spins": 3})
    check(not spun["isError"], "slot_spin 成功")
    check(len(spun["data"]["spins"]) == 3, "返回 3 局结果")
    grid = spun["data"]["spins"][0]["steps"][0]["grid"]
    check(len(grid) == 5 and len(grid[0]) == 3, "网格尺寸为 5x3")

    ok = handle_tool("slot_spin", {"game_id": "lucky_fruits", "bet": 1.0, "seed": 42})
    again = handle_tool("slot_spin", {"game_id": "lucky_fruits", "bet": 1.0, "seed": 42})
    check(
        ok["data"]["spins"][0]["steps"][0]["grid"] == again["data"]["spins"][0]["steps"][0]["grid"],
        "相同种子可复现同一局",
    )

    print("[mcp] 参数热更新")
    tuned = handle_tool(
        "slot_set_parameter",
        {"game_id": "candy_carnival", "path": "features.expanding_wild.respins", "value": 2},
    )
    check(not tuned["isError"], "slot_set_parameter 成功")
    check(tuned["data"]["value"] == 2, "返回值已更新")

    bad = handle_tool(
        "slot_set_parameter",
        {"game_id": "candy_carnival", "path": "features.expanding_wild.respins", "value": -5},
    )
    check(bad["isError"] and "非法" in bad["content"][0]["text"], "非法值被拦截并回滚")

    print("[mcp] 会话")
    created = handle_tool(
        "slot_session_create", {"session_id": "t1", "game_id": "lucky_fruits", "credits": 100.0}
    )
    check(not created["isError"], "会话创建成功")
    played = handle_tool("slot_session_spin", {"session_id": "t1", "bet": 1.0})
    check(not played["isError"], "会话旋转成功")
    check(abs(played["data"]["credits"] - (100.0 - played["data"]["bet"] + played["data"]["result"]["total_win"])) < 1e-6, "余额结算正确")

    print("[mcp] 错误收敛")
    missing = handle_tool("slot_spin", {"game_id": "not_exists"})
    check(missing["isError"], "未知机台返回结构化错误而非抛异常")
    unknown = handle_tool("no_such_tool", {})
    check(unknown["isError"], "未知工具返回结构化错误")

    print("[mcp] 桥接未启动时的降级")
    status = handle_tool("blender_status", {}, None)
    check(status["isError"], "无桥接时返回明确错误")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
