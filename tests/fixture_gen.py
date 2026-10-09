"""Build the deterministic FICTIONAL TEST fixture (tests only): python -m tests.fixture_gen

Scenarios (in order), separated by quiet filler hours whose identical ranges never sweep each other:
  1 valid BUY -> runs to TP          2 valid SELL -> runs to TP
  3 BUY invalidated (sweep extreme revisited before confirmation)
  4 BUY rejected: no confirmed swing high inside A
  5 SELL expired: no structure break within 12 M5 bars
  6 double-sided sweep (rejected)    7 valid BUY -> stopped out (SL)
Transitions between blocks may create extra rejected candidates; that is expected and visible in the UI.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from app.models import H1, M5, UTC, Bar, iso
from tests.fixture_feed import FIXTURE as DEMO_FIXTURE
from tests.scenarios import _A, _B, _CONFIRM, _P, _RUN, bars_from, mirror

START = datetime(2030, 1, 7, 0, 0, tzinfo=UTC)  # deliberately in the future: obviously not historical market data
TICK = 0.01


def _shift(rows, delta):
    return [tuple(round(v + delta, 2) for v in r) for r in rows]


def _flat(price, n):
    return [(price, round(price + 0.15, 2), round(price - 0.15, 2), price) for _ in range(n)]


def _filler_hour(c):
    rows = []
    for i in range(12):
        hi = c + (0.5 if i == 3 else 0.3)
        lo = c - (0.5 if i == 8 else 0.3)
        rows.append((c, round(hi, 2), round(lo, 2), c))
    return rows


def _mirror_rows(rows, axis=4800.0):
    return [(round(axis - o, 2), round(axis - l, 2), round(axis - h, 2), round(axis - c, 2)) for o, h, l, c in rows]


def scenario_rows() -> list[tuple[str, list]]:
    after = _CONFIRM + _RUN
    invalidated = [(2403.0, 2403.4, 2398.5, 2400.4)] + _flat(2400.4, 11)
    p_ties = [(o, max(o, c, 2415.0), l, c) for o, h, l, c in _P]
    a_flat = [r if i != 8 else (r[0], 2404.5, r[2], r[3]) for i, r in enumerate(_A)]
    expiry_post = _flat(2403.0, 12)
    double_b = [r if i != 9 else (r[0], 2420.8, r[2], r[3]) for i, r in enumerate(_B)]
    sl_run = _CONFIRM + [(2405.4, 2405.8, 2403.0, 2403.2), (2403.2, 2403.5, 2400.6, 2400.9), (2400.9, 2401.2, 2398.7, 2399.1)] + _flat(2399.1, 7)
    return [
        ("valid BUY, runs to TP", _P + _A + _B + after),
        ("valid SELL, runs to TP", _mirror_rows(_P + _A + _B + after)),
        ("BUY invalidated: sweep extreme revisited", _P + _A + _B + invalidated),
        ("BUY rejected: no swing high inside A", p_ties + a_flat + _B + after),
        ("SELL expired: no confirmation within 12 M5 bars", _mirror_rows(_P + _A + _B + expiry_post)),
        ("double-sided sweep rejected", _P + _A + double_b + _flat(2403.0, 12)),
        ("valid BUY, stopped out", _P + _A + _B + sl_run),
    ]


def build() -> dict:
    rows: list = []
    labels = []
    t = START
    price = 2414.0
    rows += _filler_hour(price) * 3
    t += 3 * H1
    first_b_open = None
    for label, block in scenario_rows():
        block = _shift(block, round(price - block[0][0], 2))
        labels.append({"label": label, "p_open": iso(t), "a_open": iso(t + H1), "b_open": iso(t + 2 * H1)})
        if first_b_open is None:
            first_b_open = t + 2 * H1
        rows += block
        t += len(block) * M5
        price = block[-1][3]
        for _ in range(3):
            rows += _filler_hour(price)
            t += H1
    bars = bars_from(START, rows)
    assert all(b.is_valid() for b in bars), "fixture produced invalid OHLC"
    return {
        "meta": {
            "symbol": "DEMO-XAUUSD", "fictional": True, "tick_size": TICK, "point": TICK, "digits": 2,
            "demo_spread": 0.20, "demo_start": iso(first_b_open + timedelta(minutes=30)),
            "note": "FICTIONAL deterministic prices for demonstration and tests. Not market data. Not a performance record.",
            "scenarios": labels,
        },
        "m5": [[iso(b.open_time), b.open, b.high, b.low, b.close] for b in bars],
    }


def main() -> int:
    data = build()
    DEMO_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    DEMO_FIXTURE.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {DEMO_FIXTURE} ({len(data['m5'])} M5 bars, {len(data['meta']['scenarios'])} scenarios)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
