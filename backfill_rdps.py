"""backfill_rdps.py — 全量回填 player_bests 的 rDPS（改用 FFLogs rankings.duration 分母）

背景
----
早期通關在 FFLogs 尚未產生 ranking（duration）時就被抓取，rDPS 分母退回 totalTime
（全程時長），而 FFLogs 網頁實際使用 rankings.duration（已扣 downtime / 修剪尾段，
略短於全程）。兩者相差導致入庫 rDPS 系統性「偏低」；報告一旦進入 processed_codes
便不再重抓，舊值因此被凍結。

本工具逐一重抓每筆 best 的「來源報告」，改用與 scraper_core 完全相同的分母邏輯
（rankings.duration → zone-62 估算 → totalTime − downtime）重算 rDPS / aDPS，
再以 PlayerBests.update_if_better() 校正。

安全性
------
所有誤差皆為「偏低」（rankings.duration ≤ totalTime ⇒ 正確 rDPS ≥ 既存值），
故 update_if_better 只會把偏低的值往上修，不會破壞任何已正確的紀錄。

特性
----
  - 可續跑：進度寫入 docs/data/backfill_state.json，中斷 / 分批後重跑自動接續
  - 預算感知：pointsSpentThisHour 接近上限即存檔結束（exit code 75），
              由 CI 或人工於下個整點再次啟動，最終跨多個批次自動完成
  - 429 自動退避（讀 retry-after）

用法
----
  python backfill_rdps.py            # 處理一批，直到逼近點數上限或全部完成
  python backfill_rdps.py --reset    # 清除進度從頭重跑

完成後務必重建 leaderboard 分割檔：
  python -c "from headless_run import _write_split_data; from pathlib import Path; _write_split_data(Path('docs/data'))"
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

# 與爬蟲共用資料模型與分母邏輯，確保回填結果與正常爬蟲完全一致
from scraper_core import (
    OAUTH_URL, API_URL, TC_SERVERS, ULTIMATE_IDS,
    PlayerBest, PlayerBests, _is_kill, _parse_rankings_duration,
    _ENCOUNTER_DOWNTIME_ESTIMATE,
)

ROOT_DIR   = Path(__file__).parent
BESTS_PATH = ROOT_DIR / "docs" / "data" / "player_bests.json"
STATE_PATH = ROOT_DIR / "docs" / "data" / "backfill_state.json"

POINT_SOFT_LIMIT = 3400   # 逼近 FFLogs 3600/hr 時停手，留緩衝給其他流程
SAVE_EVERY       = 25     # 每處理 N 份報告存一次檔，避免中斷遺失進度
EXIT_BUDGET      = 75     # 因預算用盡而中止的 exit code（與「全部完成」區隔）


# ── .env 載入 ─────────────────────────────────────────────────────────────────
def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv(ROOT_DIR / ".env")

FIGHTS_QUERY = """
query ($code: String) {
  rateLimitData { pointsSpentThisHour }
  reportData {
    report(code: $code) {
      startTime
      rankings
      masterData { actors(type: "Player") { id name server } }
      fights {
        id encounterID name kill startTime endTime friendlyPlayers fightPercentage
      }
    }
  }
}
"""

DETAIL_QUERY = """
query ($code: String, $fightIDs: [Int!]) {
  rateLimitData { pointsSpentThisHour }
  reportData {
    report(code: $code) {
      table(dataType: DamageDone, fightIDs: $fightIDs)
    }
  }
}
"""


# ── FFLogs API ────────────────────────────────────────────────────────────────
def get_token(client_id: str, client_secret: str) -> str:
    r = requests.post(
        OAUTH_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def gql(token: str, query: str, variables: dict) -> dict:
    """送出 GraphQL 請求，自動處理 429 限流（讀 retry-after，最多重試 6 次）。"""
    for _ in range(6):
        r = requests.post(
            API_URL,
            json={"query": query, "variables": variables},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if r.status_code == 429:
            wait = int(r.headers.get("retry-after", 60))
            print(f"  [429] 限流，等待 {wait}s...", flush=True)
            time.sleep(wait + 2)
            continue
        r.raise_for_status()
        d = r.json()
        if "errors" in d:
            raise RuntimeError(d["errors"])
        return d["data"]
    raise RuntimeError("429 連續 6 次仍失敗")


def _points(data: dict) -> int:
    try:
        return int(data["rateLimitData"]["pointsSpentThisHour"])
    except Exception:
        return 0


# ── 分母邏輯（與 scraper_core._process_kill_bests 完全相同）────────────────────
def _effective_seconds(fight: dict, rankings_duration: dict, table_data: dict) -> float:
    raw_ms = fight["endTime"] - fight["startTime"]
    enc_id = fight.get("encounterID")
    fid    = fight["id"]

    if rankings_duration and fid in rankings_duration:
        rd = rankings_duration[fid]
        # Zone-62 嵌入場次：rankings.duration 回傳近似全程（未扣 downtime），改用估算
        if rd > raw_ms - 50_000 and _ENCOUNTER_DOWNTIME_ESTIMATE.get(enc_id):
            effective_ms = raw_ms - _ENCOUNTER_DOWNTIME_ESTIMATE[enc_id]
        else:
            effective_ms = rd
    else:
        total_time_ms = table_data.get("totalTime") or raw_ms
        downtime      = table_data.get("damageDowntime") or 0
        if downtime == 0:
            downtime = _ENCOUNTER_DOWNTIME_ESTIMATE.get(enc_id, 0)
        effective_ms = total_time_ms - downtime

    return effective_ms / 1000 if effective_ms > 0 else raw_ms / 1000


# ── 進度狀態 ──────────────────────────────────────────────────────────────────
def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done_codes": [], "updated": 0}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _target_codes(recent_days: int | None = None) -> list[str]:
    """所有 best 紀錄的來源 report code（去重）。處理這些報告即可校正每一筆既存值。

    recent_days 有值時只回傳「通關時間在近 N 天內」之報告 —— 供 fix-forward 使用：
    新通關常在 FFLogs 尚未 ranking 時就入庫（分母退回 totalTime 而偏低），
    每日 CI 重跑近幾天的報告，待 FFLogs 完成 ranking 後即自動校正。
    """
    raw = json.loads(BESTS_PATH.read_text(encoding="utf-8"))
    cutoff_ms = None
    if recent_days is not None:
        cutoff_ms = int(time.time() * 1000) - recent_days * 86_400_000
    codes: dict[str, None] = {}
    for v in raw.values():
        c = v.get("report_code")
        if not c:
            continue
        if cutoff_ms is not None and (v.get("timestamp_ms") or 0) < cutoff_ms:
            continue
        codes.setdefault(c, None)
    return list(codes)


# ── 單份報告處理 ──────────────────────────────────────────────────────────────
def _process_report(token: str, code: str, bests: PlayerBests) -> tuple[int, int]:
    """重抓單份報告所有通關場次並校正。回傳 (更新筆數, 最新 pointsSpentThisHour)。"""
    fdata = gql(token, FIGHTS_QUERY, {"code": code})
    points = _points(fdata)
    rep = fdata["reportData"]["report"]
    if rep is None:
        # 報告已私密 / 刪除：無法重算，視為已處理（避免反覆重試）
        return 0, points

    report_start      = rep["startTime"]
    by_id             = {a["id"]: a for a in rep["masterData"]["actors"]}
    rankings_duration = _parse_rankings_duration(rep.get("rankings"))

    # 僅保留繁中服絕境戰的通關場次
    kill_fights = [
        f for f in rep["fights"]
        if f.get("encounterID") in ULTIMATE_IDS and _is_kill(f)
    ]

    updated = 0
    for fight in kill_fights:
        fid    = fight["id"]
        enc_id = fight["encounterID"]
        tc_actors = [
            a for aid in fight.get("friendlyPlayers", [])
            if (a := by_id.get(aid)) and a.get("server") in TC_SERVERS
        ]
        if not tc_actors:
            continue

        time.sleep(0.25)  # 輕度節流，降低 FFLogs 突發 429 機率
        ddata = gql(token, DETAIL_QUERY, {"code": code, "fightIDs": [fid]})
        points = _points(ddata)
        table_data = ddata["reportData"]["report"]["table"]["data"]
        fight_s = _effective_seconds(fight, rankings_duration, table_data)
        if fight_s <= 0:
            continue

        table_by_name = {e.get("name", ""): e for e in table_data["entries"]}
        for p in tc_actors:
            tbl = table_by_name.get(p["name"])
            if not tbl:
                continue
            pb = PlayerBest(
                name         = p["name"],
                server       = p.get("server", ""),
                encounter_id = enc_id,
                encounter    = fight.get("name", "Unknown"),
                is_clear     = True,
                boss_hp_pct  = 0.0,
                rdps         = tbl.get("totalRDPS", 0.0) / fight_s,
                adps         = tbl.get("totalADPS", 0.0) / fight_s,
                parse_pct    = float(tbl.get("rankPercent") or 0.0),
                job          = tbl.get("type", "Unknown"),
                char_id      = tbl.get("guid", 0),
                report_code  = code,
                fight_id     = fid,
                timestamp_ms = report_start + fight["endTime"],
                duration_ms  = fight["endTime"] - fight["startTime"],
                phase_reached= 0,
            )
            if bests.update_if_better(pb):
                updated += 1

    return updated, points


# ── 主程式 ────────────────────────────────────────────────────────────────────
def _parse_recent_days() -> int | None:
    for i, a in enumerate(sys.argv):
        if a == "--recent-days" and i + 1 < len(sys.argv):
            try:
                return max(1, int(sys.argv[i + 1]))
            except ValueError:
                return None
    return None


def main() -> None:
    if "--reset" in sys.argv and STATE_PATH.exists():
        STATE_PATH.unlink()
        print("已清除進度，將從頭重跑")

    client_id     = os.environ.get("FFLOGS_CLIENT_ID", "")
    client_secret = os.environ.get("FFLOGS_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("錯誤：請設定 FFLOGS_CLIENT_ID 與 FFLOGS_CLIENT_SECRET")
        sys.exit(1)

    recent_days = _parse_recent_days()
    # fix-forward 模式（--recent-days N）：只重跑近 N 天的報告且不使用持久進度，
    # 因為這些報告的 ranking 可能隨時間更新，需每次重新檢查。
    persist = recent_days is None

    bests = PlayerBests(BESTS_PATH)
    state = _load_state() if persist else {"done_codes": [], "updated": 0}
    done  = set(state["done_codes"])

    all_codes = _target_codes(recent_days)
    todo = [c for c in all_codes if c not in done]
    mode = "全量回填" if persist else f"fix-forward（近 {recent_days} 天）"
    print(f"[{mode}] 目標報告 {len(all_codes)} 份，已完成 {len(done)} 份，本批待處理 {len(todo)} 份")
    if not todo:
        print("沒有待處理報告 ✔")
        bests.save()
        return

    token = get_token(client_id, client_secret)
    processed_this_run = 0
    updated_this_run   = 0

    for i, code in enumerate(todo, 1):
        try:
            updated, points = _process_report(token, code, bests)
        except Exception as e:
            # 私密 / 已刪除報告會回 permission 錯誤：永久無法重算，標記完成以免每批重試
            if "permission" in str(e).lower():
                done.add(code)
                if persist:
                    state["done_codes"] = list(done)
                print(f"  [私密] {code}: 無權限，標記為已處理（既存值維持原樣）", flush=True)
            else:
                print(f"  [錯誤] {code}: {e}（暫時性，不標記完成，下批重試）", flush=True)
            continue

        done.add(code)
        updated_this_run += updated
        if persist:
            state["done_codes"] = list(done)
            state["updated"]    = state.get("updated", 0) + updated
        processed_this_run += 1
        if updated:
            print(f"  [{i}/{len(todo)}] {code}: 校正 {updated} 筆 (pts={points})", flush=True)

        if processed_this_run % SAVE_EVERY == 0:
            bests.save()
            if persist:
                _save_state(state)
            print(f"  …已存檔（本批 {processed_this_run} 份，本批校正 {updated_this_run} 筆）", flush=True)

        # 預算守門：逼近上限就收工，留待下批
        if points >= POINT_SOFT_LIMIT:
            bests.save()
            if persist:
                _save_state(state)
            print(f"\n逼近點數上限（pts={points}），本批處理 {processed_this_run} 份後暫停。"
                  f"\n剩餘 {len(todo) - i} 份，請於下個整點再次執行。")
            sys.exit(EXIT_BUDGET)

    bests.save()
    if persist:
        _save_state(state)
    remaining = len(all_codes) - len(done)
    print(f"\n本批完成 {processed_this_run} 份，本批校正 {updated_this_run} 筆，剩餘 {remaining} 份")
    if persist and remaining == 0:
        print("全部報告已回填完成 ✔（記得重建 leaderboard 分割檔）")


if __name__ == "__main__":
    main()
