"""ManualBackfill.py — 針對指定 FFLogs report+fight 強制重新抓取 rDPS 並更新本地資料

用途：
  - FFLogs 重算 rDPS 後，更新既有紀錄至最新數值（數字可能變高或變低）
  - 修補手動發現的 rDPS 誤差

用法：
  python ManualBackfill.py                       # 使用腳本內 TARGETS 設定
  python ManualBackfill.py <code> <fight_id>     # 命令列指定單筆
  python ManualBackfill.py <code>                # 補抓整份 report 所有通關場次

行為說明：
  - 與正常爬蟲相同：通關取更高 rDPS，不覆蓋已有更佳紀錄
  - 只更新 player_bests.json；不修改 clears.json、processed_codes.json
  - 不推進掃描進度

憑證：
  優先從專案根目錄的 .env 讀取；.env 不存在時 fallback 至環境變數
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

# ── 載入 .env（若存在）────────────────────────────────────────────────────────
def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())

_load_dotenv(Path(__file__).parent / ".env")

# ── 補抓目標設定（命令列未指定時使用）────────────────────────────────────────
# 格式：(report_code, fight_id)；fight_id=None 表示補抓整份 report 所有通關
TARGETS: list[tuple[str, int | None]] = [
    ("1fQ4pLrmnvzJZXT6", 6),
]

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
ROOT_DIR   = Path(__file__).parent
BESTS_PATH = ROOT_DIR / "docs" / "data" / "player_bests.json"

# ── FFLogs API ────────────────────────────────────────────────────────────────
OAUTH_URL = "https://www.fflogs.com/oauth/token"
API_URL   = "https://www.fflogs.com/api/v2/client"

TC_SERVERS    = {"奧汀", "伊弗利特", "迦樓羅", "巴哈姆特", "鳳凰", "泰坦", "利維坦"}
ULTIMATE_IDS  = {1073, 1074, 1075, 1076, 1077, 1079}

FIGHTS_QUERY = """
query ($code: String) {
  rateLimitData { pointsSpentThisHour }
  reportData {
    report(code: $code) {
      title
      startTime
      masterData { actors(type: "Player") { id name server subType } }
      rankings
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


# ── OAuth ─────────────────────────────────────────────────────────────────────

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
    """送出 GraphQL 請求，自動處理 429 限流（最多重試 5 次）。"""
    for attempt in range(5):
        r = requests.post(
            API_URL,
            json={"query": query, "variables": variables},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if r.status_code == 429:
            wait = int(r.headers.get("retry-after", 60))
            print(f"  [429] 速率限制，等待 {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        d = r.json()
        if "errors" in d:
            raise RuntimeError(d["errors"])
        return d["data"]
    raise RuntimeError("重試 5 次仍失敗")


# ── Rankings duration 解析（與 scraper_core._parse_rankings_duration 相同）────

def _parse_rankings_duration(rankings_raw) -> dict:
    if not rankings_raw:
        return {}
    try:
        raw = rankings_raw if isinstance(rankings_raw, dict) else json.loads(rankings_raw)
        return {f["fightID"]: f["duration"] for f in raw.get("data", []) if "duration" in f}
    except Exception:
        return {}


# ── UCoB 通關判定（與 scraper_core._is_kill 相同）────────────────────────────

def _is_kill(fight: dict) -> bool:
    if fight.get("encounterID") == 1073:
        return (
            fight.get("fightPercentage") == 80
            and "Bahamut Prime" in fight.get("name", "")
            and (fight["endTime"] - fight["startTime"]) >= 780_000
        )
    return bool(fight.get("kill"))


# ── 核心補抓邏輯 ──────────────────────────────────────────────────────────────

def patch_report(token: str, code: str, target_fight_ids: list[int] | None,
                 bests: dict) -> int:
    """補抓單份 report，強制更新 player_bests。回傳更新筆數。"""
    print(f"\n[{code}] 取得戰鬥列表...")
    fdata = gql(token, FIGHTS_QUERY, {"code": code})
    rep = fdata["reportData"]["report"]
    if rep is None:
        print(f"  [跳過] report 不存在或為私密")
        return 0

    report_start = rep["startTime"]
    by_id = {a["id"]: a for a in rep["masterData"]["actors"]}
    rankings_duration = _parse_rankings_duration(rep.get("rankings"))

    # 篩選目標場次（通關 + 絕境戰 + 指定 fight_id）
    ult_fights = [f for f in rep["fights"] if f.get("encounterID") in ULTIMATE_IDS]
    kill_fights = [f for f in ult_fights if _is_kill(f)]

    if target_fight_ids:
        kill_fights = [f for f in kill_fights if f["id"] in target_fight_ids]
        if not kill_fights:
            print(f"  [警告] fight {target_fight_ids} 不存在或非通關場次")
            return 0

    total_updated = 0

    for fight in kill_fights:
        fid = fight["id"]
        enc_id = fight["encounterID"]

        # 確認有繁中服玩家
        tc_actors = [
            a for aid in fight.get("friendlyPlayers", [])
            if (a := by_id.get(aid)) and a.get("server") in TC_SERVERS
        ]
        if not tc_actors:
            print(f"  [跳過] fight {fid}: 無繁中服玩家")
            continue

        print(f"  → fight {fid} 「{fight.get('name','')}」 取得傷害資料...")
        time.sleep(1)
        ddata = gql(token, DETAIL_QUERY, {"code": code, "fightIDs": [fid]})

        table_data = ddata["reportData"]["report"]["table"]["data"]
        if fid in rankings_duration:
            effective_ms = rankings_duration[fid]
            src = "rankings.duration"
        else:
            total_time_ms      = table_data.get("totalTime") or (fight["endTime"] - fight["startTime"])
            damage_downtime_ms = table_data.get("damageDowntime") or 0
            effective_ms       = total_time_ms - damage_downtime_ms
            src = "totalTime-downtime"
        fight_s = effective_ms / 1000 if effective_ms > 0 else (fight["endTime"] - fight["startTime"]) / 1000

        table_by_name = {e.get("name", ""): e for e in table_data["entries"]}
        pts_used = ddata["rateLimitData"]["pointsSpentThisHour"]
        print(f"     有效時長: {fight_s:.3f}s（{src}）  [已用 {pts_used}pt]")

        for p in tc_actors:
            name   = p["name"]
            server = p.get("server", "")
            tbl    = table_by_name.get(name)
            if not tbl:
                continue

            job     = tbl.get("type", "Unknown")
            rdps    = tbl.get("totalRDPS", 0.0) / fight_s
            adps    = tbl.get("totalADPS", 0.0) / fight_s
            parse_pct = float(tbl.get("rankPercent") or 0.0)
            char_id = tbl.get("guid", 0)

            bkey = f"{name}@{server}:{enc_id}:{job}"
            old  = bests.get(bkey)
            old_rdps = old.get("rdps", 0.0) if old else None

            # 與正常爬蟲相同：只有新值更高才更新
            if old is not None and rdps <= old_rdps:
                print(f"     - {name}@{server} [{job}]  rDPS: {old_rdps:.1f} >= {rdps:.1f}，略過")
                continue

            bests[bkey] = {
                "name": name, "server": server,
                "encounter_id": enc_id,
                "encounter": fight.get("name", "Unknown"),
                "is_clear": True, "boss_hp_pct": 0.0,
                "rdps": rdps, "adps": adps, "parse_pct": parse_pct,
                "job": job, "char_id": char_id,
                "report_code": code, "fight_id": fid,
                "timestamp_ms": report_start + fight["endTime"],
                "duration_ms": fight["endTime"] - fight["startTime"],
                "phase_reached": 0,
            }

            delta = f"{rdps - old_rdps:+.1f}" if old_rdps is not None else "新增"
            print(f"     ★ {name}@{server} [{job}]  rDPS: {old_rdps:.1f} → {rdps:.1f}  ({delta})")
            total_updated += 1

    return total_updated


# ── 主程式 ────────────────────────────────────────────────────────────────────

def main():
    # 解析命令列
    targets = list(TARGETS)
    if len(sys.argv) >= 3:
        targets = [(sys.argv[1], int(sys.argv[2]))]
    elif len(sys.argv) == 2:
        targets = [(sys.argv[1], None)]

    # 讀取憑證
    client_id     = os.environ.get("FFLOGS_CLIENT_ID", "")
    client_secret = os.environ.get("FFLOGS_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("錯誤：請設定環境變數 FFLOGS_CLIENT_ID 與 FFLOGS_CLIENT_SECRET")
        sys.exit(1)

    # 載入 player_bests.json
    bests: dict = {}
    if BESTS_PATH.exists():
        bests = json.loads(BESTS_PATH.read_text(encoding="utf-8"))

    print("取得 OAuth Token...")
    token = get_token(client_id, client_secret)

    total = 0
    for code, fight_id in targets:
        fids = [fight_id] if fight_id is not None else None
        total += patch_report(token, code, fids, bests)

    # 寫回 player_bests.json
    if total > 0:
        BESTS_PATH.write_text(json.dumps(bests, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n完成：共更新 {total} 筆，已寫入 {BESTS_PATH}")
    else:
        print("\n無任何紀錄需要更新")


if __name__ == "__main__":
    main()
