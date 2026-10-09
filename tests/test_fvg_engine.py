"""FVG rules, replay and the live engine on FICTIONAL fixtures (fake broker, mocked delivery; nothing real is sent)."""
import json
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

import httpx
import pytest

from app.active_strategy import parse_active_strategy
from app.config import Settings, StrategyConfig
from app.delivery import Delivery, TelegramClient, format_fvg_basket
from app.fastsweep import BUY, M15, bangkok_date
from app.fvg import PROFILES, FvgSetup, advance_setup, atr_last, basket_levels, contiguous_run, detect_gap, new_setup, qualify
from app.fvg_execution import ExecutionJournal, ExecutionPolicy, MT5FvgExecutor
from app.fvg_live import FvgLiveEngine, FvgStore
from app.fvg_replay import Costs, frequency, replay
from app.models import M5, UTC, Bar, Quote, SymbolMeta, aggregate, iso
from app.scanner import Scanner
from app.store import SqliteStore

from .test_fastsweep import m15
from .test_fvg_execution import Broker
from tests.conftest import fixture_factory

META = SymbolMeta("TEST", 0.01, 0.01, 2, "test")
CFG = PROFILES["rr2"]
T0 = datetime(2030, 1, 7, 0, 0, tzinfo=UTC)  # Monday 07:00 Bangkok
WARM = 55


def scenario(warm=WARM, tail=()):
    """Rising warm-up, then A/B/C with a bullish FVG [116.6, 117.8], an M5 retest and a confirmation close."""
    bars = []
    for k in range(warm):
        c = 100 + 0.3 * k
        bars += m15(T0 + k * M15, c - 0.2, c + 0.1, c - 0.3, c)
    ta = T0 + warm * M15
    bars += m15(ta, 116.3, 116.6, 116.1, 116.5)            # A
    bars += m15(ta + M15, 116.5, 120.5, 116.4, 120.3)      # B: strong bullish body
    bars += m15(ta + 2 * M15, 120.3, 120.9, 117.8, 120.7)  # C: low 117.8 > A high 116.6
    tc = ta + 3 * M15                                      # zone available from here
    bars += [Bar(tc, M5, 120.7, 120.8, 119.9, 120.0),            # no touch
             Bar(tc + M5, M5, 120.0, 120.1, 117.5, 118.0),       # first retest (low 117.5 <= 117.8): level 120.1
             Bar(tc + 2 * M5, M5, 118.0, 120.3, 117.9, 120.2)]   # confirmation: close 120.2 > 120.1
    t = tc + 3 * M5
    for o, h, l, c in tail:
        bars.append(Bar(t, M5, o, h, l, c))
        t += M5
    return bars, ta, tc


def flat(price, n):
    return [(price, price, price, price)] * n


# ------------------------------------------------------------------ rules
def test_gap_qualifies_with_atr_through_b_and_trend_warmup():
    bars, ta, tc = scenario()
    h15 = aggregate(bars, M15)
    j = next(i for i, b in enumerate(h15) if b.close_time == tc)
    gap = detect_gap(h15[j - 2], h15[j - 1], h15[j], META.tick_size)
    assert (gap.direction, gap.bottom, gap.top) == (BUY, 116.6, 117.8)
    assert qualify(gap, h15[: j + 1], CFG, META.tick_size) is None
    atr_b = atr_last(contiguous_run(h15[: j]), CFG.atr_period)
    bigger_c = h15[: j] + [replace(h15[j], high=h15[j].high + 50)]  # C's range never enters the ATR
    assert atr_last(contiguous_run(bigger_c[:-1]), CFG.atr_period) == atr_b
    short, _, tc2 = scenario(warm=40)
    s15 = aggregate(short, M15)
    k = next(i for i, b in enumerate(s15) if b.close_time == tc2)
    assert qualify(detect_gap(s15[k - 2], s15[k - 1], s15[k], 0.01), s15[: k + 1], CFG, 0.01) == "trend_warmup"


def _setup():
    bars, ta, tc = scenario()
    h15 = aggregate(bars, M15)
    j = next(i for i, b in enumerate(h15) if b.close_time == tc)
    return new_setup(detect_gap(h15[j - 2], h15[j - 1], h15[j], 0.01), CFG, "TEST", CFG.version), bars, tc


def test_first_retest_then_a_different_bar_confirms():
    s, bars, tc = _setup()
    inside_c = Bar(tc - M5, M5, 120.0, 120.1, 117.0, 120.0)  # one of C's own bars: never a retest
    assert advance_setup(s, inside_c, CFG) == "pending"
    for b in bars:
        if b.open_time >= tc:
            advance_setup(s, b, CFG)
    assert s.status == "confirmed" and s.level == 120.1 and s.retest_close == tc + 2 * M5 and s.confirm_close == tc + 3 * M5


def test_retest_bar_cannot_confirm_itself_and_invalidation_wins():
    s, _, tc = _setup()
    assert advance_setup(s, Bar(tc, M5, 120.7, 121.0, 117.5, 120.9), CFG) == "retested"  # closes high, still only a retest
    s2, _, _ = _setup()
    advance_setup(s2, Bar(tc, M5, 120.7, 120.8, 117.5, 118.0), CFG)
    assert advance_setup(s2, Bar(tc + M5, M5, 118.0, 118.2, 116.0, 116.5), CFG) == "invalidated"  # close < bottom
    assert s2.reason == "close_beyond_far_edge"
    s3, _, _ = _setup()
    assert advance_setup(s3, Bar(tc, M5, 120.7, 120.8, 116.0, 116.4), CFG) == "invalidated"  # first touch closes beyond


def test_missing_bar_and_no_confirmation_within_three_bars():
    s, _, tc = _setup()
    assert advance_setup(s, Bar(tc + M5, M5, 120, 120.1, 119.9, 120), CFG) == "invalidated"  # skipped the bar at tc
    s2, _, _ = _setup()
    advance_setup(s2, Bar(tc, M5, 120.7, 120.8, 117.5, 118.0), CFG)
    for k in range(1, 4):
        st = advance_setup(s2, Bar(tc + k * M5, M5, 118.0, 118.5, 117.9, 118.1), CFG)
    assert st == "expired" and s2.reason == "no_confirmation_after_retest"



@pytest.mark.parametrize("direction", [BUY, "SELL"])
def test_far_edge_close_invalidates_even_before_the_first_touch(direction):
    a = Bar(T0, M15, 1, 1, 1, 1)
    gap = NS(direction=direction, bottom=100.0, top=110.0, first=a, third=Bar(T0 + 2 * M15, M15, 1, 1, 1, 1))
    s = new_setup(gap, CFG, "TEST", CFG.version)
    t = s.next_open
    beyond = Bar(t, M5, 99, 99.5, 98, 99) if direction == BUY else Bar(t, M5, 111, 112, 110.5, 111)  # never touches
    assert advance_setup(s, beyond, CFG) == "invalidated" and s.reason == "close_beyond_far_edge"
    s2 = new_setup(gap, CFG, "TEST", CFG.version)
    near = Bar(t, M5, 112, 113, 111, 112) if direction == BUY else Bar(t, M5, 98, 99, 97, 98)  # beyond the NEAR edge
    assert advance_setup(s2, near, CFG) == "pending"

def test_setup_lifetime_two_hours():
    s, _, tc = _setup()
    for k in range(24):
        assert advance_setup(s, Bar(tc + k * M5, M5, 120.5, 120.6, 120.4, 120.5), CFG) == "pending"
    assert advance_setup(s, Bar(tc + 24 * M5, M5, 120.5, 120.6, 120.4, 120.5), CFG) == "expired"


def test_basket_levels_mirrored_three_distinct_prices_common_sl_and_2r():
    sl, legs = basket_levels(NS(direction=BUY, bottom=116.6, top=117.8), META, CFG)
    assert sl == 116.58 and [l.entry for l in legs] == [117.78, 117.2, 116.84]
    assert [l.tp for l in legs] == [120.18, 118.44, 117.36]
    sl2, legs2 = basket_levels(NS(direction="SELL", bottom=116.6, top=117.8), META, CFG)
    assert sl2 == 117.82 and [l.entry for l in legs2] == [116.62, 117.2, 117.56]
    assert all(abs(abs(l.tp - l.entry) - 2 * abs(l.entry - sl2)) < 0.011 for l in legs2)
    with pytest.raises(ValueError):
        basket_levels(NS(direction=BUY, bottom=117.0, top=117.02), META, CFG)  # too narrow for three prices


# ------------------------------------------------------------------ replay (simulated, research only)
def run(tail, costs=Costs(0.05, 0.05)):
    bars, ta, tc = scenario(tail=tail)
    return replay(bars, META, CFG, costs)


def test_replay_fill_then_tp_and_tp_in_fill_bar_is_ambiguous():
    # leg1 entry 117.78 fills when Ask (low + 0.2) <= 117.78; TP 120.18
    r = run([(120.1, 120.1, 117.5, 118.0)] + flat(118.0, 2) + [(118.0, 120.3, 117.9, 120.2)] + flat(120.2, 3))
    (b,) = r["baskets"]
    leg1 = b["legs"][0]
    assert leg1["state"] == "filled" and leg1["outcome"] == "tp" and leg1["r"] >= 2.0
    amb = run([(120.2, 120.4, 117.5, 118.0)] + flat(118.0, 3))["baskets"][0]["legs"][0]
    assert amb["outcome"] == "ambiguous" and amb["r"] is None and amb["worst_r"] < -1


def test_replay_sl_in_fill_bar_expiry_and_far_edge_cancel():
    sl = run([(117.3, 117.3, 116.4, 116.5)] + flat(116.5, 3))["baskets"][0]  # no TP inside the fill bar
    assert [l["outcome"] for l in sl["legs"]] == ["sl", "sl", "sl"]  # every leg filled then stopped (SL 116.58)
    exp = run(flat(120.2, 26))["baskets"][0]
    assert [l["state"] for l in exp["legs"]] == ["expired"] * 3
    canc = run([(120.2, 120.2, 117.5, 118.0), (118.0, 118.1, 116.0, 116.59)] + flat(116.59, 2))["baskets"][0]
    assert canc["legs"][0]["state"] == "filled"


def test_replay_conservative_counts_ambiguous_as_losses_and_daily_table():
    r = run([(120.2, 120.4, 117.5, 118.0)] + flat(118.0, 3))
    a = r["segments"]["all"]
    assert a["conservative"]["net_basket_r"] < a["baseline"]["net_basket_r"] or a["baseline"]["baskets_with_r"] == 0
    f = frequency(r["daily"])
    assert r["daily"][0]["date"] == bangkok_date(T0) and f["all_calendar_dates"]["dates"] >= 1


# ------------------------------------------------------------------ live engine
class ArmedBroker(Broker):
    def __init__(self, now):
        super().__init__()
        self.symbol = NS(trade_mode=4, trade_tick_size=0.01, point=0.01, digits=2, volume_min=0.01, volume_max=100.0,
                         volume_step=0.01, trade_stops_level=0, order_mode=3, expiration_mode=5, filling_mode=1)
        self.set_quote(now, 120.2, 120.25)

    def set_quote(self, now, bid, ask):
        self.ticks = [NS(bid=bid, ask=ask, time=now.timestamp(), time_msc=int(now.timestamp() * 1000))]
        self.tick_calls = 0


def make_engine(tmp_path, armed=False, name="f"):
    fstore = FvgStore(tmp_path / f"{name}.sqlite")
    events = SqliteStore(tmp_path / f"{name}-events.sqlite")
    journal = ExecutionJournal(tmp_path / f"{name}-journal.sqlite")
    _, _, tc = scenario()
    broker = ArmedBroker(tc + 3 * M5 + timedelta(seconds=1))
    pol = ExecutionPolicy(True, 10.0, 77, "mt5", META.name, CFG.version, account_server="Test-Server")
    alerts = []
    eng = FvgLiveEngine(CFG, META, fstore, events, "mt5", alert_fn=alerts.append,
                        executor_fn=(lambda: (MT5FvgExecutor(lambda: broker, journal, pol), "ON")) if armed
                        else (lambda: (None, "automatic execution OFF")),
                        maintenance_fn=lambda: MT5FvgExecutor(lambda: broker, journal, ExecutionPolicy()))
    return eng, fstore, broker, alerts, journal


def drive(bars, eng, delay_s=1):
    for i, b in enumerate(bars):
        eng.process_bar(bars, i, None, b.close_time + timedelta(seconds=delay_s))


def test_armed_engine_submits_exactly_three_limits_automatically(tmp_path):
    bars, ta, tc = scenario()
    eng, fstore, broker, alerts, _ = make_engine(tmp_path, armed=True)
    drive(bars, eng)
    (b,) = fstore.baskets()
    assert len(broker.requests) == 3 and b["status"] == "orders_pending" and len(alerts) == 1
    assert [r["price"] for r in broker.requests] == [117.78, 117.2, 116.84]
    assert b["execution"]["risk_usd"] == 10.0 and b["execution"]["nominal_planned_loss"] <= 10.0 + 1e-9
    assert b["confirm_close"] == iso(tc + 3 * M5)


def test_execution_off_sends_nothing_and_keeps_the_alert_plan(tmp_path):
    bars, _, _ = scenario()
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=False)
    drive(bars, eng)
    (b,) = fstore.baskets()
    assert broker.requests == [] and journal.rows() == [] and b["status"] == "alert_only"
    assert b["execution"] == {"state": "not_submitted", "reason": "automatic execution OFF"} and len(alerts) == 1


def test_historical_confirmation_before_watermark_never_alerts_or_submits(tmp_path):
    bars, _, tc = scenario()
    eng, fstore, broker, alerts, _ = make_engine(tmp_path, armed=True)
    eng.eligible_after = tc + 3 * M5  # session opened exactly at the confirmation close (restart/reconnect)
    drive(bars, eng)
    assert fstore.baskets() == [] and broker.requests == [] and alerts == []
    assert any(s.reason == "confirmation_before_session_watermark" for s in fstore.list_setups())


def test_restart_reprocessing_never_submits_again(tmp_path):
    bars, _, _ = scenario()
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=True)
    drive(bars, eng)
    eng2 = FvgLiveEngine(CFG, META, fstore, eng.events, "mt5", alert_fn=alerts.append, executor_fn=eng.executor_fn,
                         maintenance_fn=eng.maintenance_fn)
    drive(bars, eng2)
    assert len(fstore.baskets()) == 1 and len(broker.requests) == 3 and len(alerts) == 1


def _accepted(fstore, bid, placed, status="closed"):
    fstore.add_basket({"id": bid, "plan_id": bid, "symbol": META.name, "version": CFG.version, "status": status,
                       "placed_at": iso(placed), "pending_expires": iso(placed + timedelta(hours=2)), "accepted": True,
                       "direction": BUY, "bottom": 1, "top": 2, "sl": 0.9, "legs": [], "execution": {"state": "closed"}})


def test_caps_and_cooldown_come_from_persisted_baskets(tmp_path):
    bars, _, tc = scenario()
    confirm = tc + 3 * M5
    eng, fstore, broker, alerts, _ = make_engine(tmp_path, armed=True, name="cool")
    _accepted(fstore, "old", confirm - timedelta(minutes=20))
    drive(bars, eng)
    assert broker.requests == [] and any(s.reason == "cooldown" for s in fstore.list_setups())
    eng2, f2, broker2, _, _ = make_engine(tmp_path, armed=True, name="cap")
    day0 = datetime(2030, 1, 6, 17, 0, tzinfo=UTC)  # 00:00 Bangkok on the confirmation's Bangkok date
    for k in range(4):
        _accepted(f2, f"c{k}", day0 + timedelta(minutes=40 * k))
    drive(bars, eng2)
    assert broker2.requests == [] and any(s.reason == "daily_cap" for s in f2.list_setups())
    eng3, f3, broker3, _, _ = make_engine(tmp_path, armed=True, name="open")
    _accepted(f3, "open1", confirm - timedelta(hours=1), status="alert_only")
    f3.update_basket({**f3.baskets()[0], "execution": {"state": "submitted"}, "status": "orders_pending"})
    drive(bars, eng3)
    assert broker3.requests == [] and any(s.reason == "basket_already_open" for s in f3.list_setups())


def test_far_edge_close_cancels_only_this_baskets_pending_legs(tmp_path):
    bars, _, tc = scenario(tail=[(120.2, 120.2, 116.0, 116.5)])
    eng, fstore, broker, _, _ = make_engine(tmp_path, armed=True)
    from .test_fvg_execution import _order
    foreign = NS(ticket=900, comment="manual", symbol=META.name, magic=0, state=1)

    def own(n, t):
        return NS(ticket=t, comment=f"FVG-{fstore_plan(fstore)}-L{n}", symbol=META.name, magic=761007, state=1)

    def fstore_plan(fs):
        b = fs.baskets()
        return b[0]["plan_id"] if b else "x"
    drive(bars[:-1], eng)
    broker.orders = (own(1, 101), own(2, 102), own(3, 103), foreign)
    drive(bars, eng)
    assert sorted(broker.removed) == [101, 102, 103] and 900 not in broker.removed


def test_outbox_dedup_and_three_four_line_blocks(tmp_path):
    store = SqliteStore(tmp_path / "o.sqlite")
    calls = []
    settings = Settings(telegram_bot_token="1:x", telegram_test_chat_id="-1")
    d = Delivery(store, settings, source="test", client_factory=lambda t: TelegramClient(t, transport=httpx.MockTransport(
        lambda r: calls.append(r) or httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}))))
    d.set_enabled(True)
    basket = {"id": "FVG-1", "placed_at": iso(datetime.now(UTC)), "meta": {"digits": 3},
              "legs": [{"entry": 117.78, "tp": 120.18, "sl": 116.58, "rr": 2.0}, {"entry": 117.2, "tp": 118.44, "sl": 116.58, "rr": 2.0},
                       {"entry": 116.84, "tp": 117.36, "sl": 116.58, "rr": 2.0}]}
    assert d.on_fvg_basket(basket) and not d.on_fvg_basket(basket)
    blocks = format_fvg_basket(basket).split("\n\n\n")  # two blank lines between entries
    lines = [b.split("\n\n") for b in blocks]  # one blank line after every line
    assert len(blocks) == 3 and all(len(ls) == 5 and all(l and "\n" not in l for l in ls) for ls in lines)
    assert [ls[0] for ls in lines] == ["1️⃣ First entry", "2️⃣ Second entry", "3️⃣ Third entry"]
    assert lines[0][1] == "\U0001F4CD Entry: 117.780"
    d.process_due()
    assert len(calls) == 1 and "parse_mode" not in json.loads(calls[0].content)


# ------------------------------------------------------------------ scanner integration (fake feed, fake broker)
class FakeFeed:
    mode = "mt5"
    supports_ticks = False

    spread = 0.05

    def __init__(self, bars, now):
        self.bars, self._now = bars, now

    def now(self):
        return self._now

    def connect(self):
        return self.status()

    def shutdown(self):
        pass

    def status(self):
        from app.data.base import FeedStatus
        return FeedStatus(True, "connected", "fake feed")

    def meta(self):
        return META

    def closed_bars(self, tf, n):
        done = [b for b in self.bars if b.close_time <= self._now]
        return done[-n:] if tf == "M5" else aggregate(done, timedelta(hours=1))[-n:]

    def quote(self):
        done = [b for b in self.bars if b.close_time <= self._now]
        c = done[-1].close if done else 100.0
        return Quote(self._now - timedelta(seconds=1), c, round(c + self.spread, 6))


def scanner(tmp_path, bars, now, armed):
    store = SqliteStore(tmp_path / "s.sqlite")
    fstore = FvgStore(tmp_path / "fvg.sqlite")
    journal = ExecutionJournal(tmp_path / "j.sqlite")
    settings = Settings()
    feed = FakeFeed(bars, now)
    broker = ArmedBroker(now)
    pol = ExecutionPolicy(True, 10.0, 77, "mt5", META.name, CFG.version, account_server="Test-Server")

    def executor_fn():
        broker.set_quote(feed.now(), 120.2, 120.2 + feed.spread)
        return (MT5FvgExecutor(lambda: broker, journal, pol), "ON") if armed else (None, "automatic execution OFF")
    sc = Scanner(settings, StrategyConfig(), feed, store, Delivery(store, settings, clock=feed.now, source="test"),
                 active=parse_active_strategy({"strategy": "fvg", "profile": "rr2"}), fvg_store=fstore,
                 fvg_executor_fn=executor_fn,
                 fvg_maintenance_fn=lambda: MT5FvgExecutor(lambda: broker, journal, ExecutionPolicy()))
    return sc, feed, store, fstore, broker


def step(sc, feed, until):
    while feed._now < until:
        feed._now += timedelta(seconds=10)
        sc.scan_once()


def test_scanner_auto_submits_a_live_confirmation_once(tmp_path):
    bars, ta, tc = scenario(tail=flat(120.2, 6))
    sc, feed, store, fstore, broker = scanner(tmp_path, bars, tc - timedelta(minutes=10), armed=True)
    store.set_meta("last_m5_close", iso(ta - M15))
    step(sc, feed, tc + timedelta(minutes=30))
    assert len(broker.requests) == 3 and len(fstore.baskets()) == 1
    assert sc.strategy_state()["state"].startswith("basket")


def test_scanner_started_after_the_confirmation_submits_nothing(tmp_path):
    bars, ta, tc = scenario(tail=flat(120.2, 6))
    sc, feed, store, fstore, broker = scanner(tmp_path, bars, tc + 3 * M5 + timedelta(seconds=20), armed=True)
    store.set_meta("last_m5_close", iso(ta - M15))
    step(sc, feed, tc + timedelta(minutes=30))
    assert broker.requests == [] and fstore.baskets() == []


# ------------------------------------------------------------------ API: inactive build, arming refused
def test_api_reports_fvg_inactive_and_refuses_arming(tmp_path):
    from fastapi.testclient import TestClient
    from app.active_strategy import ActiveStrategy
    from app.web import create_app
    app = create_app(Settings(port=8000), feed_factory=fixture_factory, state_dir=tmp_path, extra_hosts=("testserver",),
                     active_strategy_loader=lambda: ActiveStrategy("crt"))
    with TestClient(app) as c:
        token = app.state.token
        st = c.get("/api/state").json()["fvg"]
        assert st["strategy_active"] is False and st["auto_execution"] == "OFF" and st["risk_usd"] == 10.0
        r = c.post("/api/fvg/execution", json={"enabled": True, "confirm": True}, headers={"X-Session-Token": token})
        assert r.status_code == 400 and "only be armed" in r.json()["detail"]
        assert c.get("/api/fvg").json()["baskets"] == []
        trading = c.get("/api/state").json()["trading"]
        assert trading.startswith("disabled:") and "no orders are sent" in trading and "FVG is not the active strategy" in trading
    app2 = create_app(Settings(port=8000), feed_factory=fixture_factory, state_dir=tmp_path / "fvg", extra_hosts=("testserver",),
                      active_strategy_loader=lambda: parse_active_strategy({"strategy": "fvg", "profile": "rr2"}))
    with TestClient(app2) as c:
        s = c.get("/api/state").json()
        assert s["active_strategy"]["kind"] == "fvg" and s["fvg"]["auto_execution"] == "OFF"
        assert s["fvg"]["reason"] == "MT5 account unavailable"  # MT5-only: the test feed has no account behind it
        assert s["trading"].startswith("disabled: FVG automatic execution is OFF") and "no orders are sent" in s["trading"]
        r = c.post("/api/fvg/execution", json={"enabled": True, "confirm": True}, headers={"X-Session-Token": app2.state.token})
        assert r.status_code == 400



# ------------------------------------------------------------------ crash windows across the two durable stores
class Crash(BaseException):
    """Simulated process exit (not an Exception: nothing in the engine may swallow it)."""


def test_exit_after_orders_were_sent_recovers_the_journal_into_the_basket_without_resending(tmp_path):
    bars, _, _ = scenario()
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=True)
    real = eng.executor_fn

    def crashing():
        ex, why = real()
        orig = ex.submit

        def submit(*a, **k):
            orig(*a, **k)  # journal committed and three orders reached the broker ...
            raise Crash()  # ... then the process dies before the basket row is updated
        ex.submit = submit
        return ex, why
    eng.executor_fn = crashing
    with pytest.raises(Crash):
        drive(bars, eng)
    (b,) = fstore.baskets()
    assert b["status"] == "planned" and b["execution"] is None and len(broker.requests) == 3
    eng2 = FvgLiveEngine(CFG, META, fstore, eng.events, "mt5", alert_fn=alerts.append, executor_fn=real,
                         maintenance_fn=eng.maintenance_fn)
    broker.orders = tuple(NS(ticket=100 + n, comment=f"FVG-{b['plan_id']}-L{n}", symbol=META.name, magic=761007, state=1)
                          for n in (1, 2, 3))
    eng2.reconcile(bars[-1].close_time + timedelta(seconds=30))
    (b,) = fstore.baskets()
    assert b["status"] == "orders_pending" and [l["state"] for l in b["execution"]["legs"]] == ["pending"] * 3
    drive(bars, eng2)
    assert len(broker.requests) == 3 and len(fstore.baskets()) == 1


def test_exit_before_any_send_resolves_as_unsubmitted_and_never_submits_later(tmp_path):
    bars, _, _ = scenario()
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=True)
    real = eng.executor_fn

    def dies():
        raise Crash()
    eng.executor_fn = dies
    with pytest.raises(Crash):
        drive(bars, eng)
    assert fstore.baskets()[0]["status"] == "planned" and journal.rows() == []
    eng2 = FvgLiveEngine(CFG, META, fstore, eng.events, "mt5", alert_fn=alerts.append, executor_fn=real,
                         maintenance_fn=eng.maintenance_fn)
    eng2.reconcile(bars[-1].close_time + timedelta(seconds=30))
    drive(bars, eng2)
    (b,) = fstore.baskets()
    assert b["status"] == "interrupted_unsubmitted" and broker.requests == []


def test_executor_and_feed_share_one_mt5_lock():
    from app.web import Workstation
    feed_lock, scanner_lock = threading.RLock(), threading.RLock()
    ws = NS(scanner=NS(feed=NS(_lock=feed_lock), _feed_lock=scanner_lock))
    assert Workstation._mt5_lock(ws) is feed_lock



def test_trading_status_reports_armed_fvg_truthfully():
    from app.active_strategy import ActiveStrategy
    from app.web import Workstation
    fvg_ws = NS(active=parse_active_strategy({"strategy": "fvg", "profile": "rr2"}), active_view=lambda: {"label": "FVG"})
    on = Workstation.trading_status(fvg_ws, {"auto_execution": "ON", "risk_usd": 10.0})
    assert on.startswith("ENABLED") and "3 pending limit orders" in on and "10.0 USD" in on
    off = Workstation.trading_status(fvg_ws, {"auto_execution": "OFF", "reason": "not armed"})
    assert off.startswith("disabled") and "not armed" in off
    crt_ws = NS(active=ActiveStrategy("crt"), active_view=lambda: {"label": "CRT-SMC-v1"})
    assert "CRT-SMC-v1 is alert-only" in Workstation.trading_status(crt_ws, {"auto_execution": "OFF"})


def test_replay_artifacts_are_read_from_the_workstation_state_dir_only(tmp_path):
    from fastapi.testclient import TestClient
    from app.active_strategy import ActiveStrategy
    from app.web import create_app
    app = create_app(Settings(port=8000), feed_factory=fixture_factory, state_dir=tmp_path, extra_hosts=("testserver",),
                     active_strategy_loader=lambda: ActiveStrategy("crt"))
    with TestClient(app) as c:
        # the real project state dir may hold saved live replays; a test workstation never sees them
        assert c.get("/api/replay", params={"source": "mt5", "strategy": "fastsweep"}).json()["available"] is False
        assert c.get("/api/replay", params={"source": "mt5"}).json()["available"] is False
        (tmp_path / "replays").mkdir(exist_ok=True)
        (tmp_path / "replays" / "latest-mt5-fastsweep.json").write_text('{"marker": 1}', encoding="utf-8")
        assert c.get("/api/replay", params={"source": "mt5", "strategy": "fastsweep"}).json()["result"] == {"marker": 1}



# ------------------------------------------------------------------ review fixes (2026-10-07)
def quote_fn(spread):
    return lambda c, bar: (Quote(T0, 120.2, 120.2 + spread), T0)


def drive_q(bars, eng, spread, delay_s=1):
    for i, b in enumerate(bars):
        eng.process_bar(bars, i, quote_fn(spread), b.close_time + timedelta(seconds=delay_s))


def test_rule6_codex_example_spread_033_rejects_before_any_basket_alert_or_capacity(tmp_path):
    # Codex reproduction: BUY FVG [116.60, 117.80], 80% entry 116.84, SL 116.58 -> stop distance 0.26 < 0.33 + 0.01
    bars, _, _ = scenario()
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=True)
    drive_q(bars, eng, spread=0.33)
    assert fstore.baskets() == [] and alerts == [] and broker.requests == [] and journal.rows() == []
    (s,) = [x for x in fstore.list_setups() if (x.reason or "").startswith("stop_within_spread")]
    assert "leg 3" in s.reason and s.status == "rejected"
    eng2, fstore2, broker2, alerts2, _ = make_engine(tmp_path, armed=True, name="ok")
    drive_q(bars, eng2, spread=0.25)  # 0.26 >= 0.25 + 0.01: equality at the minimum passes
    assert len(broker2.requests) == 3 and len(alerts2) == 1


def test_rule6_boundary_and_sell_symmetry():
    from app.fvg import stop_within_spread
    sl, legs = basket_levels(NS(direction=BUY, bottom=116.6, top=117.8), META, CFG)
    entries = [(l.number, l.entry) for l in legs]
    assert stop_within_spread(sl, entries, 0.25, CFG, 0.01) is None          # 0.26 == 0.25 + 0.01
    assert "leg 3" in stop_within_spread(sl, entries, 0.26, CFG, 0.01)       # 0.26 < 0.27
    sl2, legs2 = basket_levels(NS(direction="SELL", bottom=116.6, top=117.8), META, CFG)
    entries2 = [(l.number, l.entry) for l in legs2]
    assert stop_within_spread(sl2, entries2, 0.25, CFG, 0.01) is None and stop_within_spread(sl2, entries2, 0.33, CFG, 0.01)
    wide_sl, wide = basket_levels(NS(direction=BUY, bottom=110.0, top=117.8), META, CFG)  # an eligible wider gap
    assert stop_within_spread(wide_sl, [(l.number, l.entry) for l in wide], 0.33, CFG, 0.01) is None


def test_rule6_executor_backstop_on_the_send_time_quote(tmp_path):
    bars, _, _ = scenario()
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=True)
    broker.ticks = [NS(bid=120.2, ask=120.53, time=t.time, time_msc=t.time_msc) for t in broker.ticks]  # 0.33 at send
    drive_q(bars, eng, spread=0.05)  # the engine's quote was fine; the broker quote at send time is not
    (b,) = fstore.baskets()
    assert broker.requests == [] and b["status"] == "preflight_rejected" and "spread" in b["execution"]["reason"]


def test_rule6_in_replay_spread_and_wrong_side_placement():
    r = run([(120.1, 120.1, 117.5, 118.0)] + flat(118.0, 3), costs=Costs(0.33, 0.05))
    assert r["baskets"] == [] and r["setup_reasons"].get("stop_within_spread") == 1
    from app.fvg import placement_violation
    assert placement_violation(BUY, [(1, 117.78)], 117.70, 117.75, 0.01)           # Ask already below the limit
    assert placement_violation(BUY, [(1, 117.78)], 117.70, 117.79, 0.01) is None   # rests 1 tick below the Ask
    assert placement_violation("SELL", [(1, 116.62)], 116.65, 116.70, 0.01)        # Bid already above the limit


def test_far_edge_cancel_runs_while_paused_and_is_not_skipped_by_resume(tmp_path):
    bars, ta, tc = scenario(tail=flat(120.2, 3) + [(120.2, 120.2, 116.0, 116.5)] + flat(116.5, 2))
    confirm_end = tc + 3 * M5
    sc, feed, store, fstore, broker = scanner(tmp_path, bars, tc - timedelta(minutes=10), armed=True)
    store.set_meta("last_m5_close", iso(ta - M15))
    step(sc, feed, confirm_end + timedelta(minutes=12))
    (b,) = fstore.baskets()
    assert len(broker.requests) == 3
    broker.orders = tuple(NS(ticket=100 + n, comment=f"FVG-{b['plan_id']}-L{n}", symbol=META.name, magic=761007, state=1)
                          for n in (1, 2, 3))
    sc.pause()
    step(sc, feed, confirm_end + timedelta(minutes=35))  # the far-edge close happens while paused
    assert sorted(broker.removed) == [101, 102, 103]
    assert fstore.baskets()[0].get("zone_invalidated_at")
    sc.resume()
    step(sc, feed, confirm_end + timedelta(minutes=40))
    assert sorted(broker.removed) == [101, 102, 103]  # idempotent: nothing removed twice, nothing new sent
    assert len(broker.requests) == 3


def test_exception_after_journal_is_adopted_as_needs_reconciliation(tmp_path):
    bars, _, _ = scenario()
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=True)
    real_save, calls = journal.save, []

    def failing_save(pid, payload):
        calls.append(payload.get("state"))
        if len(calls) == 3:  # after the first order_send reached the broker
            raise RuntimeError("disk I/O error")
        return real_save(pid, payload)
    journal.save = failing_save
    drive(bars, eng)
    (b,) = fstore.baskets()
    assert len(broker.requests) == 1 and b["status"] == "needs_reconciliation"
    assert b["execution"]["state"] == "needs_reconciliation" and "disk I/O error" in b["execution"]["error"]
    from app.fvg_live import basket_is_open
    assert basket_is_open(b, bars[-1].close_time)  # still managed and reconciled, never shown as "rejected"


def test_other_account_is_logged_once_and_not_counted_until_it_returns(tmp_path):
    bars, _, _ = scenario()
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=True)
    drive(bars, eng)
    from .test_fvg_execution import LOGIN
    broker.account.login = LOGIN + 1
    t = bars[-1].close_time
    for k in range(5):
        eng.reconcile(t + timedelta(seconds=5 * k))
    (b,) = fstore.baskets()
    from app.fvg_live import basket_is_open
    assert "another MT5 server/login" in b["other_account"] and not basket_is_open(b, t)
    warnings = [e for e in eng.events.list_events(100) if "another MT5 server/login" in e["message"]]
    assert len(warnings) == 1
    broker.account.login = LOGIN
    eng.reconcile(t + timedelta(minutes=1))
    (b,) = fstore.baskets()
    assert "other_account" not in b and basket_is_open(b, t)


def test_quote_age_uses_the_real_clock_not_the_scan_start(tmp_path):
    from .test_fvg import META as M, T, candles
    from .test_fvg_execution import Broker, policy
    from app.fvg import Gap
    a, _, c = candles()
    gap = Gap(BUY, 100, 110, a, c)
    old_scan_start = T - timedelta(minutes=2)  # the quote (stamped T) would look 120 s in the future against it
    broker = Broker()
    ex = MT5FvgExecutor(lambda: broker, ExecutionJournal(tmp_path / "a.sqlite"), policy())
    with pytest.raises(ValueError, match="stale"):
        ex.submit("p1", gap, M, old_scan_start, T + timedelta(hours=2))
    broker2 = Broker()
    ex2 = MT5FvgExecutor(lambda: broker2, ExecutionJournal(tmp_path / "b.sqlite"), policy(), clock=lambda: T)
    assert ex2.submit("p2", gap, M, old_scan_start, T + timedelta(hours=2))["state"] == "submitted"


# ------------------------------------------------------------------ default ON for demo accounts (user request 2026-10-07)
def _ws(tmp_path, default_on=True):
    from app.fvg_execution import ExecutionOptIn
    return NS(fvg_optin=ExecutionOptIn(tmp_path / "optin.json"), fvg_user_off=tmp_path / "off.json",
              _fvg_binding=lambda a: {"source": "mt5", "symbol": "XAUUSD", "account": str(a.login), "strategy_version": "v"},
              _fvg_default_on_demo=lambda: default_on, fvg_status=lambda: {})


MT5C = NS(ACCOUNT_TRADE_MODE_DEMO=0)


def test_demo_accounts_are_on_by_default_including_after_an_account_switch(tmp_path):
    from app.web import Workstation
    ws = _ws(tmp_path)
    assert Workstation._fvg_armed(ws, NS(login=1, trade_mode=0), MT5C) == (True, None, "default (demo account)")
    assert Workstation._fvg_armed(ws, NS(login=2, trade_mode=0), MT5C)[0] is True  # another demo account: still ON


def test_real_and_contest_accounts_are_never_on_by_default(tmp_path):
    from app.web import Workstation
    ws = _ws(tmp_path)
    for mode, word in ((1, "contest account"), (2, "real-money account"), (None, "account type unknown"), (7, "account type unknown")):
        on, why, _ = Workstation._fvg_armed(ws, NS(login=1, trade_mode=mode), MT5C)
        assert on is False and word in why
    ws.fvg_optin.arm(ws._fvg_binding(NS(login=7)), T0)  # an explicit arming for THAT real account still works
    assert Workstation._fvg_armed(ws, NS(login=7, trade_mode=2), MT5C) == (True, None, "you")
    assert Workstation._fvg_armed(ws, NS(login=8, trade_mode=2), MT5C)[0] is False


def test_explicit_off_beats_the_default_until_turned_on_again(tmp_path):
    from app.web import Workstation
    ws = _ws(tmp_path)
    Workstation.fvg_arm(ws, False)  # the user's Turn OFF
    assert ws.fvg_user_off.exists()
    assert Workstation._fvg_armed(ws, NS(login=1, trade_mode=0), MT5C) == (False, "turned OFF by you", None)
    assert Workstation._fvg_armed(ws, NS(login=2, trade_mode=0), MT5C)[0] is False  # also after an account switch
    ws.fvg_user_off.unlink()  # what a successful Turn ON does
    assert Workstation._fvg_armed(ws, NS(login=1, trade_mode=0), MT5C)[0] is True


def test_no_default_when_the_setting_is_off_or_missing(tmp_path):
    from app.web import Workstation
    ws = _ws(tmp_path, default_on=False)
    assert Workstation._fvg_armed(ws, NS(login=1, trade_mode=0), MT5C) == (False, "not armed", None)
    real = Workstation._fvg_default_on_demo(NS(fvg_execution_path=tmp_path / "missing.json"))
    assert real is False
    (tmp_path / "bad.json").write_text('{"default_on_for_demo_accounts": "yes"}', encoding="utf-8")
    assert Workstation._fvg_default_on_demo(NS(fvg_execution_path=tmp_path / "bad.json")) is False
