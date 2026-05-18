<script setup>
import { JOBS } from '../domain/jobs.js'
import { fmtDuration, fmtDate } from '../utils/format.js'

const props = defineProps({ app: Object })

const JOB_IMG_BASE = import.meta.env.DEV ? '/docs/img/jobs' : '/img/jobs'
const jobIcon = (name) => name ? `${JOB_IMG_BASE}/${name.toLowerCase()}.png` : ''

function hexRgb(hex) {
  if (!hex) return '128,128,128'
  const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16)
  return `${r},${g},${b}`
}

const ROLE_ORDER = ['Tank', 'Healer', 'Melee', 'Ranged', 'Caster']
function sortedPlayers(row) {
  return [...row.players].sort((a, b) => {
    const ra = ROLE_ORDER.indexOf(JOBS[row.jobs?.[a]]?.role ?? '')
    const rb = ROLE_ORDER.indexOf(JOBS[row.jobs?.[b]]?.role ?? '')
    return ra - rb
  })
}
</script>

<template>
  <div class="table-wrap">
    <div v-if="app.loading.value"  class="status-msg">載入中…</div>
    <div v-else-if="app.error.value"   class="status-msg error">{{ app.error.value }}</div>
    <div v-else-if="!app.spRows.value.length" class="status-msg">目前沒有速刷資料</div>

    <template v-else>
      <table>
        <thead>
          <tr>
            <th style="width:48px">#</th>
            <th class="num">通關時長</th>
            <th class="num">紀錄日期</th>
            <th>成員</th>
            <th class="num">報告</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in app.spRows.value" :key="`${row.code}-${row.fight_id}`">
            <td class="rank-cell" :class="i===0?'rank-1':i===1?'rank-2':i===2?'rank-3':'rank-n'">
              #{{ (app.spPage.value - 1) * 30 + i + 1 }}
            </td>
            <td class="td-num" style="font-weight:600;letter-spacing:-0.01em">
              {{ fmtDuration(row.duration_ms) }}
            </td>
            <td class="td-num" style="color:var(--text-2);font-size:0.78rem">
              {{ fmtDate(row.clear_dt_ms) }}
            </td>
            <td>
              <div class="team-list">
                <button
                  v-for="player in sortedPlayers(row)"
                  :key="player"
                  class="team-member team-member--btn"
                  :style="{
                    background: `rgba(${hexRgb(JOBS[row.jobs?.[player]]?.color)}, 0.12)`,
                    color: JOBS[row.jobs?.[player]]?.color ?? 'var(--text-2)',
                  }"
                  @click="app.openPlayer(player.split('@')[0], player.split('@')[1])"
                >
                  <img
                    :src="jobIcon(row.jobs?.[player])"
                    :alt="row.jobs?.[player]"
                    @error="$event.target.style.display='none'"
                  />
                  {{ player.split('@')[0] }}
                </button>
              </div>
            </td>
            <td class="td-num">
              <a
                v-if="row.code"
                class="report-link"
                :href="`https://www.fflogs.com/reports/${row.code}#fight=${row.fight_id}`"
                target="_blank"
                rel="noopener"
              >↗</a>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="pagination">
        <span class="page-info">顯示 {{ app.spStart.value }} - {{ app.spEnd.value }} 名，共 {{ app.spTotal.value }} 筆</span>
        <div class="page-controls">
          <button class="page-btn" :disabled="app.spPage.value <= 1" @click="app.spPage.value--">上一頁</button>
          <span class="page-cur">{{ app.spPage.value }} / {{ app.spTotalPages.value }}</span>
          <button class="page-btn" :disabled="app.spPage.value >= app.spTotalPages.value" @click="app.spPage.value++">下一頁</button>
        </div>
      </div>
    </template>
  </div>
</template>
