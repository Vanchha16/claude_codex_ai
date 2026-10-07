"""Live FVG engine: persistent setups and three-leg baskets, driven by the scanner (same rules as app/fvg_replay.py).

Records live in their OWN typed tables (fvg_setups, fvg_baskets in fvg-<symbol>.sqlite), never in the simulated-signal
tables, so a pending broker order is never pushed through the simulated-outcome tracker.

Flow per newly CLOSED M5 bar (each bar once, in time order):
1. open baskets: a close beyond the zone's far edge cancels THIS basket's remaining pending legs (owned orders only);
2. active setups advance (first retest, then a different M5 close beyond the frozen level within 3 bars);
3. at each M15 close a new A/B/C gap is detected and qualified.
On confirmation (STRICTLY after the session watermark, else consumed as rejected): capacity from persisted baskets (one
open basket per symbol, >= 30 min since the last accepted basket, <= 4 accepted baskets per Bangkok date), geometry,
a durable basket record, the Telegram alert (existing opt-in, dedup by basket id), and - only when automatic execution
is armed for this exact source/symbol/account/version with a configured risk - automatic submission of the three
limits. Without arming the basket is "alert_only" and nothing is sent to the broker.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from .fastsweep import BUY, M15, bangkok_date, ema_last
from .fvg import (FvgConfig, FvgSetup, Gap, advance_setup, atr_last, basket_levels, contiguous_run, detect_gap, new_setup,
                  placement_violation, qualify, stop_within_spread)
from .fvg_execution import OtherAccountError, UnverifiableAccountError, plan_id_for
from .models import M5, Bar, SymbolMeta, aggregate, iso, parse_iso

OPEN_EXEC_STATES = {"submitting", "submitted", "partial", "needs_reconciliation"}
CANCEL_RETRY_SECONDS = 30  # bounded cadence for re-verifying/re-removing an unresolved owned pending remainder


def _dump_setup(s: FvgSetup) -> dict:
    d = asdict(s)
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = iso(v)
    return d


def _load_setup(d: dict) -> FvgSetup:
    d = dict(d)
    for k in ("a_open", "c_close", "expires", "next_open", "retest_close", "confirm_close"):
        if d.get(k):
            d[k] = parse_iso(d[k])
    return FvgSetup(**d)


class FvgStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._lock = threading.RLock()
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS fvg_setups (key TEXT PRIMARY KEY, symbol TEXT, version TEXT, status TEXT,
                c_close TEXT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS fvg_baskets (id TEXT PRIMARY KEY, symbol TEXT, version TEXT, status TEXT,
                placed_at TEXT, payload TEXT NOT NULL);
        """)

    def add_setup(self, s: FvgSetup, symbol: str, version: str) -> bool:
        with self._lock:
            cur = self.db.execute("INSERT OR IGNORE INTO fvg_setups VALUES (?,?,?,?,?,?)",
                                  (s.key, symbol, version, s.status, iso(s.c_close), json.dumps(_dump_setup(s))))
        return cur.rowcount == 1

    def update_setup(self, s: FvgSetup) -> None:
        with self._lock:
            self.db.execute("UPDATE fvg_setups SET status=?, payload=? WHERE key=?", (s.status, json.dumps(_dump_setup(s)), s.key))

    def get_setup(self, key: str) -> Optional[FvgSetup]:
        with self._lock:
            row = self.db.execute("SELECT payload FROM fvg_setups WHERE key=?", (key,)).fetchone()
        return _load_setup(json.loads(row[0])) if row else None

    def active_setups(self, symbol: str, version: str) -> list[FvgSetup]:
        with self._lock:
            rows = self.db.execute("SELECT payload FROM fvg_setups WHERE symbol=? AND version=? AND status IN ('pending','retested') "
                                   "ORDER BY c_close", (symbol, version)).fetchall()
        return [_load_setup(json.loads(r[0])) for r in rows]

    def list_setups(self, limit: int = 200) -> list[FvgSetup]:
        with self._lock:
            rows = self.db.execute("SELECT payload FROM fvg_setups ORDER BY c_close DESC LIMIT ?", (limit,)).fetchall()
        return [_load_setup(json.loads(r[0])) for r in rows]

    def add_basket(self, b: dict) -> bool:
        with self._lock:
            cur = self.db.execute("INSERT OR IGNORE INTO fvg_baskets VALUES (?,?,?,?,?,?)",
                                  (b["id"], b["symbol"], b["version"], b["status"], b["placed_at"], json.dumps(b)))
        return cur.rowcount == 1

    def update_basket(self, b: dict) -> None:
        with self._lock:
            self.db.execute("UPDATE fvg_baskets SET status=?, payload=? WHERE id=?", (b["status"], json.dumps(b), b["id"]))

    def baskets(self, symbol: Optional[str] = None, limit: int = 500) -> list[dict]:
        q, args = "SELECT payload FROM fvg_baskets", []
        if symbol:
            q += " WHERE symbol=?"; args.append(symbol)
        q += " ORDER BY placed_at DESC LIMIT ?"; args.append(limit)
        with self._lock:
            return [json.loads(r[0]) for r in self.db.execute(q, args).fetchall()]

    def close(self) -> None:
        with self._lock:
            self.db.close()


EXEC_STATUS = {"submitted": "orders_pending", "partial": "partial", "rejected": "rejected",
               "needs_reconciliation": "needs_reconciliation", "disabled": "alert_only",
               "preflight_rejected": "preflight_rejected", "closed": "closed"}


def basket_is_open(b: dict, now: datetime) -> bool:
    if b.get("other_account"):  # submitted on another MT5 account: not manageable here, not capacity on this account
        return False
    ex = b.get("execution") or {}
    if ex.get("state") in OPEN_EXEC_STATES:
        return True
    if b["status"] == "planned":  # accepted but its execution outcome was never recorded (e.g. process exit): unresolved
        return True
    if b["status"] == "alert_only":
        return now < parse_iso(b["pending_expires"])
    return False


class FvgLiveEngine:
    kind = "fvg"

    def __init__(self, cfg: FvgConfig, meta: SymbolMeta, fstore: FvgStore, events, mode: str, *,
                 alert_fn: Callable[[dict], None] = lambda b: None,
                 executor_fn: Callable[[], tuple[object, str]] = lambda: (None, "automatic execution OFF"),
                 maintenance_fn: Callable[[], object] = lambda: None,
                 account_fn: Callable[[], Optional[str]] = lambda: None,
                 clock: Optional[Callable[[], datetime]] = None):
        self.cfg, self.meta, self.fstore, self.events, self.mode = cfg.validate(), meta, fstore, events, mode
        self.symbol, self.version = meta.name, cfg.version
        self.alert_fn, self.executor_fn, self.maintenance_fn = alert_fn, executor_fn, maintenance_fn
        self.account_fn = account_fn  # canonical server+login identity of the connected account (None = unavailable)
        self.clock = clock  # current UTC clock for decisions when no live entry callback supplies one
        self.eligible_after: Optional[datetime] = None
        self.last_evaluation: Optional[dict] = None
        self.readiness: Optional[dict] = None

    # ------------------------------------------------------------------ helpers
    def _event(self, kind: str, msg: str, at: datetime, level: str = "info") -> None:
        if self.events is not None:
            self.events.add_event(kind, f"[FVG] {msg}", level, at=at)

    def _family(self) -> list[dict]:
        return [b for b in self.fstore.baskets(self.symbol) if b.get("accepted")]

    # ------------------------------------------------------------------ per closed M5 bar
    def process_bar(self, m5: list[Bar], i: int, entry_fn, now: datetime) -> list:
        bar = m5[i]
        self._entry_fn = entry_fn  # current quote source for the rule-6 spread check at confirmation
        self._manage_bar(bar, now)
        for s in self.fstore.active_setups(self.symbol, self.version):
            before = s.status
            st = advance_setup(s, bar, self.cfg)
            if st == before and st == "pending":
                if s.next_open == bar.close_time:
                    self.fstore.update_setup(s)
                continue
            self.fstore.update_setup(s)
            if st == "retested" and before == "pending":
                self._event("fvg", f"{s.direction} zone {s.bottom}-{s.top}: retested at {iso(s.retest_close)}, "
                                   f"level {s.level}", bar.close_time)
            elif st == "confirmed":
                self._on_confirmed(s, now)
            elif st in ("invalidated", "expired"):
                self._event(st, f"{s.direction} zone {s.bottom}-{s.top}: {s.reason}", bar.close_time)
        if bar.close_time.minute % 15 == 0 and bar.close_time.second == 0:
            self._detect(m5[: i + 1], bar, now)
        return []

    def _detect(self, history: list[Bar], bar: Bar, now: datetime) -> None:
        m15 = aggregate(history, M15)
        if len(m15) < 3 or m15[-1].close_time != bar.close_time:
            return
        gap = detect_gap(m15[-3], m15[-2], m15[-1], self.meta.tick_size)
        self.last_evaluation = {"a_open": iso(m15[-3].open_time), "c_close": iso(bar.close_time), "evaluated_at": iso(now),
                                "gap": None if gap is None else {"direction": gap.direction, "bottom": gap.bottom, "top": gap.top},
                                "config_version": self.version}
        if gap is None:
            return
        s = new_setup(gap, self.cfg, self.symbol, self.version)
        why = qualify(gap, m15, self.cfg, self.meta.tick_size)
        if why:
            s.status, s.reason = "rejected", why
        s.meta["warmup"] = self.eligible_after is not None and gap.third.close_time <= self.eligible_after
        self.last_evaluation["reason"] = why
        if self.fstore.add_setup(s, self.symbol, self.version):
            self._event("candidate", f"{gap.direction} FVG {gap.bottom}-{gap.top} (A {iso(gap.first.open_time)}): "
                                     f"{s.status}" + (f" ({why})" if why else ""), now)

    def _reject(self, s: FvgSetup, reason: str, now: datetime) -> None:
        s.status, s.reason = "rejected", reason
        self.fstore.update_setup(s)
        self._event("rejected", f"{s.direction} zone {s.bottom}-{s.top}: {reason}", now)

    def _on_confirmed(self, s: FvgSetup, now: datetime) -> None:
        cfg = self.cfg
        if self.eligible_after is not None and not s.confirm_close > self.eligible_after:
            return self._reject(s, "confirmation_before_session_watermark", now)  # history: never alerted or sent
        # the CURRENT decision time (not the scan start): the live entry callback returns (quote, current clock time);
        # without one, an injected clock; the quote's own timestamp never stands in for the wall clock
        entry_fn = getattr(self, "_entry_fn", None)
        quote = None
        if entry_fn is not None:
            quote, current = entry_fn(None, None)
            now = max(now, current) if current is not None else now
        elif self.clock is not None:
            now = max(now, self.clock())
        # decision-time freshness: a delayed scan must never act on an old confirmation (consumed, not replayed)
        age = (now - s.confirm_close).total_seconds()
        if now >= s.expires:
            return self._reject(s, "setup_expired_at_decision", now)
        if age < 0:
            return self._reject(s, "confirmation_in_future", now)
        if age > cfg.max_confirmation_age_seconds:
            return self._reject(s, f"confirmation_too_old ({age:.0f}s > {cfg.max_confirmation_age_seconds}s)", now)
        current = self.account_fn()
        # capacity within the connected account's context (alert-only plans have no account); other-account plans stay
        # tracked but do not block this account
        family = [b for b in self._family() if current is None or b.get("account_id") in (None, current)]
        if any(basket_is_open(b, now) for b in family):
            return self._reject(s, "basket_already_open", now)
        last = max((parse_iso(b["placed_at"]) for b in family), default=None)
        if last is not None and now - last < timedelta(minutes=cfg.cooldown_minutes):
            return self._reject(s, "cooldown", now)
        if sum(1 for b in family if bangkok_date(parse_iso(b["placed_at"])) == bangkok_date(now)) >= cfg.max_baskets_per_day:
            return self._reject(s, "daily_cap", now)
        gap = Gap(s.direction, s.bottom, s.top, None, None)
        try:
            sl, legs = basket_levels(gap, self.meta, cfg)
        except ValueError as exc:
            return self._reject(s, f"levels_invalid: {exc}", now)
        if entry_fn is not None:  # rule 6 on the live quote, BEFORE a basket exists (no alert, no capacity used)
            if quote is None:
                return self._reject(s, "no_quote_for_eligibility_check", now)
            entries = [(l.number, l.entry) for l in legs]
            why = stop_within_spread(sl, entries, quote.ask - quote.bid, cfg, self.meta.tick_size)
            if why:
                return self._reject(s, f"stop_within_spread: {why}", now)
            why = placement_violation(s.direction, entries, quote.bid, quote.ask, self.meta.tick_size)
            if why:
                return self._reject(s, f"limit_on_wrong_side_of_market: {why}", now)
        pid = plan_id_for(s.key)
        expires = now + timedelta(minutes=cfg.pending_expiry_minutes)
        basket = {"id": f"FVG-{pid}", "plan_id": pid, "setup_key": s.key, "symbol": self.symbol, "version": self.version,
                  "mode": self.mode, "direction": s.direction, "bottom": s.bottom, "top": s.top, "sl": sl,
                  "retest_close": iso(s.retest_close), "level": s.level, "confirm_close": iso(s.confirm_close),
                  "placed_at": iso(now), "pending_expires": iso(expires), "accepted": True, "status": "planned",
                  "legs": [{"n": l.number, "pct": l.percent, "entry": l.entry, "tp": l.tp, "sl": sl,
                            "rr": round(abs(l.tp - l.entry) / abs(l.entry - sl), 2)} for l in legs],
                  "execution": None, "meta": {"digits": self.meta.digits, "tick_size": self.meta.tick_size},
                  "account_id": current}
        if not self.fstore.add_basket(basket):
            return self._reject(s, "duplicate_basket", now)
        s.meta["basket"] = basket["id"]
        self.fstore.update_setup(s)
        self._event("signal", f"{basket['id']}: {s.direction} 3 limits {[l['entry'] for l in basket['legs']]} SL {sl}", now)
        try:
            self.alert_fn(basket)  # existing Telegram opt-in + outbox (dedup by basket id); never the submission trigger
        except Exception as exc:  # an alert problem must not stop the basket lifecycle
            self._event("error", f"{basket['id']}: alert failed: {type(exc).__name__}", now, "error")
        try:
            executor, why = self.executor_fn()
        except Exception as exc:  # no executor = nothing could have been sent
            executor, why = None, f"execution unavailable: {type(exc).__name__}"
        if executor is None:
            basket["status"], basket["execution"] = "alert_only", {"state": "not_submitted", "reason": why}
        else:
            try:
                result = executor.submit(pid, gap, self.meta, now, expires,  # automatic: no per-trade confirmation
                                         stop_spread_margin_ticks=cfg.stop_spread_margin_ticks,
                                         eligibility={"confirm_close": s.confirm_close, "setup_expires": s.expires,
                                                      "max_age_seconds": cfg.max_confirmation_age_seconds})
            except Exception as exc:
                result = self._classify_submit_error(executor, pid, exc)
            basket["execution"] = result
            basket["status"] = EXEC_STATUS.get(result.get("state"), result.get("state", "unknown"))
            self._event("order", f"{basket['id']}: automatic execution {result.get('state')}"
                                 + (f" ({result.get('reason')})" if result.get("reason") else ""), now)
        self.fstore.update_basket(basket)

    @staticmethod
    def _classify_submit_error(executor, pid: str, exc: Exception) -> dict:
        """A genuine preflight failure has NO journal row (the row is written before any send). If the row exists,
        sending may have begun -> reconciliation; if the journal cannot even be read, the outcome is uncertain."""
        error = f"{type(exc).__name__}: {exc}"
        journal = getattr(executor, "journal", None)
        try:
            payload = journal.get(pid) if journal is not None else None
        except Exception as read_exc:
            return {"state": "needs_reconciliation", "uncertain": True,
                    "reason": f"execution error ({error}) and the journal is unreadable ({type(read_exc).__name__}); "
                              "a send may have begun - recovered from the journal when storage is available"}
        if payload is None:
            return {"state": "preflight_rejected", "reason": str(exc)}
        payload["state"], payload["error"] = "needs_reconciliation", error
        try:
            journal.save(pid, payload)
        except Exception:
            pass  # the basket row below still carries the adopted payload
        return payload

    def manage_baskets(self, m5: list[Bar], now: datetime) -> None:
        """Every scan, also while PAUSED or catching up after stale quotes: apply the far-edge rule to already accepted
        baskets over all closed bars after placement. Idempotent (each basket is invalidated once); never creates
        setups, alerts or submissions."""
        for b in self._family():  # durably invalidated baskets keep being resolved without a new breach
            self._retry_cancel(b, now)
        family = [b for b in self._family() if not b.get("zone_invalidated_at") and not b.get("other_account")
                  and (basket_is_open(b, now) or b["status"] in ("alert_only", "planned"))]
        if not family:
            return
        oldest = min(parse_iso(b["placed_at"]) for b in family)
        for bar in m5:
            if bar.close_time > oldest:
                self._manage_bar(bar, now, family)

    def _manage_bar(self, bar: Bar, now: datetime, family: Optional[list] = None) -> None:
        for b in (family if family is not None else self._family()):
            if not basket_is_open(b, bar.close_time):
                if b["status"] == "alert_only" and bar.close_time >= parse_iso(b["pending_expires"]):
                    b["status"] = "expired_unsubmitted"
                    self.fstore.update_basket(b)
                continue
            if b.get("zone_invalidated_at") or bar.close_time <= parse_iso(b["placed_at"]):
                continue  # invalidation already detected (durable), or a close from before the plan existed
            if bar.tf != M5 or not bar.is_valid():
                continue  # only valid closed M5 bars can invalidate a zone
            far = bar.close < b["bottom"] if b["direction"] == BUY else bar.close > b["top"]
            if not far:
                continue
            # 1) the invalidation is recorded durably, independent of whether the broker removal succeeds; a later
            #    return inside the zone never erases it
            b["zone_invalidated_at"] = iso(bar.close_time)
            if b["status"] == "alert_only":
                b["status"], b["cancel_complete"] = "zone_invalidated", True
                self.fstore.update_basket(b)
                continue
            b["cancel_complete"] = False
            self.fstore.update_basket(b)
            # 2) removal of the owned remainders, retried until broker evidence proves completion
            self._retry_cancel(b, now, force=True)

    def _retry_cancel(self, b: dict, now: datetime, force: bool = False) -> None:
        """Resolve the cancellation of an invalidated basket's pending remainders: bounded cadence, each attempt verifies
        the current broker state first (never a blind duplicate), on the ORIGINAL account only."""
        if not b.get("zone_invalidated_at") or b.get("cancel_complete") or b.get("other_account"):
            return
        if not force and b.get("cancel_retry_at") and now < parse_iso(b["cancel_retry_at"]):
            return
        ex = self.maintenance_fn()
        if ex is None:
            return  # no broker access now: retried on a later scan
        b["cancel_retry_at"] = iso(now + timedelta(seconds=CANCEL_RETRY_SECONDS))
        try:
            payload = ex.cancel_remaining(b["plan_id"], "zone invalidated", now)
        except OtherAccountError as exc:
            self._mark_other_account(b, now, exc)  # resumes when the original account is connected again
            return
        except Exception as exc:
            self.fstore.update_basket(b)
            self._error_once(b, f"cancel failed (will retry): {exc}", now)
            return
        if payload:
            b["execution"] = payload
            state = payload.get("cancel_state")
            b["cancel_complete"] = state == "complete"
            if state != "complete":
                self._error_once(b, f"pending remainder cancellation not confirmed ({state}); retrying", now)
            else:
                b.pop("last_error", None)
        self.fstore.update_basket(b)

    def _mark_other_account(self, b: dict, now: datetime, exc: Optional[Exception] = None) -> None:
        legacy = isinstance(exc, UnverifiableAccountError)
        reason = ("legacy journal without server identity: ownership unverifiable; needs manual review" if legacy else
                  "submitted on another MT5 server/login; not managed or counted here until that account is connected again")
        if b.get("other_account") != reason:
            b["other_account"] = reason
            self.fstore.update_basket(b)
            self._event("warning", f"{b['id']}: {reason} (its orders keep their broker SL/TP/expiry)", now, "warning")

    def _error_once(self, b: dict, msg: str, now: datetime) -> None:
        if b.get("last_error") != msg:  # the same failure is logged once, not every 5-second scan
            b["last_error"] = msg
            self.fstore.update_basket(b)
            self._event("error", f"{b['id']}: {msg}", now, "error")

    # ------------------------------------------------------------------ every scan
    def reconcile(self, now: datetime) -> None:
        ex = self.maintenance_fn()
        if ex is None:
            return
        for b in self._family():
            if b["status"] == "planned" and b.get("execution") is None:
                self._recover_planned(b, ex, now)
            if (b.get("execution") or {}).get("state") not in OPEN_EXEC_STATES:
                continue
            try:
                payload = ex.reconcile(b["plan_id"], now)
            except OtherAccountError as exc:
                self._mark_other_account(b, now, exc)  # logged once, not every scan
                continue
            except Exception as exc:
                self._error_once(b, f"reconcile failed: {exc}", now)
                continue
            if payload is None and (b.get("execution") or {}).get("uncertain"):
                # the journal is readable again and has NO row: it is written before any send, so nothing was sent
                b["status"] = "interrupted_unsubmitted"
                b["execution"] = {"state": "not_submitted", "reason": "no execution journal row exists: nothing was sent"}
                self.fstore.update_basket(b)
                self._event("order", f"{b['id']}: uncertain submission resolved - nothing was sent", now)
                continue
            b.pop("last_error", None)
            if payload and b.get("other_account"):
                b.pop("other_account")  # its account is connected again
                self._event("order", f"{b['id']}: original MT5 account connected again; managed and counted again", now)
            if payload:
                b["execution"] = payload
                if payload.get("state") == "closed":
                    b["status"] = "closed"
                self.fstore.update_basket(b)
            self._retry_cancel(b, now)  # through pause/stale/reconnect: broker access is enough, no new bar needed

    def _recover_planned(self, b: dict, ex, now: datetime) -> None:
        """A basket accepted before a process exit: adopt the execution journal (committed before any send), so its owned
        broker orders are reconciled; with no journal row nothing was ever sent. Never submits again either way."""
        journal = getattr(ex, "journal", None)
        payload = journal.get(b["plan_id"]) if journal is not None else None
        if payload is None:
            b["status"] = "interrupted_unsubmitted"
            b["execution"] = {"state": "not_submitted", "reason": "process stopped before any order was sent"}
        else:
            b["execution"] = payload
            b["status"] = EXEC_STATUS.get(payload.get("state"), payload.get("state", "unknown"))
            if payload.get("state") == "submitting":  # stopped mid-batch: per-leg states say what reached the broker
                payload["state"] = "needs_reconciliation"
                journal.save(b["plan_id"], payload)
                b["status"] = "needs_reconciliation"
        self.fstore.update_basket(b)
        self._event("order", f"{b['id']}: recovered after restart -> {b['status']} (no resubmission)", now)

    def on_quote(self, quote) -> None:
        return None  # limits rest at the broker; setups use closed bars only

    def check_deadlines(self, now: datetime) -> None:
        for s in self.fstore.active_setups(self.symbol, self.version):
            if now >= s.expires + timedelta(minutes=6):
                s.status, s.reason = "expired", "setup_lifetime_elapsed"
                self.fstore.update_setup(s)

    def cancel_pending(self, now: datetime, reason: str) -> None:
        for s in self.fstore.active_setups(self.symbol, self.version):
            s.status, s.reason = "expired", reason
            self.fstore.update_setup(s)

    def update_readiness(self, m5: list[Bar], now: datetime) -> dict:
        run = contiguous_run(aggregate(m5, M15))
        closes = [b.close for b in run]
        fast, slow = ema_last(closes, self.cfg.ema_fast), ema_last(closes, self.cfg.ema_slow)
        atr = atr_last(run, self.cfg.atr_period)
        trend = None
        if len(run) >= self.cfg.trend_min_candles and fast is not None and slow is not None:
            trend = "flat" if abs(fast - slow) <= 1e-9 else ("up (BUY zones allowed)" if fast > slow else "down (SELL zones allowed)")
        last = m5[-1].close_time if m5 else None
        nxt = None if last is None else last + timedelta(minutes=(15 - last.minute % 15) or 15) - timedelta(seconds=last.second)
        self.readiness = {"m15_run": len(run), "required": self.cfg.trend_min_candles,
                          "ready": len(run) >= self.cfg.trend_min_candles, "trend": trend,
                          "atr14": None if atr is None else round(atr, 3),
                          "last_m15_close": iso(run[-1].close_time) if run else None,
                          "next_m15_close": iso(nxt) if nxt else None, "checked_at": iso(now)}
        return self.readiness
