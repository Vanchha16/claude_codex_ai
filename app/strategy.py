"""CRT-SMC-v1: CRT range sweep/reclaim with one M5 structure-break confirmation.

This is OUR documented, configurable definition (see README "Strategy: CRT-SMC-v1"), not a universal
ICT/SMC/CRT standard. Every function here is pure: it only sees bars that are complete at the
decision time it is asked about, so live scanning and historical replay share identical rules.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .config import StrategyConfig
from .models import H1, M5, Bar, Quote, SymbolMeta, contiguous, round_down_to_tick, round_up_to_tick

BUY, SELL = "BUY", "SELL"


# ---------------------------------------------------------------- A. range + B. sweep/reclaim
@dataclass(frozen=True)
class RangeCheck:
    direction: str | None  # BUY / SELL when a candidate exists
    reason: str | None  # rejection reason; "no_sweep" means nothing worth recording


def evaluate_range(a: Bar, b: Bar, tick: float, cfg: StrategyConfig) -> RangeCheck:
    """Evaluate completed H1 candles A and B once, at B's close."""
    if a.tf != H1 or b.tf != H1:
        return RangeCheck(None, "not_h1")
    if not (a.is_valid() and b.is_valid()) or tick <= 0:
        return RangeCheck(None, "invalid_prices")
    if b.open_time != a.close_time:
        return RangeCheck(None, "noncontiguous_hours")
    if not a.high > a.low:
        return RangeCheck(None, "zero_range")
    margin = cfg.sweep_min_ticks * tick
    eps = tick * 1e-6  # float tolerance only; the two-tick rule itself is not relaxed
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
        if not inside:
            return RangeCheck(None, "buy_sweep_close_not_inside_a")
        return RangeCheck(BUY, None)
    if b.low < a.low:
        return RangeCheck(None, "sell_sweep_but_b_low_below_a_low")
    if not inside:
        return RangeCheck(None, "sell_sweep_close_not_inside_a")
    return RangeCheck(SELL, None)


# ---------------------------------------------------------------- C. structure level
@dataclass(frozen=True)
class Pivot:
    kind: str  # "high" or "low"
    bar_open: datetime
    level: float
    available_at: datetime  # close of the last right-hand confirming bar


def find_pivots(bars: list[Bar], side: int) -> list[Pivot]:
    """Strict swing highs/lows with `side` CLOSED bars on each side. Ties are not pivots."""
    out: list[Pivot] = []
    for i in range(side, len(bars) - side):
        window = bars[i - side : i + side + 1]
        if not contiguous(window):
            continue
        others = window[:side] + window[side + 1 :]
        mid = bars[i]
        available = window[-1].close_time
        if all(mid.high > o.high for o in others):
            out.append(Pivot("high", mid.open_time, mid.high, available))
        if all(mid.low < o.low for o in others):
            out.append(Pivot("low", mid.open_time, mid.low, available))
    return out


@dataclass(frozen=True)
class StructureCheck:
    pivot: Pivot | None
    reason: str | None


def select_structure(direction: str, a: Bar, b: Bar, m5: list[Bar], cfg: StrategyConfig) -> StructureCheck:
    """Freeze the most recent confirmed swing (high for BUY, low for SELL) available at or before B OPEN,
    taken from the `structure_lookback_bars` M5 bars that precede B open, strictly inside A's range."""
    start = b.open_time - cfg.structure_lookback_bars * M5
    window = [x for x in m5 if start <= x.open_time and x.close_time <= b.open_time]
    if window and (not contiguous(window) or window[-1].close_time != b.open_time):
        return StructureCheck(None, "m5_gap_before_b")
    if len(window) < cfg.structure_lookback_bars:
        return StructureCheck(None, "insufficient_m5_history")
    if not all(x.is_valid() for x in window):
        return StructureCheck(None, "invalid_m5_prices")
    kind = "high" if direction == BUY else "low"
    eligible = [p for p in find_pivots(window, cfg.pivot_side_bars)
                if p.kind == kind and p.available_at <= b.open_time and a.low < p.level < a.high]
    if not eligible:
        return StructureCheck(None, f"no_confirmed_swing_{kind}_inside_a")
    return StructureCheck(max(eligible, key=lambda p: p.available_at), None)


# ---------------------------------------------------------------- D. confirmation
@dataclass(frozen=True)
class Setup:
    """Frozen facts of a candidate; never relabelled after creation."""
    direction: str
    a_high: float
    a_low: float
    sweep_extreme: float  # B.low for BUY, B.high for SELL
    level: float
    b_close: datetime

    def deadline(self, cfg: StrategyConfig) -> datetime:
        return self.b_close + cfg.confirm_max_bars * M5


@dataclass(frozen=True)
class Step:
    status: str  # pending | confirmed | invalidated | expired | rejected
    reason: str | None = None


def invalidation_by_price(setup: Setup, high: float, low: float) -> str | None:
    if setup.direction == BUY:
        if low <= setup.sweep_extreme:
            return "sweep_extreme_revisited"
        if high >= setup.a_high:
            return "opposite_boundary_touched"
    else:
        if high >= setup.sweep_extreme:
            return "sweep_extreme_revisited"
        if low <= setup.a_low:
            return "opposite_boundary_touched"
    return None


def confirm_step(setup: Setup, prev: Bar | None, bar: Bar, cfg: StrategyConfig) -> Step:
    """Process one newly CLOSED M5 bar for a pending setup. Invalidation beats confirmation in the same bar."""
    if bar.open_time < setup.b_close:
        return Step("pending")  # still inside B; confirmation bars open at/after B close
    if bar.open_time >= setup.deadline(cfg):
        return Step("expired", "no_confirmation_within_window")
    if prev is None or prev.close_time != bar.open_time or not bar.is_valid():
        return Step("invalidated", "m5_continuity_lost")
    reason = invalidation_by_price(setup, bar.high, bar.low)
    if reason:
        return Step("invalidated", reason)
    crossed = (prev.close <= setup.level < bar.close) if setup.direction == BUY else (prev.close >= setup.level > bar.close)
    if crossed:
        if not setup.a_low < bar.close < setup.a_high:
            return Step("rejected", "confirmation_closed_outside_a_range")
        return Step("confirmed")
    if bar.close_time >= setup.deadline(cfg):
        return Step("expired", "no_confirmation_within_window")
    return Step("pending")


def invalidation_by_quote(setup: Setup, quote: Quote) -> str | None:
    """Live tick check between bar closes (chart prices are Bid)."""
    return invalidation_by_price(setup, quote.bid, quote.bid)


# ---------------------------------------------------------------- E/F. entry, levels, freshness
@dataclass(frozen=True)
class Levels:
    entry: float
    sl: float
    tp: float
    reward_risk: float
    spread: float
    quote: Quote


@dataclass(frozen=True)
class EntryCheck:
    levels: Levels | None
    reason: str | None


def build_entry(setup: Setup, confirm_close: datetime, quote: Quote | None, now: datetime,
                meta: SymbolMeta, cfg: StrategyConfig) -> EntryCheck:
    if quote is None:
        return EntryCheck(None, "no_quote")
    if (now - confirm_close).total_seconds() > cfg.signal_max_age_seconds:
        return EntryCheck(None, "missed_confirmation_too_late")
    if quote.time < confirm_close:
        return EntryCheck(None, "quote_older_than_confirmation_close")
    if (now - quote.time).total_seconds() > cfg.quote_max_age_seconds:
        return EntryCheck(None, "stale_quote")
    if not quote.is_valid() or not quote.spread > 0 or not math.isfinite(quote.spread):
        return EntryCheck(None, "invalid_spread")
    if quote.spread > cfg.max_spread_price + 1e-12:
        return EntryCheck(None, "spread_too_wide")
    tick = meta.tick_size
    if setup.direction == BUY:
        entry = quote.ask
        sl = round_down_to_tick(setup.sweep_extreme - cfg.sl_buffer_ticks * tick, tick, meta.digits)
        tp = setup.a_high
        if not sl < entry < tp:
            return EntryCheck(None, "levels_out_of_order")
        rr = (tp - entry) / (entry - sl)
    else:
        entry = quote.bid
        sl = round_up_to_tick(setup.sweep_extreme + cfg.sl_buffer_ticks * tick, tick, meta.digits)
        tp = setup.a_low
        if not tp < entry < sl:
            return EntryCheck(None, "levels_out_of_order")
        rr = (entry - tp) / (sl - entry)
    if rr < cfg.min_reward_risk:
        return EntryCheck(None, "reward_risk_below_minimum")
    return EntryCheck(Levels(entry, sl, tp, rr, quote.spread, quote), None)


def explain(direction: str, a: dict, level: float, b_extreme: float) -> str:
    if direction == BUY:
        return (f"H1 candle B swept below candle A's low ({a['low']}) to {b_extreme} and closed back inside A's range; "
                f"an M5 close then broke above the frozen swing high {level}. Target: A's high ({a['high']}).")
    return (f"H1 candle B swept above candle A's high ({a['high']}) to {b_extreme} and closed back inside A's range; "
            f"an M5 close then broke below the frozen swing low {level}. Target: A's low ({a['low']}).")
