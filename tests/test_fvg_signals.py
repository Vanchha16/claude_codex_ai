"""Separate M5 / M15 signals (task 20261008-161842): one standalone Telegram message per basket, per-engine API lists.
Fake delivery client and test-only feeds only: nothing is sent and no real terminal is touched."""
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.active_strategy import parse_active_strategy
from app.config import Settings
from app.delivery import Delivery, TelegramClient, format_fvg_basket
from app.fvg_dual import DUAL_PROFILE
from app.models import iso
from app.store import SqliteStore
from app.web import create_app
from tests.conftest import fixture_factory
from tests.test_fvg_dual import Env, m15_then_m5_gap

D = DUAL_PROFILE


def basket(engine, bid, direction, placed, base, legs_state=None, version=None):
    sl = round(base - 0.02, 2) if direction == "BUY" else round(base + 1.22, 2)
    legs = [{"n": n + 1, "pct": p, "entry": round(base + 1.2 - 1.2 * p / 100, 2) if direction == "BUY" else round(base + 1.2 * p / 100, 2),
             "tp": round(base + 5 + n, 2) if direction == "BUY" else round(base - 5 - n, 2), "sl": sl, "rr": 2.0}
            for n, p in enumerate((1, 50, 80))]
    b = {"id": bid, "plan_id": bid.split("-", 1)[1], "setup_key": f"S|{placed.isoformat()}|{version or D.engine_version(engine or 'M15')}",
         "symbol": "XAUUSD", "version": version or (D.engine_version(engine) if engine else "FVG-Trend-M15-M5-v1-RR2@8a49bace"),
         "direction": direction, "bottom": base, "top": base + 1.2, "sl": sl, "placed_at": iso(placed),
         "pending_expires": iso(placed + timedelta(hours=2)), "accepted": True, "status": "alert_only", "legs": legs,
         "meta": {"digits": 2, "tick_size": 0.01}, "account_id": None,
         "execution": {"state": "not_submitted", "reason": "automatic execution OFF"} if legs_state is None else
         {"state": "submitted", "account_currency": "USD", "legs": [{"state": s, "volume": 0.02, "planned_loss": 3.3} for s in legs_state]}}
    if engine:
        b["engine"] = engine
    return b


def delivery(tmp_path, calls):
    store = SqliteStore(tmp_path / "d.sqlite")
    settings = Settings(telegram_bot_token="1:x", telegram_test_chat_id="-1")

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(calls)}})
    d = Delivery(store, settings, client_factory=lambda t: TelegramClient(t, transport=httpx.MockTransport(handler)),
                 source="test")
    d.enabled = True  # fake client only: no network, no real chat
    return d, store


def test_simultaneous_m15_and_m5_baskets_give_two_standalone_messages_and_no_duplicates(tmp_path):
    from datetime import datetime, timezone
    t = datetime(2026, 10, 8, 9, 15, tzinfo=timezone.utc)
    d, store = delivery(tmp_path, [])
    m15 = basket("M15", "FVG15-aaa", "BUY", t, 4100.0)
    m5 = basket("M5", "FVG5-bbb", "SELL", t, 4120.0)  # same close, opposite side: both independent
    assert d.on_fvg_basket(m15) and d.on_fvg_basket(m5)
    assert not d.on_fvg_basket(m15) and not d.on_fvg_basket(m5)  # duplicate processing: unique per basket id
    rows = {r["signal_id"]: r for r in store.outbox_rows()}
    assert set(rows) == {"FVG15-aaa", "FVG5-bbb"} and all(r["kind"] == "fvg_basket" for r in rows.values())
    t15, t5 = rows["FVG15-aaa"]["text"], rows["FVG5-bbb"]["text"]
    assert t15.splitlines()[0] == "M15 FVG · XAUUSD · BUY · 3 planned limit entries"
    assert t5.splitlines()[0] == "M5 FVG · XAUUSD · SELL · 3 planned limit entries"
    for own, other, text in ((m15, m5, t15), (m5, m15, t5)):
        assert text.count("📍 Entry:") == 3
        assert all(f"{l['entry']:.2f}" in text for l in own["legs"])
        assert not any(f"{l['entry']:.2f}" in text for l in other["legs"])  # never the other basket's levels
        assert "pending limits" not in text and "accepted" not in text  # planned, not broker-confirmed


def test_live_engines_queue_exactly_one_message_per_engine_basket(tmp_path):
    calls = []
    d, store = delivery(tmp_path / "d", calls)
    (tmp_path / "d").mkdir(exist_ok=True)
    env = Env(tmp_path)
    env.eng.alert_fn = d.on_fvg_basket
    bars, _, _ = m15_then_m5_gap()
    env.run(bars, delay=1)
    env.run(bars, delay=1, start=len(bars) - 3)  # repeated polls of the same closes
    rows = store.outbox_rows()
    assert sorted(r["text"].splitlines()[0].split(" ·")[0] for r in rows) == ["M15 FVG", "M5 FVG"]
    assert len(rows) == 2 and len({r["signal_id"] for r in rows}) == 2
    d.process_due()
    assert len(calls) == 2  # two separate sends through the fake client, never one combined message


def test_api_partitions_by_stored_engine_before_the_limit_and_shows_each_baskets_own_message(tmp_path):
    from datetime import datetime, timezone
    app = create_app(Settings(port=8000), feed_factory=fixture_factory, state_dir=tmp_path, extra_hosts=("testserver",),
                     local_settings_path=tmp_path / "local_settings.json",
                     active_strategy_loader=lambda: parse_active_strategy({"strategy": "fvg", "profile": "dual"}))
    with TestClient(app) as c:
        ws = app.state.ws
        ws.scanner.stop()
        t = datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc)
        ws.fvg_store.add_basket(basket("M15", "FVG15-old", "BUY", t, 4100.0, ["pending", "rejected", "not_sent"]))
        for k in range(5):  # newer M5 history dominates
            ws.fvg_store.add_basket(basket("M5", f"FVG5-n{k}", "SELL", t + timedelta(minutes=10 * (k + 1)), 4120.0 + k))
        ws.fvg_store.add_basket(basket(None, "FVG-legacy1", "BUY", t + timedelta(hours=2), 4090.0))
        ws.fvg_store.add_basket(basket("M5", "FVG5-fake", "BUY", t + timedelta(hours=3), 4000.0, version="FVG-Immediate-M15-v2-RR2@x"))
        ws.store.enqueue("FVG5-n4", "fvg_basket", "QUEUED TEXT OF FVG5-n4", t + timedelta(hours=9), t)
        before = (len(ws.fvg_store.baskets(limit=500)), len(ws.store.outbox_rows()))
        g = lambda q: c.get(f"/api/fvg?{q}").json()["baskets"]
        assert [b["id"] for b in g("engine=M15&limit=1")] == ["FVG15-old"]  # not starved by newer M5 baskets
        assert [b["id"] for b in g("engine=M5&limit=2")] == ["FVG5-n4", "FVG5-n3"]
        assert {b["id"] for b in g("engine=legacy")} == {"FVG-legacy1", "FVG5-fake"}  # mismatched provenance is never M5
        n4 = g("engine=M5&limit=1")[0]
        assert n4["message"] == {"source": "queued", "text": "QUEUED TEXT OF FVG5-n4"} and n4["delivery"]["status"] == "pending"
        n3 = g("engine=M5&limit=2")[1]
        assert n3["message"]["source"] == "preview" and n3["delivery"] is None
        assert n3["message"]["text"] == format_fvg_basket(n3) and "FVG5-n4" not in n3["message"]["text"]
        assert c.get("/api/fvg?engine=H1").status_code == 400
        assert len(c.get("/api/fvg").json()["baskets"]) == 8  # unfiltered contract unchanged
        assert (len(ws.fvg_store.baskets(limit=500)), len(ws.store.outbox_rows())) == before  # GETs never mutate
