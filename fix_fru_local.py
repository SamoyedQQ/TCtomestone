"""本地修正 FRU player_bests rDPS — 不需呼叫 FFLogs API。

背景
----
FRU（1079）在 zone 65 的 rankings.duration ≈ raw_ms（未扣 phase transition
downtime），導致用 rd 當分母算出的 rDPS 偏低約 34%。
症狀：同一場通關，有 ranking 的紀錄 rDPS 約 19-22k；沒 ranking 的 fallback
紀錄則約 27-28k（正確）。

辨識方法
--------
逐 (report_code, fight_id) 群組看 max rDPS：
  - max >= 25_000 → fallback path（正確），不動
  - max <  25_000 → rankings.duration path（偏低），rdps/adps × correction
correction = duration_ms / (duration_ms - DOWNTIME_MS)

實測 FRU damageDowntime ≈ 287_500ms（佔全程 25%）。

用法
----
  python fix_fru_local.py            # dry-run，只印報告
  python fix_fru_local.py --apply    # 真的寫回 player_bests.json + 重建 leaderboard
"""
import json
import sys
from pathlib import Path
from collections import defaultdict

ROOT       = Path(__file__).parent
BESTS_PATH = ROOT / "docs" / "data" / "player_bests.json"
FRU_ENC_ID = 1079
DOWNTIME_MS = 287_500          # 實測 FRU damageDowntime
GOOD_THRESHOLD = 25_000        # group max_rdps >= 此值視為已用 fallback path

APPLY = "--apply" in sys.argv


def main() -> None:
    bests = json.loads(BESTS_PATH.read_text(encoding="utf-8"))

    # 群組化所有 FRU clear 紀錄
    groups: dict[tuple[str, int], list[tuple[str, dict]]] = defaultdict(list)
    for key, v in bests.items():
        if v.get("encounter_id") != FRU_ENC_ID or not v.get("is_clear"):
            continue
        rc, fid = v.get("report_code"), v.get("fight_id")
        if rc is None or fid is None:
            continue
        groups[(rc, fid)].append((key, v))

    bad_groups = []
    good_groups = []
    for (rc, fid), entries in groups.items():
        max_rdps = max(e["rdps"] for _, e in entries)
        if max_rdps >= GOOD_THRESHOLD:
            good_groups.append((rc, fid, len(entries), max_rdps))
        else:
            bad_groups.append((rc, fid, entries, max_rdps))

    print(f"FRU groups: {len(groups)} 個")
    print(f"  good (max>={GOOD_THRESHOLD}, 已用 fallback path): {len(good_groups)} 個")
    for rc, fid, n, m in sorted(good_groups, key=lambda x: -x[3])[:5]:
        print(f"    max={m:.0f}  n={n}  {rc}#{fid}")
    print(f"  bad  (max< {GOOD_THRESHOLD}, 需修正)               : {len(bad_groups)} 個")

    total_updated = 0
    for rc, fid, entries, max_rdps in bad_groups:
        # 取群組內任一筆的 duration_ms 作為基準（同 fight 應一致）
        durations = {e["duration_ms"] for _, e in entries}
        if len(durations) > 1:
            print(f"  [警告] {rc}#{fid} 內 duration_ms 不一致：{durations}")
        dur = next(iter(durations))
        effective_ms = dur - DOWNTIME_MS
        if effective_ms <= 0:
            print(f"  [跳過] {rc}#{fid} duration_ms={dur} < {DOWNTIME_MS}")
            continue
        correction = dur / effective_ms
        for key, v in entries:
            old_rdps = v["rdps"]
            new_rdps = old_rdps * correction
            old_adps = v.get("adps", 0.0)
            new_adps = old_adps * correction if old_adps else 0.0
            v["rdps"] = new_rdps
            if old_adps:
                v["adps"] = new_adps
            total_updated += 1

    print(f"\n[{'APPLY' if APPLY else 'DRY-RUN'}] 將更新 {total_updated} 筆 FRU best 紀錄")
    if not APPLY:
        # 印幾筆預覽
        sample = bad_groups[0][2][:3] if bad_groups else []
        for key, v in sample:
            print(f"  例：{key} → rdps={v['rdps']:.1f}  adps={v.get('adps', 0):.1f}")
        print("（dry-run，未寫入。加 --apply 才會真的存檔）")
        return

    # 寫回 player_bests.json
    BESTS_PATH.write_text(
        json.dumps(bests, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已寫回 {BESTS_PATH}")

    # 重建 leaderboard 分割檔（前端讀的快取）
    from headless_run import _write_split_data
    _write_split_data(ROOT / "docs" / "data")
    print("已重建 leaderboard_{eid}.json")


if __name__ == "__main__":
    main()
