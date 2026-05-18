import { ref, computed, reactive } from 'vue'
import { ENCOUNTERS, PLAYER_ENCOUNTERS, DEFAULT_EID } from '../domain/encounters.js'
import { JOBS } from '../domain/jobs.js'
import { DATA_URL } from '../utils/dataUrl.js'

const PER_PAGE = 30

// ── 資料快取 ────────────────────────────────────────────────
const cache = reactive({
  meta: null,
  lb: {},    // eid → array
  cl: {},    // eid → array
  playersIdx: null,
})

async function fetchJson(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${url}`)
  return res.json()
}

// ── 主 composable ────────────────────────────────────────────
export function useApp() {
  // ── state
  const page      = ref('leaderboard')  // 'leaderboard' | 'speed' | 'player'
  const prevPage  = ref('leaderboard')
  const eid       = ref(DEFAULT_EID)
  const role      = ref(null)           // null = 全職業
  const job       = ref(null)
  const server    = ref('')
  const lbPage    = ref(1)
  const spPage    = ref(1)
  const loading   = ref(false)
  const error     = ref(null)

  // player search
  const query          = ref('')
  const playerName     = ref(null)
  const playerServer   = ref(null)
  const searchResults  = ref([])

  // meta
  const updatedAt = ref('')

  // ── 資料載入
  async function loadMeta() {
    if (cache.meta) { updatedAt.value = cache.meta.updated_at; return }
    try {
      cache.meta = await fetchJson(DATA_URL.meta)
      updatedAt.value = cache.meta.updated_at
    } catch { /* non-critical */ }
  }

  async function loadEncounter(id) {
    if (cache.lb[id]) return
    loading.value = true
    error.value   = null
    try {
      const [lb, cl] = await Promise.all([
        fetchJson(DATA_URL.leaderboard(id)),
        fetchJson(DATA_URL.clears(id)),
      ])
      cache.lb[id] = lb
      cache.cl[id] = cl
    } catch (e) {
      error.value = `載入副本資料失敗：${e.message}`
    } finally {
      loading.value = false
    }
  }

  async function loadPlayersIndex() {
    if (cache.playersIdx) return
    try { cache.playersIdx = await fetchJson(DATA_URL.playersIndex) } catch { /* ok */ }
  }

  // ── 切副本
  async function selectEncounter(id) {
    eid.value   = id
    role.value  = null
    job.value   = null
    lbPage.value = 1
    spPage.value = 1
    await loadEncounter(id)
  }

  // ── 切頁
  function setPage(tab) {
    if (tab === 'player' && page.value !== 'player') prevPage.value = page.value
    page.value = tab
    if (tab === 'player') loadPlayersIndex()
  }

  function goBack() {
    playerName.value = null
    playerServer.value = null
    page.value = prevPage.value
  }

  // ── 排行榜資料（過濾 + 分頁）
  const rawLb = computed(() => cache.lb[eid.value] ?? [])

  const filteredLb = computed(() => {
    let rows = rawLb.value.filter(r => r.is_clear)  // 只顯示通關

    if (role.value) rows = rows.filter(r => JOBS[r.job]?.role === role.value)
    if (job.value)  rows = rows.filter(r => r.job === job.value)
    if (server.value) rows = rows.filter(r => r.server === server.value)

    // 依 rDPS 排序
    rows = [...rows].sort((a, b) => (b.rdps ?? 0) - (a.rdps ?? 0))

    // 每位玩家同職業只保留最高分（防重複紀錄）
    const seen = new Set()
    rows = rows.filter(r => {
      const key = `${r.name}@${r.server}:${r.job}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })

    return rows
  })

  const lbTotal     = computed(() => filteredLb.value.length)
  const lbTotalPages = computed(() => Math.max(1, Math.ceil(lbTotal.value / PER_PAGE)))
  const lbRows       = computed(() => {
    const s = (lbPage.value - 1) * PER_PAGE
    return filteredLb.value.slice(s, s + PER_PAGE)
  })
  const lbStart = computed(() => lbRows.value.length ? (lbPage.value - 1) * PER_PAGE + 1 : 0)
  const lbEnd   = computed(() => (lbPage.value - 1) * PER_PAGE + lbRows.value.length)

  // ── 速刷排行
  const rawCl = computed(() => cache.cl[eid.value] ?? [])

  const sortedClears = computed(() => {
    const seen = new Set()
    return [...rawCl.value]
      .filter(c => c.duration_ms > 0)
      .sort((a, b) => a.duration_ms - b.duration_ms)
      .filter(c => {
        const key = [...c.players].sort().join('|')
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })
  })

  const spTotal      = computed(() => sortedClears.value.length)
  const spTotalPages = computed(() => Math.max(1, Math.ceil(spTotal.value / PER_PAGE)))
  const spRows       = computed(() => {
    const s = (spPage.value - 1) * PER_PAGE
    return sortedClears.value.slice(s, s + PER_PAGE)
  })
  const spStart = computed(() => spRows.value.length ? (spPage.value - 1) * PER_PAGE + 1 : 0)
  const spEnd   = computed(() => (spPage.value - 1) * PER_PAGE + spRows.value.length)

  // ── 可用職業（目前副本 + 職能篩選後）
  const availableJobs = computed(() => {
    let rows = rawLb.value.filter(r => r.is_clear)
    if (role.value) rows = rows.filter(r => JOBS[r.job]?.role === role.value)
    return [...new Set(rows.map(r => r.job))]
  })

  // ── 伺服器清單
  const servers = computed(() =>
    [...new Set(rawLb.value.map(r => r.server))].sort()
  )

  // ── 玩家搜尋
  async function searchPlayers() {
    await loadPlayersIndex()
    const q = query.value.trim().toLowerCase()
    if (!q || !cache.playersIdx) { searchResults.value = []; return }
    searchResults.value = cache.playersIdx
      .filter(p => p.name.toLowerCase().includes(q) || `${p.name}@${p.server}`.toLowerCase().includes(q))
      .slice(0, 30)
  }

  // ── 玩家個人資料（從 leaderboard 快取撈）
  const playerProfile = computed(() => {
    if (!playerName.value) return null
    const key = `${playerName.value}@${playerServer.value}`
    const result = []

    for (const enc of PLAYER_ENCOUNTERS) {
      const rows = (cache.lb[enc.id] ?? []).filter(r => `${r.name}@${r.server}` === key)
      if (!rows.length) continue

      const clears = rows.filter(r => r.is_clear)
      const best = clears.length
        ? clears.reduce((a, b) => (b.rdps ?? 0) > (a.rdps ?? 0) ? b : a)
        : rows.reduce((a, b) => ((a.boss_hp_pct ?? 100) <= (b.boss_hp_pct ?? 100) ? a : b))

      // 各職業最佳通關，含各職排名與 TC PR%
      const jobMap = new Map()
      for (const r of clears) {
        if (!jobMap.has(r.job) || (r.rdps ?? 0) > (jobMap.get(r.job).rdps ?? 0)) jobMap.set(r.job, r)
      }
      const jobBests = [...jobMap.values()].sort((a, b) => (b.rdps ?? 0) - (a.rdps ?? 0)).map(jb => {
        const seen2 = new Set()
        const jr = [...(cache.lb[enc.id] ?? [])]
          .filter(r => r.is_clear && r.job === jb.job)
          .sort((a, b) => (b.rdps ?? 0) - (a.rdps ?? 0))
          .filter(r => { const k = `${r.name}@${r.server}`; if (seen2.has(k)) return false; seen2.add(k); return true })
        const ji = jr.findIndex(r => r.name === playerName.value && r.server === playerServer.value)
        const jRank = ji !== -1 ? ji + 1 : null
        const jTotal = jr.length
        const jPct = jRank === 1 ? 100 : (jRank && jTotal > 1 ? Math.min(99, Math.round(((jTotal - jRank) / jTotal) * 100)) : null)
        return { ...jb, jobRank: jRank, jobParsePct: jPct }
      }).sort((a, b) => (b.jobParsePct ?? -1) - (a.jobParsePct ?? -1) || (b.rdps ?? 0) - (a.rdps ?? 0))

      result.push({
        enc, best, all: rows, jobBests,
        rank:     jobBests[0]?.jobRank     ?? null,
        parsePct: jobBests[0]?.jobParsePct ?? null,
      })
    }
    return result.length ? { name: playerName.value, server: playerServer.value, encounters: result } : null
  })

  async function openPlayer(name, srv) {
    if (page.value !== 'player') prevPage.value = page.value
    playerName.value   = name
    playerServer.value = srv
    page.value         = 'player'

    // 確保所有副本資料都已載入（才能顯示完整個人資料）
    await Promise.all(ENCOUNTERS.map(e => loadEncounter(e.id)))
  }

  // ── init
  async function init() {
    await Promise.all([loadMeta(), loadEncounter(DEFAULT_EID)])
  }

  return {
    // state
    page, eid, role, job, server,
    lbPage, spPage, loading, error,
    query, playerName, playerServer, searchResults, updatedAt,

    // computed
    rawLb, rawCl,
    filteredLb, lbRows, lbTotal, lbTotalPages, lbStart, lbEnd,
    spRows, spTotal, spTotalPages, spStart, spEnd,
    sortedClears, availableJobs, servers, playerProfile,

    // actions
    init, setPage, selectEncounter,
    searchPlayers, openPlayer, goBack,
    prevPage,
  }
}
