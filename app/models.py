"""Market data value types. All times are timezone-aware UTC; bar times are OPEN times."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

UTC = timezone.utc
M5 = timedelta(minutes=5)
H1 = timedelta(hours=1)


def utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime; all times must be timezone-aware UTC")
    return dt.astimezone(UTC)


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else utc(dt).isoformat().replace("+00:00", "Z")


def parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


@dataclass(frozen=True)
class Bar:
    open_time: datetime
    tf: timedelta
    open: float
    high: float
    low: float
    close: float

    @property
    def close_time(self) -> datetime:
        """The bar is complete (and usable) only at its close time."""
        return self.open_time + self.tf

    def is_valid(self) -> bool:
        values = (self.open, self.high, self.low, self.close)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in values):
            return False
        return self.high >= max(self.open, self.close) and self.low <= min(self.open, self.close)

    def to_dict(self) -> dict:
        return {"t": iso(self.open_time), "o": self.open, "h": self.high, "l": self.low, "c": self.close}


@dataclass(frozen=True)
class Quote:
    time: datetime
    bid: float
    ask: float

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    def is_valid(self) -> bool:
        return (
            all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (self.bid, self.ask))
            and self.ask >= self.bid
        )


@dataclass(frozen=True)
class SymbolMeta:
    name: str
    tick_size: float
    point: float
    digits: int
    source: str  # "mt5" (live terminal) or "csv" (user-supplied replay history)

    def to_dict(self) -> dict:
        return {"name": self.name, "tick_size": self.tick_size, "point": self.point, "digits": self.digits, "source": self.source}


def _round_to_tick(price: float, tick: float, rounding: str, digits: int) -> float:
    p, t = Decimal(repr(price)), Decimal(repr(tick))
    if t <= 0:
        raise ValueError("tick size must be positive")
    steps = (p / t).to_integral_value(rounding=rounding)
    return round(float(steps * t), digits)


def round_down_to_tick(price: float, tick: float, digits: int) -> float:
    return _round_to_tick(price, tick, ROUND_FLOOR, digits)


def round_up_to_tick(price: float, tick: float, digits: int) -> float:
    return _round_to_tick(price, tick, ROUND_CEILING, digits)


def contiguous(bars: list[Bar]) -> bool:
    return all(b.open_time == a.close_time for a, b in zip(bars, bars[1:]))


def aggregate(m5: list[Bar], tf: timedelta = H1) -> list[Bar]:
    """Build complete higher-timeframe bars from contiguous M5 bars (incomplete periods are skipped)."""
    per = int(tf / M5)
    groups: dict[datetime, list[Bar]] = {}
    for bar in m5:
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        start = epoch + ((bar.open_time - epoch) // tf) * tf
        groups.setdefault(start, []).append(bar)
    out = []
    for start in sorted(groups):
        g = sorted(groups[start], key=lambda b: b.open_time)
        if len(g) != per or g[0].open_time != start or not contiguous(g):
            continue
        if any(b.tf != M5 or not b.is_valid() for b in g):
            continue  # one invalid/non-M5 constituent voids the whole group; the gap breaks contiguous runs/warm-up
        out.append(Bar(start, tf, g[0].open, max(b.high for b in g), min(b.low for b in g), g[-1].close))
    return out
