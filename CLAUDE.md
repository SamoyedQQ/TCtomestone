# TC Tomestone — 專案運作準則

本專案為「FFXIV 繁中服絕境戰排行榜」系統，資料來源為 FFLogs 公開報告。

---

## 1. 架構邊界（嚴格遵守）

| 層級 | 職責 | 禁止 |
|------|------|------|
| **Python（資料管線）** | FFLogs API 呼叫、限流、TC 伺服器過濾、JSON 寫入 | 不可輸出 UI 聚合格式 |
| **Vanilla JS（前端）** | 讀靜態 JSON 渲染排行榜 | 不可直接呼叫 FFLogs API |

資料流：`FFLogs API → scraper_core.py → headless_run.py（CI）→ docs/data/*.json → docs/index.html`

---

## 2. 設定檔架構

非敏感設定在 `config/`；憑證只透過環境變數注入，絕不進 repo。

| 檔案 | 用途 |
|------|------|
| `config/encounters.json` | 副本清單、FFLogs ID、啟用狀態（encounterID 唯一真實來源） |
| `config/fflogs.json` | TC 伺服器列表、掃描調校參數、手動補抓設定 |

讀取優先順序：`config/*.json` → `scraper_core.py` 模組常數（同值，作為 fallback）。

---

## 3. 資料保護原則

- **`clears.json`**：只能 append；不可刪除或覆蓋既有通關紀錄。
- **`player_bests.json`**：每個 key 只保留最佳成績（`PlayerBests.update_if_better()`）。
- **`processed_codes.json`**：只能累加；`retry_report_codes` 才可暫時移除特定 code。
- 修改歷史資料前**必須確認影響範圍**，再執行。

---

## 4. FFLogs API 關鍵細節

**端點**：OAuth2 `POST /oauth/token`（client_credentials）；GraphQL `POST /api/v2/client`  
**限流**：3600 pt/hr 滾動視窗；`POINT_LIMIT = 3400`（留緩衝）；429 讀 `retry-after`，最多重試 5 次

### rDPS 計算（重要）

**時間分母優先使用 `rankings.duration`**（FFLogs 網頁同源），無法取得時 fallback：

| 來源 | 欄位 | 含義 |
|------|------|------|
| `FIGHTS_QUERY` → `rankings` | `data[].duration` | **首選分母**（ms）；FFLogs 網頁顯示 rDPS 所用的實際輸出時長，比 endTime-startTime 約短 1s |
| `DETAIL_QUERY` → `table` | `totalTime` / `combatTime` | raw 戰鬥時長（ms），**未**扣 downtime（兩者相等，combatTime 無用） |
| `DETAIL_QUERY` → `table` | `damageDowntime` | 無輸出 downtime（ms）；TOP ≈ 274,000 |
| `DETAIL_QUERY` → `table` | `entries[].totalRDPS` | 玩家總 rDPS 傷害量（非 per-second） |

```python
# rankings.duration 已由 FFLogs 內部處理 downtime，直接使用
if fight_id in rankings_duration:
    effective_ms = rankings_duration[fight_id]        # 首選：與網頁完全一致
else:
    effective_ms = total_time_ms - damage_downtime_ms  # fallback：TOP 實測 860s，+32%
rdps = entry["totalRDPS"] / (effective_ms / 1000)
```

`rankings` 欄位已加入 `FIGHTS_QUERY`（+1pt），由 `_parse_rankings_duration()` 解析為 `{fight_id: ms}`。

### 去重機制（四層）
1. `seen_keys`（`{code}:{fight_id}`）：本 session 已存通關，防重複寫入
2. `seen_codes`：已呼叫 FIGHTS_QUERY 的 report codes
3. `processed_codes`（`docs/data/processed_codes.json`）：跨 session 快取，防重掃
4. `seen_clear_sigs`（`sorted(players)|clear_dt_ms`）：跨 report code 去重

### UCoB（1073）特殊通關判定
FFLogs 不標記 UCoB 為 `kill=true`。判定條件：`fightPercentage == 80` + "Bahamut Prime" in name + 時長 ≥ 10 分鐘。  
見 `scraper_core.py _is_kill()` 與 `ucob.md`。

### 掃描策略
**現在 → 舊**，固定 14 天視窗（`scan_window_days`），每批最多 25 頁（`max_pages_per_batch`）。  
Early-exit（方法二）：處理頁面**之前**先看首筆 TC → 若重複，probe 下一頁 → 下頁有新 TC 補掃本頁，無則跳過。

---

## 5. 資料 JSON 格式

### `clears.json`（陣列）
```json
{
  "code": "報告碼", "title": "報告標題", "encounter": "fight.name",
  "players": ["名@伺服器"], "fight_id": 1,
  "duration_ms": 978462, "clear_dt_ms": 1778157793454,
  "jobs": {"名@伺服器": "BlackMage"}
}
```
去重 key：`{code}:{fight_id}`；跨報告去重：`"|".join(sorted(players)) + ":" + str(clear_dt_ms)`

### `player_bests.json`（物件，key 為玩家+副本+職業）
```json
{
  "name": "名", "server": "巴哈姆特", "encounter_id": 1074, "encounter": "...",
  "is_clear": true, "boss_hp_pct": 0.0, "rdps": 1364.86, "adps": 1200.0,
  "parse_pct": 99.0, "job": "BlackMage", "char_id": 12345,
  "report_code": "...", "fight_id": 1, "timestamp_ms": 0,
  "duration_ms": 885000, "phase_reached": 0
}
```
Key：通關 `name@server:encounter_id:job`；團滅 `name@server:encounter_id:_wipe`

---

## 6. 手動補抓流程

**`ManualBackfill.py`**：直接指定 report code + fight_id 補抓，自動讀 `.env` 憑證，只更新 `player_bests.json`（取最佳），不動 `clears.json` / `processed_codes.json`。

```bash
python ManualBackfill.py                      # 用腳本內 TARGETS
python ManualBackfill.py <code> <fight_id>    # 單筆
python ManualBackfill.py <code>               # 整份 report 所有通關
```

> **⚠️ 必做：補抓完畢後必須重新產生 leaderboard 分割檔案**，否則網站顯示的仍是舊值：
>
> ```python
> python -c "from headless_run import _write_split_data; from pathlib import Path; _write_split_data(Path('docs/data'))"
> ```
>
> `player_bests.json` 是真實來源；`leaderboard_{eid}.json` 是前端顯示用的快取，兩者必須同步。

**`config/fflogs.json`** 設定後執行爬蟲，完成後**務必清空**對應欄位：

| 模式 | 行為 |
|------|------|
| `retry_report_codes` | 從 `processed_codes` 移除，在一般掃描中重新處理，會更新 `processed_codes` |
| `only_report_codes` | 跳過一般掃描，直接處理，**不**推進掃描進度，**不**更新 `processed_codes` |

---

## 7. GitHub Actions

`.github/workflows/update_data.yml` 每天 UTC 02:00 執行（台灣時間 10:00）。  
所需 Secrets：**`FFLOGS_CLIENT_ID`、`FFLOGS_CLIENT_SECRET`**（僅此兩個；Python 原始碼已在 repo 中，不再 base64 傳入）。

---

## 8. Commit 格式

`type(scope): 繁中描述`

`feat` 新功能 | `fix` 修正 | `data` 資料更新 | `refactor` 重構 | `docs` 文件 | `chore` CI/設定

範例：`fix(website): 修正速刷榜隊友職業顯示順序`

---

## 9. 語言規範

全程**繁體中文（台灣用語）**。  
禁用中國用語：接口→API/介面、項目→專案、回調→回呼、模塊→模組、服務器→伺服器、異步→非同步

---

## 10. 禁止事項

- 不可在前端 JS 直接呼叫 FFLogs API
- 不可在爬蟲中刪除既有通關紀錄（只能 append）
- 不可覆寫 `processed_codes.json`（只能累加）
- 不可在 log / commit 中印出明文憑證
- 不可未經確認就 force push 或破壞性 git 操作

---

## 附錄：已確立的技術決策

### A. Phase 偵測策略
通關 phase 由 `_WIPE_PHASE_NPCS` 的 `enemyNPCs.gameID` 辨識，寫入 `phase_reached`。  
前端 `detectPhase(eid, encounterName)` 依 fight name 字串偵測（舊格式 fallback）。  
UCoB P5（Golden Bahamut）無法用 NPC gameID 辨識，改用 `fightPercentage < 80` 判定。詳見 `ucob.md`。

### B. rDPS 分母來源（rankings.duration vs totalTime）
FFLogs 網頁顯示的 rDPS 使用 `rankings.duration` 作為時間分母，比 `endTime - startTime` 約短 1 秒（精確實測值），導致我們若用 `totalTime` 算出來的 rDPS 系統性偏低（約 +7 rDPS / 1094s fight 的量級）。  
現行做法：`FIGHTS_QUERY` 加入 `rankings` 欄位（+1pt），`_parse_rankings_duration()` 解析後傳入 `_process_kill_bests()`。`rankings.duration` 不存在時（如私密報告）fallback 至 `totalTime - damageDowntime`。

### C. Wipe 排行最佳成績規則
- 已通關 > 未通關（有 clear 的 job 覆蓋 wipe）
- 通關中：`rdps` 越高越好
- 團滅中：`boss_hp_pct` 越低越好（fightPercentage，lower = further）
