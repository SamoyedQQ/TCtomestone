# 設定檔說明

非敏感設定集中在此目錄，敏感資訊（FFLogs OAuth 憑證）透過環境變數或 GitHub Secrets 注入，不存放於此。

## `encounters.json` — 副本清單

每個副本的識別碼、名稱、FFLogs ID 與掃描起始日期。

| 欄位 | 說明 |
|------|------|
| `key` | 內部識別碼，對應未來資料檔名，建立後**不可改名** |
| `name` | 網站顯示名稱（繁中） |
| `full` | FFLogs 英文全名 |
| `encounter_id` | FFLogs encounterID（唯一，不因版本變動） |
| `zone_id` | FFLogs zoneID，絕本均為 59 |
| `enabled` | 控制下一輪爬蟲是否掃描此副本；`false` 不代表前端隱藏 |
| `scan_start_date` | 爬蟲掃描的終止時間點（比此日期更舊的報告不處理） |

新增副本時先確認 `encounter_id` 與 `zone_id`，再設定 `scan_start_date`，`enabled` 設為 `true` 後執行爬蟲即可。

## `fflogs.json` — 爬蟲參數

### TC 伺服器
| 欄位 | 說明 |
|------|------|
| `tc_servers` | 繁中伺服器列表（奧汀/伊弗利特/迦樓羅/巴哈姆特/鳳凰/泰坦/利維坦） |

### 掃描調校
| 欄位 | 預設值 | 說明 |
|------|--------|------|
| `point_limit` | 3400 | 每次執行最大消耗 API 點數（FFLogs 上限 3600/hr，留緩衝） |
| `page_delay_s` | 2 | 每頁 SCAN_QUERY 之間的等待秒數 |
| `fight_delay_s` | 1 | 每份 report 的 FIGHTS_QUERY 之間的等待秒數 |
| `max_pages_per_batch` | 25 | 每個時間批次最多掃描頁數 |
| `max_batches` | 200 | 最多批次數（防無限迴圈） |
| `scan_window_days` | 14 | 每個時間批次的視窗大小（天） |
| `scan_start_date` | 2026-01-01 | 掃描終止時間點，比此日期更舊的報告不處理 |

### 額外掃描 zone
| 欄位 | 預設值 | 說明 |
|------|--------|------|
| `extra_scan_zone_ids` | `[]` | 除 zone 59（絕境戰）外，額外掃描的 FFLogs zoneID 清單。用於捕捉混入 Savage 報告裡的絕境戰場次（如 zone 62 = AAC Light-Heavyweight）。掃到的報告仍只提取 `encounter_ids` 中的場次，不影響現有過濾邏輯。 |

### 手動補抓

處理完成後**務必清空**，避免排程重複補抓。

| 欄位 | 說明 |
|------|------|
| `retry_report_codes` | 在一般掃描中強制重抓這些 report code（從 `processed_codes` 移除後重跑） |
| `only_report_codes` | 只處理這些 report code，跳過一般掃描，不推進掃描進度 |
