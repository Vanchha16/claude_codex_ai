"""Live adapter for FastSweep-M15-M5-v1: persistent candidates/signals on the existing store, driven by the scanner.

Same rule functions as the replay (app/fastsweep.py). The scanner feeds each newly CLOSED M5 bar exactly once, in
time order. M15 candles come from complete closed M5 groups (app.models.aggregate); an A/B pair is evaluated only at
B's close; the EMA trend uses the contiguous closed-M15 run ending at B inside the scanner's history window (no
future bars, SMA seed, >= 50 candles). Persisted records use the existing Candidate/Signal tables:
level = B high (BUY) / B low (SELL), deadline = B close + confirm_bars x M5, last_bar_close = confirmation progress.

Only records whose config_version equals this engine's fingerprinted version are processed; pending setups of
another strategy/profile are retired explicitly (status "expired", reason "retired_strategy_switch") and never
evaluated with these rules. Controls are enforced from persisted signals, so restarts or profile switches cannot
reset them: one active signal per symbol (any strategy), >= cooldown since the last FastSweep-family signal, and
at most N FastSweep-family signals per Asia/Bangkok date. Only confirmations closing STRICTLY after the session
eligibility watermark may become signals; earlier ones are recorded as rejected and never count toward the cap.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Callable, Optional

from .active_strategy import fastsweep_version, is_fastsweep_version
from .engine import CONFIRMED, EXPIRED, INVALIDATED, PENDING, REJECTED, Candidate, Signal
from .fastsweep import (BUY, M15, STRATEGY, FastSweepConfig, Setup, bangkok_date, build_levels, confirm_step,
                        ema_last, evaluate_range, trend_permits)
from .models import M5, Bar, Quote, SymbolMeta, aggregate, iso

ALERT_VALID_SECONDS = 120          # same alert validity window as CRT
FUTURE_QUOTE_TOLERANCE_S = 5.0     # same clock-skew tolerance the scanner applies to quote freshness
EntryFn = Callable[[Candidate, Bar], tuple[Optional[Quote], datetime]]


def retire_foreign_pending(store, symbol: str, active_version: str, now: datetime) -> int:
    """Pending setups created by another strategy/profile are closed explicitly, never re-evaluated."""
    n = 0
    for c in store.pending_candidates(symbol):
        if c.config_version != active_version:
            c.status, c.reason, c.updated_at = EXPIRED, "retired_strategy_switch", now
            store.update_candidate(c)
            store.add_event(EXPIRED, f"{c.direction or 'range'} {iso(c.a_open)} ({c.config_version}): retired, "
                                     f"active strategy is now {active_version}", at=now)
            n += 1
    return n


def m15_run_ending_at(m15: list[Bar], j: int) -> list[Bar]:
    k = j
    while k > 0 and m15[k - 1].close_time == m15[k].open_time:
        k -= 1
    return m15[k: j + 1]


class FastSweepEngine:
    kind = "fastsweep"

    def __init__(self, cfg: FastSweepConfig, profile: str, meta: SymbolMeta, store, mode: str):
        self.cfg, self.profile, self.meta, self.store, self.mode = cfg.validate(), profile, meta, store, mode
        self.symbol = meta.name
        self.version = fastsweep_version(cfg)
        self.eligible_after: Optional[datetime] = None   # set by the scanner (startup/restart/resume/recovery)
        self.last_evaluation: Optional[dict] = None
        self.readiness: Optional[dict] = None

    # ------------------------------------------------------------------ helpers
    def _own_pending(self) -> list[Candidate]:
        return [c for c in self.store.pending_candidates(self.symbol) if c.config_version == self.version]

    def _setup(self, c: Candidate) -> Setup:
        s = Setup(key=c.key, direction=c.direction, a_open=c.a_open, b_open=c.b_open, b_close=c.b_close,
                  a_high=c.a_high, a_low=c.a_low, b_high=c.b_high, b_low=c.b_low, b_close_price=0.0)
        s.next_open = c.last_bar_close or c.b_close
        s.bars_seen = int((s.next_open - c.b_close) / M5)
        return s

    def _close(self, c: Candidate, status: str, reason: Optional[str], at: datetime) -> None:
        c.status, c.reason, c.updated_at = status, reason, at
        self.store.update_candidate(c)
        self.store.add_event(status, f"{c.direction} {iso(c.a_open)} [FastSweep {self.profile}]: {reason}", at=at)

    def _family_signals(self) -> list[Signal]:
        return [s for s in self.store.list_signals(1000) if s.symbol == self.symbol and is_fastsweep_version(s.config_version)]

    # ------------------------------------------------------------------ per closed M5 bar
    def process_bar(self, m5: list[Bar], i: int, entry_fn: EntryFn, now: datetime) -> list[Signal]:
        bar = m5[i]
        prev = m5[i - 1] if i > 0 else None
        created: list[Signal] = []
        for c in sorted(self._own_pending(), key=lambda x: x.b_close):
            if c.confirm_close is not None:
                continue  # confirmed, waiting for the first quote at/after the close (see retry_awaiting)
            if bar.open_time < c.b_close or (c.last_bar_close and bar.close_time <= c.last_bar_close):
                continue
            s = self._setup(c)
            if prev is None or prev.close_time != bar.open_time:
                status, s.reason = "invalidated", "m5_continuity_lost"  # a missing M5 bar breaks the window
            else:
                s.last_close = prev.close
                status = confirm_step(s, bar, self.cfg)
            c.last_bar_close, c.updated_at = bar.close_time, bar.close_time
            if status == "pending":
                self.store.update_candidate(c)
            elif status == "confirmed":
                c.confirm_close = bar.close_time
                if self.eligible_after is not None and c.confirm_close <= self.eligible_after:
                    self._close(c, REJECTED, "confirmation_before_session_watermark", bar.close_time)
                    continue
                quote, decided = entry_fn(c, bar)
                if self._awaiting_quote(c, quote, decided):
                    continue
                sig = self._confirm(c, s, quote, decided)
                if sig:
                    created.append(sig)
            else:
                self._close(c, INVALIDATED if status == "invalidated" else EXPIRED, s.reason, bar.close_time)
        if bar.close_time.minute % 15 == 0 and bar.close_time.second == 0:
            self._evaluate_pair(m5[: i + 1], bar, now)
        return created

    def _awaiting_quote(self, c: Candidate, quote: Optional[Quote], now: datetime) -> bool:
        """The scanner treats a bar as closed by clock time, so the first scan can hold a quote stamped just BEFORE
        the confirmation close. The rule is the first observation at/after the close, so wait (status stays pending
        with confirm_close set) while still inside the freshness window instead of rejecting a valid confirmation."""
        no_observation = quote is None or quote.time < c.confirm_close
        if no_observation and (now - c.confirm_close).total_seconds() <= self.cfg.quote_max_age_seconds:
            if c.reason != "awaiting_first_quote_after_close":
                c.reason, c.updated_at = "awaiting_first_quote_after_close", now
                self.store.update_candidate(c)
            return True
        return False

    def retry_awaiting(self, entry_fn: EntryFn, now: datetime) -> list[Signal]:
        """Called on every scan: enter confirmed setups once a quote at/after the confirmation close is observed."""
        created = []
        for c in self._own_pending():
            if c.confirm_close is None:
                continue
            if not self._eligible(c):  # e.g. stored before a restart/recovery: consume, never retry again
                self._close(c, REJECTED, "confirmation_before_session_watermark", now)
                continue
            quote, decided = entry_fn(c, None)
            if self._awaiting_quote(c, quote, decided):
                continue
            s = self._setup(c)
            sig = self._confirm(c, s, quote, decided)
            if sig:
                created.append(sig)
        return created

    def _evaluate_pair(self, history: list[Bar], bar: Bar, now: datetime) -> None:
        m15 = aggregate(history, M15)
        if len(m15) < 2 or m15[-1].close_time != bar.close_time:
            return  # B is not a complete closed M15 candle
        a, b = m15[-2], m15[-1]
        rc = evaluate_range(a, b, self.meta.tick_size, self.cfg)
        trend, why = (None, None)
        if rc.direction:
            trend, why = trend_permits(m15_run_ending_at(m15, len(m15) - 1), self.cfg)
        self.last_evaluation = {"a_open": iso(a.open_time), "b_close": iso(b.close_time), "evaluated_at": iso(now),
                                "direction": rc.direction, "reason": rc.reason, "trend": why, "config_version": self.version}
        if rc.reason in ("no_sweep", "not_m15"):
            return
        key = f"{self.symbol}|{iso(a.open_time)}|{self.version}"
        if self.store.get_candidate(key) is not None:
            return  # persistent deduplication across scans and restarts
        status, reason = (REJECTED, rc.reason) if rc.reason else (PENDING, None)
        if status == PENDING and trend is None:
            status, reason = REJECTED, why
        elif status == PENDING and trend != rc.direction:
            status, reason = REJECTED, "trend_against"
        warm = self.eligible_after is not None and b.close_time <= self.eligible_after
        c = Candidate(key=key, symbol=self.symbol, config_version=self.version, mode=self.mode, direction=rc.direction,
                      a_open=a.open_time, b_open=b.open_time, b_close=b.close_time, a_high=a.high, a_low=a.low,
                      b_high=b.high, b_low=b.low, status=status, reason=reason, created_at=now, updated_at=now, warmup=warm)
        if rc.direction:
            c.level = b.high if rc.direction == BUY else b.low
            c.deadline = b.close_time + self.cfg.confirm_bars * M5
            c.last_bar_close = b.close_time
        self.store.add_candidate(c)
        self.store.add_event("candidate", f"FastSweep {self.profile} M15 A={iso(a.open_time)}: {c.direction or 'range'} "
                                          f"{c.status}" + (f" ({c.reason})" if c.reason else ""), at=now)

    def _eligible(self, c: Candidate) -> bool:
        """Strict session eligibility: only confirmations closing STRICTLY after the current watermark may alert."""
        return self.eligible_after is None or (c.confirm_close is not None and c.confirm_close > self.eligible_after)

    def _confirm(self, c: Candidate, s: Setup, quote: Optional[Quote], now: datetime) -> Optional[Signal]:
        cfg = self.cfg
        if not self._eligible(c):  # common final gate for every path (bar close and post-close retry)
            self._close(c, REJECTED, "confirmation_before_session_watermark", now)
            return None
        if self.store.active_signals(self.symbol):
            self._close(c, REJECTED, "active_signal", now)
            return None
        family = self._family_signals()
        last = max((x.created_at for x in family), default=None)
        if last is not None and now - last < timedelta(minutes=cfg.cooldown_minutes):
            self._close(c, REJECTED, "cooldown", now)
            return None
        today = bangkok_date(now)
        if sum(1 for x in family if bangkok_date(x.created_at) == today) >= cfg.max_signals_per_day:
            self._close(c, REJECTED, "daily_cap", now)
            return None
        if quote is not None and quote.is_valid():  # live Bid revisit of B's sweep extreme beats the confirmation
            if (c.direction == BUY and quote.bid <= c.b_low) or (c.direction != BUY and quote.bid >= c.b_high):
                self._close(c, INVALIDATED, "sweep_extreme_revisited_live_quote", now)
                return None
        s.status, s.confirm_close = "confirmed", c.confirm_close
        lv, why = build_levels(s, quote, now, self.meta, cfg, future_tolerance_s=FUTURE_QUOTE_TOLERANCE_S)
        if lv is None:
            self._close(c, REJECTED, why, now)
            return None
        digest = hashlib.sha256(c.key.encode()).hexdigest()[:6].upper()
        prefix = "DEMO-" if self.mode == "demo" else ""
        sig = Signal(id=f"{prefix}FS-{c.b_close:%Y%m%d-%H%M}-{c.direction}-{digest}", candidate_key=c.key, symbol=self.symbol,
                     mode=self.mode, direction=c.direction, entry=lv.entry, sl=lv.sl, tp=lv.tp,
                     reward_risk=round(lv.reward_risk, 3), spread=round(lv.quote.spread, 6), bid=lv.quote.bid,
                     ask=lv.quote.ask, quote_time=lv.quote.time, confirm_close=c.confirm_close, created_at=now,
                     valid_until=c.confirm_close + timedelta(seconds=ALERT_VALID_SECONDS), config_version=self.version,
                     explanation=(f"FastSweep M15: B swept A's {'low' if c.direction == BUY else 'high'} and closed back "
                                  f"inside; an M5 close broke B's {'high' if c.direction == BUY else 'low'} ({c.level}). "
                                  f"Fixed 1:{cfg.reward_risk:g} target."),
                     meta={"symbol": self.meta.to_dict(), "strategy": STRATEGY, "profile": self.profile,
                           "outcome_expiry_hours": cfg.outcome_expiry_hours, "a_open": iso(c.a_open),
                           "b_open": iso(c.b_open), "b_high": c.b_high, "b_low": c.b_low, "level": c.level},
                     last_checked=now)
        if not self.store.add_signal(sig):
            self._close(c, REJECTED, "duplicate_signal", now)
            return None
        c.status, c.reason, c.updated_at = CONFIRMED, None, now
        self.store.update_candidate(c)
        self.store.add_event("signal", f"{sig.id}: {sig.direction} entry {sig.entry} SL {sig.sl} TP {sig.tp} "
                                       f"R:R {sig.reward_risk} [FastSweep {self.profile}]", at=now)
        return sig

    # ------------------------------------------------------------------ live checks on every scan
    def on_quote(self, quote: Optional[Quote]) -> None:
        if quote is None or not quote.is_valid():
            return
        for c in self._own_pending():
            if quote.time < c.b_close:
                continue
            if (c.direction == BUY and quote.bid <= c.b_low) or (c.direction != BUY and quote.bid >= c.b_high):
                self._close(c, INVALIDATED, "sweep_extreme_revisited_live_tick", quote.time)

    def check_deadlines(self, now: datetime, grace: timedelta = timedelta(seconds=60)) -> None:
        for c in self._own_pending():
            if c.deadline and now >= c.deadline + M5 + grace:
                self._close(c, EXPIRED, "deadline_passed_without_confirmation_data", now)

    def cancel_pending(self, now: datetime, reason: str) -> None:
        for c in self._own_pending():
            self._close(c, EXPIRED, reason, now)

    def update_readiness(self, m5: list[Bar], now: datetime) -> dict:
        """Trend readiness from the scanner's closed-bar window (what the next B close would see)."""
        m15 = aggregate(m5, M15)
        run = m15_run_ending_at(m15, len(m15) - 1) if m15 else []
        closes = [b.close for b in run]
        fast, slow = ema_last(closes, self.cfg.ema_fast), ema_last(closes, self.cfg.ema_slow)
        trend = None
        if len(run) >= self.cfg.trend_min_candles and fast is not None and slow is not None:
            trend = "flat" if abs(fast - slow) <= 1e-9 else ("up (BUY setups allowed)" if fast > slow else "down (SELL setups allowed)")
        last_close = m5[-1].close_time if m5 else None
        nxt = None
        if last_close is not None:
            nxt = last_close + timedelta(minutes=(15 - last_close.minute % 15) or 15) - timedelta(seconds=last_close.second)
        self.readiness = {"m15_run": len(run), "required": self.cfg.trend_min_candles,
                          "ready": len(run) >= self.cfg.trend_min_candles, "trend": trend,
                          "ema_fast": None if fast is None else round(fast, 3), "ema_slow": None if slow is None else round(slow, 3),
                          "last_m15_close": iso(m15[-1].close_time) if m15 else None, "next_m15_close": iso(nxt) if nxt else None,
                          "checked_at": iso(now)}
        return self.readiness
