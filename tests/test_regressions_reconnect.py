"""Regression for the same-scan reconnect gap found in Codex review of 20261002-132805-gold-three-bug-fixes.

An MT5-mode feed reports `disconnected`, and `connect()` restores it immediately within the same scan. The
recovered scan must still open a NEW session watermark, so a confirmation that closed while disconnected is not
actionable. Mock-only: the demo feed impersonates MT5 mode; no MetaTrader 5 API or Telegram network is used.
"""
from datetime import datetime, timedelta

from app.data.base import FeedStatus
from app.models import UTC

from .test_scanner import make, run

FIRST_CONFIRM = datetime(2030, 1, 7, 6, 10, tzinfo=UTC)
FIRST_A_OPEN = datetime(2030, 1, 7, 4, 0, tzinfo=UTC)


def disconnect_once_then_reconnect(feed):
    """Status says disconnected once; connect() recovers immediately (same scan)."""
    healthy_status = feed.status
    state = {"down": True, "connects": 0}
    feed.mode = "mt5"

    def status():
        if state["down"]:
            return FeedStatus(False, "disconnected", "mock: terminal disconnected")
        return healthy_status()

    def connect():
        state["connects"] += 1
        state["down"] = False
        return healthy_status()
    feed.status, feed.connect = status, connect
    return state


def first_candidate(store):
    return next(c for c in store.list_candidates(1000) if c.a_open == FIRST_A_OPEN)


def test_same_scan_reconnect_opens_new_watermark_and_blocks_missed_confirmation(tmp_path):
    sc, feed, store, delivery, calls = make(tmp_path, telegram=True)
    delivery.set_enabled(True)
    run(sc, feed, 39.5, delivery)  # 05:30 -> 06:09:30; old watermark 05:30:05; candidate pending
    old_watermark = sc.session_watermark
    assert first_candidate(store).status == "pending"
    feed._now = FIRST_CONFIRM + timedelta(seconds=5)  # 06:10:05, five seconds after the confirmation close
    state = disconnect_once_then_reconnect(feed)
    sc.scan_once()
    delivery.process_due()
    assert state["connects"] == 1
    assert sc.session_watermark == FIRST_CONFIRM + timedelta(seconds=5) != old_watermark  # watermark reset
    assert store.list_signals() == [] and store.active_signals("DEMO-XAUUSD") == []
    assert store.outbox_rows() == [] and calls == []
    assert first_candidate(store).reason == "confirmation_before_session_watermark"


def test_genuinely_new_confirmation_after_reconnect_is_eligible(tmp_path):
    sc, feed, store, delivery, calls = make(tmp_path, telegram=True)
    delivery.set_enabled(True)
    run(sc, feed, 39.5, delivery)  # 06:09:30, candidate pending
    feed._now = FIRST_CONFIRM - timedelta(seconds=20)  # reconnect at 06:09:40, before the confirmation closes
    disconnect_once_then_reconnect(feed)
    sc.scan_once()
    assert sc.session_watermark == FIRST_CONFIRM - timedelta(seconds=20)
    run(sc, feed, 1, delivery)  # through 06:10:40: the 06:10:00 confirmation closes after the new watermark
    (sig,) = store.list_signals()
    assert sig.confirm_close == FIRST_CONFIRM and len(calls) == 1
    run(sc, feed, 5, delivery)  # repeat scans do not duplicate
    assert len(store.list_signals()) == 1 and len(calls) == 1
