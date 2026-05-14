"""Backfill phase_reached for existing player_bests wipe records."""
import json
import time
from collections import defaultdict
from pathlib import Path

import requests

from scraper_core import PlayerBest, PlayerBests, _wipe_phase

OAUTH_URL = "https://www.fflogs.com/oauth/token"
API_URL   = "https://www.fflogs.com/api/v2/client"
DATA_PATH = Path("docs/data/player_bests.json")
CONFIG_PATH = Path("docs/data/config.json")

TARGETS = {1073, 1074, 1075, 1076, 1077}


def get_token(client_id: str, client_secret: str) -> str:
    r = requests.post(OAUTH_URL, auth=(client_id, client_secret),
                      data={"grant_type": "client_credentials"})
    return r.json()["access_token"]


def gql(token: str, query: str, variables: dict) -> dict:
    r = requests.post(API_URL,
                      headers={"Authorization": f"Bearer {token}"},
                      json={"query": query, "variables": variables})
    return r.json()


ENEMY_NPCS_QUERY = """
query ($code: String, $fightIDs: [Int!]) {
  reportData {
    report(code: $code) {
      fights(fightIDs: $fightIDs) {
        id
        enemyNPCs { gameID }
      }
    }
  }
}
"""


def main():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    token = get_token(cfg["client_id"], cfg["client_secret"])

    bests = PlayerBests(DATA_PATH)

    # Collect wipe records that need backfill
    # Group by report_code for batching
    by_report: dict[str, list[PlayerBest]] = defaultdict(list)
    needs_backfill = 0
    for pb in bests._data.values():
        if not pb.is_clear and pb.encounter_id in TARGETS and pb.phase_reached == 0:
            by_report[pb.report_code].append(pb)
            needs_backfill += 1

    print(f"Records needing backfill: {needs_backfill} across {len(by_report)} reports")

    updated = 0
    for i, (code, pbs) in enumerate(by_report.items()):
        fight_ids = list({pb.fight_id for pb in pbs})
        try:
            data = gql(token, ENEMY_NPCS_QUERY, {"code": code, "fightIDs": fight_ids})
            fights = data["data"]["reportData"]["report"]["fights"]
            fight_map = {f["id"]: f for f in fights}
        except Exception as e:
            print(f"  [{i+1}/{len(by_report)}] {code}: ERROR {e}")
            continue

        for pb in pbs:
            fight = fight_map.get(pb.fight_id)
            if not fight:
                continue
            phase = _wipe_phase(fight, pb.encounter_id)
            if phase > 0:
                pb.phase_reached = phase
                bests._dirty = True
                updated += 1

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(by_report)}] processed, {updated} updated so far...")
            time.sleep(1)

    bests.save()
    print(f"Done. Updated {updated} records.")


if __name__ == "__main__":
    main()
