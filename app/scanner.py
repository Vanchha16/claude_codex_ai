"""Background scanner: one per process. Never blocks web requests. CRT/FastSweep never trade; the opt-in FVG engine
submits only through app/fvg_execution.py when its automatic execution is explicitly ON.

Each scan: check feed health and quote freshness -> track simulated outcomes -> feed newly CLOSED M5 bars
(and H1 closes) to the engine in time order -> live tick invalidation and deadline checks -> queue delivery.
Eligibility: every session (process start/restart, resume, and recovery after a disconnected or stale feed)
opens a fresh in-memory watermark = the time of its first healthy scan. Only confirmations whose M5 bar closed
STRICTLY AFTER that watermark can become signals; earlier ones are consumed inside the Engine without creating a
signal, an active position or an outbox job. A persisted watermark from an older session never authorises anything.
History before the watermark is still used as context (ranges, swings, pending candidates).
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Optional

from .active_strategy import ActiveStrategy
from .config import Settings, StrategyConfig
from .delivery import Delivery
from .engine import Engine
from .fastsweep_live import FastSweepEngine, retire_foreign_pending
from .fvg_live import FvgLiveEngine
from .models import H1, M5, contiguous, iso, parse_iso
from .outcomes import track_live, track_measured
from .store import SqliteStore

_PROCESS_LOCK = threading.Lock()  # enforces a single scanner per process (see app/owner.py for cross-process)
FUTURE_TOLERANCE_SECONDS = 5  # a quote stamped further in the future than this is invalid (clock skew/bad data)
TICK_CHUNK_HOURS = 6  # bounded tick reads for outcome measurement
TICK_MAX_CHUNKS = 8
RECONNECT_MIN_SECONDS = 15  # bounded MT5 reconnect back-off
RECONNECT_MAX_SECONDS = 60
M5_WINDOW = {"crt": 300, "fastsweep": 600, "fvg": 600}  # FastSweep: >= 50 contiguous M15 since the last daily break fit easily


class Scanner:
    def __init__(self, settings: Settings, cfg: StrategyConfig, feed, store: SqliteStore, delivery: Delivery,
                 active: Optional[ActiveStrategy] = None, *, fvg_store=None, fvg_executor_fn=None, fvg_maintenance_fn=None,
                 fvg_account_fn=None):
        self.settings, self.cfg, self.feed, self.store, self.delivery = settings, cfg, feed, store, delivery
        self.active = active or ActiveStrategy("crt")  # CRT-SMC-v1 unless another strategy is explicitly selected
        # FVG only: its own record store and the (default OFF) execution hooks supplied by the workstation
        self.fvg_store = fvg_store
        self.fvg_executor_fn = fvg_executor_fn or (lambda: (None, "automatic execution OFF"))
        self.fvg_maintenance_fn = fvg_maintenance_fn or (lambda: None)
        self.fvg_account_fn = fvg_account_fn or (lambda: None)
        self.engine = None  # Engine (CRT) or FastSweepEngine
        self.paused = store.get_meta("paused", "0") == "1"
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._owns_lock = False
        self.state: dict = {"feed": None, "quote": None, "last_scan": None, "error": None, "data_issues": []}
        self._feed_lock = threading.RLock()
        self.session_watermark: Optional[datetime] = None  # never restored from the database
        self._unhealthy = True  # the first healthy scan opens the session
        self._next_connect = 0.0
        self._skip_to_latest = False  # set by a Resume while disconnected
        self._connect_backoff = RECONNECT_MIN_SECONDS

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if not _PROCESS_LOCK.acquire(blocking=False):
            raise RuntimeError("a scanner is already running in this process")
        self._owns_lock = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="gold-scanner", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        if self._owns_lock:
            _PROCESS_LOCK.release()
            self._owns_lock = False
        with self._feed_lock:
            self.feed.shutdown()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def pause(self) -> None:
        self.paused = True
        self.store.set_meta("paused", "1")
        self.store.add_event("scanner", "paused: no new candidates or alerts; outcome tracking continues")

    def resume(self) -> None:
        with self._feed_lock:
            now = self.feed.now()
            if self.engine:
                self.engine.cancel_pending(now, "cancelled_by_pause")
            try:
                healthy = self.feed.status().ok
            except Exception:
                healthy = False
            if healthy:
                try:
                    self._set_watermark_to_latest()
                    self._open_session(now, "resumed")
                except Exception:
                    healthy = False
            if not healthy:
                # Feed not connected: read no history now. The first HEALTHY scan skips the paused period and
                # opens a fresh eligibility watermark, so nothing confirmed before it can alert.
                self._skip_to_latest = True
                self._unhealthy = True
        self.paused = False
        self.store.set_meta("paused", "0")
        self.store.add_event("scanner", "resumed with a new live-start watermark" if healthy else
                             "resumed while the feed is disconnected; a new session starts when it recovers")

    def _run(self) -> None:
        demo = self.feed.mode == "demo"
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                if demo:
                    # simulated clock: several 5-simulated-second scans per real tick keep live semantics intact
                    tick_real = 0.25
                    steps = max(1, int(round(self.settings.demo_speed * tick_real / 5)))
                    for _ in range(steps):
                        if self.feed.finished:
                            break
                        self.feed.advance(5)
                        self.scan_once()
                    if self.feed.finished:
                        self.scan_once()
                    wait = tick_real
                else:
                    self.scan_once()
                    wait = self.settings.scan_interval_seconds
                self.state["error"] = None
            except Exception as exc:  # keep the worker alive; surface the error in the UI
                self.state["error"] = self.settings.redact(f"{type(exc).__name__}: {exc}")
                self.store.add_event("error", self.state["error"], "error")
                traceback.print_exc()
                wait = self.settings.scan_interval_seconds
            self._stop.wait(max(0.05, wait - (time.monotonic() - started)))

    # ------------------------------------------------------------------ one scan
    def _open_session(self, now: datetime, why: str) -> None:
        self.session_watermark = now
        self._unhealthy = False
        if self.engine:
            self.engine.eligible_after = now
        self.store.set_meta("live_start", iso(now))
        self.store.add_event("scanner", f"session watermark {iso(now)} ({why}): only confirmations closing after it are actionable", at=now)

    def _set_watermark_to_latest(self) -> None:
        bars = self.feed.closed_bars("M5", 1)
        if bars:
            self.store.set_meta("last_m5_close", iso(bars[-1].close_time))

    def _ensure_connected(self):
        st = self.feed.status()
        if not st.ok:
            # Record the unhealthy transition BEFORE reconnecting: even if connect() succeeds within this same scan,
            # the recovered scan must open a new session watermark rather than reuse the pre-outage one.
            self._unhealthy = True
            reconnectable = ("disconnected", "error", "not_configured", "symbol_missing", "symbol_selection_required")
            if st.state in reconnectable and self.feed.mode == "mt5" and time.monotonic() >= self._next_connect:
                st = self.feed.connect()
                if st.ok:
                    self._connect_backoff = RECONNECT_MIN_SECONDS
                else:  # bounded back-off between reconnect attempts
                    self._next_connect = time.monotonic() + self._connect_backoff
                    self._connect_backoff = min(self._connect_backoff * 2, RECONNECT_MAX_SECONDS)
        return st

    def scan_once(self) -> None:
        with self._feed_lock:
            self._scan()

    def _scan(self) -> None:
        st = self._ensure_connected()
        self.state["feed"] = st.to_dict()
        now = self.feed.now()
        self.state["last_scan"] = iso(now)
        if not st.ok:
            self.state["quote"] = None
            self._unhealthy = True
            return
        meta = self.feed.meta()
        if self.engine is None or self.engine.meta != meta:
            self.engine = self._make_engine(meta, now)
        quote = self.feed.quote()
        age = None if quote is None else (now - quote.time).total_seconds()
        future = age is not None and age < -FUTURE_TOLERANCE_SECONDS
        fresh = (quote is not None and quote.is_valid() and age is not None and not future
                 and age <= self.cfg.quote_max_age_seconds)
        note = None
        if quote is not None and not fresh:
            note = ("quote timestamp is in the future (clock skew or invalid data); nothing actionable" if future else
                    "invalid quote (non-positive or crossed Bid/Ask); nothing actionable" if not quote.is_valid() else
                    "stale quote: market closed, terminal disconnected or no ticks; nothing actionable")
            hours = abs(age) / 3600
            if hours >= 0.9 and abs(hours * 4 - round(hours * 4)) * 900 <= 60:  # within a minute of a quarter-hour multiple
                # a fact, not a correction: nothing is shifted automatically (see app/mt5_time.py)
                note += (f" (the quote is ~{round(hours * 4) / 4:g} h {'ahead' if age < 0 else 'behind'}: the MT5 server "
                         "time offset may be wrong or changed, e.g. DST; verify config/mt5_time.json)")
        self.state["quote"] = None if quote is None else {
            "time": iso(quote.time), "bid": quote.bid, "ask": quote.ask, "spread": round(quote.spread, 6),
            "age_seconds": round(age, 1), "fresh": fresh, "note": note}

        m5 = self.feed.closed_bars("M5", M5_WINDOW[self.active.kind])
        h1 = self.feed.closed_bars("H1", 6)
        issues = []
        if len(m5) < self.cfg.structure_lookback_bars + 5:
            issues.append("incomplete M5 history")
        if m5 and not contiguous(m5[-(self.cfg.structure_lookback_bars + 1):]):
            issues.append("gap in recent M5 bars (market break or missing history)")
        self.state["data_issues"] = issues
        self.state["last_closed"] = {"M5": iso(m5[-1].open_time) if m5 else None, "H1": iso(h1[-1].open_time) if h1 else None,
                                     "M5_close": iso(m5[-1].close_time) if m5 else None,
                                     "H1_close": iso(h1[-1].close_time) if h1 else None}
        if self.active.kind in ("fastsweep", "fvg") and m5:
            self.engine.update_readiness(m5, now)

        # 1) simulated outcomes keep running even while paused
        last_seen = parse_iso(self.store.get_meta("last_m5_close"))
        for sig in self.store.active_signals(meta.name):
            if getattr(self.feed, "supports_ticks", False):
                observations, gap = self._observed_quotes(sig, quote if fresh else None, now)
                changed = track_measured(sig, observations, now, self.cfg, gap)
            else:  # demo / no-tick feeds: bar + per-scan quote ESTIMATES, labelled as such
                new_bars = [b for b in m5 if not sig.last_checked or b.close_time > sig.last_checked]
                changed = track_live(sig, new_bars, quote, now, self.cfg, fresh)
                if not changed and new_bars:
                    sig.last_checked = new_bars[-1].close_time
                    changed = True
            if changed:
                self.store.update_signal(sig)
                if sig.outcome_status != "active":
                    self.store.add_event("outcome", f"{sig.id}: {sig.outcome_status.upper()} ({sig.outcome_note})", at=now)

        if self.active.is_fvg:
            self.engine.reconcile(now)  # broker reconciliation continues while paused or stale
            if fresh:  # far-edge maintenance of accepted baskets also while PAUSED, but only on trusted (fresh) context;
                self.engine.manage_baskets(m5, now)  # after stale periods it catches up over all bars since placement

        if self.paused:
            return
        if not fresh:
            # stale quotes (market closed, no ticks, terminal lagging): nothing is actionable and candidates wait;
            # the next healthy scan opens a NEW session watermark, so confirmations missed meanwhile stay non-actionable
            self._unhealthy = True
            return

        # 2) session eligibility watermark (startup, restart, recovery)
        if self.session_watermark is None or self._unhealthy:
            self._open_session(now, "startup" if self.session_watermark is None else "recovered after a disconnected/stale feed")
        self.engine.eligible_after = self.session_watermark
        watermark = self.session_watermark

        if self._skip_to_latest and m5:
            # Resumed while disconnected: do not process bars from the paused period
            last_seen = m5[-1].close_time
            self.store.set_meta("last_m5_close", iso(last_seen))
            self._skip_to_latest = False
            self.store.add_event("scanner", f"resume completed on recovery: skipping to {iso(last_seen)}", at=now)

        # 3) warm-up start point for a brand-new database (context only; eligibility comes from the watermark)
        if last_seen is None:
            if not h1:
                return
            last_seen = h1[-1].close_time - H1
            self.store.set_meta("last_m5_close", iso(last_seen))
            self.store.add_event("scanner", f"warm-up context from {iso(last_seen)}", at=now)

        def entry_fn(c, bar):
            return self.feed.quote(), self.feed.now()

        h1_by_close = {b.close_time: i for i, b in enumerate(h1)}
        new = [i for i, b in enumerate(m5) if b.close_time > last_seen]
        for i in new:
            bar = m5[i]
            if self.active.kind in ("fastsweep", "fvg"):  # each closed M5 bar once; M15 logic at M15 closes
                for sig in self.engine.process_bar(m5, i, entry_fn, now):
                    self.delivery.on_signal(sig)
                self.store.set_meta("last_m5_close", iso(bar.close_time))
                continue
            prev = m5[i - 1] if i > 0 else None
            for sig in self.engine.on_m5_bar(bar, prev, entry_fn):
                self.delivery.on_signal(sig)  # the Engine only creates signals that closed after the watermark
            j = h1_by_close.get(bar.close_time)
            if j:
                self.engine.evaluate_hour(h1[j - 1], h1[j], m5[: i + 1], now, warmup=h1[j].close_time <= watermark)
            self.store.set_meta("last_m5_close", iso(bar.close_time))
        if self.active.is_fastsweep:
            for sig in self.engine.retry_awaiting(entry_fn, now):
                self.delivery.on_signal(sig)
        self.engine.on_quote(quote)
        self.engine.check_deadlines(now)
        if self.engine.last_evaluation:
            self.store.set_meta("last_evaluation", json.dumps(self.engine.last_evaluation))

    def _observed_quotes(self, sig, quote, now: datetime):
        """Chronological observed ticks after the signal's last check (bounded chunks), plus the current fresh quote.
        Returns (observations, gap description or None). A failed read is a gap, never an estimate."""
        start = sig.last_checked or sig.quote_time
        observations, gap = [], None
        chunk = timedelta(hours=TICK_CHUNK_HOURS)
        for _ in range(TICK_MAX_CHUNKS):
            if start >= now:
                break
            end = min(now, start + chunk)
            try:
                ticks = self.feed.ticks_range(start, end)
            except Exception as exc:
                gap = f"{iso(start)}..{iso(end)}: {self.settings.redact(str(exc))}"
                observations.append(None)  # marker: stop here so last_checked is not advanced past the gap
                break
            observations.extend(q for q in ticks if start < q.time <= end and q.is_valid())
            start = end
        if None in observations:
            observations = observations[:observations.index(None)]
        elif quote is not None and quote.time <= now and (not observations or quote.time > observations[-1].time):
            observations.append(quote)
        observations.sort(key=lambda q: q.time)
        return observations, gap

    def _make_engine(self, meta, now: datetime):
        """Build the selected strategy's engine; pending setups of any other strategy/profile are retired, never
        evaluated with these rules. Existing history and signals are untouched."""
        if self.active.is_fvg:
            if self.fvg_store is None:
                raise RuntimeError("FVG selected but no FVG record store was provided")
            engine = FvgLiveEngine(self.active.fvg, meta, self.fvg_store, self.store, self.feed.mode,
                                   alert_fn=lambda b: self.delivery.on_fvg_basket(b),
                                   executor_fn=self.fvg_executor_fn, maintenance_fn=self.fvg_maintenance_fn,
                                   account_fn=self.fvg_account_fn)
            version = engine.version
        elif self.active.is_fastsweep:
            engine = FastSweepEngine(self.active.fastsweep, self.active.profile, meta, self.store, self.feed.mode)
            version = engine.version
        else:
            engine = Engine(self.cfg, meta, self.store, self.feed.mode)
            version = self.cfg.version
        retire_foreign_pending(self.store, meta.name, version, now)
        engine.eligible_after = self.session_watermark
        return engine

    def _fastsweep_state(self) -> dict:
        eng = self.engine
        r = getattr(eng, "readiness", None)
        pending = [c for c in self.store.pending_candidates(eng.symbol) if c.config_version == eng.version]
        if pending:
            c = pending[-1]
            side, edge = ("below A's low", "above B's high") if c.direction == "BUY" else ("above A's high", "below B's low")
            return {"state": "pending M5 confirmation", "readiness": r,
                    "detail": f"{c.direction}: M15 B swept {side} to {c.sweep_extreme} and closed back inside A "
                              f"({c.a_low}-{c.a_high}); waiting for an M5 close {edge} {c.level} until {iso(c.deadline)}",
                    "candidate": {"direction": c.direction, "a_high": c.a_high, "a_low": c.a_low,
                                  "sweep_extreme": c.sweep_extreme, "level": c.level, "deadline": iso(c.deadline),
                                  "b_close": iso(c.b_close)}}
        if r and not r.get("ready"):
            eta = None
            if r.get("last_m15_close"):
                eta = iso(parse_iso(r["last_m15_close"]) + timedelta(minutes=15 * (r["required"] - r["m15_run"])))
            return {"state": "trend warm-up", "readiness": r,
                    "detail": f"{r['m15_run']}/{r['required']} contiguous M15 candles since the last market break; "
                              f"EMA{self.active.fastsweep.ema_fast}/{self.active.fastsweep.ema_slow} trend becomes available "
                              f"around {eta} if no gap occurs. Setups before that are recorded as trend_warmup."}
        ev = eng.last_evaluation
        if ev is None:
            raw = self.store.get_meta("last_evaluation")
            ev = json.loads(raw) if raw else None
            if ev and ev.get("config_version") != eng.version:
                ev = None
        trend = (r or {}).get("trend") or "n/a"
        nxt = (r or {}).get("next_m15_close")
        if ev and ev.get("reason") == "no_sweep":
            return {"state": "no eligible sweep", "readiness": r, "last": ev,
                    "detail": f"Last M15 pair (A {ev['a_open']}, B closed {ev['b_close']}): no one-sided sweep. "
                              f"Trend {trend}. Next M15 close {nxt}."}
        if ev:
            c = self.store.get_candidate(f"{eng.symbol}|{ev['a_open']}|{ev['config_version']}")
            if c is not None:
                return {"state": c.status, "readiness": r, "last": ev,
                        "detail": f"Last M15 setup (A {ev['a_open']}): {c.status}" + (f" - {c.reason}" if c.reason else "") +
                                  f". Trend {trend}. Next M15 close {nxt}."}
        return {"state": "waiting for the next closed M15 pair", "readiness": r,
                "detail": f"Trend {trend}. Next M15 close {nxt}."}

    def _fvg_state(self) -> dict:
        eng = self.engine
        r = eng.readiness
        now = self.feed.now()
        from .fvg_live import basket_is_open
        open_b = [b for b in eng._family() if basket_is_open(b, now)]
        if open_b:
            b = open_b[0]
            ex = b.get("execution") or {}
            return {"state": f"basket {b['status']}", "readiness": r, "basket": b["id"],
                    "detail": f"{b['direction']} FVG {b['bottom']}-{b['top']}: limits "
                              f"{', '.join(str(l['entry']) for l in b['legs'])}, SL {b['sl']}; execution "
                              f"{ex.get('state')}" + (f" ({ex.get('reason')})" if ex.get("reason") else "")}
        active = eng.fstore.active_setups(eng.symbol, eng.version)
        if active:
            s = active[-1]
            what = (f"retested at {iso(s.retest_close)}; waiting for an M5 close beyond {s.level}" if s.status == "retested"
                    else "waiting for the first M5 retest")
            return {"state": f"FVG {s.status}", "readiness": r,
                    "detail": f"{s.direction} zone {s.bottom}-{s.top} (from {iso(s.c_close)}): {what}; expires {iso(s.expires)}"}
        if r and not r.get("ready"):
            return {"state": "trend warm-up", "readiness": r,
                    "detail": f"{r['m15_run']}/{r['required']} contiguous M15 candles since the last market break."}
        return {"state": "waiting for a qualified FVG", "readiness": r,
                "detail": f"Trend {(r or {}).get('trend') or 'n/a'}. Next M15 close {(r or {}).get('next_m15_close')}."}

    def strategy_state(self) -> dict:
        """Human-readable state of the ACTIVE strategy from actual records (no invented signals)."""
        feed = self.state.get("feed") or {}
        q = self.state.get("quote")
        if self.paused:
            return {"state": "paused", "detail": "Paused: no new candidates or alerts; open simulated signals are still tracked."}
        if not feed.get("ok"):
            label = {"symbol_selection_required": "symbol selection required", "symbol_missing": "symbol unavailable"}.get(
                feed.get("state"), "disconnected")
            return {"state": label, "detail": feed.get("message") or "Feed not connected."}
        if q is None or not q.get("fresh"):
            return {"state": "waiting for fresh quotes", "detail": (q or {}).get("note") or "No current quote (market closed?)."}
        if self.active.is_fastsweep and self.engine is not None and getattr(self.engine, "kind", "") == "fastsweep":
            return self._fastsweep_state()
        if self.active.is_fvg and self.engine is not None and getattr(self.engine, "kind", "") == "fvg":
            return self._fvg_state()
        try:
            symbol = self.feed.meta().name
        except Exception:
            symbol = None
        pending = self.store.pending_candidates(symbol) if symbol else []
        if pending:
            c = pending[-1]
            return {"state": "pending structure confirmation",
                    "detail": f"{c.direction}: A {c.a_low}-{c.a_high}, sweep {c.sweep_extreme}, frozen level {c.level}; "
                              f"waiting for an M5 close beyond the level until {iso(c.deadline)}",
                    "candidate": {"direction": c.direction, "a_high": c.a_high, "a_low": c.a_low,
                                  "sweep_extreme": c.sweep_extreme, "level": c.level, "deadline": iso(c.deadline),
                                  "b_close": iso(c.b_close)}}
        raw = self.store.get_meta("last_evaluation")
        ev = json.loads(raw) if raw else None
        if ev and ev.get("reason") == "no_sweep":
            return {"state": "no eligible sweep", "detail": f"Last H1 pair (A {ev['a_open']}, B closed {ev['b_close']}): "
                                                            "B did not sweep A's high or low by the minimum ticks.", "last": ev}
        if ev:
            c = self.store.get_candidate(f"{symbol}|{ev['a_open']}|{ev['config_version']}") if symbol else None
            if c is not None:
                return {"state": c.status, "detail": f"Last setup (A {ev['a_open']}): {c.status}" + (f" - {c.reason}" if c.reason else ""),
                        "last": ev}
        return {"state": "waiting for the next closed H1 range", "detail": "No H1 pair evaluated in this session yet."}

    # ------------------------------------------------------------------ helpers for the API
    def chart_bars(self, start: datetime, end: datetime) -> list:
        with self._feed_lock:
            if not self.feed.status().ok and self.feed.mode == "mt5":
                return []
            return self.feed.bars_range("M5", start, end)
