"""Hand-specified FICTIONAL M5 price paths used by tests and the test fixture (TEST-ONLY; never imported by app/).

`buy_setup` is a complete CRT-SMC-v1 BUY: hour P (filler), hour A (range 2400-2420 with a confirmed swing
high at 2405 inside it), hour B (sweeps A's low to 2399.00 and closes back inside at 2403.00), then M5 bars
that break above 2405 and run to A's high. `mirror` turns any path into its SELL twin.
"""
from __future__ import annotations

from datetime import datetime

from app.models import M5, Bar

# (open, high, low, close) per M5 bar
_P = [(2414.0, 2415.0, 2413.0, 2414.5), (2414.5, 2415.5, 2414.0, 2415.0), (2415.0, 2415.8, 2414.2, 2414.6),
      (2414.6, 2415.2, 2413.8, 2414.0), (2414.0, 2414.8, 2413.2, 2413.6), (2413.6, 2414.4, 2413.0, 2414.2),
      (2414.2, 2415.0, 2413.9, 2414.8), (2414.8, 2415.4, 2414.1, 2414.3), (2414.3, 2414.9, 2413.5, 2413.8),
      (2413.8, 2414.6, 2413.2, 2414.1), (2414.1, 2414.7, 2413.6, 2414.0), (2414.0, 2414.5, 2413.4, 2414.0)]
_A = [(2414.0, 2416.0, 2413.5, 2415.5), (2415.5, 2420.0, 2415.0, 2418.0), (2418.0, 2418.5, 2412.0, 2412.5),
      (2412.5, 2413.0, 2407.0, 2408.0), (2408.0, 2408.5, 2403.0, 2403.5), (2403.5, 2404.0, 2400.0, 2401.0),
      (2401.0, 2402.5, 2400.5, 2402.0), (2402.0, 2404.5, 2401.5, 2404.0), (2404.0, 2405.0, 2403.0, 2403.5),
      (2403.5, 2404.0, 2402.0, 2402.5), (2402.5, 2403.0, 2401.0, 2401.5), (2401.5, 2402.0, 2400.8, 2401.2)]
_B = [(2401.2, 2401.5, 2399.5, 2399.8), (2399.8, 2400.0, 2399.0, 2399.6), (2399.6, 2401.0, 2399.4, 2400.8),
      (2400.8, 2401.8, 2400.5, 2401.5), (2401.5, 2402.2, 2401.0, 2401.9), (2401.9, 2402.5, 2401.5, 2402.0),
      (2402.0, 2402.8, 2401.6, 2402.4), (2402.4, 2403.0, 2402.0, 2402.6), (2402.6, 2403.4, 2402.2, 2403.0),
      (2403.0, 2403.6, 2402.5, 2402.9), (2402.9, 2403.5, 2402.4, 2403.2), (2403.2, 2403.8, 2402.8, 2403.0)]
_CONFIRM = [(2403.0, 2404.0, 2402.6, 2403.8), (2403.8, 2405.6, 2403.5, 2405.4)]
_RUN = [(2405.4, 2407.0, 2405.0, 2406.8), (2406.8, 2409.5, 2406.5, 2409.2), (2409.2, 2412.0, 2409.0, 2411.8),
        (2411.8, 2414.5, 2411.5, 2414.2), (2414.2, 2417.0, 2414.0, 2416.6), (2416.6, 2419.0, 2416.2, 2418.8),
        (2418.8, 2420.3, 2418.5, 2419.9), (2419.9, 2420.0, 2418.0, 2418.4), (2418.4, 2419.0, 2417.5, 2418.0),
        (2418.0, 2418.6, 2417.2, 2417.5)]

BUY_A_HIGH, BUY_A_LOW, BUY_B_LOW, BUY_LEVEL = 2420.0, 2400.0, 2399.0, 2405.0
MIRROR_AXIS = 4800.0  # mirror(p) = 4800 - p keeps prices positive and on the 0.01 grid


def bars_from(start: datetime, rows: list[tuple[float, float, float, float]]) -> list[Bar]:
    return [Bar(start + i * M5, M5, *row) for i, row in enumerate(rows)]


def buy_setup(start: datetime, include_run: bool = True) -> list[Bar]:
    """`start` must be an hour boundary; returns P, A, B, confirmation (and optionally the run to TP)."""
    rows = _P + _A + _B + _CONFIRM + (_RUN if include_run else [])
    return bars_from(start, rows)


def mirror(bars: list[Bar], axis: float = MIRROR_AXIS) -> list[Bar]:
    return [Bar(b.open_time, b.tf, round(axis - b.open, 2), round(axis - b.low, 2), round(axis - b.high, 2),
                round(axis - b.close, 2)) for b in bars]


def sell_setup(start: datetime, include_run: bool = True) -> list[Bar]:
    return mirror(buy_setup(start, include_run))
