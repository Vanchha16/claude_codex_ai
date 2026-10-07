"""FICTIONAL demo feed: replays the deterministic fixture on a simulated clock.

Nothing here is market data. Quotes are synthesised inside the currently forming M5 bar
(open -> low/high -> close path) with a fixed demo spread, and timestamped at the simulated time.
"""
from __future__ import annotations

import bisect
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from ..market import ChartBar, ChartUnavailable, aggregate_closed, epoch, from_bar, normalize
from ..models import H1, M5, Bar, Quote, SymbolMeta, aggregate, parse_iso
from .base import FeedStatus


class DemoFeed:
    mode = "demo"
    supports_ticks = False

    def __init__(self, fixture: Path):
        from ..replay import load_fixture
        self.m5, self._meta, raw = load_fixture(fixture)
        self.h1 = aggregate(self.m5)
        self.spread = float(raw["meta"].get("demo_spread", 0.20))
        self.start = parse_iso(raw["meta"]["demo_start"])
        self.end = self.m5[-1].close_time
        self._open_times = [b.open_time for b in self.m5]
        self._h1_open = [b.open_time for b in self.h1]
        self._now = self.start
        self._lock = threading.RLock()

    # --- simulated clock
    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now = min(self._now + timedelta(seconds=seconds), self.end)

    def reset(self) -> None:
        with self._lock:
            self._now = self.start

    def now(self) -> datetime:
        with self._lock:
            return self._now

    @property
    def finished(self) -> bool:
        return self.now() >= self.end

    # --- Feed protocol
    def connect(self) -> FeedStatus:
        return self.status()

    def status(self) -> FeedStatus:
        if self.finished:
            return FeedStatus(False, "demo_finished", "Demo fixture finished. Restart the demo to replay it.",
                              {"sim_time": self.now().isoformat()})
        return FeedStatus(True, "demo", "DEMO data: fictional fixture on a simulated clock (not market data)",
                          {"sim_time": self.now().isoformat(), "fixture_end": self.end.isoformat()})

    def meta(self) -> SymbolMeta:
        return self._meta

    def _forming(self, now: datetime) -> Optional[Bar]:
        i = bisect.bisect_right(self._open_times, now) - 1
        if i < 0:
            return None
        bar = self.m5[i]
        return bar if bar.open_time <= now < bar.close_time else None

    def quote(self) -> Optional[Quote]:
        now = self.now()
        bar = self._forming(now)
        if bar is None:
            return None
        f = (now - bar.open_time) / M5
        path = [bar.open, bar.low, bar.high, bar.close] if bar.close >= bar.open else [bar.open, bar.high, bar.low, bar.close]
        seg = min(int(f * 3), 2)
        local = f * 3 - seg
        bid = path[seg] + (path[seg + 1] - path[seg]) * local
        tick = self._meta.tick_size
        bid = round(round(bid / tick) * tick, self._meta.digits)
        return Quote(now, bid, round(bid + self.spread, self._meta.digits))

    def closed_bars(self, tf: str, count: int) -> list[Bar]:
        now = self.now()
        src, opens, step = (self.m5, self._open_times, M5) if tf == "M5" else (self.h1, self._h1_open, H1)
        hi = bisect.bisect_right(opens, now - step)  # bars whose close_time <= now
        return src[max(0, hi - count): hi]

    def bars_range(self, tf: str, start: datetime, end: datetime) -> list[Bar]:
        now = self.now()
        src = self.m5 if tf == "M5" else self.h1
        return [b for b in src if start <= b.open_time and b.close_time <= min(end, now)]

    def account_context(self) -> dict:
        return {}

    # ---------------------------------------------------------------- chart (display only)
    def chart_bars(self, tf: str, count: int, before: Optional[datetime] = None):
        """Fixture bars for the chart. Only M5 and timeframes derivable from COMPLETE M5 periods exist;
        M1 is unavailable (the fixture has no M1 prices) and is never invented."""
        if tf == "M1":
            raise ChartUnavailable("M1 is not available in the fictional demo fixture (it only contains M5 bars)")
        now = self.now()
        bars = aggregate_closed(self.m5, tf, now)
        if before is not None:
            bars = [b for b in bars if b.open_time < before]
        closed = normalize(from_bar(b) for b in bars)[-count:]
        forming = None
        if before is None and tf == "M5":
            bar = self._forming(now)
            q = self.quote()
            if bar is not None and q is not None:
                f = (now - bar.open_time) / M5
                path = [bar.open, bar.low, bar.high, bar.close] if bar.close >= bar.open else [bar.open, bar.high, bar.low, bar.close]
                seen = path[: min(int(f * 3), 2) + 1] + [q.bid]  # only prices up to the simulated "now"
                forming = ChartBar(epoch(bar.open_time), bar.open, max(seen), min(seen), q.bid, None, forming=True)
        return closed, forming

    def shutdown(self) -> None:
        pass
