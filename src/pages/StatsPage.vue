<script setup>
import { ref, computed, watch } from 'vue'
import { ROLES, JOBS } from '../domain/jobs.js'
import { fmtDps, fmtDuration } from '../utils/format.js'

const props = defineProps({ app: Object })
const app = props.app

const JOB_IMG_BASE = import.meta.env.DEV ? '/docs/img/jobs' : '/img/jobs'

const metric   = ref('rdps')
const rdpsRole = ref('all')
const speedRole = ref('all')

watch(() => app.eid.value, () => { rdpsRole.value = 'all'; speedRole.value = 'all' })

// ─── Helpers ──────────────────────────────────────────────────────────────

function hexRgb(hex) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `${r}, ${g}, ${b}`
}


function lerp(sorted, p) {
  if (!sorted.length) return 0
  const idx = (p / 100) * (sorted.length - 1)
  const lo = Math.floor(idx), hi = Math.ceil(idx)
  return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo)
}

function boxPlot(values) {
  if (!values.length) return null
  const s = [...values].sort((a, b) => a - b)
  const n = s.length
  const q1 = lerp(s, 25), q2 = lerp(s, 50), q3 = lerp(s, 75)
  const iqr  = q3 - q1
  const fence = 1.5 * iqr
  const wLow  = s.find(v => v >= q1 - fence) ?? s[0]
  const wHigh = [...s].reverse().find(v => v <= q3 + fence) ?? s[n - 1]
  const outliers = s.filter(v => v < wLow || v > wHigh)
  return { min: s[0], max: s[n - 1], q1, q2, q3, wLow, wHigh, outliers, n }
}

function makeTicks(lo, hi, count) {
  if (!lo || !hi || hi <= lo) return []
  const rawStep = (hi - lo) / count
  const mag  = Math.pow(10, Math.floor(Math.log10(rawStep)))
  const step = Math.round(rawStep / mag) * mag || mag
  const ticks = []
  for (let t = Math.ceil(lo / step) * step; t <= hi + step * 0.01; t += step)
    ticks.push(Math.round(t))
  return ticks
}

function makeTimeTicks(lo, hi, count) {
  if (!lo || !hi || hi <= lo) return []
  const rawStep = (hi - lo) / count
  const step = rawStep < 10000 ? 10000 : rawStep < 20000 ? 15000
    : rawStep < 40000 ? 30000 : rawStep < 80000 ? 60000 : 120000
  const ticks = []
  for (let t = Math.ceil(lo / step) * step; t <= hi + step * 0.01; t += step)
    ticks.push(Math.round(t))
  return ticks
}

// ─── rDPS Stats ───────────────────────────────────────────────────────────

const rdpsJobStats = computed(() => {
  const byJob = {}
  for (const r of app.rawLb.value) {
    if (!r.is_clear || !(r.rdps > 0)) continue
    if (!byJob[r.job]) byJob[r.job] = []
    byJob[r.job].push(r.rdps)
  }
  return Object.entries(byJob)
    .map(([job, vals]) => {
      const info = JOBS[job]
      const bp   = info && boxPlot(vals)
      if (!bp) return null
      return { job, role: info.role, abbr: info.abbr, color: info.color, ...bp }
    })
    .filter(Boolean)
    .sort((a, b) => b.q2 - a.q2)
})

const filteredRdpsStats = computed(() =>
  rdpsRole.value === 'all'
    ? rdpsJobStats.value
    : rdpsJobStats.value.filter(s => s.role === rdpsRole.value)
)

const rdpsMin = computed(() => {
  const s = filteredRdpsStats.value
  return s.length ? Math.min(...s.map(x => x.min)) * 0.97 : 0
})

const rdpsMax = computed(() => {
  const s = filteredRdpsStats.value
  return s.length ? Math.max(...s.map(x => x.max)) * 1.03 : 1
})

function rdpsPct(val) {
  const lo = rdpsMin.value, hi = rdpsMax.value
  return hi <= lo ? 50 : Math.max(0, Math.min(100, ((val - lo) / (hi - lo)) * 100))
}

const rdpsTicks = computed(() => makeTicks(rdpsMin.value, rdpsMax.value, 5))
const rdpsTotalRecords = computed(() => filteredRdpsStats.value.reduce((s, j) => s + j.n, 0))

// ─── Speed per-job Stats ──────────────────────────────────────────────────

const speedJobStats = computed(() => {
  const byJob = {}
  for (const clear of app.rawCl.value) {
    if (!clear.duration_ms) continue
    for (const job of Object.values(clear.jobs || {})) {
      if (!byJob[job]) byJob[job] = []
      byJob[job].push(clear.duration_ms)
    }
  }
  return Object.entries(byJob)
    .map(([job, vals]) => {
      const info = JOBS[job]
      const bp   = info && boxPlot(vals)
      if (!bp) return null
      return { job, role: info.role, abbr: info.abbr, color: info.color, ...bp }
    })
    .filter(Boolean)
    .sort((a, b) => a.q2 - b.q2)  // 最快在上
})

const filteredSpeedStats = computed(() =>
  speedRole.value === 'all'
    ? speedJobStats.value
    : speedJobStats.value.filter(s => s.role === speedRole.value)
)

const speedMin = computed(() => {
  const s = filteredSpeedStats.value
  return s.length ? Math.min(...s.map(x => x.min)) * 0.97 : 0
})

const speedMax = computed(() => {
  const s = filteredSpeedStats.value
  return s.length ? Math.max(...s.map(x => x.max)) * 1.03 : 1
})

function speedPct(val) {
  const lo = speedMin.value, hi = speedMax.value
  return hi <= lo ? 50 : Math.max(0, Math.min(100, ((hi - val) / (hi - lo)) * 100))
}

const speedTicks = computed(() => makeTimeTicks(speedMin.value, speedMax.value, 5))
const speedTotalRecords = computed(() => filteredSpeedStats.value.reduce((s, j) => s + j.n, 0))

// Overall speed summary
const speedVals = computed(() =>
  app.rawCl.value.filter(c => c.duration_ms > 0).map(c => c.duration_ms)
)
const speedOverallBp = computed(() => boxPlot(speedVals.value))

// Histogram
const speedHistogram = computed(() => {
  const vals = speedVals.value
  if (!vals.length) return []
  const lo = Math.min(...vals), hi = Math.max(...vals)
  const range = hi - lo
  if (!range) return [{ start: lo, end: lo + 1000, count: vals.length }]
  const rawBucket = range / 16
  const bucketMs = rawBucket < 10000 ? 10000 : rawBucket < 20000 ? 15000
    : rawBucket < 40000 ? 30000 : 60000
  const buckets = {}
  for (const v of vals) {
    const k = Math.floor(v / bucketMs) * bucketMs
    buckets[k] = (buckets[k] || 0) + 1
  }
  const result = []
  for (let k = Math.floor(lo / bucketMs) * bucketMs; k <= Math.floor(hi / bucketMs) * bucketMs; k += bucketMs)
    result.push({ start: k, end: k + bucketMs, count: buckets[k] || 0 })
  return result
})
const histMax = computed(() =>
  speedHistogram.value.length ? Math.max(...speedHistogram.value.map(b => b.count), 1) : 1
)
const histLabelStep = computed(() => Math.max(1, Math.floor(speedHistogram.value.length / 6)))

// ─── Tooltip ──────────────────────────────────────────────────────────────

const tooltip = ref(null)

function showTooltip(stat, event, isSpeed) {
  tooltip.value = { stat, isSpeed, x: event.clientX, y: event.clientY }
}

function moveTooltip(event) {
  if (tooltip.value) {
    tooltip.value.x = event.clientX
    tooltip.value.y = event.clientY
  }
}

function hideTooltip() {
  tooltip.value = null
}
</script>

<template>
  <div class="stats-page" @mousemove="moveTooltip">

    <!-- Sub-metric tabs -->
    <div class="stats-metric-tabs">
      <button class="stats-metric-btn" :class="{active: metric === 'rdps'}" @click="metric = 'rdps'">
        傷害量 rDPS
      </button>
      <button class="stats-metric-btn" :class="{active: metric === 'speed'}" @click="metric = 'speed'">
        通關速度
      </button>
    </div>

    <div v-if="app.loading.value" class="status-msg">載入中…</div>
    <div v-else>

      <!-- ─── rDPS Tab ─────────────────────────────────────────────────── -->
      <template v-if="metric === 'rdps'">
        <div class="filter-bar">
          <button class="role-btn"
            :class="{active: rdpsRole === 'all'}"
            :style="rdpsRole === 'all' ? '--role-color:var(--accent-text);--role-rgb:196,181,253' : ''"
            @click="rdpsRole = 'all'">全部</button>
          <button v-for="role in ROLES" :key="role.id"
            class="role-btn"
            :class="{active: rdpsRole === role.id}"
            :style="rdpsRole === role.id ? `--role-color:${role.color};--role-rgb:${hexRgb(role.color)}` : ''"
            @click="rdpsRole = role.id">{{ role.label }}</button>
        </div>

        <template v-if="filteredRdpsStats.length">
          <div class="stats-chart-wrap">

            <!-- Axis header -->
            <div class="bp-header-row">
              <div class="bp-job-col">職業</div>
              <div class="bp-chart-col">
                <div class="bp-axis-ticks">
                  <span v-for="tick in rdpsTicks" :key="tick"
                    class="bp-tick" :style="{left: rdpsPct(tick)+'%'}">
                    {{ (tick/1000).toFixed(1) }}k
                  </span>
                </div>
              </div>
              <div class="bp-stats-col">中位數 / 樣本</div>
            </div>

            <!-- Job rows -->
            <div v-for="(stat, i) in filteredRdpsStats" :key="stat.job"
              class="bp-row" :class="{alt: i % 2 === 1}"
              @mouseenter="showTooltip(stat, $event, false)"
              @mouseleave="hideTooltip">

              <div class="bp-job-col">
                <img class="bp-job-icon"
                  :src="`${JOB_IMG_BASE}/${stat.job.toLowerCase()}.png`" :alt="stat.abbr"
                  @error="$event.target.style.display='none'" />
                <span class="bp-job-name" :style="{color: stat.color}">{{ stat.abbr }}</span>
              </div>

              <div class="bp-chart-col">
                <div class="bp-track">
                  <div v-for="tick in rdpsTicks" :key="tick"
                    class="bp-grid-line" :style="{left: rdpsPct(tick)+'%'}"></div>
                  <!-- 左鬚臂（wLow → Q1） -->
                  <div class="bp-arm"
                    :style="{left: rdpsPct(stat.wLow)+'%', width: Math.max(0, rdpsPct(stat.q1)-rdpsPct(stat.wLow))+'%', background: stat.color}"></div>
                  <!-- IQR 色塊左半（Q1→Q2） -->
                  <div class="bp-box"
                    :style="{
                      left: rdpsPct(stat.q1)+'%',
                      right: `calc(${100 - rdpsPct(stat.q2)}% + 1px)`,
                      background: stat.color,
                    }"></div>
                  <!-- IQR 色塊右半（Q2→Q3） -->
                  <div class="bp-box"
                    :style="{
                      left: `calc(${rdpsPct(stat.q2)}% + 1px)`,
                      right: (100 - rdpsPct(stat.q3))+'%',
                      background: stat.color,
                    }"></div>
                  <!-- 右鬚臂（Q3 → wHigh） -->
                  <div class="bp-arm"
                    :style="{left: rdpsPct(stat.q3)+'%', width: Math.max(0, rdpsPct(stat.wHigh)-rdpsPct(stat.q3))+'%', background: stat.color}"></div>
                  <!-- 鬚端蓋 -->
                  <div class="bp-cap" :style="{left: rdpsPct(stat.wLow)+'%', background: stat.color}"></div>
                  <div class="bp-cap" :style="{left: rdpsPct(stat.wHigh)+'%', background: stat.color}"></div>
                  <!-- 極端值點 -->
                  <div v-for="(ov, oi) in stat.outliers" :key="oi"
                    class="bp-outlier"
                    :style="{left: rdpsPct(ov)+'%', background: stat.color}"></div>
                </div>
              </div>

              <div class="bp-stats-col">
                <span class="bp-median-val" :style="{color: stat.color}">{{ fmtDps(stat.q2) }}</span>
                <span class="bp-count">n={{ stat.n }}</span>
              </div>
            </div>

            <!-- Legend -->
            <div class="bp-legend">
              <div class="bp-legend-demo">
                <div class="bp-track" style="width:80px;flex-shrink:0">
                  <div class="bp-arm"  style="left:5%;width:23%;background:#6060a0"></div>
                  <div class="bp-box"  style="left:28%;right:calc(51%+1px);background:#6060a0"></div>
                  <div class="bp-box"  style="left:calc(50%+1px);right:28%;background:#6060a0"></div>
                  <div class="bp-arm"  style="left:72%;width:23%;background:#6060a0"></div>
                  <div class="bp-cap"     style="left:5%;background:#6060a0"></div>
                  <div class="bp-cap"     style="left:95%;background:#6060a0"></div>
                  <div class="bp-outlier" style="left:2%;background:#6060a0"></div>
                </div>
              </div>
              <span class="bp-legend-text">鬚 = 1.5×IQR &nbsp;·&nbsp; 箱 = Q1–Q3 &nbsp;·&nbsp; 縫 = 中位數 &nbsp;·&nbsp; 點 = 極端值</span>
              <span class="bp-legend-count">{{ rdpsTotalRecords }} 筆通關 &nbsp;·&nbsp; {{ filteredRdpsStats.length }} 個職業</span>
            </div>
          </div>
        </template>
        <div v-else class="status-msg">此副本尚無通關資料</div>
      </template>

      <!-- ─── Speed Tab ────────────────────────────────────────────────── -->
      <template v-else>
        <template v-if="speedOverallBp && speedOverallBp.n > 0">

          <!-- Summary cards -->
          <div class="speed-summary-grid">
            <div class="speed-stat-card">
              <div class="speed-stat-label">最快</div>
              <div class="speed-stat-value rank-1">{{ fmtDuration(speedOverallBp.min) }}</div>
            </div>
            <div class="speed-stat-card">
              <div class="speed-stat-label">Q1 (25%)</div>
              <div class="speed-stat-value">{{ fmtDuration(speedOverallBp.q1) }}</div>
            </div>
            <div class="speed-stat-card speed-stat-card--hl">
              <div class="speed-stat-label">中位數</div>
              <div class="speed-stat-value">{{ fmtDuration(speedOverallBp.q2) }}</div>
            </div>
            <div class="speed-stat-card">
              <div class="speed-stat-label">Q3 (75%)</div>
              <div class="speed-stat-value">{{ fmtDuration(speedOverallBp.q3) }}</div>
            </div>
            <div class="speed-stat-card">
              <div class="speed-stat-label">最慢</div>
              <div class="speed-stat-value" style="color:var(--text-2)">{{ fmtDuration(speedOverallBp.max) }}</div>
            </div>
            <div class="speed-stat-card">
              <div class="speed-stat-label">通關筆數</div>
              <div class="speed-stat-value">{{ speedOverallBp.n }}</div>
            </div>
          </div>

          <!-- Role filter for speed -->
          <div class="filter-bar" style="margin-top:16px">
            <button class="role-btn"
              :class="{active: speedRole === 'all'}"
              :style="speedRole === 'all' ? '--role-color:var(--accent-text);--role-rgb:196,181,253' : ''"
              @click="speedRole = 'all'">全部</button>
            <button v-for="role in ROLES" :key="role.id"
              class="role-btn"
              :class="{active: speedRole === role.id}"
              :style="speedRole === role.id ? `--role-color:${role.color};--role-rgb:${hexRgb(role.color)}` : ''"
              @click="speedRole = role.id">{{ role.label }}</button>
          </div>

          <!-- Per-job speed chart -->
          <template v-if="filteredSpeedStats.length">
            <div class="stats-chart-wrap">
              <!-- Axis header -->
              <div class="bp-header-row">
                <div class="bp-job-col">職業</div>
                <div class="bp-chart-col">
                  <div class="bp-axis-ticks">
                    <span v-for="tick in speedTicks" :key="tick"
                      class="bp-tick" :style="{left: speedPct(tick)+'%'}">
                      {{ fmtDuration(tick) }}
                    </span>
                  </div>
                </div>
                <div class="bp-stats-col">中位數 / 樣本</div>
              </div>

              <!-- Job rows -->
              <div v-for="(stat, i) in filteredSpeedStats" :key="stat.job"
                class="bp-row" :class="{alt: i % 2 === 1}"
                @mouseenter="showTooltip(stat, $event, true)"
                @mouseleave="hideTooltip">

                <div class="bp-job-col">
                  <img class="bp-job-icon"
                    :src="`${JOB_IMG_BASE}/${stat.job.toLowerCase()}.png`" :alt="stat.abbr"
                    @error="$event.target.style.display='none'" />
                  <span class="bp-job-name" :style="{color: stat.color}">{{ stat.abbr }}</span>
                </div>

                <div class="bp-chart-col">
                  <div class="bp-track">
                    <div v-for="tick in speedTicks" :key="tick"
                      class="bp-grid-line" :style="{left: speedPct(tick)+'%'}"></div>
                    <!-- 左鬚臂（慢端 wHigh → Q3） -->
                    <div class="bp-arm"
                      :style="{left: speedPct(stat.wHigh)+'%', width: Math.max(0, speedPct(stat.q3)-speedPct(stat.wHigh))+'%', background: stat.color}"></div>
                    <!-- IQR 色塊左半（Q3→Q2，慢→中） -->
                    <div class="bp-box"
                      :style="{
                        left: speedPct(stat.q3)+'%',
                        right: `calc(${100 - speedPct(stat.q2)}% + 1px)`,
                        background: stat.color,
                      }"></div>
                    <!-- IQR 色塊右半（Q2→Q1，中→快） -->
                    <div class="bp-box"
                      :style="{
                        left: `calc(${speedPct(stat.q2)}% + 1px)`,
                        right: (100 - speedPct(stat.q1))+'%',
                        background: stat.color,
                      }"></div>
                    <!-- 右鬚臂（Q1 → wLow，快端） -->
                    <div class="bp-arm"
                      :style="{left: speedPct(stat.q1)+'%', width: Math.max(0, speedPct(stat.wLow)-speedPct(stat.q1))+'%', background: stat.color}"></div>
                    <div class="bp-cap" :style="{left: speedPct(stat.wHigh)+'%', background: stat.color}"></div>
                    <div class="bp-cap" :style="{left: speedPct(stat.wLow)+'%', background: stat.color}"></div>
                    <div v-for="(ov, oi) in stat.outliers" :key="oi"
                      class="bp-outlier"
                      :style="{left: speedPct(ov)+'%', background: stat.color}"></div>
                  </div>
                </div>

                <div class="bp-stats-col">
                  <span class="bp-median-val" :style="{color: stat.color}">{{ fmtDuration(stat.q2) }}</span>
                  <span class="bp-count">n={{ stat.n }}</span>
                </div>
              </div>

              <!-- Legend -->
              <div class="bp-legend">
                <div class="bp-legend-demo">
                  <div class="bp-track" style="width:80px;flex-shrink:0">
                    <div class="bp-arm"     style="left:5%;width:23%;background:#6060a0"></div>
                    <div class="bp-box"     style="left:28%;width:44%;background:linear-gradient(to right,#6060a0 calc(55% - 0.8px),#0d0d14 calc(55% - 0.8px),#0d0d14 calc(55% + 0.8px),#6060a0 calc(55% + 0.8px))"></div>
                    <div class="bp-arm"     style="left:72%;width:23%;background:#6060a0"></div>
                    <div class="bp-cap"     style="left:5%;background:#6060a0"></div>
                    <div class="bp-cap"     style="left:95%;background:#6060a0"></div>
                  </div>
                </div>
                <span class="bp-legend-text">速度越右 = 越快 &nbsp;·&nbsp; 縫 = 中位數 &nbsp;·&nbsp; 點 = 極端值</span>
                <span class="bp-legend-count">{{ speedTotalRecords }} 筆資料 &nbsp;·&nbsp; {{ filteredSpeedStats.length }} 個職業</span>
              </div>
            </div>
          </template>

          <!-- Histogram -->
          <div class="stats-chart-wrap" style="margin-top:12px">
            <div class="hist-title">整體通關時間分佈</div>
            <div class="speed-histogram">
              <div class="hist-bar-area">
                <div v-for="(bucket, i) in speedHistogram" :key="bucket.start"
                  class="hist-bar-col"
                  :title="`${fmtDuration(bucket.start)} – ${fmtDuration(bucket.end)}: ${bucket.count} 筆`">
                  <div class="hist-bar-count" v-if="bucket.count > 0 && bucket.count / histMax > 0.18">
                    {{ bucket.count }}
                  </div>
                  <div class="hist-bar-fill"
                    :style="{height: (bucket.count / histMax * 100)+'%', opacity: bucket.count ? 1 : 0}">
                  </div>
                </div>
              </div>
              <div class="hist-label-row">
                <span v-for="(bucket, i) in speedHistogram" :key="bucket.start"
                  class="hist-label"
                  :style="{opacity: i % histLabelStep === 0 ? 1 : 0}">
                  {{ fmtDuration(bucket.start) }}
                </span>
              </div>
            </div>
          </div>

        </template>
        <div v-else class="status-msg">此副本尚無速刷資料</div>
      </template>
    </div>

    <!-- ─── Tooltip (fixed to cursor) ─────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="tooltip" class="bp-tooltip"
        :style="{top: tooltip.y+'px', left: tooltip.x+'px'}">
        <div class="bp-tooltip__title" :style="{color: tooltip.stat.color}">
          {{ tooltip.stat.abbr }}
        </div>
        <div class="bp-tooltip__row">
          <span class="bp-tooltip__label">最大值</span>
          <span class="bp-tooltip__val">
            {{ tooltip.isSpeed ? fmtDuration(tooltip.stat.max) : fmtDps(tooltip.stat.max) }}
          </span>
        </div>
        <div class="bp-tooltip__row">
          <span class="bp-tooltip__label">上四分位 (Q3)</span>
          <span class="bp-tooltip__val">
            {{ tooltip.isSpeed ? fmtDuration(tooltip.stat.q3) : fmtDps(tooltip.stat.q3) }}
          </span>
        </div>
        <div class="bp-tooltip__row bp-tooltip__row--hl">
          <span class="bp-tooltip__label">中位數</span>
          <span class="bp-tooltip__val">
            {{ tooltip.isSpeed ? fmtDuration(tooltip.stat.q2) : fmtDps(tooltip.stat.q2) }}
          </span>
        </div>
        <div class="bp-tooltip__row">
          <span class="bp-tooltip__label">下四分位 (Q1)</span>
          <span class="bp-tooltip__val">
            {{ tooltip.isSpeed ? fmtDuration(tooltip.stat.q1) : fmtDps(tooltip.stat.q1) }}
          </span>
        </div>
        <div class="bp-tooltip__row">
          <span class="bp-tooltip__label">最小值</span>
          <span class="bp-tooltip__val">
            {{ tooltip.isSpeed ? fmtDuration(tooltip.stat.min) : fmtDps(tooltip.stat.min) }}
          </span>
        </div>
        <div class="bp-tooltip__sep"></div>
        <div class="bp-tooltip__row">
          <span class="bp-tooltip__label">樣本數</span>
          <span class="bp-tooltip__val">{{ tooltip.stat.n }}</span>
        </div>
        <div class="bp-tooltip__row" v-if="tooltip.stat.outliers.length">
          <span class="bp-tooltip__label">極端值</span>
          <span class="bp-tooltip__val">{{ tooltip.stat.outliers.length }}</span>
        </div>
      </div>
    </Teleport>

  </div>
</template>
