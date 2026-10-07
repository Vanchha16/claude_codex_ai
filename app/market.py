"""Chart-only market data (display). Deliberately separate from the strategy engine, which only ever
processes CLOSED H1 and M5 bars. Chart timeframes, forming candles, tick volume and indicators never reach the
engine and never change signal rules."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from .models import M5, UTC, Bar, aggregate

CHART_TIMEFRAMES = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
MAX_CHART_BARS = 1000


class ChartUnavailable(Exception):
    """The requested chart timeframe/history is not available from this source (never fabricated)."""


@dataclass(frozen=True)
class ChartBar:
    time: int  # bar OPEN time, UTC epoch seconds
    open: float
    high: float
    low: float
    close: float
    volume: Optional[int] = None  # MT5 tick_volume when supplied; never exchange volume, never invented
    forming: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["volume"] is None:
            d.pop("volume")
        return d


def validate_request(tf: str, count: int, before: Optional[datetime]) -> tuple[str, int]:
    tf = (tf or "").upper()
    if tf not in CHART_TIMEFRAMES:
        raise ValueError(f"unsupported chart timeframe {tf!r}; use one of {', '.join(CHART_TIMEFRAMES)}")
    if not isinstance(count, int) or not 1 <= count <= MAX_CHART_BARS:
        raise ValueError(f"count must be between 1 and {MAX_CHART_BARS}")
    if before is not None and before.tzinfo is None:
        raise ValueError("before must be a timezone-aware UTC time")
    return tf, count


def epoch(dt: datetime) -> int:
    return int(dt.astimezone(UTC).timestamp())


def from_bar(bar: Bar, volume: Optional[int] = None, forming: bool = False) -> ChartBar:
    return ChartBar(epoch(bar.open_time), bar.open, bar.high, bar.low, bar.close, volume, forming)


def normalize(bars: Iterable[ChartBar]) -> list[ChartBar]:
    """Ascending, unique open times (last occurrence wins), valid finite OHLC only. No gap filling."""
    by_time: dict[int, ChartBar] = {}
    for b in bars:
        values = (b.open, b.high, b.low, b.close)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in values):
            continue
        if b.high < max(b.open, b.close) or b.low > min(b.open, b.close):
            continue
        by_time[b.time] = b
    return [by_time[t] for t in sorted(by_time)]


def aggregate_closed(m5: list[Bar], tf: str, now: datetime) -> list[Bar]:
    """Higher timeframe bars from complete M5 periods that have fully closed by `now` (chart display only)."""
    if tf == "M5":
        return [b for b in m5 if b.close_time <= now]
    seconds = CHART_TIMEFRAMES[tf]
    if seconds % 300:
        raise ChartUnavailable(f"{tf} cannot be derived from M5 bars")
    return [b for b in aggregate(m5, timedelta(seconds=seconds)) if b.close_time <= now]
