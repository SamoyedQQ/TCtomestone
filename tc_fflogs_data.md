# TC Tomestone — 技術參考

## 專案結構

- **Python scraper**（`scraper_core.py` + `headless_run.py`）：抓 FFLogs 資料，輸出 JSON
- **GitHub Pages 網站**（`docs/`）：讀 JSON 顯示排行榜，純靜態
- 兩者**只透過 JSON 交換**：`docs/data/clears.json`、`docs/data/player_bests.json`、`docs/data/meta.json`

## Encounter ID（zoneID: 59）

| 副本 | encounterID |
|------|------------|
| UCoB | 1073 |
| UWU  | 1074 |
| TEA  | 1075 |
| DSR  | 1076 |
| TOP  | 1077 |

## TC 伺服器

`奧汀 / 伊弗利特 / 迦樓羅 / 巴哈姆特 / 鳳凰 / 泰坦 / 利維坦`（繁中名稱，可與同名 JP/EU 伺服器區分）

## JSON 格式

### clears.json（陣列）

```json
{ "code": "報告碼", "encounter": "fight.name", "players": ["名@伺服器"],
  "fight_id": 1, "duration_ms": 978462, "clear_dt_ms": 1778157793454 }
```

去重 key：`{code}:{fight_id}`；跨報告去重 sig：`"|".join(sorted(players)) + ":" + str(clear_dt_ms)`（已實作於 scraper + headless_run）

### player_bests.json（陣列）

```json
{ "name": "X", "server": "巴哈姆特", "encounter_id": 1074,
  "encounter": "...", "is_clear": true, "boss_hp_pct": 0.0,
  "rdps": 1364.86, "job": "BlackMage", "report_code": "...",
  "fight_id": 1, "timestamp_ms": 0, "duration_ms": 885000 }
```

Key 格式：通關 `name@server:encounter_id:job`；團滅 `name@server:encounter_id:_wipe`

## rDPS 計算 — damageDowntime 修正

部分副本（確認：**TOP 1077**）有玩家無法輸出的 downtime（例如 Phase 6 上天）。
FFLogs 排名用的有效戰鬥時間 = `totalTime − damageDowntime`，**不是** raw `endTime − startTime`。

`table(dataType: DamageDone)` 回傳的欄位含義：

| 欄位 | 含義 |
|------|------|
| `totalTime` | 等同 raw 戰鬥時長（ms），**未**扣除 downtime |
| `combatTime` | 同上，值與 `totalTime` 相等，**無用** |
| `damageDowntime` | 無傷害輸出的 downtime（ms）；TOP ≈ 274,000 ms |
| `entries[].totalRDPS` | 玩家該場的 rDPS 總傷害量（非 per-second） |

正確公式（`scraper_core.py _process_kill_bests`）：

```python
effective_ms = total_time_ms - damage_downtime_ms   # ≈ 860 s for TOP
rdps = entry["totalRDPS"] / (effective_ms / 1000)
```

TOP 實測：raw 1134 s → effective 860 s → rDPS **+32%**。
其他副本若 `damageDowntime = 0`，公式退化為原始計算，行為不變。

## API

- OAuth2: `POST https://www.fflogs.com/oauth/token` — `grant_type=client_credentials`
- GraphQL: `POST https://www.fflogs.com/api/v2/client`
- 限制：3600pt/hr 滾動視窗；429 讀 `retry-after`

## 爬蟲架構重點

- 掃描方向：**現在 → 舊**，固定 14 天窗口（`WINDOW_MS`），每批最多 25 頁
- 四層去重：
  - `seen_keys`（`{code}:{fight_id}`）：本 session 已存 clears
  - `seen_codes`：已呼叫 FIGHTS_QUERY 的 report codes（`processed_codes` + 本 session 新掃碼）
  - `processed_codes`（跨 session，`docs/data/processed_codes.json`）：避免重掃舊 report
  - `seen_clear_sigs`（跨 report 去重，`sorted(players)|clear_dt_ms`）：防止同一場通關因存在於兩個不同 report code 而重複計入；每次執行從 `clears.json` 重建，不需額外存檔
- `DEFAULT_START = "2026-01-01 00:00"` — 掃描終點
- `POINT_LIMIT = 3400`，達到後停止本次執行

## GitHub Actions 設定

`headless_run.py` 與 `scraper_core.py` **不在 repo**，以 base64 儲存於 GitHub Secrets：

| Secret | 說明 |
|--------|------|
| `SCRAPER_CORE_B64` | scraper_core.py 的 base64 |
| `HEADLESS_RUN_B64` | headless_run.py 的 base64 |
| `FFLOGS_CLIENT_ID` | FFLogs API client ID |
| `FFLOGS_CLIENT_SECRET` | FFLogs API client secret |

**更新 Secret 的正確方式**（必須用 bash 重導向，PowerShell pipe 會帶入 BOM）：

```bash
python -c "import base64; open('out.txt','w',encoding='ascii').write(base64.b64encode(open('file.py','rb').read()).decode('ascii'))"
gh secret set KEY_NAME < out.txt
```

**已知問題**：`FFLOGS_CLIENT_ID` / `FFLOGS_CLIENT_SECRET` 值開頭帶 BOM（`﻿`），`headless_run.py` 已在讀取時 `.lstrip('﻿').strip()` 處理。
