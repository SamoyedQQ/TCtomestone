# UCoB（絕巴哈姆特）技術參考

encounterID: **1073**，zoneID: 59

---

## FFLogs 戰鬥名稱結構

UCoB 的三個 Boss 都是**開場 preload**，敵人 ID 全部預先存在，因此不能用 enemyID 出現時機判斷進度。

| 到達相位 | FFLogs fight.name |
|---------|-------------------|
| P1（雙尾貓） | `Twintania` |
| P2（奈爾） | `Nael Deus Darnus / Twintania` |
| P3-P5（巴哈姆特本體、大八角、金色巴哈） | `Nael Deus Darnus / Bahamut Prime / Twintania` |

> **注意**：P3/P4/P5 的 fight.name 完全相同，**僅憑名稱無法區分**。  
> 名稱中 Twintania 排在最後，legacy fallback 必須用 `chain.some()` 比對全名，不能只看 `last`。

---

## fightPercentage 語義（scraper 用）

`fightPercentage` 為整場戰鬥剩餘 HP 百分比（**越低 = 進度越深**）：

| 相位 | fightPercentage 範圍 | bossPercentage（BP HP%） |
|------|---------------------|--------------------------|
| P1 wipe | ~94–100 | Twintania HP% |
| P2 wipe | ~88–94 | Nael HP% |
| P3 wipe | ~88–91 | ~43–51%（BP 有在掉血） |
| P4 wipe (Grand Octet) | ~85–89 | ~29–43%（BP 鎖血中） |
| **通關** | **= 80（精確值）** | ~0% |

> 資料來源：`ucob_calibration.json`（report `m29TjCJwxaWqbLDt`）

**關鍵結論**：
- `fightPercentage == 80` **唯一且精確**對應通關，所有 wipe 的值均 > 80
- duration ≥ 10min 的額外檢查是安全網，理論上不必要
- P4/P5 wipe **不會**被誤判成通關（fp 永遠 > 80）

---

## 通關偵測（`_is_kill`）

```python
# scraper_core.py
if fight.get("encounterID") == 1073:
    return (
        fight.get("fightPercentage") == 80
        and "Bahamut Prime" in fight.get("name", "")
        and (fight["endTime"] - fight["startTime"]) >= 600_000  # 10 分鐘安全網
    )
```

---

## Phase 偵測（`_wipe_phase`）

```python
# scraper_core.py _WIPE_PHASE_NPCS[1073]
(3, {8163, 8164, 8165, 8168}),  # Bahamut Prime（P3 或 P4 adds）
(2, {8161, 8162}),              # Nael Deus Darnus
# P1 fallback: return 1
```

**P3/P4 同 NPC，無法區分**，兩者都存為 `phase_reached=3`。  
NPC 8167（Golden Bahamut）因為在 P3 Morn Afah 動畫中也會 preload，**不能**作為 P5 marker。

---

## player_bests.json 的 boss_hp_pct 欄位

wipe 記錄儲存的是 **`fightPercentage`**（非 bossPercentage），值域 > 80。  
越低表示進度越深，`can_skip_wipe` 以此判斷是否跳過：

```python
return fight_pct >= existing.boss_hp_pct  # 相等或更差則跳過
```

### 已知資料問題

部分舊資料的 `boss_hp_pct = 80`（通關時的 fightPercentage 值），可能原因：
- 舊版 scraper 錯存 `bossPercentage` 而非 `fightPercentage`
- BP 剛出現、尚未扣血即全滅，fp 停在 ~80

此問題會導致 `can_skip_wipe` 永遠跳過這些玩家的後續更新（80 是下限，任何真實 wipe fp > 80）。  
**修法**：執行 `ucob_rescrape.py`（從零重建所有 UCoB 記錄）。

---

## JS 端 detectPhase（app.js）

### 新格式（FFLogs 2022+）
`"P1 Twintania"` / `"P2 Nael"` / `"P3 Bahamut Prime"` / `"P4 Grand Octet"`  
→ 直接 regex 取數字 `/^P(\d+)/i`

### Legacy fallback
```javascript
// 必須用 chain.some()，不能只看 last（Twintania 在名稱最後但不代表 P1）
if (chain.some(p => p.includes('golden bahamut'))) return 4;
if (chain.some(p => p.includes('bahamut prime')))  return 3;
if (chain.some(p => p.includes('nael')))           return 2;
return 1;
```

### wipePhaseLabel
- `phase_reached > 0` → 直接用 `phase_reached`
- `phase_reached == 0` → fallback 到 `detectPhase(encounterName)`

---

## 已知限制

| 問題 | 狀態 |
|------|------|
| P3/P4 wipe 無法區分（同 NPC） | 兩者都顯示 P3，可接受 |
| P5 wipe 偵測（Golden Bahamut） | 待實作（fp < 88 時可推斷） |
| 舊資料 boss_hp_pct=80 卡 skip | 需執行 ucob_rescrape.py 修復 |
| bossPercentage（BP 實際 HP%）未儲存 | 暫無規劃 |
