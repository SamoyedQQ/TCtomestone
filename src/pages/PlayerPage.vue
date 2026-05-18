<script setup>
import { ref, computed, reactive, watch } from 'vue'
import { JOBS } from '../domain/jobs.js'
import { fmtDps, fmtDuration, fmtDate } from '../utils/format.js'

const props = defineProps({ app: Object })

const selectedJob = ref(null)
const expandedCards = reactive(new Set())

const IMG_BASE = import.meta.env.DEV ? '/docs/img' : `${import.meta.env.BASE_URL}img`
function jobIcon(job) { return `${IMG_BASE}/jobs/${job.toLowerCase()}.png` }

watch(() => props.app.playerName.value, () => {
  selectedJob.value = null
  expandedCards.clear()
})

function hexRgb(hex) {
  if (!hex) return '128,128,128'
  const r = parseInt(hex.slice(1,3),16)
  const g = parseInt(hex.slice(3,5),16)
  const b = parseInt(hex.slice(5,7),16)
  return `${r},${g},${b}`
}

function fmtPhase(row) {
  if (row.phase_reached > 0) return `P${row.phase_reached}`
  if (row.boss_hp_pct > 0) return `${row.boss_hp_pct.toFixed(1)}%`
  return '—'
}

function prClass(pct) {
  if (pct === 100) return 'pr-gold'
  if (pct >= 99)  return 'pr-pink'
  if (pct >= 95)  return 'pr-orange'
  if (pct >= 75)  return 'pr-purple'
  if (pct >= 50)  return 'pr-blue'
  if (pct >= 30)  return 'pr-green'
  return 'pr-gray'
}

const ROLE_ORDER = ['Tank', 'Healer', 'Melee', 'Ranged', 'Caster']

const allJobs = computed(() => {
  if (!props.app.playerProfile.value) return []
  const seen = new Set()
  for (const { jobBests } of props.app.playerProfile.value.encounters) {
    for (const jb of jobBests) seen.add(jb.job)
  }
  return [...seen].sort((a, b) =>
    ROLE_ORDER.indexOf(JOBS[a]?.role ?? '') - ROLE_ORDER.indexOf(JOBS[b]?.role ?? '')
  )
})

const backLabel = computed(() =>
  props.app.prevPage.value === 'speed' ? '通關速度' : '排行榜'
)

// 取得此副本要顯示的列。null = 此職業無紀錄（顯示提示）
function getRows(encId, best, jobBests) {
  if (selectedJob.value) {
    const jb = jobBests.find(j => j.job === selectedJob.value)
    return jb ? [jb] : null
  }
  if (!best.is_clear) return null  // 未通關另外用 wipe 模板
  return expandedCards.has(encId) ? jobBests : [jobBests[0]]
}
</script>

<template>
  <div class="player-page">

    <!-- 搜尋結果列表 -->
    <div v-if="!app.playerName.value && app.searchResults.value.length" style="margin-bottom:16px">
      <div style="font-size:0.82rem;color:var(--text-2);margin-bottom:10px">找到 {{ app.searchResults.value.length }} 位玩家</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        <button
          v-for="p in app.searchResults.value"
          :key="`${p.name}@${p.server}`"
          class="role-btn"
          :style="{ '--role-color': 'var(--accent-text)', '--role-rgb': '196,181,253' }"
          @click="app.openPlayer(p.name, p.server)"
        >{{ p.name }} <span style="opacity:.55">@{{ p.server }}</span></button>
      </div>
    </div>

    <!-- 玩家個人資料 -->
    <template v-if="app.playerName.value">
      <div style="margin-bottom:16px">
        <button
          class="role-btn"
          :style="{ '--role-color': 'var(--text-2)', '--role-rgb': '122,122,152' }"
          @click="app.goBack()"
        >← 返回{{ backLabel }}</button>
      </div>

      <div v-if="app.loading.value" class="status-msg">載入中…</div>

      <template v-else-if="app.playerProfile.value">

        <!-- 名稱 + 職業篩選 -->
        <div class="profile-header">
          <div>
            <div class="profile-name">{{ app.playerName.value }}</div>
            <div class="profile-server">@{{ app.playerServer.value }}</div>
          </div>
          <div v-if="allJobs.length > 1" class="profile-job-filter">
            <button
              class="pjf-btn"
              :class="{ active: !selectedJob }"
              @click="selectedJob = null"
            >全部</button>
            <button
              v-for="job in allJobs"
              :key="job"
              class="pjf-btn"
              :class="{ active: selectedJob === job }"
              :style="{ '--jc': JOBS[job]?.color ?? 'var(--text-2)', '--jc-rgb': hexRgb(JOBS[job]?.color) }"
              @click="selectedJob = job"
            >
              <img :src="jobIcon(job)" class="pjf-icon" alt="" />
              {{ JOBS[job]?.abbr ?? job }}
            </button>
          </div>
        </div>

        <!-- 副本卡片 -->
        <div class="profile-sections">
          <div
            v-for="{ enc, best, jobBests } in app.playerProfile.value.encounters"
            :key="enc.id"
            class="profile-card"
          >
            <!-- 卡片標頭 -->
            <div class="profile-card__header">
              <span class="enc-dot" :style="{ background: enc.color }"></span>
              <span class="profile-card__title">{{ enc.name }}</span>
              <span
                class="badge-clear"
                :style="best.is_clear
                  ? { background:'rgba(52,211,153,0.12)', color:'#34d399' }
                  : { background:'rgba(255,255,255,0.06)', color:'var(--text-2)' }"
              >{{ best.is_clear ? '通關' : `最佳進度：${fmtPhase(best)}` }}</span>
              <button
                v-if="!selectedJob && jobBests.length > 1"
                class="expand-btn"
                @click="expandedCards.has(enc.id) ? expandedCards.delete(enc.id) : expandedCards.add(enc.id)"
              >{{ expandedCards.has(enc.id) ? '收合 ▲' : '展開 ▼' }}</button>
            </div>

            <!-- 通關資料列（篩選模式 or 展開/收合） -->
            <template v-if="best.is_clear || selectedJob">
              <template v-if="getRows(enc.id, best, jobBests) !== null">
                <div
                  v-for="(jb, i) in getRows(enc.id, best, jobBests)"
                  :key="jb.job"
                  class="profile-stats-grid"
                  :class="{ 'psg-sep': i > 0 }"
                >
                  <div class="psg-cell">
                    <span class="psg-label">排名</span>
                    <span class="psg-value psg-rank">{{ jb.jobRank ? '#' + jb.jobRank : '—' }}</span>
                  </div>
                  <div class="psg-cell">
                    <span class="psg-label">繁中PR% <i class="col-hint" :data-tip="`繁中服同職業通關百分位排名（100 = 第一名）。資料量少時僅供參考。${jb.jobTotal && jb.jobRank ? '\n' + jb.jobTotal + '筆數據中的 #' + jb.jobRank : ''}`">?</i></span>
                    <span class="psg-value" :class="jb.jobParsePct != null ? prClass(jb.jobParsePct) : 'psg-muted'">
                      {{ jb.jobParsePct != null ? jb.jobParsePct : '—' }}
                    </span>
                  </div>
                  <div class="psg-cell">
                    <span class="psg-label">職業</span>
                    <span class="psg-value psg-job" :style="{ color: JOBS[jb.job]?.color ?? 'var(--text)' }">
                      <img :src="jobIcon(jb.job)" class="psg-job-icon" alt="" />
                      {{ JOBS[jb.job]?.abbr ?? jb.job }}
                    </span>
                  </div>
                  <div class="psg-cell">
                    <span class="psg-label">rDPS <i class="col-hint" data-tip="隊伍貢獻傷害：你的傷害扣除他人Buff加成，再加上你的Buff使隊友額外造成的傷害。">?</i></span>
                    <span class="psg-value">{{ fmtDps(jb.rdps) }}</span>
                  </div>
                  <div class="psg-cell">
                    <span class="psg-label">aDPS <i class="col-hint" data-tip="調整後傷害：扣除占星牌等特定單體Buff後的輸出，但保留AOE團輔影響。">?</i></span>
                    <span class="psg-value psg-muted">{{ fmtDps(jb.adps) }}</span>
                  </div>
                  <div class="psg-cell">
                    <span class="psg-label">時間</span>
                    <span class="psg-value psg-muted">{{ fmtDuration(jb.duration_ms) }}</span>
                  </div>
                  <div class="psg-cell">
                    <span class="psg-label">紀錄日期</span>
                    <span class="psg-value psg-muted">{{ fmtDate(jb.timestamp_ms) }}</span>
                  </div>
                  <div class="psg-cell">
                    <span class="psg-label">報告</span>
                    <a
                      v-if="jb.report_code"
                      class="psg-value psg-link"
                      :href="`https://www.fflogs.com/reports/${jb.report_code}#fight=${jb.fight_id}`"
                      target="_blank" rel="noopener"
                    >↗ FFLogs</a>
                    <span v-else class="psg-value psg-muted">—</span>
                  </div>
                </div>
              </template>
              <!-- 篩選職業在此副本無紀錄 -->
              <div v-else class="psg-no-record">此職業無紀錄</div>
            </template>

            <!-- 未通關（最佳推進紀錄） -->
            <template v-else>
              <div class="profile-stats-grid">
                <div class="psg-cell"><span class="psg-label">排名</span><span class="psg-value psg-muted">—</span></div>
                <div class="psg-cell"><span class="psg-label">繁中PR%</span><span class="psg-value psg-muted">—</span></div>
                <div class="psg-cell">
                  <span class="psg-label">職業</span>
                  <span class="psg-value psg-job" :style="{ color: JOBS[best.job]?.color ?? 'var(--text)' }">
                    <img :src="jobIcon(best.job)" class="psg-job-icon" alt="" />
                    {{ JOBS[best.job]?.abbr ?? best.job }}
                  </span>
                </div>
                <div class="psg-cell"><span class="psg-label">rDPS</span><span class="psg-value psg-muted">—</span></div>
                <div class="psg-cell"><span class="psg-label">aDPS</span><span class="psg-value psg-muted">—</span></div>
                <div class="psg-cell"><span class="psg-label">時間</span><span class="psg-value psg-muted">{{ fmtDuration(best.duration_ms) }}</span></div>
                <div class="psg-cell"><span class="psg-label">紀錄日期</span><span class="psg-value psg-muted">{{ fmtDate(best.timestamp_ms) }}</span></div>
                <div class="psg-cell">
                  <span class="psg-label">報告</span>
                  <a
                    v-if="best.report_code"
                    class="psg-value psg-link"
                    :href="`https://www.fflogs.com/reports/${best.report_code}#fight=${best.fight_id}`"
                    target="_blank" rel="noopener"
                  >↗ FFLogs</a>
                  <span v-else class="psg-value psg-muted">—</span>
                </div>
              </div>
            </template>

          </div>
        </div>
      </template>

      <div v-else class="status-msg">找不到此玩家的紀錄</div>
    </template>

  </div>
</template>
