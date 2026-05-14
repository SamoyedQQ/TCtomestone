"""backfill_jobs.py — 為 clears.json 中缺少 jobs 欄位的記錄補充職業資訊

步驟：
  1. 先從 player_bests.json 免費補（report_code + fight_id 精確對應）
  2. 剩餘仍缺的玩家才呼叫 FFLogs DETAIL_QUERY

使用方式：
  set FFLOGS_CLIENT_ID=xxx
  set FFLOGS_CLIENT_SECRET=yyy
  python backfill_jobs.py
"""
import json
import os
import time
from pathlib import Path

import requests

# Load .env if present (simple parser, no extra dependency)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

OAUTH_URL = "https://www.fflogs.com/oauth/token"
API_URL   = "https://www.fflogs.com/api/v2/client"
FIGHT_DELAY = 1.5

CLEARS_PATH = Path("docs/data/clears.json")
BESTS_PATH  = Path("docs/data/player_bests.json")

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


def get_token(client_id: str, client_secret: str) -> str:
    r = requests.post(OAUTH_URL, data={"grant_type": "client_credentials"},
                      auth=(client_id, client_secret), timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def gql(token: str, query: str, variables: dict) -> dict:
    for attempt in range(5):
        r = requests.post(API_URL,
                          json={"query": query, "variables": variables},
                          headers={"Authorization": f"Bearer {token}"},
                          timeout=30)
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
    raise RuntimeError("重試 5 次失敗")


def main():
    client_id     = os.environ.get("FFLOGS_CLIENT_ID", "").lstrip("﻿").strip()
    client_secret = os.environ.get("FFLOGS_CLIENT_SECRET", "").lstrip("﻿").strip()

    clears    = json.loads(CLEARS_PATH.read_text(encoding="utf-8"))
    bests_raw = json.loads(BESTS_PATH.read_text(encoding="utf-8"))

    # ── Step 1: 從 player_bests.json 免費補 ──────────────────────────────────
    # key: "report_code:fight_id:Name@Server" → job
    pb_map: dict = {}
    for rec in bests_raw.values():
        rc  = rec.get("report_code")
        fid = rec.get("fight_id")
        nm  = rec.get("name")
        srv = rec.get("server")
        job = rec.get("job")
        if rc and fid and nm and srv and job and job != "Unknown":
            pb_map[f"{rc}:{fid}:{nm}@{srv}"] = job

    free_filled = 0
    needs_api: list = []   # (clear_dict, [missing_player_strings])

    for c in clears:
        if "jobs" not in c:
            c["jobs"] = {}
        jobs = c["jobs"]
        code = c["code"]
        fid  = c["fight_id"]
        missing = []
        for p in c["players"]:
            if p in jobs:
                continue
            key = f"{code}:{fid}:{p}"
            if key in pb_map:
                jobs[p] = pb_map[key]
                free_filled += 1
            else:
                missing.append(p)
        if missing:
            needs_api.append((c, missing))

    print(f"從 player_bests 補填：{free_filled} 筆")
    print(f"仍需 API 查詢的場次：{len(needs_api)} 場")

    # ── Step 2: API 補填 ──────────────────────────────────────────────────────
    if needs_api:
        if not client_id or not client_secret:
            print("\n[!] 未設定 FFLOGS_CLIENT_ID / FFLOGS_CLIENT_SECRET，跳過 API 補填")
            print("  請設定環境變數後重新執行以補齊剩餘記錄")
        else:
            print("\n取得 OAuth Token...")
            token = get_token(client_id, client_secret)
            pts_start = None
            api_filled = 0

            for i, (c, missing) in enumerate(needs_api, 1):
                code = c["code"]
                fid  = c["fight_id"]
                time.sleep(FIGHT_DELAY)
                try:
                    data = gql(token, DETAIL_QUERY, {"code": code, "fightIDs": [fid]})
                except Exception as e:
                    print(f"  [{i}/{len(needs_api)}] {code}:{fid} 查詢失敗: {e}")
                    continue

                pts_now = data["rateLimitData"]["pointsSpentThisHour"]
                if pts_start is None:
                    pts_start = pts_now
                pts_used = pts_now - pts_start

                entries      = data["reportData"]["report"]["table"]["data"]["entries"]
                tbl_by_name  = {e["name"]: e for e in entries}

                jobs = c["jobs"]
                for p in missing:
                    name = p.split("@")[0]
                    tbl  = tbl_by_name.get(name)
                    if tbl:
                        job = tbl.get("type", "Unknown")
                        if job and job != "Unknown":
                            jobs[p] = job
                            api_filled += 1

                n_filled = len(c['jobs'])
                print(f"  [{i}/{len(needs_api)}] {code}:{fid}  jobs={n_filled}  [{pts_used}pt]")

            print(f"\n從 API 補填：{api_filled} 筆")

    # ── 儲存 ──────────────────────────────────────────────────────────────────
    CLEARS_PATH.write_text(
        json.dumps(clears, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("已儲存 clears.json")


if __name__ == "__main__":
    main()
