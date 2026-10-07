"""FastSweep-M15-M5-v1: a research strategy evaluated in replay only (NOT wired to the live scanner).

Predeclared rules (task 20261006-144723; no parameter search):
1. Data: M15 candles are built with app.models.aggregate from complete, contiguous M5 groups. A and B are adjacent
   closed M15 candles; incomplete or gapped groups never exist as candles.
2. Range: BUY when B.low <= A.low - 2 ticks, B.high <= A.high and A.low < B.close < A.high (strict). SELL mirrors it.
   Both sides swept -> double_sided_sweep; non-adjacent A/B -> noncontiguous_m15. (Same predicates as CRT, on M15.)
3. Trend: EMA20 vs EMA50 of M15 closes over the contiguous run of closed M15 candles ending at B. Each EMA is seeded
   with the simple average of its first N closes, then ema = close * k + ema * (1 - k), k = 2 / (N + 1). Ready only
   when the run holds >= 50 candles. EMA20 > EMA50 permits BUY, < permits SELL; equal permits neither.
4. Confirmation: the next three completed M5 candles after B closes (opening at B.close, +5, +10 min). BUY confirms
   when prev.close <= B.high < bar.close; SELL when prev.close >= B.low > bar.close. A bar that revisits B's sweep
   extreme (BUY low <= B.low, SELL high >= B.high) invalidates first (precedence over confirmation in the same bar).
   A missing M5 bar breaks continuity and invalidates. B's extremes are frozen at setup creation.
5. Entry: first executable observation at/after the confirmation close (replay: the contiguous next M5 open);
   BUY at Ask, SELL at Bid; quote freshness 30 s and spread <= 0.50 price units.
6. Stop: B.low - 2 ticks (BUY, rounded down) / B.high + 2 ticks (SELL, rounded up).
7. Target: entry +/- R * risk with R = 1.0 or 2.0 (two separate profiles), rounded outward to the tick so the quoted
   reward/risk is >= R. Costs (spread, slippage) are applied to the simulated fill, not hidden in the geometry.
Frequency controls and outcomes live in app/fastsweep_replay.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .models import M5, Bar, Quote, SymbolMeta, round_down_to_tick, round_up_to_tick

M15 = timedelta(minutes=15)
BUY, SELL = "BUY", "SELL"
BANGKOK = timezone(timedelta(hours=7), "Asia/Bangkok")  # fixed UTC+7: Bangkok observes no DST
STRATEGY = "FastSweep-M15-M5-v1"


@dataclass(frozen=True)
class FastSweepConfig:
    reward_risk: float = 1.0           # fixed target ratio: 1.0 or 2.0 (the two approved profiles)
    sweep_min_ticks: int = 2
    sl_buffer_ticks: int = 2
    ema_fast: int = 20
    ema_slow: int = 50
    trend_min_candles: int = 50        # contiguous closed M15 candles required (incl. B)
    confirm_bars: int = 3              # M5 bars after B's close
    max_spread_price: float = 0.50
    quote_max_age_seconds: int = 30
    cooldown_minutes: int = 30
    max_signals_per_day: int = 4       # per Asia/Bangkok calendar date; a maximum, never a quota
    outcome_expiry_hours: float = 2.0

    @property
    def version(self) -> str:
        return f"{STRATEGY}-RR{self.reward_risk:g}"

    def validate(self) -> "FastSweepConfig":
        if self.reward_risk not in (1.0, 2.0):
            raise ValueError("reward_risk must be 1.0 or 2.0 (the approved profiles)")
        if not (self.ema_fast < self.ema_slow <= self.trend_min_candles):
            raise ValueError("need ema_fast < ema_slow <= trend_min_candles")
        for name in ("sweep_min_ticks", "sl_buffer_ticks", "confirm_bars", "cooldown_minutes", "max_signals_per_day"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")
        if not 0 < self.max_spread_price <= 0.50:
            raise ValueError("max_spread_price must be in (0, 0.50]")
        return self


PROFILES = {"rr1": FastSweepConfig(reward_risk=1.0), "rr2": FastSweepConfig(reward_risk=2.0)}


# ---------------------------------------------------------------- 2. range
@dataclass(frozen=True)
class RangeCheck:
    direction: Optional[str]
    reason: Optional[str]   # "no_sweep" pairs are counted but not recorded as candidates


def evaluate_range(a: Bar, b: Bar, tick: float, cfg: FastSweepConfig) -> RangeCheck:
    if a.tf != M15 or b.tf != M15:
        return RangeCheck(None, "not_m15")
    if not (a.is_valid() and b.is_valid()) or tick <= 0:
        return RangeCheck(None, "invalid_prices")
    if b.open_time != a.close_time:
        return RangeCheck(None, "noncontiguous_m15")
    if not a.high > a.low:
        return RangeCheck(None, "zero_range")
    margin = cfg.sweep_min_ticks * tick
    eps = tick * 1e-6  # float tolerance only; the two-tick rule is not relaxed
    swept_low = b.low <= a.low - margin + eps
    swept_high = b.high >= a.high + margin - eps
    if swept_low and swept_high:
        return RangeCheck(None, "double_sided_sweep")
    if not swept_low and not swept_high:
        return RangeCheck(None, "no_sweep")
    inside = a.low < b.close < a.high
    if swept_low:
        if b.high > a.high:
            return RangeCheck(None, "buy_sweep_but_b_high_above_a_high")
        return RangeCheck(BUY, None) if inside else RangeCheck(None, "buy_sweep_close_not_inside_a")
    if b.low < a.low:
        return RangeCheck(None, "sell_sweep_but_b_low_below_a_low")
    return RangeCheck(SELL, None) if inside else RangeCheck(None, "sell_sweep_close_not_inside_a")


# ---------------------------------------------------------------- 3. trend
def ema_last(closes: list[float], period: int) -> Optional[float]:
    """EMA of the given closes (oldest first), seeded with the SMA of the first `period` closes."""
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    value = sum(closes[:period]) / period
    for c in closes[period:]:
        value = c * k + value * (1 - k)
    return value


def trend_permits(m15_run: list[Bar], cfg: FastSweepConfig) -> tuple[Optional[str], str]:
    """`m15_run`: the contiguous closed M15 candles ending at B (oldest first). Returns (direction|None, reason)."""
    if len(m15_run) < cfg.trend_min_candles:
        return None, "trend_warmup"
    closes = [b.close for b in m15_run]
    fast, slow = ema_last(closes, cfg.ema_fast), ema_last(closes, cfg.ema_slow)
    if fast is None or slow is None or not (math.isfinite(fast) and math.isfinite(slow)):
        return None, "trend_warmup"
    if math.isclose(fast, slow, rel_tol=0.0, abs_tol=1e-9):
        return None, "trend_flat"
    return (BUY, "trend_up") if fast > slow else (SELL, "trend_down")


# ---------------------------------------------------------------- 4. confirmation
@dataclass
class Setup:
    """Frozen when created at B's close."""
    key: str
    direction: str
    a_open: datetime
    b_open: datetime
    b_close: datetime
    a_high: float
    a_low: float
    b_high: float
    b_low: float
    b_close_price: float
    status: str = "pending"            # pending | confirmed | invalidated | expired | rejected | signal
    reason: Optional[str] = None
    confirm_close: Optional[datetime] = None
    bars_seen: int = 0
    last_close: Optional[float] = None  # close of the previous M5 bar (B's last M5 bar initially = B close)
    next_open: Optional[datetime] = None
    meta: dict = field(default_factory=dict)

    @property
    def sweep_extreme(self) -> float:
        return self.b_low if self.direction == BUY else self.b_high

    @property
    def level(self) -> float:
        return self.b_high if self.direction == BUY else self.b_low


def new_setup(a: Bar, b: Bar, direction: str, symbol: str) -> Setup:
    return Setup(key=f"{symbol}|{a.open_time.isoformat()}|{direction}", direction=direction, a_open=a.open_time,
                 b_open=b.open_time, b_close=b.close_time, a_high=a.high, a_low=a.low, b_high=b.high, b_low=b.low,
                 b_close_price=b.close, last_close=b.close, next_open=b.close_time)


def confirm_step(s: Setup, bar: Bar, cfg: FastSweepConfig) -> str:
    """Advance a pending setup with one newly CLOSED M5 bar. Returns the new status."""
    if s.status != "pending" or bar.open_time < s.b_close:
        return s.status                      # confirmation can never happen inside B
    if bar.open_time != s.next_open or not bar.is_valid():
        s.status, s.reason = "invalidated", "m5_continuity_lost"
        return s.status
    s.bars_seen += 1
    revisit = bar.low <= s.b_low if s.direction == BUY else bar.high >= s.b_high
    if revisit:                              # invalidation has precedence over a same-bar confirmation
        s.status, s.reason = "invalidated", "sweep_extreme_revisited"
        return s.status
    prev = s.last_close
    crossed = (prev <= s.b_high < bar.close) if s.direction == BUY else (prev >= s.b_low > bar.close)
    if crossed:
        s.status, s.confirm_close = "confirmed", bar.close_time
        return s.status
    if s.bars_seen >= cfg.confirm_bars:
        s.status, s.reason = "expired", "no_confirmation_within_window"
        return s.status
    s.last_close, s.next_open = bar.close, bar.close_time
    return s.status


# ---------------------------------------------------------------- 5-7. entry, stop, fixed target
@dataclass(frozen=True)
class Levels:
    entry: float
    sl: float
    tp: float
    risk: float
    reward_risk: float     # quoted geometry (>= the profile ratio after outward rounding)
    quote: Quote


def build_levels(s: Setup, quote: Optional[Quote], now: datetime, meta: SymbolMeta,
                 cfg: FastSweepConfig, future_tolerance_s: float = 0.0) -> tuple[Optional[Levels], Optional[str]]:
    """Entry decision at `now`. Rejects: no quote; a decision more than quote_max_age_seconds after the confirmation
    close (even with a fresh quote); a quote older than the confirmation close; a quote stamped later than the decision
    time (beyond `future_tolerance_s`, e.g. terminal clock skew); a stale, invalid or too-wide quote."""
    if quote is None:
        return None, "no_quote"
    if s.confirm_close is None:
        return None, "not_confirmed"
    if (now - s.confirm_close).total_seconds() > cfg.quote_max_age_seconds:
        return None, "missed_confirmation_too_late"
    if quote.time < s.confirm_close:
        return None, "quote_older_than_confirmation_close"
    if (quote.time - now).total_seconds() > future_tolerance_s:
        return None, "quote_in_future"
    if (now - quote.time).total_seconds() > cfg.quote_max_age_seconds:
        return None, "stale_quote"
    if not quote.is_valid() or not quote.spread > 0:
        return None, "invalid_spread"
    if quote.spread > cfg.max_spread_price + 1e-12:
        return None, "spread_too_wide"
    tick, digits, r = meta.tick_size, meta.digits, cfg.reward_risk
    if s.direction == BUY:
        entry = quote.ask
        sl = round_down_to_tick(s.b_low - cfg.sl_buffer_ticks * tick, tick, digits)
        risk = entry - sl
        if not risk > 0:
            return None, "levels_out_of_order"
        tp = round_up_to_tick(entry + r * risk, tick, digits)
        reward = tp - entry
    else:
        entry = quote.bid
        sl = round_up_to_tick(s.b_high + cfg.sl_buffer_ticks * tick, tick, digits)
        risk = sl - entry
        if not risk > 0:
            return None, "levels_out_of_order"
        tp = round_down_to_tick(entry - r * risk, tick, digits)
        reward = entry - tp
    rr = reward / risk
    if rr < r - 1e-9:  # outward rounding guarantees this; kept as an explicit check
        return None, "reward_risk_below_profile"
    return Levels(entry, sl, tp, risk, rr, quote), None


def bangkok_date(t: datetime) -> str:
    return t.astimezone(BANGKOK).date().isoformat()
