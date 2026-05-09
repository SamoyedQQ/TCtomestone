'use strict';

// ── Constants ────────────────────────────────────────────────────────────────

const ENCOUNTERS = {
  1077: { name: '絕歐米茄',   full: 'The Omega Protocol' },
  1076: { name: '絕龍詩戰爭', full: "Dragonsong's Reprise" },
  1075: { name: '絕亞歷山大', full: 'The Epic of Alexander' },
  1074: { name: '絕究極神兵', full: "The Weapon's Refrain" },
  1073: { name: '絕巴哈姆特', full: 'The Unending Coil of Bahamut' },
};

const JOB_ZH = {
  Paladin: '騎士', Warrior: '戰士', DarkKnight: '暗騎', Gunbreaker: '絕槍',
  WhiteMage: '白魔', Scholar: '學者', Astrologian: '占星', Sage: '賢者',
  Monk: '武僧', Dragoon: '龍騎', Ninja: '忍者', Samurai: '武士',
  Reaper: '鐮刀', Viper: '蝰蛇',
  Bard: '詩人', Machinist: '機工', Dancer: '舞者',
  BlackMage: '黑魔', Summoner: '召喚', RedMage: '赤魔', Pictomancer: '繪靈',
};

// Job colors from PartyFinderWindow.cs (Vector4 → hex)
const JOB_CSS = {
  Paladin: '#a6d4ff', Warrior: '#f05959', DarkKnight: '#d14fbf', Gunbreaker: '#bfbf80',
  WhiteMage: '#e0e0e0', Scholar: '#94b5f5', Astrologian: '#f7de7a', Sage: '#8ad6cc',
  Monk: '#f59e59', Dragoon: '#6691de', Ninja: '#f55c8c', Samurai: '#e3822e',
  Reaper: '#a170b3', Viper: '#59cc73',
  Bard: '#e6db9e', Machinist: '#a3dede', Dancer: '#ed9ebf',
  BlackMage: '#a68ce6', Summoner: '#73c79e', RedMage: '#e68080', Pictomancer: '#d9a6e6',
};

const ROLE_JOBS = {
  Tank:   ['Paladin', 'Warrior', 'DarkKnight', 'Gunbreaker'],
  Healer: ['WhiteMage', 'Scholar', 'Astrologian', 'Sage'],
  Melee:  ['Monk', 'Dragoon', 'Ninja', 'Samurai', 'Reaper', 'Viper'],
  Ranged: ['Bard', 'Machinist', 'Dancer'],
  Caster: ['BlackMage', 'Summoner', 'RedMage', 'Pictomancer'],
};

const ROLE_ZH = { Tank: '坦克', Healer: '治療', Melee: '近戰', Ranged: '遠端', Caster: '法術' };

const PAGE_SIZE = 30;

const TEAM_ORDER = [
  'Warrior', 'DarkKnight', 'Paladin', 'Gunbreaker',
  'Monk', 'Dragoon', 'Ninja', 'Samurai', 'Reaper', 'Viper',
  'Bard', 'Machinist', 'Dancer',
  'BlackMage', 'Summoner', 'RedMage', 'Pictomancer',
  'WhiteMage', 'Astrologian', 'Scholar', 'Sage',
];

const ROLE_BORDER = { Tank: '#3b82f6', Healer: '#22c55e' };
function roleBorderColor(job) {
  return ROLE_BORDER[jobToRole(job)] ?? '#ef4444';
}

function jobToRole(job) {
  for (const [role, jobs] of Object.entries(ROLE_JOBS)) {
    if (jobs.includes(job)) return role;
  }
  return 'Unknown';
}

function detectEncounterId(name) {
  const n = name.toLowerCase();
  if (n.includes('twintania') || n.includes('nael') || n.includes('bahamut prime') || n.includes('golden bahamut')) return 1073;
  if (n.includes('garuda') || n.includes('ifrit') || n.includes('titan') || (n.includes('ultima') && !n.includes('alexander'))) return 1074;
  if (n.includes('living liquid') || n.includes('cruise chaser') || n.includes('alexander') || n.includes('brute justice')) return 1075;
  if (n.includes('adelphel') || n.includes('thordan') || n.includes('nidhogg') || n.includes('hraesvelgr') || n.includes('estinien') || n.includes('dragon king') || n.includes('left eye') || n.includes('right eye')) return 1076;
  if (n.includes('omega')) return 1077;
  return null;
}

function detectPhase(eid, encounterName) {
  if (!encounterName) return null;
  const parts = encounterName.split('/').map(s => s.trim().toLowerCase());
  const chain = parts.filter(p => p && p !== '...' && !p.startsWith('...'));
  const last  = chain[chain.length - 1] || '';

  switch (eid) {
    case 1073: {  // UCoBH - 5 phases (wipes P1–P4; P5 = clear)
      // New format: "P1 Twintania" / "P2 Nael" / "P3 Bahamut Prime" / "P4 Grand Octet"
      const m = encounterName.match(/^P(\d+)/i);
      if (m) return parseInt(m[1]);
      // Legacy fallback
      if (last.includes('golden bahamut')) return 4;
      if (last.includes('bahamut prime'))  return 3;
      if (last.includes('nael'))           return 2;
      return 1;
    }

    case 1074: // UWU - 4 phases
      if (last.includes('ultima'))  return 4;
      if (last.includes('titan'))   return 3;
      if (last.includes('ifrit'))   return 2;
      return 1;

    case 1075: // TEA - 4 phases
      if (chain.some(p => p.includes('perfect')))                                 return 4;
      if (chain.some(p => p.includes('alexander') && !p.includes('living')))      return 3;
      if (chain.some(p => p.includes('brute') || p.includes('cruise')))           return 2;
      return 1;

    case 1076: { // DSR - 7 phases
      if (last.includes('dragon king') || last.includes('dragon-king')) return 7;
      if (last.includes('hraesvelgr') || last.includes('nidstinien') || last.includes('estinien')) return 6;
      if (last.includes('left eye') || last.includes('right eye') || last.includes('the eyes')) return 4;
      if (last.includes('nidhogg'))
        return chain.some(p => p.includes('hraesvelgr') || p.includes('nidstinien')) ? 6 : 3;
      if (last.includes('thordan')) {
        if (chain.some(p => p.includes('hraesvelgr') || p.includes('nidstinien'))) return 7;
        if (chain.some(p => p.includes('nidhogg'))) return 5;
        return 2;
      }
      return 1;
    }

    case 1077: { // TOP - 6 phases
      if (last.includes('alpha omega'))                                   return 6;
      if (last.includes('dynamis') || last.includes('run:'))              return 5;
      if (last.includes('blue screen') || last.includes('blue_screen'))   return 4;
      if (last.includes('reconfigur'))                                     return 3;
      if (last.includes('omega-m') || last.includes('omega-f') ||
          last.includes('omega m') || last.includes('omega f'))           return 2;
      return 1;
    }
  }
  return null;
}

// UCoB phase HP pools (fightPercentage 100=start → 80=clear spans this total)
const UCOB_PHASES = [
  { name: 'P1', hp: 1_882_943 },
  { name: 'P2', hp: 1_706_046 },
  { name: 'P3', hp: 1_871_792 },  // BP × 0.4 (transitions at 60%)
  { name: 'P4', hp: 1_520_898 },  // Twin P4 (753,177) + Nael P4 (767,721)
  { name: 'P5', hp: 4_679_480 },
];
const UCOB_TOTAL_HP = UCOB_PHASES.reduce((s, p) => s + p.hp, 0);

// fightPercentage → { phase: "P3", pct: 45.2 }
function ucobPhaseFromFightPct(fightPct) {
  const damage = UCOB_TOTAL_HP * (100 - fightPct) / 20;
  let cumulative = 0;
  for (const { name, hp } of UCOB_PHASES) {
    if (damage <= cumulative + hp) {
      return { phase: name, pct: (damage - cumulative) / hp * 100 };
    }
    cumulative += hp;
  }
  return { phase: 'P5', pct: 100 };
}

// UCOB wipe boss_hp_pct (= raw fightPercentage) → "P3 (45.2%)"
function ucobWipeHpStr(bossHpPct) {
  const { phase, pct } = ucobPhaseFromFightPct(bossHpPct);
  return `${phase} (${pct.toFixed(1)}%)`;
}

// HP pools per phase for non-UCoB ultimates (fightPercentage 100→0)
const ENCOUNTER_PHASES = {
  1074: [
    { name: 'P1', hp: 1_664_845 },
    { name: 'P2', hp: 1_408_008 },
    { name: 'P3', hp: 1_449_210 },
    { name: 'P4', hp: 3_750_000 },
  ],
  1075: [
    { name: 'P1', hp: 3_356_051 },
    { name: 'P2', hp: 4_337_852 },
    { name: 'P3', hp: 3_180_181 },
    { name: 'P4', hp: 7_535_109 },
  ],
  1076: [
    { name: 'P1', hp: 5_670_940 },
    { name: 'P2', hp: 7_439_000 },
    { name: 'P3', hp: 6_449_440 },
    { name: 'P4', hp: 8_839_608 },
    { name: 'P5', hp: 5_821_796 },
    { name: 'P6', hp: 9_070_736 },
    { name: 'P7', hp: 12_178_508 },
  ],
  1077: [
    { name: 'P1', hp: 8_557_964 },
    { name: 'P2', hp: 8_629_240 },
    { name: 'P3', hp: 11_125_976 },
    { name: 'P4', hp: 4_895_429 },
    { name: 'P5', hp: 13_707_136 },
    { name: 'P6', hp: 20_530_948 },
  ],
};

// fightPercentage (100→0) → "P3 (45.2%)" using HP pools
function wipeProgressStr(eid, fightPct) {
  const phases = ENCOUNTER_PHASES[eid];
  if (!phases) return null;
  const totalHp = phases.reduce((s, p) => s + p.hp, 0);
  const damage = totalHp * (100 - fightPct) / 100;
  if (damage < 0) return null;
  let cumulative = 0;
  for (const { name, hp } of phases) {
    if (damage <= cumulative + hp)
      return `${name} (${((damage - cumulative) / hp * 100).toFixed(1)}%)`;
    cumulative += hp;
  }
  return `${phases[phases.length - 1].name} (100.0%)`;
}

function fmtDuration(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2, '0')}`;
}

function fmtDate(ms) {
  if (!ms) return '—';
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function rankBadge(n) {
  const colors = ['var(--rank1)', 'var(--rank2)', 'var(--rank3)'];
  const color  = n <= 3 ? `color:${colors[n-1]};font-weight:700` : 'color:var(--text-muted)';
  return `<span style="${color};font-variant-numeric:tabular-nums">#${n}</span>`;
}

function rankPctBadge(rank, total, job) {
  if (rank == null || !total) return '—';
  const pct = Math.floor((1 - (rank - 1) / total) * 100);
  const color = pct === 100 ? '#ffd700'
    : pct === 99           ? '#f472b6'
    : pct >= 95            ? '#fb923c'
    : pct >= 70            ? '#c084fc'
    : pct >= 50            ? '#60a5fa'
    : pct >= 30            ? '#4ade80'
    :                        '#71717a';
  const jobZh = JOB_ZH[job] || job || '';
  const tip = `<span style="color:${color};font-weight:700">${pct}%</span> for all ${jobZh} (${total} parses)`;
  return `<span class="rank-pct-badge" style="color:${color};font-variant-numeric:tabular-nums;font-weight:600">#${rank} (${pct})<span class="rank-tip">${tip}</span></span>`;
}

function fmtDateTime(ms) {
  if (!ms) return '—';
  const d = new Date(ms);
  const date = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  const time = `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  return `${date} ${time}`;
}

function jobChip(job) {
  const zh = JOB_ZH[job] || job;
  const cls = JOB_CSS[job] ? `job-${job}` : 'job-Unknown';
  return `<span class="job-chip ${cls}">${zh}</span>`;
}

function encChip(eid) {
  return `<span class="enc-chip">${ENCOUNTERS[eid]?.name ?? '—'}</span>`;
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Data Store ────────────────────────────────────────────────────────────────

const DS = {
  playerBests: null,
  clears: null,
  clearsByEnc: {},
  killCounts: {},
  playerJobMap: {},   // key: "Name@Server:eid" → best clear record

  meta: null,

  async loadAll() {
    const [pb, cl, mt] = await Promise.all([
      fetch('data/player_bests.json').then(r => r.json()),
      fetch('data/clears.json').then(r => r.json()),
      fetch('data/meta.json').then(r => r.json()).catch(() => null),
    ]);
    this.playerBests = pb;
    this.clears = cl;
    this.meta = mt;
    this._buildClearsByEnc();
    this._buildKillCounts();
    this._buildPlayerJobMap();
  },

  _buildPlayerJobMap() {
    for (const [key, rec] of Object.entries(this.playerBests)) {
      const parts = key.split(':');
      if (parts.length < 3 || parts[parts.length - 1] === '_wipe') continue;
      const mapKey = `${parts[0]}:${parts[1]}`;   // Name@Server:eid
      const cur = this.playerJobMap[mapKey];
      if (!cur) { this.playerJobMap[mapKey] = rec; continue; }
      if (rec.is_clear && !cur.is_clear) { this.playerJobMap[mapKey] = rec; continue; }
      if (rec.is_clear === cur.is_clear && rec.rdps > cur.rdps) this.playerJobMap[mapKey] = rec;
    }
  },

  _buildClearsByEnc() {
    const bestByTeam = {};   // key: "eid|player1|player2|..."
    for (const c of this.clears) {
      const eid = detectEncounterId(c.encounter);
      if (!eid) continue;
      const teamKey = `${eid}|` + [...c.players].sort().join('|');
      const existing = bestByTeam[teamKey];
      if (!existing || c.duration_ms < existing.duration_ms) {
        bestByTeam[teamKey] = { ...c, _eid: eid };
      }
    }
    for (const rec of Object.values(bestByTeam)) {
      if (!this.clearsByEnc[rec._eid]) this.clearsByEnc[rec._eid] = [];
      this.clearsByEnc[rec._eid].push(rec);
    }
    for (const eid of Object.keys(this.clearsByEnc)) {
      this.clearsByEnc[eid].sort((a, b) => a.duration_ms - b.duration_ms);
    }
  },

  _buildKillCounts() {
    for (const c of this.clears) {
      const eid = detectEncounterId(c.encounter);
      if (!eid) continue;
      for (const p of c.players) {
        const key = `${p}:${eid}`;
        this.killCounts[key] = (this.killCounts[key] || 0) + 1;
      }
    }
  },

  getLeaderboard(encounterId, role, job) {
    const entries = [];
    for (const rec of Object.values(this.playerBests)) {
      if (rec.encounter_id !== encounterId) continue;
      if (!rec.is_clear || rec.rdps <= 0 || !rec.job || rec.job === 'Unknown') continue;
      if (jobToRole(rec.job) !== role) continue;
      if (job && rec.job !== job) continue;
      entries.push(rec);
    }
    entries.sort((a, b) => b.rdps - a.rdps);
    return entries;
  },

  getClearSpeed(encounterId) {
    if (!encounterId) {
      // all encounters merged, sorted by duration
      return Object.values(this.clearsByEnc).flat().sort((a, b) => a.duration_ms - b.duration_ms);
    }
    return this.clearsByEnc[encounterId] || [];
  },

  getRank(eid, job, rdps) {
    let rank = 1, total = 0;
    for (const rec of Object.values(this.playerBests)) {
      if (rec.encounter_id !== eid || rec.job !== job) continue;
      if (!rec.is_clear || rec.rdps <= 0 || rec.job === 'Unknown') continue;
      total++;
      if (rec.rdps > rdps) rank++;
    }
    return { rank, total };
  },

  // Returns the set of jobs present in the leaderboard for a given encounter+role
  availableJobs(encounterId, role) {
    const jobs = new Set();
    for (const rec of Object.values(this.playerBests)) {
      if (rec.encounter_id !== encounterId) continue;
      if (!rec.is_clear || rec.rdps <= 0 || !rec.job || rec.job === 'Unknown') continue;
      if (jobToRole(rec.job) !== role) continue;
      jobs.add(rec.job);
    }
    return jobs;
  },

  searchPlayer(query) {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const seen = new Set();
    const results = [];
    for (const rec of Object.values(this.playerBests)) {
      const id = `${rec.name}@${rec.server}`;
      if (seen.has(id)) continue;
      if (rec.name.toLowerCase().includes(q) || id.toLowerCase().includes(q)) {
        seen.add(id);
        results.push({ name: rec.name, server: rec.server });
      }
    }
    return results;
  },

  getPlayerProfile(name, server) {
    const byEnc = {};
    for (const rec of Object.values(this.playerBests)) {
      if (rec.name !== name || rec.server !== server) continue;
      const eid = rec.encounter_id;
      if (!byEnc[eid]) byEnc[eid] = [];
      const kills    = this.killCounts[`${name}@${server}:${eid}`] || 0;
      const rankInfo = (rec.is_clear && rec.rdps > 0) ? this.getRank(eid, rec.job, rec.rdps) : null;
      byEnc[eid].push({ ...rec, kills, rank: rankInfo?.rank ?? null, rankTotal: rankInfo?.total ?? null });
    }
    for (const eid of Object.keys(byEnc)) {
      const recs = byEnc[eid];
      const hasClears = recs.some(r => r.is_clear);
      if (hasClears) byEnc[eid] = recs.filter(r => r.is_clear);
      byEnc[eid].sort((a, b) => {
        if (a.is_clear && !b.is_clear) return -1;
        if (!a.is_clear && b.is_clear) return 1;
        if (a.is_clear) {
          const rankDiff = (a.rank ?? Infinity) - (b.rank ?? Infinity);
          if (rankDiff !== 0) return rankDiff;
          const pctA = a.rankTotal ? Math.floor((1 - (a.rank - 1) / a.rankTotal) * 100) : 0;
          const pctB = b.rankTotal ? Math.floor((1 - (b.rank - 1) / b.rankTotal) * 100) : 0;
          return pctB - pctA;
        }
        return a.boss_hp_pct - b.boss_hp_pct;
      });
    }
    return byEnc;
  },
};

// ── UI State ──────────────────────────────────────────────────────────────────

const STATE = {
  mainTab: 'leaderboard',
  lbType: 'rdps',
  rdpsEncounter: 1074,
  speedEncounter: 1074,
  role: 'Tank',
  job: null,
  rdpsPage: 1,
  speedPage: 1,
};

let returnSnapshot = null;

function $id(id) { return document.getElementById(id); }

function renderPagination(el, page, totalPages, onChange) {
  if (totalPages <= 1) { el.innerHTML = ''; return; }
  el.innerHTML = `
    <button class="page-btn" data-dir="-1"${page <= 1 ? ' disabled' : ''}>‹ 上一頁</button>
    <span class="page-info">第 ${page} / ${totalPages} 頁</span>
    <button class="page-btn" data-dir="1"${page >= totalPages ? ' disabled' : ''}>下一頁 ›</button>
  `;
  el.onclick = e => {
    const btn = e.target.closest('.page-btn');
    if (!btn || btn.disabled) return;
    onChange(page + parseInt(btn.dataset.dir, 10));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
}

function setActive(container, selector, activeEl) {
  container.querySelectorAll(selector).forEach(el => el.classList.remove('active'));
  if (activeEl) activeEl.classList.add('active');
}

// ── Job Filter ────────────────────────────────────────────────────────────────

function renderJobFilter() {
  const bar = $id('job-filter');
  bar.innerHTML = '';

  const available = DS.availableJobs(STATE.rdpsEncounter, STATE.role);
  const jobs = (ROLE_JOBS[STATE.role] || []).filter(j => available.has(j));

  for (const job of jobs) {
    const color = JOB_CSS[job] || '#a1a1aa';
    const btn = document.createElement('button');
    btn.className = `filter-btn job-btn${STATE.job === job ? ' active' : ''}`;
    btn.dataset.job = job;
    btn.style.setProperty('--jc', color);
    btn.textContent = JOB_ZH[job] || job;
    bar.appendChild(btn);
  }

  bar.onclick = e => {
    const btn = e.target.closest('.job-btn');
    if (!btn) return;
    const clicked = btn.dataset.job;
    STATE.job = STATE.job === clicked ? null : clicked;
    STATE.rdpsPage = 1;
    renderJobFilter();
    renderLeaderboard();
  };
}

// ── Leaderboard Render ────────────────────────────────────────────────────────

function renderLeaderboard() {
  const all    = DS.getLeaderboard(STATE.rdpsEncounter, STATE.role, STATE.job);
  const tbody  = $id('rdps-tbody');
  const empty  = $id('rdps-empty');
  const table  = $id('rdps-table');
  const pgEl   = $id('rdps-pagination');
  const stats  = $id('lb-stats');

  if (stats) {
    if (all.length === 0) {
      stats.textContent = '';
    } else {
      const uniq = new Set(all.map(r => `${r.name}@${r.server}`)).size;
      stats.innerHTML = `此分類資料：共 ${all.length} 筆<br>此分類玩家數：共 ${uniq} 人`;
    }
  }

  if (all.length === 0) {
    tbody.innerHTML = '';
    table.classList.add('hidden');
    empty.classList.remove('hidden');
    pgEl.innerHTML = '';
    return;
  }
  table.classList.remove('hidden');
  table.classList.toggle('single-job', !!STATE.job);
  empty.classList.add('hidden');

  const totalPages = Math.max(1, Math.ceil(all.length / PAGE_SIZE));
  if (STATE.rdpsPage > totalPages) STATE.rdpsPage = totalPages;
  const start   = (STATE.rdpsPage - 1) * PAGE_SIZE;
  const entries = all.slice(start, start + PAGE_SIZE);

  tbody.innerHTML = entries.map((rec, i) => {
    const rank      = start + i + 1;
    const nameColor = JOB_CSS[rec.job] || 'var(--text)';
    return `
    <tr class="lb-row" data-name="${esc(rec.name)}" data-server="${esc(rec.server)}">
      <td class="col-rank" style="text-align:center">${rankBadge(rank)}</td>
      <td class="col-player" style="color:${nameColor};font-weight:500">${esc(rec.name)}</td>
      <td class="col-server"><span class="server-name">${esc(rec.server)}</span></td>
      <td class="col-job">${jobChip(rec.job)}</td>
      <td class="col-lnum rdps-val">${rec.rdps.toFixed(1)}</td>
      <td class="col-lnum parse-val">${rec.adps > 0 ? rec.adps.toFixed(1) : '—'}</td>
      <td class="col-date">${rec.duration_ms > 0 ? fmtDuration(rec.duration_ms) : '—'}</td>
    </tr>`;
  }).join('');

  renderPagination(pgEl, STATE.rdpsPage, totalPages, p => {
    STATE.rdpsPage = p;
    renderLeaderboard();
  });
}

// ── Speed Render ──────────────────────────────────────────────────────────────

function renderClearSpeed() {
  const all   = DS.getClearSpeed(STATE.speedEncounter);
  const tbody = $id('speed-tbody');
  const empty = $id('speed-empty');
  const table = $id('speed-table');
  const pgEl  = $id('speed-pagination');

  if (all.length === 0) {
    tbody.innerHTML = '';
    table.classList.add('hidden');
    empty.classList.remove('hidden');
    pgEl.innerHTML = '';
    return;
  }
  table.classList.remove('hidden');
  empty.classList.add('hidden');

  const totalPages = Math.max(1, Math.ceil(all.length / PAGE_SIZE));
  if (STATE.speedPage > totalPages) STATE.speedPage = totalPages;
  const start  = (STATE.speedPage - 1) * PAGE_SIZE;
  const clears = all.slice(start, start + PAGE_SIZE);

  tbody.innerHTML = clears.map((c, i) => {
    const i_global = start + i;
    const eid = c._eid ?? detectEncounterId(c.encounter);
    const sorted = [...c.players].sort((a, b) => {
      const ja = DS.playerJobMap[`${a}:${eid}`]?.job;
      const jb = DS.playerJobMap[`${b}:${eid}`]?.job;
      return (ja ? TEAM_ORDER.indexOf(ja) : 999) - (jb ? TEAM_ORDER.indexOf(jb) : 999);
    });
    const team = sorted.map(p => {
      const [pName, pSrv = ''] = p.split('@');
      const rec   = DS.playerJobMap[`${p}:${eid}`];
      const job   = rec?.job;
      const color  = job ? (JOB_CSS[job] || '') : '';
      const tip    = job ? (JOB_ZH[job] || job) : '';
      const border = job ? roleBorderColor(job) : '';
      const style  = (color || border) ? ` style="${color ? `--jc:${color};` : ''}${border ? `--rc:${border}` : ''}"` : '';
      return `<span class="team-player team-player-link"${style}${tip ? ` data-tip="${tip}"` : ''} data-name="${esc(pName)}" data-srv="${esc(pSrv)}"><span>${esc(pName)}</span>@${esc(pSrv)}</span>`;
    }).join('');
    return `
      <tr>
        <td class="col-rank" style="text-align:center">${rankBadge(i_global + 1)}</td>
        <td class="col-enc">${encChip(eid)}</td>
        <td class="col-time">${fmtDuration(c.duration_ms)}</td>
        <td class="col-date">${fmtDate(c.clear_dt_ms)}</td>
        <td><div class="team-list">${team}</div></td>
      </tr>
    `;
  }).join('');

  renderPagination(pgEl, STATE.speedPage, totalPages, p => {
    STATE.speedPage = p;
    renderClearSpeed();
  });
}

// ── Player Render ─────────────────────────────────────────────────────────────

function renderPlayerProfile(name, server) {
  const byEnc = DS.getPlayerProfile(name, server);
  const results = $id('player-results');
  results.innerHTML = '';

  if (Object.keys(byEnc).length === 0) {
    results.innerHTML = `<div class="empty-state">找不到玩家「${esc(name)}@${esc(server)}」的資料</div>`;
    return;
  }

  const card = document.createElement('div');
  card.className = 'player-card';
  card.innerHTML = `
    <div class="player-card-header">
      <div class="player-card-name">${esc(name)}<span class="at-server">@${esc(server)}</span></div>
    </div>
    <div class="table-wrap" style="border:none;border-radius:0">
      <table class="data-table player-profile-table">
        <thead>
          <tr>
            <th>副本</th>
            <th>狀態</th>
            <th>職業</th>
            <th class="col-num">rDPS</th>
            <th class="col-rank">排名</th>
            <th class="col-num">總擊殺數</th>
            <th class="col-date">日期</th>
          </tr>
        </thead>
        <tbody class="player-profile-tbody"></tbody>
      </table>
    </div>
  `;
  results.appendChild(card);

  const tbody = card.querySelector('.player-profile-tbody');

  for (const eid of [1077, 1076, 1075, 1074, 1073]) {
    const enc = ENCOUNTERS[eid];
    const recs = byEnc[eid];

    if (!recs || recs.length === 0) {
      tbody.insertAdjacentHTML('beforeend',
        `<tr><td><strong>${enc.name}</strong></td><td class="no-data" colspan="6">—</td></tr>`);
      continue;
    }

    const primary = recs[0];
    const extras  = recs.slice(1);
    const groupId = `grp-${eid}`;

    let statusHtml;
    if (primary.is_clear) {
      statusHtml = `<span class="status-clear">✓ 已通關</span>`;
    } else {
      const pctStr = eid === 1073
        ? ucobWipeHpStr(primary.boss_hp_pct)
        : (wipeProgressStr(eid, primary.boss_hp_pct) ?? `${(100 - primary.boss_hp_pct).toFixed(1)}%`);
      statusHtml   = `<span class="status-wipe">✗ 最佳進度 ${pctStr}</span>`;
    }
    const expandHtml = extras.length > 0
      ? ` <button class="expand-btn" data-group="${groupId}" data-expanded="">▼</button>`
      : '';
    const rdpsHtml = primary.rdps > 0 ? `<span class="rdps-val">${primary.rdps.toFixed(1)}</span>` : '—';
    const killHtml = `<span class="kill-count" style="color:${primary.kills > 0 ? '#f4f4f5' : '#52525b'}">${primary.kills}</span>`;

    const rankHtml = rankPctBadge(primary.rank, primary.rankTotal, primary.job);
    tbody.insertAdjacentHTML('beforeend', `
      <tr>
        <td><strong>${enc.name}</strong></td>
        <td>${statusHtml}${expandHtml}</td>
        <td>${jobChip(primary.job)}</td>
        <td>${rdpsHtml}</td>
        <td>${rankHtml}</td>
        <td>${killHtml}</td>
        <td>${fmtDate(primary.timestamp_ms)}</td>
      </tr>`);

    for (const rec of extras) {
      let s2;
      if (rec.is_clear) {
        s2 = `<span class="status-clear">✓ 已通關</span>`;
      } else {
        const pctStr2 = eid === 1073
          ? ucobWipeHpStr(rec.boss_hp_pct)
          : (wipeProgressStr(eid, rec.boss_hp_pct) ?? `${(100 - rec.boss_hp_pct).toFixed(1)}%`);
        s2 = `<span class="status-wipe">✗ 最佳進度 ${pctStr2}</span>`;
      }
      const r2  = rec.rdps > 0 ? `<span class="rdps-val">${rec.rdps.toFixed(1)}</span>` : '—';
      const rk2 = rankPctBadge(rec.rank, rec.rankTotal, rec.job);
      tbody.insertAdjacentHTML('beforeend', `
        <tr class="extra-job-row hidden" data-group="${groupId}">
          <td></td>
          <td>${s2}</td>
          <td>${jobChip(rec.job)}</td>
          <td>${r2}</td>
          <td>${rk2}</td>
          <td>—</td>
          <td>${fmtDate(rec.timestamp_ms)}</td>
        </tr>`);
    }
  }

  tbody.addEventListener('click', e => {
    const btn = e.target.closest('.expand-btn');
    if (!btn) return;
    const group = btn.dataset.group;
    const rows = tbody.querySelectorAll(`tr[data-group="${group}"]`);
    const isExpanded = btn.dataset.expanded === 'true';
    rows.forEach(r => r.classList.toggle('hidden', isExpanded));
    btn.dataset.expanded = isExpanded ? '' : 'true';
    btn.textContent = isExpanded ? '▼' : '▲';
  });
}

function renderDisambig(matches) {
  const results = $id('player-results');
  results.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'disambig-list';
  for (const m of matches) {
    const btn = document.createElement('button');
    btn.className = 'disambig-btn';
    btn.textContent = `${m.name}@${m.server}`;
    btn.onclick = () => renderPlayerProfile(m.name, m.server);
    wrap.appendChild(btn);
  }
  results.appendChild(wrap);
}

// ── Event Wiring ──────────────────────────────────────────────────────────────

function wireMainNav() {
  document.querySelectorAll('.nav-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      STATE.mainTab = btn.dataset.tab;
      setActive(document, '.nav-tab', btn);
      document.querySelectorAll('.tab-section').forEach(s => s.classList.add('hidden'));
      $id(`tab-${STATE.mainTab}`).classList.remove('hidden');
    });
  });
}

function wireLbTypeTabs() {
  $id('lb-type-tabs').addEventListener('click', e => {
    const btn = e.target.closest('.sub-tab');
    if (!btn) return;
    STATE.lbType = btn.dataset.lbtype;
    setActive($id('lb-type-tabs'), '.sub-tab', btn);

    const isSpeed = STATE.lbType === 'speed';
    $id('rdps-section').classList.toggle('hidden', isSpeed);
    $id('speed-section').classList.toggle('hidden', !isSpeed);

    if (isSpeed) renderClearSpeed();
  });
}

function wireRdpsEncFilter() {
  $id('rdps-enc-filter').addEventListener('click', e => {
    const btn = e.target.closest('.filter-btn');
    if (!btn) return;
    STATE.rdpsEncounter = parseInt(btn.dataset.enc, 10);
    STATE.rdpsPage = 1;
    STATE.job = null;
    setActive($id('rdps-enc-filter'), '.filter-btn', btn);
    renderJobFilter();
    renderLeaderboard();
  });
}

function wireRoleTabs() {
  $id('role-tabs').addEventListener('click', e => {
    const btn = e.target.closest('.role-tab');
    if (!btn) return;
    STATE.role = btn.dataset.role;
    STATE.rdpsPage = 1;
    STATE.job = null;
    setActive($id('role-tabs'), '.role-tab', btn);
    renderJobFilter();
    renderLeaderboard();
  });
}

function wireSpeedEncFilter() {
  $id('speed-enc-filter').addEventListener('click', e => {
    const btn = e.target.closest('.filter-btn');
    if (!btn) return;
    STATE.speedEncounter = btn.dataset.enc ? parseInt(btn.dataset.enc, 10) : null;
    STATE.speedPage = 1;
    setActive($id('speed-enc-filter'), '.filter-btn', btn);
    renderClearSpeed();
  });
}

function goToPlayerProfile(name, server) {
  returnSnapshot = {
    mainTab:       STATE.mainTab,
    lbType:        STATE.lbType,
    rdpsEncounter: STATE.rdpsEncounter,
    speedEncounter: STATE.speedEncounter,
    role:          STATE.role,
    job:           STATE.job,
    rdpsPage:      STATE.rdpsPage,
    speedPage:     STATE.speedPage,
  };

  STATE.mainTab = 'player';
  document.querySelectorAll('.nav-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === 'player');
  });
  document.querySelectorAll('.tab-section').forEach(s => s.classList.add('hidden'));
  $id('tab-player').classList.remove('hidden');
  $id('player-input').value = name;
  renderPlayerProfile(name, server);

  $id('return-bar').classList.remove('hidden');
}

function wireLeaderboardRowClick() {
  $id('rdps-tbody').addEventListener('click', e => {
    const row = e.target.closest('tr.lb-row');
    if (!row) return;
    goToPlayerProfile(row.dataset.name, row.dataset.server);
  });
}

function wireSpeedPlayerClick() {
  $id('speed-tbody').addEventListener('click', e => {
    const sp = e.target.closest('.team-player-link');
    if (!sp) return;
    goToPlayerProfile(sp.dataset.name, sp.dataset.srv);
  });
}

function wireReturnBtn() {
  $id('return-btn').addEventListener('click', () => {
    if (!returnSnapshot) return;
    Object.assign(STATE, returnSnapshot);
    returnSnapshot = null;

    $id('return-bar').classList.add('hidden');

    document.querySelectorAll('.nav-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === STATE.mainTab);
    });
    document.querySelectorAll('.tab-section').forEach(s => s.classList.add('hidden'));
    $id(`tab-${STATE.mainTab}`).classList.remove('hidden');

    const isSpeed = STATE.lbType === 'speed';
    document.querySelectorAll('#lb-type-tabs .sub-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.lbtype === STATE.lbType);
    });
    $id('rdps-section').classList.toggle('hidden', isSpeed);
    $id('speed-section').classList.toggle('hidden', !isSpeed);

    setActive($id('rdps-enc-filter'), '.filter-btn',
      $id('rdps-enc-filter').querySelector(`[data-enc="${STATE.rdpsEncounter}"]`));
    setActive($id('role-tabs'), '.role-tab',
      $id('role-tabs').querySelector(`[data-role="${STATE.role}"]`));

    renderJobFilter();
    if (isSpeed) renderClearSpeed(); else renderLeaderboard();
  });
}

function wirePlayerSearch() {
  const input = $id('player-input');
  const btn   = $id('search-btn');

  function doSearch() {
    const q = input.value.trim();
    if (!q) return;
    returnSnapshot = null;
    $id('return-bar').classList.add('hidden');
    const matches = DS.searchPlayer(q);
    if (matches.length === 0) {
      $id('player-results').innerHTML = `<div class="empty-state">找不到玩家「${esc(q)}」</div>`;
    } else if (matches.length === 1) {
      renderPlayerProfile(matches[0].name, matches[0].server);
    } else {
      renderDisambig(matches);
    }
  }

  btn.addEventListener('click', doSearch);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────

async function init() {
  wireMainNav();
  wireLbTypeTabs();
  wireRdpsEncFilter();
  wireRoleTabs();
  wireSpeedEncFilter();
  wirePlayerSearch();
  wireLeaderboardRowClick();
  wireSpeedPlayerClick();
  wireReturnBtn();

  try {
    await DS.loadAll();
    const metaEl = $id('header-meta');
    if (metaEl) {
      const t = DS.meta?.updated_at ?? '—';
      metaEl.textContent = `更新時間：${t}`;
    }
    renderJobFilter();
    renderLeaderboard();
  } catch (err) {
    console.error('Failed to load data:', err);
    document.querySelector('main').innerHTML =
      `<div class="empty-state" style="margin-top:4rem">⚠ 無法載入資料，請確認 data/ 目錄內有 JSON 檔案。<br><small>${esc(String(err))}</small></div>`;
  }
}

document.addEventListener('DOMContentLoaded', init);
