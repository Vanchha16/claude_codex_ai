"""Candidate lifecycle shared by the live scanner and historical replay.

The engine is fed CLOSED bars in time order plus (live only) quotes. It never looks at a bar before
that bar's close time, never relabels a frozen setup, and consumes each candidate at most once.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional, Protocol

from .config import StrategyConfig
from .models import M5, Bar, Quote, SymbolMeta, iso
from .strategy import (BUY, Setup, build_entry, confirm_step, evaluate_range, explain,
                       invalidation_by_quote, select_structure)

PENDING, CONFIRMED, INVALIDATED, EXPIRED, REJECTED = "pending", "confirmed", "invalidated", "expired", "rejected"


@dataclass
class Candidate:
    key: str
    symbol: str
    config_version: str
    mode: str
    direction: Optional[str]
    a_open: datetime
    b_open: datetime
    b_close: datetime
    a_high: float
    a_low: float
    b_high: float
    b_low: float
    status: str
    reason: Optional[str] = None
    level: Optional[float] = None
    pivot_time: Optional[datetime] = None
    pivot_available: Optional[datetime] = None
    deadline: Optional[datetime] = None
    last_bar_close: Optional[datetime] = None
    confirm_close: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    warmup: bool = False  # evaluated from history before the live-start watermark

    @property
    def sweep_extreme(self) -> float:
        return self.b_low if self.direction == BUY else self.b_high

    def setup(self) -> Setup:
        assert self.direction and self.level is not None
        return Setup(self.direction, self.a_high, self.a_low, self.sweep_extreme, self.level, self.b_close)


@dataclass
class Signal:
    id: str
    candidate_key: str
    symbol: str
    mode: str
    direction: str
    entry: float
    sl: float
    tp: float
    reward_risk: float
    spread: float
    bid: float
    ask: float
    quote_time: datetime
    confirm_close: datetime
    created_at: datetime
    valid_until: datetime
    config_version: str
    explanation: str
    meta: dict = field(default_factory=dict)
    outcome_status: str = "active"  # active | tp | sl | expired | ambiguous
    outcome_time: Optional[datetime] = None
    outcome_price: Optional[float] = None
    outcome_r: Optional[float] = None
    outcome_note: Optional[str] = None
    last_checked: Optional[datetime] = None

    @property
    def risk(self) -> float:
        return abs(self.entry - self.sl)


class Store(Protocol):
    def get_candidate(self, key: str) -> Optional[Candidate]: ...
    def add_candidate(self, c: Candidate) -> None: ...
    def update_candidate(self, c: Candidate) -> None: ...
    def pending_candidates(self, symbol: str) -> list[Candidate]: ...
    def add_signal(self, s: Signal) -> bool: ...
    def update_signal(self, s: Signal) -> None: ...
    def active_signals(self, symbol: str) -> list[Signal]: ...
    def add_event(self, kind: str, message: str, level: str = "info", at: datetime | None = None) -> None: ...


# entry_fn(candidate, confirmation_bar) -> (quote or None, decision time "now")
EntryFn = Callable[[Candidate, Bar], tuple[Optional[Quote], datetime]]


def candidate_key(symbol: str, a_open: datetime, version: str) -> str:
    return f"{symbol}|{iso(a_open)}|{version}"


def signal_id(c: Candidate, mode: str) -> str:
    digest = hashlib.sha256(c.key.encode()).hexdigest()[:6].upper()
    return f"SIG-{c.b_close.strftime('%Y%m%d-%H%M')}-{c.direction}-{digest}"


class Engine:
    def __init__(self, cfg: StrategyConfig, meta: SymbolMeta, store: Store, mode: str):
        self.cfg, self.meta, self.store, self.mode = cfg, meta, store, mode
        self.symbol = meta.name
        # Live session eligibility watermark (set by the scanner on startup, restart, resume and feed recovery).
        # A confirmation is actionable only if its M5 bar closed STRICTLY AFTER this instant; anything at or before
        # it closed while this session was not yet watching and is consumed without a signal. None = replay/tests.
        self.eligible_after: Optional[datetime] = None
        self.last_evaluation: Optional[dict] = None  # most recent A/B evaluation (for the dashboard strategy state)

    # -- H1: evaluate A/B once at B close
    def evaluate_hour(self, a: Bar, b: Bar, m5_history: list[Bar], now: datetime, warmup: bool = False) -> Optional[Candidate]:
        check = evaluate_range(a, b, self.meta.tick_size, self.cfg)
        self.last_evaluation = {"a_open": iso(a.open_time), "b_close": iso(b.close_time), "evaluated_at": iso(now),
                                "direction": check.direction, "reason": check.reason, "config_version": self.cfg.version}
        if check.reason in ("no_sweep", "not_h1"):
            return None
        key = candidate_key(self.symbol, a.open_time, self.cfg.version)
        if self.store.get_candidate(key) is not None:
            return None  # persistent deduplication across scans and restarts
        c = Candidate(key=key, symbol=self.symbol, config_version=self.cfg.version, mode=self.mode,
                      direction=check.direction, a_open=a.open_time, b_open=b.open_time, b_close=b.close_time,
                      a_high=a.high, a_low=a.low, b_high=b.high, b_low=b.low,
                      status=REJECTED if check.reason else PENDING, reason=check.reason,
                      created_at=now, updated_at=now, warmup=warmup)
        if check.direction:
            s = select_structure(check.direction, a, b, m5_history, self.cfg)
            if s.pivot is None:
                c.status, c.reason = REJECTED, s.reason
            else:
                c.level, c.pivot_time, c.pivot_available = s.pivot.level, s.pivot.bar_open, s.pivot.available_at
                c.deadline = c.setup().deadline(self.cfg)
                c.last_bar_close = b.close_time
        self.store.add_candidate(c)
        label = c.direction or "range"
        self.store.add_event("candidate", f"{label} candidate A={iso(a.open_time)}: {c.status}" + (f" ({c.reason})" if c.reason else ""), at=now)
        return c

    # -- M5: advance pending candidates with one newly closed bar
    def on_m5_bar(self, bar: Bar, prev: Optional[Bar], entry_fn: EntryFn) -> list[Signal]:
        created: list[Signal] = []
        for c in self.store.pending_candidates(self.symbol):
            if bar.open_time < c.b_close or (c.last_bar_close and bar.close_time <= c.last_bar_close):
                continue
            step = confirm_step(c.setup(), prev, bar, self.cfg)
            c.last_bar_close = bar.close_time
            if step.status == PENDING:
                self.store.update_candidate(c)
                continue
            if step.status == CONFIRMED:
                c.confirm_close = bar.close_time
                if self.eligible_after is not None and c.confirm_close <= self.eligible_after:
                    c.status, c.reason, c.updated_at = REJECTED, "confirmation_before_session_watermark", bar.close_time
                    self.store.add_event(REJECTED, f"{c.direction} {iso(c.a_open)}: confirmation closed {iso(c.confirm_close)}, "
                                         f"not after the session watermark {iso(self.eligible_after)}; not actionable", at=bar.close_time)
                    self.store.update_candidate(c)
                    continue
                quote, now = entry_fn(c, bar)
                sig = self._confirm(c, quote, now)
                if sig:
                    created.append(sig)
            else:
                c.status, c.reason, c.updated_at = step.status, step.reason, bar.close_time
                self.store.add_event(c.status, f"{c.direction} {iso(c.a_open)}: {c.reason}", at=bar.close_time)
            self.store.update_candidate(c)
        return created

    def _confirm(self, c: Candidate, quote: Optional[Quote], now: datetime) -> Optional[Signal]:
        c.updated_at = now
        if self.store.active_signals(self.symbol):
            c.status, c.reason = REJECTED, "overlapping_active_signal"
            self.store.add_event("rejected", f"{c.direction} {iso(c.a_open)}: confirmation ignored, a simulated signal is still active", at=now)
            return None
        check = build_entry(c.setup(), c.confirm_close, quote, now, self.meta, self.cfg)
        if check.levels is None:
            c.status, c.reason = REJECTED, check.reason
            self.store.add_event("rejected", f"{c.direction} {iso(c.a_open)}: entry check failed ({check.reason})", at=now)
            return None
        lv = check.levels
        sig = Signal(id=signal_id(c, self.mode), candidate_key=c.key, symbol=self.symbol, mode=self.mode,
                     direction=c.direction, entry=lv.entry, sl=lv.sl, tp=lv.tp, reward_risk=round(lv.reward_risk, 3),
                     spread=round(lv.spread, 6), bid=lv.quote.bid, ask=lv.quote.ask, quote_time=lv.quote.time,
                     confirm_close=c.confirm_close, created_at=now,
                     valid_until=c.confirm_close + timedelta(seconds=self.cfg.alert_valid_seconds),
                     config_version=self.cfg.version,
                     explanation=explain(c.direction, {"high": c.a_high, "low": c.a_low}, c.level, c.sweep_extreme),
                     meta={"symbol": self.meta.to_dict(), "a_open": iso(c.a_open), "b_open": iso(c.b_open),
                           "level": c.level, "pivot_time": iso(c.pivot_time)},
                     last_checked=now)
        if not self.store.add_signal(sig):
            c.status, c.reason = REJECTED, "duplicate_signal"
            return None
        c.status, c.reason = CONFIRMED, None
        self.store.add_event("signal", f"{sig.id}: {sig.direction} entry {sig.entry} SL {sig.sl} TP {sig.tp} R:R {sig.reward_risk}", at=now)
        return sig

    # -- live checks performed on every scan
    def on_quote(self, quote: Quote) -> None:
        for c in self.store.pending_candidates(self.symbol):
            if quote.time < c.b_close:
                continue
            reason = invalidation_by_quote(c.setup(), quote)
            if reason:
                c.status, c.reason, c.updated_at = INVALIDATED, f"{reason}_live_tick", quote.time
                self.store.update_candidate(c)
                self.store.add_event(INVALIDATED, f"{c.direction} {iso(c.a_open)}: {c.reason}", at=quote.time)

    def check_deadlines(self, now: datetime, grace: timedelta = timedelta(seconds=60)) -> None:
        for c in self.store.pending_candidates(self.symbol):
            if c.deadline and now >= c.deadline + M5 + grace:
                c.status, c.reason, c.updated_at = EXPIRED, "deadline_passed_without_confirmation_data", now
                self.store.update_candidate(c)
                self.store.add_event(EXPIRED, f"{c.direction} {iso(c.a_open)}: {c.reason}", at=now)

    def cancel_pending(self, now: datetime, reason: str) -> None:
        for c in self.store.pending_candidates(self.symbol):
            c.status, c.reason, c.updated_at = EXPIRED, reason, now
            self.store.update_candidate(c)
