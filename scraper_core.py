"""FFLogs 繁中服絕境戰資料抓取核心

職責：
  1. 透過 FFLogs GraphQL API 掃描繁中服的絕境戰通關報告
  2. 為每位玩家維護「最佳紀錄」（通關取最高 rDPS；團滅取最遠進度）
  3. 輸出通關清單（ClearRecord）與玩家最佳紀錄（PlayerBest）

掃描策略（由新到舊）：
  - 從「現在」往回掃，每次以固定時間視窗（scan_window_days）為一批
  - 每批最多掃 max_pages_per_batch 頁，達到 point_limit 後停止本次執行
  - 所有已處理的 report code 跨次執行快取於 processed_codes，避免重複掃

rDPS 計算：
  - 部分副本（TOP）有 damageDowntime（玩家無法輸出的時段）
  - 正確分母 = totalTime - damageDowntime，而非 combatTime（兩者數值相同，均未扣）
"""
import json
import time
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import requests

# ── API 端點 ──────────────────────────────────────────────────────────────────

OAUTH_URL = "https://www.fflogs.com/oauth/token"   # OAuth2 client_credentials 流程
API_URL   = "https://www.fflogs.com/api/v2/client"  # FFLogs GraphQL 入口

# ── 模組預設常數（fallback；可透過 Scraper(cfg=...) 全部覆蓋）────────────────

# 繁中服七個伺服器（與日/歐同名伺服器的辨識靠 region.id==4 + 伺服器名稱）
TC_SERVERS = {"奧汀", "伊弗利特", "迦樓羅", "巴哈姆特", "鳳凰", "泰坦", "利維坦"}

# 絕境戰 encounterID（zoneID 統一為 59）
ULTIMATE_IDS = {1073, 1074, 1075, 1076, 1077, 1079}

_ENCOUNTER_NAMES: dict[int, str] = {
    1073: "絕巴哈姆特",
    1074: "絕究極神兵",
    1075: "絕亞歷山大",
    1076: "絕龍詩戰爭",
    1077: "絕歐米茄",
    1079: "絕伊甸",
}

# 各絕境戰的已知 damageDowntime 估算值（ms）
# 用於下列兩種情境（一般情況優先使用 DETAIL_QUERY 真實 damageDowntime，此表只是 fallback）：
#   (1) zone 62（Savage）報告中嵌入的絕境戰場次：DETAIL_QUERY 在非主 zone context
#       下可能不回傳 damageDowntime，導致 fallback 使用全程時長為分母，rDPS 嚴重偏低。
#   (2) FRU 在 zone 65 的 rankings.duration 也未扣 downtime（≈ raw），此時 DETAIL_QUERY
#       會回傳真實 damageDowntime，本表只在 DETAIL 也缺值時補位。
_ENCOUNTER_DOWNTIME_ESTIMATE: dict[int, int] = {
    # TOP：zone 62 嵌入的絕境戰 rankings.duration 回傳 raw fight time（無扣 downtime）。
    # 使用 raw_ms - 275_000 作為分母（反推自 FFLogs 網頁顯示 6557.1 rDPS / fight#8 1133s）。
    # zone 59 正常報告 rankings.duration 已扣 downtime（rd 比 raw 少 ~275s），不受此值影響。
    1077: 275_000,
    # FRU：zone 65 的 rankings.duration 與 raw 僅差約 1 秒（FFLogs 沒在裡面扣 phase
    # transition downtime）。實測 damageDowntime ≈ 287.5s（佔全程 25%）；
    # DETAIL_QUERY 回傳值穩定可用，此估算僅作為 DETAIL 缺值時的 fallback。
    1079: 287_500,
}

POINT_LIMIT = 3400   # 每次執行最多消耗點數（FFLogs 上限 3600/hr，預留緩衝）
PAGE_DELAY  = 2      # 每頁 SCAN_QUERY 之間等待秒數（避免頻率過高）
FIGHT_DELAY = 1      # 每份 report 的 FIGHTS_QUERY 之間等待秒數
MAX_PAGES   = 25     # 每個時間批次最多掃描頁數
MAX_BATCHES = 200    # 最多批次數（防無限迴圈）
WINDOW_MS   = 14 * 24 * 60 * 60 * 1000  # 每批時間視窗寬度（14 天，毫秒）

# ── GraphQL 查詢定義 ──────────────────────────────────────────────────────────

# 淺層掃描：只抓 report code、時間戳、玩家伺服器列表
# zoneID: 59 = Ultimate/Unreal 副本區段（包含 UCoB/UWU/TEA/DSR/TOP）
# limit: 25 = API 單頁上限
SCAN_QUERY = """
query ($page: Int, $startTime: Float, $endTime: Float, $zoneID: Int!) {
  rateLimitData { pointsSpentThisHour }
  reportData {
    reports(zoneID: $zoneID, page: $page, limit: 25,
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

# 深層查詢：取得單份 report 的完整戰鬥列表
# fightPercentage: 全流程 HP% 剩餘（越低 = 打得越深 = 越好的進度指標）
# enemyNPCs.gameID: 用來辨識當前 phase 的 NPC ID（見 _WIPE_PHASE_NPCS）
# startTime（report 層級）：手動補抓模式（run_manual）需要 report 的絕對時間戳
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
        enemyNPCs { gameID }
      }
    }
  }
}
"""

# 傷害詳情查詢：取得單場（或多場）戰鬥的玩家傷害統計
# totalRDPS/totalADPS: 該場的總傷害量（需自行除以有效時間轉為 per-second）
# rankPercent: FFLogs 的解析百分位（0–100），私密報告時為 null
# type: 職業名稱（英文，如 BlackMage）
# guid: 角色 ID（用於跨報告識別同一角色，比名稱更穩定）
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

# 針對特定 fightID 補查 rankings.duration（用於 zone 62 嵌入的絕境戰缺少此欄位時）
RANKINGS_QUERY = """
query ($code: String, $fightIDs: [Int!]) {
  rateLimitData { pointsSpentThisHour }
  reportData {
    report(code: $code) {
      rankings(fightIDs: $fightIDs)
    }
  }
}
"""

# ── Phase 偵測：透過 enemyNPCs gameID 辨識團滅時到達的 Phase ─────────────────
#
# 結構：{ encounterID: [(phase編號, {marker_gameID集合}), ...] }，由高到低排列
# 比對時取第一個「有交集」的條目，即為當前 phase
#
# 特殊情況：
#   UCoB P5（Golden Bahamut）= 已通關，以 fightPercentage==80 判斷，不在此表
#   UCoB P3/P4 共用相同 NPC（Bahamut Prime），統一對應 P3
#   TOP P3/P4 共用相同 NPC（Omega Reconfigured），統一對應 P3
_WIPE_PHASE_NPCS: dict[int, list[tuple[int, set[int]]]] = {
    1073: [  # UCoB — 5 phases（P5 = 通關，另以 fightPercentage 判斷）
        # 8167 (Golden Bahamut) 亦在 P3 Morn Afah 動畫出現，不能作為 P5 標記
        (3, {8163, 8164, 8165, 8168}),  # Bahamut Prime（P3 本體或 P4 adds）
        (2, {8161, 8162}),              # Nael Deus Darnus
    ],
    1074: [  # UWU — 4 phases
        (4, {8734}),   # The Ultima Weapon
        (3, {8727}),   # Titan
        (2, {8730}),   # Ifrit
    ],
    1075: [  # TEA — 4 phases
        (4, {11349}),           # Perfect Alexander
        (3, {11347}),           # Alexander Prime
        (2, {11340, 11342}),    # Brute Justice / Cruise Chaser
    ],
    1076: [  # DSR — 7 phases
        (7, {12616}),           # Dragon-king Thordan（P7，最終型態）
        (6, {12613, 13119}),    # Hraesvelgr / Estinien（Nidstinien）
        (5, {12611}),           # King Thordan（第二次）
        (4, {12609, 12610}),    # The Eyes
        (3, {12605, 12606}),    # Nidhogg（P3）
        (2, {12604}),           # King Thordan（第一次）
    ],
    1077: [  # TOP — 6 phases（P3/P4 共用 NPC，統一對應 P3）
        (6, {15725}),   # Alpha Omega（最終 phase）
        (5, {15720}),   # Omega-M（Run: Dynamis，P5）
        (3, {15717}),   # Omega Reconfigured（P3 或 P4）
        (2, {15714}),   # Omega-M（P2 雙人 Duo）
    ],
    1079: [  # FRU — 5 phases；P4/P5 共用 Pandora 系列 NPC，靠 fightPercentage 細分
        (4, {17833}),   # Pandora（P4 Akh Rhai 起）；HP<10 視為 P5 Crystallize Time，
                        # 由 _wipe_phase() 特殊處理
        (3, {17831}),   # Oracle of Darkness（P3）
        (2, {17823}),   # Usurper of Frost（P2，含 Light Rampant intermission 17827–17829）
    ],
}


def _wipe_phase(fight: dict, enc_id: int) -> int:
    """根據 enemyNPCs gameID 回傳團滅時達到的 phase（1–N）；0 表示無法判斷。"""
    table = _WIPE_PHASE_NPCS.get(enc_id)
    if not table:
        return 0
    # 收集本場出現過的所有 NPC gameID
    game_ids = {npc["gameID"] for npc in fight.get("enemyNPCs") or []}
    # 從最高 phase 往下找，第一個有交集的就是當前 phase
    phase = 1
    for ph, markers in table:
        if game_ids & markers:
            phase = ph
            break
    # FRU 特殊：P4/P5 共用 Pandora NPC，用 fightPercentage 細分
    #   HP < 10% 即進入 P5 Crystallize Time
    #   kill 場 fightPercentage = 0 也視為 P5（已通關 = 最終相位）
    if enc_id == 1079 and phase == 4:
        pct = fight.get("fightPercentage")
        if pct is not None and pct < 10:
            return 5
    return phase


# ── 資料模型 ──────────────────────────────────────────────────────────────────

@dataclass
class ClearRecord:
    """單次絕境戰通關紀錄（對應 docs/data/clears.json 的一個條目）。"""
    code:        str    # FFLogs report code（如 "aBcDeFgH"）
    title:       str    # 報告標題（uploader 自訂）
    encounter:   str    # fight.name（如 "The Omega Protocol"）
    players:     list   # ["玩家名@伺服器", ...] 只含繁中服玩家
    fight_id:    int    # 在該 report 內的 fight 編號（1-based）
    duration_ms: int    # 通關時長（毫秒）= fight.endTime - fight.startTime
    clear_dt_ms: int    # 通關絕對時間戳（毫秒）= report.startTime + fight.endTime
    jobs:        dict = None  # {"玩家名@伺服器": "職業英文名", ...}；可能為空

    def __post_init__(self):
        if self.jobs is None:
            self.jobs = {}

    @property
    def url(self) -> str:
        """回傳 FFLogs 直連網址，可在瀏覽器直接開啟查看。"""
        return f"https://www.fflogs.com/reports/{self.code}#fight={self.fight_id}"

    def to_dict(self) -> dict:
        """序列化為 JSON 可存格式（省略空的 jobs 欄位）。"""
        d = {k: getattr(self, k) for k in
             ("code", "title", "encounter", "players", "fight_id", "duration_ms", "clear_dt_ms")}
        if self.jobs:
            d["jobs"] = self.jobs
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ClearRecord":
        """從 JSON dict 還原（忽略不認識的欄位以支援舊格式）。"""
        return cls(
            **{k: d[k] for k in
               ("code", "title", "encounter", "players", "fight_id", "duration_ms", "clear_dt_ms")},
            jobs=d.get("jobs", {}),
        )


@dataclass
class PlayerBest:
    """一位玩家在一個絕境戰副本中的最佳紀錄（對應 player_bests.json 的一個值）。

    key 格式：
      - 通關："{name}@{server}:{encounter_id}:{job}"（同職業只保留最高 rDPS）
      - 團滅："{name}@{server}:{encounter_id}:_wipe"（只保留最遠進度）
    """
    name:          str    # 角色名稱
    server:        str    # 伺服器（繁中）
    encounter_id:  int    # FFLogs encounterID（1073–1079）
    encounter:     str    # fight.name
    is_clear:      bool   # True = 通關；False = 未通關（團滅）
    boss_hp_pct:   float  # 通關時為 0.0；團滅時為 fightPercentage（越低越好）
    rdps:          float  # 通關時的 rDPS（per-second）；團滅時為 0.0
    adps:          float  # 通關時的 aDPS（per-second）；團滅時為 0.0
    parse_pct:     float  # FFLogs 解析百分位（0–100）；私密報告或未取得時為 0
    job:           str    # 職業英文名（如 "BlackMage"）；未知時為 "Unknown"
    char_id:       int    # FFLogs 角色 guid（用於跨報告識別同一角色）
    report_code:   str    # 來源 report code
    fight_id:      int    # 來源 fight 編號
    timestamp_ms:  int    # 通關或團滅的絕對時間戳（毫秒）
    duration_ms:   int = 0   # 戰鬥時長（毫秒）；僅通關有效
    phase_reached: int = 0   # 團滅時到達的 phase（1–N）；0 = 無法判斷

    @property
    def key(self) -> str:
        """計算此紀錄的 player_bests.json 儲存鍵值。"""
        if self.is_clear:
            # 通關以職業區分，同玩家可有多個職業最佳
            return f"{self.name}@{self.server}:{self.encounter_id}:{self.job}"
        # 未通關只保留一個 slot（最遠進度），不分職業
        return f"{self.name}@{self.server}:{self.encounter_id}:_wipe"

    def is_better_than(self, other: "PlayerBest") -> bool:
        """回傳 self 是否比 other 更好（通關 > 未通關；通關比 rDPS；未通關比 boss_hp_pct）。"""
        if self.is_clear and not other.is_clear:
            return True   # 通關永遠優先於未通關
        if not self.is_clear and other.is_clear:
            return False
        if self.is_clear:
            return self.rdps > other.rdps   # 同為通關：取更高 rDPS
        return self.boss_hp_pct < other.boss_hp_pct  # 同為未通關：取更低 HP%（打得更深）

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PlayerBest":
        """從 JSON dict 還原，自動忽略未知欄位（向後相容舊格式）。"""
        fields = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in fields})


class PlayerBests:
    """player_bests.json 的讀寫管理器。

    在記憶體中以 dict 維護，避免每次更新都重寫整個檔案。
    只有在 _dirty=True 時（有新紀錄寫入）才執行磁碟寫入。
    """

    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, PlayerBest] = {}
        self._dirty = False
        self._load()

    def update_if_better(self, pb: PlayerBest) -> bool:
        """若 pb 比現有紀錄更好，則更新並回傳 True；否則回傳 False。

        特例：若現有紀錄 duration_ms==0（舊格式缺欄位），補值後不算「更新」。
        """
        existing = self._data.get(pb.key)
        if existing is None or pb.is_better_than(existing):
            self._data[pb.key] = pb
            self._dirty = True
            return True
        # 補值：若舊紀錄缺 duration_ms（早期格式），直接填入新值（不改排名）
        if existing.duration_ms == 0 and pb.duration_ms > 0 and existing.is_clear and pb.is_clear:
            existing.duration_ms = pb.duration_ms
            self._dirty = True
        return False

    def can_skip_wipe(self, name: str, server: str, enc_id: int, fight_pct: float) -> bool:
        """判斷是否可以跳過此次團滅紀錄的處理（節省 DETAIL_QUERY 點數）。

        可跳過的情況：
          1. 該玩家在此副本已有通關（任意職業）— 通關永遠優先
          2. 該玩家已有更好的團滅進度（更低 boss_hp_pct）
        """
        prefix = f"{name}@{server}:{enc_id}:"
        for k in self._data:
            if k.startswith(prefix) and not k.endswith(":_wipe"):
                return True  # 存在通關紀錄 → 可跳過
        existing = self._data.get(f"{name}@{server}:{enc_id}:_wipe")
        if existing is None:
            return False  # 沒有任何紀錄 → 不可跳過
        # 若現有進度已更好（HP% 更低），此次可跳過
        return fight_pct >= existing.boss_hp_pct

    def save(self):
        """將記憶體中的資料寫入磁碟（僅在有異動時執行）。"""
        if not self._dirty:
            return
        try:
            self.path.write_text(
                json.dumps(
                    {k: v.to_dict() for k, v in self._data.items()},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            self._dirty = False
        except Exception:
            pass  # 寫入失敗時靜默忽略（下次執行會重試）

    def _load(self):
        """從磁碟載入現有資料，遇到損壞條目自動跳過（避免整批失敗）。"""
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                for _stored_key, v in raw.items():
                    try:
                        pb = PlayerBest.from_dict(v)
                        # 以計算出的 key 重新索引（處理舊格式 key 不一致的情況）
                        existing = self._data.get(pb.key)
                        if existing is None or pb.is_better_than(existing):
                            self._data[pb.key] = pb
                    except Exception:
                        pass
        except Exception:
            pass


# ── 掃描結果 ──────────────────────────────────────────────────────────────────

@dataclass
class _ScanResult:
    """_do_scan 的回傳值，記錄本次執行的統計資訊。"""
    pts_used:  int  = 0      # 本次消耗的 API 點數
    completed: bool = False  # True = 掃描完整到達 start_from_ms（沒被中斷）


# ── 主要爬蟲類別 ──────────────────────────────────────────────────────────────

class Scraper:
    """FFLogs 資料抓取器。

    設計為可同時被 GUI（app.py）與 Headless CI（headless_run.py）使用：
      - GUI：透過 callback（on_log/on_clear/on_status）即時更新介面
      - CI：callback 全部接到 stdout 印出，on_done 通知寫檔

    掃描演算法（_do_scan）：
      - 從 end_from_ms（或現在）往回掃，每批 scan_window_days 天
      - 每批最多 max_pages_per_batch 頁；達 point_limit 點數立即停止
      - Early-exit：若當頁首筆 TC report 已在 seen_codes 中，probe 下一頁：
          - 下一頁有新 TC → 補掃本頁再繼續
          - 下一頁亦無新 TC → 跳過後續所有頁面

    run_manual：
      - 跳過一般掃描，直接抓取 config/fflogs.json 指定的 report code
      - 不更新 processed_codes（不推進掃描進度）
    """

    def __init__(
        self,
        on_log:          Callable[[str], None],
        on_clear:        Callable[["ClearRecord"], None],
        on_status:       Callable[[dict], None],
        on_done:         Callable[[dict], None],
        on_progress:     Optional[Callable[[dict], None]],
        on_checkpoint:   Optional[Callable[[int, set], None]],
        bests_path:      Path,
        start_from_ms:   int,
        end_from_ms:     Optional[int],
        seen_keys:        set,
        processed_codes:  set,
        seen_clear_sigs:  set,
        client_id:        str,
        client_secret:   str,
        cfg:             Optional[dict] = None,
    ):
        """
        參數說明：
          on_log          — 接收 log 字串（GUI 印到文字框；CI 印到 stdout）
          on_clear        — 接收新通關紀錄（GUI 顯示；CI 存到 new_clears list）
          on_status       — 接收狀態 dict（{"state": ..., "points": ...}）
          on_done         — 掃描結束時呼叫（{"reason": "done"/"stopped"/"error"}）
          on_progress     — 可選，每處理一份 report 時回報當前時間戳（GUI 進度條）
          on_checkpoint   — 可選，每批結束時回報（batch_start_ms, 新掃到的 codes）
          bests_path      — player_bests.json 路徑
          start_from_ms   — 掃描終點（比此更舊的 report 不處理），毫秒時間戳
          end_from_ms     — 掃描起點（None = 現在）
          seen_keys       — 已存在的 "code:fight_id" 集合（防止重複寫入 clears）
          processed_codes — 已呼叫過 FIGHTS_QUERY 的 report codes（跨次執行快取）
          seen_clear_sigs — 跨 report 去重簽名集合（防止同一場被兩份 report 重複計入）
          client_id/secret— FFLogs OAuth 憑證
          cfg             — 來自 config/fflogs.json 的設定 dict（可覆蓋所有常數預設值）
        """
        self.on_log         = on_log
        self.on_clear       = on_clear
        self.on_status      = on_status
        self.on_done        = on_done
        self.on_progress    = on_progress
        self.on_checkpoint  = on_checkpoint
        self.bests_path     = bests_path
        self.start_from_ms  = start_from_ms
        self.end_from_ms    = end_from_ms
        self.seen_keys       = seen_keys
        self.processed_codes = processed_codes
        self.seen_clear_sigs = seen_clear_sigs
        self._client_id     = client_id
        self._client_secret = client_secret
        self._stop  = threading.Event()
        self._token: Optional[str] = None

        # 調校參數：從 cfg 讀取，未設定的項目退回模組預設值
        _cfg = cfg or {}
        self._point_limit   = int(_cfg.get("point_limit",          POINT_LIMIT))
        self._page_delay    = float(_cfg.get("page_delay_s",        PAGE_DELAY))
        self._fight_delay   = float(_cfg.get("fight_delay_s",       FIGHT_DELAY))
        self._max_pages     = int(_cfg.get("max_pages_per_batch",   MAX_PAGES))
        self._max_batches   = int(_cfg.get("max_batches",           MAX_BATCHES))
        self._window_ms     = int(_cfg.get("scan_window_days", 14) * 24 * 60 * 60 * 1000)
        self._tc_servers    = set(_cfg.get("tc_servers",            list(TC_SERVERS)))
        self._encounter_ids = set(_cfg.get("encounter_ids",         list(ULTIMATE_IDS)))
        # extra_scan_zones 支援兩種格式：
        #   新格式 [{"id": 62, "name": "AAC Light-Heavyweight"}]
        #   舊格式 [62]（backward compat，自動補名稱）
        raw_extra = _cfg.get("extra_scan_zones") or [
            {"id": z} for z in _cfg.get("extra_scan_zone_ids", [])
        ]
        self._extra_zones: list[tuple[int, str]] = [
            (z["id"], z.get("name", f"zone{z['id']}")) for z in raw_extra
        ]

        # scan_zones：完整 zone 列表（由 headless_run.py 從 encounters.json + extra_scan_zones 推導）
        # 若 cfg 有提供，run() / run_two_phase() 直接使用；否則 fallback 至
        # 「硬編碼 zone 59 + extra_scan_zones」的舊行為（GUI / 沒升級 caller 用）。
        raw_scan_zones = _cfg.get("scan_zones")
        if raw_scan_zones:
            seen: set[int] = set()
            self._scan_zones: list[tuple[int, str]] = []
            for z in raw_scan_zones:
                zid = int(z["id"])
                if zid in seen:
                    continue
                seen.add(zid)
                self._scan_zones.append((zid, z.get("name", f"zone{zid}")))
        else:
            self._scan_zones = [(59, "絕境戰")] + list(self._extra_zones)

    def stop(self):
        """通知掃描執行緒在下一個安全點停止（GUI 停止按鈕使用）。"""
        self._stop.set()

    def run(self):
        """執行一般掃描（從 end_from_ms 往回掃到 start_from_ms）。

        依序掃描 zone 59（絕境戰主區）以及 extra_scan_zone_ids 中的額外 zone（如 Savage zone），
        共享同一個 point 預算與 seen_keys / seen_clear_sigs，避免重複處理。
        """
        self._stop.clear()
        bests           = PlayerBests(self.bests_path)
        seen_keys       = set(self.seen_keys)
        seen_clear_sigs = set(self.seen_clear_sigs)

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

        zone_configs = [{"id": zid, "name": zname} for zid, zname in self._scan_zones]
        total_pts_used = 0
        last_r = None

        for zc in zone_configs:
            if self._stop.is_set():
                break
            if len(zone_configs) > 1:
                self.on_log(f"── 掃描 {zc['name']} (zone{zc['id']}) ──")
            r = self._do_scan(
                self.start_from_ms, self.end_from_ms,
                seen_keys, seen_clear_sigs, bests,
                zone_id=zc["id"], zone_name=zc["name"], pts_budget_used=total_pts_used,
            )
            total_pts_used += r.pts_used
            last_r = r

        bests.save()

        completed = (last_r.completed if last_r else True) and not self._stop.is_set()
        if self._stop.is_set():
            self.on_log(f"已停止。已使用 {total_pts_used}pt")
            self.on_status({"state": "已停止", "points": total_pts_used})
            self.on_done({"reason": "stopped", "end_ms": effective_end_ms})
        else:
            self.on_log(f"掃描完成。共使用 {total_pts_used}pt")
            self.on_status({"state": "閒置", "points": total_pts_used})
            self.on_done({"reason": "done", "completed": completed, "end_ms": effective_end_ms})

    def run_two_phase(
        self,
        history_state: dict,
        incremental_hours: int = 24,
        history_window_hours: int = 24,
        history_recent_gap_hours: int = 6,
        history_scan_enabled: bool = True,
    ) -> dict:
        """兩階段掃描（CI 排程用，取代 run()）。

        Phase 1：必跑。掃描 ``now - incremental_hours → now``，覆蓋全部 zone，
                 確保每天新增的資料一定被收進來。
        Phase 2：用剩餘 point 預算做歷史補查，每 zone 各自獨立游標，
                 以 round-robin 推進，避免高流量 zone（62）吃光低流量 zone（59）的預算。
                 游標到達範圍尾端時 wrap 回 start_from_ms，並累加 wraps 計數。

        history_state 格式（caller 持久化於 docs/data/state.json）::

            {"<zone_id>": {"cursor_at_ms": int, "cursor_at_iso": str, "wraps": int}, ...}

        回傳更新後的 history_state（caller 寫回檔案）。

        備註：
          - ``self.start_from_ms`` 同時作為歷史補查範圍的最舊邊界。
          - ``_do_scan`` 內部已會在處理完一份 report 後即時把 code 寫入
            ``self.processed_codes``，因此 Phase 2 不會重做 Phase 1 剛抓過的 report。
        """
        self._stop.clear()
        bests           = PlayerBests(self.bests_path)
        seen_keys       = set(self.seen_keys)
        seen_clear_sigs = set(self.seen_clear_sigs)

        self.on_status({"state": "執行中", "points": 0})
        self.on_log("取得 OAuth Token...")
        try:
            self._token = self._get_token()
        except Exception as e:
            self.on_log(f"Token 失敗: {e}")
            self.on_done({"reason": "error"})
            return history_state

        zone_configs = [{"id": zid, "name": zname} for zid, zname in self._scan_zones]
        now_ms = int(time.time() * 1000)
        total_pts_used = 0

        # ── Phase 1：近期掃描 ────────────────────────────────────────────
        phase1_start = max(self.start_from_ms, now_ms - incremental_hours * 60 * 60 * 1000)
        self.on_log(
            f"━━ Phase 1：近期掃描 {_fmt_dt(phase1_start)} → 現在"
            f"（{incremental_hours}h）━━"
        )
        for zc in zone_configs:
            if self._stop.is_set():
                break
            if total_pts_used >= self._point_limit:
                self.on_log(f"[Phase 1] points 已耗盡 ({total_pts_used}/{self._point_limit})")
                break
            if len(zone_configs) > 1:
                self.on_log(f"── [Phase 1] {zc['name']} (zone{zc['id']}) ──")
            r = self._do_scan(
                phase1_start, now_ms,
                seen_keys, seen_clear_sigs, bests,
                zone_id=zc["id"], zone_name=zc["name"], pts_budget_used=total_pts_used,
            )
            total_pts_used += r.pts_used
        self.on_log(f"━━ Phase 1 完成。累計 {total_pts_used}pt ━━")

        # ── Phase 2：歷史補查（round-robin 逐 zone 推進游標）────────────
        # 即使 Phase 1 已耗盡 budget，也要把 history_state 內現有 zone 的條目
        # 帶回去（避免下次跑時 history_state 殘缺）。
        updated_history: dict = {}
        for zc in zone_configs:
            zk = str(zc["id"])
            updated_history[zk] = dict(history_state.get(zk, {}))

        if not history_scan_enabled:
            self.on_log("[Phase 2] history_scan_enabled=false，跳過歷史補查")
        elif self._stop.is_set():
            self.on_log("[Phase 2] 已停止，跳過歷史補查")
        elif total_pts_used >= self._point_limit:
            self.on_log(f"[Phase 2] Phase 1 已耗盡 points，跳過歷史補查")
        else:
            history_start_ms = self.start_from_ms
            history_end_ms = now_ms - history_recent_gap_hours * 60 * 60 * 1000
            window_ms = history_window_hours * 60 * 60 * 1000

            if history_end_ms <= history_start_ms:
                self.on_log(
                    f"[Phase 2] 歷史範圍為空（start={_fmt_dt(history_start_ms)} "
                    f">= end={_fmt_dt(history_end_ms)}），跳過"
                )
            else:
                self.on_log(
                    f"━━ Phase 2：歷史補查 "
                    f"範圍 {_fmt_dt(history_start_ms)} → {_fmt_dt(history_end_ms)}"
                    f"｜視窗 {history_window_hours}h"
                    f"｜剩餘預算 {self._point_limit - total_pts_used}pt ━━"
                )

                cursors: dict[str, int] = {}
                for zc in zone_configs:
                    zk = str(zc["id"])
                    raw = updated_history[zk].get("cursor_at_ms")
                    try:
                        c = int(raw) if raw is not None else history_start_ms
                    except (TypeError, ValueError):
                        c = history_start_ms
                    # 範圍外（設定變更等）→ 回到起點重新跑
                    if c < history_start_ms or c >= history_end_ms:
                        c = history_start_ms
                    cursors[zk] = c

                round_idx = 0
                while True:
                    if self._stop.is_set():
                        self.on_log("[Phase 2] 已停止")
                        break
                    if total_pts_used >= self._point_limit:
                        self.on_log(
                            f"[Phase 2] points 耗盡 "
                            f"({total_pts_used}/{self._point_limit})"
                        )
                        break

                    round_idx += 1
                    progressed_this_round = False

                    for zc in zone_configs:
                        if self._stop.is_set():
                            break
                        if total_pts_used >= self._point_limit:
                            break

                        zk = str(zc["id"])
                        cursor = cursors[zk]

                        if cursor >= history_end_ms:
                            # 游標到尾 → wrap 回起點
                            wraps_prev = int(updated_history[zk].get("wraps") or 0)
                            updated_history[zk]["wraps"] = wraps_prev + 1
                            cursors[zk] = history_start_ms
                            cursor = history_start_ms
                            self.on_log(
                                f"[Phase 2] {zc['name']} 游標 wrap "
                                f"→ {_fmt_dt(cursor)}（第 {wraps_prev + 1} 圈）"
                            )

                        window_end = min(cursor + window_ms - 1, history_end_ms)
                        self.on_log(
                            f"── [Phase 2 R{round_idx}] {zc['name']} "
                            f"{_fmt_dt(cursor)} → {_fmt_dt(window_end)} ──"
                        )
                        r = self._do_scan(
                            cursor, window_end,
                            seen_keys, seen_clear_sigs, bests,
                            zone_id=zc["id"], zone_name=zc["name"],
                            pts_budget_used=total_pts_used,
                        )
                        total_pts_used += r.pts_used

                        if r.completed:
                            cursors[zk] = window_end + 1
                            updated_history[zk]["cursor_at_ms"] = cursors[zk]
                            updated_history[zk]["cursor_at_iso"] = _fmt_dt(cursors[zk])
                            progressed_this_round = True
                        else:
                            # 中斷（budget 用盡或 stop）→ 游標不前進，下次重來
                            self.on_log(
                                f"[Phase 2] {zc['name']} 視窗中斷於 "
                                f"{_fmt_dt(cursor)}，下次接續同視窗"
                            )
                            # 不更新 cursor_at_ms，但仍寫 iso 讓 state.json 反映目前位置
                            updated_history[zk].setdefault("cursor_at_ms", cursor)
                            updated_history[zk].setdefault("cursor_at_iso", _fmt_dt(cursor))

                    if not progressed_this_round:
                        # 沒有任何 zone 推進 → 不可能再進展，跳出
                        break

                self.on_log(f"━━ Phase 2 完成。累計 {total_pts_used}pt ━━")

        bests.save()

        if self._stop.is_set():
            self.on_log(f"已停止。共使用 {total_pts_used}pt")
            self.on_status({"state": "已停止", "points": total_pts_used})
            self.on_done({"reason": "stopped"})
        else:
            self.on_log(f"掃描完成。共使用 {total_pts_used}pt")
            self.on_status({"state": "閒置", "points": total_pts_used})
            self.on_done({"reason": "done", "completed": True})

        return updated_history

    def run_manual(self, codes: list) -> None:
        """直接補抓指定 report code，跳過一般掃描。

        對應 config/fflogs.json 的 only_report_codes 設定。
        執行完畢後不更新 processed_codes（不推進掃描進度）。
        """
        self._stop.clear()
        bests           = PlayerBests(self.bests_path)
        seen_keys       = set(self.seen_keys)
        seen_clear_sigs = set(self.seen_clear_sigs)

        self.on_status({"state": "手動補抓", "points": 0})
        self.on_log("取得 OAuth Token...")
        try:
            self._token = self._get_token()
        except Exception as e:
            self.on_log(f"Token 失敗: {e}")
            self.on_done({"reason": "error"})
            return

        pts_start: Optional[int] = None
        res = _ScanResult()

        for code in codes:
            if self._stop.is_set():
                break
            self.on_log(f"[手動] 補抓 {code}...")

            fdata = self._gql(FIGHTS_QUERY, {"code": code})
            if fdata is None:
                continue

            pts_now = fdata["rateLimitData"]["pointsSpentThisHour"]
            if pts_start is None:
                pts_start = pts_now
            elif pts_now < pts_start:   # 整點 rollover（點數歸零重算）
                pts_start = 0
            res.pts_used = pts_now - pts_start
            self.on_status({"points": res.pts_used})

            rep = fdata["reportData"]["report"]
            if rep is None:
                self.on_log(f"  [跳過] {code}: report 不存在或為私密")
                continue

            # 組成模擬的 report dict，供現有 helper 方法（_process_kill_bests 等）使用
            report_obj = {"code": code, "startTime": rep.get("startTime", 0)}
            by_id      = {a["id"]: a for a in rep["masterData"]["actors"]}
            ult_fights = [f for f in rep["fights"]
                          if f.get("encounterID") in self._encounter_ids]
            rankings_duration = _parse_rankings_duration(rep.get("rankings"))
            self.on_log(f"  [深層 FIGHTS] {code} 《{rep.get('title', '')}》 → {_ult_fights_summary(ult_fights)}")

            # 處理通關場次的玩家最佳紀錄
            kill_job_maps: dict = {}
            for fight in ult_fights:
                if self._stop.is_set():
                    break
                if not _is_kill(fight):
                    continue
                tc_in = _tc_actors(fight, by_id, self._tc_servers)
                if not tc_in:
                    continue

                # 若此通關場次缺少 rankings.duration（zone 62 嵌入的絕境戰常見），
                # 額外補查一次以取得正確時間分母；失敗則稍後 fallback 估算值。
                if fight["id"] not in (rankings_duration or {}):
                    rq = self._gql(RANKINGS_QUERY, {
                        "code": code,
                        "fightIDs": [fight["id"]],
                    })
                    if rq:
                        extra = _parse_rankings_duration(
                            rq["reportData"]["report"].get("rankings")
                        )
                        if extra:
                            if rankings_duration is None:
                                rankings_duration = {}
                            rankings_duration.update(extra)
                            self.on_log(
                                f"  [rankings補查] fight#{fight['id']}: "
                                f"duration={extra.get(fight['id'], '?')}ms"
                            )

                time.sleep(self._fight_delay)
                pts_now_raw, _, job_map = self._process_kill_bests(
                    report_obj, fight, tc_in, bests, pts_start or 0,
                    rankings_duration=rankings_duration,
                )
                kill_job_maps[fight["id"]] = job_map
                if pts_now_raw is not None:
                    if pts_start is None:
                        pts_start = pts_now_raw
                    elif pts_now_raw < pts_start:
                        pts_start = 0
                    res.pts_used = pts_now_raw - pts_start
                    self.on_status({"points": res.pts_used})

            # 處理未通關場次的玩家最佳進度
            if not self._stop.is_set():
                wipe_candidates = [
                    (f, _tc_actors(f, by_id, self._tc_servers))
                    for f in ult_fights if not _is_kill(f)
                ]
                wipe_candidates = [(f, a) for f, a in wipe_candidates if a]
                if wipe_candidates:
                    pts_now_raw = self._process_all_wipe_bests(
                        report_obj, wipe_candidates, bests
                    )
                    if pts_now_raw is not None:
                        if pts_start is None:
                            pts_start = pts_now_raw
                        elif pts_now_raw < pts_start:
                            pts_start = 0
                        res.pts_used = pts_now_raw - pts_start
                        self.on_status({"points": res.pts_used})

            # 處理通關的 clear 紀錄
            for kill in [f for f in ult_fights if _is_kill(f)]:
                key = f"{code}:{kill['id']}"
                if key in seen_keys:
                    continue
                players = _tc_players(by_id, kill.get("friendlyPlayers", []), self._tc_servers)
                if not players:
                    continue
                clear_dt_ms = report_obj["startTime"] + kill["endTime"]
                sig = "|".join(sorted(players)) + ":" + str(clear_dt_ms)
                if sig in seen_clear_sigs:
                    self.on_log(f"  [跳過] 重複通關 (不同 report): {code}:{kill['id']}")
                    seen_keys.add(key)
                    continue
                seen_clear_sigs.add(sig)
                seen_keys.add(key)
                self.on_clear(ClearRecord(
                    code        = code,
                    title       = rep.get("title", ""),
                    encounter   = kill.get("name", "Unknown"),
                    players     = players,
                    fight_id    = kill["id"],
                    duration_ms = kill["endTime"] - kill["startTime"],
                    clear_dt_ms = clear_dt_ms,
                    jobs        = kill_job_maps.get(kill["id"], {}),
                ))

        bests.save()
        self.on_log(f"手動補抓完成。共使用 {res.pts_used}pt")
        self.on_status({"state": "閒置", "points": res.pts_used})
        self.on_done({"reason": "done_manual"})

    # ── 核心掃描引擎 ──────────────────────────────────────────────────────────

    def _do_scan(
        self,
        start_ms:        int,
        end_ms:          Optional[int],
        seen_keys:       set,
        seen_clear_sigs: set,
        bests:           PlayerBests,
        zone_id:         int = 59,
        zone_name:       str = "絕境戰",
        pts_budget_used: int = 0,
    ) -> _ScanResult:
        """批次掃描引擎。

        演算法概要：
          外層迴圈（batch）：每批處理一個時間視窗 [batch_start, end_time]
            內層迴圈（page）：逐頁抓取 SCAN_QUERY
              - Early-exit：若首筆 TC 已存在 → probe 下頁 → 決定是否跳過
              - 逐份 report：
                  - 跳過非 TC 或已處理的 report
                  - FIGHTS_QUERY 取得戰鬥列表
                  - 通關場次 → DETAIL_QUERY 取 rDPS → 更新 PlayerBest
                  - 未通關場次 → 批次 DETAIL_QUERY → 更新 PlayerBest
                  - 通關場次 → 寫入 ClearRecord（帶去重）
          批次結束：移動視窗到前一批（end_time = batch_start - 1）
        """
        res = _ScanResult()
        # 若 end_ms 為 None（即現在），取當前時間戳作為具體邊界
        end_time: float = float(end_ms) if end_ms is not None else float(int(time.time() * 1000))
        pts_start: Optional[int] = None
        effective_limit = self._point_limit - pts_budget_used

        # seen_codes 合併兩個來源：本次已處理 + 跨次快取
        # 這樣 early-exit 和 skip 才能同時考慮兩者
        seen_codes = {k.split(":")[0] for k in seen_keys} | self.processed_codes

        for batch in range(1, self._max_batches + 1):
            if self._stop.is_set():
                break

            # 計算本批時間視窗：向前最多 window_ms，不超過 start_ms
            batch_start = max(float(start_ms), end_time - self._window_ms)
            batch_done = False
            new_codes_in_batch: set = set()   # 本批新掃到的 report codes（用於 checkpoint 回呼）

            _preloaded: Optional[dict] = None  # early-exit probe 的預讀結果

            for page in range(1, self._max_pages + 1):
                if self._stop.is_set():
                    break

                # 取得本頁資料（優先使用 probe 預讀結果以節省 API 點數）
                if _preloaded is not None:
                    data, _preloaded = _preloaded, None
                else:
                    if page > 1:
                        time.sleep(self._page_delay)
                    data = self._gql(SCAN_QUERY, {
                        "page": page, "startTime": batch_start, "endTime": end_time, "zoneID": zone_id
                    })
                    if data is None:
                        break

                # 更新點數計數（處理整點 rollover：新值 < 舊值時重設基準）
                pts_now = data["rateLimitData"]["pointsSpentThisHour"]
                if pts_start is None:
                    pts_start = pts_now
                elif pts_now < pts_start:
                    pts_start = 0
                res.pts_used = pts_now - pts_start
                self.on_status({"points": res.pts_used})

                if res.pts_used >= effective_limit:
                    self.on_log(f"積分上限 {pts_budget_used + res.pts_used}/{self._point_limit}pt，停止。")
                    batch_done = True
                    break

                pg       = data["reportData"]["reports"]
                reps     = pg["data"]
                has_more = pg["has_more_pages"]

                if not reps:
                    batch_done = True
                    break

                # ── Early-exit 機制（方法二：處理前 probe）─────────────────────
                # 若本頁首筆 TC report 已在 seen_codes → 有機會跳過後續頁面
                first_tc_rep = next(
                    (r for r in reps if r.get("masterData") and _is_tc(r["masterData"]["actors"], self._tc_servers)), None
                )
                if (not self._stop.is_set()
                        and first_tc_rep is not None
                        and first_tc_rep["code"] in seen_codes):

                    time.sleep(self._page_delay)
                    probe = self._gql(SCAN_QUERY, {
                        "page": page + 1, "startTime": batch_start, "endTime": end_time, "zoneID": zone_id,
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
                        # 檢查 probe 頁是否有任何新 TC（不只看第一筆）
                        has_new_tc = any(
                            r.get("masterData") and _is_tc(r["masterData"]["actors"], self._tc_servers)
                            and r["code"] not in seen_codes
                            for r in probe_reps
                        )
                        if has_new_tc:
                            # 下一頁有新資料 → 本頁仍需完整掃描，先暫存 probe 結果
                            self.on_log(f"  [批{batch} 頁{page:2d}] 首筆TC重複，下頁有新TC，補掃此頁")
                            _preloaded = probe
                        else:
                            # 下一頁也沒新資料 → 後續全部跳過
                            self.on_log(f"  [批{batch}] 首筆TC重複，下頁亦無新TC，跳過後續頁面")
                            batch_done = True

                if batch_done:
                    break

                # ── 逐份 report 處理 ──────────────────────────────────────────
                tc_count   = 0   # 本頁新處理的 TC report 數
                tc_skipped = 0   # 本頁跳過的 TC report 數（已在 seen_codes）

                for report in reps:
                    if self._stop.is_set():
                        break

                    st = report["startTime"]
                    if self.on_progress:
                        self.on_progress({"current_ts": report.get("endTime", st)})

                    # 跳過非繁中服 report
                    if not report.get("masterData") or \
                            not _is_tc(report["masterData"]["actors"], self._tc_servers):
                        continue

                    # 跳過已處理的 report（processed_codes 快取命中）
                    if report["code"] in seen_codes:
                        self.on_log(f"  [跳過] {report['code']} 已有紀錄")
                        tc_skipped += 1
                        continue

                    tc_count += 1
                    time.sleep(self._fight_delay)

                    new_codes_in_batch.add(report["code"])
                    seen_codes.add(report["code"])

                    # 取得完整戰鬥列表
                    fdata = self._gql(FIGHTS_QUERY, {"code": report["code"]})
                    if fdata is None:
                        break

                    pts_now = fdata["rateLimitData"]["pointsSpentThisHour"]
                    if pts_start is None:
                        pts_start = pts_now
                    elif pts_now < pts_start:
                        pts_start = 0
                    res.pts_used = pts_now - pts_start
                    self.on_status({"points": res.pts_used})

                    if res.pts_used >= effective_limit:
                        self.on_log(f"積分上限 {pts_budget_used + res.pts_used}/{self._point_limit}pt，停止。")
                        batch_done = True
                        break

                    rep      = fdata["reportData"]["report"]
                    by_id    = {a["id"]: a for a in rep["masterData"]["actors"]}
                    # 只取絕境戰的場次（過濾掉 Extreme/Savage 等）
                    ult_fights = [f for f in rep["fights"]
                                  if f.get("encounterID") in self._encounter_ids]
                    # rankings.duration：FFLogs 網頁使用的時間分母（fight_id → ms）
                    rankings_duration = _parse_rankings_duration(rep.get("rankings"))
                    self.on_log(f"  [深層 FIGHTS] {report['code']} 《{rep.get('title', '')}》 → {_ult_fights_summary(ult_fights)}")

                    # 處理通關場次：每場各呼叫一次 DETAIL_QUERY 取 rDPS
                    kill_job_maps: dict = {}   # fight_id → {"玩家名@伺服器": "職業"}
                    for fight in ult_fights:
                        if self._stop.is_set():
                            break
                        if not _is_kill(fight):
                            continue
                        tc_in = _tc_actors(fight, by_id, self._tc_servers)
                        if not tc_in:
                            continue

                        # 若此通關場次缺少 rankings.duration（zone 62 嵌入的絕境戰常見），
                        # 額外補查一次以取得正確時間分母；失敗則稍後 fallback 估算值。
                        if fight["id"] not in (rankings_duration or {}):
                            rq = self._gql(RANKINGS_QUERY, {
                                "code": report["code"],
                                "fightIDs": [fight["id"]],
                            })
                            if rq:
                                extra = _parse_rankings_duration(
                                    rq["reportData"]["report"].get("rankings")
                                )
                                if extra:
                                    if rankings_duration is None:
                                        rankings_duration = {}
                                    rankings_duration.update(extra)
                                    self.on_log(
                                        f"  [rankings補查] fight#{fight['id']}: "
                                        f"duration={extra.get(fight['id'], '?')}ms"
                                    )

                        pts_now, _, job_map = self._process_kill_bests(
                            report, fight, tc_in, bests, pts_start or 0,
                            rankings_duration=rankings_duration,
                        )
                        kill_job_maps[fight["id"]] = job_map
                        if pts_now is not None:
                            if pts_start is None:
                                pts_start = pts_now
                            elif pts_now < pts_start:
                                pts_start = 0
                            res.pts_used = pts_now - pts_start
                            self.on_status({"points": res.pts_used})
                        if res.pts_used >= effective_limit:
                            batch_done = True
                            break

                    # 處理未通關場次：整份 report 一次 DETAIL_QUERY（批次節省點數）
                    if not batch_done and not self._stop.is_set():
                        wipe_candidates = [
                            (f, _tc_actors(f, by_id, self._tc_servers))
                            for f in ult_fights if not _is_kill(f)
                        ]
                        wipe_candidates = [(f, a) for f, a in wipe_candidates if a]
                        if wipe_candidates:
                            pts_now = self._process_all_wipe_bests(
                                report, wipe_candidates, bests
                            )
                            if pts_now is not None:
                                if pts_start is None:
                                    pts_start = pts_now
                                elif pts_now < pts_start:
                                    pts_start = 0
                                res.pts_used = pts_now - pts_start
                                self.on_status({"points": res.pts_used})
                            if res.pts_used >= effective_limit:
                                batch_done = True

                    if batch_done:
                        break

                    # 寫入通關的 ClearRecord（帶四層去重）
                    for kill in [f for f in ult_fights if _is_kill(f)]:
                        key = f"{report['code']}:{kill['id']}"
                        if key in seen_keys:
                            continue  # 第一層：本次 session 內已存
                        players = _tc_players(by_id, kill.get("friendlyPlayers", []), self._tc_servers)
                        if not players:
                            continue
                        clear_dt_ms = report["startTime"] + kill["endTime"]
                        # 第四層去重：相同隊伍 + 相同時間戳 = 同一場（防不同 report 重複）
                        sig = "|".join(sorted(players)) + ":" + str(clear_dt_ms)
                        if sig in seen_clear_sigs:
                            self.on_log(f"  [跳過] 重複通關 (不同 report): {report['code']}:{kill['id']}")
                            seen_keys.add(key)
                            continue
                        seen_clear_sigs.add(sig)
                        seen_keys.add(key)
                        self.on_clear(ClearRecord(
                            code        = report["code"],
                            title       = rep["title"],
                            encounter   = kill.get("name", "Unknown"),
                            players     = players,
                            fight_id    = kill["id"],
                            duration_ms = kill["endTime"] - kill["startTime"],
                            clear_dt_ms = clear_dt_ms,
                            jobs        = kill_job_maps.get(kill["id"], {}),
                        ))

                skip_lbl = f" ({tc_skipped}跳)" if tc_skipped else ""
                self.on_log(
                    f"  [淺層 SCAN {zone_name} 批{batch} 頁{page:2d}] "
                    f"{len(reps)}筆, {tc_count}筆TC{skip_lbl} "
                    f"({'有更多' if has_more else '末頁'}) [{pts_budget_used + res.pts_used}pt]"
                )

                if not has_more:
                    batch_done = True

                if batch_done:
                    break

            # 本批結束：通知 checkpoint（用於更新 processed_codes）
            if self.on_checkpoint:
                self.on_checkpoint(int(batch_start), new_codes_in_batch)
            # 同步更新 self.processed_codes：讓同一輪後續 _do_scan 呼叫
            # （兩階段掃描下 Phase 2 緊接著 Phase 1）能即時看到剛處理的 codes，
            # 避免歷史補查視窗碰到 Phase 1 才剛抓過的 report 又重做一次。
            if new_codes_in_batch:
                self.processed_codes |= new_codes_in_batch

            # 若本批已觸底（到達目標日期），掃描完成
            if batch_start <= float(start_ms):
                res.completed = True
                break

            if self._stop.is_set():
                break

            # 移動視窗到前一批（固定步進，不使用游標）
            end_time = batch_start - 1

        return res

    # ── 玩家最佳紀錄 helper ───────────────────────────────────────────────────

    def _process_kill_bests(self, report, fight, tc_actors, bests, pts_start_ref,
                            rankings_duration: Optional[dict] = None):
        """呼叫 DETAIL_QUERY 取得單場通關的 rDPS，更新各玩家最佳紀錄。

        rDPS 時間分母優先使用 rankings_duration（FFLogs 網頁同源），
        不存在時退回 totalTime - damageDowntime。

        回傳：(pts_now_raw, did_update, job_map)
        """
        self.on_log(f"  [深層 DETAIL] 《{fight.get('name', '')}》 fight#{fight['id']}")
        ddata = self._gql(DETAIL_QUERY, {
            "code": report["code"],
            "fightIDs": [fight["id"]],
        })
        if ddata is None:
            return None, False, {}

        pts_now_raw = ddata["rateLimitData"]["pointsSpentThisHour"]

        table_data = ddata["reportData"]["report"]["table"]["data"]

        # 時間分母：rankings.duration 通常與 FFLogs 網頁一致（已扣 downtime），
        # 但下列兩種情況 rankings.duration 會回傳 ≈ raw fight time（未扣 downtime）：
        #   (a) zone 62（Savage）報告中嵌入的絕境戰場次
        #   (b) FRU（1079）在 zone 65：實測 rd 與 raw 僅差約 1 秒，但 damageDowntime≈287s
        # 偵測訊號：rd > raw - 50_000。命中時優先用 totalTime - damageDowntime
        # （DETAIL_QUERY 通常有真實值），缺值才退回估算表。
        if rankings_duration is not None and fight["id"] in rankings_duration:
            rd     = rankings_duration[fight["id"]]
            raw_ms = fight["endTime"] - fight["startTime"]
            enc_id = fight.get("encounterID")
            if rd > raw_ms - 50_000:
                total_time_ms      = table_data.get("totalTime") or raw_ms
                damage_downtime_ms = table_data.get("damageDowntime") or 0
                if damage_downtime_ms > 0:
                    effective_ms = total_time_ms - damage_downtime_ms
                    self.on_log(
                        f"    [rDPS分母] rankings.duration={rd/1000:.0f}s≈raw（未扣downtime），"
                        f"改用 totalTime-damageDowntime={total_time_ms/1000:.0f}s-"
                        f"{damage_downtime_ms/1000:.0f}s = {effective_ms/1000:.0f}s"
                    )
                else:
                    estimated = _ENCOUNTER_DOWNTIME_ESTIMATE.get(enc_id, 0)
                    if estimated:
                        effective_ms = raw_ms - estimated
                        self.on_log(
                            f"    [rDPS分母] rankings.duration={rd/1000:.0f}s≈raw 且 "
                            f"damageDowntime=0，用估算 {estimated/1000:.0f}s → 分母="
                            f"{effective_ms/1000:.0f}s"
                        )
                    else:
                        effective_ms = rd
                        self.on_log(
                            f"    [⚠ rDPS] enc={enc_id}: rankings.duration≈raw 且無 "
                            f"damageDowntime/估算 → 分母={effective_ms/1000:.0f}s，rDPS 恐偏低"
                        )
            else:
                effective_ms = rd
        else:
            raw_ms             = fight["endTime"] - fight["startTime"]
            total_time_ms_raw  = table_data.get("totalTime")
            total_time_ms      = total_time_ms_raw or raw_ms
            damage_downtime_ms = table_data.get("damageDowntime") or 0
            # damageDowntime=0 時：DETAIL_QUERY 對非主 zone 場次（如 zone 62 嵌入的絕境戰）
            # 可能不回傳此欄位。使用已知估算值補足，避免 rDPS 以全程時長為分母而嚴重偏低。
            if damage_downtime_ms == 0:
                enc_id    = fight.get("encounterID")
                estimated = _ENCOUNTER_DOWNTIME_ESTIMATE.get(enc_id, 0)
                if estimated:
                    damage_downtime_ms = estimated
                    self.on_log(
                        f"    [rDPS分母] enc={enc_id}: damageDowntime=0，"
                        f"使用估算值 {estimated/1000:.0f}s"
                    )
            effective_ms = total_time_ms - damage_downtime_ms
            if damage_downtime_ms == 0 and effective_ms > raw_ms * 0.9:
                self.on_log(
                    f"    [⚠ rDPS] fight#{fight['id']} enc={fight.get('encounterID')}: "
                    f"rankings無資料且damageDowntime=0（無估算值）→ 分母={effective_ms/1000:.0f}s"
                    f"（≈原始時長），rDPS 恐嚴重偏低"
                )
            else:
                self.on_log(
                    f"    [rDPS分母] fallback: "
                    f"{total_time_ms/1000:.0f}s - {damage_downtime_ms/1000:.0f}s"
                    f" = {effective_ms/1000:.0f}s"
                )
        fight_s = effective_ms / 1000 if effective_ms > 0 else \
                  (fight["endTime"] - fight["startTime"]) / 1000

        if fight_s <= 0:
            return pts_now_raw, False, {}

        # 建立「玩家名 → 傷害統計」的查找表（table entries 用名稱索引）
        table_by_name: dict = {e.get("name", ""): e for e in table_data["entries"]}

        did_update = False
        job_map: dict = {}  # 回傳給外層，用於 ClearRecord.jobs 欄位

        for p in tc_actors:
            name   = p["name"]
            server = p.get("server", "")
            tbl    = table_by_name.get(name)
            if not tbl:
                self.on_log(f"    [跳過] {name}@{server} 不在 DamageDone table（輔助職或資料缺失）")
                continue

            # 將總傷害量除以有效時間轉為 per-second 數值
            rdps      = tbl.get("totalRDPS", 0.0) / fight_s
            adps      = tbl.get("totalADPS", 0.0) / fight_s
            parse_pct = float(tbl.get("rankPercent") or 0.0)
            job       = tbl.get("type", "Unknown")
            char_id   = tbl.get("guid", 0)

            if job and job != "Unknown":
                job_map[f"{name}@{server}"] = job

            pb = PlayerBest(
                name=name, server=server,
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
                    f"  ★ 最佳更新: {name}@{server} "
                    f"[{job}] rDPS={rdps:.0f} aDPS={adps:.0f} ({parse_str}) "
                    f"「{fight.get('name','')[:20]}」"
                )

        return pts_now_raw, did_update, job_map

    def _process_all_wipe_bests(self, report, wipe_fights_with_actors, bests) -> Optional[int]:
        """處理一份 report 中所有未通關場次的最佳進度，只用一次 DETAIL_QUERY。

        策略：對每個玩家只取其個人最佳團滅（最低 boss_hp_pct），
              收集這些最佳場次的 fight_id，一次批次查詢取得職業資訊。
              節省點數（否則每場各一次 DETAIL_QUERY）。
        """
        # "name@server:enc_id" → (fight, fight_pct, player_dict)
        player_best: dict = {}
        for fight, tc_actors in wipe_fights_with_actors:
            fight_pct = fight.get("fightPercentage")
            if fight_pct is None:
                continue
            enc_id = fight.get("encounterID")
            for p in tc_actors:
                name, server = p["name"], p.get("server", "")
                # 若玩家已有通關或更好的團滅進度，跳過（省點數）
                if bests.can_skip_wipe(name, server, enc_id, fight_pct):
                    continue
                key = f"{name}@{server}:{enc_id}"
                existing = player_best.get(key)
                if existing is None or fight_pct < existing[1]:
                    player_best[key] = (fight, fight_pct, p)

        if not player_best:
            return None  # 所有玩家都可跳過，不需消耗點數

        # 取出每個玩家最佳場次的 fight_id（通常只有 1–2 個唯一值）
        best_fight_ids = list({f["id"] for f, _, _ in player_best.values()})
        self.on_log(f"  [深層 DETAIL] 批次團滅 {len(best_fight_ids)} 場")
        ddata = self._gql(DETAIL_QUERY, {"code": report["code"], "fightIDs": best_fight_ids})

        table_by_name: dict = {}
        pts_now: Optional[int] = None
        if ddata is not None:
            pts_now = ddata["rateLimitData"]["pointsSpentThisHour"]
            for entry in ddata["reportData"]["report"]["table"]["data"]["entries"]:
                table_by_name[entry.get("name", "")] = entry

        for _key, (fight, fight_pct, p) in player_best.items():
            name, server = p["name"], p.get("server", "")
            tbl    = table_by_name.get(name, {})
            enc_id = fight["encounterID"]
            pb = PlayerBest(
                name=name, server=server,
                encounter_id=enc_id,
                encounter=fight.get("name", "Unknown"),
                is_clear=False, boss_hp_pct=fight_pct,
                phase_reached=_wipe_phase(fight, enc_id),
                rdps=0.0, adps=0.0, parse_pct=0.0,
                # 優先用 table 的職業，否則退回 masterData 的 subType
                job=tbl.get("type") or p.get("subType") or "Unknown",
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

    # ── 網路層 ────────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        """向 FFLogs OAuth 端點取得 Bearer Token（client_credentials 流程）。"""
        r = requests.post(
            OAUTH_URL,
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["access_token"]

    def _gql(self, query: str, variables: Optional[dict] = None) -> Optional[dict]:
        """送出 GraphQL 請求，自動處理 429 限流與網路錯誤重試（最多 5 次）。

        回傳 data 欄位內容；失敗或停止時回傳 None。
        """
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
                    # 讀取伺服器指定的等待時間，逐秒等待並檢查停止訊號
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
                time.sleep(5 * (attempt + 1))  # 指數退避：5s, 10s, 15s, 20s
        return None


# ── 模組級 helper 函式 ────────────────────────────────────────────────────────

def _parse_rankings_duration(rankings_raw) -> dict:
    """從 FIGHTS_QUERY 的 rankings 欄位解析出 {fight_id: duration_ms}。

    rankings 是 FFLogs 回傳的 JSON blob（dict 或字串），
    duration 是 FFLogs 網頁顯示 rDPS 所用的時間分母，比 endTime-startTime 略短。
    解析失敗時回傳空 dict，呼叫端會 fallback 至 totalTime-damageDowntime。
    """
    if not rankings_raw:
        return {}
    try:
        raw = rankings_raw if isinstance(rankings_raw, dict) else json.loads(rankings_raw)
        return {f["fightID"]: f["duration"] for f in raw.get("data", []) if "duration" in f}
    except Exception:
        return {}


def _is_tc(actors: list, servers: Optional[set] = None) -> bool:
    """判斷此 report 是否包含繁中服玩家（至少一名）。

    servers 為 None 時使用模組預設 TC_SERVERS（向後相容 GUI 呼叫）。
    """
    if not actors:
        return False
    s = servers if servers is not None else TC_SERVERS
    return any(a.get("server") in s for a in actors)


def _is_kill(fight: dict) -> bool:
    """判斷此場戰鬥是否為通關。

    UCoB 特殊規則（encounterID == 1073）：
      FFLogs 不標記 UCoB 為 kill=true，需手動以三個條件判斷：
        1. fightPercentage == 80（通關結束的 HP 閾值）
        2. fight name 包含 "Bahamut Prime"（確認已進入 P3+ 階段）
        3. 戰鬥時長 ≥ 13 分鐘（排除 P4/P5 轉換點全滅：fp 同樣為 80 但時長僅約 10 分鐘）
      其他副本直接使用 FFLogs 原生 kill 旗標。
    """
    if fight.get("encounterID") == 1073:
        return (
            fight.get("fightPercentage") == 80
            and "Bahamut Prime" in fight.get("name", "")
            and (fight["endTime"] - fight["startTime"]) >= 780_000
        )
    return bool(fight.get("kill"))


def _tc_actors(fight: dict, by_id: dict, servers: Optional[set] = None) -> list:
    """回傳此場戰鬥中屬於繁中服的玩家 actor 列表。

    friendlyPlayers 為 actor id 列表，需透過 by_id 對照取得完整資訊。
    """
    s = servers if servers is not None else TC_SERVERS
    return [
        a for fid in fight.get("friendlyPlayers", [])
        if (a := by_id.get(fid)) and a.get("server") in s
    ]


def _tc_players(by_id: dict, ids: list, servers: Optional[set] = None) -> list:
    """回傳此場戰鬥中繁中服玩家的 "名@伺服器" 字串列表。"""
    s = servers if servers is not None else TC_SERVERS
    return [
        f"{a['name']}@{a['server']}"
        for fid in ids
        if (a := by_id.get(fid)) and a.get("server") in s
    ]


def _fmt_dt(epoch_ms) -> str:
    """將毫秒時間戳格式化為人類可讀的 UTC 字串。"""
    return datetime.fromtimestamp(float(epoch_ms) / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def _ult_fights_summary(fights: list) -> str:
    """將絕境戰場次列表轉為人類可讀摘要，例如「絕歐米茄 ×2通×5滅」。"""
    summary: dict[str, list[int, int]] = {}
    for f in fights:
        name = _ENCOUNTER_NAMES.get(f.get("encounterID", 0), f"enc{f.get('encounterID')}")
        if name not in summary:
            summary[name] = [0, 0]
        if _is_kill(f):
            summary[name][0] += 1
        else:
            summary[name][1] += 1
    parts = []
    for name, (kills, wipes) in summary.items():
        s = name
        if kills:
            s += f" ×{kills}通"
        if wipes:
            s += f"×{wipes}滅"
        parts.append(s)
    return "、".join(parts) if parts else "無絕境戰場次"
