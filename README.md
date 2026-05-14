# TC Tomestone

FFLogs TC 伺服器絕境副本排行榜。記錄 2026-01-01 以後的「公開」資料。

## 檔案結構

| 檔案 | 說明 |
|------|------|
| `docs/` | GitHub Pages 網站（靜態） |
| `docs/data/clears.json` | 通關紀錄 |
| `docs/data/player_bests.json` | 玩家最佳記錄 |
| `docs/data/processed_codes.json` | 已掃描報告碼（跨 session 去重） |
| `scraper_core.py` | 爬蟲核心（不在 repo，存於 GitHub Secret） |
| `headless_run.py` | GitHub Actions 執行入口（不在 repo，存於 GitHub Secret） |
| `update_data.bat` | 本地更新資料並 push |

## 本地設定

`dist/config.json`（需手動建立，不內嵌於 exe）：

```json
{ "client_id": "...", "client_secret": "..." }
```

## 更新資料

```
update_data.bat
```

複製 `dist/` 的 JSON 到 `docs/data/`，更新 `meta.json`，commit 並 push（含 `docs/js/`、`docs/css/`、`docs/img/`）。

## GitHub Actions 自動更新

每天 02:00 UTC（台灣 10:00）自動執行，或手動觸發。見 `.github/workflows/update_data.yml`。

## 建置 EXE

```powershell
.venv\Scripts\python.exe -m PyInstaller TC-Tomestone.spec
```

輸出：`dist\TC-Tomestone.exe`。`config.json` 需手動複製到 `dist/`。詳見 [BUILD.md](BUILD.md)。

## TC 伺服器

奧汀 / 伊弗利特 / 迦樓羅 / 巴哈姆特 / 鳳凰 / 泰坦 / 利維坦
