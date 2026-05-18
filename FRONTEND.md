# TC Tomestone — Vue 前端文件

本文件說明 Vue 3 前端的完整架構、設計決策與維護要點。

---

## 1. 技術棧

| 項目 | 版本 / 說明 |
|------|------------|
| Vue 3 | Composition API，`<script setup>` |
| Vite | 建置工具，`vite.config.js` → `outDir: 'docs'` |
| 純 CSS | 無 UI 框架，設計系統完全自定義 |

啟動開發伺服器：
```bash
npm run dev      # http://localhost:5173/
npm run build    # 輸出至 docs/（emptyOutDir: false 保留 docs/data/）
```

---

## 2. 目錄結構

```
src/
├── App.vue                  # 根元件：header、副本切換、頁面路由
├── main.js                  # Vue 掛載點
├── composables/
│   └── useApp.js            # 唯一狀態管理（所有 state + computed + actions）
├── domain/
│   ├── encounters.js        # 副本常數（encounterID、中文名、顏色、排序）
│   └── jobs.js              # 職業常數（中文縮寫、role、顏色）
├── pages/
│   ├── LeaderboardPage.vue  # rDPS 排行榜（含職能/職業/伺服器篩選）
│   ├── SpeedPage.vue        # 通關速度榜
│   └── PlayerPage.vue       # 玩家搜尋 + 個人資料
├── utils/
│   ├── dataUrl.js           # 資料 URL 工廠（dev=remote GitHub Pages，prod=相對路徑）
│   └── format.js            # fmtDps / fmtDuration / fmtDate / fmtRank
└── styles/
    └── app.css              # 全站 CSS（設計系統 + 元件樣式）
```

建置輸出：`docs/`（GitHub Pages 根目錄）

---

## 3. 資料來源

```js
// src/utils/dataUrl.js
const REMOTE = 'https://samoyedqq.github.io/TCtomestone/data'
const BASE = import.meta.env.PROD ? '/data' : REMOTE
```

**Dev 模式永遠讀 remote GitHub Pages**（CORS: * 已開放）。  
**Prod 建置後讀相對路徑 `/data`**（即 `docs/data/`，由 Python scraper 寫入）。

讀取的 JSON 檔：
| 檔案 | 用途 |
|------|------|
| `meta.json` | 更新時間戳 |
| `leaderboard_{eid}.json` | 該副本所有玩家最佳成績（含 wipe） |
| `clears_{eid}.json` | 該副本所有通關紀錄（速刷榜用） |
| `players_index.json` | 全站玩家清單（搜尋用） |

**`parse_pct` 欄位在現有資料中全為 0.0**（FFLogs rankPercent API 未回傳），前端改用同職業排名自行計算 TC 相對百分位（TC PR%）。

---

## 4. 副本設定（encounters.js）

**排序**：神兵 → 巴哈 → 亞歷 → 龍詩 → 歐米茄  

| encounterID | short | name | 顏色 |
|-------------|-------|------|------|
| 1074 | 神兵 | 絕 究極神兵 | `#3b82f6` 藍 |
| 1073 | 巴哈 | 絕 巴哈姆特 | `#f59e0b` 琥珀 |
| 1075 | 亞歷 | 絕 亞歷山大 | `#c8a46a` 米黃 |
| 1076 | 龍詩 | 絕 龍詩戰爭 | `#f97316` 橘 |
| 1077 | 歐米茄 | 絕 歐米茄 | `#a855f7` 紫 |

名稱格式：**絕 + 空格 + 副本名**（例：絕 究極神兵）。

---

## 5. 職業設定（jobs.js）

所有 `abbr` 使用繁體中文。`JOBS` key 為英文 PascalCase（與 FFLogs 資料對應）：

| key | abbr | role |
|-----|------|------|
| Paladin | 騎士 | Tank |
| Warrior | 戰士 | Tank |
| DarkKnight | 暗騎 | Tank |
| Gunbreaker | 絕槍 | Tank |
| WhiteMage | 白魔 | Healer |
| Scholar | 學者 | Healer |
| Astrologian | 占星 | Healer |
| Sage | 賢者 | Healer |
| Monk | 武僧 | Melee |
| Dragoon | 龍騎 | Melee |
| Ninja | 忍者 | Melee |
| Samurai | 武士 | Melee |
| Reaper | 奪魂 | Melee |
| Viper | 毒蛇 | Melee |
| Bard | 詩人 | Ranged |
| Machinist | 機工 | Ranged |
| Dancer | 舞者 | Ranged |
| BlackMage | 黑魔 | Caster |
| Summoner | 召喚 | Caster |
| RedMage | 赤魔 | Caster |
| Pictomancer | 繪靈 | Caster |

職業圖示路徑：`/img/jobs/{name.toLowerCase()}.png`（檔名全小寫）。

---

## 6. 狀態管理（useApp.js）

全站唯一 composable，以 `reactive` cache 跨元件共享資料。

### 關鍵 computed

**`filteredLb`**（排行榜過濾 + 去重）：
1. 只保留 `is_clear = true`
2. 依 role / job / server 篩選
3. 依 `rdps` 降序排列
4. **去重**：每個 `name@server:job` 只保留一筆（最高 rDPS 已在排序後自然取第一）

**`sortedClears`**（速刷榜）：  
`duration_ms > 0` 過濾後依 `duration_ms` 升序排列

**`playerProfile`**（玩家個人資料）：
- 遍歷所有副本，撈取該玩家的所有紀錄
- 最佳成績選取邏輯：
  - 有通關 → 取 rdps 最高的通關紀錄
  - 全為 wipe → 取 `boss_hp_pct` 最低的（推進最遠）
- 同職業排名計算：過濾同副本同職業通關紀錄，去重後依 rdps 排序，取 index + 1
- TC PR% = `((total - rank) / total) × 100`，上限 99

### 資料快取

```js
const cache = reactive({
  meta: null,
  lb: {},          // eid → array（leaderboard）
  cl: {},          // eid → array（clears）
  playersIdx: null,
})
```

切副本（`selectEncounter`）只在 cache 無資料時才 fetch，已載入的副本不重複請求。

---

## 7. 設計系統（app.css）

### 色彩 tokens

```css
--bg:           #0d0d14;   /* 主背景（深藍紫） */
--bg-surface:   #14141e;   /* 卡片背景 */
--bg-raised:    #1c1c28;   /* 表頭、raised 元素 */
--accent:       #7c3aed;   /* 主強調色（紫羅蘭） */
--accent-text:  #c4b5fd;   /* 強調文字 */
--text:         #eaeaf2;
--text-2:       #8484a4;
--text-3:       #52526e;
--border:       rgba(255,255,255,0.09);
```

### TC PR% 顏色分級

| 範圍 | class | 顏色 |
|------|-------|------|
| 100 | `pr-gold` | `#e5c84a` 金 |
| 99 | `pr-pink` | `#e879a0` 粉 |
| 98–95 | `pr-orange` | `#f97316` 橘 |
| 94–75 | `pr-purple` | `#c084fc` 紫 |
| 74–50 | `pr-blue` | `#60a5fa` 藍 |
| 49–30 | `pr-green` | `#4ade80` 綠 |
| ＜30 | `pr-gray` | `var(--text-3)` 灰 |

### 職能顏色

```css
--tank:   #60a5fa;
--healer: #34d399;
--melee:  #f87171;
--ranged: #fbbf24;
--caster: #c084fc;
```

---

## 8. 頁面功能

### 排行榜（LeaderboardPage）
- 職能按鈕（坦克/治療/近戰/遠程/法系）→ 展開職業 pills
- 伺服器下拉篩選（當有多個伺服器時才顯示）
- 表格：排名（#1–#3 金銀銅）| 玩家名稱（可點擊→玩家資料）| 伺服器 | 職業 chip | rDPS | aDPS | 通關時間 | 報告連結

### 速刷榜（SpeedPage）
- 依通關時間升序排列
- 顯示整隊成員（含職業圖示 + 顏色）
- 點擊報告連結直接開啟 FFLogs

### 玩家資料（PlayerPage）
- 搜尋框輸入名稱 → 即時顯示符合玩家清單
- 點擊玩家 → 載入所有副本的最佳成績
- 每個副本卡片顯示固定 7 欄 grid：
  **排名 | rDPS | aDPS | TC PR% | 時間 | 職業 | 報告**
- 未通關：rDPS/aDPS/排名/PR% 顯示「—」；標頭 badge 顯示最遠進度（P3 / 45.2%）

### 說明面板
- Header 右側 `ⓘ` 按鈕 → 切換說明面板
- 說明網站用途、資料來源、三個頁面功能、rDPS/aDPS 定義

---

## 9. 部署

GitHub Pages：`https://samoyedqq.github.io/TCtomestone/`  
Branch：`master`，GitHub Pages 根目錄：`docs/`

```bash
npm run build   # 建置至 docs/（保留 docs/data/）
git add docs/
git commit -m "feat(website): ..."
git push
```

**注意**：`vite.config.js` 設定 `emptyOutDir: false`，確保 `docs/data/`（Python scraper 寫入的 JSON）不會被建置清除。

---

## 10. 已知限制

- `parse_pct` 欄位全為 0（FFLogs API 不回傳 TC 伺服器的 rankPercent），改用 TC 內部排名計算相對百分位
- 玩家個人資料載入需拉取所有副本的 leaderboard JSON（5 個副本 × 約 300–800KB），首次開啟玩家頁面較慢
- 圖示依賴 `docs/img/jobs/` 的靜態圖片，檔名必須全小寫（代碼已統一 `.toLowerCase()`）
