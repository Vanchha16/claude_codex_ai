"""Simulated outcomes (price hits, NOT broker fills).

Exit sides: BUY exits on Bid, SELL exits on Ask. Bars are Bid prices, so for SELL the Ask is approximated
as Bid + spread (the spread observed at entry live, or the configured assumption in replay). If TP and SL
are both reachable inside one bar the order is unknown: the result is AMBIGUOUS, never an optimistic fill.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional

from .config import StrategyConfig
from .engine import Signal
from .models import Bar, Quote
from .strategy import BUY


def expiry_hours(sig: Signal, cfg: StrategyConfig) -> float:
    """Each signal keeps the outcome lifetime of the strategy that created it (FastSweep records carry it in meta;
    older CRT records fall back to the CRT config), so switching strategies never changes an open signal's expiry."""
    try:
        return float(sig.meta.get("outcome_expiry_hours", cfg.outcome_expiry_hours))
    except (TypeError, ValueError):
        return cfg.outcome_expiry_hours


def r_multiple(sig: Signal, exit_price: float, entry: Optional[float] = None) -> float:
    entry = sig.entry if entry is None else entry
    risk = abs(sig.entry - sig.sl)
    if risk <= 0:
        return 0.0
    return round(((exit_price - entry) if sig.direction == BUY else (entry - exit_price)) / risk, 4)


def bar_hit(sig: Signal, bar: Bar, ask_add: float) -> Optional[str]:
    if sig.direction == BUY:
        tp, sl = bar.high >= sig.tp, bar.low <= sig.sl
    else:
        tp, sl = bar.low + ask_add <= sig.tp, bar.high + ask_add >= sig.sl
    if tp and sl:
        return "ambiguous"
    return "tp" if tp else "sl" if sl else None


def quote_hit(sig: Signal, q: Quote) -> Optional[str]:
    px = q.bid if sig.direction == BUY else q.ask
    if (sig.direction == BUY and px >= sig.tp) or (sig.direction != BUY and px <= sig.tp):
        return "tp"
    if (sig.direction == BUY and px <= sig.sl) or (sig.direction != BUY and px >= sig.sl):
        return "sl"
    return None


def settle(sig: Signal, status: str, at: datetime, price: Optional[float], note: str, entry: Optional[float] = None) -> Signal:
    sig.outcome_status, sig.outcome_time, sig.outcome_price, sig.outcome_note = status, at, price, note
    sig.outcome_r = None if status == "ambiguous" or price is None else r_multiple(sig, price, entry)
    return sig


def track_live(sig: Signal, new_bars: Iterable[Bar], quote: Optional[Quote], now: datetime, cfg: StrategyConfig,
               quote_fresh: bool) -> bool:
    """Advance one active live/demo signal. Returns True if the signal changed state."""
    if sig.outcome_status != "active":
        return False
    hours = expiry_hours(sig, cfg)
    deadline = sig.created_at + timedelta(hours=hours)
    for bar in new_bars:
        # Only bars that start at/after the entry quote: earlier prices happened before the simulated entry.
        if bar.open_time < sig.quote_time or (sig.last_checked and bar.close_time <= sig.last_checked):
            continue
        if bar.open_time >= deadline:
            break  # bars after the outcome window never settle a TP/SL (aligned with replay)
        hit = bar_hit(sig, bar, sig.spread)
        sig.last_checked = bar.close_time
        if hit == "ambiguous":
            settle(sig, "ambiguous", bar.close_time, None, "TP and SL both inside one M5 bar; order unknown")
            return True
        if hit:
            note = f"{hit.upper()} touched in M5 bar {bar.open_time:%H:%M} UTC"
            if sig.direction != BUY:
                note += " (ESTIMATE: Ask approximated as Bid bar + entry spread; demo/no-tick feed)"
            settle(sig, hit, bar.close_time, sig.tp if hit == "tp" else sig.sl, note)
            return True
    if quote is not None and quote_fresh and sig.quote_time <= quote.time <= deadline:
        hit = quote_hit(sig, quote)
        if hit:
            settle(sig, hit, quote.time, sig.tp if hit == "tp" else sig.sl, f"{hit.upper()} touched by live quote")
            return True
    if now >= deadline:
        if quote is not None and quote_fresh and quote.time <= deadline + timedelta(seconds=60):
            price = quote.bid if sig.direction == BUY else quote.ask
            settle(sig, "expired", deadline, price, f"expired after {hours:g}h; marked at live exit-side quote")
        else:
            settle(sig, "expired", deadline, None, f"expired after {hours:g}h; no exit-side quote at the deadline to mark R")
        return True
    return False


def track_measured(sig: Signal, observations: list[Quote], now: datetime, cfg: StrategyConfig,
                   gap: Optional[str] = None) -> bool:
    """Live (MT5) outcome tracking from OBSERVED quotes only: Bid ticks for BUY exits, Ask ticks for SELL exits.

    `observations` must be chronological, after `sig.last_checked`, and not later than `now`. A tick-history gap is
    recorded on the signal and never replaced by an estimate from bars. Returns True if the signal changed."""
    if sig.outcome_status != "active":
        return False
    changed = False
    hours = expiry_hours(sig, cfg)
    deadline = sig.created_at + timedelta(hours=hours)
    for q in observations:
        if q.time < sig.quote_time or (sig.last_checked and q.time <= sig.last_checked) or q.time > now:
            continue
        if q.time > deadline:
            break  # the outcome window closed: a later TP/SL never overrides the expiry (same as tick replay)
        sig.last_checked = q.time
        px = q.bid if sig.direction == BUY else q.ask
        sig.meta["last_exit_px"], sig.meta["last_exit_time"] = px, q.time.isoformat()
        hit = quote_hit(sig, q)
        if hit:
            side = "Bid" if sig.direction == BUY else "Ask"
            note = f"{hit.upper()} measured on an observed {side} tick ({px}) at {q.time:%Y-%m-%d %H:%M:%S} UTC"
            if sig.meta.get("measurement_gaps"):
                note += f"; {sig.meta['measurement_gaps']} tick-history gap(s) were recorded earlier"
            settle(sig, hit, q.time, px, note)
            return True
        changed = True
    if gap:
        sig.meta["measurement_gaps"] = int(sig.meta.get("measurement_gaps", 0)) + 1
        sig.meta["last_gap"] = gap
        changed = True
    if now >= deadline:
        px = sig.meta.get("last_exit_px")
        gaps = f"; {sig.meta['measurement_gaps']} tick-history gap(s) recorded" if sig.meta.get("measurement_gaps") else ""
        if px is None:
            settle(sig, "expired", deadline, None, f"expired after {hours:g}h; no exit-side tick observed{gaps}")
        else:
            settle(sig, "expired", deadline, float(px),
                   f"expired after {hours:g}h; marked at the last observed exit-side tick before the deadline{gaps}")
        return True
    return changed
