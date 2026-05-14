"""rename_player.py — 將玩家舊 ID 的全部資料合併到新 ID

用法：直接執行，OLD_ID / NEW_ID 在下方設定。

處理範圍：
  - player_bests.json：重新命名 key 與 name 欄位；若新 ID 已有同副本同職業紀錄，取較優者
  - clears.json：更新 players 列表與 jobs 字典的 key
"""
import json
from pathlib import Path

# ── 設定 ──────────────────────────────────────────────────────────────────────
OLD_NAME = "Rlu"
OLD_SERVER = "利維坦"
NEW_NAME = "栗米"
NEW_SERVER = "利維坦"

OLD_ID = f"{OLD_NAME}@{OLD_SERVER}"   # "Rlu@利維坦"
NEW_ID = f"{NEW_NAME}@{NEW_SERVER}"   # "栗米@利維坦"

CLEARS_PATH = Path("docs/data/clears.json")
BESTS_PATH  = Path("docs/data/player_bests.json")

# ── 判斷哪筆紀錄較優（同 PlayerBest.is_better_than 邏輯）───────────────────
def is_better(a: dict, b: dict) -> bool:
    """True if a is better than b."""
    if a["is_clear"] and not b["is_clear"]:
        return True
    if not a["is_clear"] and b["is_clear"]:
        return False
    if a["is_clear"]:
        return a.get("rdps", 0) > b.get("rdps", 0)
    return a.get("boss_hp_pct", 1) < b.get("boss_hp_pct", 1)


def merge_bests(path: Path) -> int:
    data: dict = json.loads(path.read_text(encoding="utf-8"))
    old_keys = [k for k in data if k.startswith(f"{OLD_ID}:")]
    if not old_keys:
        print(f"  player_bests: 找不到 {OLD_ID} 的紀錄")
        return 0

    merged = 0
    for old_key in old_keys:
        rec = data.pop(old_key)
        # 更新紀錄內的 name 欄位
        rec["name"] = NEW_NAME
        rec["server"] = NEW_SERVER

        # 計算新 key（直接替換前綴）
        suffix = old_key[len(f"{OLD_ID}:"):]   # e.g. "1077:BlackMage" or "1077:_wipe"
        new_key = f"{NEW_ID}:{suffix}"

        existing = data.get(new_key)
        if existing is None:
            data[new_key] = rec
        elif is_better(rec, existing):
            data[new_key] = rec
        # else: existing 較優，丟棄 old rec
        merged += 1

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def merge_clears(path: Path) -> tuple[int, int]:
    clears: list = json.loads(path.read_text(encoding="utf-8"))
    players_updated = 0
    jobs_updated = 0

    for c in clears:
        # players 列表
        new_players = []
        for p in c.get("players", []):
            if p == OLD_ID:
                new_players.append(NEW_ID)
                players_updated += 1
            else:
                new_players.append(p)
        c["players"] = new_players

        # jobs 字典
        if OLD_ID in c.get("jobs", {}):
            c["jobs"][NEW_ID] = c["jobs"].pop(OLD_ID)
            jobs_updated += 1

    path.write_text(json.dumps(clears, ensure_ascii=False, indent=2), encoding="utf-8")
    return players_updated, jobs_updated


def main():
    print(f"將 {OLD_ID} 合併為 {NEW_ID}")

    n_bests = merge_bests(BESTS_PATH)
    print(f"  player_bests: {n_bests} 筆紀錄更新/合併")

    n_pl, n_jobs = merge_clears(CLEARS_PATH)
    print(f"  clears: players={n_pl} 筆，jobs={n_jobs} 筆更新")
    print("完成")


if __name__ == "__main__":
    main()
