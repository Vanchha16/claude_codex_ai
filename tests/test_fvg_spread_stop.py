"""Spread-aware common stop for the dual engines (M5: task 20261009-103608, M15: task 20261009-110034) on FICTIONAL fixtures: pure levels, the live M5/M15 decision,
sizing and a fake MT5 broker only. Nothing real is sent; no MT5 terminal, Telegram or live store is touched."""
import math
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace as NS

import pytest

from app.delivery import format_fvg_basket
from app.fastsweep import BUY, SELL
from app.fvg import (PROFILES, Gap, base_stop, basket_levels, spread_aware_levels, spread_aware_stop, spread_ticks,
                     stop_within_spread)
from app.fvg_dual import DUAL_PROFILE, DualFvgConfig, replay_dual
from app.fvg_execution import ExecutionJournal, MT5FvgExecutor
from app.fvg_guide import dual_record_view
from app.fvg_orders import build_order_plan
from app.fvg_replay import Costs
from app.models import Bar, Quote, SymbolMeta

from .test_fvg import T
from .test_fvg_dual import CURRENT, Env, m5_gap_series
from .test_fvg_engine import scenario
from .test_fvg_execution import Broker, policy

CFG = PROFILES["rr2"]
XAU = SymbolMeta("XAUUSD", 0.01, 0.01, 2, "mt5")
EXAMPLE = Gap(BUY, 4172.68, 4175.02, None, None)  # the 2026-10-09 02:45Z M5 zone that was refused (spread 0.49)
FIXED_M5 = DualFvgConfig(stop_policy=(("M15", "fixed"), ("M5", "fixed")))  # both fixed: rollback/comparison policy
M5_ONLY = DualFvgConfig(stop_policy=(("M15", "fixed"), ("M5", "spread_aware")))  # the @a2d893f0 configuration


def mirror(bars, k=240.0):
    """Price-mirrored copy (p -> k - p): a rising BUY scenario becomes a falling SELL one with the same geometry."""
    return [Bar(b.open_time, b.tf, k - b.open, k - b.low, k - b.high, k - b.close) for b in bars]


def m15_bars():
    bars, _, tc = scenario()
    return [b for b in bars if b.close_time <= tc], tc


def entries(legs):
    return [(l.number, l.entry) for l in legs]


# ------------------------------------------------------------------ pure levels
def test_exact_buy_example_moves_the_stop_two_ticks_and_keeps_the_entries():
    base_sl, base_legs = basket_levels(EXAMPLE, XAU, CFG)
    assert base_sl == 4172.66 and [l.entry for l in base_legs] == [4174.99, 4173.85, 4173.14]
    assert "leg 3 stop distance 0.48" in stop_within_spread(base_sl, entries(base_legs), 0.49, CFG, 0.01)
    plan = spread_aware_levels(EXAMPLE, XAU, CFG, 0.49)
    assert (plan.sl, plan.base_sl, plan.moved_ticks, plan.policy) == (4172.64, 4172.66, 2, "spread_aware")
    assert [l.entry for l in plan.legs] == [4174.99, 4173.85, 4173.14]          # entries unchanged
    assert [l.tp for l in plan.legs] == [4179.69, 4176.27, 4174.14]             # each TP = entry + 2 x its new risk
    assert round(plan.legs[2].entry - plan.sl, 2) == 0.50                       # = spread 0.49 + 1 tick
    assert stop_within_spread(plan.sl, entries(plan.legs), 0.49, CFG, 0.01) is None
    for l in plan.legs:
        assert math.isclose(l.tp - l.entry, 2 * (l.entry - plan.sl), abs_tol=1e-9)


def test_mirror_sell_moves_the_stop_up_by_the_minimum_ticks():
    gap = Gap(SELL, 4172.68, 4175.02, None, None)
    base_sl, base_legs = basket_levels(gap, XAU, CFG)
    assert base_sl == 4175.04 and [l.entry for l in base_legs] == [4172.71, 4173.85, 4174.56]
    plan = spread_aware_levels(gap, XAU, CFG, 0.49)
    assert (plan.sl, plan.moved_ticks) == (4175.06, 2) and [l.entry for l in plan.legs] == [4172.71, 4173.85, 4174.56]
    assert [l.tp for l in plan.legs] == [4168.01, 4171.43, 4173.56]
    assert round(plan.sl - plan.legs[2].entry, 2) == 0.50
    assert stop_within_spread(plan.sl, entries(plan.legs), 0.49, CFG, 0.01) is None


def test_no_adjustment_when_the_base_stop_already_passes():
    plan = spread_aware_levels(EXAMPLE, XAU, CFG, 0.20)
    assert (plan.sl, plan.moved_ticks) == (4172.66, 0) and (plan.sl, plan.legs) == basket_levels(EXAMPLE, XAU, CFG)
    assert spread_aware_levels(EXAMPLE, XAU, CFG, 0.47).moved_ticks == 0  # 0.48 >= 0.47 + 1 tick: equality passes


def test_fractional_and_float_noisy_spreads_round_up_to_whole_ticks():
    assert spread_ticks(4175.79 - 4175.30, 0.01) == 49                      # 0.48999999999978 -> 49 ticks
    assert spread_ticks(0.49 + 1e-12, 0.01) == 49
    assert spread_ticks(0.4905, 0.01) == 50                                 # a fractional spread never shrinks room
    assert spread_aware_levels(EXAMPLE, XAU, CFG, 4175.79 - 4175.30).sl == 4172.64
    assert spread_aware_levels(EXAMPLE, XAU, CFG, 0.4905).sl == 4172.63
    coarse = SymbolMeta("COARSE", 0.05, 0.01, 2, "test")                   # a 0.05 tick grid
    plan = spread_aware_levels(Gap(BUY, 100.0, 102.0, None, None), coarse, CFG, 0.52)
    assert [l.entry for l in plan.legs] == [101.95, 101.0, 100.4] and plan.base_sl == 99.9
    assert plan.sl == 99.8 and round(plan.sl / 0.05, 9) == round(plan.sl / 0.05)  # 11 + 1 ticks below 100.40
    assert spread_aware_stop(SELL, 102.1, [(1, 100.05)], 0.52, 1, 0.05, 2) == 102.1  # base already farther: kept


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.01, True, None])
def test_invalid_spread_is_refused_never_replaced(bad):
    with pytest.raises(ValueError, match="spread"):
        spread_aware_levels(EXAMPLE, XAU, CFG, bad)


# ------------------------------------------------------------------ provenance / version
def test_policy_is_part_of_the_dual_version_and_validated():
    assert dict(DUAL_PROFILE.stop_policy) == {"M15": "spread_aware", "M5": "spread_aware"}   # task 20261009-110034
    assert len({DUAL_PROFILE.version, FIXED_M5.version, M5_ONLY.version}) == 3
    assert M5_ONLY.version.endswith("@a2d893f0") and DUAL_PROFILE.version.endswith("@dc9ff475")
    assert {DUAL_PROFILE.engine_version(e) for e in ("M15", "M5")} == {"FVG-Immediate-M15-v2-RR2@dc9ff475",
                                                                         "FVG-Immediate-M5-v2-RR2@dc9ff475"}
    assert all(v.startswith("spread-aware") for v in DUAL_PROFILE.scopes()["stop_policy"].values())
    assert M5_ONLY.scopes()["stop_policy"]["M15"].startswith("fixed")
    with pytest.raises(ValueError, match="stop_policy"):
        DualFvgConfig(stop_policy=(("M15", "fixed"), ("M5", "wider"))).validate()
    with pytest.raises(ValueError, match="stop_policy"):
        DualFvgConfig(stop_policy=(("M5", "spread_aware"),)).validate()


# ------------------------------------------------------------------ live decision (fake store, alert-only)
def test_live_m5_adjusts_the_stop_and_stores_one_consistent_plan(tmp_path):
    env = Env(tmp_path)
    bars, tc = m5_gap_series()            # M5 BUY zone 116.60-117.80: leg 3 at 116.84, base SL 116.58 (0.26 away)
    env.run(bars, delay=1, spread=0.4)
    [b] = env.baskets()
    assert b["engine"] == "M5" and b["sl"] == 116.43 and b["version"] == DUAL_PROFILE.engine_version("M5")
    assert b["stop"]["policy"] == "spread_aware" and (b["stop"]["base_sl"], b["stop"]["moved_ticks"]) == (116.58, 15)
    assert math.isclose(b["stop"]["spread"], 0.4) and b["stop"]["quote_time"]
    assert all(l["sl"] == 116.43 for l in b["legs"]) and [l["entry"] for l in b["legs"]] == [117.78, 117.2, 116.84]
    assert [l["tp"] for l in b["legs"]] == [120.48, 118.74, 117.66] and all(l["rr"] == 2.0 for l in b["legs"])
    text = format_fvg_basket(env.alerts[0])
    for l in b["legs"]:                   # the queued message shows exactly the stored levels
        assert f"Entry: {l['entry']:.2f}" in text and f"TP: {l['tp']:.2f}" in text
    assert text.count("SL: 116.43") == 3
    assert any("moved 15 tick(s) outward from 116.58" in m for _, m in env.events.log)


def test_without_the_policy_the_same_m5_gap_is_still_refused(tmp_path):
    env = Env(tmp_path)
    env.eng.dcfg = FIXED_M5
    bars, _ = m5_gap_series()
    env.run(bars, delay=1, spread=0.4)
    assert env.baskets() == []
    [s] = [x for x in env.store.list_setups(100) if x.meta.get("engine") == "M5" and x.status == "rejected"
           and (x.reason or "").startswith("stop_within_spread")]
    assert "leg 3 stop distance 0.26" in s.reason


@pytest.mark.parametrize("cfg", [M5_ONLY, FIXED_M5], ids=["m5-only", "all-fixed"])
def test_explicit_fixed_m15_policy_keeps_its_previous_stop_and_refusal(tmp_path, cfg):
    env = Env(tmp_path)
    env.eng.dcfg = cfg                    # rollback/comparison: the previous fixed M15 stop
    bars, tc = m15_bars()
    env.run(bars, delay=1, spread=0.4)
    assert env.baskets() == []
    [m15] = [x for x in env.store.list_setups(100) if x.meta.get("engine") == "M15" and x.c_close == tc]
    assert m15.reason.startswith("stop_within_spread") and "leg 3 stop distance 0.26" in m15.reason
    env2 = Env(tmp_path / "ok")
    env2.eng.dcfg = cfg
    env2.run(bars, delay=1, spread=0.2)
    [b] = env2.baskets()
    assert b["engine"] == "M15" and b["stop"]["policy"] == "fixed" and b["stop"]["moved_ticks"] == 0
    sl, legs = basket_levels(Gap(b["direction"], b["bottom"], b["top"], None, None), env2.eng.meta, CFG)
    assert (b["sl"], [(l["entry"], l["tp"]) for l in b["legs"]]) == (sl, [(l.entry, l.tp) for l in legs])


@pytest.mark.parametrize("side", [BUY, SELL])
def test_live_m15_buy_and_sell_move_the_stop_where_the_fixed_stop_failed(tmp_path, side):
    env = Env(tmp_path)
    bars, tc = m15_bars()
    bars = bars if side == BUY else mirror(bars)  # SELL zone 122.20-123.40 (mirror of BUY 116.60-117.80)
    env.run(bars, delay=1, spread=0.4)
    [b] = env.baskets()
    assert b["engine"] == "M15" and b["direction"] == side and b["id"].startswith("FVG15-")
    assert b["version"] == DUAL_PROFILE.engine_version("M15") and b["decision_close"].startswith(tc.isoformat()[:16])
    st = b["stop"]
    assert st["policy"] == "spread_aware" and st["moved_ticks"] == 15 and math.isclose(st["spread"], 0.4)
    if side == BUY:
        assert (st["base_sl"], b["sl"]) == (116.58, 116.43)
        assert [l["entry"] for l in b["legs"]] == [117.78, 117.2, 116.84]       # original 1/50/80 % entries
        assert [l["tp"] for l in b["legs"]] == [120.48, 118.74, 117.66]
    else:
        assert (st["base_sl"], b["sl"]) == (123.42, 123.57)
        assert [l["entry"] for l in b["legs"]] == [122.22, 122.8, 123.16]
        assert [l["tp"] for l in b["legs"]] == [119.52, 121.26, 122.34]
    assert all(l["sl"] == b["sl"] and l["rr"] == 2.0 for l in b["legs"])
    assert round(abs(b["legs"][2]["entry"] - b["sl"]), 2) == 0.41                  # spread 0.40 + 1 tick, minimum move
    assert stop_within_spread(b["sl"], [(l["n"], l["entry"]) for l in b["legs"]], 0.4, CFG, 0.01) is None
    text = format_fvg_basket(env.alerts[0])
    assert text.splitlines()[0].startswith(f"M15 FVG") and text.count(f"SL: {b['sl']:.2f}") == 3
    assert any(f"moved 15 tick(s) outward from {st['base_sl']}" in m for _, m in env.events.log)


def test_m15_base_stop_that_already_passes_does_not_move(tmp_path):
    env = Env(tmp_path)
    bars, _ = m15_bars()
    env.run(bars, delay=1, spread=0.2)    # leg 3 is 0.26 from the base stop >= 0.20 + 1 tick
    [b] = env.baskets()
    assert b["engine"] == "M15" and b["stop"]["policy"] == "spread_aware" and b["stop"]["moved_ticks"] == 0
    assert b["sl"] == b["stop"]["base_sl"] == 116.58


def test_m5_numbers_are_unchanged_by_the_m15_switch(tmp_path):
    bars, _ = m5_gap_series()
    got = []
    for i, cfg in enumerate((DUAL_PROFILE, M5_ONLY)):
        env = Env(tmp_path / str(i))
        env.eng.dcfg = cfg
        env.run(bars, delay=1, spread=0.4)
        [b] = env.baskets()
        got.append((b["sl"], b["stop"]["moved_ticks"], [(l["entry"], l["sl"], l["tp"]) for l in b["legs"]]))
    assert got[0] == got[1] and got[0][0] == 116.43


def test_wide_spread_both_engines_keep_separate_baskets_messages_and_slots(tmp_path):
    from .test_fvg_dual import m15_then_m5_gap
    env = Env(tmp_path)
    bars, _, _ = m15_then_m5_gap()
    env.run(bars, delay=1, spread=0.4)
    got = env.baskets()
    assert [b["engine"] for b in got] == ["M15", "M5"] and len({b["id"] for b in got}) == 2
    assert all(b["stop"]["policy"] == "spread_aware" and b["stop"]["moved_ticks"] > 0 for b in got)
    heads = [format_fvg_basket(a).splitlines()[0] for a in env.alerts]
    assert heads[0].startswith("M15 FVG") and heads[1].startswith("M5 FVG") and len(env.alerts) == 2


def _decide_with(env, bars, quote_fn):
    for i, b in enumerate(bars):
        now = b.close_time + timedelta(seconds=1)
        env.eng.process_bar(bars, i, lambda c, x, b=b, now=now: (quote_fn(b, now), now), now)


@pytest.mark.parametrize("quote_fn, why", [
    (lambda b, now: Quote(now - timedelta(seconds=90), b.close, b.close + 0.4), "quote is 90s old"),
    (lambda b, now: Quote(now, b.close + 1, b.close), "quote invalid"),
    (lambda b, now: Quote(now, float("nan"), b.close), "quote invalid"),
])
def test_stale_or_invalid_quote_never_supplies_a_spread(tmp_path, quote_fn, why):
    env = Env(tmp_path)
    bars, _ = m5_gap_series()
    _decide_with(env, bars, quote_fn)
    assert env.baskets() == []
    [s] = [x for x in env.store.list_setups(100) if x.meta.get("engine") == "M5" and x.reason
           and x.reason.startswith("no_quote_for_eligibility_check")]
    assert why in s.reason


def test_missing_quote_is_still_refused(tmp_path):
    env = Env(tmp_path)
    bars, _ = m5_gap_series()
    _decide_with(env, bars, lambda b, now: None)
    assert env.baskets() == [] and any(x.reason == "no_quote_for_eligibility_check" for x in env.store.list_setups(100))


def test_spread_above_the_maximum_is_not_adjusted_and_still_refused(tmp_path):
    env = Env(tmp_path)
    bars, _ = m5_gap_series()
    env.run(bars, delay=1, spread=0.6)
    assert env.baskets() == []
    assert any((x.reason or "").startswith("stop_within_spread") and "spread 0.60" in x.reason
               for x in env.store.list_setups(100) if x.meta.get("engine") == "M5")


# ------------------------------------------------------------------ sizing and the fake broker
class GoldBroker(Broker):
    """Fake broker with a 100-unit contract (1 lot loses 100 account units per 1.00 move) at XAU-like prices."""

    def __init__(self, spreads=(0.49,)):
        super().__init__()
        self.ticks = [NS(bid=4175.30, ask=round(4175.30 + s, 2), time=T.timestamp(), time_msc=int(T.timestamp() * 1000))
                      for s in spreads]

    def order_calc_profit(self, side, symbol, volume, entry, stop):
        return -abs(entry - stop) * 100.0 * volume


def _executor(tmp_path, broker):
    journal = ExecutionJournal(tmp_path / "orders.sqlite")
    return journal, MT5FvgExecutor(lambda: broker, journal, policy(symbol="XAUUSD"))


def test_sizing_uses_the_adjusted_stop_and_never_exceeds_the_budget():
    plan = spread_aware_levels(EXAMPLE, XAU, CFG, 0.49)
    orders = build_order_plan(EXAMPLE, XAU, 10.0, lambda d, e, s: abs(e - s) * 100, volume_min=0.01, volume_max=100,
                              volume_step=0.01, levels=(plan.sl, plan.legs))
    assert [(o.entry, o.sl, o.tp, o.volume) for o in orders] == [
        (4174.99, 4172.64, 4179.69, 0.01), (4173.85, 4172.64, 4176.27, 0.02), (4173.14, 4172.64, 4174.14, 0.06)]
    assert [round(o.planned_loss, 2) for o in orders] == [2.35, 2.42, 3.0] and sum(o.planned_loss for o in orders) <= 10.0
    with pytest.raises(ValueError, match="minimum lot"):  # a wider stop never raises risk to reach the broker minimum
        build_order_plan(EXAMPLE, XAU, 10.0, lambda d, e, s: abs(e - s) * 100, volume_min=0.1, volume_max=100,
                         volume_step=0.01, levels=(plan.sl, plan.legs))


@pytest.mark.parametrize("levels, match", [
    ((4172.67, None), "inside the base stop"),
    ((4172.645, None), "tick grid"),
    ((float("nan"), None), "invalid"),
    ((4172.64, "tp+1"), "do not match"),
])
def test_external_levels_are_verified_never_trusted(levels, match):
    sl, legs = levels
    plan = spread_aware_levels(EXAMPLE, XAU, CFG, 0.49)
    legs = plan.legs if legs is None else tuple(replace(l, tp=l.tp + 1) for l in plan.legs)
    with pytest.raises(ValueError, match=match):
        build_order_plan(EXAMPLE, XAU, 10.0, lambda d, e, s: abs(e - s) * 100, volume_min=0.01, volume_max=100,
                         volume_step=0.01, levels=(sl, legs))


def test_broker_requests_match_the_stored_plan_and_restart_is_idempotent(tmp_path):
    broker = GoldBroker()
    journal, ex = _executor(tmp_path, broker)
    plan = spread_aware_levels(EXAMPLE, XAU, CFG, 0.49)
    out = ex.submit("m5x", EXAMPLE, XAU, T, T + timedelta(hours=2), comment_tag="FVG5", engine="M5",
                    levels=(plan.sl, plan.legs), stop=plan.provenance())
    assert out["state"] == "submitted" and out["stop"]["moved_ticks"] == 2 and out["stop"]["base_sl"] == 4172.66
    assert [(r["price"], r["sl"], r["tp"], r["volume"]) for r in broker.requests] == [
        (4174.99, 4172.64, 4179.69, 0.01), (4173.85, 4172.64, 4176.27, 0.02), (4173.14, 4172.64, 4174.14, 0.06)]
    assert [(l["entry"], l["sl"], l["tp"]) for l in out["legs"]] == [(r["price"], r["sl"], r["tp"]) for r in broker.requests]
    again = ex.submit("m5x", EXAMPLE, XAU, T, T + timedelta(hours=2), comment_tag="FVG5", engine="M5",
                      levels=(plan.sl, plan.legs), stop=plan.provenance())
    assert again == out and len(broker.requests) == 3  # never rebuilt or resent
    journal.close()


def test_spread_widening_at_the_send_boundary_refuses_the_fixed_plan(tmp_path):
    broker = GoldBroker(spreads=(0.47, 0.49))   # decided/preflight at 0.47, the re-check right before the first send 0.49
    journal, ex = _executor(tmp_path, broker)
    plan = spread_aware_levels(EXAMPLE, XAU, CFG, 0.47)
    assert plan.moved_ticks == 0                # 0.48 >= 0.47 + 1 tick: no move was needed at the decision
    with pytest.raises(ValueError, match="leg 3: stop distance 0.48 is below spread 0.49"):
        ex.submit("m5y", EXAMPLE, XAU, T, T + timedelta(hours=2), comment_tag="FVG5", engine="M5",
                  levels=(plan.sl, plan.legs), stop=plan.provenance())
    assert broker.requests == [] and journal.get("m5y") is None  # nothing sent, no adjusted re-plan
    journal.close()


def test_base_stop_plan_is_refused_at_the_broker_like_before(tmp_path):
    broker = GoldBroker()
    journal, ex = _executor(tmp_path, broker)
    with pytest.raises(ValueError, match="leg 3: stop distance 0.48 is below spread 0.49"):
        ex.submit("legacy", EXAMPLE, XAU, T, T + timedelta(hours=2))  # no levels: the unchanged base stop
    assert broker.requests == []
    journal.close()


def test_live_m15_basket_message_guide_journal_and_broker_requests_agree(tmp_path):
    from .test_fvg_dual import META
    broker = Broker()
    journal = ExecutionJournal(tmp_path / "j.sqlite")
    holder = {}
    env = Env(tmp_path, executor_fn=lambda: (MT5FvgExecutor(lambda: broker, journal, policy(),
                                                            clock=lambda: holder["now"]), "ON"))
    bars, tc = m15_bars()
    for i, b in enumerate(bars):
        now = b.close_time + timedelta(seconds=1)
        holder["now"] = now
        broker.ticks = [NS(bid=b.close, ask=b.close + 0.4, time=now.timestamp(), time_msc=int(now.timestamp() * 1000))]
        broker.tick_calls = 0
        env.eng.process_bar(bars, i, lambda c, x, b=b, now=now: (Quote(now, b.close, b.close + 0.4), now), now)
    [b] = env.baskets()
    assert b["engine"] == "M15" and b["status"] == "orders_pending" and b["sl"] == 116.43
    ex_legs = b["execution"]["legs"]
    stored = [(l["entry"], l["sl"], l["tp"]) for l in b["legs"]]
    assert stored == [(l["entry"], l["sl"], l["tp"]) for l in ex_legs] == [(r["price"], r["sl"], r["tp"]) for r in broker.requests]
    assert [r["comment"] for r in broker.requests] == [f"FVG15-{b['plan_id']}-L{n}" for n in (1, 2, 3)]
    assert b["execution"]["stop"] == b["stop"] and b["execution"]["engine"] == "M15"
    assert sum(l["planned_loss"] for l in ex_legs) <= 10.0 + 1e-9
    text = format_fvg_basket(b)
    assert all(f"Entry: {e:.2f}" in text and f"TP: {t:.2f}" in text for e, _, t in stored) and text.count("SL: 116.43") == 3
    s = env.store.get_setup(b["setup_key"])
    v = dual_record_view(s, b, bars, CFG, META, tc + timedelta(minutes=1), CURRENT, dict(DUAL_PROFILE.stop_policy))
    assert v["levels"]["source"] == "basket" and v["levels"]["sl"] == 116.43 and v["levels"]["stop"] == b["stop"]
    assert [(l["entry"], l["tp"], l["volume"]) for l in v["levels"]["legs"]] == [(l["entry"], l["tp"], l["volume"]) for l in ex_legs]
    env.run(bars, delay=1, start=len(bars) - 1, spread=0.4)
    assert len(broker.requests) == 3      # the decided C is never decided or sent again
    journal.close()


def test_live_m5_basket_journal_and_broker_requests_agree(tmp_path):
    from .test_fvg_dual import META
    broker = Broker()
    journal = ExecutionJournal(tmp_path / "j.sqlite")
    holder = {}
    env = Env(tmp_path, executor_fn=lambda: (MT5FvgExecutor(lambda: broker, journal, policy(),
                                                            clock=lambda: holder["now"]), "ON"))
    bars, _ = m5_gap_series()
    for i, b in enumerate(bars):
        now = b.close_time + timedelta(seconds=1)
        holder["now"] = now
        broker.ticks = [NS(bid=b.close, ask=b.close + 0.4, time=now.timestamp(), time_msc=int(now.timestamp() * 1000))]
        broker.tick_calls = 0
        env.eng.process_bar(bars, i, lambda c, x, b=b, now=now: (Quote(now, b.close, b.close + 0.4), now), now)
    [b] = env.baskets()
    assert b["status"] == "orders_pending" and b["sl"] == 116.43 and META.name == "TEST"
    ex_legs = b["execution"]["legs"]
    stored = [(l["entry"], l["sl"], l["tp"]) for l in b["legs"]]
    assert stored == [(l["entry"], l["sl"], l["tp"]) for l in ex_legs] == [(r["price"], r["sl"], r["tp"]) for r in broker.requests]
    assert b["execution"]["stop"] == b["stop"] and sum(l["planned_loss"] for l in ex_legs) <= 10.0 + 1e-9
    journal.close()


# ------------------------------------------------------------------ replay and Guide
def test_replay_labels_its_assumed_spread_and_uses_the_same_policy():
    bars, _ = m5_gap_series()
    res = replay_dual(bars, SymbolMeta("TEST", 0.01, 0.01, 2, "test"), DUAL_PROFILE, Costs(0.4, 0.05))
    [b] = [x for x in res["baskets"] if x["engine"] == "M5"]
    assert b["sl"] == 116.43 and res["stop_policy"]["M5"] == "spread_aware"
    assert "assumed spread 0.4" in res["spread_note"] and "not historical spread validation" in res["spread_note"]
    fixed = replay_dual(bars, SymbolMeta("TEST", 0.01, 0.01, 2, "test"), FIXED_M5, Costs(0.4, 0.05))
    assert not [x for x in fixed["baskets"] if x["engine"] == "M5"]


def test_guide_shows_the_stored_stop_and_labels_the_preview_limitation(tmp_path):
    from .test_fvg_dual import META
    env = Env(tmp_path)
    bars, tc = m5_gap_series()
    env.run(bars, delay=1, spread=0.4)
    [b] = env.baskets()
    s = env.store.get_setup(b["setup_key"])
    v = dual_record_view(s, b, bars, CFG, META, tc + timedelta(minutes=1), CURRENT, dict(DUAL_PROFILE.stop_policy))
    assert v["levels"]["source"] == "basket" and v["levels"]["sl"] == 116.43 and v["levels"]["stop"]["moved_ticks"] == 15
    p = dual_record_view(s, None, bars, CFG, META, tc + timedelta(minutes=1), CURRENT, dict(DUAL_PROFILE.stop_policy))
    assert p["levels"]["source"] == "preview" and p["levels"]["sl"] == base_stop(Gap(BUY, 116.6, 117.8, None, None), META, CFG)
    assert "not stored" in p["levels"]["note"]
    m15, m15_tc = m15_bars()           # the M15 preview carries the same limitation now
    env15 = Env(tmp_path / "m15")
    env15.run(m15, delay=1, spread=0.4)
    s15 = next(x for x in env15.store.list_setups(100) if x.meta.get("engine") == "M15" and x.c_close == m15_tc)
    p15 = dual_record_view(s15, None, m15, CFG, META, m15_tc + timedelta(minutes=1), CURRENT, dict(DUAL_PROFILE.stop_policy))
    assert p15["levels"]["source"] == "preview" and "not stored" in p15["levels"]["note"]
    old = dual_record_view(s15, None, m15, CFG, META, m15_tc + timedelta(minutes=1), CURRENT, dict(M5_ONLY.stop_policy))
    assert "note" not in old["levels"]   # a fixed-policy engine needs no spread note
