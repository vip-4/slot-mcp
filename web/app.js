/* SLOT 机台合集前端
 * 与后端约定：/api/games、/api/games/<id>、/api/session[/<id>/spin|bet|gamble|auto]
 * 一次 SPIN 可能返回多个 steps（级联 / 免费旋转 / Hold&Win），这里按序播放并保持 UI 响应性。
 */

const API = {
  async json(url, options) {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.error || `HTTP ${res.status}`);
    }
    return res.json();
  },
  get: (url) => API.json(url),
  post: (url, body) => API.json(url, { method: 'POST', body: JSON.stringify(body || {}) }),
};

const state = {
  games: [],
  gameId: null,
  game: null,
  sessionId: 'web-default',
  session: null,
  betIndex: 0,
  betLevels: [],
  lastResult: null,
  stepIndex: 0,
  spinning: false,
  auto: false,
  playing: false,
  cells: [],
  symbols: {},
};

const el = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ------------------------------------------------------------------ 初始化 */
async function init() {
  const { games } = await API.get('/api/games');
  state.games = games;
  renderTabs();
  await selectGame(games[0].id);
  bindControls();
  await refreshBlender();
  setInterval(refreshBlender, 5000);
}

function renderTabs() {
  const tabs = el('game-tabs');
  tabs.innerHTML = '';
  state.games.forEach((game) => {
    const btn = document.createElement('button');
    btn.className = 'tab' + (game.id === state.gameId ? ' active' : '');
    btn.textContent = `${game.name} · ${game.reels}x${game.rows}`;
    btn.onclick = () => selectGame(game.id);
    tabs.appendChild(btn);
  });
}

async function selectGame(gameId) {
  state.gameId = gameId;
  state.game = await API.get(`/api/games/${gameId}`);
  state.symbols = state.game.symbols || {};
  applyTheme(state.game.theme);
  renderTabs();
  renderMeta();
  renderPaytable();
  renderFeatures();
  buildGrid(state.game.reels, state.game.rows);
  el('game-description').textContent = state.game.description;

  state.session = await API.post('/api/session', {
    session_id: state.sessionId,
    game_id: gameId,
    credits: 1000,
  });
  state.betLevels = state.session.bet_levels;
  state.betIndex = state.session.bet_index;
  updateWallet();
  updateBet();
  setStateReady();
}

function applyTheme(theme = {}) {
  const root = document.documentElement.style;
  root.setProperty('--cabinet', theme.cabinet_color || '#20143a');
  root.setProperty('--bg', theme.background || '#0b0714');
  root.setProperty('--accent', theme.accent || '#ffcc33');
  const palette = theme.palette || {};
  if (palette.reel) root.setProperty('--reel', palette.reel);
  if (palette.win) root.setProperty('--win', palette.win);
}

/* ------------------------------------------------------------------ 渲染 */
function buildGrid(reels, rows) {
  const container = el('reels');
  container.innerHTML = '';
  state.cells = [];
  for (let c = 0; c < reels; c += 1) {
    const column = document.createElement('div');
    column.className = 'reel-column';
    const colCells = [];
    for (let r = 0; r < rows; r += 1) {
      const cell = document.createElement('div');
      cell.className = 'cell';
      cell.textContent = '·';
      column.appendChild(cell);
      colCells.push(cell);
    }
    container.appendChild(column);
    state.cells.push(colCells);
  }
}

function renderMeta() {
  const g = state.game;
  const rows = [
    ['尺寸', `${g.reels} x ${g.rows}`],
    ['赔付', g.pay_mode === 'ways' ? `全盘 ${g.lines} Ways` : `固定 ${g.lines} 线`],
    ['目标 RTP', `${(g.target_rtp * 100).toFixed(1)}%`],
    ['波动', g.volatility],
    ['最大倍率', `${g.max_win_multiplier}x`],
    ['下注档位', `${Math.min(...g.bet_steps)} ~ ${Math.max(...g.bet_steps)}`],
  ];
  el('meta-list').innerHTML = rows
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
    .join('');
}

function renderPaytable() {
  const table = el('paytable');
  const body = table.querySelector('tbody');
  const maxCount = state.game.pay_mode === 'ways' ? state.game.reels : state.game.reels;
  const counts = Array.from({ length: maxCount - 1 }, (_, i) => i + 3);
  el('pay-head').textContent = counts.join(' / ') + ' 连';
  const unit = state.game.pay_mode === 'ways' ? '每通路注' : '每线注';
  body.innerHTML = '';
  Object.values(state.symbols).forEach((sym) => {
    const pays = counts.map((c) => (sym.pays && sym.pays[c] ? sym.pays[c] : '-'));
    const scatter = sym.scatter_pays && Object.keys(sym.scatter_pays).length
      ? ` <small>(Scatter ${Object.entries(sym.scatter_pays).map(([k, v]) => `${k}连 ${v}x总注`).join('，')})</small>`
      : '';
    const tr = document.createElement('tr');
    tr.innerHTML =
      `<td><span class="sym">${sym.glyph} ${sym.name}</span>${scatter}</td>` +
      `<td>${pays.join(' / ')} <small>${unit}</small></td>`;
    body.appendChild(tr);
  });
}

function renderFeatures() {
  const detail = state.game.features_detail || {};
  const labels = {
    free_spins: '免费旋转 + 递增倍率',
    hold_win: 'Hold & Win 宝箱重转',
    cascade: '级联雪崩倍率',
    expanding_wild: '扩展 Wild + 重转',
    gamble: '红黑翻倍博彩',
  };
  const items = Object.entries(detail)
    .filter(([, v]) => v && v.enabled !== false)
    .map(([k, v]) => {
      if (k === 'free_spins') {
        const counts = Object.entries(v.trigger_counts).map(([n, s]) => `${n}个→${s}次`).join('，');
        return `<li><b>${labels[k]}</b><br>触发表：${counts}</li>`;
      }
      if (k === 'hold_win') {
        return `<li><b>${labels[k]}</b><br>${v.trigger_count}个赏金符号触发，${v.respins} 次重转</li>`;
      }
      if (k === 'cascade') {
        return `<li><b>${labels[k]}</b><br>每次 +${v.multiplier_step}，上限 ${v.multiplier_cap}x</li>`;
      }
      if (k === 'expanding_wild') {
        return `<li><b>${labels[k]}</b><br>第 ${v.reels.map((r) => r + 1).join('/')} 轴扩展，重转 ${v.respins} 次</li>`;
      }
      if (k === 'gamble') {
        return `<li><b>${labels[k]}</b><br>最多 ${v.max_steps} 次，上限 ${v.max_win_multiplier}x</li>`;
      }
      return `<li><b>${labels[k] || k}</b></li>`;
    });
  el('feature-list').innerHTML = items.join('') || '<li>无额外特性</li>';
}

function updateWallet() {
  el('credits').textContent = Number(state.session.credits).toFixed(2);
  el('step-badge').textContent = state.session.pending_gamble ? '等待博彩结算' : '准备就绪';
  el('step-badge').classList.remove('live');
  renderState();
}

function renderState() {
  const s = state.session.state || {};
  const rows = [
    ['阶段', phaseLabel(s.phase)],
    ['免费旋转剩余', s.free_spins_left || 0],
    ['当前倍率', `${(s.fs_multiplier || 1) * (s.cascade_multiplier || 1)}x`],
    ['本轮已玩', s.spin_count || 0],
  ];
  el('state-list').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');

  const log = el('log');
  log.innerHTML = '';
  (state.session.history || []).slice(-20).reverse().forEach((item) => {
    const li = document.createElement('li');
    const gain = item.win - item.bet;
    li.innerHTML =
      `<span class="tag">#${item.spin_id} ${item.events.length ? item.events.join('/') : ''}</span>` +
      `<span class="${gain >= 0 ? 'pos' : 'neg'}">${gain >= 0 ? '+' : ''}${gain.toFixed(2)}</span>`;
    log.appendChild(li);
  });
}

function phaseLabel(phase) {
  return { base: '基础游戏', free_spins: '免费旋转', hold_win: 'Hold & Win' }[phase] || phase;
}

function updateBet() {
  el('bet-amount').textContent = Number(state.betLevels[state.betIndex]).toFixed(2);
}

/* ------------------------------------------------------------------ 交互 */
function bindControls() {
  el('spin-btn').onclick = spin;
  el('bet-up').onclick = () => changeBet(1);
  el('bet-down').onclick = () => changeBet(-1);
  el('auto-btn').onclick = toggleAuto;
  el('paytable-btn').onclick = () => document.querySelector('.paytable-panel').classList.toggle('hidden');
  el('clear-log').onclick = () => { el('log').innerHTML = ''; };
  el('build-btn').onclick = buildCabinet;
  el('animate-btn').onclick = animateInBlender;
  el('gamble-red').onclick = () => gamble('red');
  el('gamble-black').onclick = () => gamble('black');
  el('gamble-take').onclick = () => gamble(null, true);
  document.addEventListener('keydown', (e) => {
    if (e.code === 'Space') { e.preventDefault(); spin(); }
  });
}

function changeBet(delta) {
  const next = Math.min(Math.max(state.betIndex + delta, 0), state.betLevels.length - 1);
  if (next === state.betIndex) return;
  state.betIndex = next;
  updateBet();
  API.post(`/api/session/${state.sessionId}/bet`, { bet_index: state.betIndex }).catch(() => {});
}

function setStateReady() {
  el('spin-btn').disabled = false;
  el('gamble-modal').hidden = !state.session.pending_gamble;
  if (state.session.pending_gamble) {
    el('gamble-stake').textContent = Number(state.session.gamble_stake).toFixed(2);
  }
}

async function spin() {
  if (state.spinning || state.session.pending_gamble) return;
  state.spinning = true;
  el('spin-btn').disabled = true;
  el('step-badge').textContent = '旋转中…';
  el('step-badge').classList.add('live');
  el('step-win').textContent = '';
  clearHighlights();
  try {
    const payload = await API.post(`/api/session/${state.sessionId}/spin`, {
      bet_index: state.betIndex,
    });
    state.session = payload;
    state.lastResult = payload.result;
    await playResult(payload.result);
    el('credits').textContent = Number(payload.credits).toFixed(2);
    renderState();
  } catch (err) {
    showToast(err.message, '⚠️');
  } finally {
    state.spinning = false;
    setStateReady();
    el('step-badge').classList.remove('live');
    el('step-badge').textContent = '准备就绪';
  }
}

async function toggleAuto() {
  state.auto = !state.auto;
  el('auto-btn').textContent = state.auto ? 'STOP' : 'AUTO';
  el('auto-btn').classList.toggle('live', state.auto);
  if (state.auto) {
    await API.post(`/api/session/${state.sessionId}/auto`, { spins: 9999, interval: 0.8 });
    autoLive();
  } else {
    await API.post(`/api/session/${state.sessionId}/auto`, { stop: true });
  }
}

async function autoLive() {
  while (state.auto) {
    const status = await API.get(`/api/session/${state.sessionId}/auto`);
    if (!status.running) break;
    const snapshot = await API.get(`/api/session/${state.sessionId}`);
    state.session = snapshot;
    el('credits').textContent = Number(snapshot.credits).toFixed(2);
    renderState();
    el('step-badge').textContent = `自动 ${status.done}/${status.total}`;
    await sleep(400);
  }
  if (state.auto) { state.auto = false; el('auto-btn').textContent = 'AUTO'; }
  el('step-badge').textContent = '准备就绪';
}

async function gamble(choice, take = false) {
  try {
    const payload = await API.post(`/api/session/${state.sessionId}/gamble`, { choice, take });
    state.session = payload;
    el('credits').textContent = Number(payload.credits).toFixed(2);
    el('gamble-modal').hidden = !payload.pending_gamble;
    el('gamble-stake').textContent = Number(payload.gamble_stake).toFixed(2);
    const outcome = payload.gamble || {};
    if (outcome.finished) {
      showToast(outcome.win ? `收下 ${outcome.collected.toFixed(2)}` : '博彩失败', outcome.win ? '🎉' : '💧');
    }
    renderState();
  } catch (err) {
    showToast(err.message, '⚠️');
  }
}

/* ------------------------------------------------------------------ 步骤播放 */
async function playResult(result) {
  const steps = result.steps || [];
  let index = 0;
  for (const step of steps) {
    index += 1;
    const label = `${kindLabel(step.phase)} ${index}/${steps.length}`;
    el('step-badge').textContent = label;
    await renderGrid(step.grid, step.wins);
    if (step.step_win > 0) {
      el('step-win').textContent = `+${step.step_win.toFixed(2)}  (${step.multiplier}x)`;
    } else {
      el('step-win').textContent = '';
    }
    await sleep(step.phase === 'base' ? 320 : 520);
  }
  announceEvents(result);
}

function kindLabel(phase) {
  return { base: '基础', free_spins: '免费旋转', hold_win: 'Hold & Win' }[phase] || phase;
}

async function renderGrid(grid, wins = []) {
  const winPositions = new Set();
  wins.forEach((w) => (w.positions || []).forEach(([c, r]) => winPositions.add(`${c},${r}`)));
  const promises = [];
  for (let c = 0; c < state.cells.length; c += 1) {
    for (let r = 0; r < state.cells[c].length; r += 1) {
      const cell = state.cells[c][r];
      const symbolId = (grid[c] && grid[c][r]) || '';
      const symbol = state.symbols[symbolId];
      cell.textContent = symbol ? symbol.glyph : '·';
      cell.classList.remove('win', 'rolling', 'pop', 'dim');
      // 逐轴的错峰滚动动画
      promises.push(
        sleep(c * 70).then(() => {
          cell.classList.add('rolling');
          setTimeout(() => cell.classList.remove('rolling'), 400);
        })
      );
      if (winPositions.has(`${c},${r}`)) {
        setTimeout(() => cell.classList.add('win'), c * 70 + 380);
      }
    }
  }
  await Promise.all(promises);
  await sleep(360);
}

function clearHighlights() {
  state.cells.forEach((col) => col.forEach((cell) => cell.classList.remove('win', 'dim')));
}

function announceEvents(result) {
  const events = result.events || [];
  const totalWin = result.total_win || 0;
  if (events.some((e) => e.type === 'free_spins_trigger')) {
    const ev = events.find((e) => e.type === 'free_spins_trigger');
    showToast(`触发免费旋转 ${ev.spins} 次！`, '🎡', 2200);
  } else if (events.some((e) => e.type === 'hold_win_trigger')) {
    const ev = events.find((e) => e.type === 'hold_win_trigger');
    showToast(`宝箱重转开启：锁定 ${ev.locked} 个符号`, '🪙', 2200);
  } else if (events.some((e) => e.type === 'expanding_wild')) {
    showToast('扩展 Wild 降临！', '🌈', 1800);
  } else if (totalWin >= result.total_bet * 10) {
    showToast(`大獎 ${totalWin.toFixed(2)}！`, '💎', 1800);
  }
}

function showToast(text, icon = 'ℹ️', duration = 1500) {
  const overlay = el('overlay');
  el('overlay-icon').textContent = icon;
  el('overlay-title').textContent = text;
  el('overlay-text').textContent = '';
  overlay.hidden = false;
  setTimeout(() => { overlay.hidden = true; }, duration);
}

/* ------------------------------------------------------------------ Blender */
async function refreshBlender() {
  try {
    const status = await API.get('/api/blender/status');
    const connected = !!status.connected;
    el('blender-chip').classList.toggle('online', connected);
    el('blender-text').textContent = connected
      ? `Blender ${(status.blender && status.blender.blender) || '已连接'}`
      : 'Blender 未连接';
  } catch {
    el('blender-text').textContent = 'UI 服务未连接';
  }
}

async function buildCabinet() {
  el('blender-note').textContent = '构建中…';
  try {
    const res = await API.post('/api/blender/build', { game_id: state.gameId, scale: 1.0 });
    el('blender-note').textContent = `已构建 ${res.result.root}`;
  } catch (err) {
    el('blender-note').textContent = err.message;
  }
}

async function animateInBlender() {
  el('blender-note').textContent = '推送动画中…';
  try {
    const res = await API.post('/api/blender/animate', { session_id: state.sessionId });
    el('blender-note').textContent = `帧范围 ${res.result.frame_start}-${res.result.frame_end}`;
  } catch (err) {
    el('blender-note').textContent = err.message;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  init().catch((err) => {
    el('game-description').textContent = `初始化失败：${err.message}`;
  });
});
