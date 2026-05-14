# TC Tomestone

**FFXIV 繁中服（TC）絕境戰排行榜**

追蹤台服七個伺服器（奧汀、伊弗利特、迦樓羅、巴哈姆特、鳳凰、泰坦、利維坦）的絕境副本通關與個人最佳成績。資料每日自動從 [FFLogs](https://www.fflogs.com) 公開報告抓取，以靜態網頁呈現。

🌐 **[查看排行榜](https://samoyedqq.github.io/TCtomestone/)**

---

## 追蹤副本

| 副本 | 英文全名 | FFLogs ID |
|------|----------|-----------|
| 絕歐米茄（TOP） | The Omega Protocol | 1077 |
| 絕龍詩戰爭（DSR） | Dragonsong's Reprise | 1076 |
| 絕亞歷山大（TEA） | The Epic of Alexander | 1075 |
| 絕究極神兵（UWU） | The Weapon's Refrain | 1074 |
| 絕巴哈姆特（UCoB） | The Unending Coil of Bahamut | 1073 |

資料涵蓋範圍：**2026-01-01 以後**的公開 FFLogs 報告。

---

## 功能

- **通關排行**：依通關時間排序，顯示隊伍組成與職業
- **速刷榜**：依戰鬥時長排序，顯示最速通關紀錄
- **個人最佳**：每位玩家每個副本每個職業的最高 rDPS 成績
- **進度榜**：未通關玩家的最深進度（boss HP%）
- **自動更新**：GitHub Actions 每天 UTC 02:00（台灣 10:00）自動執行

---

## 系統架構

```
FFLogs GraphQL API
        │
        ▼
scraper_core.py        ← 爬蟲核心：API 呼叫、限流、TC 過濾、去重
headless_run.py        ← CI 執行入口：讀設定、呼叫 Scraper、寫 JSON
        │
        ▼
docs/data/
  ├── clears.json          ← 所有通關紀錄（陣列，只 append）
  ├── player_bests.json    ← 玩家最佳成績（dict，key = 名@伺服器:副本:職業）
  ├── processed_codes.json ← 已處理報告碼（跨執行去重快取）
  └── meta.json            ← 最後更新時間戳記
        │
        ▼
docs/index.html + docs/js/app.js   ← 靜態前端（GitHub Pages）
```

資料管線（Python）與前端（Vanilla JS）**只透過 JSON 交換**，兩層職責完全分離。

---

## 本地開發

### 需求

- Python 3.12+
- FFLogs API 憑證（[申請教學](https://www.fflogs.com/api/clients/)）

### 安裝

```bash
git clone https://github.com/SamoyedQQ/TCtomestone.git
cd TCtomestone
python -m venv .venv
.venv/Scripts/pip install requests   # Windows
# source .venv/bin/activate && pip install requests  # Linux/Mac
```

### 設定憑證

建立 `.env` 檔（已列入 `.gitignore`，不會進 repo）：

```env
FFLOGS_CLIENT_ID=your_client_id
FFLOGS_CLIENT_SECRET=your_client_secret
```

或直接設為環境變數：

```powershell
$env:FFLOGS_CLIENT_ID = "your_client_id"
$env:FFLOGS_CLIENT_SECRET = "your_client_secret"
```

### 執行爬蟲

```bash
python headless_run.py
```

爬蟲會將結果寫入 `docs/data/`。執行前可先調整 `config/fflogs.json` 的掃描參數。

### 資料驗證

```bash
python validate_data.py
```

### 建置 Windows GUI 執行檔（選用）

詳見 [BUILD.md](BUILD.md)。

---

## GitHub Actions 自動化

`.github/workflows/update_data.yml` 每天自動執行：

1. Checkout repo
2. 執行 `headless_run.py`（從 FFLogs 抓取新通關）
3. 執行 `validate_data.py`（驗證資料完整性）
4. 若有新資料，commit 並 push 至 `docs/data/`

### 所需 Secrets

在 GitHub 倉庫的 **Settings → Secrets and variables → Actions** 設定：

| Secret | 說明 |
|--------|------|
| `FFLOGS_CLIENT_ID` | FFLogs API Client ID |
| `FFLOGS_CLIENT_SECRET` | FFLogs API Client Secret |

---

## 設定說明

### `config/encounters.json` — 副本清單

控制爬蟲掃描哪些副本。`"enabled": false` 可暫停特定副本的掃描（前端仍顯示歷史資料）。

```json
[
  {
    "key": "top",
    "name": "絕歐米茄",
    "full": "The Omega Protocol",
    "encounter_id": 1077,
    "zone_id": 59,
    "enabled": true,
    "scan_start_date": "2026-01-01"
  }
]
```

新增副本時，確認 `encounter_id` 後加入此檔即可，不需修改程式碼。

### `config/fflogs.json` — 爬蟲參數

| 欄位 | 預設值 | 說明 |
|------|--------|------|
| `point_limit` | 3400 | API 積分上限（FFLogs 每小時 3600，保留緩衝） |
| `page_delay_s` | 2 | 每頁查詢後等待秒數 |
| `fight_delay_s` | 1 | 每場戰鬥查詢後等待秒數 |
| `max_pages_per_batch` | 25 | 每批次最多掃描頁數 |
| `scan_window_days` | 14 | 每批次掃描的時間視窗（天） |
| `scan_start_date` | 2026-01-01 | 不處理此日期以前的報告 |

---

## 手動補抓報告

若某份報告遺漏或需要重新處理，在 `config/fflogs.json` 設定後執行爬蟲：

```json
{
  "only_report_codes": ["ABCdef123456"]
}
```

| 模式 | 行為 |
|------|------|
| `only_report_codes` | 只處理指定報告，跳過一般掃描，不影響掃描進度 |
| `retry_report_codes` | 強制重抓指定報告（從已處理快取移除，在一般掃描中重新處理） |

**使用完畢後務必清空這兩個欄位**，避免排程重複執行。

---

## 資料格式

### `clears.json`

```json
[
  {
    "code": "FFLogs報告碼",
    "title": "報告標題",
    "encounter": "The Omega Protocol",
    "players": ["玩家名@伺服器"],
    "fight_id": 1,
    "duration_ms": 978462,
    "clear_dt_ms": 1778157793454,
    "jobs": {"玩家名@伺服器": "BlackMage"}
  }
]
```

### `player_bests.json`

```json
{
  "玩家名@伺服器:1077:BlackMage": {
    "name": "玩家名",
    "server": "巴哈姆特",
    "encounter_id": 1077,
    "is_clear": true,
    "boss_hp_pct": 0.0,
    "rdps": 1364.86,
    "job": "BlackMage",
    "report_code": "...",
    "fight_id": 1,
    "duration_ms": 860000,
    "phase_reached": 6
  }
}
```

---

## 相關文件

| 文件 | 說明 |
|------|------|
| [CLAUDE.md](CLAUDE.md) | 專案運作準則（AI 協作用） |
| [BUILD.md](BUILD.md) | Windows GUI 執行檔建置說明 |
| [CHANGELOG.md](CHANGELOG.md) | 修改紀錄 |
| [config/README.md](config/README.md) | 設定欄位完整說明 |
| [ucob.md](ucob.md) | 絕巴哈姆特（UCoB）技術細節 |

---

## 注意事項

- 本專案只讀取 FFLogs **公開**報告，不抓取私人或隱藏報告
- 資料涵蓋 2026-01-01 以後，更早的歷史資料不在收錄範圍
- 若發現資料錯誤，歡迎開 Issue 或 PR

## License

MIT
