/*!
 * SlotEngine.js —— 纯前端 SLOT 引擎（零依赖，可直接静态托管）
 *
 * 与 Python 侧 `slotmcp.engine`（config / rng / reels / evaluator / features / game）
 * 语义等价：同样由一份 CONFIG 驱动，引擎内不含任何按机台 id 的分支。
 * 数据来自 `data/games.json`（由 `tools/build_static.py` 从 Python 配置导出）。
 *
 * 坐标约定：grid[reel][row]，row = 0 为顶部。
 * 赔付单位：pays[n] 为「单条线注」倍数；scatter_pays[n] 与 Hold&Win 赏金为「总注」倍数。
 */
(function (global) {
  'use strict';

  var PHASE_BASE = 'base';
  var PHASE_FREE = 'free_spins';
  var PHASE_HOLD = 'hold_win';

  // 单局硬上限：防止异常配置或极端运气导致不可收敛
  var MAX_TURNS_PER_SPIN = 300;
  var MAX_STEPS_PER_SPIN = 400;
  var MAX_CASCADES_PER_SPIN = 40;
  var MAX_FREE_SPINS_PER_PURCHASE = 200;

  // ------------------------------------------------------------------ 随机数
  function hashSeed(s) {
    var h = 0x811c9dc5;
    for (var i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return h >>> 0;
  }

  function Rng(seed) {
    if (seed === undefined || seed === null) {
      seed = (Math.random() * 4294967296) >>> 0;
    }
    this.seed = typeof seed === 'string' ? hashSeed(seed) : seed >>> 0;
    this._s = this.seed || 1;
  }

  // mulberry32：小、快、可复现
  Rng.prototype.next = function () {
    this._s = (this._s + 0x6d2b79f5) >>> 0;
    var t = this._s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  Rng.prototype.intBelow = function (n) {
    return Math.floor(this.next() * n) % n;
  };
  Rng.prototype.random = function () {
    return this.next();
  };
  Rng.prototype.shuffle = function (a) {
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(this.next() * (i + 1));
      var tmp = a[i];
      a[i] = a[j];
      a[j] = tmp;
    }
    return a;
  };

  // ------------------------------------------------------------------ 配置归一化
  function numKeys(raw) {
    var out = {};
    if (!raw) return out;
    Object.keys(raw).forEach(function (k) {
      var n = parseInt(k, 10);
      out[isNaN(n) ? k : n] = Number(raw[k]);
    });
    return out;
  }

  function normalize(cfg) {
    Object.keys(cfg.symbols || {}).forEach(function (id) {
      var s = cfg.symbols[id];
      s.pays = numKeys(s.pays);
      s.scatter_pays = numKeys(s.scatter_pays);
      s.substitutes = s.substitutes || [];
    });
    var f = cfg.features || {};
    if (f.free_spins) {
      f.free_spins.trigger_counts = numKeys(f.free_spins.trigger_counts);
      f.free_spins.retrigger_counts = numKeys(f.free_spins.retrigger_counts);
      f.free_spins.multiplier_progression = (f.free_spins.multiplier_progression || [1]).map(Number);
      f.free_spins.sticky_wild_reels = f.free_spins.sticky_wild_reels || [];
    }
    return cfg;
  }

  function waysOf(cfg) {
    return Math.pow(cfg.rows, cfg.reels);
  }

  function isWild(cfg, id) {
    var s = cfg.symbols[id];
    return !!s && s.kind === 'wild';
  }

  function paySymbols(cfg) {
    var out = {};
    Object.keys(cfg.symbols).forEach(function (id) {
      var s = cfg.symbols[id];
      if (s.kind === 'standard' || s.kind === 'wild') out[id] = s;
    });
    return out;
  }

  function countSymbol(grid, id) {
    var n = 0;
    for (var r = 0; r < grid.length; r++) {
      for (var w = 0; w < grid[r].length; w++) if (grid[r][w] === id) n++;
    }
    return n;
  }

  function countSymbols(grid, ids) {
    var wanted = {};
    ids.forEach(function (i) {
      wanted[i] = true;
    });
    var n = 0;
    for (var r = 0; r < grid.length; r++) {
      for (var w = 0; w < grid[r].length; w++) if (wanted[grid[r][w]]) n++;
    }
    return n;
  }

  function collectPositions(grid, ids) {
    var wanted = {};
    ids.forEach(function (i) {
      wanted[i] = true;
    });
    var out = [];
    for (var r = 0; r < grid.length; r++) {
      for (var w = 0; w < grid[r].length; w++) if (wanted[grid[r][w]]) out.push([r, w]);
    }
    return out;
  }

  // Pick'em：与 Python 端 resolve_pick_bonus 同构（加权轮盘 + 顺序扫描）
  function resolvePickBonus(cfg, pb, picks, rng) {
    var prizes = Object.keys(pb.prize_pool || {});
    var chosen = [];
    var total = 0;
    for (var k = 0; k < (picks | 0); k++) {
      var candidates = pb.unique ? prizes.filter(function (p) { return chosen.indexOf(p) < 0; }) : prizes.slice();
      if (!candidates.length) break;
      var remaining = 0;
      candidates.forEach(function (p) { remaining += Math.max(0, (pb.weights || {})[p] | 0); });
      if (remaining <= 0) break;
      var target = rng.random() * remaining;
      var acc = 0;
      var picked = candidates[candidates.length - 1];
      for (var i = 0; i < candidates.length; i++) {
        acc += Math.max(0, (pb.weights || {})[candidates[i]] | 0);
        if (target < acc) {
          picked = candidates[i];
          break;
        }
      }
      chosen.push(picked);
      total += Number((pb.prize_pool || {})[picked] || 0);
    }
    return { picked: chosen, total: Math.round(total * Number(pb.award_multiplier || 1.0) * 1e6) / 1e6 };
  }

  function pickBonusAward(machine, cfg, ctx, grid) {
    var pb = cfg.features.pick_bonus;
    if (!pb || !pb.enabled) return null;
    var count = 0;
    grid.forEach(function (col) {
      col.forEach(function (s) {
        if (s === pb.trigger_symbol) count++;
      });
    });
    var picks = Number((pb.trigger_counts || {})[count] || 0);
    if (picks <= 0) return null;
    var res = resolvePickBonus(cfg, pb, picks, machine.rng);
    if (res.total <= 0) return null;
    var amount = Math.round(res.total * ctx.totalBet * 1e6) / 1e6;
    return {
      picked: res.picked,
      win: {
        kind: 'pick_bonus',
        symbol: pb.trigger_symbol,
        count: res.picked.length,
        positions: [],
        baseAmount: amount,
        amount: amount,
        label: '选宝 ' + res.picked.length + ' 次：' + res.picked.join(' / ')
      }
    };
  }

  // 神秘符号揭示：与 Python 端 reveal_mystery_symbols 同构
  // reveal_all_same=true 时全屏揭示为同一符号（只消耗 1 个随机数）；
  // 否则按「轴优先、行次之」的扫描顺序逐格独立揭示。
  function revealMysterySymbols(grid, ms, rng, phase) {
    if (!ms || !ms.enabled) return null;
    var phases = ms.phases || ['base', 'free_spins'];
    if (phases.indexOf(phase) < 0) return null;
    var positions = [];
    for (var r = 0; r < grid.length; r++) {
      for (var c = 0; c < grid[r].length; c++) {
        if (grid[r][c] === ms.symbol) positions.push([r, c]);
      }
    }
    if (!positions.length) return null;
    var ids = Object.keys(ms.reveal_symbols || {}).filter(function (s) {
      return Number(ms.reveal_symbols[s]) > 0;
    });
    var total = 0;
    ids.forEach(function (s) {
      total += Number(ms.reveal_symbols[s]) || 0;
    });
    if (total <= 0) return null;

    function draw() {
      var t = rng.random() * total;
      var acc = 0;
      var picked = ids[ids.length - 1];
      for (var i = 0; i < ids.length; i++) {
        acc += Number(ms.reveal_symbols[ids[i]]) || 0;
        if (t < acc) {
          picked = ids[i];
          break;
        }
      }
      return picked;
    }

    var revealed;
    if (ms.reveal_all_same) {
      revealed = draw();
      positions.forEach(function (p) {
        grid[p[0]][p[1]] = revealed;
      });
    } else {
      var list = positions.map(function () {
        return draw();
      });
      positions.forEach(function (p, idx) {
        grid[p[0]][p[1]] = list[idx];
      });
      revealed = list.join(',');
    }
    return { type: 'mystery_reveal', symbol: revealed, count: positions.length, positions: positions };
  }

  // 巨符号投放：与 Python 端 place_colossal_symbol 同构
  // 抽样顺序：块尺寸 -> 最左轴 -> 最上排 -> 符号；块内撞到受保护符号则放弃本次投放
  function placeColossalSymbol(grid, cfg, cc, rng, phase) {
    if (!cc || !cc.enabled) return null;
    if ((cc.phases || ['base']).indexOf(phase) < 0) return null;
    var sizes = Object.keys(cc.size_weights || {}).map(Number).filter(function (s) { return s > 0; }).sort(function (a, b) { return a - b; });
    if (!sizes.length) return null;
    var total = 0;
    sizes.forEach(function (s) { total += Number(cc.size_weights[s]) || 0; });
    var target = rng.random() * total;
    var acc = 0;
    var size = sizes[sizes.length - 1];
    for (var i = 0; i < sizes.length; i++) {
      acc += Number(cc.size_weights[sizes[i]]) || 0;
      if (target < acc) { size = sizes[i]; break; }
    }
    if (size <= 1) return null;

    var reels = (cc.reels || []).filter(function (r) { return r >= 0 && r <= grid.length - size; });
    var rows = (cc.rows || []).filter(function (r) { return r >= 0 && r <= grid[0].length - size; });
    if (!reels.length || !rows.length) return null;
    var left = reels[Math.floor(rng.random() * reels.length)];
    var top = rows[Math.floor(rng.random() * rows.length)];

    var symIds = Object.keys(cc.symbols || {});
    var symTotal = 0;
    symIds.forEach(function (s) { symTotal += Number(cc.symbols[s]) || 0; });
    if (symTotal <= 0) return null;
    target = rng.random() * symTotal;
    acc = 0;
    var symbolId = symIds[symIds.length - 1];
    for (var j = 0; j < symIds.length; j++) {
      acc += Number(cc.symbols[symIds[j]]) || 0;
      if (target < acc) { symbolId = symIds[j]; break; }
    }

    var protectedSet = {};
    (cc.protected_symbols || []).forEach(function (s) { protectedSet[s] = true; });
    var positions = [];
    for (var r2 = left; r2 < left + size; r2++) {
      for (var c2 = top; c2 < top + size; c2++) {
        if (protectedSet[grid[r2][c2]]) return null;
        positions.push([r2, c2]);
      }
    }
    positions.forEach(function (p) { grid[p[0]][p[1]] = symbolId; });
    return { type: 'colossal', symbol: symbolId, size: size, reel: left, row: top, positions: positions };
  }

  // 随机 Wild 投放与 Python 端 place_random_wilds 完全同构（含 RNG 消耗顺序）
  function placeRandomWilds(grid, symbolId, count, rng, excludeReels, protectedSymbols) {
    if (count <= 0) return [];
    var protectedSet = {};
    (protectedSymbols || []).forEach(function (s) {
      protectedSet[s] = true;
    });
    protectedSet[symbolId] = true;
    var skipped = {};
    (excludeReels || []).forEach(function (r) {
      skipped[r] = true;
    });
    var candidates = [];
    for (var reel = 0; reel < grid.length; reel++) {
      if (skipped[reel]) continue;
      for (var row = 0; row < grid[reel].length; row++) {
        if (!protectedSet[grid[reel][row]]) candidates.push([reel, row]);
      }
    }
    var n = Math.min(count, candidates.length);
    if (n <= 0) return [];
    for (var i = candidates.length - 1; i > 0; i--) {
      var j = rng.intBelow(i + 1);
      var tmp = candidates[i];
      candidates[i] = candidates[j];
      candidates[j] = tmp;
    }
    var picked = candidates.slice(0, n);
    picked.forEach(function (p) {
      grid[p[0]][p[1]] = symbolId;
    });
    return picked.sort(function (a, b) {
      return a[0] - b[0] || a[1] - b[1];
    });
  }

  // Cash Collect：与 Python 端 _collect_award 同构（不含 RNG）
  function collectAward(cfg, phase, ctx, grid) {
    var col = cfg.features.collect;
    if (!col || !col.enabled) return null;
    var has = false;
    for (var r = 0; r < grid.length && !has; r++) {
      if (grid[r].indexOf(col.collector) >= 0) has = true;
    }
    if (!has) return null;
    var coins = collectPositions(grid, col.coin_symbols);
    if (!coins.length) return null;
    var multiplier = phase === PHASE_FREE ? col.free_award_multiplier : col.award_multiplier;
    var pot = 0;
    var jackpot = false;
    coins.forEach(function (p) {
      var sym = grid[p[0]][p[1]];
      pot += col.coin_values[sym] || 0;
      if (col.jackpot_symbol && sym === col.jackpot_symbol) jackpot = true;
    });
    if (jackpot) pot += col.jackpot_value || 0;
    if (pot <= 0) return null;
    return {
      kind: 'collect',
      symbol: col.collector,
      count: coins.length,
      positions: coins,
      baseAmount: Math.round(pot * ctx.totalBet * 1e6) / 1e6,
      amount: Math.round(pot * multiplier * ctx.totalBet * 1e6) / 1e6,
      label: '收集 ' + coins.length + ' 枚金币 ×' + multiplier
    };
  }

  // ------------------------------------------------------------------ 条带
  function buildStrips(cfg, name) {
    var rs = cfg.reel_sets[name];
    var rows = cfg.rows;
    // 优先使用 Python 侧导出的「已展开 + 已洗牌」虚拟条带：
    // 只要洗牌排布不同，Scatter / 赏金符号的聚集程度就会变化，触发频率与 RTP 随之偏移，
    // 因此静态站必须与 Python 引擎使用完全相同的条带。
    if (rs.expanded && rs.expanded.length === rs.strips.length) {
      return rs.expanded.map(function (s) {
        return s.slice();
      });
    }
    var out = [];
    for (var i = 0; i < rs.strips.length; i++) {
      var strip = rs.strips[i];
      var virtual = strip.slice();
      if (rs.weights && rs.weights[i]) {
        var wmap = rs.weights[i];
        virtual = [];
        for (var k = 0; k < strip.length; k++) {
          // 与 Python 端一致：权重 <= 0 表示该符号不在该轴出现
          var n = parseInt(wmap[strip[k]] || 1, 10);
          if (!(n > 0)) continue;
          for (var m = 0; m < n; m++) virtual.push(strip[k]);
        }
        while (virtual.length < rows) virtual = virtual.concat(virtual);
        // 权重展开会成簇，做确定性洗牌：同种子永远得到同一条带，RTP 可复算
        new Rng(name + '#' + i).shuffle(virtual);
      }
      out.push(virtual);
    }
    return out;
  }

  function rollGrid(strips, rows, rng) {
    var grid = [];
    var stops = [];
    for (var i = 0; i < strips.length; i++) {
      var len = strips[i].length;
      var stop = rng.intBelow(len);
      stops.push(stop);
      var col = [];
      for (var r = 0; r < rows; r++) col.push(strips[i][(stop + r) % len]);
      grid.push(col);
    }
    return { grid: grid, stops: stops };
  }

  function cascadeCollapse(grid, strips, removePositions, rng) {
    var removed = {};
    removePositions.forEach(function (p) {
      if (!removed[p[0]]) removed[p[0]] = {};
      removed[p[0]][p[1]] = true;
    });
    var out = [];
    for (var i = 0; i < grid.length; i++) {
      var col = grid[i];
      var survivors = [];
      for (var r = 0; r < col.length; r++) {
        if (!(removed[i] && removed[i][r])) survivors.push(col[r]);
      }
      var missing = col.length - survivors.length;
      if (missing <= 0) {
        out.push(col.slice());
        continue;
      }
      var padding = [];
      for (var m = 0; m < missing; m++) {
        padding.push(strips[i][rng.intBelow(strips[i].length)]);
      }
      out.push(padding.concat(survivors));
    }
    return out;
  }

  // ------------------------------------------------------------------ 中奖判定
  function bestSymbolForCount(cfg, count) {
    var best = null;
    var bestPay = -1;
    var ps = paySymbols(cfg);
    Object.keys(ps).forEach(function (id) {
      var pay = ps[id].pays[count];
      if (pay && pay > bestPay) {
        bestPay = pay;
        best = id;
      }
    });
    return best;
  }

  // 倍率 Wild：与 Python 端 _wild_multiplier 同构（未启用时退回符号自带倍率取最大）
  function wildMultiplier(cfg, seq, mode) {
    var mw = cfg.features.multiplier_wild;
    var applyTo = (mw && mw.apply_to) || ['line', 'ways'];
    var enabled = !!(mw && mw.enabled && applyTo.indexOf(mode || 'line') >= 0);
    var values = [];
    for (var i = 0; i < seq.length; i++) {
      var s = cfg.symbols[seq[i]];
      if (!s || s.kind !== 'wild') continue;
      var v = enabled ? Number((mw.symbols || {})[seq[i]] || 1.0) : Number(s.multiplier || 1.0);
      if (v > 1.0) values.push(v);
    }
    if (!values.length) return 1.0;
    if (!enabled) return Math.max.apply(null, values);
    var combine = mw.combine || 'max';
    if (combine === 'sum') {
      return values.reduce(function (acc, v) { return acc + (v - 1.0); }, 1.0);
    }
    if (combine === 'product') {
      return values.reduce(function (acc, v) { return acc * Math.max(1.0, v); }, 1.0);
    }
    return Math.max.apply(null, values);
  }

  function scanLine(cfg, cells, ps) {
    if (!cells.length) return { symbol: null, count: 0, seq: [] };
    var target = null;
    for (var i = 0; i < cells.length; i++) {
      if (ps[cells[i]] && !isWild(cfg, cells[i])) {
        target = cells[i];
        break;
      }
    }
    if (target === null) {
      var allPay = cells.every(function (c) {
        return !!ps[c];
      });
      if (!allPay) return { symbol: null, count: 0, seq: [] };
      return { symbol: bestSymbolForCount(cfg, cells.length), count: cells.length, seq: cells.slice() };
    }
    var count = 0;
    var seq = [];
    for (var j = 0; j < cells.length; j++) {
      if (cells[j] === target || (ps[cells[j]] && isWild(cfg, cells[j]))) {
        count++;
        seq.push(cells[j]);
      } else {
        break;
      }
    }
    if (count === 0) return { symbol: null, count: 0, seq: [] };
    return { symbol: target, count: count, seq: seq };
  }

  function evaluateLines(cfg, grid, lineBet, lines, activeLines, baseMultiplier) {
    var events = [];
    var ps = paySymbols(cfg);
    var limit = activeLines > 0 ? Math.min(activeLines, lines.length) : lines.length;
    for (var li = 0; li < limit; li++) {
      var line = lines[li];
      var cells = [];
      for (var r = 0; r < line.length; r++) cells.push(grid[r][line[r]]);
      var scan = scanLine(cfg, cells, ps);
      if (!scan.symbol || scan.count < 2) continue;
      var sym = cfg.symbols[scan.symbol];
      var pay = sym.pays[scan.count];
      if (!pay) continue;
      var mult = wildMultiplier(cfg, scan.seq, 'line') * Math.max(1.0, baseMultiplier || 1.0);
      var positions = [];
      for (var p = 0; p < scan.count; p++) positions.push([p, line[p]]);
      events.push({
        kind: 'line',
        symbol: scan.symbol,
        count: scan.count,
        positions: positions,
        lineIndex: li,
        baseAmount: pay * lineBet,
        multiplier: mult,
        amount: pay * lineBet * mult,
        label: sym.name + ' x' + scan.count
      });
    }
    return events;
  }

  function evaluateWays(cfg, grid, betPerWay, baseMultiplier) {
    var events = [];
    var ps = paySymbols(cfg);
    Object.keys(ps).forEach(function (id) {
      if (ps[id].kind !== 'standard' || !ps[id].pays || !Object.keys(ps[id].pays).length) return;
      var ways = 1;
      var hits = [];
      var matched = 0;
      for (var r = 0; r < grid.length; r++) {
        var pos = [];
        for (var row = 0; row < grid[r].length; row++) {
          if (grid[r][row] === id || isWild(cfg, grid[r][row])) pos.push([r, row]);
        }
        if (!pos.length) break;
        ways *= pos.length;
        hits = hits.concat(pos);
        matched++;
      }
      if (matched < 2) return;
      var pay = cfg.symbols[id].pays[matched];
      if (!pay) return;
      var wildSeq = hits
        .filter(function (p) { return isWild(cfg, grid[p[0]][p[1]]); })
        .map(function (p) { return grid[p[0]][p[1]]; });
      var mult = wildMultiplier(cfg, wildSeq, 'ways') * Math.max(1.0, baseMultiplier || 1.0);
      events.push({
        kind: 'ways',
        symbol: id,
        count: matched,
        positions: hits,
        lineIndex: -1,
        baseAmount: pay * betPerWay,
        multiplier: mult,
        amount: pay * betPerWay * mult,
        label: cfg.symbols[id].name + ' ' + matched + '连 x' + ways
      });
    });
    return events;
  }

  function evaluateScatters(cfg, grid, totalBet, baseMultiplier) {
    var events = [];
    Object.keys(cfg.symbols).forEach(function (id) {
      var sym = cfg.symbols[id];
      if (!sym.scatter_pays || !Object.keys(sym.scatter_pays).length) return;
      var positions = collectPositions(grid, [id]);
      if (!positions.length) return;
      var pay = sym.scatter_pays[positions.length];
      if (!pay) return;
      var mult = Math.max(1.0, baseMultiplier || 1.0);
      events.push({
        kind: 'scatter',
        symbol: id,
        count: positions.length,
        positions: positions,
        lineIndex: -1,
        baseAmount: pay * totalBet,
        multiplier: mult,
        amount: pay * totalBet * mult,
        label: sym.name + ' x' + positions.length
      });
    });
    return events;
  }

  function evaluateGrid(cfg, grid, ctx, baseMultiplier) {
    var events = [];
    if (cfg.pay_mode === 'ways') {
      events = events.concat(evaluateWays(cfg, grid, ctx.totalBet / Math.max(1, waysOf(cfg)), baseMultiplier));
    } else {
      events = events.concat(evaluateLines(cfg, grid, ctx.lineBet, ctx.lines, ctx.activeLines, baseMultiplier));
    }
    return events.concat(evaluateScatters(cfg, grid, ctx.totalBet, baseMultiplier));
  }

  // ------------------------------------------------------------------ 状态
  function GameState() {
    this.phase = PHASE_BASE;
    this.freeSpinsLeft = 0;
    this.freeSpinsPlayed = 0;
    this.freeSpinsTotal = 0;
    this.purchaseFreeSpins = 0;
    this.fsMultiplier = 1.0;
    this.cascadeMultiplier = 1.0;
    this.stickyKeys = {};
    this.respinsLeft = 0;
    this.holdGrid = null;
    this.holdLockedKeys = [];
    this.holdReturnPhase = PHASE_BASE;
    this.holdInitialAwarded = false;
    this.holdPot = 0.0;
    this.totalWin = 0.0;
    this.spinCount = 0;
  }

  GameState.prototype.clone = function () {
    var s = new GameState();
    Object.keys(this).forEach(
      function (k) {
        var v = this[k];
        s[k] = v && typeof v === 'object' && !Array.isArray(v) ? Object.assign({}, v) : Array.isArray(v) ? v.slice() : v;
      }.bind(this)
    );
    return s;
  };

  // ------------------------------------------------------------------ 机台
  function SlotMachine(cfg, seed) {
    this.cfg = normalize(cfg);
    this.rng = new Rng(seed);
    this.strips = {};
    var self = this;
    Object.keys(this.cfg.reel_sets).forEach(function (name) {
      self.strips[name] = buildStrips(self.cfg, name);
    });
  }

  SlotMachine.prototype.buildContext = function (totalBet, activeLines) {
    var cfg = this.cfg;
    if (cfg.pay_mode === 'ways') {
      return { totalBet: totalBet, lineBet: 0, activeLines: 0, lines: [] };
    }
    var lines = cfg.paylines.lines;
    var n = activeLines > 0 ? Math.min(activeLines, lines.length) : lines.length;
    return { totalBet: totalBet, lineBet: totalBet / n, activeLines: n, lines: lines };
  };

  SlotMachine.prototype.currentStrips = function (st) {
    var name = this.cfg.base_reel_set;
    if (st.phase === PHASE_FREE) {
      var fs = this.cfg.features.free_spins;
      if (fs && fs.reel_set) name = fs.reel_set;
    }
    return this.strips[name];
  };

  SlotMachine.prototype.roll = function (st, strips) {
    var res = rollGrid(strips, this.cfg.rows, this.rng);
    var grid = res.grid;
    Object.keys(st.stickyKeys || {}).forEach(function (key) {
      var parts = key.split(',');
      grid[parseInt(parts[0], 10)][parseInt(parts[1], 10)] = st.stickyKeys[key];
    });
    return { grid: grid, stops: res.stops };
  };

  SlotMachine.prototype.spin = function (opts) {
    opts = opts || {};
    var ctx = this.buildContext(opts.totalBet, opts.activeLines || 0);
    var st = opts.state ? opts.state.clone() : new GameState();
    st.totalWin = 0;
    st.spinCount += 1;
    st.purchaseFreeSpins = 0;

    var steps = [];
    var events = [];
    var turns = 0;
    while (turns < MAX_TURNS_PER_SPIN && steps.length < MAX_STEPS_PER_SPIN) {
      turns++;
      var produced = st.phase === PHASE_HOLD ? this._runHoldWin(st, ctx) : this._runSpin(st, ctx);
      if (!produced || !produced.length) break;
      steps = steps.concat(produced);
      this._applyTriggers(st, produced, events);
      if (st.phase === PHASE_BASE) break;
    }

    var totalWin = 0;
    steps.forEach(function (s) {
      totalWin += s.stepWin;
    });
    return {
      gameId: this.cfg.id,
      totalBet: ctx.totalBet,
      lineBet: ctx.lineBet,
      activeLines: ctx.activeLines,
      steps: steps,
      totalWin: Math.round(totalWin * 1e6) / 1e6,
      state: st,
      events: events,
      seed: this.rng.seed
    };
  };

  SlotMachine.prototype._runSpin = function (st, ctx) {
    var cfg = this.cfg;
    var steps = [];
    var stepEvents = [];

    if (st.phase === PHASE_FREE) {
      var fs = cfg.features.free_spins;
      st.freeSpinsLeft -= 1;
      st.freeSpinsPlayed += 1;
      if (cfg.features.cascade && cfg.features.cascade.reset_each_free_spin) st.cascadeMultiplier = 1.0;
      if (fs) {
        var prog = fs.multiplier_progression || [1.0];
        st.fsMultiplier = prog[Math.min(st.freeSpinsPlayed - 1, prog.length - 1)];
      }
    } else {
      st.phase = PHASE_BASE;
      st.cascadeMultiplier = 1.0;
      st.fsMultiplier = 1.0;
    }
    var strips = this.currentStrips(st);
    var rolled = this.roll(st, strips);
    var grid = rolled.grid;
    var stops = rolled.stops;

    // 巨符号：先于其它网格改写算子投放，保证后续判定看到的是最终网格
    var cs = cfg.features.colossal;
    if (cs && cs.enabled) {
      var block = placeColossalSymbol(grid, cfg, cs, this.rng, st.phase);
      if (block) stepEvents.push(block);
    }

    // 神秘符号揭示：顺序与 Python 一致（巨符号之后、随机 Wild 之前）
    var ms = cfg.features.mystery;
    if (ms && ms.enabled) {
      var revealed = revealMysterySymbols(grid, ms, this.rng, st.phase);
      if (revealed) stepEvents.push(revealed);
    }

    // 随机 Wild 投放：顺序与 Python 一致（替代计算前、触发判定前）
    var rw = cfg.features.random_wild;
    if (rw && rw.enabled && (rw.phases || ['base']).indexOf(st.phase) >= 0) {
      var keys = Object.keys(rw.counts).map(Number).sort(function (a, b) {
        return a - b;
      });
      var total = 0;
      keys.forEach(function (k) {
        total += rw.counts[k];
      });
      if (total > 0) {
        var target = this.rng.random() * total;
        var chosen = keys[keys.length - 1];
        var acc = 0;
        for (var ki = 0; ki < keys.length; ki++) {
          acc += rw.counts[keys[ki]];
          if (target < acc) {
            chosen = keys[ki];
            break;
          }
        }
        var placed = placeRandomWilds(grid, rw.symbol, chosen, this.rng, rw.exclude_reels, rw.protected_symbols);
        if (placed.length) {
          stepEvents.push({
            type: 'random_wild',
            symbol: rw.symbol,
            count: placed.length,
            positions: placed
          });
        }
      }
    }

    var ew = cfg.features.expanding_wild;
    if (ew && st.phase === PHASE_BASE) {
      var targets = (ew.reels && ew.reels.length ? ew.reels : Object.keys(grid).map(Number)).map(Number);
      var expanded = [];
      targets.forEach(function (reelIdx) {
        var col = grid[reelIdx];
        if (!col || col.indexOf(ew.symbol) < 0) return;
        for (var row = 0; row < col.length; row++) {
          col[row] = ew.symbol;
          expanded.push([reelIdx, row]);
        }
      });
      if (expanded.length) {
        expanded.forEach(function (p) {
          st.stickyKeys[p[0] + ',' + p[1]] = ew.symbol;
        });
        st.respinsLeft = Math.max(0, ew.respins);
        stepEvents.push({
          type: 'expanding_wild',
          symbol: ew.symbol,
          reels: Array.from(new Set(expanded.map(function (p) { return p[0]; }))).sort(),
          respins: st.respinsLeft,
          positions: expanded
        });
      }
    }

    if (st.phase === PHASE_FREE) {
      var fsCfg = cfg.features.free_spins;
      if (fsCfg && fsCfg.sticky_wild_reels && fsCfg.sticky_wild_reels.length) {
        var wildIds = Object.keys(cfg.symbols).filter(function (id) {
          return cfg.symbols[id].kind === 'wild';
        });
        fsCfg.sticky_wild_reels.forEach(function (reelIdx) {
          grid[reelIdx].forEach(function (sym, row) {
            if (wildIds.indexOf(sym) >= 0) st.stickyKeys[reelIdx + ',' + row] = sym;
          });
        });
      }
    }

    this._settle(st, ctx, grid, stops, steps, stepEvents);

    while (st.respinsLeft > 0 && steps.length < MAX_STEPS_PER_SPIN) {
      st.respinsLeft -= 1;
      var rr = this.roll(st, strips);
      this._settle(st, ctx, rr.grid, rr.stops, steps, [{ type: 'respin', remaining: st.respinsLeft }]);
    }

    // 锁轴 Wild 只在本次特性内有效，重转结束后必须解锁（否则会跨局累积）
    if (st.phase === PHASE_BASE && st.respinsLeft <= 0) st.stickyKeys = {};

    if (st.phase === PHASE_FREE) {
      steps.forEach(function (s) {
        s.freeSpinRemaining = st.freeSpinsLeft;
      });
    }
    return steps;
  };

  SlotMachine.prototype._settle = function (st, ctx, grid, stops, steps, extraEvents) {
    var cfg = this.cfg;
    var strips = this.currentStrips(st);
    var cascade = cfg.features.cascade;
    var guard = 0;
    while (true) {
      var multiplier = st.fsMultiplier * st.cascadeMultiplier;
      var wins = evaluateGrid(cfg, grid, ctx, multiplier);
      var events = guard === 0 ? (extraEvents || []).slice() : [];
      // Cash Collect / Pick'em 只对「新鲜网格」结算：级联派生网格会重复派发
      if (guard === 0) {
        var award = collectAward(cfg, st.phase, ctx, grid);
        if (award) {
          wins.push(award);
          events.push({
            type: 'collect',
            collector: cfg.features.collect.collector,
            coins: award.count,
            amount: award.amount
          });
        }
        var pick = pickBonusAward(this, cfg, ctx, grid);
        if (pick) {
          wins.push(pick.win);
          events.push({ type: 'pick_bonus', picks: pick.picked, award: pick.win.amount });
        }
      }
      var stepWin = 0;
      wins.forEach(function (w) {
        stepWin += w.amount;
      });
      stepWin = Math.round(stepWin * 1e6) / 1e6;
      steps.push({
        index: steps.length,
        phase: st.phase,
        grid: grid.map(function (c) { return c.slice(); }),
        stops: stops.slice(),
        wins: wins,
        stepWin: stepWin,
        multiplier: multiplier,
        freeSpinRemaining: st.freeSpinsLeft,
        isFresh: guard === 0,
        events: events
      });

      if (!cascade || !cascade.enabled || stepWin <= 0) break;
      var posMap = {};
      wins.forEach(function (w) {
        if (w.kind !== 'line' && w.kind !== 'ways') return;
        w.positions.forEach(function (p) {
          posMap[p[0] + ',' + p[1]] = p;
        });
      });
      var positions = Object.keys(posMap).map(function (k) {
        return posMap[k];
      });
      if (!positions.length) break;
      guard++;
      if (guard >= MAX_CASCADES_PER_SPIN) break;
      st.cascadeMultiplier = Math.min(cascade.multiplier_cap, st.cascadeMultiplier + cascade.multiplier_step);
      grid = cascadeCollapse(grid, strips, positions, this.rng);
      stops = grid.map(function () { return -1; });
    }
  };

  SlotMachine.prototype._applyTriggers = function (st, steps, events) {
    var cfg = this.cfg;

    if (st.phase === PHASE_FREE) {
      this._maybeRetrigger(st, steps.filter(function (s) { return s.phase === PHASE_FREE; }), events);
      if (st.freeSpinsLeft <= 0) this._leaveFreeSpins(st, events);
      return;
    }
    if (st.phase === PHASE_HOLD) return;

    var fs = cfg.features.free_spins;
    var hw = cfg.features.hold_win;
    // 只有「本轮新鲜网格」参与触发判定：级联/重转派生网格会让触发频率失控
    var fresh = steps.filter(function (s) { return s.phase === PHASE_BASE && s.isFresh; });
    if (!fresh.length) return;

    if (fs) {
      var bestCount = 0;
      fresh.forEach(function (s) {
        var c = countSymbol(s.grid, fs.trigger_symbol);
        if (c > bestCount) bestCount = c;
      });
      var awarded = 0;
      Object.keys(fs.trigger_counts)
        .map(Number)
        .sort(function (a, b) { return b - a; })
        .forEach(function (tc) {
          if (!awarded && bestCount >= tc) awarded = fs.trigger_counts[tc];
        });
      if (awarded) {
        var granted = Math.max(0, Math.min(awarded, MAX_FREE_SPINS_PER_PURCHASE - st.purchaseFreeSpins));
        if (granted === 0) {
          events.push({ type: 'free_spins_cap_reached', requested: awarded, count: bestCount });
          return;
        }
        st.phase = PHASE_FREE;
        st.freeSpinsLeft += granted;
        st.freeSpinsTotal += granted;
        st.purchaseFreeSpins += granted;
        st.stickyKeys = {};
        events.push({ type: 'free_spins_trigger', symbol: fs.trigger_symbol, count: bestCount, spins: granted });
        return;
      }
    }

    if (hw) {
      var candidates = [hw.trigger_symbol].concat(hw.prize_symbols || [], hw.jackpot_symbols || []);
      var best = 0;
      var sourceGrid = fresh[0].grid;
      fresh.forEach(function (s) {
        var c = countSymbols(s.grid, candidates);
        if (c > best) {
          best = c;
          sourceGrid = s.grid;
        }
      });
      if (best >= hw.trigger_count) this._enterHoldWin(st, sourceGrid, events);
    }
  };

  SlotMachine.prototype._maybeRetrigger = function (st, steps, events) {
    var fs = this.cfg.features.free_spins;
    if (!fs || !fs.retrigger_counts || !Object.keys(fs.retrigger_counts).length) return;
    for (var i = 0; i < steps.length; i++) {
      if (!steps[i].isFresh) continue;
      var cnt = countSymbol(steps[i].grid, fs.trigger_symbol);
      var extra = fs.retrigger_counts[cnt];
      if (!extra) return;
      var granted = Math.max(0, Math.min(extra, MAX_FREE_SPINS_PER_PURCHASE - st.purchaseFreeSpins));
      if (granted === 0) {
        events.push({ type: 'free_spins_cap_reached', requested: extra, count: cnt });
        return;
      }
      st.freeSpinsLeft += granted;
      st.freeSpinsTotal += granted;
      st.purchaseFreeSpins += granted;
      events.push({ type: 'free_spins_retrigger', count: cnt, spins: granted });
      return;
    }
  };

  SlotMachine.prototype._leaveFreeSpins = function (st, events) {
    st.phase = PHASE_BASE;
    st.stickyKeys = {};
    st.fsMultiplier = 1.0;
    st.cascadeMultiplier = 1.0;
    events.push({ type: 'free_spins_end', played: st.freeSpinsPlayed, remaining: 0 });
    st.freeSpinsPlayed = 0;
  };

  SlotMachine.prototype._enterHoldWin = function (st, grid, events) {
    var hw = this.cfg.features.hold_win;
    if (!hw) return;
    var candidates = [hw.trigger_symbol].concat(hw.prize_symbols || [], hw.jackpot_symbols || []);
    var locked = collectPositions(grid, candidates);
    st.holdReturnPhase = st.phase === PHASE_FREE ? PHASE_FREE : PHASE_BASE;
    st.phase = PHASE_HOLD;
    st.holdGrid = grid.map(function (c) { return c.slice(); });
    st.holdLockedKeys = locked.map(function (p) { return p[0] + ',' + p[1]; });
    st.holdPot = 0.0;
    st.holdInitialAwarded = false;
    st.respinsLeft = hw.respins;
    events.push({
      type: 'hold_win_trigger',
      locked: locked.length,
      respins: hw.respins,
      positions: locked
    });
  };

  SlotMachine.prototype._runHoldWin = function (st, ctx) {
    var hw = this.cfg.features.hold_win;
    if (!hw || !st.holdGrid) {
      st.phase = PHASE_BASE;
      return [];
    }
    var grid = st.holdGrid.map(function (c) { return c.slice(); });
    var self = this;
    var steps = [];
    var locked = st.holdLockedKeys.map(function (k) {
      var p = k.split(',');
      return [parseInt(p[0], 10), parseInt(p[1], 10)];
    });
    var pool = (hw.prize_symbols && hw.prize_symbols.length ? hw.prize_symbols : [hw.trigger_symbol]).slice();
    var fillers = (hw.filler_symbols && hw.filler_symbols.length
      ? hw.filler_symbols
      : Object.keys(this.cfg.symbols).filter(function (id) { return self.cfg.symbols[id].kind === 'standard'; })
    ).slice();
    if (!fillers.length) fillers = [pool[0]];

    var lockedAtStart = locked.slice();
    var guard = 0;
    var guardLimit = Math.min(MAX_STEPS_PER_SPIN, 120);
    var prizeNames = {};
    [hw.trigger_symbol].concat(hw.prize_symbols || [], hw.jackpot_symbols || []).forEach(function (s) {
      prizeNames[s] = true;
    });

    while (guard < guardLimit) {
      guard++;
      var lockedSet = {};
      locked.forEach(function (p) {
        lockedSet[p[0] + ',' + p[1]] = true;
      });
      for (var reelIdx = 0; reelIdx < grid.length; reelIdx++) {
        for (var row = 0; row < grid[reelIdx].length; row++) {
          if (lockedSet[reelIdx + ',' + row]) continue;
          if (this.rng.random() < hw.hit_probability) {
            grid[reelIdx][row] = pool[this.rng.intBelow(pool.length)];
          } else {
            grid[reelIdx][row] = fillers[this.rng.intBelow(fillers.length)];
          }
        }
      }

      var newly = [];
      var found = collectPositions(grid, Object.keys(prizeNames)).sort(function (a, b) {
        return a[0] - b[0] || a[1] - b[1];
      });
      found.forEach(function (pos) {
        if (lockedSet[pos[0] + ',' + pos[1]]) return;
        newly.push(pos);
        lockedSet[pos[0] + ',' + pos[1]] = true;
        var sym = grid[pos[0]][pos[1]];
        st.holdPot += hw.prizes[sym] || hw.jackpots[sym] || 0.0;
      });

      locked = Object.keys(lockedSet).map(function (k) {
        var p = k.split(',');
        return [parseInt(p[0], 10), parseInt(p[1], 10)];
      });
      st.holdLockedKeys = locked.map(function (p) { return p[0] + ',' + p[1]; });
      st.holdGrid = grid.map(function (c) { return c.slice(); });
      st.respinsLeft -= 1;

      var wins = [];
      var stepWin = 0.0;
      var initial = [];
      if (guard === 1 && !st.holdInitialAwarded) {
        initial = lockedAtStart;
        st.holdInitialAwarded = true;
        initial.forEach(function (pos) {
          var sym = grid[pos[0]][pos[1]];
          st.holdPot += hw.prizes[sym] || hw.jackpots[sym] || 0.0;
        });
      }
      initial.concat(newly).forEach(function (pos) {
        var sym = grid[pos[0]][pos[1]];
        var isJackpot = (hw.jackpot_symbols || []).indexOf(sym) >= 0;
        var value = (isJackpot ? hw.jackpots : hw.prizes)[sym] || 0.0;
        if (!self.cfg.symbols[sym]) return;
        var amount = value * ctx.totalBet;
        wins.push({
          kind: isJackpot ? 'jackpot' : 'hold_win',
          symbol: sym,
          count: 1,
          positions: [pos],
          lineIndex: -1,
          baseAmount: amount,
          multiplier: 1.0,
          amount: amount,
          label: self.cfg.symbols[sym].name
        });
        stepWin += amount;
      });

      var events = [
        { type: 'hold_win_respin', new_locked: newly.length, remaining: Math.max(0, st.respinsLeft), pot: Math.round(st.holdPot * 1e4) / 1e4 }
      ];
      if (newly.length) st.respinsLeft = hw.respins;

      steps.push({
        index: steps.length,
        phase: PHASE_HOLD,
        grid: grid.map(function (c) { return c.slice(); }),
        stops: grid.map(function () { return -1; }),
        wins: wins,
        stepWin: Math.round(stepWin * 1e6) / 1e6,
        multiplier: 1.0,
        freeSpinRemaining: st.freeSpinsLeft,
        isFresh: false,
        events: events
      });

      var totalCells = grid.length * grid[0].length;
      if (st.respinsLeft <= 0 || locked.length >= totalCells) break;
    }

    var totalCells = grid.length * grid[0].length;
    if (hw.full_grid_bonus > 0 && locked.length >= totalCells && steps.length) {
      var bonus = hw.full_grid_bonus * ctx.totalBet;
      var last = steps[steps.length - 1];
      last.wins.push({
        kind: 'jackpot',
        symbol: 'full_grid',
        count: totalCells,
        positions: [],
        lineIndex: -1,
        baseAmount: bonus,
        multiplier: 1.0,
        amount: bonus,
        label: '全屏大奖'
      });
      last.stepWin = Math.round((last.stepWin + bonus) * 1e6) / 1e6;
      last.events.push({ type: 'full_grid_bonus', amount: Math.round(bonus * 1e4) / 1e4 });
    }

    st.phase = st.holdReturnPhase || PHASE_BASE;
    st.holdReturnPhase = PHASE_BASE;
    st.holdGrid = null;
    st.holdLockedKeys = [];
    st.holdPot = 0.0;
    st.respinsLeft = 0;
    return steps;
  };

  // ------------------------------------------------------------------ 元信息
  function gameInfo(cfg) {
    var features = [];
    var f = cfg.features || {};
    if (f.free_spins) features.push('free_spins');
    if (f.hold_win) features.push('hold_win');
    if (f.cascade && f.cascade.enabled) features.push('cascade');
    if (f.expanding_wild) features.push('expanding_wild');
    if (f.gamble && f.gamble.enabled) features.push('gamble');
    return {
      id: cfg.id,
      name: cfg.name,
      description: cfg.description,
      reels: cfg.reels,
      rows: cfg.rows,
      pay_mode: cfg.pay_mode,
      lines: cfg.pay_mode === 'ways' ? waysOf(cfg) : cfg.paylines.lines.length,
      target_rtp: cfg.math.target_rtp,
      volatility: cfg.math.volatility,
      max_win_multiplier: cfg.math.max_win_multiplier,
      features: features,
      bet_steps: cfg.bet.steps,
      theme: cfg.theme
    };
  }

  var api = {
    PHASE_BASE: PHASE_BASE,
    PHASE_FREE: PHASE_FREE,
    PHASE_HOLD: PHASE_HOLD,
    Rng: Rng,
    GameState: GameState,
    SlotMachine: SlotMachine,
    normalize: normalize,
    gameInfo: gameInfo,
    waysOf: waysOf,
    countSymbol: countSymbol
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.SlotEngine = api;
})(typeof window !== 'undefined' ? window : globalThis);
