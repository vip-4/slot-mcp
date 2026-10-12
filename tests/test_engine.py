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
    check(len(ids) == 6, f"内置 6 款机台: {', '.join(ids)}")
    check("fortune_koi" in ids, "新增机台 fortune_koi 已注册")
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


def test_collect_and_random_wild() -> None:
    print("[engine] 随机 Wild 投放 / Cash Collect")
    from slotmcp.engine.features import collect_coins, place_random_wilds

    grid = [
        ["carp", "scatter", "coin_b"],
        ["ingot", "coin_s", "coin_g"],
    ]
    # 保护符号（Scatter / 币值）不得被覆盖
    placed = place_random_wilds(
        grid, "wild", 3, SlotRNG("rw"), exclude_reels=[], protected_symbols=["scatter", "coin_b", "coin_s", "coin_g"]
    )
    check(len(placed) == 2, f"只覆盖可替换位置（期望 2 个，实际 {len(placed)}）")
    check(all(grid[r][c] == "wild" for r, c in placed), "落点已替换为 Wild")
    check(
        any("scatter" in col for col in grid) and any("coin_g" in col for col in grid),
        "受保护符号未被覆盖",
    )

    grid2 = [["carp", "carp"], ["ingot", "ingot"]]
    placed2 = place_random_wilds(grid2, "wild", 2, SlotRNG("rw2"), exclude_reels=[0], protected_symbols=[])
    check(all(r == 1 for r, _ in placed2), f"exclude_reels 生效：{placed2}")

    grid3 = [["carp", "carp", "carp"]]
    coins = collect_coins(grid3, ["coin_b"])
    check(coins == [], "没有币值符号时收集为空")

    # 收集结算：基础 1x / 免费 2x / 含大奖币
    koi = get_registry().get("fortune_koi")
    cfg = koi.config
    check(
        cfg.features.random_wild is not None and cfg.features.collect is not None,
        "fortune_koi 同时启用 random_wild 与 collect",
    )
    ctx = koi.build_context(total_bet=1.0)
    from slotmcp.engine.game import GameState

    st = GameState()
    grid4 = [
        ["coin_b", "coin_s", "coin_g"],
        ["wild", "carp", "carp"],
        ["carp", "carp", "carp"],
        ["carp", "carp", "carp"],
        ["carp", "carp", "carp"],
    ]
    award = koi._collect_award(cfg, st, ctx, grid4)
    check(award is not None and award.kind == "collect", "收集者 + 币值命中时产生 collect 中奖")
    expected = (0.11 + 0.55 + 2.2) * 1.0
    check(abs((award.amount or 0) - expected) < 1e-6, f"基础收集额 = {expected}（实际 {award.amount}）")

    st.phase = PHASE_FREE
    award_free = koi._collect_award(cfg, st, ctx, grid4)
    check(abs((award_free.amount or 0) - expected * 2) < 1e-6, "免费旋转收集倍率 ×2")

    grid5 = [
        ["coin_jp", "carp", "carp"],
        ["wild", "carp", "carp"],
        ["carp", "carp", "carp"],
        ["carp", "carp", "carp"],
        ["carp", "carp", "carp"],
    ]
    st.phase = "base"
    award_jp = koi._collect_award(cfg, st, ctx, grid5)
    check(abs((award_jp.amount or 0) - 7.0) < 1e-6, f"大奖币按 jackpot_value 结算（实际 {award_jp.amount}）")

    st.phase = "base"
    grid6 = [["coin_b"] * 3 for _ in range(5)]  # 有币无收集者
    check(koi._collect_award(cfg, st, ctx, grid6) is None, "缺少收集者时不派奖")

    # 权重 0 表示该符号不在该轴出现（新机台的稀有币依赖此语义）
    expanded = cfg.reel_sets["base"].expanded(cfg.rows)
    check(
        all("coin_jp" not in strip for strip in expanded),
        "基础条带中权重为 0 的稀有币不出现",
    )
    check(any("coin_jp" in strip for strip in cfg.reel_sets["free"].expanded(cfg.rows)), "免费条带保留稀有币")

    # 端到端：能命中 collect / random_wild 事件
    hit = {"collect": 0, "random_wild": 0}
    koi.rng = SlotRNG("koi")
    for _ in range(3000):
        res = koi.spin(total_bet=1.0)
        # random_wild / collect 是步骤级事件（result.events 只放触发级事件）
        for step in res.steps:
            for e in step.events:
                if e["type"] in hit:
                    hit[e["type"]] += 1
    check(hit["collect"] > 0, f"端到端可触发 Cash Collect（{hit['collect']} 次）")
    check(hit["random_wild"] > 0, f"端到端可触发随机 Wild（{hit['random_wild']} 次）")

    # 参数可调：调整收集倍率后结果随之变化
    from slotmcp.engine.config import set_parameter as _set

    before = koi._collect_award(cfg, st, ctx, grid4).amount
    _set(cfg, "features.collect.award_multiplier", 3.0)
    after = koi._collect_award(cfg, st, ctx, grid4).amount
    _set(cfg, "features.collect.award_multiplier", 1.0)
    check(abs(after - before * 3) < 1e-6, "slot_set_parameter 可调整收集倍率并即时生效")


def test_feature_config_validation() -> None:
    print("[engine] 新特性配置校验")
    from slotmcp.engine.config import CollectConfig, Features, GameConfig, RandomWildConfig

    bad = GameConfig(
        id="bad_collect",
        name="bad",
        reels=5,
        rows=3,
        symbols={"wild": _sym("wild", "wild"), "coin_b": _sym("coin_b", "bonus")},
        reel_sets={"base": _reel_set(["wild", "coin_b"])},
        features=Features(
            collect=CollectConfig(enabled=True, collector="nope", coin_symbols=["coin_b"], coin_values={}),
            random_wild=RandomWildConfig(enabled=True, symbol="ghost", counts={}, phases=["nonsense"]),
        ),
    )
    errors = bad.validate()
    joined = " | ".join(errors)
    check(any("collect.collector" in e for e in errors), f"收集者未定义被拦截：{joined[:120]}")
    check(any("coin_values" in e for e in errors), "缺少面值被拦截")
    check(any("random_wild.symbol" in e for e in errors), "随机 Wild 符号未定义被拦截")
    check(any("counts" in e for e in errors), "随机 Wild 权重为空被拦截")
    check(any("phases" in e for e in errors), "非法阶段被拦截")


def _sym(symbol_id: str, kind: str):
    from slotmcp.engine.config import Symbol, SymbolKind

    return Symbol(symbol_id, symbol_id, SymbolKind(kind))


def _reel_set(symbols):
    from slotmcp.engine.config import ReelSet

    return ReelSet(name="base", strips=[list(symbols) for _ in range(5)], weights=[{s: 1 for s in symbols} for _ in range(5)])


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
    test_collect_and_random_wild()
    test_feature_config_validation()
    test_session()
    test_hot_reload()
    test_rtp_regression()
    print(f"\n[engine] 全部通过（{CHECKS} 项断言）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
