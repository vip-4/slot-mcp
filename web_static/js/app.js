/*!
 * app.js —— 静态站交互层（零依赖）
 *
 * 职责：加载 data/games.json → 用 SlotEngine 跑一局 → 按 steps 顺序播放动画。
 * 不发送任何网络请求、不依赖后端；积分保存在浏览器 localStorage。
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'slot-static-credits';

  // 站点可能部署在子目录，也可能从 games/ 子页进入：按脚本自身位置解析站点根
  function siteRoot() {
    const self = document.currentScript || document.querySelector('script[src*="app.js"]');
    try {
      return new URL('../', (self && self.src) || location.href).href;
    } catch (e) {
      return './';
    }
  }
  const DATA_URL = new URL('data/games.json', siteRoot()).href;
  const START_CREDITS = 1000;

  const el = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const reduceMotion =
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let DATA = null;
  let machine = null;
  let cfg = null;
  let state = null;
  let credits = START_CREDITS;
  let autoLeft = 0;
  let busy = false;
  let pendingGamble = 0;
  let gambleSteps = 0;

  // ------------------------------------------------------------------ 启动
  async function init() {
    const res = await fetch(DATA_URL, { cache: 'no-cache' });
    DATA = await res.json();
    credits = Number(localStorage.getItem(STORAGE_KEY) || START_CREDITS);

    const qs = new URLSearchParams(location.search).get('game');
    const initial = qs || document.body.dataset.game || DATA.games[0].id;
    loadGame(initial);
    bindEvents();
    updateHud();
  }

  function loadGame(gameId) {
    const found = DATA.games.find((g) => g.id === gameId) || DATA.games[0];
    cfg = found;
    machine = new SlotEngine.SlotMachine(JSON.parse(JSON.stringify(found)));
    state = new SlotEngine.GameState();
    autoLeft = 0;
    pendingGamble = 0;
    gambleSteps = 0;
    document.body.dataset.game = cfg.id;
    buildBetOptions();
    buildGrid();
    renderPaytable();
    el('feature-badge').textContent = '基础旋转';
    el('win-line').textContent = `${cfg.name}：${cfg.reels}×${cfg.rows}，${payModeText(cfg)}。`;
    el('gamble-panel').hidden = true;
    if (el('play-game-name')) el('play-game-name').textContent = cfg.name;
    updateHud();
  }

  function payModeText(c) {
    if (c.pay_mode === 'ways') return `${Math.pow(c.rows, c.reels)} Ways`;
    return `${c.paylines.lines.length} 条赔付线`;
  }

  // ------------------------------------------------------------------ 渲染
  function buildBetOptions() {
    const sel = el('bet-select');
    sel.innerHTML = '';
    cfg.bet.steps.forEach((v, i) => {
      const opt = document.createElement('option');
      opt.value = String(i);
      opt.textContent = v.toFixed(2);
      if (i === (cfg.bet.default_index || 0)) opt.selected = true;
      sel.appendChild(opt);
    });
  }

  function currentBet() {
    const i = Number(el('bet-select').value || cfg.bet.default_index || 0);
    return cfg.bet.steps[i];
  }

  function buildGrid() {
    const wrap = el('reels');
    wrap.innerHTML = '';
    wrap.style.setProperty('--reels', cfg.reels);
    wrap.style.setProperty('--rows', cfg.rows);
    for (let r = 0; r < cfg.reels; r++) {
      const col = document.createElement('div');
      col.className = 'reel-col';
      for (let row = 0; row < cfg.rows; row++) {
        const cell = document.createElement('div');
        cell.className = 'cell';
        cell.dataset.reel = String(r);
        cell.dataset.row = String(row);
        col.appendChild(cell);
      }
      wrap.appendChild(col);
    }
    paintGrid(firstGrid());
  }

  function firstGrid() {
    const stripsKey = cfg.base_reel_set;
    const grid = [];
    for (let r = 0; r < cfg.reels; r++) {
      const col = [];
      for (let row = 0; row < cfg.rows; row++) col.push('wild');
      grid.push(col);
    }
    // 首屏用条带里的第一个符号占位，避免空白
    const strips = machine.strips[stripsKey];
    for (let r = 0; r < cfg.reels; r++) {
      for (let row = 0; row < cfg.rows; row++) grid[r][row] = strips[r][row % strips[r].length];
    }
    return grid;
  }

  function paintGrid(grid, winPositions, holdCandidates) {
    const wrap = el('reels');
    const winset = new Set((winPositions || []).map((p) => `${p[0]},${p[1]}`));
    const holdset = new Set((holdCandidates || []).map((p) => `${p[0]},${p[1]}`));
    wrap.querySelectorAll('.cell').forEach((cell) => {
      const key = `${cell.dataset.reel},${cell.dataset.row}`;
      const id = grid[Number(cell.dataset.reel)][Number(cell.dataset.row)];
      const sym = cfg.symbols[id] || { glyph: '?', name: id, color: '#888' };
      cell.textContent = sym.glyph;
      cell.setAttribute('role', 'img');
      cell.setAttribute('aria-label', sym.name);
      cell.style.setProperty('--sym', sym.color || '#8ea0ff');
      cell.classList.toggle('win', winset.has(key));
      cell.classList.toggle('hold', holdset.has(key));
    });
  }

  function renderPaytable() {
    const box = el('paytable');
    if (!box) return;
    const maxLen = cfg.pay_mode === 'ways' ? cfg.reels : Math.min(5, cfg.reels);
    const heads = [];
    for (let n = 2; n <= maxLen; n++) heads.push(n);
    let html =
      '<table class="paytable"><caption>赔付表（单位：线注 / 通路注倍数）</caption><thead><tr><th scope="col">符号</th>';
    heads.forEach((n) => {
      html += `<th scope="col">${n} 连</th>`;
    });
    html += '</tr></thead><tbody>';
    Object.keys(cfg.symbols).forEach((id) => {
      const s = cfg.symbols[id];
      if (!s.pays || !Object.keys(s.pays).length) return;
      html += `<tr><th scope="row"><span class="sym" style="--sym:${s.color}">${s.glyph}</span>${s.name}</th>`;
      heads.forEach((n) => {
        html += `<td>${s.pays[String(n)] ? formatNum(s.pays[String(n)]) : '—'}</td>`;
      });
      html += '</tr>';
    });
    Object.keys(cfg.symbols).forEach((id) => {
      const s = cfg.symbols[id];
      if (!s.scatter_pays || !Object.keys(s.scatter_pays).length) return;
      html += `<tr><th scope="row"><span class="sym" style="--sym:${s.color}">${s.glyph}</span>${s.name}（总注倍数）</th>`;
      heads.forEach((n) => {
        html += `<td>${s.scatter_pays[String(n)] ? formatNum(s.scatter_pays[String(n)]) : '—'}</td>`;
      });
      html += '</tr>';
    });
    html += '</tbody></table>';
    box.innerHTML = html;
  }

  function formatNum(v) {
    return Number(v) % 1 === 0 ? String(Number(v)) : Number(v).toFixed(2);
  }

  function updateHud() {
    el('credits').textContent = credits.toFixed(2);
    el('fs-left').textContent = String(state ? state.freeSpinsLeft : 0);
    el('mult').textContent =
      'x' + (state ? Number(state.fsMultiplier * state.cascadeMultiplier).toFixed(0) : 1);
    const spinning = busy || autoLeft > 0;
    el('btn-spin').disabled = spinning || pendingGamble > 0;
    el('btn-auto').disabled = spinning || pendingGamble > 0;
    el('bet-select').disabled = spinning || (state && state.phase !== 'base');
  }

  // ------------------------------------------------------------------ 交互
  function bindEvents() {
    el('btn-spin').addEventListener('click', () => doSpin());
    el('btn-auto').addEventListener('click', () => {
      autoLeft = autoLeft > 0 ? 0 : 10;
      el('btn-auto').textContent = autoLeft > 0 ? '停止自动' : '自动 10 次';
      updateHud();
      if (autoLeft > 0) doSpin();
    });
    el('btn-reset').addEventListener('click', () => {
      credits = START_CREDITS;
      state = new SlotEngine.GameState();
      localStorage.setItem(STORAGE_KEY, String(credits));
      el('feature-badge').textContent = '基础旋转';
      updateHud();
      say('积分已重置为 1000。');
    });
    const sel = el('game-select');
    if (sel) sel.addEventListener('change', () => loadGame(sel.value));
    el('bet-select').addEventListener('change', updateHud);
    el('gamble-red').addEventListener('click', () => resolveGamble('red'));
    el('gamble-black').addEventListener('click', () => resolveGamble('black'));
    el('gamble-take').addEventListener('click', () => resolveGamble(null));
    document.addEventListener('keydown', (e) => {
      if (e.code === 'Space' && !busy && pendingGamble === 0 && document.activeElement === document.body) {
        e.preventDefault();
        doSpin();
      }
    });
  }

  function say(text) {
    el('win-line').textContent = text;
  }

  async function doSpin() {
    if (busy || pendingGamble > 0) return;
    const bet = currentBet();
    const inFeature = state.phase !== 'base';
    if (!inFeature && credits < bet) {
      say('积分不足，点击「重置积分」继续体验。');
      autoLeft = 0;
      el('btn-auto').textContent = '自动 10 次';
      updateHud();
      return;
    }
    busy = true;
    updateHud();
    if (!inFeature) {
      credits -= bet;
      localStorage.setItem(STORAGE_KEY, String(credits));
    }
    el('round-win').textContent = '0.00';

    const result = machine.spin({ totalBet: bet, state: state });
    state = result.state;
    await playSteps(result);

    credits += result.totalWin;
    localStorage.setItem(STORAGE_KEY, String(credits));

    el('round-win').textContent = result.totalWin.toFixed(2);
    if (result.totalWin > 0) {
      say(`本局中奖 ${result.totalWin.toFixed(2)}（${(result.totalWin / bet).toFixed(1)}x 投注）`);
    } else {
      say('本局未中奖，再试一次？');
    }

    const gamble = cfg.features.gamble;
    if (gamble && gamble.enabled && result.totalWin > 0 && state.phase === 'base') {
      pendingGamble = result.totalWin;
      gambleSteps = 0;
      el('gamble-stake').textContent = pendingGamble.toFixed(2);
      el('gamble-panel').hidden = false;
      say('可选择红黑翻倍，或收下奖金。');
    }

    busy = false;
    if (state.phase !== 'base') {
      el('feature-badge').textContent =
        state.phase === 'free_spins' ? `免费旋转剩余 ${state.freeSpinsLeft}` : '特性进行中';
    } else {
      el('feature-badge').textContent = '基础旋转';
    }
    updateHud();

    if (autoLeft > 0 && pendingGamble === 0) {
      autoLeft -= 1;
      if (autoLeft <= 0) {
        el('btn-auto').textContent = '自动 10 次';
        updateHud();
      } else {
        setTimeout(() => doSpin(), 260);
      }
    }
  }

  async function playSteps(result) {
    let total = 0;
    for (let i = 0; i < result.steps.length; i++) {
      const step = result.steps[i];
      total += step.stepWin;
      const positions = [];
      step.wins.forEach((w) => {
        if (w.kind === 'line' || w.kind === 'ways' || w.kind === 'scatter') {
          w.positions.forEach((p) => positions.push(p));
        }
      });
      const holdCandidates = [];
      if (step.phase === 'hold_win') {
        const hw = cfg.features.hold_win;
        if (hw) {
          const ids = [hw.trigger_symbol].concat(hw.prize_symbols || [], hw.jackpot_symbols || []);
          step.grid.forEach((col, r) =>
            col.forEach((sym, row) => {
              if (ids.indexOf(sym) >= 0) holdCandidates.push([r, row]);
            })
          );
        }
      }
      paintGrid(step.grid, positions, holdCandidates);
      el('mult').textContent = 'x' + Number(step.multiplier).toFixed(0);
      el('fs-left').textContent = String(step.freeSpinRemaining);
      if (step.phase === 'free_spins') {
        el('feature-badge').textContent = `免费旋转剩余 ${step.freeSpinRemaining}`;
      } else if (step.phase === 'hold_win') {
        el('feature-badge').textContent = 'Hold & Win 宝箱重转';
      }
      if (step.events && step.events.length) {
        const e = step.events[0];
        if (e.type === 'expanding_wild') say(`彩虹 Wild 第 ${e.reels.map((r) => r + 1).join('/')} 轴扩展，赠送 ${e.respins} 次重转`);
        else if (e.type === 'free_spins_trigger') say(`触发免费旋转：${e.count} 个 Scatter，获得 ${e.spins} 次`);
        else if (e.type === 'free_spins_retrigger') say(`再触发：额外 ${e.spins} 次免费旋转`);
        else if (e.type === 'hold_win_trigger') say(`Hold & Win 触发：锁定 ${e.locked} 个赏金符号`);
        else if (e.type === 'full_grid_bonus') say(`全屏大奖 +${e.amount}`);
      }
      if (!reduceMotion) await sleep(step.phase === 'hold_win' ? 620 : i === 0 ? 420 : 340);
      if (step.stepWin > 0) el('round-win').textContent = total.toFixed(2);
    }
  }

  function resolveGamble(choice) {
    const g = cfg.features.gamble;
    if (!choice) {
      credits += pendingGamble;
      localStorage.setItem(STORAGE_KEY, String(credits));
      say(`已收下 ${pendingGamble.toFixed(2)}。`);
      pendingGamble = 0;
      el('gamble-panel').hidden = true;
      updateHud();
      return;
    }
    const win = Math.random() < (g.win_probability || 0.5);
    gambleSteps += 1;
    if (win) {
      pendingGamble *= 2;
      el('gamble-stake').textContent = pendingGamble.toFixed(2);
      say(`翻倍成功！当前奖金 ${pendingGamble.toFixed(2)}。`);
    } else {
      say('博彩失败，奖金清零。');
      pendingGamble = 0;
      el('gamble-panel').hidden = true;
    }
    if (pendingGamble > 0 && gambleSteps >= (g.max_steps || 5)) {
      credits += pendingGamble;
      localStorage.setItem(STORAGE_KEY, String(credits));
      say(`已达上限，收下 ${pendingGamble.toFixed(2)}。`);
      pendingGamble = 0;
      el('gamble-panel').hidden = true;
    }
    updateHud();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
