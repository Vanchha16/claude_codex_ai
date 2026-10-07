"""Scanner + persistence: warm-up/live-start, restart deduplication, pause, delivery hand-off, no trading code."""
from datetime import timedelta
from pathlib import Path

import httpx

from app.config import DEMO_FIXTURE, Settings, StrategyConfig
from app.data.demo import DemoFeed
from app.delivery import Delivery, TelegramClient
from app.models import parse_iso
from app.scanner import Scanner
from app.store import SqliteStore

CFG = StrategyConfig()


def make(tmp_path, start_offset=None, telegram=False, calls=None):
    feed = DemoFeed(DEMO_FIXTURE)
    if start_offset is not None:
        feed._now = feed.start + start_offset
    store = SqliteStore(tmp_path / "demo.sqlite")
    settings = Settings(telegram_bot_token="1:x" if telegram else "", telegram_test_chat_id="-1" if telegram else "")
    calls = calls if calls is not None else []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(calls)}})
    delivery = Delivery(store, settings, client_factory=lambda t: TelegramClient(t, transport=httpx.MockTransport(handler)),
                        clock=feed.now)
    return Scanner(settings, CFG, feed, store, delivery), feed, store, delivery, calls


def run(scanner, feed, minutes, delivery=None):
    for _ in range(int(minutes * 60 / 5)):
        feed.advance(5)
        scanner.scan_once()
        if delivery:
            delivery.process_due()


def test_first_signal_live_and_delivered_once(tmp_path):
    sc, feed, store, delivery, calls = make(tmp_path, telegram=True)
    delivery.set_enabled(True)
    run(sc, feed, 60, delivery)
    sigs = store.list_signals()
    assert len(sigs) == 1 and sigs[0].direction == "BUY" and sigs[0].mode == "demo"
    assert sigs[0].entry == sigs[0].ask  # BUY at Ask from the fresh quote
    assert (sigs[0].quote_time - sigs[0].confirm_close).total_seconds() <= CFG.signal_max_age_seconds
    assert [r["status"] for r in store.outbox_rows()] == ["sent"] and len(calls) == 1
    run(sc, feed, 30, delivery)  # later scans must not resend
    assert len(calls) == 1


def test_startup_after_confirmation_sends_nothing_historical(tmp_path):
    # start 40 simulated minutes after the first BUY's B close: its confirmation (B close + 10 min) is history
    sc, feed, store, delivery, calls = make(tmp_path, start_offset=timedelta(minutes=70), telegram=True)
    delivery.set_enabled(True)
    run(sc, feed, 20, delivery)
    assert store.list_signals() == []
    reasons = {c.reason for c in store.list_candidates()}
    assert "confirmation_before_session_watermark" in reasons  # consumed by the session watermark (bug-fix task)
    assert calls == []


def test_restart_does_not_duplicate(tmp_path):
    sc, feed, store, delivery, _ = make(tmp_path)
    run(sc, feed, 60)
    before_sigs = [s.id for s in store.list_signals()]
    before_cands = [c.key for c in store.list_candidates(1000)]
    t = feed.now()
    store.close()
    # "restart": new process objects on the same database, clock continues
    sc2, feed2, store2, _, _ = make(tmp_path)
    feed2._now = t
    run(sc2, feed2, 30)
    assert [s.id for s in store2.list_signals()] == before_sigs
    keys = [c.key for c in store2.list_candidates(1000)]
    assert len(keys) == len(set(keys)) and set(before_cands) <= set(keys)


def test_pause_stops_new_alerts_but_tracks_outcomes(tmp_path):
    sc, feed, store, delivery, _ = make(tmp_path)
    run(sc, feed, 45)  # first BUY confirmed (active)
    (sig,) = store.list_signals()
    sc.pause()
    run(sc, feed, 8 * 60)  # covers the SELL scenario
    sigs = store.list_signals()
    assert len(sigs) == 1 and sigs[0].outcome_status == "tp"  # outcome tracker still ran
    sc.resume()
    assert parse_iso(store.get_meta("live_start")) == feed.now()


def test_overlapping_signals_prevented(tmp_path):
    from app.engine import Engine
    from app.models import M5
    from app.scenarios import buy_setup
    from app.store import MemoryStore
    from tests.helpers import META, T0, drive
    store = MemoryStore()
    drive(buy_setup(T0, include_run=False), store=store)
    assert len(store.signals) == 1  # active (no run to TP)
    # a second, later identical setup while the first is still active is rejected
    later = buy_setup(T0 + timedelta(hours=5), include_run=False)
    drive(later, store=store)
    assert len(store.signals) == 1
    assert any(c.reason == "overlapping_active_signal" for c in store.candidates.values())


def test_broker_requests_exist_only_in_the_opt_in_fvg_executor():
    """Scoped guarantee (replaces the old blanket check): CRT, FastSweep, the feed and every other module stay
    read-only; only app/fvg_execution.py may build broker requests, and its default policy is disabled."""
    root = Path(__file__).resolve().parent.parent / "app"
    banned = ("order_send", "order_check", "positions_close", "TRADE_ACTION")
    allowed = root / "fvg_execution.py"
    for path in root.rglob("*.py"):
        if path == allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if path.name == "mt5.py":
            text = text.split('"""', 2)[2]  # the module docstring names what it never calls
        for word in banned:
            assert word not in text, f"{word} found in {path}"
    assert "order_send" in allowed.read_text(encoding="utf-8")
    from app.fvg_execution import ExecutionPolicy
    assert ExecutionPolicy().enabled is False and ExecutionPolicy().risk_usd is None


def test_read_only_strategies_never_import_the_executor():
    root = Path(__file__).resolve().parent.parent / "app"
    import re
    imports = re.compile(r"^\s*(from\s+\S*fvg_execution\s+import|import\s+\S*fvg_execution)", re.M)
    for name in ("engine.py", "strategy.py", "fastsweep.py", "fastsweep_live.py", "fastsweep_replay.py", "replay.py",
                 "data/mt5.py", "data/demo.py", "fvg.py", "fvg_replay.py", "fvg_orders.py", "delivery.py"):
        path = root / name
        if path.exists():
            assert not imports.search(path.read_text(encoding="utf-8")), name
