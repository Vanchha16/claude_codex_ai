"""Independent M15 + M5 FVG engines (task 20261008-143801) on FICTIONAL fixtures: fake broker only, nothing real sent."""
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from app.active_strategy import parse_active_strategy
from app.delivery import format_fvg_basket
from app.fastsweep import BUY, M15, SELL
from app.fvg import PROFILES, detect_gap, qualify
from app.fvg_dual import (DUAL_PROFILE, ENGINES, DualFvgLiveEngine, Occupancy, admission, engine_bars, evaluate_c,
                          readiness, replay_dual)
from app.fvg_execution import MAGIC, ExecutionJournal, MT5FvgExecutor
from app.fvg_live import FvgStore, basket_is_open
from app.fvg_replay import Costs
from app.models import M5, UTC, Bar, Quote, SymbolMeta, aggregate, iso

from .test_fvg_engine import META, T0, scenario
from .test_fvg_execution import Broker, policy
from tests.conftest import fixture_factory

D = DUAL_PROFILE.validate()
R = D.rules


def m5_gap_series(warm=55, t0=T0, base=100.0):
    """Rising closed M5 candles, then an M5 A/B/C bullish FVG [base+16.6, base+17.8] closing at the returned time."""
    bars = []
    for k in range(warm):
        c = base + 0.3 * k
        bars.append(Bar(t0 + k * M5, M5, c - 0.2, c + 0.1, c - 0.3, c))
    ta = t0 + warm * M5
    o = base - 100
    bars += [Bar(ta, M5, 116.3 + o, 116.6 + o, 116.1 + o, 116.5 + o), Bar(ta + M5, M5, 116.5 + o, 120.5 + o, 116.4 + o, 120.3 + o),
             Bar(ta + 2 * M5, M5, 120.3 + o, 120.9 + o, 117.8 + o, 120.7 + o)]
    return bars, ta + 3 * M5


def m15_then_m5_gap():
    """The M15 scenario up to its C close, then an M5 A/B/C bullish gap [121.0, 122.5] a few M5 candles later."""
    bars, _, tc = scenario()
    bars = [b for b in bars if b.close_time <= tc]
    t = tc
    for o, h, l, c in [(120.7, 120.8, 120.5, 120.75), (120.75, 120.9, 120.6, 120.85),
                       (120.7, 121.0, 120.6, 120.9), (120.9, 125.0, 120.8, 124.9), (124.9, 125.5, 122.5, 125.3)]:
        bars.append(Bar(t, M5, o, h, l, c))
        t += M5
    return bars, tc, t


class Env:
    def __init__(self, tmp_path, executor_fn=None, account="acct-1", risk=10.0):
        self.store = FvgStore(tmp_path / "fvg.sqlite")
        self.events = NS(log=[])
        self.events.add_event = lambda kind, msg, level="info", at=None: self.events.log.append((kind, msg))
        self.alerts = []
        self.eng = DualFvgLiveEngine(D, META, self.store, self.events, "mt5", alert_fn=self.alerts.append,
                                     executor_fn=executor_fn or (lambda: (None, "automatic execution OFF")),
                                     account_fn=lambda: account, risk_fn=lambda: risk)

    def run(self, bars, delay=0.0, start=0, spread=0.2):
        """Feed each closed M5 bar once, deciding `delay` seconds after its close with a quote at its close."""
        for i in range(start, len(bars)):
            b = bars[i]
            now = b.close_time + timedelta(seconds=delay)
            self.eng.process_bar(bars, i, lambda c, x, b=b, now=now: (Quote(now, b.close, b.close + spread), now), now)

    def baskets(self):
        return sorted(self.store.baskets(limit=100), key=lambda b: b["placed_at"])


# ------------------------------------------------------------------ rules: own timeframe, own readiness
def test_each_engine_detects_only_its_own_timeframe_candles():
    bars, tc = m5_gap_series()
    gap, why = evaluate_c("M5", engine_bars(bars, "M5"), META, R)
    assert gap is not None and why is None and gap.direction == BUY and (gap.bottom, gap.top) == (116.6, 117.8)
    assert gap.third.close_time == tc
    a, b, c = bars[-3:]
    assert detect_gap(a, b, c, META.tick_size) is None          # the M15 rule never reads M5 candles
    assert detect_gap(a, b, c, META.tick_size, M5) is not None


def test_readiness_is_independent_m5_ready_while_m15_warms_up():
    bars, tc = m5_gap_series()
    r5, r15 = readiness("M5", bars, R, tc), readiness("M15", bars, R, tc)
    assert r5["ready"] and r5["run"] >= 50
    assert not r15["ready"] and r15["run"] < 50 and r15["ready_eta"]
    sc, _, c15 = scenario()
    sc = [b for b in sc if b.close_time <= c15]
    assert readiness("M15", sc, R, c15)["ready"]


def test_m5_history_gap_restarts_only_the_m5_run():
    bars, tc = m5_gap_series()
    broken = bars[:20] + bars[21:]  # one missing M5 candle
    gap, why = evaluate_c("M5", engine_bars(broken, "M5"), META, R)
    assert gap is not None and why == "trend_warmup"


# ------------------------------------------------------------------ live: immediate entry on qualification
def test_qualified_m5_gap_places_a_basket_at_c_without_retest_or_confirmation(tmp_path):
    env = Env(tmp_path)
    bars, tc = m5_gap_series()
    env.run(bars, delay=2)
    [b] = env.baskets()
    assert b["engine"] == "M5" and b["id"].startswith("FVG5-") and b["decision_close"] == iso(tc)
    assert b["status"] == "alert_only" and b["execution"]["state"] == "not_submitted"
    assert (b["bottom"], b["top"]) == (116.6, 117.8) and b["sl"] < b["bottom"] and len(b["legs"]) == 3
    assert all(l["tp"] > l["entry"] > b["sl"] for l in b["legs"]) and "retest_close" not in b
    assert env.alerts and env.alerts[0]["id"] == b["id"]
    assert "M5 FVG" in format_fvg_basket(b).splitlines()[0]


def test_m15_gap_places_a_basket_when_its_m15_c_closes(tmp_path):
    env = Env(tmp_path)
    bars, _, tc = scenario()
    bars = [b for b in bars if b.close_time <= tc]
    env.run(bars, delay=1)
    [b] = env.baskets()
    assert b["engine"] == "M15" and b["id"].startswith("FVG15-") and b["decision_close"] == iso(tc)


def test_old_or_pre_watermark_c_is_recorded_but_never_ordered(tmp_path):
    env = Env(tmp_path)
    bars, tc = m5_gap_series()
    env.run(bars, delay=31)  # > 30 s at the decision
    assert env.baskets() == []
    s = [x for x in env.store.list_setups(100) if x.status != "rejected" or x.reason.startswith("decision_too_old")]
    assert s and s[0].reason.startswith("decision_too_old")
    env2 = Env(tmp_path / "w")
    env2.eng.eligible_after = tc  # C closed AT the watermark, not strictly after it
    env2.run(bars, delay=1)
    assert env2.baskets() == [] and any(x.reason == "c_before_session_watermark" for x in env2.store.list_setups(100))


def test_each_c_is_decided_once_across_polls_and_restarts(tmp_path):
    env = Env(tmp_path)
    bars, tc = m5_gap_series()
    env.run(bars, delay=1)
    env.run(bars, delay=1, start=len(bars) - 1)  # the same close seen again
    restarted = Env.__new__(Env)
    restarted.store, restarted.events, restarted.alerts = env.store, env.events, []
    restarted.eng = DualFvgLiveEngine(D, META, env.store, env.events, "mt5", alert_fn=restarted.alerts.append,
                                      account_fn=lambda: "acct-1", risk_fn=lambda: 10.0)
    restarted.run(bars, delay=1, start=len(bars) - 1)
    assert len(env.baskets()) == 1 and restarted.alerts == []


def test_one_m15_and_one_m5_basket_coexist(tmp_path):
    env = Env(tmp_path)
    bars, tc15, t_end = m15_then_m5_gap()
    env.run(bars, delay=1)
    got = env.baskets()
    assert [b["engine"] for b in got] == ["M15", "M5"]
    assert all(basket_is_open(b, t_end) for b in got)  # two baskets, up to six legs, together


# ------------------------------------------------------------------ shared admission (live and replay use the same rule)
def occ(engine, minutes_ago, open_=True, risk=10.0, now=None):
    now = now or datetime(2030, 1, 8, 6, 0, tzinfo=UTC)
    return Occupancy(engine, now - timedelta(minutes=minutes_ago), open_, risk)


NOW = datetime(2030, 1, 8, 6, 0, tzinfo=UTC)  # 13:00 Bangkok


def test_one_open_basket_per_engine_and_the_other_engine_is_free():
    assert admission("M15", NOW, [occ("M15", 60)], D, 10.0) == "engine_basket_open"
    assert admission("M5", NOW, [occ("M15", 60)], D, 10.0) is None


def test_cooldown_is_per_engine():
    assert admission("M5", NOW, [occ("M5", 10, open_=False)], D, 10.0) == "cooldown"
    assert admission("M15", NOW, [occ("M5", 10, open_=False)], D, 10.0) is None
    assert admission("M5", NOW, [occ("M5", 30, open_=False)], D, 10.0) is None


def test_daily_cap_counts_both_engines_and_m15_wins_a_shared_last_slot():
    day = [occ("M15", 300, False), occ("M5", 240, False), occ("M15", 200, False)]
    assert admission("M15", NOW, day, D, 10.0) is None  # M15 decided first at the shared timestamp ...
    taken = day + [Occupancy("M15", NOW, True, 10.0)]
    assert admission("M5", NOW, taken, D, 10.0) == "daily_cap"  # ... so the M5 gap at the same time is rejected
    assert admission("M5", NOW, day, D, 10.0) is None


def test_unknown_or_larger_legacy_risk_is_never_assumed_zero():
    assert admission("M5", NOW, [occ("M15", 60, risk=None)], D, 10.0) is None  # unknown counts as one full budget
    assert admission("M5", NOW, [occ("M15", 60, risk=15.0)], D, 10.0) == "concurrent_risk_cap"


def test_open_legacy_v1_basket_occupies_the_m15_slot(tmp_path):
    env = Env(tmp_path)
    legacy = {"id": "FVG-legacy", "plan_id": "legacy", "symbol": META.name, "version": PROFILES["rr2"].version,
              "status": "orders_pending", "placed_at": iso(T0), "pending_expires": iso(T0 + timedelta(hours=48)),
              "accepted": True, "direction": BUY, "bottom": 1.0, "top": 2.0, "legs": [], "account_id": "acct-1",
              "execution": {"state": "submitted", "risk_usd": 10.0, "legs": [{"state": "pending"}]}}
    env.store.add_basket(legacy)
    bars, _, tc = scenario()
    env.run([b for b in bars if b.close_time <= tc], delay=1)
    assert [b["id"] for b in env.baskets()] == ["FVG-legacy"]
    assert any(s.reason == "engine_basket_open" for s in env.store.list_setups(50) if (s.meta or {}).get("engine") == "M15")


@pytest.mark.parametrize("state,legs", [("partial", ["pending", "rejected", "not_sent"]),
                                        ("needs_reconciliation", ["unknown", "not_sent", "not_sent"]),
                                        ("submitting", ["sending", "not_sent", "not_sent"])])
def test_partial_unknown_and_sending_outcomes_keep_their_slot(tmp_path, state, legs):
    env = Env(tmp_path)
    b = {"id": "FVG5-x", "plan_id": "x", "engine": "M5", "symbol": META.name, "status": state, "placed_at": iso(T0),
         "pending_expires": iso(T0 - timedelta(hours=1)), "accepted": True, "direction": BUY, "bottom": 1, "top": 2,
         "legs": [], "account_id": "acct-1", "execution": {"state": state, "legs": [{"state": s} for s in legs]}}
    assert basket_is_open(b, T0 + timedelta(days=1))  # a deadline alone never frees the slot
    o = env.eng.occupancy([b], T0 + timedelta(days=1))
    assert o[0].open and admission("M5", T0 + timedelta(days=1), o, D, 10.0) == "engine_basket_open"


# ------------------------------------------------------------------ candle-close invalidation on the originating timeframe
def test_m15_basket_ignores_m5_closes_and_is_invalidated_by_the_m15_close(tmp_path):
    env = Env(tmp_path)
    bars, _, tc = scenario()
    bars = [b for b in bars if b.close_time <= tc]
    env.run(bars, delay=1)
    [b] = env.baskets()
    t = tc
    tail = [Bar(t, M5, 120.7, 120.8, 116.0, 116.2),        # M5 close below 116.6 (zone bottom): NOT an M15 close
            Bar(t + M5, M5, 116.2, 118.5, 116.1, 118.4),   # back inside
            Bar(t + 2 * M5, M5, 118.4, 118.6, 117.9, 118.0)]  # the M15 candle closes at 118.0: inside, no invalidation
    bars2 = bars + tail
    env.run(bars2, delay=1, start=len(bars))
    assert not env.store.baskets(limit=5)[0].get("zone_invalidated_at")
    t2 = t + 3 * M5
    tail2 = [Bar(t2, M5, 118.0, 118.1, 116.0, 116.3), Bar(t2 + M5, M5, 116.3, 116.4, 116.0, 116.2),
             Bar(t2 + 2 * M5, M5, 116.2, 116.3, 116.0, 116.1)]  # the next M15 close (116.1) is below the zone
    env.run(bars2 + tail2, delay=1, start=len(bars2))
    b = env.store.baskets(limit=5)[0]
    assert b["zone_invalidated_at"] == iso(t2 + 3 * M5) and b["zone_invalidated_by"] == "M15 close"
    assert b["status"] == "zone_invalidated"


def test_m5_basket_is_invalidated_by_its_own_m5_close(tmp_path):
    env = Env(tmp_path)
    bars, tc = m5_gap_series()
    env.run(bars, delay=1)
    tail = [Bar(tc, M5, 120.7, 120.8, 116.0, 116.2)]
    env.run(bars + tail, delay=1, start=len(bars))
    b = env.baskets()[0]
    assert b["zone_invalidated_at"] == iso(tc + M5) and b["zone_invalidated_by"] == "M5 close"


# ------------------------------------------------------------------ broker: the other engine's own exposure may coexist
def _gap():
    from app.fvg import Gap
    return Gap(BUY, 100.0, 110.0, None, None)


def test_executor_allows_only_the_other_engines_own_open_basket(tmp_path):
    broker = Broker()
    journal = ExecutionJournal(tmp_path / "j.sqlite")
    ex = MT5FvgExecutor(lambda: broker, journal, policy())
    from .test_fvg import T
    broker.orders = (NS(ticket=1, symbol=META.name, magic=MAGIC, comment="FVG15-aaaa-L1", state=1),)
    with pytest.raises(ValueError, match="block another FVG basket"):
        ex.submit("p1", _gap(), META, T, T + timedelta(hours=2))  # legacy single-basket rule: anything blocks
    out = ex.submit("p2", _gap(), META, T, T + timedelta(hours=2), comment_tag="FVG5", allowed_prefixes=("FVG15-aaaa-",),
                    engine="M5")
    assert out["state"] == "submitted" and out["engine"] == "M5" and out["comment_prefix"] == "FVG5-p2-"
    assert [r["comment"] for r in broker.requests] == ["FVG5-p2-L1", "FVG5-p2-L2", "FVG5-p2-L3"]
    broker.orders += (NS(ticket=2, symbol=META.name, magic=999, comment="manual", state=1),)
    with pytest.raises(ValueError, match="block another FVG basket"):
        ex.submit("p3", _gap(), META, T, T + timedelta(hours=2), comment_tag="FVG5", allowed_prefixes=("FVG15-aaaa-",))
    journal.close()


def test_live_engines_submit_two_baskets_with_engine_tagged_orders(tmp_path):
    broker = Broker()
    journal = ExecutionJournal(tmp_path / "j.sqlite")
    holder = {}

    def executor_fn():
        return MT5FvgExecutor(lambda: broker, journal, policy(), clock=lambda: holder["now"]), "ON"

    env = Env(tmp_path, executor_fn=executor_fn)
    bars, tc15, _ = m15_then_m5_gap()

    def run(start, end):
        for i in range(start, end):
            b = bars[i]
            now = b.close_time + timedelta(seconds=1)
            holder["now"] = now
            broker.ticks = [NS(bid=b.close, ask=b.close + 0.2, time=now.timestamp(), time_msc=int(now.timestamp() * 1000))]
            broker.tick_calls = 0
            env.eng.process_bar(bars, i, lambda c, x, b=b, now=now: (Quote(now, b.close, b.close + 0.2), now), now)

    first = next(i for i, b in enumerate(bars) if b.close_time == tc15) + 1
    run(0, first)
    m15b = env.baskets()[0]
    assert m15b["engine"] == "M15" and m15b["status"] == "orders_pending"
    # the M15 limits now rest at the broker (owned, engine-tagged); the M5 engine may still trade next to them
    broker.orders = tuple(NS(ticket=100 + n, symbol=META.name, magic=MAGIC, comment=r["comment"], state=1)
                          for n, r in enumerate(broker.requests, 1))
    run(first, len(bars))
    got = env.baskets()
    assert [b["engine"] for b in got] == ["M15", "M5"] and got[1]["status"] == "orders_pending"
    assert sorted({r["comment"].split("-")[0] for r in broker.requests}) == ["FVG15", "FVG5"]
    assert len(broker.requests) == 6 and got[1]["risk_usd"] == 10.0 and got[0]["risk_usd"] == 10.0
    journal.close()


def test_unknown_send_keeps_the_slot_and_is_never_resent(tmp_path):
    broker = Broker()
    broker.fail_at = 2  # leg 2 times out
    journal = ExecutionJournal(tmp_path / "j.sqlite")
    holder = {}
    env = Env(tmp_path, executor_fn=lambda: (MT5FvgExecutor(lambda: broker, journal, policy(),
                                                            clock=lambda: holder["now"]), "ON"))
    bars, tc = m5_gap_series()
    for i, b in enumerate(bars):
        now = b.close_time + timedelta(seconds=1)
        holder["now"] = now
        broker.ticks = [NS(bid=b.close, ask=b.close + 0.2, time=now.timestamp(), time_msc=int(now.timestamp() * 1000))]
        broker.tick_calls = 0
        env.eng.process_bar(bars, i, lambda c, x, b=b, now=now: (Quote(now, b.close, b.close + 0.2), now), now)
    [b] = env.baskets()
    assert b["status"] == "needs_reconciliation" and [l["state"] for l in b["execution"]["legs"]] == ["pending", "unknown", "not_sent"]
    assert basket_is_open(b, tc + timedelta(days=3)) and len(broker.requests) == 2
    env.run(bars, delay=1, start=len(bars) - 1)
    assert len(broker.requests) == 2  # never resent
    journal.close()


# ------------------------------------------------------------------ replay agrees with live; legacy untouched
def test_replay_uses_the_same_rules_and_matches_the_live_decisions(tmp_path):
    bars, tc15, _ = m15_then_m5_gap()
    res = replay_dual(bars, META, D, Costs(0.2, 0.05))
    env = Env(tmp_path)
    env.run(bars, delay=0)
    live = [(b["engine"], b["direction"], b["bottom"], b["top"], b["decision_close"]) for b in env.baskets()]
    sim = [(b["engine"], b["dir"], b["zone"][0], b["zone"][1], b["placed_utc"]) for b in res["baskets"]]
    assert live == sim and res["simulation"] is True
    assert [s["engine"] for s in res["setups"] if s["status"] == "accepted"] == ["M15", "M5"]


def test_legacy_v1_remains_selectable_with_its_version_and_waiting_v1_setups_are_retired(tmp_path):
    v1 = parse_active_strategy({"strategy": "fvg", "profile": "rr2"})
    dual = parse_active_strategy({"strategy": "fvg", "profile": "dual"})
    assert v1.fvg_version == PROFILES["rr2"].version and not v1.is_fvg_dual
    assert dual.is_fvg_dual and dual.fvg_version == D.version and dual.fvg_version != v1.fvg_version
    assert set(dual.describe("x")["engine_versions"]) == set(ENGINES)
    env = Env(tmp_path)
    from app.fvg import new_setup, Gap
    a, b, c = (Bar(T0 + k * M15, M15, 1, 2, 0.5, 1.5) for k in range(3))
    s = new_setup(Gap(BUY, 1.0, 2.0, a, c), PROFILES["rr2"], META.name, PROFILES["rr2"].version)
    s.status = "retested"
    env.store.add_setup(s, META.name, PROFILES["rr2"].version)
    assert env.eng.retire_legacy_setups(T0) == 1
    got = env.store.get_setup(s.key)
    assert got.status == "expired" and got.reason == "retired_strategy_switch_to_dual"


# ------------------------------------------------------------------ Guide: dual path (read-only presentation)
from app.fvg_guide import dual_record_view  # noqa: E402

CURRENT = {D.version, *(D.engine_version(e) for e in ENGINES)}


def test_guide_dual_record_has_no_retest_or_confirmation_and_uses_engine_timestamps(tmp_path):
    env = Env(tmp_path)
    bars, tc = m5_gap_series()
    env.run(bars, delay=1)
    [b] = env.baskets()
    s = env.store.get_setup(b["setup_key"])
    v = dual_record_view(s, b, bars, R, META, tc + timedelta(minutes=1), CURRENT)
    assert [x["key"] for x in v["steps"]] == ["detected", "qualified", "eligibility", "pending", "fills"]
    assert v["record"]["engine"] == "M5" and v["record"]["rule_set"] == "dual" and v["record"]["current_version"]
    assert [c["role"] for c in v["m15"]] == ["A", "B", "C"] and all(c["tf"] == "M5" for c in v["m15"])
    states = {x["key"]: x["state"] for x in v["steps"]}
    assert states["eligibility"] == "done" and states["pending"] == "skipped"  # alert-only: no broker orders
    assert v["deadlines"][0]["label"].startswith("Decision window")


def test_guide_dual_rejection_is_reported_as_failed_eligibility(tmp_path):
    env = Env(tmp_path)
    bars, tc = m5_gap_series()
    env.run(bars, delay=45)
    s = next(x for x in env.store.list_setups(100) if (x.reason or "").startswith("decision_too_old"))
    v = dual_record_view(s, None, bars, R, META, tc + timedelta(minutes=1), CURRENT)
    st = {x["key"]: x for x in v["steps"]}
    assert st["qualified"]["state"] == "done" and st["eligibility"]["state"] == "failed"
    assert "30 seconds" in st["eligibility"]["detail"] and v["next"].startswith("Finished")


def test_guide_endpoints_are_read_only_in_dual_mode_and_lessons_are_gone(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.web import create_app
    app = create_app(Settings(port=8000), feed_factory=fixture_factory, state_dir=tmp_path, extra_hosts=("testserver",),
                     active_strategy_loader=lambda: parse_active_strategy({"strategy": "fvg", "profile": "dual"}))
    with TestClient(app) as c:
        ws = app.state.ws

        def forbidden(*a, **k):
            raise AssertionError("the guide must never reach execution or maintenance")
        ws.scanner.stop()
        ws._fvg_executor, ws._fvg_maintenance = forbidden, forbidden
        env = Env(tmp_path / "x")
        bars, tc = m5_gap_series()
        env.run(bars, delay=1)
        for s in env.store.list_setups(100):
            ws.fvg_store.add_setup(s, META.name, s.key.rsplit("|", 1)[-1])
        for b in env.baskets():
            ws.fvg_store.add_basket(b)
        before = (len(ws.fvg_store.list_setups(500)), len(ws.fvg_store.baskets(limit=500)))
        d = c.get("/api/fvg/guide").json()
        assert d["strategy_mode"] == "dual" and d["scopes"]["daily_cap"].endswith("(both engines)")
        key = env.baskets()[0]["setup_key"]
        sel = c.get("/api/fvg/guide", params={"key": key}).json()["selected"]
        assert sel["record"]["engine"] == "M5" and [x["key"] for x in sel["steps"]][-2:] == ["pending", "fills"]
        assert c.get("/api/fvg/guide/lessons").status_code == 404  # fictional lessons were removed
        st = c.get("/api/state").json()
        assert st["active_strategy"]["mode"] == "dual" and st["fvg"]["mode"] == "dual"
        assert (len(ws.fvg_store.list_setups(500)), len(ws.fvg_store.baskets(limit=500))) == before
