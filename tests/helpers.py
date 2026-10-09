from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from app.config import StrategyConfig
from app.engine import Engine
from app.models import M5, UTC, Bar, Quote, SymbolMeta, aggregate
from app.store import MemoryStore

T0 = datetime(2026, 1, 6, 6, 0, tzinfo=UTC)  # Tuesday 06:00 UTC: P=06h, A=07h, B=08h, confirmation from 09:00
A_OPEN = T0 + timedelta(hours=1)
B_OPEN = T0 + timedelta(hours=2)
B_CLOSE = T0 + timedelta(hours=3)
CONFIRM_CLOSE = B_CLOSE + 2 * M5  # second bar after B closes above the 2405 level
META = SymbolMeta("TEST-XAU", 0.01, 0.01, 2, "test")
CFG = StrategyConfig()


def with_bar(bars: list[Bar], idx: int, **changes) -> list[Bar]:
    out = list(bars)
    out[idx] = replace(out[idx], **changes)
    return out


def idx_at(bars: list[Bar], when: datetime) -> int:
    return next(i for i, b in enumerate(bars) if b.open_time == when)


def quote_at_close(spread: float = 0.2, delay_s: float = 1.0, quote_age_s: float = 0.0):
    """Live-style entry: fresh quote right after the confirmation close."""
    def fn(c, bar):
        now = bar.close_time + timedelta(seconds=delay_s)
        q = Quote(now - timedelta(seconds=quote_age_s), bar.close, round(bar.close + spread, 2))
        return q, now
    return fn


def drive(m5: list[Bar], cfg: StrategyConfig = CFG, entry_fn=None, store=None, meta: SymbolMeta = META):
    """Feed closed bars in time order exactly like the scanner/replay do."""
    store = store if store is not None else MemoryStore()
    entry_fn = entry_fn or quote_at_close()
    eng = Engine(cfg, meta, store, mode="test")
    h1 = aggregate(m5)
    by_close = {b.close_time: i for i, b in enumerate(h1)}
    for i, bar in enumerate(m5):
        eng.on_m5_bar(bar, m5[i - 1] if i else None, entry_fn)
        j = by_close.get(bar.close_time)
        if j:
            eng.evaluate_hour(h1[j - 1], h1[j], m5[: i + 1], bar.close_time)
    return store, eng


def candidate_for_a(store: MemoryStore, a_open: datetime = A_OPEN):
    return next((c for c in store.candidates.values() if c.a_open == a_open), None)
