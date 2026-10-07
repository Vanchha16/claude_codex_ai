from datetime import timedelta

import pytest

from app.config import DEMO_FIXTURE, StrategyConfig
from app.models import M5, Bar, Quote
from app.replay import Costs, load_fixture, replay
from app.scenarios import buy_setup, sell_setup

from .helpers import CONFIRM_CLOSE, META, T0, idx_at, with_bar

CFG = StrategyConfig()
OHLC = Costs(spread=0.2, slippage=0.05, source="ohlc-assumed")


def _pad(bars, n=40):
    """Quiet bars after the scenario so the replay has data after the outcome."""
    last = bars[-1]
    return bars + [Bar(last.close_time + i * M5, M5, last.close, last.close + 0.1, last.close - 0.1, last.close) for i in range(n)]


def test_buy_fill_is_next_open_plus_spread_and_slippage():
    bars = _pad(buy_setup(T0))
    r = replay(bars, META, CFG, OHLC)
    (s,) = r.signals
    nxt = bars[idx_at(bars, CONFIRM_CLOSE)]
    assert s["confirm_close"] == CONFIRM_CLOSE.isoformat().replace("+00:00", "Z")
    assert s["entry_quote"] == pytest.approx(nxt.open + 0.2)
    assert s["fill"] == pytest.approx(nxt.open + 0.25)
    assert s["outcome"] == "tp"


def test_sell_fill_uses_bid_minus_slippage_and_ask_exits():
    bars = _pad(sell_setup(T0))
    r = replay(bars, META, CFG, OHLC)
    (s,) = r.signals
    nxt = bars[idx_at(bars, CONFIRM_CLOSE)]
    assert s["entry_quote"] == pytest.approx(nxt.open)  # SELL enters at Bid
    assert s["fill"] == pytest.approx(nxt.open - 0.05)
    assert s["outcome"] == "tp"  # run low 2379.7 + 0.2 spread = Ask 2379.9 <= TP 2380


def test_sell_tp_not_hit_when_only_bid_touches():
    bars = _pad(sell_setup(T0))
    # make the lowest run bar reach 2379.9 on Bid: Ask (2380.1) never reaches TP 2380
    lows = [i for i, b in enumerate(bars) if b.low < 2380.0]
    for i in lows:
        bars = with_bar(bars, i, low=2379.9)
    r = replay(bars, META, CFG, OHLC)
    assert r.signals[0]["outcome"] != "tp"


def test_same_bar_tp_and_sl_is_ambiguous_and_excluded():
    bars = _pad(buy_setup(T0))
    i = idx_at(bars, CONFIRM_CLOSE)  # the fill bar
    bars = with_bar(bars, i, high=2420.5, low=2398.0)
    r = replay(bars, META, CFG, OHLC)
    (s,) = r.signals
    assert s["outcome"] == "ambiguous" and s["outcome_r"] is None
    seg = r.segments["development"] if r.segments["development"]["signals"] else r.segments["holdout"]
    assert seg["win_rate"] is None and "excludes ambiguous" in seg["win_rate_denominator"]


def test_replay_uses_no_future_data():
    """Truncating history right after the fill bar must not change the decision."""
    bars = _pad(buy_setup(T0))
    full = replay(bars, META, CFG, OHLC, holdout_fraction=0.01)
    cut = idx_at(bars, CONFIRM_CLOSE) + 1
    short = replay(bars[:cut], META, CFG, OHLC, holdout_fraction=0.01)
    assert short.signals[0]["entry_quote"] == full.signals[0]["entry_quote"]
    assert short.signals[0]["sl"] == full.signals[0]["sl"]
    assert short.signals[0]["outcome"] == "open_at_end"


def test_no_fill_without_next_observation():
    bars = buy_setup(T0, include_run=False)  # history ends exactly at the confirmation close
    r = replay(bars, META, CFG, OHLC)
    assert r.signals == []
    assert r.segments["development"]["reasons"].get("no_quote", 0) + r.segments["holdout"]["reasons"].get("no_quote", 0) == 1


def test_holdout_is_chronological_and_isolated():
    m5, meta, _ = load_fixture(DEMO_FIXTURE)
    full = replay(m5, meta, CFG, OHLC, holdout_fraction=0.30)
    split = full.split_at
    dev_only = [b for b in m5 if b.close_time.isoformat().replace("+00:00", "Z") <= split]
    dev = replay(dev_only, meta, CFG, OHLC, holdout_fraction=0.0001)
    full_dev = [s for s in full.signals if s["segment"] == "development"]
    dev_sigs = [s for s in dev.signals if s["outcome"] != "open_at_end"]
    assert [s["id"] for s in full_dev] == [s["id"] for s in dev_sigs]
    assert all(s["confirm_close"] < split for s in full_dev)
    assert all(s["confirm_close"] >= split for s in full.signals if s["segment"] == "holdout")


def test_demo_fixture_expected_scenarios():
    m5, meta, raw = load_fixture(DEMO_FIXTURE)
    assert raw["meta"]["fictional"] is True
    r = replay(m5, meta, CFG, OHLC)
    outcomes = [(s["direction"], s["outcome"]) for s in r.signals]
    assert outcomes == [("BUY", "tp"), ("SELL", "tp"), ("BUY", "sl")]
    reasons = {**r.segments["development"]["reasons"]}
    for k, v in r.segments["holdout"]["reasons"].items():
        reasons[k] = reasons.get(k, 0) + v
    for expected in ("sweep_extreme_revisited", "no_confirmed_swing_high_inside_a", "no_confirmation_within_window", "double_sided_sweep"):
        assert reasons.get(expected), expected


def test_tick_mode_entry_and_outcome():
    bars = _pad(buy_setup(T0))
    ticks = [Quote(CONFIRM_CLOSE + timedelta(seconds=2), 2405.5, 2405.7),
             Quote(CONFIRM_CLOSE + timedelta(minutes=20), 2412.0, 2412.2),
             Quote(CONFIRM_CLOSE + timedelta(minutes=40), 2420.0, 2420.2)]

    def tick_fn(start, end):
        return [q for q in ticks if start <= q.time <= end]
    r = replay(bars, META, CFG, Costs(0.2, 0.0, "ticks"), ticks_fn=tick_fn)
    (s,) = r.signals
    assert s["entry_quote"] == 2405.7 and s["outcome"] == "tp"
