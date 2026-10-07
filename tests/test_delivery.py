import json
from datetime import datetime, timedelta

import httpx
import pytest

from app.config import Settings
from app.delivery import Delivery, TelegramClient, format_signal
from app.engine import Signal
from app.models import UTC
from app.store import SqliteStore

TOKEN = "123456:SECRET-TOKEN-abc"
NOW = datetime(2030, 1, 7, 6, 10, 1, tzinfo=UTC)


def make_signal(valid_s=120, sid="DEMO-SIG-1"):
    return Signal(id=sid, candidate_key="k|" + sid, symbol="XAUUSDm", mode="mt5", direction="BUY", entry=2405.6,
                  sl=2398.98, tp=2420.0, reward_risk=2.175, spread=0.2, bid=2405.4, ask=2405.6, quote_time=NOW,
                  confirm_close=NOW - timedelta(seconds=1), created_at=NOW, valid_until=NOW + timedelta(seconds=valid_s),
                  config_version="CRT-SMC-v1@abcd1234", explanation="test explanation", meta={"symbol": {"digits": 2}})


class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t


def setup(tmp_path, handler, configured=True):
    store = SqliteStore(tmp_path / "t.sqlite")
    settings = Settings(telegram_bot_token=TOKEN if configured else "", telegram_test_chat_id="-100123" if configured else "")
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)
    clock = Clock()
    d = Delivery(store, settings, client_factory=lambda tok: TelegramClient(tok, transport=httpx.MockTransport(wrapped)), clock=clock)
    return store, d, calls, clock


def ok(request):
    return httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})


def test_message_is_exactly_entry_tp_sl_rr():
    assert format_signal(make_signal()) == "📍 Entry: 2405.60\n🎯 TP: 2420.00\n🛑 SL: 2398.98\n⚖️ RR: 2.17"


def test_message_uses_symbol_digits():
    sig = make_signal()
    sig.meta = {"symbol": {"digits": 3}}
    sig.entry, sig.tp, sig.sl, sig.reward_risk = 4141.208, 4120.5, 4151.2, 2.0
    assert format_signal(sig) == "📍 Entry: 4141.208\n🎯 TP: 4120.500\n🛑 SL: 4151.200\n⚖️ RR: 2.00"


def test_success_records_message_id(tmp_path):
    store, d, calls, _ = setup(tmp_path, ok)
    d.set_enabled(True)
    assert d.on_signal(make_signal())
    assert d.process_due() == 1
    row = store.outbox_rows()[0]
    assert row["status"] == "sent" and row["telegram_message_id"] == 77 and len(calls) == 1
    payload = json.loads(calls[0].content)
    assert payload["text"] == "📍 Entry: 2405.60\n🎯 TP: 2420.00\n🛑 SL: 2398.98\n⚖️ RR: 2.17" == row["text"]
    assert payload["chat_id"] == "-100123" and "parse_mode" not in payload  # plain UTF-8 text


def test_disabled_and_unconfigured_send_nothing(tmp_path):
    store, d, calls, _ = setup(tmp_path, ok, configured=False)
    assert not d.on_signal(make_signal())
    with pytest.raises(ValueError):
        d.set_enabled(True)
    store2, d2, calls2, _ = setup(tmp_path / "b", ok)
    assert not d2.on_signal(make_signal())  # configured but not enabled
    d2.process_due()
    assert calls == [] and calls2 == []


def test_429_retry_after_then_success(tmp_path):
    responses = [httpx.Response(429, json={"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 3}}), None]

    def handler(request):
        r = responses.pop(0)
        return r or ok(request)
    store, d, calls, clock = setup(tmp_path, handler)
    d.set_enabled(True)
    d.on_signal(make_signal())
    d.process_due()
    row = store.outbox_rows()[0]
    assert row["status"] == "pending" and row["attempts"] == 1
    d.process_due()  # not due yet
    assert len(calls) == 1
    clock.t = NOW + timedelta(seconds=4)
    d.process_due()
    assert store.outbox_rows()[0]["status"] == "sent" and len(calls) == 2


def test_definite_error_fails_without_retry(tmp_path):
    store, d, calls, clock = setup(tmp_path, lambda r: httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"}))
    d.set_enabled(True)
    d.on_signal(make_signal())
    d.process_due()
    clock.t = NOW + timedelta(seconds=30)
    d.process_due()
    row = store.outbox_rows()[0]
    assert row["status"] == "failed" and "chat not found" in row["last_error"] and len(calls) == 1


def test_timeout_is_unknown_and_never_resent(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)
    store, d, calls, clock = setup(tmp_path, handler)
    d.set_enabled(True)
    d.on_signal(make_signal())
    d.process_due()
    clock.t = NOW + timedelta(seconds=10)
    d.process_due()
    assert store.outbox_rows()[0]["status"] == "unknown" and len(calls) == 1


def test_connect_error_retries_while_timely_then_expires(tmp_path):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)
    store, d, calls, clock = setup(tmp_path, handler)
    d.set_enabled(True)
    d.on_signal(make_signal(valid_s=5))
    d.process_due()
    assert store.outbox_rows()[0]["status"] == "pending"
    clock.t = NOW + timedelta(seconds=10)  # past validity
    d.process_due()
    assert store.outbox_rows()[0]["status"] == "expired" and len(calls) == 1


def test_expired_signal_is_not_sent(tmp_path):
    store, d, calls, clock = setup(tmp_path, ok)
    d.set_enabled(True)
    d.on_signal(make_signal(valid_s=1))
    clock.t = NOW + timedelta(seconds=30)
    d.process_due()
    assert store.outbox_rows()[0]["status"] == "expired" and calls == []


def test_token_is_redacted_from_errors(tmp_path):
    def handler(request):
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)
    store, d, calls, _ = setup(tmp_path, handler)
    d.set_enabled(True)
    d.on_signal(make_signal())
    d.process_due()
    stored = repr(store.outbox_rows()) + repr(store.list_events())
    assert TOKEN not in stored
    r = TelegramClient(TOKEN, transport=httpx.MockTransport(lambda req: httpx.Response(401, json={"description": f"bad {TOKEN}"}))).send("1", "x")
    assert TOKEN not in (r.error or "") and "<redacted-token>" in r.error


def test_crash_mid_send_becomes_unknown(tmp_path):
    store = SqliteStore(tmp_path / "c.sqlite")
    store.enqueue("SIG-X", "signal", "text", NOW + timedelta(minutes=5), NOW)
    oid = store.outbox_rows()[0]["id"]
    store.update_outbox(oid, status="sending")
    Delivery(store, Settings(telegram_bot_token=TOKEN, telegram_test_chat_id="1"))
    assert store.outbox_rows()[0]["status"] == "unknown"


def test_test_message_only_on_explicit_request(tmp_path):
    store, d, calls, _ = setup(tmp_path, ok)
    d.process_due()
    assert calls == []
    d.queue_test_message()
    d.process_due()
    assert len(calls) == 1 and "TEST MESSAGE" in calls[0].content.decode()
