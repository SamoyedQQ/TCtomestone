"""Headless runner for GitHub Actions — no GUI."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from scraper_core import ClearRecord, Scraper

DATA_DIR     = Path(__file__).parent / "docs" / "data"
CLEARS_PATH  = DATA_DIR / "clears.json"
BESTS_PATH   = DATA_DIR / "player_bests.json"
CODES_PATH   = DATA_DIR / "processed_codes.json"
META_PATH    = DATA_DIR / "meta.json"

DEFAULT_START = "2026-02-01 00:00"


def _parse_dt_ms(s: str):
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
    try:
        if CLEARS_PATH.exists():
            return json.loads(CLEARS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _load_processed_codes() -> set:
    try:
        if CODES_PATH.exists():
            return set(json.loads(CODES_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return set()


def main():
    client_id     = os.environ.get("FFLOGS_CLIENT_ID", "")
    client_secret = os.environ.get("FFLOGS_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("ERROR: FFLOGS_CLIENT_ID / FFLOGS_CLIENT_SECRET not set", flush=True)
        sys.exit(1)

    start_ms        = _parse_dt_ms(os.environ.get("START_DT", DEFAULT_START)) or 0
    raw_clears      = _load_clears()
    clears          = [ClearRecord.from_dict(d) for d in raw_clears]
    seen_keys       = {f"{c.code}:{c.fight_id}" for c in clears}
    processed_codes = _load_processed_codes()

    new_clears:       list = []
    processed_in_run: set  = set()

    def on_log(msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

    def on_clear(rec: ClearRecord):
        new_clears.append(rec)
        print(f"  ✓ 通關: {rec.encounter} | {', '.join(rec.players)}", flush=True)

    def on_checkpoint(_batch_start_ms: int, new_codes: set):
        processed_in_run.update(new_codes)

    scraper = Scraper(
        on_log          = on_log,
        on_clear        = on_clear,
        on_status       = lambda _: None,
        on_done         = lambda _: None,
        on_progress     = None,
        on_checkpoint   = on_checkpoint,
        bests_path      = BESTS_PATH,
        start_from_ms   = start_ms,
        end_from_ms     = None,
        seen_keys       = seen_keys,
        processed_codes = processed_codes,
        client_id       = client_id,
        client_secret   = client_secret,
    )
    scraper.run()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if new_clears:
        clears.extend(new_clears)
        CLEARS_PATH.write_text(
            json.dumps([c.to_dict() for c in clears], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"saved {len(new_clears)} new clears (total {len(clears)})", flush=True)

    processed_codes |= processed_in_run
    CODES_PATH.write_text(
        json.dumps(sorted(processed_codes), ensure_ascii=False),
        encoding="utf-8",
    )

    updated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    META_PATH.write_text(
        json.dumps({"updated_at": updated_at}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"done. updated_at={updated_at} UTC", flush=True)


if __name__ == "__main__":
    main()
