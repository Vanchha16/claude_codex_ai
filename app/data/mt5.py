"""Read-only MetaTrader 5 feed for the user's existing, already logged-in terminal (e.g. Exness MT5).

Uses only initialize/terminal_info/account_info/symbol_info/symbol_info_tick/symbol_select/copy_rates_*/
copy_ticks_range/symbols_get. It never calls order_send/order_check or any trading function, never logs in
(no credentials are passed to initialize) and never searches the disk for terminals or credentials; an explicit
terminal64.exe path may be configured instead.

Time: one contract for every timestamp, app/mt5_time.py. The documented API behaviour is UTC epochs and UTC range
arguments; a server that delivers its own server time needs a VERIFIED entry for that exact server name in
config/mt5_time.json (else the explicit legacy GOLD_MT5_SERVER_UTC_OFFSET_HOURS, default 0). The time base is
resolved for the connected server on every connect and reported in the status; a server change is treated as a
disconnect so the scanner opens a new session watermark under the new time base.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..market import CHART_TIMEFRAMES, ChartBar, normalize
from ..models import H1, M5, UTC, Bar, Quote, SymbolMeta
from ..mt5_time import MT5_TIME_FILE, TimeBase, TimeConfigError, resolve_time_base
from .base import FeedStatus

_TF = {"M5": M5, "H1": H1}


def _run_hidden(args: list[str], timeout: float) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None


def terminal_running() -> Optional[bool]:
    """Is a MetaTrader 5 terminal (terminal64.exe) running? Read-only process listing; no disk search.

    Returns True only on POSITIVE evidence, False only when enumeration succeeded and found none, and None when
    the process list could not be read (e.g. tasklist "ERROR: Access denied"). Callers must treat None as
    "cannot verify" and must not call initialize(), which could launch a terminal."""
    r = _run_hidden(["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/NH"], 5)
    if r is not None and r.returncode == 0:
        out = (r.stdout or "").lower()
        if "terminal64.exe" in out:
            return True
        if "no tasks are running" in out:
            return False
    # tasklist failed, was denied or gave unrecognised output: bounded, hidden, read-only fallback
    r = _run_hidden(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                     "(Get-Process -Name terminal64 -ErrorAction SilentlyContinue).ProcessName"], 10)
    if r is not None and r.returncode == 0:
        return "terminal64" in (r.stdout or "").lower()
    return None
_ACCOUNT_TYPES = {0: "demo", 1: "contest", 2: "real"}
GOLD_PATTERNS = ("*XAU*", "*GOLD*")


class MT5Feed:
    mode = "mt5"
    supports_ticks = True

    def __init__(self, symbol: str, terminal_path: str = "", server_utc_offset_hours: float = 0.0, *, module=None,
                 time_config_path=MT5_TIME_FILE):
        self.symbol = symbol
        self.terminal_path = terminal_path
        self.legacy_offset_hours = server_utc_offset_hours
        self.time_config_path = time_config_path
        # until connected: the explicit legacy offset only (no server known yet, so no server-bound correction)
        self.timebase = TimeBase(server_utc_offset_hours, None, "GOLD_MT5_SERVER_UTC_OFFSET_HOURS (legacy, all servers)"
                                 if server_utc_offset_hours else "default UTC (documented MT5 API behaviour)")
        self._mt5 = module
        self._meta: Optional[SymbolMeta] = None
        self._status = FeedStatus(False, "disconnected", "Not connected yet")
        self._lock = threading.RLock()
        self._initialized = False
        self._identity: Optional[str] = None  # private hash of server+login at connect; never shown or stored
        # real module -> require a user-started terminal; injected test modules skip the process check
        self.require_running_terminal = module is None and os.name == "nt"

    # ---------------------------------------------------------------- connection
    def _module(self):
        if self._mt5 is None:
            try:
                import MetaTrader5 as mt5  # Windows-only package
            except ImportError as exc:
                raise RuntimeError("The MetaTrader5 Python package is not installed in .venv") from exc
            self._mt5 = mt5
        return self._mt5

    def _details(self, extra: Optional[dict] = None) -> dict:
        d = {"provider": "MetaTrader 5 terminal (read-only)", "symbol": self.symbol or None,
             "time_base": self.timebase.to_dict()}
        if self.timebase.offset_hours and self.timebase.source.startswith("GOLD_MT5_SERVER_UTC_OFFSET_HOURS"):
            d["legacy_utc_offset_hours"] = self.timebase.offset_hours
        d.update(extra or {})
        return d

    def connect(self) -> FeedStatus:
        with self._lock:
            # Only attach to a terminal the user already started: MetaTrader5.initialize() would otherwise try to
            # LAUNCH a terminal by itself. This is a process-list check, not a disk search.
            if self.require_running_terminal:
                seen = terminal_running()
                if seen is not True:
                    msg = ("MetaTrader 5 is not running. Start your Exness MT5 terminal and log in; VC Signal connects to it "
                           "automatically (read-only)." if seen is False else
                           "Could not confirm that MetaTrader 5 is running (the Windows process list could not be read), so "
                           "VC Signal did not call initialize(). Check that terminal64.exe is running for this user.")
                    self._status = FeedStatus(False, "disconnected", msg,
                                              self._details({"process_check": "absent" if seen is False else "unknown"}))
                    return self._status
            try:
                mt5 = self._module()
            except RuntimeError as exc:
                self._status = FeedStatus(False, "error", str(exc), self._details())
                return self._status
            ok = mt5.initialize(path=self.terminal_path) if self.terminal_path else mt5.initialize()
            self._initialized = bool(ok)
            if not ok:
                code, msg = mt5.last_error()
                self._status = FeedStatus(False, "disconnected",
                                          f"MT5 initialize failed ({code}: {msg}). Start your MetaTrader 5 terminal and log in "
                                          "to your Exness account, or set the terminal64.exe path in Setup.", self._details())
                return self._status
            info = mt5.terminal_info()
            account = self.account_context()
            self._identity = self._account_identity()
            try:  # the time base of THIS server: a verified server-bound entry, else legacy/UTC; never guessed
                self.timebase = resolve_time_base(account.get("server"), self.legacy_offset_hours, self.time_config_path)
            except TimeConfigError as exc:
                self._meta = None
                self._status = FeedStatus(False, "error", f"MT5 time configuration invalid: {exc}", self._details({"account": account}))
                return self._status
            if info is None or not info.connected:
                self._status = FeedStatus(False, "disconnected",
                                          "The MT5 terminal is running but not connected to the broker server (check its login).",
                                          self._details({"account": account}))
                return self._status
            if not self.symbol:
                candidates = self.discover_gold()
                self._status = FeedStatus(False, "symbol_selection_required",
                                          f"Choose the exact gold symbol in Setup ({len(candidates)} candidate(s) found in this "
                                          "terminal). VC Signal never guesses between contracts.",
                                          self._details({"account": account, "candidates": candidates}))
                return self._status
            si = mt5.symbol_info(self.symbol)
            if si is None:
                self._status = FeedStatus(False, "symbol_missing",
                                          f"Symbol {self.symbol!r} is not available in this terminal. Choose another in Setup.",
                                          self._details({"account": account, "candidates": self.discover_gold()}))
                return self._status
            if not si.visible:
                mt5.symbol_select(self.symbol, True)  # adds it to Market Watch so quotes stream; not a trading action
            tick = si.trade_tick_size or si.point
            self._meta = SymbolMeta(self.symbol, float(tick), float(si.point), int(si.digits), "mt5")
            self._status = FeedStatus(True, "connected", f"Connected to MT5 (read-only), symbol {self.symbol}",
                                      self._details({"account": account, "tick_size": tick, "point": si.point,
                                                     "digits": si.digits, "description": getattr(si, "description", "")}))
            return self._status

    def account_context(self) -> dict:
        """Broker/server context so the user can verify Exness. Never login numbers, names or balances."""
        mt5 = self._mt5
        try:
            acc = mt5.account_info() if mt5 else None
            term = mt5.terminal_info() if mt5 else None
        except Exception:
            return {}
        out = {}
        if acc is not None:
            out.update({"server": getattr(acc, "server", None), "company": getattr(acc, "company", None),
                        "account_type": _ACCOUNT_TYPES.get(getattr(acc, "trade_mode", -1), "unknown")})
        if term is not None:
            out.update({"terminal": getattr(term, "name", None), "terminal_company": getattr(term, "company", None),
                        "build": getattr(term, "build", None), "connected": bool(getattr(term, "connected", False))})
        return out

    def status(self) -> FeedStatus:
        with self._lock:
            if self._mt5 is None or self._meta is None:
                return self._status
            info = self._mt5.terminal_info()
            if info is None or not info.connected:
                self._status = FeedStatus(False, "disconnected", "MT5 terminal disconnected; reconnecting on the next scan.",
                                          self._details())
                self._meta = None
                return self._status
            acc = self._mt5.account_info()
            server = getattr(acc, "server", None) if acc is not None else None
            if server != self.timebase.server or self._account_identity() != self._identity:
                # another account or trade server (possibly another time base): reconnect, so the scanner opens a new
                # session watermark under a freshly resolved time base. The message never names the login.
                what = (f"trade server changed ({self.timebase.server} -> {server})" if server != self.timebase.server
                        else "account changed on the same server")
                self._status = FeedStatus(False, "disconnected", f"MT5 {what}; reconnecting with a new session.",
                                          self._details())
                self._meta = None
            return self._status

    def _account_identity(self) -> Optional[str]:
        try:
            acc = self._mt5.account_info() if self._mt5 else None
        except Exception:
            return None
        if acc is None:
            return None
        raw = f"{getattr(acc, 'server', '')}|{getattr(acc, 'login', '')}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def meta(self) -> SymbolMeta:
        if self._meta is None:
            raise RuntimeError(self._status.message)
        return self._meta

    def now(self) -> datetime:
        return datetime.now(UTC)

    def _api(self):
        """The initialised MetaTrader5 module, or a clear error (never an AttributeError on None)."""
        if self._mt5 is None or not self._initialized:
            raise RuntimeError(f"MT5 is not connected: {self._status.message}")
        return self._mt5

    def _utc(self, epoch_seconds: float) -> datetime:
        """Broker epoch -> UTC through the connected server's time base (see app/mt5_time.py)."""
        return self.timebase.to_utc(epoch_seconds)

    def _req(self, dt: datetime) -> datetime:
        return self.timebase.to_broker(dt)

    # ---------------------------------------------------------------- data
    def quote(self) -> Optional[Quote]:
        with self._lock:
            t = self._mt5.symbol_info_tick(self.symbol) if self._mt5 and self.symbol else None
        if t is None or not t.bid or not t.ask:
            return None
        return Quote(self._utc(t.time_msc / 1000.0), float(t.bid), float(t.ask))

    def _bars(self, rates, tf: str) -> list[Bar]:
        if rates is None:
            return []
        step = _TF[tf]
        return [Bar(self._utc(int(r["time"])), step, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
                for r in rates]

    def closed_bars(self, tf: str, count: int) -> list[Bar]:
        mt5 = self._api()
        with self._lock:
            rates = mt5.copy_rates_from_pos(self.symbol, getattr(mt5, f"TIMEFRAME_{tf}"), 0, count + 1)
        now = self.now()
        return [b for b in self._bars(rates, tf) if b.close_time <= now][-count:]

    def bars_range(self, tf: str, start: datetime, end: datetime) -> list[Bar]:
        mt5 = self._api()
        with self._lock:
            rates = mt5.copy_rates_range(self.symbol, getattr(mt5, f"TIMEFRAME_{tf}"), self._req(start), self._req(end))
        return self._bars(rates, tf)

    def ticks_range(self, start: datetime, end: datetime) -> list[Quote]:
        """Bid/Ask ticks in [start, end], UTC, chronological. Raises if the terminal returns an error (None):
        callers must treat that as a measurement gap, never as 'no price hit'."""
        mt5 = self._api()
        with self._lock:
            ticks = mt5.copy_ticks_range(self.symbol, self._req(start), self._req(end), mt5.COPY_TICKS_INFO)
        if ticks is None:
            code, msg = mt5.last_error()
            raise RuntimeError(f"tick history unavailable ({code}: {msg})")
        out = [Quote(self._utc(int(t["time_msc"]) / 1000.0), float(t["bid"]), float(t["ask"]))
               for t in ticks if t["bid"] and t["ask"]]
        return sorted((q for q in out if q.is_valid()), key=lambda q: q.time)

    # ---------------------------------------------------------------- chart (display only)
    def chart_bars(self, tf: str, count: int, before: Optional[datetime] = None) -> tuple[list[ChartBar], Optional[ChartBar]]:
        """Recent real bars for any chart timeframe. Returns (closed bars, forming bar or None)."""
        mt5 = self._api()
        if not self.symbol:
            raise RuntimeError(self._status.message)
        code = getattr(mt5, f"TIMEFRAME_{tf}")
        seconds = CHART_TIMEFRAMES[tf]
        with self._lock:
            if before is None:
                rates = mt5.copy_rates_from_pos(self.symbol, code, 0, count + 1)
            else:
                rates = mt5.copy_rates_from(self.symbol, code, self._req(before), count + 1)
        if rates is None:
            code_, msg = mt5.last_error()
            raise RuntimeError(f"no {tf} history returned ({code_}: {msg})")
        now = self.now().timestamp()
        bars, forming = [], None
        for r in rates:
            t = int(self._utc(int(r["time"])).timestamp())
            if before is not None and t >= before.timestamp():
                continue
            vol = int(r["tick_volume"]) if "tick_volume" in r.dtype.names else None
            b = ChartBar(t, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), vol)
            if t + seconds > now:
                forming = ChartBar(b.time, b.open, b.high, b.low, b.close, b.volume, forming=True)
            else:
                bars.append(b)
        return normalize(bars)[-count:], (forming if before is None else None)

    # ---------------------------------------------------------------- discovery
    def discover_gold(self) -> list[dict]:
        """Gold-like symbols offered by THIS terminal. The user must pick one explicitly."""
        seen, out = set(), []
        with self._lock:
            mt5 = self._api()  # an unconnected terminal must not look like "no gold symbols"
            for pattern in GOLD_PATTERNS:
                for s in mt5.symbols_get(pattern) or []:
                    if s.name in seen:
                        continue
                    seen.add(s.name)
                    out.append({"name": s.name, "description": s.description, "path": s.path, "visible": bool(s.visible),
                                "digits": s.digits, "tick_size": s.trade_tick_size})
        return sorted(out, key=lambda d: d["name"])

    def list_symbols(self, pattern: str = "*XAU*") -> list[dict]:
        with self._lock:
            syms = self._api().symbols_get(pattern) or []
        return [{"name": s.name, "description": s.description, "path": s.path, "visible": bool(s.visible),
                 "digits": s.digits, "tick_size": s.trade_tick_size, "spread_points": s.spread} for s in syms]

    def shutdown(self) -> None:
        with self._lock:
            if self._mt5 is not None and self._initialized:
                self._mt5.shutdown()
                self._initialized = False
