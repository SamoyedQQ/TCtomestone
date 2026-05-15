"""
headless_run.py — GitHub Actions 無介面執行器

此腳本在 CI 環境（GitHub Actions）中被呼叫，負責：
  1. 從環境變數讀取 FFLogs API 憑證（FFLOGS_CLIENT_ID / FFLOGS_CLIENT_SECRET）
  2. 從 config/ 目錄讀取爬蟲設定與副本設定
  3. 載入現有通關資料（clears.json）與已處理 report 清單（processed_codes.json）
  4. 呼叫 scraper_core.Scraper 執行掃描
  5. 將新通關紀錄寫回 clears.json，並更新 processed_codes.json 與 meta.json

【安全原則】
  - 憑證只從環境變數讀取，絕不寫入任何輸出檔案或日誌
  - config/ 目錄下的 JSON 只存放非敏感設定（副本 ID、掃描視窗等）
  - .env / docs/data/config.json 已列入 .gitignore，永遠不進 repo

【呼叫方式】
  $ python headless_run.py
  或由 .github/workflows/update_data.yml 自動呼叫

【環境變數】
  FFLOGS_CLIENT_ID     — FFLogs OAuth2 Client ID（必填）
  FFLOGS_CLIENT_SECRET — FFLogs OAuth2 Client Secret（必填）
  START_DT             — 可選，掃描起始日期，格式 YYYY-MM-DD 或 YYYY-MM-DD HH:MM
                         優先級：環境變數 > config/fflogs.json > 預設值 2026-01-01
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from scraper_core import ClearRecord, Scraper

# ── 路徑常數 ──────────────────────────────────────────────────────────────────

ROOT_DIR     = Path(__file__).parent          # 專案根目錄
DATA_DIR     = ROOT_DIR / "docs" / "data"     # GitHub Pages 資料目錄（靜態 JSON）
CLEARS_PATH  = DATA_DIR / "clears.json"       # 通關紀錄（陣列）
BESTS_PATH   = DATA_DIR / "player_bests.json" # 玩家最佳成績（dict，key = name@server:enc_id:job）
CODES_PATH   = DATA_DIR / "processed_codes.json"  # 已處理 report code 清單（跨執行持久化）
META_PATH    = DATA_DIR / "meta.json"         # 最後更新時間戳記

# config 路徑：非敏感設定，可進 repo
FFLOGS_CFG_PATH     = ROOT_DIR / "config" / "fflogs.json"      # 爬蟲參數設定
ENCOUNTERS_CFG_PATH = ROOT_DIR / "config" / "encounters.json"  # 副本列表設定


# ── 設定載入 ──────────────────────────────────────────────────────────────────

def _load_fflogs_cfg() -> dict:
    """
    載入 config/fflogs.json。

    若檔案不存在或解析失敗，回傳空 dict；
    Scraper 將使用 scraper_core.py 中定義的模組層級預設值。

    可設定欄位：
      tc_servers          — 台服伺服器名稱清單
      point_limit         — API 積分上限（每小時 3600，建議設 3400 保留緩衝）
      page_delay_s        — 每頁查詢後等待秒數
      fight_delay_s       — 每場戰鬥查詢後等待秒數
      max_pages_per_batch — 每批次最多掃描頁數
      max_batches         — 掃描批次上限（防止無限迴圈）
      scan_window_days    — 每批次掃描的時間視窗（天）
      scan_start_date     — 掃描起始日期（YYYY-MM-DD）
      retry_report_codes  — 強制重抓的 report code 清單
      only_report_codes   — 手動補抓模式，只處理這些 code
    """
    try:
        if FFLOGS_CFG_PATH.exists():
            return json.loads(FFLOGS_CFG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[警告] 無法讀取 config/fflogs.json：{e}", flush=True)
    return {}


def _load_encounters_cfg() -> list:
    """
    載入 config/encounters.json。

    若檔案不存在或解析失敗，回傳空陣列；
    此時 Scraper 將使用 scraper_core.py 中硬編碼的預設 encounter_id 清單。

    每個副本物件格式：
      {
        "key": "top",           — 程式用識別鍵
        "name": "絕歐米茄",     — 中文名稱
        "full": "The Omega Protocol",  — 英文全名
        "encounter_id": 1077,   — FFLogs encounter ID
        "zone_id": 59,          — FFLogs zone ID
        "enabled": true,        — false 則跳過此副本
        "scan_start_date": "2026-01-01"  — 此副本的掃描起始日（目前未使用，保留擴充性）
      }
    """
    try:
        if ENCOUNTERS_CFG_PATH.exists():
            return json.loads(ENCOUNTERS_CFG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[警告] 無法讀取 config/encounters.json：{e}", flush=True)
    return []


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def _parse_dt_ms(s: str):
    """
    將日期字串解析為 UTC millisecond timestamp。

    支援格式：
      "YYYY-MM-DD HH:MM" — 精確到分鐘
      "YYYY-MM-DD"       — 當天 00:00 UTC

    解析失敗時回傳 None。
    """
    s = s.strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    return None


def _load_clears() -> list:
    """
    從 clears.json 載入現有通關紀錄（原始 dict 陣列）。

    若檔案不存在或損毀，回傳空陣列（首次執行時的正常情況）。
    呼叫端負責將 dict 轉換為 ClearRecord 物件。
    """
    try:
        if CLEARS_PATH.exists():
            return json.loads(CLEARS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _load_processed_codes() -> set:
    """
    從 processed_codes.json 載入已處理的 FFLogs report code 集合。

    processed_codes 是跨執行的持久化狀態，用於避免重複處理同一份報告。
    每次成功掃描後，本次處理的 code 會被合併寫回此檔案。

    若檔案不存在，回傳空集合（首次執行時的正常情況）。
    """
    try:
        if CODES_PATH.exists():
            return set(json.loads(CODES_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return set()


# ── 主程式 ────────────────────────────────────────────────────────────────────

def main():
    """
    主流程：

    1. 驗證憑證（必填環境變數）
    2. 載入設定（config/fflogs.json、config/encounters.json）
    3. 從 encounters.json 注入啟用副本的 encounter_id 到爬蟲設定
    4. 決定掃描起始時間（環境變數 > config > 預設）
    5. 處理手動模式設定（retry_codes、only_codes）
    6. 載入現有資料，建立去重索引
    7. 初始化 Scraper 並執行掃描
    8. 儲存結果（clears.json、processed_codes.json、meta.json）

    【掃描模式說明】

    一般模式（預設）：
      - 呼叫 scraper.run()，依時間批次向前掃描
      - 新處理的 report code 加入 processed_codes，下次不重複處理
      - 適合 GitHub Actions 排程自動執行

    retry_report_codes 模式：
      - 在 config/fflogs.json 設定 "retry_report_codes": ["ABC123", ...]
      - 啟動前從 processed_codes 移除這些 code，使其在一般掃描中被重新處理
      - 適合需要重抓特定報告（例如 FFLogs 資料修正後）

    only_report_codes 模式（手動補抓）：
      - 在 config/fflogs.json 設定 "only_report_codes": ["ABC123", ...]
      - 跳過一般掃描，直接處理指定 code
      - 不更新 processed_codes，不影響正常掃描進度
      - 適合補抓遺漏的特定報告
    """

    # ── 步驟 1：驗證 API 憑證 ─────────────────────────────────────────────────

    # 從環境變數讀取憑證；lstrip('﻿') 移除可能的 BOM 字元（Windows 環境下的常見問題）
    client_id     = os.environ.get("FFLOGS_CLIENT_ID", "").lstrip('﻿').strip()
    client_secret = os.environ.get("FFLOGS_CLIENT_SECRET", "").lstrip('﻿').strip()

    if not client_id or not client_secret:
        # 不在錯誤訊息中印出憑證本身，只提示缺少設定
        print("ERROR: FFLOGS_CLIENT_ID / FFLOGS_CLIENT_SECRET not set", flush=True)
        sys.exit(1)

    # ── 步驟 2：載入設定檔 ───────────────────────────────────────────────────

    fflogs_cfg     = _load_fflogs_cfg()
    encounters_cfg = _load_encounters_cfg()

    # ── 步驟 3：從 encounters.json 注入啟用副本的 encounter_id ────────────────

    # encounters.json 是副本的真實來源（Single Source of Truth）
    # 將已啟用（enabled=true）的副本 ID 注入 fflogs_cfg["encounter_ids"]
    # 若 encounters.json 為空，Scraper 使用 scraper_core.py 中的硬編碼預設值
    if encounters_cfg:
        enabled_ids = [e["encounter_id"] for e in encounters_cfg if e.get("enabled", True)]
        if enabled_ids:
            fflogs_cfg["encounter_ids"] = enabled_ids
            print(f"[設定] 已啟用副本 ID：{enabled_ids}", flush=True)

    # ── 步驟 4：決定掃描起始時間 ─────────────────────────────────────────────

    # 優先級：環境變數 START_DT > config/fflogs.json 的 scan_start_date > 硬編碼預設
    default_start_str = fflogs_cfg.get("scan_start_date", "2026-01-01")
    start_ms = _parse_dt_ms(os.environ.get("START_DT", default_start_str)) or 0
    print(f"[設定] 掃描起始：{datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC", flush=True)

    # ── 步驟 5：處理手動模式設定 ─────────────────────────────────────────────

    # 從 config 讀取手動補抓設定（空字串過濾掉，防止設定失誤）
    retry_codes = [c for c in fflogs_cfg.get("retry_report_codes", []) if c]
    only_codes  = [c for c in fflogs_cfg.get("only_report_codes", [])  if c]

    # ── 步驟 6：載入現有資料，建立去重索引 ──────────────────────────────────

    raw_clears      = _load_clears()
    clears          = [ClearRecord.from_dict(d) for d in raw_clears]
    print(f"[載入] 現有通關紀錄：{len(clears)} 筆", flush=True)

    # seen_keys：code:fight_id 唯一鍵集合，防止同一戰鬥被記錄兩次
    seen_keys = {f"{c.code}:{c.fight_id}" for c in clears}

    # seen_clear_sigs：跨報告去重簽名（玩家組合 + 通關時間），防止同一通關因不同 report 被重複記錄
    # 格式：sorted(players).join("|") + ":" + clear_dt_ms
    seen_clear_sigs = {"|".join(sorted(c.players)) + ":" + str(c.clear_dt_ms) for c in clears}

    # processed_codes：已完整處理的 report code，跨執行持久化
    processed_codes = _load_processed_codes()
    print(f"[載入] 已處理 report：{len(processed_codes)} 個", flush=True)

    # retry_report_codes 處理：從 processed_codes 移除指定 code，使其在一般掃描中被重新拉取
    # 使用情境：FFLogs 更新了已存在報告的資料（例如補充 kill 旗標），需要強制重抓
    if retry_codes:
        removed = processed_codes & set(retry_codes)
        if removed:
            processed_codes -= removed
            print(f"[retry] 從 processed_codes 移除 {len(removed)} 個 code 以強制重抓：{sorted(removed)}", flush=True)
        else:
            print(f"[retry] retry_report_codes 中的 code 不在 processed_codes 內，將在一般掃描中處理", flush=True)

    # ── 步驟 7：初始化 Scraper 並設定回呼 ────────────────────────────────────

    # 本執行回圈收集到的新通關紀錄
    new_clears: list = []

    # 本次執行中新處理的 report code（由 on_checkpoint 累積）
    processed_in_run: set = set()

    def on_log(msg: str) -> None:
        """將 Scraper 的日誌訊息印出，附加時間戳記。"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

    def on_clear(rec: ClearRecord) -> None:
        """接收新通關紀錄，加入本次執行清單並印出摘要。"""
        new_clears.append(rec)
        print(f"  ✓ 通關: {rec.encounter} | {', '.join(rec.players)}", flush=True)

    def on_checkpoint(_batch_start_ms: int, new_codes: set) -> None:
        """
        每批次掃描完成後的檢查點回呼。

        Scraper 在每個時間批次結束時呼叫此函式，傳入本批次新處理的 code 集合。
        headless runner 在此累積 processed_in_run，待掃描全部完成後一次寫入檔案。
        （GUI 模式下，此回呼用於即時儲存檢查點，防止中斷丟失進度）
        """
        processed_in_run.update(new_codes)

    scraper = Scraper(
        on_log         = on_log,
        on_clear       = on_clear,
        on_status      = lambda _: None,   # headless 不需更新狀態列
        on_done        = lambda _: None,   # 完成後由本腳本處理輸出
        on_progress    = None,             # headless 不需進度條
        on_checkpoint  = on_checkpoint,
        bests_path     = BESTS_PATH,
        start_from_ms  = start_ms,
        end_from_ms    = None,             # 不設結束時間（掃描到現在）
        seen_keys       = seen_keys,
        processed_codes = processed_codes,
        seen_clear_sigs = seen_clear_sigs,
        client_id      = client_id,
        client_secret  = client_secret,
        cfg            = fflogs_cfg,       # 注入設定（含 encounter_ids、限速參數等）
    )

    # ── 步驟 7b：執行掃描 ────────────────────────────────────────────────────

    if only_codes:
        # 手動補抓模式：只處理指定的 report code，跳過時間批次掃描
        # 此模式不更新 processed_codes，確保不影響正常掃描的進度追蹤
        print(f"[only] 手動補抓模式，目標 {len(only_codes)} 個 report：{only_codes}", flush=True)
        scraper.run_manual(only_codes)
    else:
        # 一般掃描模式：按時間批次向前掃描（含 retry_codes 的重抓）
        scraper.run()

    # ── 步驟 8：儲存結果 ─────────────────────────────────────────────────────

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 8a. 儲存通關紀錄（有新通關時才寫入）
    if new_clears:
        clears.extend(new_clears)

        # 寫入前再次全量去重：防止並發執行（例如手動觸發與排程同時跑）導致重複
        # 以「玩家組合 + 通關時間」為去重簽名，與 seen_clear_sigs 邏輯一致
        seen_sigs: set = set()
        deduped: list = []
        for c in clears:
            sig = "|".join(sorted(c.players)) + ":" + str(c.clear_dt_ms)
            if sig not in seen_sigs:
                seen_sigs.add(sig)
                deduped.append(c)

        removed = len(clears) - len(deduped)
        if removed:
            print(f"  dedup: 去除 {removed} 筆重複通關紀錄", flush=True)

        CLEARS_PATH.write_text(
            json.dumps([c.to_dict() for c in deduped], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"儲存完成：新增 {len(new_clears)} 筆，共 {len(deduped)} 筆通關紀錄", flush=True)
    else:
        print("本次執行無新通關紀錄", flush=True)

    # 8b. 儲存 processed_codes（only 模式不更新，保持掃描進度不受影響）
    if not only_codes:
        processed_codes |= processed_in_run
        CODES_PATH.write_text(
            json.dumps(sorted(processed_codes), ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"processed_codes 已更新：共 {len(processed_codes)} 個 report（本次新增 {len(processed_in_run)} 個）", flush=True)

    # 8c. 更新 meta.json（前端用於顯示最後更新時間）
    updated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    META_PATH.write_text(
        json.dumps({"updated_at": updated_at}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"完成。updated_at={updated_at} UTC", flush=True)

    # 8d. 產生分割 JSON（讓前端按副本按需載入，大幅降低首次載入流量）
    print("產生分割 JSON...", flush=True)
    _write_split_data(DATA_DIR)
    print("分割完成。", flush=True)

    # 8e. 清空 config/fflogs.json 中的一次性欄位（避免下次執行重複處理）
    if retry_codes or only_codes:
        _clear_manual_codes(FFLOGS_CFG_PATH)


def _clear_manual_codes(cfg_path: Path) -> None:
    """執行完畢後將 config/fflogs.json 的 retry/only_report_codes 清空為 []。"""
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        changed = False
        for key in ("retry_report_codes", "only_report_codes"):
            if cfg.get(key):
                cfg[key] = []
                changed = True
        if changed:
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[設定] retry/only_report_codes 已清空", flush=True)
    except Exception as e:
        print(f"[警告] 無法清空 manual codes：{e}", flush=True)


def _detect_encounter_id(encounter_name: str):
    """
    從 FFLogs fight name 推導 encounter_id，邏輯與前端 detectEncounterId() 一致。
    """
    n = encounter_name.lower()
    if any(kw in n for kw in ('twintania', 'nael', 'bahamut prime', 'golden bahamut')):
        return 1073
    if 'garuda' in n or 'ifrit' in n or 'titan' in n or ('ultima' in n and 'alexander' not in n):
        return 1074
    if 'living liquid' in n or 'cruise chaser' in n or 'alexander' in n or 'brute justice' in n:
        return 1075
    if any(kw in n for kw in ('adelphel', 'thordan', 'nidhogg', 'hraesvelgr', 'estinien',
                               'dragon king', 'dragonsong', 'left eye', 'right eye')):
        return 1076
    if 'omega' in n:
        return 1077
    return None


def _write_split_data(data_dir: Path) -> None:
    """
    讀取合併的 player_bests.json 與 clears.json，產生按副本與功能分割的 JSON 檔案，
    讓前端可以按需載入，避免每次載入全量 3.4 MB 資料。

    輸出：
      leaderboard_{eid}.json  — 該副本所有玩家最佳成績（含 _key 欄位，array 格式）
      clears_{eid}.json       — 該副本所有通關紀錄（含 _eid 欄位，array 格式）
      players_index.json      — 全站玩家名稱+伺服器清單（搜尋用，去重後）
    """
    bests_path  = data_dir / "player_bests.json"
    clears_path = data_dir / "clears.json"

    bests_dict: dict = {}
    if bests_path.exists():
        bests_dict = json.loads(bests_path.read_text(encoding="utf-8"))

    clears_list: list = []
    if clears_path.exists():
        clears_list = json.loads(clears_path.read_text(encoding="utf-8"))

    # ── leaderboard_{eid}.json：player_bests 依 encounter_id 分割 ──────────────
    lb_by_eid: dict[int, list] = {}
    players_set: set[tuple] = set()

    for key, rec in bests_dict.items():
        eid = rec.get("encounter_id")
        if not eid:
            continue
        lb_by_eid.setdefault(eid, []).append({"_key": key, **rec})
        name, server = rec.get("name", ""), rec.get("server", "")
        if name:
            players_set.add((name, server))

    for eid, records in lb_by_eid.items():
        path = data_dir / f"leaderboard_{eid}.json"
        path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        print(f"  分割: leaderboard_{eid}.json ({len(records)} 筆)", flush=True)

    # ── clears_{eid}.json：clears 依副本分割（fight name → encounter_id） ───────
    cl_by_eid: dict[int, list] = {}

    for c in clears_list:
        eid = _detect_encounter_id(c.get("encounter", ""))
        if not eid:
            continue
        cl_by_eid.setdefault(eid, []).append({"_eid": eid, **c})

    for eid, records in cl_by_eid.items():
        path = data_dir / f"clears_{eid}.json"
        path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        print(f"  分割: clears_{eid}.json ({len(records)} 筆)", flush=True)

    # ── players_index.json：全站玩家索引（搜尋用） ────────────────────────────
    players_index = sorted(
        [{"name": n, "server": s} for n, s in players_set],
        key=lambda x: x["name"].lower(),
    )
    idx_path = data_dir / "players_index.json"
    idx_path.write_text(json.dumps(players_index, ensure_ascii=False), encoding="utf-8")
    print(f"  分割: players_index.json ({len(players_index)} 位玩家)", flush=True)


if __name__ == "__main__":
    main()
