"""Regressions for task 20261007-161242 (Codex + Claude reviews): each test fails against the pre-fix behaviour.
Fake brokers/feeds/delivery only; nothing is sent anywhere."""
from datetime import timedelta
from types import SimpleNamespace as NS

import pytest

from app.config import StrategyConfig
from app.fvg import contiguous_run, detect_gap
from app.fvg_execution import (MAGIC, ExecutionJournal, MT5FvgExecutor, OtherAccountError, UnverifiableAccountError,
                               account_fp, account_id, leg_comment)
from app.fvg_live import FvgLiveEngine, basket_is_open
from app.models import M5, Bar, aggregate
from app.outcomes import track_live, track_measured

from .test_fvg import META as XMETA, T, candles
from .test_fvg_engine import (CFG, M15, META, T0, ArmedBroker, Quote, drive, flat, make_engine, quote_fn, scenario)
from .test_fvg_execution import LOGIN, SERVER, Broker, _order, policy, submit
from .test_live_market import CFG as LCFG, NOW, make_signal, q
from app.fastsweep import BUY
from app.fvg import Gap


def gap():
    a, _, c = candles()
    return Gap(BUY, 100, 110, a, c)


# ===================================================================== 1. server + login identity
def test_same_login_on_another_server_is_another_account_for_consent_and_submission(tmp_path):
    a, b = NS(server="Broker-A", login=LOGIN), NS(server="Broker-B", login=LOGIN)
    assert account_id(a) != account_id(b) and str(LOGIN) not in account_id(a)
    broker = Broker()
    broker.account.server = "Broker-B"  # terminal switched server, same login number
    ex = MT5FvgExecutor(lambda: broker, ExecutionJournal(tmp_path / "j.sqlite"), policy(account_server="Broker-A"))
    with pytest.raises(ValueError, match="server\\+login"):
        submit(ex, gap())
    assert broker.requests == []


def test_reconcile_and_cancel_refuse_a_server_switch_with_the_same_login(tmp_path):
    broker = Broker()
    journal = ExecutionJournal(tmp_path / "j.sqlite")
    ex = MT5FvgExecutor(lambda: broker, journal, policy())
    assert submit(ex, gap())["state"] == "submitted"
    broker.account.server = "Other-Server"
    with pytest.raises(OtherAccountError):
        ex.reconcile("abc123", T)
    with pytest.raises(OtherAccountError):
        ex.cancel_remaining("abc123", "zone invalidated", T)
    assert broker.removed == []


def test_legacy_login_only_consent_never_matches_a_server_bound_binding():
    from app.web import Workstation
    ws = NS(mode="mt5", settings=NS(symbol="XAUUSD"), active=NS(is_fvg=True, fvg=NS(version="v")))
    acct = NS(server="MetaQuotes-Demo", login=LOGIN)
    binding = Workstation._fvg_binding(ws, acct)
    legacy = {**binding, "account": account_fp(LOGIN)}  # what a pre-fix opt-in stored
    assert binding["account"] == account_id(acct) and legacy != binding


def test_legacy_journal_without_server_identity_stays_tracked_and_unresolved(tmp_path):
    bars, _, _ = scenario()
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=True)
    drive(bars, eng)
    (b,) = fstore.baskets()
    payload = journal.get(b["plan_id"])
    payload.pop("account_id")  # what a pre-fix journal looked like
    payload["account_fp"] = account_fp(77)
    journal.save(b["plan_id"], payload)
    for k in range(4):
        eng.reconcile(bars[-1].close_time + timedelta(seconds=5 * k))
    (b,) = fstore.baskets()
    assert "legacy journal without server identity" in b["other_account"]
    assert journal.get(b["plan_id"]) is not None  # kept for manual review, not deleted or adopted
    warnings = [e for e in eng.events.list_events(100) if "legacy journal" in e["message"]]
    assert len(warnings) == 1
    with pytest.raises(UnverifiableAccountError):
        MT5FvgExecutor(lambda: broker, journal, policy()).reconcile(b["plan_id"], T0)


def test_capacity_is_scoped_to_the_connected_account(tmp_path):
    bars, _, tc = scenario()
    eng, fstore, broker, alerts, _ = make_engine(tmp_path, armed=True)
    fstore.add_basket({"id": "A1", "plan_id": "A1", "symbol": META.name, "version": CFG.version, "status": "orders_pending",
                       "placed_at": (tc - timedelta(minutes=50)).isoformat(), "pending_expires": (tc + timedelta(hours=1)).isoformat(),
                       "accepted": True, "direction": BUY, "bottom": 1, "top": 2, "sl": 0.9, "legs": [],
                       "execution": {"state": "submitted"}, "account_id": "srv1-account-A"})
    eng.account_fn = lambda: "srv1-account-B"
    drive(bars, eng)
    ids = [b["id"] for b in fstore.baskets()]
    assert "A1" in ids and len(ids) == 2  # A's basket stays tracked; it does not block account B
    eng2, fstore2, broker2, _, _ = make_engine(tmp_path, armed=True, name="same")
    fstore2.add_basket({**fstore.baskets(symbol=META.name)[-1], "id": "A2", "plan_id": "A2", "account_id": "srv1-account-A",
                        "execution": {"state": "submitted"}, "status": "orders_pending",
                        "placed_at": (tc - timedelta(minutes=50)).isoformat()})
    eng2.account_fn = lambda: "srv1-account-A"
    drive(bars, eng2)
    assert [b["id"] for b in fstore2.baskets()] == ["A2"] and broker2.requests == []  # same account: blocked


# ===================================================================== 2. decision-time freshness
def test_three_hour_old_confirmation_with_a_fresh_quote_is_never_alerted_or_submitted(tmp_path):
    bars, _, tc = scenario()
    eng, fstore, broker, alerts, _ = make_engine(tmp_path, armed=True)
    for i, b in enumerate(bars):  # a delayed healthy scan processes the backlog 3 hours late
        eng.process_bar(bars, i, quote_fn(0.05), b.close_time + timedelta(hours=3))
    assert fstore.baskets() == [] and alerts == [] and broker.requests == []
    reasons = [s.reason for s in fstore.list_setups()]
    assert any(r and (r.startswith("setup_expired_at_decision") or r.startswith("confirmation_too_old")) for r in reasons)
    for i, b in enumerate(bars):  # the next scan cannot re-emit it
        eng.process_bar(bars, i, quote_fn(0.05), b.close_time + timedelta(seconds=1))
    assert fstore.baskets() == [] and broker.requests == []


@pytest.mark.parametrize("delay,accepted", [(30, True), (31, False), (-2, False)])
def test_confirmation_age_boundary(tmp_path, delay, accepted):
    bars, _, tc = scenario()
    confirm_close = tc + 3 * M5
    eng, fstore, broker, alerts, _ = make_engine(tmp_path, armed=True, name=f"d{delay}")
    frozen = confirm_close + timedelta(seconds=delay)  # deterministic executor clock at the decision instant
    real_fn = eng.executor_fn

    def executor_fn():
        ex, why = real_fn()
        if ex is not None:
            ex.clock = lambda: frozen
        return ex, why
    eng.executor_fn = executor_fn
    for i, b in enumerate(bars):
        now = b.close_time + timedelta(seconds=delay if b.close_time == confirm_close else 1)
        eng.process_bar(bars, i, quote_fn(0.05), now)
    assert (len(broker.requests) == 3) is accepted
    if not accepted:
        want = "confirmation_too_old" if delay > 0 else "confirmation_in_future"
        assert any((x.reason or "").startswith(want) for x in fstore.list_setups()) and alerts == []


# ===================================================================== 3. post-send exceptions
def test_unreadable_journal_after_an_error_is_uncertain_then_resolved_from_storage(tmp_path):
    bars, _, _ = scenario()
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=True)
    real_get, real_create = journal.get, journal.create
    state = {"broken": True}

    def get(pid):
        if state["broken"]:
            raise RuntimeError("database is locked")
        return real_get(pid)

    def create(pid, payload):
        raise RuntimeError("disk I/O error")  # fails BEFORE any row exists: nothing can have been sent
    journal.get, journal.create = get, create
    drive(bars, eng)
    (b,) = fstore.baskets()
    assert b["status"] == "needs_reconciliation" and b["execution"]["uncertain"] and broker.requests == []
    assert basket_is_open(b, bars[-1].close_time)  # tracked, never shown as a preflight rejection
    state["broken"] = False
    eng.reconcile(bars[-1].close_time + timedelta(seconds=5))
    (b,) = fstore.baskets()
    assert b["status"] == "interrupted_unsubmitted" and broker.requests == []


def test_genuine_preflight_failure_without_journal_row_stays_rejected(tmp_path):
    bars, _, _ = scenario()
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=True)
    broker.check_code = 10014  # broker preflight refuses: no row, no send
    drive(bars, eng)
    (b,) = fstore.baskets()
    assert b["status"] == "preflight_rejected" and journal.rows() == [] and broker.requests == []


# ===================================================================== 4. fill racing the remainder cancellation
def _submitted(tmp_path):
    broker = Broker()
    journal = ExecutionJournal(tmp_path / "j.sqlite")
    ex = MT5FvgExecutor(lambda: broker, journal, policy())
    submit(ex, gap())
    return broker, journal, ex


def test_partial_fill_since_last_reconcile_is_kept_when_the_remainder_is_cancelled(tmp_path):
    broker, journal, ex = _submitted(tmp_path)  # stored legs still say "pending": no reconcile since the fill
    live1 = NS(**vars(_order(101, 1, broker.ORDER_STATE_PARTIAL)), volume_current=0.4)
    broker.orders = (live1, _order(102, 2, broker.ORDER_STATE_PLACED), _order(103, 3, broker.ORDER_STATE_PLACED))
    broker.positions = (NS(identifier=101, ticket=101, symbol=XMETA.name, magic=MAGIC, comment=leg_comment("abc123", 1)),)
    broker.deals = (NS(order=101, position_id=101, entry=broker.DEAL_ENTRY_IN, volume=0.6, reason=0, price=0.0, profit=0.0,
                       commission=-0.2, swap=0.0, fee=0.0),)
    out = ex.cancel_remaining("abc123", "zone invalidated", T)
    leg1 = out["legs"][0]
    assert sorted(broker.removed) == [101, 102, 103]
    assert leg1["state"] == "filled_open" and leg1["remainder"] == "cancelled" and leg1["filled_volume"] == 0.6
    assert [l["state"] for l in out["legs"][1:]] == ["cancelled", "cancelled"] and out["state"] != "closed"
    for k in range(3):  # later reconciles never close the basket while its position is open
        assert ex.reconcile("abc123", T + timedelta(minutes=5 * (k + 1)))["state"] != "closed"


def test_delayed_history_after_removal_keeps_the_leg_open_until_evidence_arrives(tmp_path):
    broker, journal, ex = _submitted(tmp_path)
    broker.orders = (_order(101, 1, broker.ORDER_STATE_PLACED),)
    real_send = broker.order_send

    def send(request):  # removal accepted, but the order is not in history yet
        r = real_send(request)
        broker.history = ()
        return r
    broker.order_send = send
    out = ex.cancel_remaining("abc123", "zone invalidated", T)
    assert out["legs"][0]["state"] == "pending" and out["legs"][0]["cancel"] == "zone invalidated"
    broker.history = (NS(**{**vars(_order(101, 1, broker.ORDER_STATE_PARTIAL)), "state": broker.ORDER_STATE_CANCELED}),)
    broker.deals = (NS(order=101, position_id=101, entry=broker.DEAL_ENTRY_IN, volume=0.3, reason=0, price=0.0, profit=0.0,
                       commission=0.0, swap=0.0, fee=0.0),)
    broker.positions = (NS(identifier=101, ticket=101, symbol=XMETA.name, magic=MAGIC),)
    leg = ex.reconcile("abc123", T + timedelta(minutes=1))["legs"][0]
    assert leg["state"] == "filled_open" and leg["remainder"] == "cancelled"


def test_cancelled_leg_is_re_examined_and_basket_closes_only_after_settling(tmp_path):
    broker, journal, ex = _submitted(tmp_path)
    broker.history = tuple(NS(**{**vars(_order(t, n, broker.ORDER_STATE_CANCELED))}) for t, n in ((101, 1), (102, 2), (103, 3)))
    first = ex.reconcile("abc123", T)
    assert [l["state"] for l in first["legs"]] == ["cancelled"] * 3 and first["state"] != "closed"  # not yet settled
    broker.deals = (NS(order=101, position_id=101, entry=broker.DEAL_ENTRY_IN, volume=0.2, reason=0, price=0.0, profit=0.0,
                       commission=0.0, swap=0.0, fee=0.0),)  # a fill shows up late in deal history
    broker.positions = (NS(identifier=101, ticket=101, symbol=XMETA.name, magic=MAGIC),)
    late = ex.reconcile("abc123", T + timedelta(seconds=30))
    assert late["legs"][0]["state"] == "filled_open" and late["state"] != "closed"
    broker.positions = ()
    broker.deals += (NS(order=900, position_id=101, entry=broker.DEAL_ENTRY_OUT, volume=0.2, reason=broker.DEAL_REASON_SL,
                        price=99.0, profit=-3.0, commission=0.0, swap=0.0, fee=0.0),)
    assert ex.reconcile("abc123", T + timedelta(minutes=2))["state"] != "closed"  # terminal first seen now
    done = ex.reconcile("abc123", T + timedelta(minutes=4))
    assert done["state"] == "closed" and done["legs"][0]["state"] == "closed_sl"


# ===================================================================== 5. invalid constituents
def _m5(t, o, h, l, c, tf=M5):
    return Bar(t, tf, o, h, l, c)


def test_one_invalid_constituent_voids_its_group_and_breaks_the_run():
    start = T0
    good = [_m5(start + k * M5, 100, 101, 99, 100.5) for k in range(9)]
    bad = list(good)
    bad[4] = _m5(start + 4 * M5, 100, 99.5, 98, 99)  # high below open: invalid, hidden by neighbours' highs before the fix
    assert len(aggregate(good, M15)) == 3
    agg = aggregate(bad, M15)
    assert [b.open_time for b in agg] == [start, start + 2 * M15]  # the middle M15 group is skipped
    assert len(contiguous_run(agg)) == 1  # the gap is preserved: warm-up cannot bridge it
    wrong_tf = list(good)
    wrong_tf[1] = _m5(start + M5, 100, 101, 99, 100.5, tf=M15)
    assert [b.open_time for b in aggregate(wrong_tf, M15)] == [start + M15, start + 2 * M15]


def test_invalid_constituent_in_candle_a_cannot_qualify_an_fvg(tmp_path):
    bars, ta, tc = scenario()
    i = next(k for k, b in enumerate(bars) if b.open_time == ta + M5)
    b = bars[i]
    bars[i] = Bar(b.open_time, M5, b.open, b.open - 0.01, b.low, b.close)  # high < open
    h15 = aggregate(bars, M15)
    assert not any(x.open_time == ta for x in h15)
    eng, fstore, broker, alerts, _ = make_engine(tmp_path, armed=True)
    drive(bars, eng)
    assert fstore.baskets() == [] and broker.requests == []


# ===================================================================== 6. legacy outcome expiry
def test_measured_tp_after_expiry_never_overrides_the_expiry():
    sig = make_signal("mt5", "BUY")
    sig.meta["outcome_expiry_hours"] = 2
    obs = [q(119 * 60, 2400.5, 2400.7), q(150 * 60, 2411.0, 2411.2)]  # safe tick at 119 min, TP tick at 150 min
    assert track_measured(sig, obs, NOW + timedelta(hours=3), LCFG)
    assert sig.outcome_status == "expired" and sig.outcome_time == NOW + timedelta(hours=2)
    assert sig.outcome_price == 2400.5  # last eligible exit-side (Bid) price before the deadline


def test_measured_tick_at_the_deadline_still_counts():
    sig = make_signal("mt5", "BUY")
    sig.meta["outcome_expiry_hours"] = 2
    assert track_measured(sig, [q(120 * 60, 2411.0, 2411.2)], NOW + timedelta(hours=3), LCFG)
    assert sig.outcome_status == "tp"


def test_bar_estimate_ignores_bars_after_the_deadline():
    sig = make_signal("demo", "BUY")
    sig.meta["outcome_expiry_hours"] = 2
    late = Bar(NOW + timedelta(minutes=125), M5, 2400.5, 2412.0, 2400.0, 2411.0)
    assert track_live(sig, [late], None, NOW + timedelta(hours=3), LCFG, False)
    assert sig.outcome_status == "expired" and sig.outcome_time == NOW + timedelta(hours=2)


# ===================================================================== 7. paused / stale maintenance
def test_far_edge_breach_then_return_inside_still_cancels(tmp_path):
    bars, _, tc = scenario(tail=flat(120.2, 2) + [(120.2, 120.2, 116.0, 116.5), (116.5, 118.5, 116.4, 118.2)] + flat(118.2, 2))
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=True)
    first_tail = tc + 5 * M5  # up to (not including) the far-edge close at tc + 6 x M5
    head = [b for b in bars if b.close_time <= first_tail]
    drive(head, eng)
    (b,) = fstore.baskets()
    broker.orders = tuple(NS(ticket=100 + n, comment=f"FVG-{b['plan_id']}-L{n}", symbol=META.name, magic=MAGIC, state=1)
                          for n in (1, 2, 3))
    eng.manage_baskets(bars, bars[-1].close_time + timedelta(seconds=1))  # catch-up after a pause/stale period
    assert sorted(broker.removed) == [101, 102, 103]
    assert fstore.baskets()[0]["zone_invalidated_at"]


def test_maintenance_waits_for_trusted_fresh_quotes(tmp_path):
    from .test_fvg_engine import scanner, step
    bars, ta, tc = scenario(tail=flat(120.2, 3) + [(120.2, 120.2, 116.0, 116.5)] + flat(118.2, 3))
    sc, feed, store, fstore, broker = scanner(tmp_path, bars, tc - timedelta(minutes=10), armed=True)
    store.set_meta("last_m5_close", (ta - M15).isoformat())
    step(sc, feed, tc + 3 * M5 + timedelta(minutes=12))
    (b,) = fstore.baskets()
    broker.orders = tuple(NS(ticket=100 + n, comment=f"FVG-{b['plan_id']}-L{n}", symbol=META.name, magic=MAGIC, state=1)
                          for n in (1, 2, 3))
    real_quote = feed.quote
    feed.quote = lambda: Quote(feed._now - timedelta(hours=1), 118.0, 118.05)  # stale: untrusted context
    step(sc, feed, tc + 3 * M5 + timedelta(minutes=35))
    assert broker.removed == []
    feed.quote = real_quote  # fresh again: the skipped far-edge close is applied
    step(sc, feed, tc + 3 * M5 + timedelta(minutes=36))
    assert sorted(broker.removed) == [101, 102, 103]


# ===================================================================== task 20261007-164056
from app.fvg_execution import ExecutionOptIn  # noqa: E402


def _ws(tmp_path, default_on=True):
    return NS(fvg_optin=ExecutionOptIn(tmp_path / "optin.json"), fvg_user_off=tmp_path / "off.json",
              _fvg_binding=lambda a: {"source": "mt5", "symbol": "XAUUSD", "account": account_id(a), "strategy_version": "v"},
              _fvg_default_on_demo=lambda: default_on, fvg_status=lambda: {})


MT5C = NS(ACCOUNT_TRADE_MODE_DEMO=0, ACCOUNT_TRADE_MODE_CONTEST=1, ACCOUNT_TRADE_MODE_REAL=2)


# ---------------------------------------------------------------- A. demo default / explicit OFF / exact consent
def test_a_any_verified_demo_account_is_on_by_default_without_an_exact_opt_in(tmp_path):
    from app.web import Workstation
    ws = _ws(tmp_path)
    assert Workstation._fvg_armed(ws, NS(server="Demo-A", login=1, trade_mode=0), MT5C) == (True, None, "default (demo account)")
    assert Workstation._fvg_armed(ws, NS(server="Demo-B", login=1, trade_mode=0), MT5C)[0] is True


def test_a_explicit_off_beats_default_and_a_stale_matching_opt_in_and_survives_restart(tmp_path):
    from app.web import Workstation
    ws = _ws(tmp_path)
    acct = NS(server="Demo-A", login=1, trade_mode=0)
    ws.fvg_optin.arm(ws._fvg_binding(acct), T0)        # an inconsistent leftover opt-in for this exact account
    ws.fvg_user_off.write_text("{}", encoding="utf-8")  # the user's explicit OFF
    assert Workstation._fvg_armed(ws, acct, MT5C) == (False, "turned OFF by you", None)
    restarted = _ws(tmp_path)                            # same files after a restart / account switch
    assert Workstation._fvg_armed(restarted, NS(server="Demo-B", login=2, trade_mode=0), MT5C)[0] is False


def test_a_real_contest_unknown_need_exact_consent_even_with_the_demo_default(tmp_path):
    from app.web import Workstation
    ws = _ws(tmp_path)
    for mode in (1, 2, None, 99):
        assert Workstation._fvg_armed(ws, NS(server="Live-1", login=5, trade_mode=mode), MT5C)[0] is False
    real = NS(server="Live-1", login=5, trade_mode=2)
    ws.fvg_optin.arm(ws._fvg_binding(real), T0)
    assert Workstation._fvg_armed(ws, real, MT5C) == (True, None, "you")
    assert Workstation._fvg_armed(ws, NS(server="Live-2", login=5, trade_mode=2), MT5C)[0] is False  # its own binding only


def test_a_account_switch_during_preflight_refuses_submission(tmp_path):
    broker = Broker()
    real_check = broker.order_check

    def order_check(request):  # the terminal switches server mid-preflight
        broker.account.server = "Other-Server"
        return real_check(request)
    broker.order_check = order_check
    ex = MT5FvgExecutor(lambda: broker, ExecutionJournal(tmp_path / "j.sqlite"), policy())
    with pytest.raises(ValueError, match=r"server\+login"):
        submit(ex, gap())
    assert broker.requests == []


# ---------------------------------------------------------------- B. current decision clock + send-time freshness
def test_b_codex_probe_old_scan_clock_with_current_callback_time_sends_nothing(tmp_path):
    bars, _, tc = scenario()
    confirm = tc + 3 * M5
    actual = confirm + timedelta(seconds=121)
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=True)
    broker.set_quote(actual, 120.2, 120.25)  # quotes are fresh against the CURRENT clock
    ex = MT5FvgExecutor(lambda: broker, journal, policy(symbol=META.name, strategy_version=CFG.version), clock=lambda: actual)
    eng.executor_fn = lambda: (ex, "ON")
    for i, b in enumerate(bars):  # scan start = bar close + 1 s, but the decision really happens at +121 s
        eng.process_bar(bars, i, lambda c, bar: (Quote(actual, 120.2, 120.25), actual), b.close_time + timedelta(seconds=1))
    assert fstore.baskets() == [] and alerts == [] and broker.requests == []
    assert any((s.reason or "").startswith("confirmation_too_old") for s in fstore.list_setups())


def test_b_slow_preflight_crossing_the_age_limit_sends_nothing(tmp_path):
    broker = Broker()
    clock = {"t": T}
    real_check = broker.order_check

    def slow_check(request):
        clock["t"] += timedelta(seconds=11)  # 3 checks -> 33 s
        return real_check(request)
    broker.order_check = slow_check
    journal = ExecutionJournal(tmp_path / "j.sqlite")
    ex = MT5FvgExecutor(lambda: broker, journal, policy(), clock=lambda: clock["t"])
    elig = {"confirm_close": T - timedelta(seconds=1), "setup_expires": T + timedelta(hours=1), "max_age_seconds": 30}
    stamp = T.timestamp() + 33
    broker.ticks = [NS(bid=111.0, ask=111.2, time=T.timestamp(), time_msc=int(T.timestamp() * 1000)),
                    NS(bid=111.0, ask=111.2, time=stamp, time_msc=int(stamp * 1000))]
    with pytest.raises(ValueError, match="no longer eligible after preflight"):
        ex.submit("abc123", gap(), XMETA, T, T + timedelta(hours=2), eligibility=elig)
    assert broker.requests == [] and journal.rows() == []


def test_b_delay_between_sends_stops_the_rest_and_keeps_accepted_legs(tmp_path):
    broker = Broker()
    clock = {"t": T}
    real_send = broker.order_send

    def slow_send(request):
        r = real_send(request)
        clock["t"] += timedelta(seconds=40)  # the broker took 40 s to answer
        return r
    broker.order_send = slow_send
    journal = ExecutionJournal(tmp_path / "j.sqlite")
    ex = MT5FvgExecutor(lambda: broker, journal, policy(), clock=lambda: clock["t"])
    elig = {"confirm_close": T - timedelta(seconds=1), "setup_expires": T + timedelta(hours=1), "max_age_seconds": 30}
    out = ex.submit("abc123", gap(), XMETA, T, T + timedelta(hours=2), eligibility=elig)
    assert len(broker.requests) == 1 and out["state"] == "partial"
    assert [l["state"] for l in out["legs"]] == ["pending", "not_sent", "not_sent"] and "stopped before leg 2" in out["reason"]
    assert ex.submit("abc123", gap(), XMETA, T, T + timedelta(hours=2), eligibility=elig) == out  # idempotent, no resend
    assert len(broker.requests) == 1


# ---------------------------------------------------------------- C. durable invalidation + verified cancellation retry
def _armed_basket(tmp_path, name="c"):
    bars, _, tc = scenario()
    eng, fstore, broker, alerts, journal = make_engine(tmp_path, armed=True, name=name)
    drive(bars, eng)
    (b,) = fstore.baskets()
    legs = journal.get(b["plan_id"])["legs"]
    broker.orders = tuple(NS(ticket=l["ticket"], comment=l["comment"], symbol=META.name, magic=MAGIC,
                             state=broker.ORDER_STATE_PLACED, volume_current=l["volume"]) for l in legs)
    far = Bar(bars[-1].close_time, M5, 117.0, 117.1, 116.5, 116.59)  # BUY zone bottom 116.60: far-edge close
    inside = Bar(far.close_time, M5, 116.8, 117.1, 116.7, 117.0)
    return eng, fstore, broker, alerts, journal, far, inside


def _remove_with(broker, retcode, actually_remove=False):
    real_send = broker.order_send

    def send(request):
        if request["action"] == broker.TRADE_ACTION_REMOVE:
            if actually_remove:
                real_send(request)
            broker.removed.append(("attempt", request["order"]))
            return NS(retcode=retcode, order=0)
        return real_send(request)
    broker.order_send = send
    return real_send


def _done(broker):
    return sorted(x for x in broker.removed if isinstance(x, int))


def _attempts(broker):
    return [x for x in broker.removed if isinstance(x, tuple)]


def test_c_codex_probe_timeout_then_recovery_and_return_inside_removes_the_remainders(tmp_path):
    eng, fstore, broker, alerts, journal, far, inside = _armed_basket(tmp_path)
    real_send = _remove_with(broker, broker.TRADE_RETCODE_TIMEOUT)
    eng.manage_baskets([far], far.close_time + timedelta(seconds=1))
    (b,) = fstore.baskets()
    assert b["zone_invalidated_at"] and b["cancel_complete"] is False and len(broker.orders) == 3
    broker.order_send = real_send  # connectivity restored; price returned inside the zone
    t = inside.close_time + timedelta(seconds=40)
    eng.reconcile(t)
    eng.manage_baskets([far, inside], t)
    (b,) = fstore.baskets()
    assert broker.orders == () and _done(broker) == [101, 102, 103]
    assert b["cancel_complete"] is True and b["zone_invalidated_at"]
    assert len(alerts) == 1 and len(broker.requests) == 3  # maintenance created no new alert or order


def test_c_rejected_removal_is_retried_on_cadence_until_proven(tmp_path):
    eng, fstore, broker, alerts, journal, far, _ = _armed_basket(tmp_path)
    real_send = _remove_with(broker, 10013)  # explicit rejection, orders still live
    t0 = far.close_time + timedelta(seconds=1)
    eng.manage_baskets([far], t0)
    eng.reconcile(t0 + timedelta(seconds=5))  # within the 30 s cadence: no new attempt
    assert len(_attempts(broker)) == 3 and fstore.baskets()[0]["cancel_complete"] is False
    broker.order_send = real_send
    eng.reconcile(t0 + timedelta(seconds=31))
    assert broker.orders == () and fstore.baskets()[0]["cancel_complete"] is True


def test_c_unreadable_pending_list_is_unknown_not_empty(tmp_path):
    eng, fstore, broker, alerts, journal, far, _ = _armed_basket(tmp_path)
    live = broker.orders
    broker.orders = None  # orders_get() returns None: the broker's pending orders cannot be seen
    eng.manage_baskets([far], far.close_time + timedelta(seconds=1))
    b = fstore.baskets()[0]
    assert b["cancel_complete"] is False and b["execution"]["cancel_state"] == "unknown" and broker.removed == []
    broker.orders = live
    eng.reconcile(far.close_time + timedelta(seconds=40))
    assert broker.orders == () and fstore.baskets()[0]["cancel_complete"] is True


def test_c_unknown_removal_that_actually_succeeded_is_not_duplicated(tmp_path):
    eng, fstore, broker, alerts, journal, far, _ = _armed_basket(tmp_path)
    real_send = _remove_with(broker, broker.TRADE_RETCODE_TIMEOUT, actually_remove=True)
    eng.manage_baskets([far], far.close_time + timedelta(seconds=1))
    assert broker.orders == ()  # the broker did remove them despite the timeout answers
    first = len(_attempts(broker))
    broker.order_send = real_send
    eng.reconcile(far.close_time + timedelta(seconds=40))
    assert len(_attempts(broker)) == first and _done(broker) == [101, 102, 103]  # verified absent: no re-removal
    assert fstore.baskets()[0]["cancel_complete"] is True


def test_c_account_switch_pauses_cancellation_and_return_resumes_it(tmp_path):
    eng, fstore, broker, alerts, journal, far, _ = _armed_basket(tmp_path)
    broker.account.server = "Other-Server"
    eng.manage_baskets([far], far.close_time + timedelta(seconds=1))
    b = fstore.baskets()[0]
    assert b["zone_invalidated_at"] and b["other_account"] and broker.removed == [] and len(broker.orders) == 3
    broker.account.server = SERVER  # the original server+login is connected again
    eng.reconcile(far.close_time + timedelta(seconds=40))
    eng.reconcile(far.close_time + timedelta(seconds=80))
    assert broker.orders == () and fstore.baskets()[0]["cancel_complete"] is True


def test_c_partial_fill_during_retry_keeps_the_position(tmp_path):
    eng, fstore, broker, alerts, journal, far, _ = _armed_basket(tmp_path)
    real_send = _remove_with(broker, broker.TRADE_RETCODE_TIMEOUT)
    eng.manage_baskets([far], far.close_time + timedelta(seconds=1))
    first = broker.orders[0]
    broker.orders = (NS(**{**vars(first), "state": broker.ORDER_STATE_PARTIAL, "volume_current": 0.5}),) + broker.orders[1:]
    broker.deals = (NS(order=first.ticket, position_id=first.ticket, entry=broker.DEAL_ENTRY_IN, volume=0.3, reason=0,
                       price=0.0, profit=0.0, commission=0.0, swap=0.0, fee=0.0),)
    broker.positions = (NS(identifier=first.ticket, ticket=first.ticket, symbol=META.name, magic=MAGIC),)
    broker.order_send = real_send
    eng.reconcile(far.close_time + timedelta(seconds=40))
    b = fstore.baskets()[0]
    leg1 = b["execution"]["legs"][0]
    assert b["cancel_complete"] is True and leg1["state"] == "filled_open" and leg1["remainder"] == "cancelled"
    assert broker.positions  # the filled position and its broker SL/TP are untouched


def test_c_invalid_raw_bar_never_invalidates(tmp_path):
    eng, fstore, broker, alerts, journal, far, _ = _armed_basket(tmp_path)
    bad = Bar(far.open_time, M5, 117.0, 116.9, 116.5, 116.59)  # high below open: invalid
    eng.manage_baskets([bad], far.close_time + timedelta(seconds=1))
    b = fstore.baskets()[0]
    assert not b.get("zone_invalidated_at") and broker.removed == [] and len(broker.orders) == 3
