# Changelog

## 2026-05-09

### 網站修正
- **TEA phase 誤判**：`detectPhase`（`app.js`）TEA case 改用 `chain.some()` 取代只看 `last`。encounter name 格式 `"Alexander Prime / living liquid / ..."` 的 `last` 是 `"living liquid"` 導致 P3 被誤判為 P1。
- **預設頁面**：`STATE.rdpsEncounter` / `STATE.speedEncounter` 從 `1075`（TEA）改為 `1077`（TOP）。

### GitHub Actions 修復
- **Token 失敗（BOM）**：`FFLOGS_CLIENT_ID` / `FFLOGS_CLIENT_SECRET` Secret 值開頭帶 BOM，`requests` Basic Auth 用 `latin-1` 編碼時爆炸。scraper 靜默吞例外，workflow 顯示成功但實際未更新資料。修正：`headless_run.py` 讀 credentials 時 `.lstrip('﻿').strip()`。
- **push 被 reject**：Actions checkout 的 commit 比 remote 舊，commit 後直接 push 失敗。修正：`update_data.yml` 加 `git pull --rebase origin master` 後再 push。
- **DEFAULT_START**：`headless_run.py` 掃描起點從 `2026-02-01` 改為 `2026-01-01`。

---

## 2026-05-09 — API 積分優化 + 小時滾動修正

### Bug 1：Wipe DETAIL_QUERY 每場各呼叫一次
- 舊：每場 wipe 各呼叫一次 DETAIL_QUERY（50 場 wipe = 50 次）
- 修正：每份報告只呼叫一次，`fightIDs` 為每位 TC 玩家最佳進度那場去重後（通常 1–8 個）

### Bug 2：小時積分滾動導致 pts_used 變負
- 舊：`pts_used = pts_now - pts_start`，跨整點後 `pts_now` 歸零 → 負值 → `POINT_LIMIT` 永不觸發
- 修正：偵測到 `pts_now < pts_start` 時將 `pts_start` 重設為 0
