"""Regressions for bug 1: a fresh session eligibility watermark on startup, restart and recovery.

A confirmation is actionable only if its M5 bar closed strictly AFTER the current session watermark;
an old persisted watermark never authorises confirmations missed while the app was down or the feed unhealthy.
"""
from datetime import datetime, timedelta

import httpx
import pytest

from app.config import DEMO_FIXTURE, Settings, StrategyConfig
from app.data.base import FeedStatus
from app.data.demo import DemoFeed
from app.delivery import Delivery, TelegramClient
from app.models import UTC, Quote
from app.scanner import Scanner
from app.store import SqliteStore

from .test_scanner import make, run

CFG = StrategyConfig()
FIRST_CONFIRM = datetime(2030, 1, 7, 6, 10, tzinfo=UTC)  # first fictional BUY's confirmation bar closes here
FIRST_A_OPEN = datetime(2030, 1, 7, 4, 0, tzinfo=UTC)
SYMBOL = "DEMO-XAUUSD"


def first_candidate(store):
    return next(c for c in store.list_candidates(1000) if c.a_open == FIRST_A_OPEN)


def test_startup_five_seconds_after_confirmation_is_not_actionable(tmp_path):
    sc, feed, store, delivery, calls = make(tmp_path, telegram=True)
    feed._now = FIRST_CONFIRM  # run() advances 5 s before the first scan -> first scan at confirm + 5 s
    delivery.set_enabled(True)
    run(sc, feed, 10, delivery)
    assert store.list_signals() == [] and store.active_signals(SYMBOL) == []
    assert store.outbox_rows() == [] and calls == []
    c = first_candidate(store)
    assert c.status == "rejected" and c.reason == "confirmation_before_session_watermark"


def test_restart_across_confirmation_with_persisted_history_is_not_actionable(tmp_path):
    sc, feed, store, delivery, calls = make(tmp_path, telegram=True)
    delivery.set_enabled(True)
    run(sc, feed, 39.5, delivery)  # 05:30 -> 06:09:30: candidate pending, history persisted
    assert feed.now() < FIRST_CONFIRM and first_candidate(store).status == "pending"
    store.close()
    sc2, feed2, store2, delivery2, calls2 = make(tmp_path, telegram=True)
    feed2._now = FIRST_CONFIRM  # process restarts; first scan 5 s after the confirmation close
    delivery2.set_enabled(True)
    run(sc2, feed2, 10, delivery2)
    assert store2.list_signals() == [] and store2.outbox_rows() == [] and calls == calls2 == []
    assert first_candidate(store2).reason == "confirmation_before_session_watermark"


class FlakyFeed(DemoFeed):
    """Demo feed that is disconnected, or serves a stale quote, inside [down_from, down_to)."""

    def __init__(self, path, down_from, down_to, kind):
        super().__init__(path)
        self.down_from, self.down_to, self.kind = down_from, down_to, kind

    def _down(self):
        return self.down_from <= self.now() < self.down_to

    def status(self):
        if self.kind == "disconnect" and self._down():
            return FeedStatus(False, "disconnected", "simulated disconnect")
        return super().status()

    def quote(self):
        q = super().quote()
        if self.kind == "stale" and self._down() and q is not None:
            return Quote(self.down_from - timedelta(seconds=60), q.bid, q.ask)
        return q


@pytest.mark.parametrize("kind", ["disconnect", "stale"])
def test_recovery_within_30_seconds_does_not_release_missed_confirmation(tmp_path, kind):
    feed = FlakyFeed(DEMO_FIXTURE, FIRST_CONFIRM - timedelta(seconds=30), FIRST_CONFIRM + timedelta(seconds=5), kind)
    store = SqliteStore(tmp_path / "demo.sqlite")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    settings = Settings(telegram_bot_token="1:x", telegram_test_chat_id="-1")
    delivery = Delivery(store, settings, clock=feed.now,
                        client_factory=lambda t: TelegramClient(t, transport=httpx.MockTransport(handler)))
    delivery.set_enabled(True)
    sc = Scanner(settings, CFG, feed, store, delivery)
    run(sc, feed, 45, delivery)  # 05:30 -> 06:15 with an outage 06:09:30-06:10:05
    assert store.list_signals() == [] and store.outbox_rows() == [] and calls == []
    assert first_candidate(store).reason == "confirmation_before_session_watermark"


def test_confirmation_after_watermark_still_creates_one_signal_and_one_alert(tmp_path):
    sc, feed, store, delivery, calls = make(tmp_path, telegram=True)
    feed._now = FIRST_CONFIRM - timedelta(minutes=2)  # session starts before the confirmation closes
    delivery.set_enabled(True)
    run(sc, feed, 10, delivery)
    (sig,) = store.list_signals()
    assert sig.confirm_close == FIRST_CONFIRM and len(calls) == 1
    run(sc, feed, 10, delivery)  # repeat scans: no duplicate
    assert len(store.list_signals()) == 1 and len(calls) == 1


def test_restart_keeps_tracking_existing_active_signal(tmp_path):
    sc, feed, store, delivery, _ = make(tmp_path)
    run(sc, feed, 41)  # signal confirmed at 06:10 and still active
    (sig,) = store.list_signals()
    assert sig.outcome_status == "active"
    t = feed.now()
    store.close()
    sc2, feed2, store2, _, _ = make(tmp_path)
    feed2._now = t
    run(sc2, feed2, 45)
    (after,) = store2.list_signals()
    assert after.id == sig.id and after.outcome_status == "tp"
    keys = [c.key for c in store2.list_candidates(1000)]
    assert len(keys) == len(set(keys))
