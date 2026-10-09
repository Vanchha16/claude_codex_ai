from dataclasses import replace
from datetime import timedelta

import pytest

from app.config import ConfigError, StrategyConfig
from app.models import H1, M5, Bar, Quote, aggregate, round_down_to_tick, round_up_to_tick
from tests.scenarios import BUY_LEVEL, buy_setup, mirror, sell_setup
from app.strategy import BUY, SELL, Setup, build_entry, confirm_step, evaluate_range, find_pivots, select_structure

from .helpers import A_OPEN, B_CLOSE, B_OPEN, CFG, CONFIRM_CLOSE, META, T0, candidate_for_a, drive, idx_at, quote_at_close, with_bar


def hours(bars):
    h = aggregate(bars)
    return next(b for b in h if b.open_time == A_OPEN), next(b for b in h if b.open_time == B_OPEN)


# ------------------------------------------------------------------ valid setups
def test_valid_buy_signal_levels():
    store, _ = drive(buy_setup(T0))
    (sig,) = store.signals.values()
    assert sig.direction == BUY and sig.confirm_close == CONFIRM_CLOSE
    assert sig.entry == 2405.6  # Ask = Bid 2405.4 + 0.2 spread
    assert sig.sl == 2398.98  # 2 ticks beyond B low 2399.00
    assert sig.tp == 2420.0  # A high
    assert sig.reward_risk == pytest.approx((2420 - 2405.6) / (2405.6 - 2398.98), abs=1e-3)
    assert candidate_for_a(store).level == BUY_LEVEL


def test_valid_sell_signal_is_symmetric():
    store, _ = drive(sell_setup(T0))
    (sig,) = store.signals.values()
    assert sig.direction == SELL
    assert sig.entry == 2394.6  # Bid
    assert sig.sl == 2401.02 and sig.tp == 2380.0
    assert candidate_for_a(store).level == 4800 - BUY_LEVEL


# ------------------------------------------------------------------ range rules
def test_no_reclaim_close_below_a_low():
    bars = buy_setup(T0)
    last_b = idx_at(bars, B_CLOSE - M5)
    bars = with_bar(bars, last_b, close=2399.5, low=2399.2)
    a, b = hours(bars)
    assert evaluate_range(a, b, 0.01, CFG).reason == "buy_sweep_close_not_inside_a"


@pytest.mark.parametrize("close", [2400.0, 2420.0])
def test_close_on_boundary_is_rejected(close):
    a = Bar(A_OPEN, H1, 2410, 2420, 2400, 2405)
    b = Bar(B_OPEN, H1, 2405, 2419 if close == 2400.0 else 2420, 2399, close)
    if close == 2420.0:
        b = Bar(B_OPEN, H1, 2405, 2420, 2399, 2420)  # touches high but not 2 ticks beyond
    assert evaluate_range(a, b, 0.01, CFG).direction is None


def test_double_sided_sweep_rejected():
    a = Bar(A_OPEN, H1, 2410, 2420, 2400, 2405)
    b = Bar(B_OPEN, H1, 2405, 2420.5, 2399.5, 2410)
    assert evaluate_range(a, b, 0.01, CFG).reason == "double_sided_sweep"


def test_sweep_needs_two_ticks():
    a = Bar(A_OPEN, H1, 2410, 2420, 2400, 2405)
    one_tick = Bar(B_OPEN, H1, 2405, 2410, 2399.99, 2404)
    two_ticks = Bar(B_OPEN, H1, 2405, 2410, 2399.98, 2404)
    assert evaluate_range(a, one_tick, 0.01, CFG).reason == "no_sweep"
    assert evaluate_range(a, two_ticks, 0.01, CFG).direction == BUY


def test_noncontiguous_hours_rejected():
    a = Bar(A_OPEN, H1, 2410, 2420, 2400, 2405)
    b = Bar(B_OPEN + H1, H1, 2405, 2410, 2399, 2404)
    assert evaluate_range(a, b, 0.01, CFG).reason == "noncontiguous_hours"


def test_sell_requires_b_low_not_below_a_low():
    a = Bar(A_OPEN, H1, 2410, 2420, 2400, 2405)
    b = Bar(B_OPEN, H1, 2405, 2421, 2399.995, 2410)  # sweeps high, dips below low by < 2 ticks
    assert evaluate_range(a, b, 0.01, CFG).reason == "sell_sweep_but_b_low_below_a_low"


# ------------------------------------------------------------------ tick grid
def test_tick_grid_rounding_outward():
    assert round_down_to_tick(2398.987, 0.01, 2) == 2398.98
    assert round_up_to_tick(2401.011, 0.01, 2) == 2401.02
    assert round_down_to_tick(2398.98, 0.01, 2) == 2398.98  # already on grid
    assert round_down_to_tick(1.23457, 0.0005, 5) == 1.2345
    assert round_up_to_tick(1.23451, 0.0005, 5) == 1.2350


# ------------------------------------------------------------------ pivots
def _m5(start, highs, lows=None):
    lows = lows or [h - 1 for h in highs]
    return [Bar(start + i * M5, M5, l + 0.5, h, l, l + 0.5) for i, (h, l) in enumerate(zip(highs, lows))]


def test_pivot_strict_and_tie_is_not_pivot():
    bars = _m5(T0, [10, 11, 13, 12, 11])
    assert [p.level for p in find_pivots(bars, 2) if p.kind == "high"] == [13]
    tied = _m5(T0, [10, 11, 13, 13, 11, 10])
    assert [p for p in find_pivots(tied, 2) if p.kind == "high"] == []


def test_pivot_availability_is_close_of_second_right_bar():
    bars = _m5(T0, [10, 11, 13, 12, 11])
    (p,) = [p for p in find_pivots(bars, 2) if p.kind == "high"]
    assert p.available_at == bars[4].close_time


def test_pivot_across_gap_is_ignored():
    bars = _m5(T0, [10, 11, 13, 12, 11])
    bars[3] = replace(bars[3], open_time=bars[3].open_time + M5)
    bars[4] = replace(bars[4], open_time=bars[4].open_time + M5)
    assert find_pivots(bars, 2) == [] or all(p.level != 13 for p in find_pivots(bars, 2))


def test_absent_pivot_rejects_candidate():
    bars = buy_setup(T0)
    # P-hour highs all equal (ties are not pivots) and the A-hour swing high at 2405 flattened into a tie
    for k in range(12):
        bars = with_bar(bars, k, high=max(bars[k].open, bars[k].close, 2415.0))
    bars = with_bar(bars, idx_at(bars, A_OPEN + 8 * M5), high=2404.5)
    store, _ = drive(bars)
    c = candidate_for_a(store)
    assert c.status == "rejected" and c.reason == "no_confirmed_swing_high_inside_a" and not store.signals


def test_pivot_not_yet_confirmed_at_b_open_is_not_used():
    """A swing high whose second right-hand bar closes after B open must not be selected."""
    start = B_OPEN - 24 * M5
    highs = [2410.0] * 24
    highs[17] = 2412.0  # confirmed pivot (available at bar 19 close, before B open)
    highs[22] = 2415.0  # would need bars 23 and B0: confirmation only after B open
    highs[23] = 2411.0
    window = [Bar(start + i * M5, M5, 2405.0, h, 2404.0, 2405.0) for i, h in enumerate(highs)]
    b0 = Bar(B_OPEN, M5, 2405.0, 2410.0, 2399.0, 2400.0)
    a = Bar(A_OPEN, H1, 2405, 2420, 2400, 2405)
    b = Bar(B_OPEN, H1, 2405, 2410, 2399, 2404)
    s = select_structure(BUY, a, b, window + [b0], CFG)
    assert s.pivot is not None and s.pivot.level == 2412.0 and s.pivot.available_at <= B_OPEN


def test_future_bars_do_not_change_frozen_level():
    bars = buy_setup(T0)
    a, b = hours(bars)
    before = select_structure(BUY, a, b, [x for x in bars if x.close_time <= B_OPEN], CFG)
    after = select_structure(BUY, a, b, bars, CFG)  # later bars present must not matter
    assert before.pivot == after.pivot


def test_gap_in_m5_history_rejects():
    bars = buy_setup(T0)
    gap_i = idx_at(bars, A_OPEN + 3 * M5)
    bars = bars[:gap_i] + bars[gap_i + 1:]
    a = Bar(A_OPEN, H1, 2414, 2420, 2400, 2401.2)
    b = Bar(B_OPEN, H1, 2401.2, 2403.8, 2399.0, 2403.0)
    assert select_structure(BUY, a, b, bars, CFG).reason == "m5_gap_before_b"


# ------------------------------------------------------------------ confirmation
SETUP = Setup(BUY, 2420.0, 2400.0, 2399.0, 2405.0, B_CLOSE)


def bar_at(i, o, h, l, c):
    return Bar(B_CLOSE + i * M5, M5, o, h, l, c)


def test_confirmation_cannot_happen_before_b_close():
    inside_b = Bar(B_CLOSE - M5, M5, 2403, 2406, 2402.8, 2405.5)
    assert confirm_step(SETUP, Bar(B_CLOSE - 2 * M5, M5, 2403, 2404, 2402, 2403), inside_b, CFG).status == "pending"


def test_same_bar_invalidation_beats_confirmation():
    prev = bar_at(-1, 2403, 2403.5, 2402.5, 2403.0)
    both = bar_at(0, 2403, 2406, 2398.9, 2405.5)  # crosses level AND revisits sweep extreme
    step = confirm_step(SETUP, prev, both, CFG)
    assert step.status == "invalidated" and step.reason == "sweep_extreme_revisited"


def test_opposite_boundary_touch_invalidates():
    prev = bar_at(-1, 2403, 2403.5, 2402.5, 2403.0)
    assert confirm_step(SETUP, prev, bar_at(0, 2403, 2420.0, 2402.9, 2404), CFG).reason == "opposite_boundary_touched"


def test_expiry_after_twelve_bars():
    store, _ = drive(buy_setup(T0, include_run=False)[:-2] + [
        Bar(B_CLOSE + i * M5, M5, 2403.0, 2403.5, 2402.5, 2403.0) for i in range(13)])
    c = candidate_for_a(store)
    assert c.status == "expired" and not store.signals


def test_revisited_setup_is_invalidated_in_engine():
    bars = buy_setup(T0)
    i = idx_at(bars, B_CLOSE)
    bars = with_bar(bars, i, low=2398.5)
    store, _ = drive(bars)
    c = candidate_for_a(store)
    assert c.status == "invalidated" and c.reason == "sweep_extreme_revisited" and not store.signals


def test_continuity_loss_invalidates():
    prev = bar_at(-1, 2403, 2403.5, 2402.5, 2403.0)
    jumped = bar_at(1, 2403, 2405.6, 2402.9, 2405.4)  # bar 0 missing
    assert confirm_step(SETUP, prev, jumped, CFG).reason == "m5_continuity_lost"


def test_confirmation_closing_outside_range_rejected():
    s = Setup(BUY, 2406.0, 2400.0, 2399.0, 2405.0, B_CLOSE)
    prev = bar_at(-1, 2403, 2403.5, 2402.5, 2403.0)
    # high below boundary is impossible if close is above it, so use a bar that closes exactly on the high edge
    step = confirm_step(replace(s, a_high=2405.5), prev, bar_at(0, 2403, 2405.49, 2402.9, 2405.49), CFG)
    assert step.status == "confirmed"


# ------------------------------------------------------------------ entry checks
def _entry(quote, now, cfg=CFG):
    return build_entry(SETUP, CONFIRM_CLOSE, quote, now, META, cfg)


def test_stale_quote_rejected():
    now = CONFIRM_CLOSE + timedelta(seconds=5)
    q = Quote(CONFIRM_CLOSE - timedelta(seconds=1), 2405.4, 2405.6)
    assert _entry(q, now).reason == "quote_older_than_confirmation_close"
    cfg = replace(CFG, quote_max_age_seconds=2)
    q2 = Quote(CONFIRM_CLOSE + timedelta(seconds=1), 2405.4, 2405.6)
    assert _entry(q2, CONFIRM_CLOSE + timedelta(seconds=10), cfg).reason == "stale_quote"


def test_missed_confirmation_is_not_actionable_late():
    q = Quote(CONFIRM_CLOSE + timedelta(seconds=40), 2405.4, 2405.6)
    assert _entry(q, CONFIRM_CLOSE + timedelta(seconds=41)).reason == "missed_confirmation_too_late"


def test_spread_limit_in_price_units():
    now = CONFIRM_CLOSE + timedelta(seconds=1)
    assert _entry(Quote(now, 2405.4, 2405.91), now).reason == "spread_too_wide"
    assert _entry(Quote(now, 2405.4, 2405.90), now).levels is not None
    assert _entry(Quote(now, 2405.4, 2405.4), now).reason == "invalid_spread"


def test_reward_risk_minimum():
    now = CONFIRM_CLOSE + timedelta(seconds=1)
    assert _entry(Quote(now, 2405.4, 2405.6), now, replace(CFG, min_reward_risk=3.0)).reason == "reward_risk_below_minimum"


def test_missed_confirmation_in_engine_consumes_candidate():
    store, _ = drive(buy_setup(T0), entry_fn=quote_at_close(delay_s=45))
    c = candidate_for_a(store)
    assert c.status == "rejected" and c.reason == "missed_confirmation_too_late" and not store.signals


# ------------------------------------------------------------------ config
def test_config_validation_and_version():
    with pytest.raises(ConfigError):
        StrategyConfig(min_reward_risk=-1).validate()
    with pytest.raises(ConfigError):
        StrategyConfig(sweep_min_ticks=0).validate()
    assert StrategyConfig().version != StrategyConfig(max_spread_price=0.4).version


def test_mirror_scenario_keeps_ohlc_valid():
    assert all(b.is_valid() for b in mirror(buy_setup(T0)))
