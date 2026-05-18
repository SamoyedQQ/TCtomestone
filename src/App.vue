<script setup>
import { ref, onMounted } from 'vue'
import { useApp } from './composables/useApp.js'
import { ENCOUNTERS } from './domain/encounters.js'
import LeaderboardPage from './pages/LeaderboardPage.vue'
import SpeedPage from './pages/SpeedPage.vue'
import PlayerPage from './pages/PlayerPage.vue'
import StatsPage from './pages/StatsPage.vue'

const app = useApp()
const showInfo = ref(false)
const showUpload = ref(false)

onMounted(() => app.init())

function hexToRgb(hex) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `${r}, ${g}, ${b}`
}

const LOGO_SRC = import.meta.env.DEV ? '/docs/img/logo.png' : `${import.meta.env.BASE_URL}img/logo.png`

function pickEncounter(id) {
  app.selectEncounter(id)
  if (app.page.value === 'player') app.setPage('leaderboard')
  // stats/leaderboard/speed 保持當前頁面，只更新 eid
}

async function headerSearch() {
  app.setPage('player')
  await app.searchPlayers()
}
</script>

<template>
  <div class="site-wrap">

    <!-- Header -->
    <header class="site-header">
      <div class="container" style="display:flex;align-items:center;gap:16px;height:60px">
        <a href="/" class="site-logo">
          <img :src="LOGO_SRC" alt="logo" @error="$event.target.style.display='none'" />
          <span>FFLogs 繁中服 絕境戰排行榜</span>
        </a>
        <span class="logo-sep"></span>
        <span class="site-subtitle">僅記錄 繁中服 2026-01-01 以後的「公開」數據，可補上傳舊數據。</span>
        <div style="flex:1"></div>
        <span class="update-time" v-if="app.updatedAt.value">更新 {{ app.updatedAt.value }}</span>
        <button class="info-btn" @click="showUpload = !showUpload; showInfo = false" :class="{ active: showUpload }" title="上傳說明">↑</button>
        <button class="info-btn" @click="showInfo = !showInfo; showUpload = false" :class="{ active: showInfo }" title="關於本站">ⓘ</button>
      </div>
    </header>

    <!-- Main -->
    <main class="site-main">
      <div class="container">

        <!-- Page Tabs（標題列下方、副本按鈕上方） -->
        <div class="page-tabs">
          <button
            class="page-tab__btn"
            :class="{ active: app.page.value === 'leaderboard' }"
            @click="app.setPage('leaderboard')"
          >排行榜</button>
          <button
            class="page-tab__btn"
            :class="{ active: app.page.value === 'speed' }"
            @click="app.setPage('speed')"
          >通關速度</button>
          <button
            class="page-tab__btn"
            :class="{ active: app.page.value === 'stats' }"
            @click="app.setPage('stats')"
          >統計數據</button>
        </div>

        <!-- Encounter Picker + 搜尋框（常駐，搜尋框在最右邊） -->
        <div class="encounter-picker">
          <button
            v-for="enc in ENCOUNTERS"
            :key="enc.id"
            class="enc-btn"
            :class="{ active: app.eid.value === enc.id && app.page.value !== 'player' }"
            :style="{
              '--enc-color': enc.color,
              '--enc-rgb': hexToRgb(enc.color),
            }"
            @click="pickEncounter(enc.id)"
          >
            <span class="enc-btn__dot" :style="{ background: enc.color }"></span>
            {{ enc.name }}
          </button>

          <!-- 玩家搜尋框（最右邊） -->
          <div class="enc-search">
            <input
              v-model="app.query.value"
              class="enc-search__input"
              type="search"
              placeholder="搜尋玩家…"
              @keydown.enter="headerSearch"
            />
            <button
              class="enc-search__btn"
              :class="{ active: app.page.value === 'player' }"
              @click="headerSearch"
            >搜尋</button>
          </div>
        </div>

        <!-- Upload guide panel -->
        <div v-if="showUpload" class="info-panel">
          <div class="info-panel__title">上傳至 FFLogs 注意事項</div>
          <div class="info-panel__body">
            <ul>
              <li>
                <strong>FFLogs Uploader 語言請選取「簡體中文」</strong>，以確保資料可被正確辨識並收錄。
              </li>
              <li>
                <strong>請勾選「選擇特定戰鬥進行上傳」</strong>，僅上傳目標戰鬥，勿一次上傳全部資料，以避免雜訊報告混入。
              </li>
            </ul>
          </div>
          <button class="info-panel__close" @click="showUpload = false">關閉</button>
        </div>

        <!-- Info panel -->
        <div v-if="showInfo" class="info-panel">
          <div class="info-panel__title">關於 FFLogs 繁中服 絕境戰排行</div>
          <div class="info-panel__body">
            <p>本站收錄繁中服玩家，在絕境戰副本的最高 rDPS 成績，資料來源為
              <a href="https://www.fflogs.com" target="_blank" rel="noopener noreferrer">FFLogs</a> 公開報告，每2小時自動更新。
            </p>
            <ul>
              <li><strong>排行榜</strong>：每位玩家同職業僅保留最高 rDPS 紀錄。可依職能 / 職業 / 伺服器篩選。</li>
              <li><strong>通關速度</strong>：以隊伍為單位，依通關時間由快到慢排列。</li>
              <li><strong>統計數據</strong>：各職業 rDPS 與通關速度的四分位距圖。</li>
              <li><strong>玩家搜尋</strong>：在右上方搜尋框輸入名稱，查看玩家在各副本的最佳成績。</li>
            </ul>
          </div>
          <button class="info-panel__close" @click="showInfo = false">關閉</button>
        </div>

        <!-- Pages -->
        <LeaderboardPage v-if="app.page.value === 'leaderboard'" :app="app" />
        <SpeedPage       v-else-if="app.page.value === 'speed'"  :app="app" />
        <StatsPage       v-else-if="app.page.value === 'stats'"  :app="app" />
        <PlayerPage      v-else-if="app.page.value === 'player'" :app="app" />

      </div>
    </main>

    <!-- Footer -->
    <footer class="site-footer">
      <div class="container">
        資料來源：<a href="https://www.fflogs.com" target="_blank" rel="noopener" style="color:var(--accent-text)">FFLogs</a>，
        僅包含繁中服玩家。排行榜每2小時自動更新。
      </div>
    </footer>

  </div>
</template>
