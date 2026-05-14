# TC Tomestone — 專案運作準則

本專案為「FFXIV 繁中服絕境戰排行榜」系統，資料來源為 FFLogs 公開報告。

---

## 1. 架構邊界（嚴格遵守）

本專案為靜態化分離架構，兩層職責不可混用：

| 層級 | 職責 | 禁止事項 |
|------|------|---------|
| **資料管線層（Python）** | FFLogs API 呼叫、限流、TC 伺服器過濾、JSON 寫入 | 不可寫入 UI 格式；不可在爬蟲中直接輸出前端所需的聚合統計 |
| **UI 呈現層（Vanilla JS）** | 讀取靜態 JSON 渲染排行榜 | 不可直接呼叫 FFLogs API；複雜聚合（排序、去重）應盡量在 Python 端完成 |

### 資料流
```
FFLogs API
    ↓ scraper_core.py（核心邏輯）
    ↓ headless_run.py（CI 入口）
docs/data/clears.json
docs/data/player_bests.json
docs/data/processed_codes.json
docs/data/meta.json
    ↓
docs/index.html + docs/js/app.js（靜態前端）
```

---

## 2. 設定檔架構

非敏感設定集中在 `config/`，敏感憑證透過環境變數注入：

| 檔案 | 用途 |
|------|------|
| `config/encounters.json` | 副本清單、FFLogs ID、掃描起始日期、啟用狀態 |
| `config/fflogs.json` | TC 伺服器列表、掃描調校參數、手動補抓設定 |

**爬蟲讀取優先順序**：`config/*.json` → 程式內預設值（相同數值，作為 fallback）。

---

## 3. 資料保護原則

- **`docs/data/clears.json`**：只能 append；不可刪除或覆蓋既有通關紀錄。
- **`docs/data/player_bests.json`**：每個 key 只保留最佳成績，比較邏輯在 `PlayerBests.update_if_better()`。
- **`docs/data/processed_codes.json`**：跨 session 的 report code 快取，只能累加；手動補抓（`retry_report_codes`）才可暫時移除特定 code。
- 任何修改歷史資料的操作**必須先確認影響範圍**，再執行。

---

## 4. FFLogs API 關鍵細節

### 限流
- 3600 pt/hr 滾動視窗；`POINT_LIMIT = 3400`（留緩衝）。
- 429 回應讀 `retry-after` header 等待，最多重試 5 次。
- `config/fflogs.json` 的 `point_limit`、`page_delay_s`、`fight_delay_s` 可調整。

### rDPS 計算（重要）
部分副本（確認：TOP 1077）有玩家無法輸出的 downtime（P6 上天 ≈274s）。

`table(dataType: DamageDone)` 回傳的欄位含義：

| 欄位 | 含義 |
|------|------|
| `totalTime` | 等同 raw 戰鬥時長（ms），**未**扣除 downtime |
| `combatTime` | 同上，值與 `totalTime` 相等，**無用** |
| `damageDowntime` | 無傷害輸出的 downtime（ms）；TOP ≈ 274,000 ms |
| `entries[].totalRDPS` | 玩家該場的 rDPS 總傷害量（非 per-second） |

```python
# 正確：用 totalTime - damageDowntime 作為分母
effective_ms = total_time_ms - damage_downtime_ms
rdps = entry["totalRDPS"] / (effective_ms / 1000)

# 錯誤：直接用 combatTime（值與 totalTime 相同，未扣 downtime）
```

TOP 實測：raw 1134s → effective 860s → rDPS **+32%**。其他副本 `damageDowntime=0` 時退化為原始計算。

### API 端點
- OAuth2：`POST https://www.fflogs.com/oauth/token`（grant_type=client_credentials）
- GraphQL：`POST https://www.fflogs.com/api/v2/client`
- 限制：3600 pt/hr 滾動視窗；429 讀 `retry-after` header

### 去重機制（四層）
1. `seen_keys`（`{code}:{fight_id}`）：本 session 已存通關，防重複寫入
2. `seen_codes`：已呼叫 FIGHTS_QUERY 的 report codes（`processed_codes` + 本次新掃）
3. `processed_codes`（`docs/data/processed_codes.json`）：跨 session 快取，防重掃
4. `seen_clear_sigs`（`sorted(players)|clear_dt_ms`）：跨 report code 去重，防同一場通關因兩份報告重複計入

### UCoB（1073）特殊通關判定
FFLogs 不標記 UCoB 為 `kill=true`。判定條件：
- `fightPercentage == 80`（Golden Bahamut phase HP）
- fight name 含 "Bahamut Prime"
- 時長 ≥ 10 分鐘

見 `scraper_core.py` 的 `_is_kill()` 函式。

### 掃描方向
**現在 → 舊**，固定 14 天視窗（`scan_window_days`），每批最多 25 頁（`max_pages_per_batch`）。

Early-exit 機制（方法二）：
- 處理頁面**之前**先看首筆 TC
- 若首筆 TC 重複 → probe 下一頁
  - 下一頁有新 TC → 補掃本頁
  - 下一頁無新 TC → 跳過後續頁面

---

## 5. 資料 JSON 格式

### `clears.json`（陣列）

```json
{
  "code": "報告碼",
  "title": "報告標題",
  "encounter": "fight.name",
  "players": ["名@伺服器"],
  "fight_id": 1,
  "duration_ms": 978462,
  "clear_dt_ms": 1778157793454,
  "jobs": {"名@伺服器": "BlackMage"}
}
```

去重 key：`{code}:{fight_id}`；跨報告去重：`"|".join(sorted(players)) + ":" + str(clear_dt_ms)`

### `player_bests.json`（物件，key 為玩家+副本+職業）

```json
{
  "名@伺服器:1074:BlackMage": {
    "name": "名", "server": "巴哈姆特",
    "encounter_id": 1074, "encounter": "...",
    "is_clear": true, "boss_hp_pct": 0.0,
    "rdps": 1364.86, "adps": 1200.0, "parse_pct": 99.0,
    "job": "BlackMage", "char_id": 12345,
    "report_code": "...", "fight_id": 1,
    "timestamp_ms": 0, "duration_ms": 885000,
    "phase_reached": 0
  }
}
```

Key 格式：通關 `name@server:encounter_id:job`；團滅 `name@server:encounter_id:_wipe`

---

## 6. 手動補抓流程

在 `config/fflogs.json` 設定後執行爬蟲，完成後**務必清空**對應欄位：

```json
{
  "retry_report_codes": ["ABC123"],
  "only_report_codes": []
}
```

| 模式 | 行為 |
|------|------|
| `retry_report_codes` | 從 `processed_codes` 移除指定 code，在一般掃描中重新處理，會更新 `processed_codes` |
| `only_report_codes` | 跳過一般掃描，直接處理指定 code，**不**推進掃描進度，**不**更新 `processed_codes` |

---

## 7. GitHub Actions 設定

`.github/workflows/update_data.yml` 每天 UTC 02:00 執行（台灣時間 10:00）。

**Secrets 設定方式**（必須用 bash 重導向，PowerShell pipe 會帶 BOM）：
```bash
python -c "import base64; open('out.txt','w',encoding='ascii').write(base64.b64encode(open('file.py','rb').read()).decode('ascii'))"
gh secret set KEY_NAME < out.txt
```

| Secret | 說明 |
|--------|------|
| `SCRAPER_CORE_B64` | `scraper_core.py` 的 base64 |
| `HEADLESS_RUN_B64` | `headless_run.py` 的 base64 |
| `FFLOGS_CLIENT_ID` | FFLogs API client ID（值開頭可能有 BOM，headless_run.py 已處理） |
| `FFLOGS_CLIENT_SECRET` | FFLogs API client secret |

Python 爬蟲不在 repo，以 base64 儲存於 Secrets 並在 CI 執行時還原。

---

## 8. Commit 格式規範

```
type(scope): 繁中描述
```

| type | 使用時機 |
|------|---------|
| `feat` | 新功能 |
| `fix` | 修正錯誤 |
| `data` | 自動資料更新（auto-update） |
| `refactor` | 重構，不改行為 |
| `docs` | 文件更新 |
| `chore` | 設定、依賴、CI 調整 |

範例：
- `feat(scraper): 實作 only_report_codes 手動補抓模式`
- `fix(website): 修正速刷榜隊友職業顯示順序`
- `data: auto-update 2026-05-14 02:03 UTC`

---

## 9. 語言規範

- 所有對話、commit、文件、程式碼註解使用**繁體中文（台灣用語）**
- 嚴禁使用中國用語：接口→API/介面、項目→專案、回調→回呼、模塊→模組、服務器→伺服器、異步→非同步

---

## 10. 禁止事項

- 不可在前端 JS 直接呼叫 FFLogs API
- 不可在爬蟲中刪除既有通關紀錄（只能 append）
- 不可覆寫 `processed_codes.json`（只能累加）
- 不可在 log / commit 中印出明文憑證
- 不可未經確認就 force push 或破壞性 git 操作

---

## 附錄：已確立的技術決策

### A. 副本 encounterID 對照
| 副本 | encounterID | zone_id |
|------|------------|---------|
| UCoB 絕巴哈姆特 | 1073 | 59 |
| UWU 絕究極神兵 | 1074 | 59 |
| TEA 絕亞歷山大 | 1075 | 59 |
| DSR 絕龍詩戰爭 | 1076 | 59 |
| TOP 絕歐米茄 | 1077 | 59 |

### B. Phase 偵測策略
**通關** phase 由 `_WIPE_PHASE_NPCS` 中的 `enemyNPCs.gameID` 辨識，寫入 `phase_reached`。
**前端**另有 `detectPhase(eid, encounterName)` 依 fight name 字串偵測（供舊格式 fallback）。

UCoB P5（Golden Bahamut）無法用 NPC gameID 辨識，改用 `fightPercentage < 80` 判定。

### C. Wipe 排行最佳成績規則
- 已通關 > 未通關（有 clear 的 job 覆蓋 wipe）
- 通關中：`rdps` 越高越好
- 團滅中：`boss_hp_pct` 越低越好（fightPercentage，lower = further）

### D. Scraper 設定讀取優先順序
1. `config/fflogs.json` 的值
2. `scraper_core.py` 中的模組常數（備用預設值）

兩者目前數值相同，config 異動後不需改程式碼即可生效。
