"""FVG geometry and the user's 1%/50%/80% ladder, on fictional prices."""
from dataclasses import replace
from datetime import datetime

import pytest

from app.fastsweep import BUY, SELL, M15
from app.fvg import Gap, detect_gap, entry_ladder
from app.models import UTC, Bar, SymbolMeta
from app.fvg_orders import build_order_plan

T = datetime(2030, 1, 7, tzinfo=UTC)
META = SymbolMeta("TEST", 0.01, 0.01, 2, "test")


def candles():
    return (Bar(T, M15, 99, 100, 98, 99),
            Bar(T + M15, M15, 99, 112, 98, 111),
            Bar(T + 2 * M15, M15, 111, 112, 110, 111))


def test_bullish_gap_bounds_available_after_third_close():
    a, b, c = candles()
    gap = detect_gap(a, b, c, META.tick_size)
    assert (gap.direction, gap.bottom, gap.top, gap.midpoint) == (BUY, 100, 110, 105)
    assert gap.third.close_time == T + 3 * M15


def test_bearish_gap_is_mirrored():
    a, b, c = candles()
    def mirror(x):
        return replace(x, open=210 - x.open, high=210 - x.low, low=210 - x.high, close=210 - x.close)
    gap = detect_gap(mirror(a), mirror(b), mirror(c), META.tick_size)
    assert (gap.direction, gap.bottom, gap.top) == (SELL, 100, 110)


@pytest.mark.parametrize("change", ["gap", "invalid", "subtick", "touch"])
def test_gap_never_uses_missing_invalid_or_overlapping_candles(change):
    a, b, c = candles()
    if change == "gap":
        c = replace(c, open_time=c.open_time + M15)
    elif change == "invalid":
        b = replace(b, high=98)
    else:
        c = replace(c, low=100.005 if change == "subtick" else 100)
    assert detect_gap(a, b, c, META.tick_size) is None


@pytest.mark.parametrize("direction, expected", [(BUY, [109.90, 105.0, 102.0]), (SELL, [100.10, 105.0, 108.0])])
def test_ladder_depth_from_correct_edge(direction, expected):
    a, _, c = candles()
    levels = entry_ladder(Gap(direction, 100, 110, a, c), META)
    assert [x.percent for x in levels] == [1, 50, 80]
    assert [x.price for x in levels] == expected


@pytest.mark.parametrize("depths", [(0, 50, 80), (1, 50, 101), (1, 80, 50), (1, 50, 50), (1, 50), (1, float("nan"), 80)])
def test_invalid_ladder_rejected(depths):
    a, _, c = candles()
    with pytest.raises(ValueError):
        entry_ladder(Gap(BUY, 100, 110, a, c), META, depths)


def test_tick_rounding_does_not_move_entry_toward_near_edge():
    a, _, c = candles()
    gap = Gap(BUY, 100, 100.17, a, c)
    prices = [x.price for x in entry_ladder(gap, META)]
    assert prices == [100.16, 100.08, 100.03]
    with pytest.raises(ValueError, match="too narrow"):
        entry_ladder(replace(gap, top=100.02), META)


@pytest.mark.parametrize("side", [BUY, SELL])
def test_shared_stop_individual_rr2_and_combined_risk(side):
    a, _, c = candles()
    gap = Gap(side, 100, 110, a, c)
    orders = build_order_plan(gap, META, 30.0, lambda direction, entry, stop: abs(entry - stop) * 100,
                             volume_min=0.01, volume_max=100, volume_step=0.01)
    assert len({x.sl for x in orders}) == 1
    assert sum(x.planned_loss for x in orders) <= 30.0
    assert all(abs(x.tp - x.entry) / abs(x.entry - x.sl) >= 2 - 1e-9 for x in orders)
    assert all(x.planned_loss <= 10 + 1e-8 for x in orders)
    assert [x.percent for x in orders] == [1, 50, 80]


def test_minimum_lot_never_forces_risk_upward():
    a, _, c = candles()
    with pytest.raises(ValueError, match="minimum lot"):
        build_order_plan(Gap(BUY, 100, 110, a, c), META, 1, lambda *args: 1000,
                         volume_min=0.01, volume_max=10, volume_step=0.01)
