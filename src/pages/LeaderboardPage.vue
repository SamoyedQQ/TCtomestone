<script setup>
import { computed } from 'vue'
import { ROLES, JOBS, jobsByRole } from '../domain/jobs.js'
import { ENCOUNTER_MAP } from '../domain/encounters.js'
import { fmtDps, fmtDuration, fmtDate, fmtRank } from '../utils/format.js'

const props = defineProps({ app: Object })

const enc = computed(() => ENCOUNTER_MAP[props.app.eid.value])

// 圖示路徑：docs/img/jobs/ 的檔名皆為小寫
const JOB_IMG_BASE = import.meta.env.DEV ? `${import.meta.env.BASE_URL}docs/img/jobs` : `${import.meta.env.BASE_URL}img/jobs`
const jobIcon = (name) => name ? `${JOB_IMG_BASE}/${name.toLowerCase()}.png` : ''

function hexRgb(hex) {
  if (!hex || hex.length < 7) return '128,128,128'
  const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16)
  return `${r},${g},${b}`
}

function selectRole(r) {
  props.app.role.value = props.app.role.value === r ? null : r
  props.app.job.value  = null
  props.app.lbPage.value = 1
}

function selectJob(j) {
  props.app.job.value = props.app.job.value === j ? null : j
  props.app.lbPage.value = 1
}

function rankClass(i) {
  const n = (props.app.lbPage.value - 1) * 30 + i + 1
  if (n === 1) return 'rank-1'
  if (n === 2) return 'rank-2'
  if (n === 3) return 'rank-3'
  return 'rank-n'
}
function globalRank(i) { return (props.app.lbPage.value - 1) * 30 + i + 1 }

const showableJobs = computed(() => {
  if (!props.app.role.value) return []
  return jobsByRole(props.app.role.value).filter(j => props.app.availableJobs.value.includes(j.name))
})
</script>

<template>
  <!-- 職能篩選 -->
  <div class="filter-bar">
    <span class="filter-label">職能</span>
    <button
      v-for="r in ROLES"
      :key="r.id"
      class="role-btn"
      :class="{ active: app.role.value === r.id }"
      :style="{ '--role-color': r.color, '--role-rgb': hexRgb(r.color) }"
      @click="selectRole(r.id)"
    >{{ r.label }}</button>

    <template v-if="app.servers.value.length > 1">
      <span style="margin-left:4px" class="filter-label">伺服器</span>
      <select class="server-select" v-model="app.server.value" @change="app.lbPage.value=1">
        <option value="">全部</option>
        <option v-for="s in app.servers.value" :key="s" :value="s">{{ s }}</option>
      </select>
    </template>
  </div>

  <!-- 職業 pills -->
  <div class="job-pills" v-if="showableJobs.length">
    <button
      v-for="j in showableJobs"
      :key="j.name"
      class="job-pill"
      :class="{ active: app.job.value === j.name }"
      :style="{ '--job-color': j.color, '--job-rgb': hexRgb(j.color) }"
      @click="selectJob(j.name)"
    >
      <img :src="jobIcon(j.name)" :alt="j.name" style="width:12px;height:12px;object-fit:contain;vertical-align:middle;margin-right:4px" @error="$event.target.style.display='none'" />
      {{ j.abbr }}
    </button>
  </div>

  <!-- 表格 -->
  <div class="table-wrap">
    <div v-if="app.loading.value" class="status-msg">載入排行榜資料中…</div>
    <div v-else-if="app.error.value" class="status-msg error">{{ app.error.value }}</div>
    <div v-else-if="!app.lbRows.value.length" class="status-msg">目前沒有符合條件的紀錄</div>

    <template v-else>
      <div class="pagination pagination--top">
        <span class="page-info">顯示 {{ app.lbStart.value }} - {{ app.lbEnd.value }} 名，共 {{ app.lbTotal.value }} 筆紀錄</span>
        <div class="page-controls">
          <button class="page-btn" :disabled="app.lbPage.value <= 1" @click="app.lbPage.value--">上一頁</button>
          <span class="page-cur">{{ app.lbPage.value }} / {{ app.lbTotalPages.value }}</span>
          <button class="page-btn" :disabled="app.lbPage.value >= app.lbTotalPages.value" @click="app.lbPage.value++">下一頁</button>
        </div>
      </div>

      <table>
        <colgroup>
          <col style="width:48px" />
          <col style="width:18%" />
          <col style="width:10%" />
          <col style="width:10%" />
          <col style="width:10%" />
          <col style="width:10%" />
          <col style="width:10%" />
          <col style="width:9%" />
          <col style="width:48px" />
        </colgroup>
        <thead>
          <tr>
            <th>排名</th>
            <th>玩家名稱</th>
            <th>伺服器</th>
            <th>職業</th>
            <th class="num">rDPS <i class="col-hint" data-tip="隊伍貢獻傷害：你的傷害扣除他人Buff加成，再加上你的Buff使隊友額外造成的傷害。與FFLogs排名所用數值相同。">?</i></th>
            <th class="num">aDPS <i class="col-hint" data-tip="調整後傷害：扣除占星牌等特定單體Buff後的輸出，但保留AOE團輔影響。">?</i></th>
            <th class="num">通關時間</th>
            <th class="num">紀錄日期</th>
            <th class="num">報告</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in app.lbRows.value" :key="`${row.name}@${row.server}:${row.job}`"
            class="lb-row-clickable"
            @click="app.openPlayer(row.name, row.server)">
            <td class="rank-cell" :class="rankClass(i)">{{ fmtRank(globalRank(i)) }}</td>
            <td>
              <span class="player-btn">{{ row.name }}</span>
            </td>
            <td style="color:var(--text-2)">{{ row.server }}</td>
            <td>
              <span
                class="job-chip"
                :style="{
                  background: `rgba(${hexRgb(JOBS[row.job]?.color)}, 0.15)`,
                  color: JOBS[row.job]?.color ?? 'var(--text-2)',
                }"
              >
                <img
                  v-if="JOBS[row.job]"
                  :src="jobIcon(row.job)"
                  :alt="row.job"
                  style="width:14px;height:14px;object-fit:contain;vertical-align:middle;margin-right:4px"
                  @error="$event.target.style.display='none'"
                />{{ JOBS[row.job]?.abbr ?? '未知' }}
              </span>
            </td>
            <td class="td-num">{{ fmtDps(row.rdps) }}</td>
            <td class="td-num" style="color:var(--text-2)">{{ fmtDps(row.adps) }}</td>
            <td class="td-num" style="color:var(--text-2)">{{ fmtDuration(row.duration_ms) }}</td>
            <td class="td-num" style="color:var(--text-2);font-size:0.78rem">{{ fmtDate(row.timestamp_ms) }}</td>
            <td class="td-num" @click.stop>
              <a
                v-if="row.report_code"
                class="report-link"
                :href="`https://www.fflogs.com/reports/${row.report_code}#fight=${row.fight_id}`"
                target="_blank" rel="noopener"
                title="查看 FFLogs 報告"
              >↗ FFLogs</a>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 分頁 -->
      <div class="pagination">
        <span class="page-info">顯示 {{ app.lbStart.value }} - {{ app.lbEnd.value }} 名，共 {{ app.lbTotal.value }} 筆紀錄</span>
        <div class="page-controls">
          <button class="page-btn" :disabled="app.lbPage.value <= 1" @click="app.lbPage.value--">上一頁</button>
          <span class="page-cur">{{ app.lbPage.value }} / {{ app.lbTotalPages.value }}</span>
          <button class="page-btn" :disabled="app.lbPage.value >= app.lbTotalPages.value" @click="app.lbPage.value++">下一頁</button>
        </div>
      </div>
    </template>
  </div>
</template>
