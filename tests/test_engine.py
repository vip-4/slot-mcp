"""CONFIG 引擎单元测试：转轮、赔付判定、特性、会话、热更新与 RTP 回归。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from slotmcp.engine.config import (  # noqa: E402
    ConfigError,
    PayMode,
    set_parameter,
)
from slotmcp.engine.evaluator import evaluate_grid  # noqa: E402
from slotmcp.engine.game import PHASE_FREE, PHASE_HOLD, get_registry  # noqa: E402
from slotmcp.engine.paylines import generate_lines, get_lines  # noqa: E402
from slotmcp.engine.rng import SlotRNG  # noqa: E402
from slotmcp.engine.session import SlotSession  # noqa: E402
from slotmcp.engine.simulator import simulate  # noqa: E402
from slotmcp.games import game_ids, iter_game_configs  # noqa: E402

CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    if not condition:
        raise AssertionError(message)
    CHECKS += 1
    print(f"  ok  {message}")


def test_configuration() -> None:
    print("[engine] 配置与校验")
    ids = game_ids()
    check(len(ids) == 5, f"内置 5 款机台: {', '.join(ids)}")
    for cfg in iter_game_configs():
        errors = cfg.validate()
        check(not errors, f"{cfg.id} 配置校验通过")
        check(len(cfg.reel_sets[cfg.base_reel_set].strips) == cfg.reels, f"{cfg.id} 条带数与轴数一致")
    check(get_registry().get("lucky_fruits").config.pay_mode == PayMode.LINES, "lucky_fruits 为固定线模式")
    check(get_registry().get("star_expedition").config.ways() == 4096, "star_expedition 为 4096 Ways")

    print("[engine] 赔付线")
    check(len(get_lines(5, 3, 20)) == 20, "5x3 内置 20 线")
    check(len(get_lines(3, 3, 5)) == 5, "3x3 内置 5 线")
    check(len(generate_lines(5, 4, 50)) == 50, "5x4 生成 50 线")
    first = get_lines(5, 3, 20)[0]
    check(first == [1, 1, 1, 1, 1], "第一条线为中行")
    try:
        generate_lines(3, 3, 30)
        raise AssertionError("应当在候选线不足时报错")
    except ValueError:
        check(True, "候选线不足时抛出 ValueError")


def test_determinism() -> None:
    print("[engine] 随机数可复现")
    machine = get_registry().get("candy_carnival")
    machine.rng = SlotRNG("same-seed")
    first = machine.spin(total_bet=1.0).to_dict()
    machine.rng = SlotRNG("same-seed")
    second = machine.spin(total_bet=1.0).to_dict()
    check(first["steps"] == second["steps"], "相同种子产生相同结果")

    machine.rng = SlotRNG(1)
    a = machine.spin(total_bet=1.0)
    machine.rng = SlotRNG(2)
    b = machine.spin(total_bet=1.0)
    check(a.to_dict()["steps"] != b.to_dict()["steps"], "不同种子产生不同结果")


def test_payline_evaluation() -> None:
    print("[engine] 赔付判定")
    cfg = get_registry().get("lucky_fruits").config
    # grid[reel][row]：中行（row 1）放三连樱桃
    grid = [["bell", "cherry", "bell"], ["bell", "cherry", "bell"], ["bell", "cherry", "bell"]]
    wins = evaluate_grid(cfg, grid, total_bet=1.0, line_bet=0.2, lines=[[1, 1, 1]])
    total = sum(w.amount for w in wins)
    check(total == 5 * 0.2, f"三连樱桃按 5x 线注赔付（实得 {total:.2f}）")

    grid = [["bell", "cherry", "bell"], ["bell", "wild", "bell"], ["bell", "cherry", "bell"]]
    wins = evaluate_grid(cfg, grid, total_bet=1.0, line_bet=0.2, lines=[[1, 1, 1]])
    check(sum(w.amount for w in wins) == 5 * 0.2, "Wild 可替代参与连线")

    grid = [["bell", "cherry", "bell"], ["bell", "lemon", "bell"], ["bell", "lemon", "bell"]]
    wins = evaluate_grid(cfg, grid, total_bet=1.0, line_bet=0.2, lines=[[1, 1, 1]])
    check(sum(w.amount for w in wins) == 0, "左侧不连续时不赔付")

    cfg_ways = get_registry().get("pharaoh_tomb").config
    grid = [["ankh"] * 3, ["ankh"] * 3, ["ankh"] * 3, ["cat"] * 3, ["cat"] * 3]
    wins = evaluate_grid(cfg_ways, grid, total_bet=1.0)
    line_wins = [w for w in wins if w.kind == "ways"]
    check(len(line_wins) == 1 and line_wins[0].count == 3, "Ways 模式按相邻轴计数")
    check(line_wins[0].amount > 0, "Ways 赔付金额为正")


def test_feature_flows() -> None:
    print("[engine] 特性流程")
    dragon = get_registry().get("dragon_palace")
    found = None
    for seed in range(1, 4000):
        dragon.rng = SlotRNG(seed)
        result = dragon.spin(total_bet=1.0)
        if any(e["type"] == "free_spins_trigger" for e in result.events):
            found = result
            break
    check(found is not None, "可在合理种子范围内触发免费旋转")
    if found:
        check(any(s.phase == PHASE_FREE for s in found.steps), "结果包含免费旋转步骤")
        check(sum(1 for s in found.steps if s.phase == PHASE_FREE) >= 1, "免费旋转至少 1 步")
        check(found.state.phase == "base", "免费旋转结束后回到基础阶段")

    pharaoh = get_registry().get("pharaoh_tomb")
    found = None
    for seed in range(1, 20000):
        pharaoh.rng = SlotRNG(seed)
        result = pharaoh.spin(total_bet=1.0)
        if any(e["type"] == "hold_win_trigger" for e in result.events):
            found = result
            break
    check(found is not None, "可在合理种子范围内触发 Hold & Win")
    if found:
        hold_steps = [s for s in found.steps if s.phase == PHASE_HOLD]
        check(len(hold_steps) >= 2, "Hold & Win 包含多次重转步骤")
        check(found.state.phase == "base", "Hold & Win 结束后回到基础阶段")
        check(sum(s.step_win for s in hold_steps) > 0, "Hold & Win 有实际派彩")


def test_session() -> None:
    print("[engine] 会话与钱包")
    machine = get_registry().get("lucky_fruits")
    session = SlotSession(machine, session_id="unit", credits=100.0)
    session.set_bet_index(3)
    bet = session.current_bet
    result = session.spin()
    check(abs(session.credits - (100 - bet + result.total_win)) < 1e-6, "余额 = 初始 - 下注 + 派彩")

    session.credits = 0.0
    try:
        session.spin()
        raise AssertionError("余额不足时应报错")
    except RuntimeError:
        check(True, "余额不足时拒绝旋转")

    gamble_machine = machine
    gamble_machine.config.features.gamble.win_probability = 1.0
    session = SlotSession(gamble_machine, session_id="gamble", credits=500.0)
    session.rng = SlotRNG(1)
    session.pending_gamble = True
    session._gamble_stake = 10.0
    outcome = session.gamble("red")
    check(outcome["stake"] == 20.0 and not outcome["finished"], "必胜时奖金翻倍")
    taken = session.take_gamble()
    check(taken["collected"] == 20.0, "可随时收下奖金")
    gamble_machine.config.features.gamble.win_probability = 0.5


def test_hot_reload() -> None:
    print("[engine] 参数热更新")
    cfg = get_registry().get("candy_carnival").config.clone()
    set_parameter(cfg, "symbols.gift.pays.5", 999)
    check(cfg.symbols["gift"].pays[5] == 999, "点号路径写入生效")
    set_parameter(cfg, "features.expanding_wild.respins", 0)
    check(cfg.features.expanding_wild.respins == 0, "嵌套字段写入生效")
    get_registry().register(cfg, replace=True)
    check(get_registry().get("candy_carnival").config.symbols["gift"].pays[5] == 999, "注册后可替换生效")
    get_registry(reload=True)

    bad = get_registry().get("lucky_fruits").config.clone()
    bad.reel_sets["base"].strips = [["cherry"]]
    errors = bad.validate()
    check(any("rows" in e or "长度" in e for e in errors), "非法条带会被校验拦截")
    try:
        from slotmcp.engine.config import GameConfig
        from slotmcp.engine.game import SlotMachine

        SlotMachine(bad)
        raise AssertionError("非法配置应当无法实例化")
    except ConfigError:
        check(True, "SlotMachine 拒绝非法配置")


def test_rtp_regression() -> None:
    print("[engine] RTP 回归（2 万局快速档）")
    for game_id in game_ids():
        machine = get_registry().get(game_id)
        report = simulate(machine, spins=20_000, bet=1.0, seed=f"regression:{game_id}")
        check(
            0.88 <= report.rtp <= 1.05,
            f"{game_id} RTP {report.rtp:.4f} 在合理区间（目标 {report.target_rtp:.2f}）",
        )
        check(report.hit_rate > 0.2, f"{game_id} 命中率 {report.hit_rate:.2%} 合理")


def main() -> int:
    test_configuration()
    test_determinism()
    test_payline_evaluation()
    test_feature_flows()
    test_session()
    test_hot_reload()
    test_rtp_regression()
    print(f"\n[engine] 全部通过（{CHECKS} 项断言）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
