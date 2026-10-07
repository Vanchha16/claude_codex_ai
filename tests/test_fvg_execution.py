"""FVG broker adapter with a FAKE MetaTrader5 module only (no MT5 terminal, no Telegram, no real orders)."""
import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace as NS

import pytest

from app.fvg import Gap
from app.fvg_execution import (DOC_CONSTANTS, MAGIC, ExecutionJournal, ExecutionOptIn, ExecutionPolicy, MT5FvgExecutor,
                               account_fp, leg_comment, load_risk_usd)
from app.fvg_orders import account_cash_risk
from .test_fvg import BUY, META, T, candles

LOGIN = 77


class Broker:
    """Constants mirror the INSTALLED MetaTrader5 5.0.6231 exports (SYMBOL_ORDER_* / SYMBOL_EXPIRATION_* /
    SYMBOL_FILLING_* are deliberately absent, as in the real package)."""
    ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2
    SYMBOL_TRADE_MODE_FULL = 4
    ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT = 0, 1, 2, 3
    TRADE_ACTION_PENDING, TRADE_ACTION_REMOVE = 5, 8
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    ORDER_TIME_SPECIFIED = 2
    TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED, TRADE_RETCODE_TIMEOUT, TRADE_RETCODE_CONNECTION = 10009, 10008, 10012, 10031
    ORDER_STATE_STARTED, ORDER_STATE_PLACED, ORDER_STATE_CANCELED, ORDER_STATE_PARTIAL = 0, 1, 2, 3
    ORDER_STATE_FILLED, ORDER_STATE_REJECTED, ORDER_STATE_EXPIRED = 4, 5, 6
    DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_REASON_SL, DEAL_REASON_TP = 0, 1, 4, 5

    def __init__(self, currency="USD"):
        self.requests, self.removed = [], []
        self.fail_at = self.fail_code = None
        self.check_code = 0
        self.orders, self.history, self.positions, self.deals = (), (), (), ()
        self.account = NS(login=LOGIN, equity=200.0, margin_free=10000.0, margin_mode=2, trade_allowed=True,
                          trade_expert=True, currency=currency)
        self.symbol = NS(trade_mode=4, trade_tick_size=0.01, point=0.01, digits=2, volume_min=0.01, volume_max=100.0,
                         volume_step=0.01, trade_stops_level=0, order_mode=2 | 1, expiration_mode=4 | 1, filling_mode=1)
        self.ticks = [NS(bid=111.0, ask=111.2, time=T.timestamp(), time_msc=int(T.timestamp() * 1000))]
        self.tick_calls = 0

    def terminal_info(self):
        return NS(connected=True, trade_allowed=True, tradeapi_disabled=False)

    def account_info(self):
        return self.account

    def symbol_info(self, symbol):
        return self.symbol

    def symbol_info_tick(self, symbol):
        self.tick_calls += 1
        return self.ticks[min(self.tick_calls, len(self.ticks)) - 1]

    def orders_get(self, **kwargs):
        return self.orders

    def positions_get(self, **kwargs):
        return self.positions

    def history_orders_get(self, *args):
        return self.history

    def history_deals_get(self, *args):
        return self.deals

    def order_calc_profit(self, side, symbol, volume, entry, stop):
        return -abs(entry - stop) * 1.0 * volume  # 1 account unit per 1.00 price move per lot (fictional contract)

    def order_calc_margin(self, *args):
        return 10.0

    def order_check(self, request):
        return NS(retcode=self.check_code)

    def order_send(self, request):
        if request["action"] == self.TRADE_ACTION_REMOVE:
            self.removed.append(request["order"])
            return NS(retcode=self.TRADE_RETCODE_DONE, order=request["order"])
        self.requests.append(request)
        if len(self.requests) == self.fail_at:
            return None if self.fail_code is None else NS(retcode=self.fail_code, order=0)
        return NS(retcode=self.TRADE_RETCODE_PLACED, order=100 + len(self.requests))


def policy(**kw):
    base = dict(enabled=True, risk_usd=10.0, account_login=LOGIN, source="mt5", symbol=META.name, strategy_version="FVG-test")
    base.update(kw)
    return ExecutionPolicy(**base)


@pytest.fixture
def env(tmp_path):
    journal = ExecutionJournal(tmp_path / "orders.sqlite")
    broker = Broker()
    executor = MT5FvgExecutor(lambda: broker, journal, policy())
    a, _, c = candles()
    yield broker, journal, executor, Gap(BUY, 100, 110, a, c)
    journal.close()


def submit(executor, gap):
    return executor.submit("abc123", gap, META, T, T + timedelta(hours=2))


# ------------------------------------------------------------------ constants and arming
def test_doc_constants_match_mql5_and_are_absent_from_the_installed_package():
    assert DOC_CONSTANTS == {"SYMBOL_ORDER_LIMIT": 2, "SYMBOL_EXPIRATION_SPECIFIED": 4}
    mt5 = pytest.importorskip("MetaTrader5")  # read-only import; never initialize
    for name in DOC_CONSTANTS:
        assert not hasattr(mt5, name)
        assert not hasattr(Broker, name)


def test_default_policy_is_off_and_never_contacts_the_broker(env):
    broker, journal, _, gap = env
    off = MT5FvgExecutor(lambda: broker, journal, ExecutionPolicy())
    assert submit(off, gap)["state"] == "disabled"
    assert broker.requests == [] and broker.tick_calls == 0 and journal.rows() == []


def test_missing_risk_submits_nothing(env, tmp_path):
    broker, journal, _, gap = env
    unarmed = MT5FvgExecutor(lambda: broker, journal, ExecutionPolicy())
    assert submit(unarmed, gap)["reason"].startswith("automatic execution is OFF")
    with pytest.raises(ValueError):
        policy(risk_usd=None).validate()
    assert load_risk_usd(tmp_path / "none.json") is None
    (tmp_path / "bad.json").write_text(json.dumps({"risk_usd_per_setup": 0}))
    assert load_risk_usd(tmp_path / "bad.json") is None
    assert broker.requests == []


def test_arming_needs_a_complete_binding():
    for bad in (dict(account_login=None), dict(symbol=""), dict(source="demo"), dict(strategy_version=None)):
        with pytest.raises(ValueError):
            policy(**bad).validate()


def test_opt_in_binding_and_risk_preference_do_not_arm_each_other(tmp_path):
    optin = ExecutionOptIn(tmp_path / "optin.json")
    binding = {"source": "mt5", "symbol": META.name, "account": account_fp(LOGIN), "strategy_version": "v1"}
    assert not optin.matches(binding)  # default OFF, even with a configured risk preference
    optin.arm(binding, T)
    assert optin.matches(binding) and not optin.matches({**binding, "account": account_fp(88)})
    assert not optin.matches({**binding, "symbol": "OTHER"}) and not optin.matches({**binding, "strategy_version": "v2"})
    assert str(LOGIN) not in (tmp_path / "optin.json").read_text()  # login number never stored
    optin.disarm()
    assert not optin.matches(binding)


# ------------------------------------------------------------------ fixed 10 USD risk, sizing, currency
def test_three_limits_fixed_ten_usd_equal_shares_and_idempotent_restart(env):
    broker, journal, executor, gap = env
    result = submit(executor, gap)
    assert result["state"] == "submitted" and len(broker.requests) == 3
    assert [r["price"] for r in broker.requests] == [109.9, 105.0, 102.0]
    assert len({r["sl"] for r in broker.requests}) == 1 and broker.requests[0]["sl"] == 99.98
    for r in broker.requests:  # each TP is 2R from its own entry
        assert abs((r["tp"] - r["price"]) - 2 * (r["price"] - r["sl"])) < 0.011
        assert r["type"] == broker.ORDER_TYPE_BUY_LIMIT and r["magic"] == MAGIC and len(r["comment"]) <= 31
        assert r["type_time"] == broker.ORDER_TIME_SPECIFIED and r["expiration"] == int((T + timedelta(hours=2)).timestamp())
    legs = result["legs"]
    assert result["cash_risk_account_ccy"] == 10.0 and result["nominal_planned_loss"] <= 10.0 + 1e-9
    assert all(l["planned_loss"] <= 10 / 3 + 1e-9 for l in legs)
    assert legs[0]["volume"] < legs[1]["volume"] < legs[2]["volume"]  # wider stop distance -> fewer lots
    assert account_fp(LOGIN) == result["account_fp"] and "account_login" not in result
    restarted = MT5FvgExecutor(lambda: broker, journal, executor.policy)
    assert submit(restarted, gap) == result and len(broker.requests) == 3


def test_cent_account_is_converted_explicitly_and_other_currencies_are_rejected(env, tmp_path):
    broker, journal, executor, gap = env
    assert account_cash_risk(10.0, "USC") == 1000.0 and account_cash_risk(10.0, "usd") == 10.0
    with pytest.raises(ValueError):
        account_cash_risk(10.0, "EUR")
    broker.account.currency = "USC"
    result = submit(executor, gap)
    assert result["cash_risk_account_ccy"] == 1000.0 and result["nominal_planned_loss"] <= 1000.0
    broker2, j2 = Broker("EUR"), ExecutionJournal(tmp_path / "eur.sqlite")
    with pytest.raises(ValueError):
        MT5FvgExecutor(lambda: broker2, j2, policy()).submit("eur1", gap, META, T, T + timedelta(hours=2))
    assert broker2.requests == []
    j2.close()


def test_minimum_lot_that_exceeds_the_share_rejects_the_whole_plan(env):
    broker, journal, executor, gap = env
    broker.symbol.volume_min = 2.0  # leg 1 needs ~0.33 lots for its 3.33 USD share
    with pytest.raises(ValueError):
        submit(executor, gap)
    assert broker.requests == [] and journal.rows() == []


# ------------------------------------------------------------------ preflight and refreshed quote
@pytest.mark.parametrize("issue", ["account", "netting", "quote", "stops", "margin", "check", "exposure", "no_limit",
                                   "no_expiry", "spread", "trading_off"])
def test_preflight_rejects_entire_batch_before_any_send(env, issue):
    broker, journal, executor, gap = env
    if issue == "account":
        broker.account.login = 88
    elif issue == "netting":
        broker.account.margin_mode = 0
    elif issue == "quote":
        broker.ticks[0].time_msc -= 60000
    elif issue == "stops":
        broker.symbol.trade_stops_level = 2000
    elif issue == "margin":
        broker.account.margin_free = 1
    elif issue == "check":
        broker.check_code = 10016
    elif issue == "exposure":
        broker.positions = (NS(ticket=999, symbol=META.name, magic=1),)
    elif issue == "no_limit":
        broker.symbol.order_mode = 1
    elif issue == "no_expiry":
        broker.symbol.expiration_mode = 1
    elif issue == "spread":
        broker.ticks[0].ask = 111.6
    else:
        broker.account.trade_expert = False
    with pytest.raises(ValueError):
        submit(executor, gap)
    assert broker.requests == [] and journal.rows() == []


def test_limits_are_revalidated_on_the_refreshed_quote_before_the_first_send(env):
    broker, journal, executor, gap = env
    first = broker.ticks[0]
    broker.ticks = [first, NS(bid=109.5, ask=109.7, time=first.time, time_msc=first.time_msc)]  # leg 1 now crossed
    with pytest.raises(ValueError):
        submit(executor, gap)
    assert broker.requests == [] and journal.rows() == []


# ------------------------------------------------------------------ partial / unknown, never resent
@pytest.mark.parametrize("retcode", [None, Broker.TRADE_RETCODE_TIMEOUT, Broker.TRADE_RETCODE_CONNECTION])
def test_unknown_submission_stops_remaining_legs_and_never_resends(env, retcode):
    broker, journal, executor, gap = env
    broker.fail_at, broker.fail_code = 2, retcode
    result = submit(executor, gap)
    assert result["state"] == "needs_reconciliation"
    assert [x["state"] for x in result["legs"]] == ["pending", "unknown", "not_sent"]
    assert len(broker.requests) == 2
    assert submit(MT5FvgExecutor(lambda: broker, journal, executor.policy), gap) == result and len(broker.requests) == 2


def test_definite_partial_failure_is_reported_as_partial(env):
    broker, journal, executor, gap = env
    broker.fail_at, broker.fail_code = 2, 10016
    result = submit(executor, gap)
    assert result["state"] == "partial" and [x["state"] for x in result["legs"]] == ["pending", "rejected", "not_sent"]
    assert len(broker.requests) == 2


def test_crash_after_reservation_leaves_sending_state_and_no_resend(env):
    broker, journal, executor, gap = env

    def crash(request):
        broker.requests.append(request)
        raise SystemExit("process killed mid-send")
    broker.order_send = crash
    with pytest.raises(SystemExit):
        submit(executor, gap)
    row = journal.get("abc123")
    assert row["state"] == "submitting" and row["legs"][0]["state"] == "sending"
    broker2 = Broker()
    assert submit(MT5FvgExecutor(lambda: broker2, journal, executor.policy), gap)["state"] == "submitting"
    assert broker2.requests == []


# ------------------------------------------------------------------ reconciliation and ownership
def _order(ticket, n, state, symbol=META.name, magic=MAGIC, position_id=0):
    return NS(ticket=ticket, comment=leg_comment("abc123", n), symbol=symbol, magic=magic, state=state, position_id=position_id)


def test_reconciliation_finds_unknown_ticket_by_comment_without_sending(env):
    broker, journal, executor, gap = env
    broker.fail_at = 1
    assert submit(executor, gap)["legs"][0]["state"] == "unknown"
    broker.orders = (_order(700, 1, broker.ORDER_STATE_PLACED),)
    rec = executor.reconcile("abc123", T + timedelta(seconds=5))
    assert rec["legs"][0]["ticket"] == 700 and rec["legs"][0]["state"] == "pending" and len(broker.requests) == 1


def test_reconciliation_separates_open_positions_and_broker_closed_outcomes(env):
    broker, journal, executor, gap = env
    submit(executor, gap)
    broker.orders = (_order(103, 3, broker.ORDER_STATE_PLACED),)
    broker.history = (_order(101, 1, broker.ORDER_STATE_FILLED, position_id=501), _order(102, 2, broker.ORDER_STATE_FILLED, position_id=502))
    broker.positions = (NS(identifier=502, ticket=502, symbol=META.name, magic=MAGIC),)
    broker.deals = (NS(position_id=501, entry=broker.DEAL_ENTRY_OUT, reason=broker.DEAL_REASON_TP, price=110.1,
                       profit=6.5, commission=-0.1, swap=0.0, fee=0.0),)
    rec = executor.reconcile("abc123", T + timedelta(minutes=30))
    assert [l["state"] for l in rec["legs"]] == ["closed_tp", "filled_open", "pending"]
    assert rec["legs"][0]["broker_pnl"] == 6.4 and rec["legs"][0]["exit_price"] == 110.1
    broker.account.login = 88
    with pytest.raises(ValueError):
        executor.reconcile("abc123", T + timedelta(minutes=31))


def test_cancel_only_removes_this_baskets_own_pending_orders(env):
    broker, journal, executor, gap = env
    submit(executor, gap)
    foreign = NS(ticket=900, comment="manual", symbol=META.name, magic=0, state=broker.ORDER_STATE_PLACED)
    broker.orders = (_order(101, 1, broker.ORDER_STATE_PLACED), _order(102, 2, broker.ORDER_STATE_PLACED), foreign)
    maint = MT5FvgExecutor(lambda: broker, journal, ExecutionPolicy())  # cancel works while execution is OFF
    out = maint.cancel_remaining("abc123", "zone invalidated")
    assert sorted(broker.removed) == [101, 102] and 900 not in broker.removed
    assert [l["state"] for l in out["legs"]] == ["cancelled", "cancelled", "pending"]  # 103 no longer at broker: left


def test_pending_limits_use_return_filling_whatever_the_market_filling_flags(env):
    broker, journal, executor, gap = env
    broker.symbol.filling_mode = 1  # FOK-only market execution flags: irrelevant for pending orders
    submit(executor, gap)
    assert {r["type_filling"] for r in broker.requests} == {broker.ORDER_FILLING_RETURN}
    mt5 = pytest.importorskip("MetaTrader5")  # read-only import; never initialize
    assert mt5.ORDER_FILLING_RETURN == broker.ORDER_FILLING_RETURN == 2


def _deal(order, pos, entry, volume, reason=0, price=0.0, profit=0.0, commission=0.0):
    return NS(order=order, position_id=pos, entry=entry, volume=volume, reason=reason, price=price, profit=profit,
              commission=commission, swap=0.0, fee=0.0)


def test_partial_fill_reports_open_volume_and_resting_remainder_then_cancel_keeps_the_position(env):
    broker, journal, executor, gap = env
    submit(executor, gap)
    live1 = NS(**vars(_order(101, 1, broker.ORDER_STATE_PARTIAL)), volume_current=0.4)
    broker.orders = (live1, _order(102, 2, broker.ORDER_STATE_PLACED), _order(103, 3, broker.ORDER_STATE_PLACED))
    broker.positions = (NS(identifier=101, ticket=101, symbol=META.name, magic=MAGIC),)
    broker.deals = (_deal(101, 101, broker.DEAL_ENTRY_IN, 0.6, commission=-0.2),)
    rec = executor.reconcile("abc123", T + timedelta(minutes=5))
    leg = rec["legs"][0]
    assert leg["state"] == "partially_filled" and leg["filled_volume"] == 0.6 and leg["pending_volume"] == 0.4
    assert rec["state"] != "closed"
    out = MT5FvgExecutor(lambda: broker, journal, ExecutionPolicy()).cancel_remaining("abc123", "zone invalidated")
    assert 101 in broker.removed and out["legs"][0]["state"] == "filled_open" and out["legs"][0]["remainder"] == "cancelled"


def test_partial_fill_with_expired_remainder_stays_open_until_closed_and_pnl_counts_every_deal(env):
    broker, journal, executor, gap = env
    submit(executor, gap)
    broker.history = (_order(101, 1, broker.ORDER_STATE_EXPIRED),)  # partially filled, remainder expired
    broker.orders = (_order(102, 2, broker.ORDER_STATE_PLACED), _order(103, 3, broker.ORDER_STATE_PLACED))
    broker.positions = (NS(identifier=101, ticket=101, symbol=META.name, magic=MAGIC),)
    broker.deals = (_deal(101, 101, broker.DEAL_ENTRY_IN, 0.6, commission=-0.2),)
    leg = executor.reconcile("abc123", T + timedelta(minutes=5))["legs"][0]
    assert leg["state"] == "filled_open" and leg["remainder"] == "expired" and leg["filled_volume"] == 0.6
    broker.positions = ()
    broker.deals += (_deal(9001, 101, broker.DEAL_ENTRY_OUT, 0.3, broker.DEAL_REASON_TP, 110.0, 3.0, -0.1),
                     _deal(9002, 101, broker.DEAL_ENTRY_OUT, 0.3, broker.DEAL_REASON_TP, 110.1, 3.1, -0.1))
    leg = executor.reconcile("abc123", T + timedelta(minutes=50))["legs"][0]
    assert leg["state"] == "closed_tp" and leg["exit_price"] == 110.1
    assert leg["broker_pnl"] == round(3.0 + 3.1 - 0.2 - 0.1 - 0.1, 2)  # entry-side commission included
