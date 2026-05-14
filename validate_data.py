"""驗證 docs/data/ 內的 JSON 資料完整性。

執行方式：python validate_data.py
回傳碼：0 = 全部通過；1 = 有錯誤
"""
import io
import json
import sys
from pathlib import Path

# 強制 stdout 使用 UTF-8（避免 Windows cp950 在 CI / 終端機上的編碼問題）
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DATA_DIR = Path(__file__).parent / "docs" / "data"

CLEAR_REQUIRED = {"code", "encounter", "players", "fight_id", "duration_ms", "clear_dt_ms"}
BEST_REQUIRED  = {"name", "server", "encounter_id", "encounter", "is_clear",
                  "boss_hp_pct", "rdps", "job", "report_code", "fight_id",
                  "timestamp_ms", "duration_ms"}

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)
    print(f"  ✗ {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"  ✓ {msg}", flush=True)


def check_clears():
    path = DATA_DIR / "clears.json"
    print(f"\n[clears.json]")
    if not path.exists():
        err("檔案不存在")
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        err(f"JSON 解析失敗：{e}")
        return

    if not isinstance(data, list):
        err("根層級應為陣列")
        return

    ok(f"共 {len(data)} 筆通關紀錄")

    seen_keys: set = set()
    seen_sigs: set = set()

    for i, rec in enumerate(data):
        prefix = f"[{i}]"
        if not isinstance(rec, dict):
            err(f"{prefix} 不是物件")
            continue

        missing = CLEAR_REQUIRED - rec.keys()
        if missing:
            err(f"{prefix} 缺少必要欄位：{missing}")

        players = rec.get("players", [])
        if not isinstance(players, list) or not players:
            err(f"{prefix} players 應為非空陣列")

        fight_id = rec.get("fight_id")
        code = rec.get("code", "")
        if not isinstance(fight_id, int) or fight_id <= 0:
            err(f"{prefix} fight_id 應為正整數，實際：{fight_id!r}")

        key = f"{code}:{fight_id}"
        if key in seen_keys:
            err(f"{prefix} 重複 key：{key}")
        seen_keys.add(key)

        clear_dt_ms = rec.get("clear_dt_ms")
        if isinstance(players, list) and isinstance(clear_dt_ms, (int, float)):
            sig = "|".join(sorted(str(p) for p in players)) + ":" + str(int(clear_dt_ms))
            if sig in seen_sigs:
                err(f"{prefix} 重複通關簽名（跨 report 去重失效）：{key}")
            seen_sigs.add(sig)

        duration_ms = rec.get("duration_ms", 0)
        if isinstance(duration_ms, int) and duration_ms <= 0:
            err(f"{prefix} duration_ms 應為正整數，實際：{duration_ms}")

    if not errors:
        ok("所有 clear 紀錄驗證通過")


def check_player_bests():
    path = DATA_DIR / "player_bests.json"
    print(f"\n[player_bests.json]")
    if not path.exists():
        err("檔案不存在")
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        err(f"JSON 解析失敗：{e}")
        return

    if not isinstance(data, dict):
        err("根層級應為物件（key → PlayerBest）")
        return

    ok(f"共 {len(data)} 筆玩家最佳紀錄")

    for stored_key, rec in data.items():
        if not isinstance(rec, dict):
            err(f"[{stored_key}] 值不是物件")
            continue

        missing = BEST_REQUIRED - rec.keys()
        if missing:
            err(f"[{stored_key}] 缺少必要欄位：{missing}")
            continue

        # 驗證 computed key 與 stored key 一致
        name = rec.get("name", "")
        server = rec.get("server", "")
        enc_id = rec.get("encounter_id")
        job = rec.get("job", "")
        is_clear = rec.get("is_clear", False)

        if is_clear:
            expected_key = f"{name}@{server}:{enc_id}:{job}"
        else:
            expected_key = f"{name}@{server}:{enc_id}:_wipe"

        if stored_key != expected_key:
            err(f"key 不一致：stored={stored_key!r}，computed={expected_key!r}")

        rdps = rec.get("rdps", 0)
        if is_clear and not isinstance(rdps, (int, float)):
            err(f"[{stored_key}] rdps 應為數字，實際：{rdps!r}")

    if not errors:
        ok("所有 player_best 紀錄驗證通過")


def check_processed_codes():
    path = DATA_DIR / "processed_codes.json"
    print(f"\n[processed_codes.json]")
    if not path.exists():
        err("檔案不存在")
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        err(f"JSON 解析失敗：{e}")
        return

    if not isinstance(data, list):
        err("根層級應為字串陣列")
        return

    non_str = [i for i, v in enumerate(data) if not isinstance(v, str)]
    if non_str:
        err(f"索引 {non_str[:5]} 的值不是字串")
    else:
        ok(f"共 {len(data)} 個已處理 report code")


def check_meta():
    path = DATA_DIR / "meta.json"
    print(f"\n[meta.json]")
    if not path.exists():
        err("檔案不存在")
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        err(f"JSON 解析失敗：{e}")
        return

    if "updated_at" not in data:
        err("缺少 updated_at 欄位")
    else:
        ok(f"updated_at = {data['updated_at']}")


def main():
    print("=== TC Tomestone 資料驗證 ===")

    check_clears()
    check_player_bests()
    check_processed_codes()
    check_meta()

    print()
    if errors:
        print(f"驗證失敗：共 {len(errors)} 個錯誤")
        sys.exit(1)
    else:
        print("所有驗證通過")
        sys.exit(0)


if __name__ == "__main__":
    main()
