"""Re-scrape UCoB (1073) data from known report codes in player_bests.json.

Rules:
  - Clear  : fightPercentage == 80
  - Wipe   : lowest fightPercentage per TC player (per report)

Rebuilds all encounter_id=1073 entries in player_bests.json and
updates clears.json with any UCoB clears found.
"""

import json
import sys
import time
from pathlib import Path

import requests

# ── paths ─────────────────────────────────────────────────────────────────────

DATA_DIR     = Path("docs/data")
CONFIG_PATH  = DATA_DIR / "config.json"
BESTS_PATH   = DATA_DIR / "player_bests.json"
CLEARS_PATH  = DATA_DIR / "clears.json"

OAUTH_URL = "https://www.fflogs.com/oauth/token"
API_URL   = "https://www.fflogs.com/api/v2/client"
ENC_UCOB  = 1073

TC_SERVERS = {"奧汀", "伊弗利特", "迦樓羅", "巴哈姆特", "鳳凰", "泰坦", "利維坦"}

FIGHTS_QUERY = """
query ($code: String) {
  rateLimitData { pointsSpentThisHour }
  reportData {
    report(code: $code) {
      title
      startTime
      masterData { actors(type: "Player") { id name server subType } }
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

# ── helpers ───────────────────────────────────────────────────────────────────

def _tc_actors(fight: dict, by_id: dict) -> list:
    return [
        a for fid in fight.get("friendlyPlayers", [])
        if (a := by_id.get(fid)) and a.get("server") in TC_SERVERS
    ]


def _tc_players(by_id: dict, ids: list) -> list:
    return [
        f"{a['name']}@{a['server']}"
        for fid in ids
        if (a := by_id.get(fid)) and a.get("server") in TC_SERVERS
    ]


def _gql(token: str, query: str, variables: dict) -> dict:
    for attempt in range(5):
        try:
            r = requests.post(
                API_URL,
                json={"query": query, "variables": variables},
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            if r.status_code == 429:
                wait = int(r.headers.get("retry-after", 60))
                print(f"  [429] 速率限制，等待 {wait}s...", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            d = r.json()
            if "errors" in d:
                raise RuntimeError(d["errors"])
            return d["data"]
        except requests.RequestException as e:
            if attempt == 4:
                raise
            print(f"  重試 ({attempt+1}/5): {e}", flush=True)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("gql failed after 5 attempts")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    creds = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    r = requests.post(
        OAUTH_URL,
        data={"grant_type": "client_credentials"},
        auth=(creds["client_id"].lstrip("﻿").strip(),
              creds["client_secret"].lstrip("﻿").strip()),
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    print("OAuth OK", flush=True)

    # ── collect codes from existing player_bests ──────────────────────────────
    raw_bests = json.loads(BESTS_PATH.read_text(encoding="utf-8"))
    ucob_codes = sorted({v["report_code"] for v in raw_bests.values()
                         if v.get("encounter_id") == ENC_UCOB})
    print(f"Found {len(ucob_codes)} UCoB report codes to re-scrape", flush=True)

    # ── load existing clears (non-UCoB kept as-is) ───────────────────────────
    raw_clears = json.loads(CLEARS_PATH.read_text(encoding="utf-8")) \
                 if CLEARS_PATH.exists() else []
    # Strip all previous UCoB clears — will be rebuilt fresh
    non_ucob_clears = [c for c in raw_clears if c.get("code") not in ucob_codes]
    existing_clear_keys = {f"{c['code']}:{c['fight_id']}" for c in non_ucob_clears}

    # ── strip UCoB entries from bests; keep everything else ──────────────────
    kept_bests = {k: v for k, v in raw_bests.items()
                  if v.get("encounter_id") != ENC_UCOB}
    new_bests: dict = {}   # key → dict
    new_clears: list = []
    seen_clear_keys: set = set()

    pts_start = None

    for code in ucob_codes:
        print(f"\n[{code}] FIGHTS_QUERY...", flush=True)
        time.sleep(1)

        fdata = _gql(token, FIGHTS_QUERY, {"code": code})
        pts_now = fdata["rateLimitData"]["pointsSpentThisHour"]
        if pts_start is None:
            pts_start = pts_now
        pts_used = max(0, pts_now - pts_start)
        print(f"  pts used so far: {pts_used}", flush=True)

        rep      = fdata["reportData"]["report"]
        rep_start = rep["startTime"]
        title    = rep.get("title", "")
        by_id    = {a["id"]: a for a in rep["masterData"]["actors"]}

        ucob_fights = [f for f in rep["fights"] if f.get("encounterID") == ENC_UCOB]
        if not ucob_fights:
            print("  no UCoB fights, skip", flush=True)
            continue

        # Real UCoB clear: reached Bahamut Prime (P3+), fight lasted ≥10 min, fp=80
        clear_fights = [
            f for f in ucob_fights
            if f.get("fightPercentage") == 80
            and "Bahamut Prime" in f.get("name", "")
            and (f["endTime"] - f["startTime"]) >= 600_000
        ]
        wipe_fights  = [f for f in ucob_fights if f not in clear_fights]
        print(f"  UCoB fights: {len(ucob_fights)}  clears: {len(clear_fights)}  wipes: {len(wipe_fights)}", flush=True)

        # ── process clears ────────────────────────────────────────────────────
        for fight in clear_fights:
            tc_in = _tc_actors(fight, by_id)
            if not tc_in:
                continue

            fight_id = fight["id"]
            ck = f"{code}:{fight_id}"

            # ClearRecord
            if ck not in seen_clear_keys and ck not in existing_clear_keys:
                players = _tc_players(by_id, fight.get("friendlyPlayers", []))
                if players:
                    new_clears.append({
                        "code":        code,
                        "title":       title,
                        "encounter":   fight.get("name", "Unknown"),
                        "players":     players,
                        "fight_id":    fight_id,
                        "duration_ms": fight["endTime"] - fight["startTime"],
                        "clear_dt_ms": rep_start + fight["endTime"],
                    })
                    seen_clear_keys.add(ck)
                    print(f"  ✓ 通關: {fight.get('name','')} | {', '.join(players)}", flush=True)

            # PlayerBest (clear) — fetch DPS
            time.sleep(1)
            ddata = _gql(token, DETAIL_QUERY, {"code": code, "fightIDs": [fight_id]})
            pts_now = ddata["rateLimitData"]["pointsSpentThisHour"]
            pts_used = max(0, pts_now - pts_start)

            table_data = ddata["reportData"]["report"]["table"]["data"]
            total_time_ms      = table_data.get("totalTime") or (fight["endTime"] - fight["startTime"])
            damage_downtime_ms = table_data.get("damageDowntime") or 0
            fight_s = (total_time_ms - damage_downtime_ms) / 1000
            if fight_s <= 0:
                fight_s = (fight["endTime"] - fight["startTime"]) / 1000

            table_by_name = {e.get("name", ""): e for e in table_data["entries"]}

            for p in tc_in:
                name   = p["name"]
                server = p.get("server", "")
                tbl    = table_by_name.get(name, {})
                rdps   = tbl.get("totalRDPS", 0.0) / fight_s
                adps   = tbl.get("totalADPS", 0.0) / fight_s
                parse  = float(tbl.get("rankPercent") or 0.0)
                job    = tbl.get("type", "Unknown")
                guid   = tbl.get("guid", 0)

                pb_key = f"{name}@{server}:{ENC_UCOB}:{job}"
                entry = {
                    "name": name, "server": server,
                    "encounter_id": ENC_UCOB,
                    "encounter": fight.get("name", "Unknown"),
                    "is_clear": True, "boss_hp_pct": 0.0,
                    "rdps": rdps, "adps": adps, "parse_pct": parse,
                    "job": job, "char_id": guid,
                    "report_code": code, "fight_id": fight_id,
                    "timestamp_ms": rep_start + fight["endTime"],
                    "duration_ms": fight["endTime"] - fight["startTime"],
                }
                existing = new_bests.get(pb_key)
                if existing is None or rdps > existing["rdps"]:
                    new_bests[pb_key] = entry
                    print(f"  ↑ 通關best: {name}@{server} [{job}] rDPS={rdps:.0f}", flush=True)

        # ── process wipes — best per player = min fightPercentage ─────────────
        # group by player: { "name@server" → (fight, fight_pct) }
        player_best_wipe: dict = {}
        for fight in wipe_fights:
            fp = fight.get("fightPercentage")
            if fp is None:
                continue
            for p in _tc_actors(fight, by_id):
                pk = f"{p['name']}@{p.get('server','')}"
                existing = player_best_wipe.get(pk)
                if existing is None or fp < existing[1]:
                    player_best_wipe[pk] = (fight, fp, p)

        if not player_best_wipe:
            continue

        # one DETAIL_QUERY per unique best fight
        best_fight_ids = list({f["id"] for f, _, _ in player_best_wipe.values()})
        time.sleep(1)
        ddata = _gql(token, DETAIL_QUERY, {"code": code, "fightIDs": best_fight_ids})
        pts_now = ddata["rateLimitData"]["pointsSpentThisHour"]
        pts_used = max(0, pts_now - pts_start)
        print(f"  wipe DETAIL done, pts={pts_used}", flush=True)

        table_by_name = {e.get("name", ""): e
                         for e in ddata["reportData"]["report"]["table"]["data"]["entries"]}

        for pk, (fight, fp, p) in player_best_wipe.items():
            name   = p["name"]
            server = p.get("server", "")
            tbl    = table_by_name.get(name, {})
            job    = tbl.get("type") or p.get("subType") or "Unknown"
            guid   = tbl.get("guid", 0)

            pb_key = f"{name}@{server}:{ENC_UCOB}:_wipe"
            # Skip if player already has a clear
            has_clear = any(
                k.startswith(f"{name}@{server}:{ENC_UCOB}:") and not k.endswith(":_wipe")
                for k in new_bests
            )
            if has_clear:
                continue

            entry = {
                "name": name, "server": server,
                "encounter_id": ENC_UCOB,
                "encounter": fight.get("name", "Unknown"),
                "is_clear": False, "boss_hp_pct": fp,
                "rdps": 0.0, "adps": 0.0, "parse_pct": 0.0,
                "job": job, "char_id": guid,
                "report_code": code, "fight_id": fight["id"],
                "timestamp_ms": rep_start + fight["endTime"],
                "duration_ms": fight["endTime"] - fight["startTime"],
            }
            existing = new_bests.get(pb_key)
            if existing is None or fp < existing["boss_hp_pct"]:
                new_bests[pb_key] = entry
                print(f"  ↑ wipe best: {name}@{server} [{job}] fp={fp:.2f}%", flush=True)

    # ── merge and save ────────────────────────────────────────────────────────
    # kept_bests (non-UCoB) + new_bests (rebuilt UCoB)
    # For UCoB wipe keys: clear supersedes wipe
    final_bests = dict(kept_bests)
    for k, v in new_bests.items():
        if k.endswith(":_wipe"):
            name_server_enc = k[:-len(":_wipe")]
            # If any clear key exists for this player+enc, skip the wipe
            has_clear = any(
                fk.startswith(name_server_enc + ":") and not fk.endswith(":_wipe")
                for fk in new_bests
            )
            if has_clear:
                continue
        final_bests[k] = v

    BESTS_PATH.write_text(
        json.dumps(final_bests, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved player_bests.json ({len(final_bests)} entries, {len(new_bests)} UCoB rebuilt)", flush=True)

    # ── save clears ───────────────────────────────────────────────────────────
    if new_clears:
        all_clears = non_ucob_clears + new_clears
        CLEARS_PATH.write_text(
            json.dumps(all_clears, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Saved clears.json (+{len(new_clears)} UCoB clears)", flush=True)
    else:
        print("No new clears found.", flush=True)

    print("Done.", flush=True)


if __name__ == "__main__":
    main()
