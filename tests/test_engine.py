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
    check(len(ids) == 10, f"内置 10 款机台: {', '.join(ids)}")
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


def test_multiplier_wild_and_pick_bonus() -> None:
    print("[engine] 倍率 Wild / Pick'em 选宝")
    from slotmcp.engine.config import MultiplierWildConfig, PickBonusConfig
    from slotmcp.engine.evaluator import evaluate_lines, evaluate_ways
    from slotmcp.engine.features import resolve_pick_bonus

    tt = get_registry().get("thunder_temple")
    cfg = tt.config
    ctx = tt.build_context(total_bet=1.0)

    # 同一命中里 ×2 与 ×3 相加 => ×4（combine=sum）
    grid = [
        ["rune", "eagle", "rune"],
        ["rune", "wild_x2", "rune"],
        ["rune", "wild_x3", "rune"],
        ["rune", "eagle", "rune"],
        ["rune", "wolf", "rune"],
    ]
    wins = evaluate_lines(cfg, grid, line_bet=ctx.line_bet, lines=ctx.lines, active_lines=ctx.active_lines, base_multiplier=1.0)
    eagle = [w for w in wins if w.symbol == "eagle"]
    check(bool(eagle), "倍率 Wild 参与替代并产生线赔")
    check(all(w.multiplier == 4.0 for w in eagle), f"×2 + ×3 相加为 ×4（实际 {[w.multiplier for w in eagle]}）")

    # combine 可切换：max / product
    for mode, expected in (("max", 3.0), ("product", 6.0), ("sum", 4.0)):
        cfg.features.multiplier_wild = MultiplierWildConfig(
            enabled=True, symbols={"wild_x2": 2.0, "wild_x3": 3.0}, combine=mode
        )
        w = [x for x in evaluate_lines(cfg, grid, line_bet=ctx.line_bet, lines=ctx.lines, active_lines=ctx.active_lines, base_multiplier=1.0) if x.symbol == "eagle"]
        check(w and abs(w[0].multiplier - expected) < 1e-9, f"combine={mode} -> ×{expected}（实际 {w[0].multiplier if w else None}）")

    cfg.features.multiplier_wild = MultiplierWildConfig(
        enabled=True, symbols={"wild_x2": 2.0, "wild_x3": 3.0}, combine="sum"
    )
    # Ways 结算同样生效（用本机台符号构造相邻轴命中）
    wgrid = [
        ["eagle", "rune", "rune"],
        ["wild_x2", "eagle", "rune"],
        ["eagle", "rune", "rune"],
        ["eagle", "rune", "rune"],
        ["rune", "rune", "rune"],
    ]
    ways_wins = evaluate_ways(cfg, wgrid, bet_per_way=ctx.line_bet, base_multiplier=1.0)
    eagle_ways = [w for w in ways_wins if w.symbol == "eagle"]
    check(
        bool(eagle_ways) and eagle_ways[0].multiplier == 2.0,
        f"Ways 结算也应用倍率 Wild（{[w.multiplier for w in ways_wins]}）",
    )

    # Pick'em：无放回抽完即停，有放回可重复
    pb = PickBonusConfig(
        enabled=True,
        trigger_symbol="totem",
        trigger_counts={3: 3},
        prize_pool={"a": 1.0, "b": 2.0},
        weights={"a": 1, "b": 1},
        unique=True,
    )
    picks, total = resolve_pick_bonus(cfg, pb, 3, SlotRNG("pick"))
    check(len(picks) == 2 and total == 3.0, f"无放回最多抽完奖品池：{picks} / {total}")

    pb2 = PickBonusConfig(
        enabled=True,
        trigger_symbol="totem",
        trigger_counts={3: 4},
        prize_pool={"a": 1.0},
        weights={"a": 1},
        unique=False,
        award_multiplier=2.0,
    )
    picks2, total2 = resolve_pick_bonus(cfg, pb2, 4, SlotRNG("pick2"))
    check(len(picks2) == 4 and abs(total2 - 8.0) < 1e-9, f"有放回可重复且应用总倍率：{picks2} / {total2}")

    # 端到端：能触发 pick_bonus，且触发符号个数决定挑选次数
    from slotmcp.engine.game import GameState

    st = GameState()
    g3 = [["totem", "rune", "rune"]] + [["rune", "rune", "rune"] for _ in range(4)]
    g3[1][1] = "totem"
    g3[2][1] = "totem"
    award = tt._pick_bonus_award(cfg, ctx, g3)
    check(award is not None and award[0].kind == "pick_bonus", "3 枚雷石触发选宝")
    check(len(award[1]) == 3, f"3 枚 -> 挑 3 次（实际 {len(award[1])}）")
    g2 = [["totem", "rune", "rune"], ["totem", "rune", "rune"]] + [["rune", "rune", "rune"] for _ in range(3)]
    check(tt._pick_bonus_award(cfg, ctx, g2) is None, "未达触发个数时不派奖")

    hit = 0
    tt.rng = SlotRNG("tt")
    for _ in range(4000):
        for step in tt.spin(total_bet=1.0).steps:
            if any(e.get("type") == "pick_bonus" for e in step.events):
                hit += 1
    check(hit > 0, f"端到端可触发选宝（{hit} 次）")

    # 参数可调
    from slotmcp.engine.config import set_parameter as _set

    _set(cfg, "features.pick_bonus.award_multiplier", 3.0)
    boosted = tt._pick_bonus_award(cfg, ctx, g3)
    _set(cfg, "features.pick_bonus.award_multiplier", 1.0)
    base = tt._pick_bonus_award(cfg, ctx, g3)
    check(boosted[0].amount > base[0].amount, "slot_set_parameter 可调整选宝总倍率")


def test_new_feature_config_validation() -> None:
    print("[engine] 倍率 Wild / 选宝 配置校验")
    from slotmcp.engine.config import (
        Features,
        GameConfig,
        MultiplierWildConfig,
        PickBonusConfig,
    )

    bad = GameConfig(
        id="bad_new",
        name="bad",
        reels=5,
        rows=3,
        symbols={"wild": _sym("wild", "wild"), "coin": _sym("coin", "bonus")},
        reel_sets={"base": _reel_set(["wild", "coin"])},
        features=Features(
            multiplier_wild=MultiplierWildConfig(
                enabled=True, symbols={"ghost": 2.0, "coin": 2.0}, combine="weird", apply_to=["line", "nope"]
            ),
            pick_bonus=PickBonusConfig(
                enabled=True,
                trigger_symbol="missing",
                trigger_counts={},
                prize_pool={"a": 1.0},
                weights={},
                unique=True,
                award_multiplier=0.0,
            ),
        ),
    )
    errors = bad.validate()
    joined = " | ".join(errors)
    check(any("multiplier_wild 引用未定义符号" in e for e in errors), f"倍率 Wild 符号未定义被拦截：{joined[:160]}")
    check(any("只能作用于 Wild" in e for e in errors), "倍率 Wild 指向非 Wild 被拦截")
    check(any("combine 非法" in e for e in errors), "非法合并方式被拦截")
    check(any("apply_to 非法" in e for e in errors), "非法生效范围被拦截")
    check(any("pick_bonus.trigger_symbol" in e for e in errors), "选宝触发符号未定义被拦截")
    check(any("trigger_counts" in e for e in errors), "选宝触发个数为空被拦截")
    check(any("weights 缺少或非法" in e for e in errors), "选宝奖品缺少权重被拦截")
    check(any("award_multiplier" in e for e in errors), "选宝总倍率非正被拦截")


def test_colossal_symbols() -> None:
    print("[engine] 巨符号（Colossal Symbol）")
    from slotmcp.engine.config import ColossalSymbolConfig
    from slotmcp.engine.features import place_colossal_symbol

    ruins = get_registry().get("colossal_ruins")
    cfg = ruins.config
    cc = cfg.features.colossal
    check(cc is not None and cc.enabled, "colossal_ruins 启用巨符号")

    # 固定网格 + 固定配置：块必须被完整写入
    grid = [["leaf", "leaf", "leaf"] for _ in range(5)]
    cc2 = ColossalSymbolConfig(
        enabled=True,
        size_weights={2: 1},
        symbols={"idol": 1},
        reels=[1],
        rows=[0],
        phases=["base"],
        protected_symbols=["scatter"],
    )
    block = place_colossal_symbol(grid, cfg, cc2, SlotRNG("blk"), "base")
    check(block is not None and block["size"] == 2, "投放 2×2 块")
    check(
        all(grid[r][c] == "idol" for r in (1, 2) for c in (0, 1)),
        f"块内格子被整体替换：{[row[:2] for row in grid[1:3]]}",
    )
    check(block["positions"] == [(1, 0), (1, 1), (2, 0), (2, 1)], f"落点坐标有序：{block['positions']}")

    # 受保护符号：块内出现 Scatter 时放弃投放
    grid2 = [["leaf", "leaf", "leaf"] for _ in range(5)]
    grid2[2][1] = "scatter"
    check(place_colossal_symbol(grid2, cfg, cc2, SlotRNG("blk2"), "base") is None, "撞到受保护符号时放弃投放")
    check(all("scatter" in col for col in [grid2[2]]) and grid2[1][0] == "leaf", "放弃时不改动网格")

    # 阶段过滤
    check(place_colossal_symbol([["leaf"] * 3 for _ in range(5)], cfg, cc2, SlotRNG("p"), "free_spins") is None,
          "未配置的阶段不投放")

    # 尺寸抽样：权重决定 2×2 与 3×3 的比例
    sizes: Dict[int, int] = {}
    for i in range(4000):
        g = [["leaf", "leaf", "leaf"] for _ in range(5)]
        b = place_colossal_symbol(g, cfg, cfg.features.colossal, SlotRNG(f"sz{i}"), "base")
        if b:
            sizes[b["size"]] = sizes.get(b["size"], 0) + 1
    check(set(sizes) == {2, 3}, f"两种尺寸都会出现：{sizes}")
    check(sizes.get(2, 0) > sizes.get(3, 0), "2×2 比 3×3 更常见（权重 55 : 20）")

    # 端到端：能触发事件，且块尺寸合法
    ruins.rng = SlotRNG("ruins")
    hit = 0
    for _ in range(2000):
        for step in ruins.spin(total_bet=1.0).steps:
            for e in step.events:
                if e.get("type") == "colossal":
                    hit += 1
                    sym = step.grid[e["reel"]][e["row"]]
                    assert sym == e["symbol"], "块内符号应与事件一致"
    check(hit > 0, f"端到端可触发巨符号（{hit} 次）")

    # 参数可调：关掉 3×3 后不再出现该尺寸
    from slotmcp.engine.config import set_parameter as _set

    _set(cfg, "features.colossal.size_weights.3", 0)
    sizes2: Dict[int, int] = {}
    for i in range(2000):
        g = [["leaf", "leaf", "leaf"] for _ in range(5)]
        b = place_colossal_symbol(g, cfg, cfg.features.colossal, SlotRNG(f"z{i}"), "base")
        if b:
            sizes2[b["size"]] = sizes2.get(b["size"], 0) + 1
    _set(cfg, "features.colossal.size_weights.3", 20)
    check(3 not in sizes2, f"slot_set_parameter 可关闭 3×3（{sizes2}）")


def test_colossal_config_validation() -> None:
    print("[engine] 巨符号配置校验")
    from slotmcp.engine.config import ColossalSymbolConfig, Features, GameConfig

    bad = GameConfig(
        id="bad_colossal",
        name="bad",
        reels=5,
        rows=3,
        symbols={"wild": _sym("wild", "wild"), "scatter": _sym("scatter", "scatter")},
        reel_sets={"base": _reel_set(["wild", "scatter", "leaf"])},
        features=Features(
            colossal=ColossalSymbolConfig(
                enabled=True,
                size_weights={1: 1, 9: 1},
                symbols={"ghost": 1, "scatter": 1},
                reels=[7],
                rows=[9],
                phases=["nonsense"],
            )
        ),
    )
    errors = bad.validate()
    joined = " | ".join(errors)
    check(any("块尺寸至少为 2" in e or "超过网格范围" in e for e in errors), f"非法块尺寸被拦截：{joined[:160]}")
    check(any("引用未定义符号" in e for e in errors), "未定义符号被拦截")
    check(any("只能投放标准符号或 Wild" in e for e in errors), "Scatter 不可被投放被拦截")
    check(any("reels 超出轴范围" in e for e in errors), "落点轴越界被拦截")
    check(any("rows 超出排范围" in e for e in errors), "落点排越界被拦截")
    check(any("phases 非法" in e for e in errors), "非法阶段被拦截")


def test_mystery_symbols() -> None:
    print("[engine] 神秘符号（Mystery Symbol）")
    from slotmcp.engine.config import MysterySymbolConfig
    from slotmcp.engine.features import reveal_mystery_symbols

    ph = get_registry().get("phoenix_rebirth")
    cfg = ph.config
    ms = cfg.features.mystery
    check(ms is not None and ms.enabled, "phoenix_rebirth 启用神秘符号")
    check(cfg.symbols[ms.symbol].kind.value == "bonus", "占位符号为 bonus（本身不参与线赔）")

    # 全屏揭示为同一符号：只消耗 1 个随机数
    grid = [["egg", "plume", "ash"], ["plume", "egg", "ash"], ["ash", "ash", "egg"]]
    ev = reveal_mystery_symbols(grid, ms, SlotRNG("egg1"), "base")
    check(ev is not None and ev["count"] == 3, f"三个蛋一次揭示：{ev}")
    revealed = ev["symbol"]
    check(
        all(grid[r][c] == revealed for r, c in ev["positions"]),
        "所有蛋揭示为同一符号",
    )
    check(revealed != "egg", "揭示结果不会是占位符号本身")

    # 独立揭示模式：逐格抽取，允许出现不同结果
    indie = MysterySymbolConfig(
        enabled=True,
        symbol="egg",
        reveal_symbols={"plume": 1, "ash": 1},
        reveal_all_same=False,
    )
    seen = set()
    for i in range(40):
        g = [[["egg", "egg"], ["egg", "egg"]] for _ in range(1)]
        g = [["egg", "egg"], ["egg", "egg"]]
        ev2 = reveal_mystery_symbols(g, indie, SlotRNG(f"i{i}"), "base")
        assert ev2 is not None
        seen.add(",".join(g[0] + g[1]))
    check(len(seen) > 1, f"独立揭示时逐格抽取（出现 {len(seen)} 种组合）")

    # 无蛋 / 阶段不匹配 -> 不产生事件
    check(reveal_mystery_symbols([["plume"]], ms, SlotRNG("x"), "base") is None, "无占位符号时无事件")
    only_base = MysterySymbolConfig(enabled=True, symbol="egg", reveal_symbols={"plume": 1}, phases=["base"])
    check(
        reveal_mystery_symbols([["egg"]], only_base, SlotRNG("y"), "free_spins") is None,
        "不在生效阶段时不揭示",
    )

    # 端到端：事件可见，且网格与事件一致
    ph.rng = SlotRNG("phoenix")
    hit = 0
    reveals: Dict[str, int] = {}
    for _ in range(3000):
        for step in ph.spin(total_bet=1.0).steps:
            for e in step.events:
                if e.get("type") == "mystery_reveal":
                    hit += 1
                    reveals[e["symbol"]] = reveals.get(e["symbol"], 0) + 1
                    for r, c in e["positions"]:
                        assert step.grid[r][c] == e["symbol"], "揭示后的网格应与事件一致"
    check(hit > 0, f"端到端可触发神秘符号（{hit} 次）")
    check(len(reveals) >= 3, f"揭示目标覆盖多种符号：{reveals}")
    check("wild" in reveals, "可以揭示为 Wild（配置里给了权重）")

    # 参数可调：把 Wild 权重调到 0 后不再揭示为 Wild
    from slotmcp.engine.config import set_parameter as _set

    _set(cfg, "features.mystery.reveal_symbols.wild", 0)
    g = [["egg", "egg", "egg"] for _ in range(5)]
    got_wild = False
    for i in range(300):
        gg = [["egg", "egg", "egg"] for _ in range(5)]
        ev3 = reveal_mystery_symbols(gg, cfg.features.mystery, SlotRNG(f"w{i}"), "base")
        if ev3 and ev3["symbol"] == "wild":
            got_wild = True
            break
    _set(cfg, "features.mystery.reveal_symbols.wild", 10)
    check(not got_wild, "slot_set_parameter 可把 Wild 权重调为 0 并即时生效")


def test_mystery_config_validation() -> None:
    print("[engine] 神秘符号配置校验")
    from slotmcp.engine.config import Features, GameConfig, MysterySymbolConfig

    base = dict(
        id="bad_mystery",
        name="bad",
        reels=5,
        rows=3,
        symbols={
            "plume": _sym("plume", "standard"),
            "wild": _sym("wild", "wild"),
            "scatter": _sym("scatter", "scatter"),
        },
        reel_sets={"base": _reel_set(["plume", "wild", "scatter"])},
    )
    bad = GameConfig(
        features=Features(
            mystery=MysterySymbolConfig(
                enabled=True,
                symbol="plume",  # 已定义但不是 bonus
                reveal_symbols={"scatter": 1},  # 揭示目标非法
                phases=["nonsense"],
            )
        ),
        **base,
    )
    errors = bad.validate()
    joined = " | ".join(errors)
    check(any("必须是 bonus 类型" in e for e in errors), f"占位符号非 bonus 被拦截：{joined[:160]}")
    check(any("mystery 只能揭示" in e for e in errors), "揭示目标含 Scatter 被拦截")

    undef = GameConfig(
        features=Features(
            mystery=MysterySymbolConfig(enabled=True, symbol="ghost", reveal_symbols={"plume": 1})
        ),
        **base,
    )
    check(any("mystery.symbol 未定义" in e for e in undef.validate()), "占位符号未定义被拦截")

    bad2 = GameConfig(
        features=Features(
            mystery=MysterySymbolConfig(
                enabled=True,
                symbol="egg",
                reveal_symbols={"plume": 0},
            )
        ),
        symbols=dict(base["symbols"], egg=_sym("egg", "bonus")),
        reel_sets=base["reel_sets"],
        id="bad_mystery2",
        name="bad2",
        reels=5,
        rows=3,
    )
    errors2 = bad2.validate()
    joined2 = " | ".join(errors2)
    check(any("揭示权重必须为正" in e for e in errors2), f"非正权重被拦截：{joined2[:160]}")

    bad3 = GameConfig(
        features=Features(
            mystery=MysterySymbolConfig(
                enabled=True,
                symbol="egg",
                reveal_symbols={"egg": 1},
                phases=["base", "nope"],
            )
        ),
        symbols=dict(base["symbols"], egg=_sym("egg", "bonus")),
        reel_sets=base["reel_sets"],
        id="bad_mystery3",
        name="bad3",
        reels=5,
        rows=3,
    )
    errors3 = bad3.validate()
    joined3 = " | ".join(errors3)
    check(any("不能包含占位符号自身" in e for e in errors3), f"自引用被拦截：{joined3[:160]}")
    check(any("mystery.phases 非法" in e for e in errors3), "非法阶段被拦截")


def test_walking_wild() -> None:
    print("[engine] 行走 Wild（跨局状态算子）")
    from slotmcp.engine.config import WalkingWildConfig
    from slotmcp.engine.features import walk_wilds
    from slotmcp.engine.game import GameState, PHASE_BASE, PHASE_FREE

    fw = get_registry().get("frost_wolf")
    cfg = fw.config
    ww = cfg.features.walking_wild
    check(ww is not None and ww.enabled, "frost_wolf 启用行走 Wild")
    check(cfg.symbols[ww.symbol].kind.value == "wild", "行走符号必须是 Wild")
    check("free_spins" in ww.phases, "只在免费旋转阶段生效")

    grid = [
        ["axe", "axe", "axe", "axe"],
        ["axe", "axe", "axe", "axe"],
        ["wolf", "axe", "axe", "axe"],
        ["axe", "axe", "axe", "axe"],
        ["axe", "axe", "axe", "axe"],
    ]
    # 上一局登记在 (2,0)，本局左移一步 -> (1,0)
    walkers, ev = walk_wilds(grid, ww, [[2, 0]], PHASE_FREE)
    check(ev is not None and ev["moved"] == [[1, 0]], f"左移一步：{ev}")
    check(grid[1][0] == "wolf", "移动后写入网格")
    check([2, 0] in walkers, "本局屏上的 Wild 登记为下一局行走落点")

    # 移出网格 -> 消失
    g2 = [["axe"] * 4 for _ in range(5)]
    walkers2, ev2 = walk_wilds(g2, ww, [[0, 1]], PHASE_FREE)
    check(ev2 is None and walkers2 == [], "移出网格后消失且无事件")
    check(all("wolf" not in col for col in g2), "网格中不再有行走 Wild")

    # 撞到受保护符号（Scatter）-> 消失
    g3 = [["axe"] * 4 for _ in range(5)]
    g3[1][2] = "scatter"
    walkers3, ev3 = walk_wilds(g3, ww, [[2, 2]], PHASE_FREE)
    check(ev3 is None and walkers3 == [], "撞到受保护符号时消失")
    check(g3[1][2] == "scatter", "受保护符号未被覆盖")

    # 阶段不匹配 -> 不生效
    g4 = [["axe"] * 4 for _ in range(5)]
    walkers4, ev4 = walk_wilds(g4, ww, [[2, 0]], PHASE_BASE)
    check(ev4 is None and walkers4 == [], "不在生效阶段时不处理")

    # max_walkers 生效
    g5 = [["wolf"] * 4 for _ in range(5)]
    many = walk_wilds(g5, ww, [], PHASE_FREE)
    check(many[0] is not None and len(many[0]) <= ww.max_walkers, f"上限生效：{len(many[0])} <= {ww.max_walkers}")

    # 端到端：免费旋转里能连续多局看到行走 Wild，离开免费旋转后状态清空
    fw.rng = SlotRNG("frost")
    hits = 0
    max_consecutive = 0
    run = 0
    st_after: Optional[GameState] = None
    for _ in range(6000):
        res = fw.spin(total_bet=1.0)
        for step in res.steps:
            walked = any(e.get("type") == "walking_wild" for e in step.events)
            if walked:
                hits += 1
                run += 1
                max_consecutive = max(max_consecutive, run)
            elif step.phase == PHASE_FREE:
                run = 0
        st_after = res.state
    check(hits > 0, f"端到端可触发行走 Wild（{hits} 次）")
    check(max_consecutive >= 2, f"行走 Wild 可连续多局在场（最长 {max_consecutive} 局）")
    check(st_after is not None and st_after.walking_wilds == [], "离开免费旋转后行走状态已清空")

    # 参数可调：steps_per_spin 改成 2 后一次移动两列
    from slotmcp.engine.config import set_parameter as _set

    _set(cfg, "features.walking_wild.steps_per_spin", 2)
    g6 = [["axe"] * 4 for _ in range(5)]
    _, ev6 = walk_wilds(g6, cfg.features.walking_wild, [[3, 0]], PHASE_FREE)
    _set(cfg, "features.walking_wild.steps_per_spin", 1)
    check(ev6 is not None and ev6["moved"] == [[1, 0]], f"slot_set_parameter 可调整步长：{ev6}")


def test_walking_wild_config_validation() -> None:
    print("[engine] 行走 Wild 配置校验")
    from slotmcp.engine.config import Features, GameConfig, WalkingWildConfig

    base = dict(
        id="bad_walk",
        name="bad",
        reels=5,
        rows=3,
        symbols={"plume": _sym("plume", "standard"), "wild": _sym("wild", "wild")},
        reel_sets={"base": _reel_set(["plume", "wild"])},
    )
    bad = GameConfig(
        features=Features(
            walking_wild=WalkingWildConfig(
                enabled=True,
                symbol="plume",  # 不是 Wild
                steps_per_spin=0,
                direction="up",
                max_walkers=0,
                phases=["base"],  # 只在 base 无意义
            )
        ),
        **base,
    )
    errors = bad.validate()
    joined = " | ".join(errors)
    check(any("必须是 Wild" in e for e in errors), f"非 Wild 被拦截：{joined[:200]}")
    check(any("steps_per_spin" in e for e in errors), "步长非正被拦截")
    check(any("direction 非法" in e for e in errors), "非法方向被拦截")
    check(any("max_walkers" in e for e in errors), "上限非正被拦截")
    check(any("只在 base 生效没有意义" in e for e in errors), "只在 base 生效被拦截")

    undef = GameConfig(
        features=Features(walking_wild=WalkingWildConfig(enabled=True, symbol="ghost")),
        **base,
    )
    check(any("walking_wild.symbol 未定义" in e for e in undef.validate()), "符号未定义被拦截")


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
    print("[engine] RTP 回归（2 万局快速档；高波动机台 8 万局）")
    for game_id in game_ids():
        machine = get_registry().get(game_id)
        # 高波动机台的单样本方差很大，2 万局容易被尾部大奖带偏，因此加大样本
        spins = 80_000 if str(machine.config.math.volatility).startswith("high") else 20_000
        report = simulate(machine, spins=spins, bet=1.0, seed=f"regression:{game_id}")
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
    test_multiplier_wild_and_pick_bonus()
    test_new_feature_config_validation()
    test_colossal_symbols()
    test_colossal_config_validation()
    test_mystery_symbols()
    test_mystery_config_validation()
    test_walking_wild()
    test_walking_wild_config_validation()
    test_session()
    test_hot_reload()
    test_rtp_regression()
    print(f"\n[engine] 全部通过（{CHECKS} 项断言）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
