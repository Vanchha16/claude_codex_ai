"""TEST-ONLY fake market feed: replays the deterministic FICTIONAL fixture on a clock the TEST advances.

Never imported by the app (VC Signal is MT5-only). It stands in for MT5 so tests never touch a real terminal.
Quotes are synthesised inside the currently forming M5 bar (open -> low/high -> close path) with a fixed spread,
timestamped at the simulated time. Tests advance the clock (`advance`) and drive `Scanner.scan_once` themselves.
"""
from __future__ import annotations

import bisect
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import json

from app.data.base import FeedStatus
from app.market import ChartBar, ChartUnavailable, aggregate_closed, epoch, from_bar, normalize
from app.models import H1, M5, Bar, Quote, SymbolMeta, aggregate, parse_iso

FIXTURE = Path(__file__).resolve().parent / "data" / "xauusd_fixture_m5.json"


def load_fixture(path: Path = FIXTURE) -> tuple[list[Bar], SymbolMeta, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    m = raw["meta"]
    meta = SymbolMeta(m["symbol"], m["tick_size"], m["point"], m["digits"], "test")
    return [Bar(parse_iso(r[0]), M5, r[1], r[2], r[3], r[4]) for r in raw["m5"]], meta, raw


class FixtureFeed:
    """Presents itself like the MT5 feed (mode "mt5"), but has no MT5 module (`_api`), so nothing can trade."""
    mode = "mt5"
    supports_ticks = False

    def __init__(self, fixture: Path = FIXTURE):
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
            return FeedStatus(False, "disconnected", "test fixture finished", {"sim_time": self.now().isoformat()})
        return FeedStatus(True, "connected", "TEST fixture feed (fictional, tests only)",
                          {"sim_time": self.now().isoformat(), "provider": "test fixture"})

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
            raise ChartUnavailable("M1 is not available in the test fixture (it only contains M5 bars)")
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


class OfflineFeed:
    """TEST-ONLY default for every test (see conftest.py): an MT5-shaped feed that is never connected."""
    mode = "mt5"
    supports_ticks = False

    def __init__(self, *a, **k):
        pass

    def connect(self) -> FeedStatus:
        return self.status()

    def status(self) -> FeedStatus:
        return FeedStatus(False, "disconnected", "MetaTrader 5 is not running (test offline feed)", {})

    def now(self):
        from datetime import datetime, timezone
        return datetime.now(timezone.utc)

    def shutdown(self) -> None:
        pass
