"""FastSweep-M15-M5-v1 (research replay only): rules, controls and outcomes on fictional fixtures."""
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app import strategy as crt
from app.fastsweep import (BANGKOK, BUY, M15, PROFILES, SELL, FastSweepConfig, bangkok_date, build_levels,
                           confirm_step, ema_last, evaluate_range, new_setup, trend_permits)
from app.fastsweep_replay import Costs, frequency, replay
from app.models import H1, M5, UTC, Bar, Quote, SymbolMeta, aggregate

META = SymbolMeta("TESTGOLD", 0.01, 0.01, 2, "test")
T0 = datetime(2030, 1, 7, 12, 0, tzinfo=UTC)  # Monday; 19:00 Bangkok
FAST = replace(PROFILES["rr1"], ema_fast=2, ema_slow=3, trend_min_candles=3)  # small warm-up for compact fixtures


def m15(t, o, h, low, c):
    """One M15 candle as three contiguous M5 bars that aggregate to exactly (o, h, low, c)."""
    return [Bar(t, M5, o, h, min(o, c), o), Bar(t + M5, M5, o, max(o, c), low, c), Bar(t + 2 * M5, M5, c, c, c, c)]


def block(t, p, outcome="tp", rr=1.0):
    """One hour: A, B (BUY sweep-and-return), C (confirm bar, entry bar, flat), D (flat). Returns M5 bars.
    Levels: B low p-0.1 -> SL p-0.12; entry Ask = (p+1.6)+0.2 = p+1.8; risk 1.92; TP = p+1.8+rr*1.92."""
    bars = m15(t, p + 0.5, p + 2, p, p + 1) + m15(t + M15, p + 1, p + 1.5, p - 0.1, p + 1.2)
    c = t + 2 * M15
    bars.append(Bar(c, M5, p + 1.2, p + 1.7, p + 1.1, p + 1.6))           # confirm: 1.2 <= 1.5 < 1.6
    tp = p + 1.8 + rr * 1.92
    if outcome == "tp":
        e = Bar(c + M5, M5, p + 1.6, tp + 0.05, p + 1.5, tp)
    elif outcome == "sl":
        e = Bar(c + M5, M5, p + 1.6, p + 1.65, p - 0.2, p - 0.15)
    elif outcome == "both":
        e = Bar(c + M5, M5, p + 1.6, tp + 0.05, p - 0.2, p + 1.0)
    else:  # none: stays open
        e = Bar(c + M5, M5, p + 1.6, p + 1.7, p + 1.5, p + 1.6)
    bars += [e, Bar(c + 2 * M5, M5, e.close, e.close, e.close, e.close)]
    bars += [Bar(t + 3 * M15 + k * M5, M5, e.close, e.close, e.close, e.close) for k in range(3)]
    return bars


def warmup(t, p):
    out = []
    for k in range(3):  # rising M15 closes so EMA2 > EMA3 (BUY permitted)
        c = p - 3 + k
        out += m15(t + k * M15, c - 0.3, c + 0.1, c - 0.4, c)
    return out


def series(n_blocks, outcome="tp", start=T0, rr=1.0, step=5.0, tail=0):
    bars = warmup(start - 3 * M15, 100)
    for k in range(n_blocks):
        o = outcome[k] if isinstance(outcome, list) else outcome
        bars += block(start + k * timedelta(hours=1), 100 + k * step, o, rr)
    last = bars[-1]
    bars += [Bar(last.close_time + k * M5, M5, last.close, last.close, last.close, last.close) for k in range(tail)]
    return bars


# ------------------------------------------------------------------ range (strict comparisons, mirrors CRT)
def bar15(t, o, h, low, c):
    return Bar(t, M15, o, h, low, c)


def test_sweep_needs_two_ticks_and_strictly_inside_close():
    a = bar15(T0, 101, 102, 100, 101.5)
    ok = evaluate_range(a, bar15(T0 + M15, 101, 101.5, 99.98, 100.5), 0.01, FAST)
    assert ok.direction == BUY
    assert evaluate_range(a, bar15(T0 + M15, 101, 101.5, 99.99, 100.5), 0.01, FAST).reason == "no_sweep"  # 1 tick
    assert evaluate_range(a, bar15(T0 + M15, 101, 101.5, 99.98, 100.0), 0.01, FAST).reason == "buy_sweep_close_not_inside_a"
    assert evaluate_range(a, bar15(T0 + M15, 101, 102.02, 99.98, 101), 0.01, FAST).reason == "double_sided_sweep"
    assert evaluate_range(a, bar15(T0 + 2 * M15, 101, 102.02, 101, 101.9), 0.01, FAST).reason == "noncontiguous_m15"
    assert evaluate_range(a, bar15(T0 + M15, 101.5, 102.02, 100.5, 102.0), 0.01, FAST).reason == "sell_sweep_close_not_inside_a"
    assert evaluate_range(a, bar15(T0 + M15, 101.5, 102.02, 100.5, 101.9), 0.01, FAST).direction == SELL


def test_range_predicates_mirror_crt_on_identical_prices():
    cases = [(100, 102, 99.98, 101.5, 100.5), (100, 102, 99.99, 101.5, 100.5), (100, 102, 99.98, 102.02, 101),
             (100, 102, 100.5, 102.02, 101.9), (100, 102, 100.5, 102.02, 102.0), (100, 102, 99.98, 101.5, 100.0)]
    for alow, ahigh, blow, bhigh, bclose in cases:
        f = evaluate_range(bar15(T0, 101, ahigh, alow, 101), bar15(T0 + M15, 101, bhigh, blow, bclose), 0.01, FAST)
        h = crt.evaluate_range(Bar(T0, H1, 101, ahigh, alow, 101), Bar(T0 + H1, H1, 101, bhigh, blow, bclose), 0.01,
                               crt.StrategyConfig() if hasattr(crt, "StrategyConfig") else __import__("app.config", fromlist=["x"]).StrategyConfig())
        assert (f.direction, f.reason) == (h.direction, h.reason)


# ------------------------------------------------------------------ aggregation and trend
def test_m15_aggregation_skips_gapped_groups():
    bars = m15(T0, 100, 101, 99, 100.5) + m15(T0 + M15, 100.5, 101, 100, 100.8)
    del bars[4]  # one missing M5 inside the 2nd M15
    out = aggregate(bars, M15)
    assert [b.open_time for b in out] == [T0]


def test_ema_seeded_with_sma_and_warmup_needs_50_contiguous_candles():
    assert ema_last([1, 2, 3], 3) == 2.0
    assert ema_last([1, 2, 3, 4], 3) == pytest.approx(3.0)  # 4*0.5 + 2*0.5
    cfg = PROFILES["rr1"]
    rising = [bar15(T0 + k * M15, 100 + k, 101 + k, 99 + k, 100.5 + k) for k in range(50)]
    assert trend_permits(rising[:49], cfg) == (None, "trend_warmup")
    assert trend_permits(rising, cfg)[0] == BUY
    falling = [bar15(T0 + k * M15, 200 - k, 201 - k, 199 - k, 199.5 - k) for k in range(50)]
    assert trend_permits(falling, cfg)[0] == SELL
    flat = [bar15(T0 + k * M15, 100, 101, 99, 100) for k in range(50)]
    assert trend_permits(flat, cfg) == (None, "trend_flat")


# ------------------------------------------------------------------ confirmation
def _setup():
    a = bar15(T0, 101, 102, 100, 101.5)
    b = bar15(T0 + M15, 101, 101.5, 99.9, 100.8)  # BUY; level = B high 101.5, sweep extreme 99.9
    return new_setup(a, b, BUY, "X")


def test_confirmation_only_after_b_close_and_needs_a_cross():
    s = _setup()
    assert confirm_step(s, Bar(T0 + M15 + M5, M5, 100.8, 101.6, 100.5, 101.55), FAST) == "pending"  # inside B: ignored
    assert confirm_step(s, Bar(s.b_close, M5, 100.8, 101.5, 100.5, 101.5), FAST) == "pending"       # 101.5 not > level
    assert confirm_step(s, Bar(s.b_close + M5, M5, 101.5, 101.7, 101.2, 101.6), FAST) == "confirmed"
    assert s.confirm_close == s.b_close + 2 * M5


def test_invalidation_wins_over_same_bar_confirmation_and_gaps_invalidate():
    s = _setup()
    assert confirm_step(s, Bar(s.b_close, M5, 100.8, 101.8, 99.9, 101.7), FAST) == "invalidated"
    assert s.reason == "sweep_extreme_revisited"
    g = _setup()
    assert confirm_step(g, Bar(g.b_close + M5, M5, 100.8, 101.8, 100.5, 101.7), FAST) == "invalidated"
    assert g.reason == "m5_continuity_lost"


def test_window_expires_after_three_bars():
    s = _setup()
    for k in range(3):
        st = confirm_step(s, Bar(s.b_close + k * M5, M5, 100.8, 101.0, 100.5, 100.9), FAST)
    assert st == "expired" and s.reason == "no_confirmation_within_window"


# ------------------------------------------------------------------ levels: Ask/Bid, outward rounding, 1:1 and 1:2
def test_buy_levels_use_ask_and_round_outward():
    s = _setup()
    s.status, s.confirm_close = "confirmed", s.b_close + M5
    q = Quote(s.confirm_close, 101.6, 101.83)
    for rr in (1.0, 2.0):
        lv, why = build_levels(s, q, q.time, META, replace(FAST, reward_risk=rr))
        assert why is None and lv.entry == 101.83 and lv.sl == 99.88       # 99.9 - 2 ticks
        assert lv.tp == pytest.approx(round(101.83 + rr * (101.83 - 99.88), 2))
        assert lv.reward_risk >= rr - 1e-9
    assert build_levels(s, Quote(s.confirm_close, 101.6, 102.2), s.confirm_close, META, FAST)[1] == "spread_too_wide"
    assert build_levels(s, Quote(s.confirm_close - M5, 101.6, 101.8), s.confirm_close, META, FAST)[1] == "quote_older_than_confirmation_close"
    assert build_levels(s, q, q.time + timedelta(seconds=31), META, FAST)[1] == "missed_confirmation_too_late"


def test_sell_levels_use_bid_and_round_outward():
    a = bar15(T0, 101, 102, 100, 101.5)
    s = new_setup(a, bar15(T0 + M15, 101.5, 102.05, 100.5, 101.2), SELL, "X")
    s.status, s.confirm_close = "confirmed", s.b_close + M5
    lv, why = build_levels(s, Quote(s.confirm_close, 100.401, 100.6), s.confirm_close, META, replace(FAST, reward_risk=2.0))
    assert why is None and lv.entry == 100.401 and lv.sl == 102.07         # 102.05 + 2 ticks
    assert lv.tp <= 100.401 - 2 * (102.07 - 100.401) and lv.reward_risk >= 2.0


# ------------------------------------------------------------------ replay: entries, outcomes, controls
def run(bars, cfg=FAST, costs=Costs(0.2, 0.05)):
    return replay(bars, META, cfg, costs, holdout_fraction=0.3)


def test_buy_signal_geometry_fill_and_tp():
    r = run(series(1))
    (sig,) = r["signals"]
    assert sig["entry"] == pytest.approx(101.8) and sig["sl"] == pytest.approx(99.88) and sig["tp"] == pytest.approx(103.72)
    assert sig["fill"] == pytest.approx(101.85) and sig["outcome"] == "tp"
    assert sig["r"] == pytest.approx(round((103.72 - 101.85) / 1.92, 4))   # quoted 1:1, simulated fill < 1R
    assert sig["created_utc"] == "2030-01-07T12:35:00Z"


def test_rr2_profile_targets_twice_the_risk():
    r = run(series(1, rr=2.0), cfg=replace(FAST, reward_risk=2.0))
    (sig,) = r["signals"]
    assert sig["tp"] == pytest.approx(101.8 + 2 * 1.92) and sig["quoted_rr"] >= 2.0 and sig["outcome"] == "tp"


def test_sl_and_same_bar_ambiguity():
    assert run(series(1, "sl"))["signals"][0]["outcome"] == "sl"
    amb = run(series(1, "both"))["signals"][0]
    assert amb["outcome"] == "ambiguous" and amb["r"] is None


def test_one_active_signal_blocks_the_next_and_expiry_marks_at_two_hours():
    r = run(series(3, "none", tail=40, step=0.5))  # small step: later blocks never reach block 1's TP/SL
    sigs, cands = r["signals"], r["candidates"]
    # block 2 (entry 13:35) is rejected while block 1 is active; block 1 expires at the 14:35 bar close, so block 3's
    # entry at the 14:35 open is accepted (entries are checked against the state at that open, i.e. the previous close)
    assert len(sigs) == 2
    assert [c["reason"] for c in cands if c["confirm_close"]] == [None, "active_signal", None]
    first = sigs[0]
    assert first["outcome"] == "expired" and first["outcome_time"] == "2030-01-07T14:35:00Z"  # created 12:35 + 2h


def test_period_end_leaves_signal_open():
    (sig,) = run(series(1, "none"))["signals"]
    assert sig["outcome"] == "open_at_end"


def test_cooldown_and_bangkok_daily_cap_count_only_accepted_signals():
    cool = run(series(3), cfg=replace(FAST, cooldown_minutes=90))
    assert [c["reason"] for c in cool["candidates"] if c["confirm_close"]] == [None, "cooldown", None]
    # signals at 12:35, 13:35, ..., 17:35 UTC; Bangkok date rolls at 17:00 UTC
    cap = run(series(6), cfg=replace(FAST, max_signals_per_day=2))
    days = [bangkok_date(datetime.fromisoformat(s["created_utc"].replace("Z", "+00:00"))) for s in cap["signals"]]
    assert days == ["2030-01-07", "2030-01-07", "2030-01-08"]
    assert [c["reason"] for c in cap["candidates"] if c["confirm_close"]].count("daily_cap") == 3


def test_daily_table_keeps_zero_and_partial_dates():
    r = run(series(1))
    f = frequency(r["daily"])
    assert r["daily"][0]["date"] == "2030-01-07" and r["daily"][0]["signals"] == 1
    assert f["covered_dates_ge_12h"]["dates"] == 0 and f["partial_dates"] == ["2030-01-07"]


def test_no_future_bars_change_earlier_decisions():
    full = series(4, ["tp", "sl", "none", "tp"], tail=30)
    whole = run(full)
    cut = full[: len(full) // 2]
    part = run(cut)
    end = cut[-1].close_time
    for c in part["candidates"]:
        if c["status"] not in ("pending_at_end",) and c["confirm_close"] is None or (
                c["confirm_close"] and datetime.fromisoformat(c["confirm_close"].replace("Z", "+00:00")) + M5 <= end):
            twin = next(x for x in whole["candidates"] if x["key"] == c["key"])
            assert (twin["status"], twin["reason"]) == (c["status"], c["reason"])


def test_config_rejects_unapproved_ratios_and_spreads():
    with pytest.raises(ValueError):
        replace(PROFILES["rr1"], reward_risk=0.5).validate()
    with pytest.raises(ValueError):
        replace(PROFILES["rr1"], max_spread_price=0.6).validate()
    with pytest.raises(ValueError):
        run(series(1), costs=Costs(0.6, 0.05))
    assert PROFILES["rr2"].version == "FastSweep-M15-M5-v1-RR2" and BANGKOK.utcoffset(None) == timedelta(hours=7)
