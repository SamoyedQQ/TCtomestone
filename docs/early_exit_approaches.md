# Early-Exit 掃描策略：兩種方法

## 背景

當 FFLogs 同一時間窗口有很多舊頁面時，為避免逐頁掃描浪費 API points，加入 early-exit 機制提前跳出。

---

## 方法一：處理後 probe（舊版，已移除）

**邏輯：** 跑完整頁 → 若全部 TC 都是重複 → probe 下一頁 → 若下一頁首筆 TC 也重複 → batch_done

```python
# 在 for report in reps: 迴圈結束後
if not batch_done and not self._stop.is_set() and tc_skipped > 0 and tc_count == 0:
    time.sleep(PAGE_DELAY)
    probe = self._gql(SCAN_QUERY, {
        "page": page + 1, "startTime": batch_start, "endTime": end_time,
    })
    if probe is None:
        batch_done = True
    else:
        pts_now = probe["rateLimitData"]["pointsSpentThisHour"]
        if pts_start is None:
            pts_start = pts_now
        elif pts_now < pts_start:
            pts_start = 0
        res.pts_used = pts_now - pts_start
        self.on_status({"points": res.pts_used})

        probe_reps = probe["reportData"]["reports"]["data"]
        first_tc = next(
            (r for r in probe_reps if _is_tc(r["masterData"]["actors"])), None
        )
        if first_tc is None or first_tc["code"] in seen_codes:
            self.on_log(f"  [批{batch}] 下頁首筆TC亦重複，跳過後續頁面")
            batch_done = True
        else:
            _preloaded = probe
```

**缺點：** probe 頁只看第一筆 TC，若第一筆是舊的但後段有新的會漏掉。

---

## 方法二：處理前 probe（現行版本）

**邏輯：** 看第一筆 TC → 若重複 → probe 下一頁 → 若下一頁有新 TC → 補掃本頁再繼續；若無新 TC → batch_done

```python
# 在 for report in reps: 迴圈之前
first_tc_rep = next((r for r in reps if _is_tc(r["masterData"]["actors"])), None)
if not self._stop.is_set() and first_tc_rep is not None and first_tc_rep["code"] in seen_codes:
    time.sleep(PAGE_DELAY)
    probe = self._gql(SCAN_QUERY, {
        "page": page + 1, "startTime": batch_start, "endTime": end_time,
    })
    if probe is None:
        batch_done = True
    else:
        pts_now = probe["rateLimitData"]["pointsSpentThisHour"]
        if pts_start is None:
            pts_start = pts_now
        elif pts_now < pts_start:
            pts_start = 0
        res.pts_used = pts_now - pts_start
        self.on_status({"points": res.pts_used})

        probe_reps = probe["reportData"]["reports"]["data"]
        has_new_tc = any(
            _is_tc(r["masterData"]["actors"]) and r["code"] not in seen_codes
            for r in probe_reps
        )
        if has_new_tc:
            # 下一頁有新 TC → 補掃本頁（fall through to report loop）
            self.on_log(f"  [批{batch} 頁{page:2d}] 首筆TC重複，下頁有新TC，補掃此頁")
            _preloaded = probe
        else:
            self.on_log(f"  [批{batch}] 首筆TC重複，下頁亦無新TC，跳過後續頁面")
            batch_done = True

if batch_done:
    break

# 接著正常執行 for report in reps: ...
```

**優點：** probe 頁掃全部 TC（`any()`），不會因第一筆是舊的就放棄整頁；本頁若需補掃也會完整跑過。

**注意：** 當「首筆 TC 重複但下一頁有新」時，會多一次 SCAN_QUERY（probe），API 點數消耗略增。

---

## 比較

| 項目 | 方法一 | 方法二 |
|------|--------|--------|
| probe 時機 | 處理完本頁之後 | 處理本頁之前 |
| probe 頁判斷 | 只看第一筆 TC | 掃所有 TC（any） |
| 本頁後段新資料 | 可能漏掉 | 不會漏（補掃） |
| API 點數 | 略少（漏掉就省了） | 幾乎相同 |
