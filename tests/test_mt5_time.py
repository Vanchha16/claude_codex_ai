"""One UTC contract for MT5 timestamps (app/mt5_time.py): feed, chart, ranges, FVG execution. Fake modules only."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from app.config import Settings, StrategyConfig
from app.data.mt5 import MT5Feed
from app.delivery import Delivery
from app.fvg_execution import ExecutionJournal, MT5FvgExecutor
from app.models import UTC
from app.mt5_time import UTC_BASE, TimeBase, TimeConfigError, load_server_offsets, resolve_time_base
from app.scanner import Scanner
from app.store import SqliteStore

from .fake_mt5 import FakeMT5
from app.fastsweep import BUY
from app.fvg import Gap

from .test_fvg import META, T, candles
from .test_fvg_execution import Broker, policy

SERVER = "MetaQuotes-Demo"


class ServerMT5(FakeMT5):
    """A terminal whose epochs are the trade server's own time: fake 'now' = true UTC + offset."""

    def __init__(self, *, utc_now, server_offset_h, server=SERVER, **kw):
        super().__init__(now=utc_now + timedelta(hours=server_offset_h), **kw)
        self.server = server
        self.range_args = []

    login = 1

    def account_info(self):
        return NS(login=self.login, balance=0.0, server=self.server, company="MetaQuotes Ltd.", trade_mode=0)

    def copy_rates_range(self, symbol, tf, date_from, date_to):
        self.range_args.append((date_from, date_to))
        return super().copy_rates_range(symbol, tf, date_from, date_to)


def cfg(tmp_path, servers):
    p = tmp_path / "mt5_time.json"
    p.write_text(json.dumps({"servers": {k: {"utc_offset_hours": v} for k, v in servers.items()}}), encoding="utf-8")
    return p


NOW = datetime.now(UTC).replace(microsecond=0)


# ------------------------------------------------------------------ contract
def test_time_base_round_trip_and_resolution(tmp_path):
    tb = TimeBase(3, SERVER, "x")
    t = datetime(2026, 10, 7, 7, 40, tzinfo=timezone.utc)
    assert tb.to_utc(tb.to_broker(t).timestamp()) == t and tb.to_broker(t) - t == timedelta(hours=3)
    with pytest.raises(ValueError):
        tb.to_broker(datetime(2026, 10, 7))  # naive datetimes are refused
    path = cfg(tmp_path, {SERVER: 3})
    assert resolve_time_base(SERVER, 0, path).offset_hours == 3
    assert resolve_time_base("Exness-MT5Real20", 0, path).offset_hours == 0  # never applied to other servers
    assert resolve_time_base("Other", 2, path).source.startswith("GOLD_MT5_SERVER_UTC_OFFSET_HOURS")
    assert resolve_time_base(None, 0, tmp_path / "missing.json") == TimeBase(0.0, None, resolve_time_base(None, 0, tmp_path / "missing.json").source)


@pytest.mark.parametrize("bad", [{"servers": {SERVER: {"utc_offset_hours": "3"}}}, {"servers": {SERVER: {"utc_offset_hours": 2.1}}},
                                 {"servers": {SERVER: {"utc_offset_hours": 15}}}, {"servers": []}, {"nope": 1}])
def test_invalid_time_config_fails_closed(tmp_path, bad):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(TimeConfigError):
        load_server_offsets(p)
    feed = MT5Feed("XAUUSD", module=ServerMT5(utc_now=NOW, server_offset_h=3), time_config_path=p)
    st = feed.connect()
    assert not st.ok and "time configuration invalid" in st.message


def test_project_config_holds_the_verified_metaquotes_demo_entry():
    assert load_server_offsets()[SERVER] == 3


# ------------------------------------------------------------------ feed
@pytest.mark.parametrize("offset", [3, 2])
def test_verified_server_offset_normalises_quotes_bars_and_ranges_exactly_once(tmp_path, offset):
    fake = ServerMT5(utc_now=NOW, server_offset_h=offset)
    feed = MT5Feed("XAUUSD", module=fake, time_config_path=cfg(tmp_path, {SERVER: offset}))
    st = feed.connect()
    assert st.ok and st.details["time_base"] == {"server": SERVER, "utc_offset_hours": offset,
                                                 "source": "t.json (verified for this server)".replace("t.json", "mt5_time.json")}
    assert feed.quote().time == NOW  # fresh, not +offset in the future
    bars = feed.closed_bars("M5", 3)
    last_open = datetime.fromtimestamp((int(NOW.timestamp()) // 300) * 300 - 300, tz=timezone.utc)
    assert bars[-1].open_time == last_open and bars[-1].close_time <= NOW  # newest CLOSED bar = current UTC, forming excluded
    closed, forming = feed.chart_bars("M5", 5)
    assert forming is not None and forming.time == int(last_open.timestamp()) + 300
    start, end = NOW - timedelta(hours=1), NOW
    feed.bars_range("M5", start, end)
    assert fake.range_args[-1] == (start + timedelta(hours=offset), end + timedelta(hours=offset))  # out: +offset once


def test_unverified_server_keeps_documented_utc_so_a_plus3_server_fails_closed(tmp_path):
    fake = ServerMT5(utc_now=NOW, server_offset_h=3, server="Some-Other-Server")
    feed = MT5Feed("XAUUSD", module=fake, time_config_path=cfg(tmp_path, {SERVER: 3}))
    assert feed.connect().ok and feed.timebase.offset_hours == 0
    assert (feed.quote().time - NOW) == timedelta(hours=3)  # looks future -> the scanner's guard rejects it


def test_standard_utc_server_is_unchanged(tmp_path):
    fake = ServerMT5(utc_now=NOW, server_offset_h=0, server="Exness-MT5Real20")
    feed = MT5Feed("XAUUSD", module=fake, time_config_path=cfg(tmp_path, {SERVER: 3}))
    feed.connect()
    assert feed.quote().time == NOW and feed.timebase.offset_hours == 0


def test_server_change_is_a_disconnect_and_reconnect_uses_the_new_servers_base(tmp_path):
    fake = ServerMT5(utc_now=NOW, server_offset_h=3)
    feed = MT5Feed("XAUUSD", module=fake, time_config_path=cfg(tmp_path, {SERVER: 3}))
    assert feed.connect().ok and feed.status().ok
    fake.server = "Exness-MT5Real20"
    st = feed.status()
    assert not st.ok and st.state == "disconnected" and "trade server changed" in st.message
    assert feed.connect().ok and feed.timebase == TimeBase(0.0, "Exness-MT5Real20", feed.timebase.source)


# ------------------------------------------------------------------ scanner: wrong/changed offsets fail closed
def run_scan(tmp_path, actual, configured):
    fake = ServerMT5(utc_now=datetime.now(UTC), server_offset_h=actual)
    feed = MT5Feed("XAUUSD", module=fake, time_config_path=cfg(tmp_path, {SERVER: configured}))
    store = SqliteStore(tmp_path / f"s{actual}{configured}.sqlite")
    settings = Settings(data_mode="mt5", symbol="XAUUSD")
    sc = Scanner(settings, StrategyConfig(), feed, store, Delivery(store, settings, source="test"))
    sc.scan_once()
    return sc


def test_correct_offset_gives_fresh_quotes_and_opens_a_session(tmp_path):
    sc = run_scan(tmp_path, 3, 3)
    assert sc.state["quote"]["fresh"] is True and sc.session_watermark is not None


@pytest.mark.parametrize("actual,configured,word", [(2, 3, "behind"), (3, 2, "ahead"), (3, 0, "ahead")])
def test_wrong_or_changed_offset_is_never_actionable(tmp_path, actual, configured, word):
    sc = run_scan(tmp_path, actual, configured)  # e.g. after DST the server moves to +2 while +3 is configured
    q = sc.state["quote"]
    assert q["fresh"] is False and sc.session_watermark is None
    assert f"~1 h {word}" in q["note"] or f"~3 h {word}" in q["note"]


# ------------------------------------------------------------------ FVG executor uses the feed's base
def server_broker(offset):
    b = Broker()
    t = b.ticks[0]
    b.ticks = [NS(bid=t.bid, ask=t.ask, time=t.time + offset * 3600, time_msc=t.time_msc + offset * 3600_000)]
    b.account.server = SERVER
    b.history_args = []
    orig = b.history_orders_get

    def history_orders_get(*args):
        b.history_args.append(args)
        return orig(*args)
    b.history_orders_get = history_orders_get
    return b


def make_exec(tmp_path, broker, tb):
    journal = ExecutionJournal(tmp_path / "j.sqlite")
    return MT5FvgExecutor(lambda: broker, journal, policy(account_server=SERVER), timebase_fn=lambda: tb), journal


def test_codex_reproduction_feed_offset_now_reaches_the_executor(tmp_path):
    broker = server_broker(3)
    ex, _ = make_exec(tmp_path, broker, TimeBase(3, SERVER, "test"))
    a, _, c = candles()
    out = ex.submit("abc123", Gap(BUY, 100, 110, a, c), META, T, T + timedelta(hours=2))
    assert out["state"] == "submitted" and len(broker.requests) == 3
    exp = {r["expiration"] for r in broker.requests}
    assert exp == {int((T + timedelta(hours=5)).timestamp())}  # 2 h lifetime, expressed in the broker's +3 base
    assert out["time_base"]["utc_offset_hours"] == 3
    ex.reconcile("abc123", T + timedelta(minutes=10))
    start, end = broker.history_args[-1]
    assert start <= T + timedelta(hours=3) - timedelta(minutes=1) and end >= T + timedelta(hours=3, minutes=10)


@pytest.mark.parametrize("tb,why", [(UTC_BASE, "stale MT5 quote"), (TimeBase(2, SERVER, "t"), "stale MT5 quote"),
                                    (TimeBase(3, "Other-Server", "t"), "trade server differs")])
def test_executor_rejects_unverified_or_mismatched_time_bases(tmp_path, tb, why):
    broker = server_broker(3)
    ex, journal = make_exec(tmp_path, broker, tb)
    with pytest.raises(ValueError, match=why):
        ex._context(META.name, T)
    assert broker.requests == []


def test_executor_still_rejects_a_genuinely_stale_tick_under_the_right_base(tmp_path):
    broker = server_broker(3)
    ex, _ = make_exec(tmp_path, broker, TimeBase(3, SERVER, "t"))
    with pytest.raises(ValueError, match="stale"):
        ex._context(META.name, T + timedelta(minutes=5))  # the same tick 5 minutes later is stale, never "corrected"


def test_same_server_account_change_is_a_disconnect_and_opens_a_new_session(tmp_path):
    fake = ServerMT5(utc_now=datetime.now(UTC), server_offset_h=3)
    feed = MT5Feed("XAUUSD", module=fake, time_config_path=cfg(tmp_path, {SERVER: 3}))
    store = SqliteStore(tmp_path / "acct.sqlite")
    settings = Settings(data_mode="mt5", symbol="XAUUSD")
    sc = Scanner(settings, StrategyConfig(), feed, store, Delivery(store, settings, source="test"))
    sc.scan_once()
    first = sc.session_watermark
    assert first is not None
    fake.login = 2  # another account on the SAME server
    st = feed.status()
    assert not st.ok and "account changed on the same server" in st.message and "2" not in st.message.split("server")[-1]
    fake.now += timedelta(seconds=2)
    fake.last_tick = None
    sc.scan_once()  # reconnects in the same scan, but must open a NEW watermark
    assert feed.status().ok and sc.session_watermark is not None and sc.session_watermark > first
