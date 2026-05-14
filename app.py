"""TC Tomestone 通關追蹤器 — GUI 主程式"""
import csv
import json
import queue
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from tkinter import filedialog, messagebox

from scraper_core import ClearRecord, Scraper


# ── path helpers ──────────────────────────────────────────────────────────────

def _data_dir() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    return base


CLEARS_PATH    = _data_dir() / "clears.json"
BESTS_PATH     = _data_dir() / "player_bests.json"
SETTINGS_PATH  = _data_dir() / "settings.json"
CONFIG_PATH    = _data_dir() / "config.json"
PROCESSED_PATH = _data_dir() / "processed_codes.json"

_DEFAULT_START = "2026-02-01 00:00"
_DEFAULT_END   = ""   # empty = now


# ── formatting ────────────────────────────────────────────────────────────────

def fmt_dt(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def fmt_dur(ms: int) -> str:
    s = int(ms / 1000)
    return f"{s // 60}:{s % 60:02d}"


def now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _load_settings() -> dict:
    try:
        if SETTINGS_PATH.exists():
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_settings(d: dict):
    try:
        SETTINGS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _load_processed_codes() -> set:
    try:
        if PROCESSED_PATH.exists():
            return set(json.loads(PROCESSED_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return set()


def _save_processed_codes(codes: set):
    try:
        PROCESSED_PATH.write_text(
            json.dumps(sorted(codes), ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _load_config() -> Optional[dict]:
    """Load config.json; return None if missing or malformed."""
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_dt_ms(s: str) -> Optional[int]:
    """Parse 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD' → epoch ms (UTC).
    Empty string → None (= now / no bound).
    Returns -1 if the string is non-empty but invalid.
    """
    s = s.strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return -1   # invalid sentinel


# ── stat card ─────────────────────────────────────────────────────────────────

class StatCard(ctk.CTkFrame):
    def __init__(self, master, label: str, **kw):
        super().__init__(master, corner_radius=12, **kw)
        self.configure(fg_color=("gray88", "gray20"))
        ctk.CTkLabel(self, text=label, font=ctk.CTkFont(size=11),
                     text_color=("gray40", "gray60")).pack(padx=14, pady=(10, 2))
        self._lbl = ctk.CTkLabel(self, text="—",
                                  font=ctk.CTkFont(size=22, weight="bold"))
        self._lbl.pack(padx=14, pady=(0, 10))

    def set(self, val: str):
        self._lbl.configure(text=val)


# ── results table ─────────────────────────────────────────────────────────────

_HDR  = ("副本", "通關時間 (UTC)", "用時", "TC 玩家")
_COLS = (220, 130, 55, 420)


class _TableHeader(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, corner_radius=0,
                         fg_color=("gray78", "gray28"), **kw)
        for c, (txt, w) in enumerate(zip(_HDR, _COLS)):
            ctk.CTkLabel(self, text=txt, width=w, anchor="w",
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=("gray20", "gray90")
                         ).grid(row=0, column=c, padx=(10, 4), pady=7, sticky="w")


class _ClearRow(ctk.CTkFrame):
    def __init__(self, master, rec: ClearRecord, idx: int, **kw):
        bg = ("gray92", "gray22") if idx % 2 == 0 else ("gray86", "gray18")
        super().__init__(master, corner_radius=0, fg_color=bg, **kw)

        cells = (
            rec.encounter[:36],
            fmt_dt(rec.clear_dt_ms),
            fmt_dur(rec.duration_ms),
            ", ".join(rec.players),
        )
        for c, (txt, w) in enumerate(zip(cells, _COLS)):
            lbl = ctk.CTkLabel(self, text=txt, width=w, anchor="w",
                               font=ctk.CTkFont(size=12), wraplength=w - 6)
            lbl.grid(row=0, column=c, padx=(10, 4), pady=5, sticky="w")
            lbl.bind("<Button-1>", lambda _e, url=rec.url: webbrowser.open(url))
        self.bind("<Button-1>", lambda _e, url=rec.url: webbrowser.open(url))
        self.bind("<Enter>", lambda _e: self.configure(fg_color=("gray80", "gray30")))
        self.bind("<Leave>", lambda _e: self.configure(fg_color=bg))


# ── main window ───────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("TC Tomestone 通關追蹤器")
        self.geometry("1200x780")
        self.minsize(1000, 620)

        self._q: queue.Queue = queue.Queue()
        self._scraper: Optional[Scraper] = None
        self._thread:  Optional[threading.Thread] = None
        self._auto_job = None
        self._auto_on  = False
        self._clears:  list[ClearRecord] = []
        self._row_idx  = 0

        settings = _load_settings()
        # Migration: remove stale cursor fields written by older versions
        if "scan_cursor_ms" in settings:
            settings.pop("scan_cursor_ms")
            settings["end_dt"] = ""   # cursor had overwritten end_dt; reset to "now"
            _save_settings(settings)

        # 若舊設定的 start_dt 比預設目標日期新（舊 bug 遺留），重設為預設值
        saved_start = settings.get("start_dt", _DEFAULT_START)
        default_start_ms = _parse_dt_ms(_DEFAULT_START) or 0
        saved_start_ms   = _parse_dt_ms(saved_start) or 0
        if saved_start_ms > default_start_ms:
            saved_start = _DEFAULT_START
        self._v_start = ctk.StringVar(value=saved_start)
        self._v_end   = ctk.StringVar(value=settings.get("end_dt", _DEFAULT_END))
        self._processed_codes: set = _load_processed_codes()

        self._v_start.trace_add("write", lambda *_: self._on_dt_changed())
        self._v_end.trace_add("write",   lambda *_: self._on_dt_changed())

        self._build_ui()
        self._load_clears()
        self._poll()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=2)
        self.grid_rowconfigure(5, weight=1)

        # ─ header ─
        hdr = ctk.CTkFrame(self, fg_color=("gray82", "gray15"), corner_radius=0, height=52)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hdr, text="TC Tomestone  通關追蹤器",
                     font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, padx=20, sticky="w")

        self._mode_btn = ctk.CTkButton(
            hdr, text="☀", width=34, height=28,
            fg_color="transparent", hover_color=("gray70", "gray35"),
            command=self._toggle_mode)
        self._mode_btn.grid(row=0, column=1, padx=12)

        # ─ stat cards ─
        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.grid(row=1, column=0, sticky="ew", padx=16, pady=(12, 6))
        for i in range(5):
            cards.grid_columnconfigure(i, weight=1)

        self._c_state  = StatCard(cards, "狀態")
        self._c_pts    = StatCard(cards, "API 積分 / 本小時")
        self._c_clears = StatCard(cards, "已找通關")
        self._c_last   = StatCard(cards, "上次完成")
        self._c_pos    = StatCard(cards, "目前位置 (↓往舊)")
        for i, c in enumerate([self._c_state, self._c_pts, self._c_clears, self._c_last, self._c_pos]):
            c.grid(row=0, column=i, padx=6, sticky="ew")
        self._c_state.set("閒置")
        self._c_pts.set("0")
        self._c_clears.set("0 筆")
        self._c_last.set("—")
        self._c_pos.set("—")

        # ─ controls row 1: buttons + auto ─
        ctrl = ctk.CTkFrame(self, fg_color=("gray86", "gray18"), corner_radius=12)
        ctrl.grid(row=2, column=0, sticky="ew", padx=16, pady=(6, 2))

        self._btn_export = ctk.CTkButton(
            ctrl, text="匯出 CSV", width=90,
            fg_color="transparent", border_width=1,
            text_color=("gray20", "gray80"),
            command=self._export_csv)
        self._btn_export.pack(side="right", padx=14, pady=12)

        self._btn_start = ctk.CTkButton(
            ctrl, text="▶  開始抓取", width=130,
            fg_color="#2d7d2d", hover_color="#38a038",
            command=self._start)
        self._btn_start.pack(side="left", padx=(14, 6), pady=12)

        self._btn_stop = ctk.CTkButton(
            ctrl, text="⏹  停止", width=100,
            fg_color="#8b2020", hover_color="#b83030",
            state="disabled", command=self._stop)
        self._btn_stop.pack(side="left", padx=6, pady=12)

        _sep(ctrl).pack(side="left", padx=14, pady=12)

        self._sw_auto = ctk.CTkSwitch(
            ctrl, text="自動抓取", font=ctk.CTkFont(size=13),
            command=self._toggle_auto)
        self._sw_auto.pack(side="left", padx=6, pady=12)

        ctk.CTkLabel(ctrl, text="間隔:", font=ctk.CTkFont(size=13)
                     ).pack(side="left", padx=(16, 4), pady=12)
        self._v_interval = ctk.StringVar(value="60")
        ctk.CTkEntry(ctrl, textvariable=self._v_interval, width=52,
                     font=ctk.CTkFont(size=13)).pack(side="left", pady=12)
        ctk.CTkLabel(ctrl, text="分", font=ctk.CTkFont(size=13)
                     ).pack(side="left", padx=(4, 0), pady=12)

        # ─ controls row 2: date range + resume ─
        ctrl2 = ctk.CTkFrame(self, fg_color=("gray86", "gray18"), corner_radius=12)
        ctrl2.grid(row=3, column=0, sticky="ew", padx=16, pady=(2, 6))

        ctk.CTkLabel(ctrl2, text="開始:", font=ctk.CTkFont(size=13)
                     ).pack(side="left", padx=(0, 4), pady=10)
        ctk.CTkEntry(ctrl2, textvariable=self._v_end, width=126,
                     font=ctk.CTkFont(size=13)).pack(side="left", pady=10)
        ctk.CTkLabel(ctrl2, text="(空=現在)", font=ctk.CTkFont(size=11),
                     text_color=("gray40", "gray60")
                     ).pack(side="left", padx=(4, 0), pady=10)

        ctk.CTkLabel(ctrl2, text="→", font=ctk.CTkFont(size=13)
                     ).pack(side="left", padx=8, pady=10)

        ctk.CTkLabel(ctrl2, text="結束:", font=ctk.CTkFont(size=13)
                     ).pack(side="left", padx=(0, 4), pady=10)
        ctk.CTkEntry(ctrl2, textvariable=self._v_start, width=126,
                     font=ctk.CTkFont(size=13)).pack(side="left", pady=10)
        ctk.CTkLabel(ctrl2, text="(空=無限)", font=ctk.CTkFont(size=11),
                     text_color=("gray40", "gray60")
                     ).pack(side="left", padx=(4, 0), pady=10)

        self._lbl_dt_hint = ctk.CTkLabel(
            ctrl2, text="", font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"))
        self._lbl_dt_hint.pack(side="left", padx=(6, 0), pady=10)
        self._refresh_dt_hint()

        # ─ results ─
        rf = ctk.CTkFrame(self, corner_radius=12)
        rf.grid(row=4, column=0, sticky="nsew", padx=16, pady=6)
        rf.grid_columnconfigure(0, weight=1)
        rf.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(rf, text="通關紀錄",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, padx=14, pady=(10, 4), sticky="w")

        inner = ctk.CTkFrame(rf, fg_color="transparent")
        inner.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_rowconfigure(1, weight=1)

        _TableHeader(inner).grid(row=0, column=0, sticky="ew")

        self._tbl = ctk.CTkScrollableFrame(inner, corner_radius=0)
        self._tbl.grid(row=1, column=0, sticky="nsew")
        self._tbl.grid_columnconfigure(0, weight=1)

        # ─ log section: debug (left) + findings (right) ─
        log_outer = ctk.CTkFrame(self, fg_color="transparent")
        log_outer.grid(row=5, column=0, sticky="nsew", padx=16, pady=(6, 16))
        log_outer.grid_columnconfigure(0, weight=3)
        log_outer.grid_columnconfigure(1, weight=2)
        log_outer.grid_rowconfigure(0, weight=1)

        # Left: debug log
        lf = ctk.CTkFrame(log_outer, corner_radius=12)
        lf.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        lf.grid_columnconfigure(0, weight=1)
        lf.grid_rowconfigure(1, weight=1)

        lh = ctk.CTkFrame(lf, fg_color="transparent")
        lh.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        ctk.CTkLabel(lh, text="執行日誌",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkButton(lh, text="清除", width=54, height=24,
                      fg_color="transparent", border_width=1,
                      text_color=("gray30", "gray70"),
                      font=ctk.CTkFont(size=11),
                      command=self._clear_log).pack(side="right")

        self._log = ctk.CTkTextbox(
            lf, font=ctk.CTkFont(family="Consolas", size=12),
            state="disabled", wrap="word")
        self._log.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        # Right: findings log (new clears, player best updates)
        ff = ctk.CTkFrame(log_outer, corner_radius=12)
        ff.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        ff.grid_columnconfigure(0, weight=1)
        ff.grid_rowconfigure(1, weight=1)

        fh = ctk.CTkFrame(ff, fg_color="transparent")
        fh.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        ctk.CTkLabel(fh, text="新發現",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkButton(fh, text="清除", width=54, height=24,
                      fg_color="transparent", border_width=1,
                      text_color=("gray30", "gray70"),
                      font=ctk.CTkFont(size=11),
                      command=self._clear_findings).pack(side="right")

        self._findings = ctk.CTkTextbox(
            ff, font=ctk.CTkFont(family="Consolas", size=12),
            state="disabled", wrap="word")
        self._findings.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

    # ── queue polling ─────────────────────────────────────────────────────────

    def _poll(self):
        try:
            while True:
                evt, data = self._q.get_nowait()
                if evt == "log":    self._log_append(data)
                elif evt == "clr":  self._add_row(data)
                elif evt == "sts":  self._update_status(data)
                elif evt == "done": self._on_done(data)
                elif evt == "prog": self._update_progress(data)
                elif evt == "ckpt": self._on_checkpoint(*data)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _emit(self, evt, data=None):
        self._q.put((evt, data))

    # ── UI updaters ───────────────────────────────────────────────────────────

    def _log_append(self, msg: str):
        if msg.startswith("  ★") or msg.startswith("  ↑"):
            self._findings_append(msg)
        else:
            self._debug_append(msg)

    def _debug_append(self, msg: str):
        self._log.configure(state="normal")
        self._log.insert("end", f"[{now_ts()}] {msg}\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _findings_append(self, msg: str):
        self._findings.configure(state="normal")
        self._findings.insert("end", f"[{now_ts()}] {msg}\n")
        self._findings.see("end")
        self._findings.configure(state="disabled")

    def _add_row(self, rec: ClearRecord):
        self._clears.append(rec)
        row = _ClearRow(self._tbl, rec, self._row_idx)
        row.grid(row=self._row_idx, column=0, sticky="ew", pady=1)
        self._row_idx += 1
        self._c_clears.set(f"{len(self._clears)} 筆")
        self._findings_append(
            f"✓ 通關: {rec.encounter} {fmt_dur(rec.duration_ms)}"
            f" | {', '.join(rec.players)}"
        )
        self._save_clears()

    def _update_status(self, d: dict):
        if "state"  in d: self._c_state.set(d["state"])
        if "points" in d: self._c_pts.set(str(d["points"]))

    def _on_done(self, d):
        reason    = d.get("reason", "done") if isinstance(d, dict) else d
        completed = d.get("completed", False) if isinstance(d, dict) else False

        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        self._c_last.set(now_ts())
        self._c_pos.set("—")

        if reason != "error" and completed:
            self._log_append("已掃完目標範圍。")

        if self._auto_on and reason != "stopped":
            try:
                mins = max(1, int(self._v_interval.get()))
            except ValueError:
                mins = 60
            self._log_append(f"自動抓取：{mins} 分後再次執行...")
            self._auto_job = self.after(mins * 60_000, self._start)

    def _on_checkpoint(self, _batch_start_ms: int, new_codes: set):
        self._processed_codes |= new_codes
        _save_processed_codes(self._processed_codes)

    # ── controls ──────────────────────────────────────────────────────────────

    def _start(self):
        if self._thread and self._thread.is_alive():
            return

        end_ms = _parse_dt_ms(self._v_end.get())
        if end_ms == -1:
            messagebox.showerror("格式錯誤", "開始時間格式應為 YYYY-MM-DD HH:MM，或留空表示現在。")
            return

        start_ms = _parse_dt_ms(self._v_start.get())
        if start_ms == -1:
            messagebox.showerror("格式錯誤", "結束時間格式應為 YYYY-MM-DD HH:MM，或留空表示無下限。")
            return

        if end_ms is not None and start_ms is not None and end_ms <= start_ms:
            messagebox.showerror("時間錯誤", "開始時間必須晚於結束時間。")
            return

        cfg = _load_config()
        if not cfg or not cfg.get("client_id") or not cfg.get("client_secret"):
            messagebox.showerror(
                "設定缺失",
                f"找不到或格式錯誤：\n{CONFIG_PATH}\n\n"
                "請確認 config.json 存在且包含 client_id 與 client_secret。"
            )
            return

        seen_keys = {f"{c.code}:{c.fight_id}" for c in self._clears}

        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self._c_state.set("執行中")
        self._c_pos.set("—")

        self._scraper = Scraper(
            on_log          = lambda m: self._emit("log", m),
            on_clear        = lambda r: self._emit("clr", r),
            on_status       = lambda s: self._emit("sts", s),
            on_done         = lambda r: self._emit("done", r),
            on_progress     = lambda p: self._emit("prog", p),
            on_checkpoint   = lambda ms, codes: self._emit("ckpt", (ms, codes)),
            bests_path      = BESTS_PATH,
            start_from_ms   = start_ms or 0,
            end_from_ms     = end_ms,
            seen_keys       = seen_keys,
            processed_codes = set(self._processed_codes),
            client_id       = cfg["client_id"],
            client_secret   = cfg["client_secret"],
        )
        self._thread = threading.Thread(target=self._scraper.run, daemon=True)
        self._thread.start()

    def _on_dt_changed(self):
        self._refresh_dt_hint()
        self._save_all_settings()

    def _refresh_dt_hint(self):
        start_ms = _parse_dt_ms(self._v_start.get())
        end_ms   = _parse_dt_ms(self._v_end.get())

        if start_ms == -1:
            self._lbl_dt_hint.configure(text="結束格式錯誤", text_color="red")
        elif end_ms == -1:
            self._lbl_dt_hint.configure(text="開始格式錯誤", text_color="red")
        elif end_ms is not None and start_ms is not None and end_ms <= start_ms:
            self._lbl_dt_hint.configure(text="開始須晚於結束", text_color="orange")
        else:
            self._lbl_dt_hint.configure(text="✓", text_color="green")

    def _update_progress(self, d: dict):
        if "current_ts" in d:
            self._c_pos.set(fmt_dt(d["current_ts"]))

    def _save_all_settings(self):
        _save_settings({"start_dt": self._v_start.get(), "end_dt": self._v_end.get()})

    def _stop(self):
        self._auto_on = False
        self._sw_auto.deselect()
        if self._auto_job:
            self.after_cancel(self._auto_job)
            self._auto_job = None
        if self._scraper:
            self._scraper.stop()
        self._btn_stop.configure(state="disabled")

    def _toggle_auto(self):
        self._auto_on = bool(self._sw_auto.get())
        if self._auto_on:
            self._log_append("自動抓取已開啟。")
            if not (self._thread and self._thread.is_alive()):
                self._start()
        else:
            self._log_append("自動抓取已關閉。")
            if self._auto_job:
                self.after_cancel(self._auto_job)
                self._auto_job = None

    def _toggle_mode(self):
        new = "Light" if ctk.get_appearance_mode() == "Dark" else "Dark"
        ctk.set_appearance_mode(new)
        self._mode_btn.configure(text="🌙" if new == "Light" else "☀")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _clear_findings(self):
        self._findings.configure(state="normal")
        self._findings.delete("1.0", "end")
        self._findings.configure(state="disabled")

    def _export_csv(self):
        if not self._clears:
            messagebox.showinfo("匯出", "尚無通關資料。")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="tc_clears.csv",
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["副本", "通關時間(UTC)", "用時", "TC玩家", "報告連結"])
            for c in self._clears:
                w.writerow([c.encounter, fmt_dt(c.clear_dt_ms),
                             fmt_dur(c.duration_ms), ", ".join(c.players), c.url])
        messagebox.showinfo("匯出成功", f"已存至\n{path}")

    # ── persistence ───────────────────────────────────────────────────────────

    def _load_clears(self):
        try:
            if CLEARS_PATH.exists():
                raw = json.loads(CLEARS_PATH.read_text(encoding="utf-8"))
                for d in raw:
                    rec = ClearRecord.from_dict(d)
                    self._clears.append(rec)
                    row = _ClearRow(self._tbl, rec, self._row_idx)
                    row.grid(row=self._row_idx, column=0, sticky="ew", pady=1)
                    self._row_idx += 1
                self._c_clears.set(f"{len(self._clears)} 筆")
                self._log_append(f"載入歷史紀錄 {len(self._clears)} 筆。")
        except Exception as e:
            self._log_append(f"載入紀錄失敗: {e}")

    def _save_clears(self):
        try:
            CLEARS_PATH.write_text(
                json.dumps([c.to_dict() for c in self._clears],
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass


# ── helpers ───────────────────────────────────────────────────────────────────

def _sep(parent) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, width=1, height=30, fg_color=("gray60", "gray50"))


if __name__ == "__main__":
    App().mainloop()
