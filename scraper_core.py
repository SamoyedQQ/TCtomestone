"""FFLogs TC Ultimate 通關抓取 + 玩家最佳紀錄

掃描策略: 依使用者指定的起始/結束時間掃描一次，無游標狀態。

玩家最佳紀錄:
  - 通關: 比較 rDPS（同通關取最高 rDPS）
  - 未通關: 比較 fightPercentage（越低 = 打得越深 = 越好）
  - 資料來源: table(DamageDone) → totalRDPS/totalADPS/rankPercent(parse%)/job/guid
"""
import json
import time
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import requests

# ── constants ─────────────────────────────────────────────────────────────────

OAUTH_URL = "https://www.fflogs.com/oauth/token"
API_URL   = "https://www.fflogs.com/api/v2/client"

TC_SERVERS   = {"奧汀", "伊弗利特", "迦樓羅", "巴哈姆特", "鳳凰", "泰坦", "利維坦"}
ULTIMATE_IDS = {1073, 1074, 1075, 1076, 1077}

POINT_LIMIT = 3400
PAGE_DELAY  = 2
FIGHT_DELAY = 1
MAX_PAGES   = 25
MAX_BATCHES = 200
WINDOW_MS   = 14 * 24 * 60 * 60 * 1000  # 14-day window per batch

# ── queries ───────────────────────────────────────────────────────────────────

SCAN_QUERY = """
query ($page: Int, $startTime: Float, $endTime: Float) {
  rateLimitData { pointsSpentThisHour }
  reportData {
    reports(zoneID: 59, page: $page, limit: 25,
            startTime: $startTime, endTime: $endTime) {
      data {
        code
        startTime
        endTime
        masterData { actors(type: "Player") { server } }
      }
      has_more_pages
    }
  }
}
"""

# fightPercentage: overall encounter HP% remaining (all phases), lower = further progress
FIGHTS_QUERY = """
query ($code: String) {
  rateLimitData { pointsSpentThisHour }
  reportData {
    report(code: $code) {
      title
      masterData { actors(type: "Player") { id name server } }
      fights {
        id encounterID name kill startTime endTime friendlyPlayers fightPercentage
      }
    }
  }
}
"""

# table entries include: totalRDPS, totalADPS, type (job), guid, rankPercent (parse%)
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

# ── data models ───────────────────────────────────────────────────────────────

@dataclass
class ClearRecord:
    code:        str
    title:       str
    encounter:   str
    players:     list
    fight_id:    int
    duration_ms: int
    clear_dt_ms: int

    @property
    def url(self) -> str:
        return f"https://www.fflogs.com/reports/{self.code}#fight={self.fight_id}"

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("code","title","encounter","players","fight_id","duration_ms","clear_dt_ms")}

    @classmethod
    def from_dict(cls, d: dict) -> "ClearRecord":
        return cls(**{k: d[k] for k in
                      ("code","title","encounter","players","fight_id","duration_ms","clear_dt_ms")})


@dataclass
class PlayerBest:
    """一個玩家在一個 Ultimate 副本中的最佳紀錄。"""
    name:         str
    server:       str
    encounter_id: int
    encounter:    str
    is_clear:     bool
    boss_hp_pct:  float   # 0.0 for clears; fightPercentage for wipes (overall %, lower = further)
    rdps:         float
    adps:         float
    parse_pct:    float   # 0–100；未公開時為 0
    job:          str
    char_id:      int
    report_code:  str
    fight_id:     int
    timestamp_ms: int
    duration_ms:  int = 0  # fight duration in ms (clears only)

    @property
    def key(self) -> str:
        # Clears are keyed per-job so multiple jobs can be tracked independently.
        # Wipes use a single slot per encounter (only best progress matters).
        if self.is_clear:
            return f"{self.name}@{self.server}:{self.encounter_id}:{self.job}"
        return f"{self.name}@{self.server}:{self.encounter_id}:_wipe"

    def is_better_than(self, other: "PlayerBest") -> bool:
        if self.is_clear and not other.is_clear:
            return True
        if not self.is_clear and other.is_clear:
            return False
        if self.is_clear:
            return self.rdps > other.rdps
        return self.boss_hp_pct < other.boss_hp_pct

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PlayerBest":
        fields = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in fields})


class PlayerBests:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, PlayerBest] = {}
        self._dirty = False
        self._load()

    def update_if_better(self, pb: PlayerBest) -> bool:
        existing = self._data.get(pb.key)
        if existing is None or pb.is_better_than(existing):
            self._data[pb.key] = pb
            self._dirty = True
            return True
        if existing.duration_ms == 0 and pb.duration_ms > 0 and existing.is_clear and pb.is_clear:
            existing.duration_ms = pb.duration_ms
            self._dirty = True
        return False

    def can_skip_wipe(self, name: str, server: str, enc_id: int, fight_pct: float) -> bool:
        prefix = f"{name}@{server}:{enc_id}:"
        for k in self._data:
            if k.startswith(prefix) and not k.endswith(":_wipe"):
                return True  # player already has a clear for some job
        existing = self._data.get(f"{name}@{server}:{enc_id}:_wipe")
        if existing is None:
            return False
        return fight_pct >= existing.boss_hp_pct

    def save(self):
        if not self._dirty:
            return
        try:
            self.path.write_text(
                json.dumps({k: v.to_dict() for k, v in self._data.items()},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._dirty = False
        except Exception:
            pass

    def _load(self):
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                for _stored_key, v in raw.items():
                    try:
                        pb = PlayerBest.from_dict(v)
                        # Re-key by computed key (handles old format migration)
                        existing = self._data.get(pb.key)
                        if existing is None or pb.is_better_than(existing):
                            self._data[pb.key] = pb
                    except Exception:
                        pass
        except Exception:
            pass


# ── scan result ───────────────────────────────────────────────────────────────

@dataclass
class _ScanResult:
    pts_used:  int  = 0
    completed: bool = False


# ── scraper ───────────────────────────────────────────────────────────────────

class Scraper:
    def __init__(
        self,
        on_log:          Callable[[str], None],
        on_clear:        Callable[[ClearRecord], None],
        on_status:       Callable[[dict], None],
        on_done:         Callable[[dict], None],
        on_progress:     Optional[Callable[[dict], None]],
        on_checkpoint:   Optional[Callable[[int, set], None]],  # (oldest_ms, new_codes)
        bests_path:      Path,
        start_from_ms:   int,
        end_from_ms:     Optional[int],   # None = 現在（無上限）
        seen_keys:       set,             # 已存在的 code:fight_id，避免重複
        processed_codes: set,             # 已呼叫過 FIGHTS_QUERY 的 report codes
        client_id:       str,
        client_secret:   str,
    ):
        self.on_log          = on_log
        self.on_clear        = on_clear
        self.on_status       = on_status
        self.on_done         = on_done
        self.on_progress     = on_progress
        self.on_checkpoint   = on_checkpoint
        self.bests_path      = bests_path
        self.start_from_ms   = start_from_ms
        self.end_from_ms     = end_from_ms
        self.seen_keys       = seen_keys
        self.processed_codes = processed_codes
        self._client_id      = client_id
        self._client_secret  = client_secret
        self._stop  = threading.Event()
        self._token: Optional[str] = None

    def stop(self):
        self._stop.set()

    def run(self):
        self._stop.clear()
        bests     = PlayerBests(self.bests_path)
        seen_keys = set(self.seen_keys)

        effective_end_ms = self.end_from_ms if self.end_from_ms else int(time.time() * 1000)

        self.on_status({"state": "執行中", "points": 0})
        self.on_log("取得 OAuth Token...")
        try:
            self._token = self._get_token()
        except Exception as e:
            self.on_log(f"Token 失敗: {e}")
            self.on_done({"reason": "error"})
            return

        start_lbl = _fmt_dt(self.start_from_ms)
        end_lbl   = _fmt_dt(self.end_from_ms) if self.end_from_ms else "現在"
        self.on_log(f"掃描範圍: {start_lbl} → {end_lbl}（API 由新到舊掃描）")

        r = self._do_scan(self.start_from_ms, self.end_from_ms, seen_keys, bests)
        bests.save()

        if self._stop.is_set():
            self.on_log(f"已停止。已使用 {r.pts_used}pt")
            self.on_status({"state": "已停止", "points": r.pts_used})
            self.on_done({"reason": "stopped", "end_ms": effective_end_ms})
        else:
            self.on_log(f"掃描完成。共使用 {r.pts_used}pt")
            self.on_status({"state": "閒置", "points": r.pts_used})
            self.on_done({"reason": "done", "completed": r.completed, "end_ms": effective_end_ms})

    # ── scan engine ───────────────────────────────────────────────────────────

    def _do_scan(
        self,
        start_ms: int,
        end_ms:   Optional[int],
        seen_keys: set,
        bests:    PlayerBests,
    ) -> _ScanResult:
        res = _ScanResult()
        # Always use a concrete end_time; compute from now if not supplied
        end_time: float = float(end_ms) if end_ms is not None else float(int(time.time() * 1000))
        pts_start: Optional[int] = None
        seen_codes = {k.split(":")[0] for k in seen_keys} | self.processed_codes

        for batch in range(1, MAX_BATCHES + 1):
            if self._stop.is_set():
                break

            # Fixed-size window: [batch_start, end_time]
            # Both bounds passed to API so outlier reports (old fight, late upload) can't
            # appear in the wrong window and drag the cursor backwards.
            batch_start = max(float(start_ms), end_time - WINDOW_MS)
            batch_done = False
            new_codes_in_batch: set = set()

            _preloaded: Optional[dict] = None

            for page in range(1, MAX_PAGES + 1):
                if self._stop.is_set():
                    break
                if _preloaded is not None:
                    data, _preloaded = _preloaded, None
                else:
                    if page > 1:
                        time.sleep(PAGE_DELAY)
                    data = self._gql(SCAN_QUERY, {"page": page, "startTime": batch_start, "endTime": end_time})
                    if data is None:
                        break

                pts_now = data["rateLimitData"]["pointsSpentThisHour"]
                if pts_start is None:
                    pts_start = pts_now
                elif pts_now < pts_start:
                    pts_start = 0
                res.pts_used = pts_now - pts_start
                self.on_status({"points": res.pts_used})
                if res.pts_used >= POINT_LIMIT:
                    self.on_log(f"積分上限 {res.pts_used}/{POINT_LIMIT}pt，停止。")
                    batch_done = True
                    break

                pg       = data["reportData"]["reports"]
                reps     = pg["data"]
                has_more = pg["has_more_pages"]

                if not reps:
                    batch_done = True
                    break

                # Early exit: check first TC before processing this page
                first_tc_rep = next((r for r in reps if _is_tc(r["masterData"]["actors"])), None)
                if not self._stop.is_set() and first_tc_rep is not None and first_tc_rep["code"] in seen_codes:
                    time.sleep(PAGE_DELAY)
                    probe = self._gql(SCAN_QUERY, {
                        "page": page + 1, "startTime": batch_start, "endTime": end_time,
                    })
                    if probe is None:
                        batch_done = True
                    else:
                        pts_now = probe["rateLimitData"]["pointsSpentThisHour"]
                        if pts_start is None:
                            pts_start = pts_now
                        elif pts_now < pts_start:
                            pts_start = 0
                        res.pts_used = pts_now - pts_start
                        self.on_status({"points": res.pts_used})

                        probe_reps = probe["reportData"]["reports"]["data"]
                        has_new_tc = any(
                            _is_tc(r["masterData"]["actors"]) and r["code"] not in seen_codes
                            for r in probe_reps
                        )
                        if has_new_tc:
                            # Next page has new TC → go back and fully process current page
                            self.on_log(f"  [批{batch} 頁{page:2d}] 首筆TC重複，下頁有新TC，補掃此頁")
                            _preloaded = probe
                        else:
                            self.on_log(f"  [批{batch}] 首筆TC重複，下頁亦無新TC，跳過後續頁面")
                            batch_done = True

                if batch_done:
                    break

                tc_count   = 0
                tc_skipped = 0
                for report in reps:
                    if self._stop.is_set():
                        break

                    st = report["startTime"]

                    if self.on_progress:
                        self.on_progress({"current_ts": report.get("endTime", st)})

                    if not _is_tc(report["masterData"]["actors"]):
                        continue

                    if report["code"] in seen_codes:
                        self.on_log(f"  [跳過] {report['code']} 已有紀錄")
                        tc_skipped += 1
                        continue

                    tc_count += 1
                    time.sleep(FIGHT_DELAY)

                    new_codes_in_batch.add(report["code"])
                    seen_codes.add(report["code"])

                    fdata = self._gql(FIGHTS_QUERY, {"code": report["code"]})
                    if fdata is None:
                        break

                    pts_now = fdata["rateLimitData"]["pointsSpentThisHour"]
                    if pts_start is None:
                        pts_start = pts_now
                    elif pts_now < pts_start:  # hour rolled over during 429 wait
                        pts_start = 0
                    res.pts_used = pts_now - pts_start
                    self.on_status({"points": res.pts_used})

                    if res.pts_used >= POINT_LIMIT:
                        self.on_log(f"積分上限 {res.pts_used}/{POINT_LIMIT}pt，停止。")
                        batch_done = True
                        break

                    rep        = fdata["reportData"]["report"]
                    by_id      = {a["id"]: a for a in rep["masterData"]["actors"]}
                    ult_fights = [f for f in rep["fights"]
                                  if f.get("encounterID") in ULTIMATE_IDS]

                    # ── Player Bests: kills (one DETAIL_QUERY per kill) ──────
                    for fight in ult_fights:
                        if self._stop.is_set():
                            break
                        if not fight.get("kill"):
                            continue
                        tc_in = _tc_actors(fight, by_id)
                        if not tc_in:
                            continue

                        pts_now, _ = self._process_kill_bests(
                            report, fight, tc_in, bests, pts_start or 0
                        )
                        if pts_now is not None:
                            if pts_start is None:
                                pts_start = pts_now
                            elif pts_now < pts_start:  # hour rolled over
                                pts_start = 0
                            res.pts_used = pts_now - pts_start
                            self.on_status({"points": res.pts_used})
                        if res.pts_used >= POINT_LIMIT:
                            batch_done = True
                            break

                    # ── Player Bests: wipes (one batched DETAIL_QUERY per report)
                    if not batch_done and not self._stop.is_set():
                        wipe_candidates = [
                            (f, _tc_actors(f, by_id))
                            for f in ult_fights if not f.get("kill")
                        ]
                        wipe_candidates = [(f, a) for f, a in wipe_candidates if a]
                        if wipe_candidates:
                            pts_now = self._process_all_wipe_bests(
                                report, wipe_candidates, bests
                            )
                            if pts_now is not None:
                                if pts_start is None:
                                    pts_start = pts_now
                                elif pts_now < pts_start:  # hour rolled over
                                    pts_start = 0
                                res.pts_used = pts_now - pts_start
                                self.on_status({"points": res.pts_used})
                            if res.pts_used >= POINT_LIMIT:
                                batch_done = True

                    if batch_done:
                        break

                    # ── Clear Records ─────────────────────────────────────────
                    kills = [f for f in ult_fights if f.get("kill")]
                    for kill in kills:
                        key = f"{report['code']}:{kill['id']}"
                        if key in seen_keys:
                            continue
                        players = _tc_players(by_id, kill.get("friendlyPlayers", []))
                        if not players:
                            continue
                        seen_keys.add(key)
                        self.on_clear(ClearRecord(
                            code        = report["code"],
                            title       = rep["title"],
                            encounter   = kill.get("name", "Unknown"),
                            players     = players,
                            fight_id    = kill["id"],
                            duration_ms = kill["endTime"] - kill["startTime"],
                            clear_dt_ms = report["startTime"] + kill["endTime"],
                        ))

                skip_lbl = f" ({tc_skipped}跳)" if tc_skipped else ""
                self.on_log(
                    f"  [批{batch} 頁{page:2d}] "
                    f"{len(reps)}筆, {tc_count}筆TC{skip_lbl} "
                    f"({'有更多' if has_more else '末頁'}) [{res.pts_used}pt]"
                )

                if not has_more:
                    batch_done = True

                if batch_done:
                    break

            # Checkpoint: cursor = start of this window (= where next scan resumes from)
            if self.on_checkpoint:
                self.on_checkpoint(int(batch_start), new_codes_in_batch)

            # Reached target date — scan complete
            if batch_start <= float(start_ms):
                res.completed = True
                break

            if self._stop.is_set():
                break

            # Fixed-step advance to the previous window
            end_time = batch_start - 1

        return res

    # ── player bests helpers ──────────────────────────────────────────────────

    def _process_kill_bests(self, report, fight, tc_actors, bests, pts_start_ref):
        ddata = self._gql(DETAIL_QUERY, {
            "code": report["code"],
            "fightIDs": [fight["id"]],
        })
        if ddata is None:
            return None, False

        pts_now_raw = ddata["rateLimitData"]["pointsSpentThisHour"]
        fight_s = (fight["endTime"] - fight["startTime"]) / 1000
        if fight_s <= 0:
            return pts_now_raw, False

        rep_detail = ddata["reportData"]["report"]
        table_by_name: dict = {}
        for entry in rep_detail["table"]["data"]["entries"]:
            table_by_name[entry.get("name", "")] = entry

        did_update = False
        for p in tc_actors:
            name = p["name"]
            tbl  = table_by_name.get(name)
            if not tbl:
                continue

            rdps      = tbl.get("totalRDPS", 0.0) / fight_s
            adps      = tbl.get("totalADPS", 0.0) / fight_s
            parse_pct = float(tbl.get("rankPercent") or 0.0)
            job       = tbl.get("type", "Unknown")
            char_id   = tbl.get("guid", 0)

            pb = PlayerBest(
                name=name, server=p.get("server", ""),
                encounter_id=fight["encounterID"],
                encounter=fight.get("name", "Unknown"),
                is_clear=True, boss_hp_pct=0.0,
                rdps=rdps, adps=adps, parse_pct=parse_pct,
                job=job, char_id=char_id,
                report_code=report["code"],
                fight_id=fight["id"],
                timestamp_ms=report["startTime"] + fight["endTime"],
                duration_ms=fight["endTime"] - fight["startTime"],
            )
            if bests.update_if_better(pb):
                did_update = True
                parse_str = f"{parse_pct:.0f}%" if parse_pct else "—%"
                self.on_log(
                    f"  ★ 最佳更新: {name}@{p.get('server','')} "
                    f"[{job}] rDPS={rdps:.0f} aDPS={adps:.0f} ({parse_str}) "
                    f"「{fight.get('name','')[:20]}」"
                )

        return pts_now_raw, did_update

    def _process_all_wipe_bests(self, report, wipe_fights_with_actors, bests) -> Optional[int]:
        """For each TC player, find their best wipe in this report and fetch job via one DETAIL_QUERY."""
        # "name@server:enc_id" → (fight, fight_pct, player_dict)
        player_best: dict = {}
        for fight, tc_actors in wipe_fights_with_actors:
            fight_pct = fight.get("fightPercentage")
            if fight_pct is None:
                continue
            enc_id = fight.get("encounterID")
            for p in tc_actors:
                name, server = p["name"], p.get("server", "")
                if bests.can_skip_wipe(name, server, enc_id, fight_pct):
                    continue
                key = f"{name}@{server}:{enc_id}"
                existing = player_best.get(key)
                if existing is None or fight_pct < existing[1]:
                    player_best[key] = (fight, fight_pct, p)

        if not player_best:
            return None

        # Unique fight IDs from each player's personal best wipe (often just one fight)
        best_fight_ids = list({f["id"] for f, _, _ in player_best.values()})
        ddata = self._gql(DETAIL_QUERY, {"code": report["code"], "fightIDs": best_fight_ids})

        table_by_name: dict = {}
        pts_now: Optional[int] = None
        if ddata is not None:
            pts_now = ddata["rateLimitData"]["pointsSpentThisHour"]
            for entry in ddata["reportData"]["report"]["table"]["data"]["entries"]:
                table_by_name[entry.get("name", "")] = entry

        for _key, (fight, fight_pct, p) in player_best.items():
            name, server = p["name"], p.get("server", "")
            tbl = table_by_name.get(name, {})
            pb = PlayerBest(
                name=name, server=server,
                encounter_id=fight["encounterID"],
                encounter=fight.get("name", "Unknown"),
                is_clear=False, boss_hp_pct=fight_pct,
                rdps=0.0, adps=0.0, parse_pct=0.0,
                job=tbl.get("type", "Unknown"),
                char_id=tbl.get("guid", 0),
                report_code=report["code"],
                fight_id=fight["id"],
                timestamp_ms=report["startTime"] + fight.get("endTime", 0),
            )
            if bests.update_if_better(pb):
                self.on_log(
                    f"  ↑ 進度更新: {name}@{server} [{tbl.get('type','?')}] "
                    f"「{fight.get('name','')[:20]}」{fight_pct:.1f}%"
                )

        return pts_now

    # ── network ───────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        r = requests.post(
            OAUTH_URL,
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["access_token"]

    def _gql(self, query: str, variables: Optional[dict] = None) -> Optional[dict]:
        for attempt in range(5):
            if self._stop.is_set():
                return None
            try:
                r = requests.post(
                    API_URL,
                    json={"query": query, "variables": variables or {}},
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=30,
                )
                if r.status_code == 429:
                    wait = int(r.headers.get("retry-after", 60))
                    self.on_log(f"[429] 速率限制，等待 {wait}s...")
                    for _ in range(wait):
                        if self._stop.is_set():
                            return None
                        time.sleep(1)
                    continue
                r.raise_for_status()
                d = r.json()
                if "errors" in d:
                    raise RuntimeError(d["errors"])
                return d["data"]
            except requests.RequestException as e:
                if attempt == 4:
                    self.on_log(f"請求失敗: {e}")
                    return None
                self.on_log(f"重試 ({attempt+1}/5)...")
                time.sleep(5 * (attempt + 1))
        return None


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_tc(actors: list) -> bool:
    return any(a.get("server") in TC_SERVERS for a in actors)


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


def _fmt_dt(epoch_ms) -> str:
    return datetime.fromtimestamp(float(epoch_ms) / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
