# Build 方式

## 環境

- Python 3.14（由 uv 管理，在 `.venv`）
- PyInstaller 6.20+（已在 `.venv` 內）

## 建置指令

### 使用現有 spec 檔（推薦）

```powershell
.venv\Scripts\python.exe -m PyInstaller TC-Tomestone.spec
```

輸出：`dist\TC-Tomestone.exe`

### 從頭生成（不常用）

```powershell
.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name TCtomestone app.py
```

注意：這會產生新的 `TCtomestone.spec`，customtkinter 可能要手動加進 `datas`（見下方）。

## spec 檔重點

`TC-Tomestone.spec` 的關鍵設定：

```python
datas=[('D:/code/TCtomestone/.venv/Lib/site-packages/customtkinter', 'customtkinter')],
console=False,   # 不顯示黑視窗
upx=True,
```

customtkinter 必須手動加入 `datas`，否則執行時找不到主題資源。

## 輸出

- `dist\TC-Tomestone.exe`：發佈用單一 exe
- `build\`：中間產物，可刪除
- `TC-Tomestone.spec`：保留，下次直接用
