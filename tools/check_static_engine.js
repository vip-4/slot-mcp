#!/usr/bin/env node
/**
 * 前端引擎 RTP 校验：与 Python 侧 `python -m slotmcp.tools.verify_rtp` 对照。
 *
 * 用法（需要 node ≥ 16，仓库根目录执行）：
 *   node tools/check_static_engine.js [局数] [机台id,逗号分隔]
 *   node tools/check_static_engine.js 100000
 *   node tools/check_static_engine.js 200000 lucky_fruits,candy_carnival
 *
 * 前端引擎复用 Python 导出的虚拟条带（reel_sets.*.expanded），
 * 因此两侧 RTP 应在统计误差内一致；偏差过大通常意味着端口实现出现分叉。
 */
'use strict';

const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const enginePath = path.join(root, 'static', 'js', 'engine.js');
const dataPath = path.join(root, 'static', 'data', 'games.json');

if (!fs.existsSync(dataPath)) {
  console.error('缺少 static/data/games.json，请先运行：python tools/build_static.py');
  process.exit(1);
}

const SlotEngine = require(enginePath);
const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
const N = Number(process.argv[2] || 100000);
const only = process.argv[3] ? process.argv[3].split(',') : null;
const games = data.games.filter((g) => !only || only.includes(g.id));

console.log(`机台                 局数      RTP      命中率    最大倍率`);
console.log('-'.repeat(58));
for (const cfg of games) {
  const machine = new SlotEngine.SlotMachine(JSON.parse(JSON.stringify(cfg)));
  const bet = 1.0;
  let total = 0;
  let hits = 0;
  let max = 0;
  for (let i = 0; i < N; i++) {
    const r = machine.spin({ totalBet: bet });
    total += r.totalWin;
    if (r.totalWin > 0) hits += 1;
    const mult = r.totalWin / bet;
    if (mult > max) max = mult;
  }
  console.log(
    cfg.id.padEnd(18) +
      String(N).padStart(8) +
      '   ' +
      (total / (N * bet)).toFixed(4) +
      '   ' +
      (hits / N).toFixed(4) +
      '   ' +
      max.toFixed(1) +
      'x'
  );
}
console.log('\n对照：python -m slotmcp.tools.verify_rtp -n ' + N);
