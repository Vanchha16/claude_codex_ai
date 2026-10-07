"""FastSweep live integration: selection, persistent engine, controls, watermark, outcomes, labels (fixtures only)."""
import json
from dataclasses import replace
from datetime import datetime, timedelta

import httpx
import pytest

from app.active_strategy import (ActiveStrategy, fastsweep_version, is_fastsweep_version, load_active_strategy,
                                 parse_active_strategy, save_active_strategy)
from app.config import Settings, StrategyConfig
from app.data.base import FeedStatus
from app.delivery import Delivery, TelegramClient, format_signal
from app.engine import Candidate, Signal
from app.fastsweep import PROFILES, Setup, bangkok_date, build_levels, new_setup
from app.fastsweep_live import FastSweepEngine, retire_foreign_pending
from app.fastsweep_replay import Costs, _daily, replay
from app.models import H1, M5, UTC, Bar, Quote, SymbolMeta, aggregate
from app.outcomes import track_live
from app.scanner import Scanner
from app.store import SqliteStore

from .test_fastsweep import M15, block, m15

META = SymbolMeta("TESTGOLD", 0.01, 0.01, 2, "test")
META3 = SymbolMeta("TESTGOLD", 0.001, 0.001, 3, "test")
RR2 = PROFILES["rr2"]
RR1 = PROFILES["rr1"]
START = datetime(2030, 1, 7, 0, 0, tzinfo=UTC)  # Monday 07:00 Bangkok


def warm(start, n=52, p0=100.0):
    """n contiguous rising M15 candles (EMA20 > EMA50 once 50 are available)."""
    out = []
    for k in range(n):
        c = p0 + 0.5 * k
        out += m15(start + k * M15, c - 0.3, c + 0.1, c - 0.4, c)
    return out


def scenario(outcomes=("tp",), step=5.0):
    """Warm-up then one BUY block per hour. Block k: A at t_k, confirmation bar closes at t_k + 35 min."""
    bars = warm(START)
    t0 = START + 52 * M15
    p = 100 + 0.5 * 51 + 2
    for k, o in enumerate(outcomes):
        bars += block(t0 + k * timedelta(hours=1), p + k * step, o, rr=2.0)
    return bars, t0


def quote_fn(spread=0.2, delay_s=1.0):
    """Live-style entry: a fresh measured quote just after the confirmation close (Bid = confirming bar close)."""
    def fn(c, bar):
        now = bar.close_time + timedelta(seconds=delay_s)
        return Quote(now, bar.close, round(bar.close + spread, 6)), now
    return fn


def drive(bars, eng, entry_fn=None):
    entry_fn = entry_fn or quote_fn()
    out = []
    for i, b in enumerate(bars):
        out += eng.process_bar(bars, i, entry_fn, b.close_time)
    return out


def engine(tmp_path, cfg=RR2, profile="rr2", meta=META, name="t.sqlite"):
    store = SqliteStore(tmp_path / name)
    return FastSweepEngine(cfg, profile, meta, store, "mt5"), store


# ------------------------------------------------------------------ review defect 1: midnight daily table
def test_daily_table_includes_a_candidate_that_closes_exactly_at_bangkok_midnight():
    # two complete M15 candles ending exactly at 2030-01-08 00:00 Bangkok (17:00 UTC): B closes on the NEXT date
    t = datetime(2030, 1, 7, 16, 30, tzinfo=UTC)
    bars = m15(t, 101, 102, 100, 101.5) + m15(t + M15, 101, 101.5, 99.9, 100.8)
    s = new_setup(Bar(t, M15, 101, 102, 100, 101.5), Bar(t + M15, M15, 101, 101.5, 99.9, 100.8), "BUY", "X")
    rows = _daily(bars, [s], [])
    by = {r["date"]: r for r in rows}
    assert by["2030-01-08"]["candidates"] == 1 and by["2030-01-08"]["m5_bars"] == 0 and not by["2030-01-08"]["covered"]
    assert by["2030-01-07"]["m5_bars"] == 6


# ------------------------------------------------------------------ review defect 2: entry timing / future quotes
def _confirmed_setup():
    s = new_setup(Bar(START, M15, 101, 102, 100, 101.5), Bar(START + M15, M15, 101, 101.5, 99.9, 100.8), "BUY", "X")
    s.status, s.confirm_close = "confirmed", s.b_close + M5
    return s


def test_fresh_quote_ten_minutes_after_confirmation_is_rejected():
    s = _confirmed_setup()
    late = s.confirm_close + timedelta(minutes=10)
    assert build_levels(s, Quote(late, 101.6, 101.8), late, META, RR2)[1] == "missed_confirmation_too_late"
    ok = s.confirm_close + timedelta(seconds=29)
    assert build_levels(s, Quote(ok, 101.6, 101.8), ok, META, RR2)[1] is None


def test_quote_later_than_decision_time_is_rejected():
    s = _confirmed_setup()
    now = s.confirm_close + timedelta(seconds=2)
    fut = Quote(now + timedelta(seconds=10), 101.6, 101.8)
    assert build_levels(s, fut, now, META, RR2)[1] == "quote_in_future"
    assert build_levels(s, fut, now, META, RR2, future_tolerance_s=5)[1] == "quote_in_future"
    slight = Quote(now + timedelta(seconds=1), 101.6, 101.8)
    assert build_levels(s, slight, now, META, RR2)[1] == "quote_in_future"
    assert build_levels(s, slight, now, META, RR2, future_tolerance_s=5)[1] is None
    old = Quote(s.confirm_close - timedelta(seconds=1), 101.6, 101.8)
    assert build_levels(s, old, now, META, RR2)[1] == "quote_older_than_confirmation_close"


# ------------------------------------------------------------------ selection
def test_selection_defaults_to_crt_and_rejects_unknowns(tmp_path):
    assert load_active_strategy(tmp_path / "none.json") == ActiveStrategy("crt")
    a = parse_active_strategy({"strategy": "fastsweep", "profile": "rr2"})
    assert a.is_fastsweep and a.fastsweep.reward_risk == 2.0
    for bad in ({"strategy": "turbo"}, {"strategy": "fastsweep", "profile": "rr3"}, {"strategy": "fastsweep"},
                {"strategy": "crt", "profile": "rr2"}, {"strategy": "crt", "extra": 1}, []):
        with pytest.raises(ValueError):
            parse_active_strategy(bad)
    path = tmp_path / "active.json"
    save_active_strategy({"strategy": "fastsweep", "profile": "rr2"}, path)
    with pytest.raises(ValueError):
        save_active_strategy({"strategy": "fastsweep", "profile": "x"}, path)
    assert json.loads(path.read_text()) == {"strategy": "fastsweep", "profile": "rr2"}  # bad choice never written
    path.write_text("{not json")
    with pytest.raises(ValueError):
        load_active_strategy(path)


def test_versions_are_fingerprinted_per_profile():
    v1, v2 = fastsweep_version(RR1), fastsweep_version(RR2)
    assert v1 != v2 and v1.startswith("FastSweep-M15-M5-v1-RR1@") and v2.startswith("FastSweep-M15-M5-v1-RR2@")
    assert is_fastsweep_version(v2) and not is_fastsweep_version(StrategyConfig().version)


# ------------------------------------------------------------------ live engine vs replay parity
def test_live_decisions_match_replay_and_geometry_is_1_to_2(tmp_path):
    bars, t0 = scenario(("tp", "sl", "none"), step=5.0)
    eng, store = engine(tmp_path)
    sigs = drive(bars, eng)
    rep = replay(bars, META, RR2, Costs(0.2, 0.0))
    # The bare engine does not track outcomes (the scanner does), so signal 1 stays active and blocks later entries;
    # compare everything up to the confirmation stage, then the first signal's geometry.
    live = {c.a_open.isoformat().replace("+00:00", "Z"): c for c in store.list_candidates(1000)}
    controls = {"active_signal", "cooldown", "daily_cap"}
    for c in rep["candidates"]:
        lc = live[c["a_open"]]
        if c["confirm_close"]:
            assert lc.confirm_close is not None and lc.confirm_close.isoformat().replace("+00:00", "Z") == c["confirm_close"]
            assert lc.status == "confirmed" or lc.reason in controls
        else:
            assert (lc.status, lc.reason) == (c["status"], c["reason"]), c["a_open"]
    assert len(sigs) >= 1
    s, r0 = sigs[0], rep["signals"][0]
    assert (s.entry, s.sl, s.tp) == pytest.approx((r0["entry"], r0["sl"], r0["tp"]))  # same Ask entry -> same 1:2 levels
    assert s.entry == s.ask and s.sl == pytest.approx(round(s.meta["b_low"] - 0.02, 2))
    assert s.tp - s.entry >= 2 * (s.entry - s.sl) - 1e-9 and s.reward_risk >= 2.0
    assert s.meta["outcome_expiry_hours"] == 2.0 and s.meta["symbol"]["digits"] == 2 and is_fastsweep_version(s.config_version)


def test_ema_warmup_needs_50_contiguous_m15(tmp_path):
    bars = warm(START, n=40)
    bars += block(START + 40 * M15, 125.0, "tp")
    eng, store = engine(tmp_path)
    assert drive(bars, eng) == []
    assert any(c.reason == "trend_warmup" and c.direction == "BUY" for c in store.list_candidates(1000))


def test_invalidation_beats_confirmation_and_live_quote_revisit_blocks_entry(tmp_path):
    bars, t0 = scenario(("tp",))
    i = next(k for k, b in enumerate(bars) if b.open_time == t0 + 2 * M15)  # confirmation bar
    b = bars[i]
    bars[i] = Bar(b.open_time, M5, b.open, b.high, b.low - 5, b.close)       # same bar also revisits B's low
    eng, store = engine(tmp_path)
    assert drive(bars, eng) == []
    assert any(c.reason == "sweep_extreme_revisited" for c in store.list_candidates(1000))
    bars2, _ = scenario(("tp",))
    eng2, store2 = engine(tmp_path, name="t2.sqlite")

    def revisit(c, bar):
        now = bar.close_time + timedelta(seconds=1)
        return Quote(now, c.b_low - 0.01, c.b_low + 0.19), now
    assert drive(bars2, eng2, revisit) == []
    assert any(c.reason == "sweep_extreme_revisited_live_quote" for c in store2.list_candidates(1000))


# ------------------------------------------------------------------ persistence, watermark, controls
def test_restart_reprocessing_creates_no_duplicates(tmp_path):
    bars, _ = scenario(("tp",))
    eng, store = engine(tmp_path)
    first = drive(bars, eng)
    eng2 = FastSweepEngine(RR2, "rr2", META, store, "mt5")
    assert len(first) == 1 and drive(bars, eng2) == []
    assert len(store.list_signals()) == 1


def test_confirmation_at_or_before_watermark_is_context_only(tmp_path):
    bars, t0 = scenario(("tp",))
    eng, store = engine(tmp_path)
    eng.eligible_after = t0 + 35 * timedelta(minutes=1)  # == confirmation close
    assert drive(bars, eng) == []
    c = next(c for c in store.list_candidates(1000) if c.direction == "BUY" and c.a_open == t0)
    assert c.reason == "confirmation_before_session_watermark" and store.list_signals() == []
    eng3, store3 = engine(tmp_path, name="w2.sqlite")
    eng3.eligible_after = t0 + 34 * timedelta(minutes=1)  # strictly before -> actionable
    assert len(drive(bars, eng3)) == 1


def _signal(store, sid, created, version, status="tp", symbol="TESTGOLD"):
    s = Signal(id=sid, candidate_key=sid, symbol=symbol, mode="mt5", direction="BUY", entry=1, sl=0.5, tp=2, reward_risk=2,
               spread=0.2, bid=0.8, ask=1, quote_time=created, confirm_close=created, created_at=created,
               valid_until=created, config_version=version, explanation="", meta={}, outcome_status=status)
    assert store.add_signal(s)


def test_cooldown_and_bangkok_cap_come_from_persisted_signals_across_profiles(tmp_path):
    bars, t0 = scenario(("tp",))
    confirm_now = t0 + timedelta(minutes=35, seconds=1)
    eng, store = engine(tmp_path)
    _signal(store, "old-rr1", confirm_now - timedelta(minutes=20), fastsweep_version(RR1))  # other profile, 20 min ago
    assert drive(bars, eng) == []
    assert any(c.reason == "cooldown" for c in store.list_candidates(1000))
    eng2, store2 = engine(tmp_path, name="cap.sqlite")
    day_start = datetime(2030, 1, 6, 17, 0, tzinfo=UTC)  # 00:00 Bangkok on the confirmation's Bangkok date
    for k in range(4):
        _signal(store2, f"cap{k}", day_start + timedelta(minutes=10 * k), fastsweep_version(RR1 if k % 2 else RR2))
    _signal(store2, "crt", day_start + timedelta(minutes=50), StrategyConfig().version)  # CRT does not count
    assert bangkok_date(confirm_now) == "2030-01-07"
    assert drive(bars, eng2) == []
    assert any(c.reason == "daily_cap" for c in store2.list_candidates(1000))
    eng3, store3 = engine(tmp_path, name="prevday.sqlite")
    for k in range(4):  # all on the previous Bangkok date (before 17:00 UTC on 2030-01-06)
        _signal(store3, f"p{k}", day_start - timedelta(minutes=60 + 10 * k), fastsweep_version(RR2))
    assert len(drive(bars, eng3)) == 1


def test_an_active_crt_signal_blocks_fastsweep_and_keeps_its_own_expiry(tmp_path):
    bars, t0 = scenario(("tp",))
    eng, store = engine(tmp_path)
    _signal(store, "crt-active", t0 - timedelta(hours=3), StrategyConfig().version, status="active")
    assert drive(bars, eng) == []
    assert any(c.reason == "active_signal" for c in store.list_candidates(1000))
    crt = store.get_signal("crt-active")
    cfg = StrategyConfig()
    assert not track_live(crt, [], None, crt.created_at + timedelta(hours=23), cfg, False)  # still 24 h CRT lifetime
    assert track_live(crt, [], None, crt.created_at + timedelta(hours=24), cfg, False)


def test_fastsweep_signal_expires_after_two_hours(tmp_path):
    bars, t0 = scenario(("none",), step=0.0)
    eng, store = engine(tmp_path)
    (sig,) = drive(bars[: next(k for k, b in enumerate(bars) if b.open_time == t0 + 2 * M15) + 1], eng)
    cfg = StrategyConfig()
    assert not track_live(sig, [], None, sig.created_at + timedelta(hours=1, minutes=59), cfg, False)
    assert track_live(sig, [], None, sig.created_at + timedelta(hours=2), cfg, False) and sig.outcome_status == "expired"


def test_foreign_pending_setups_are_retired_not_processed(tmp_path):
    store = SqliteStore(tmp_path / "r.sqlite")
    t = START
    crt = Candidate(key="TESTGOLD|x|CRT", symbol="TESTGOLD", config_version=StrategyConfig().version, mode="mt5",
                    direction="BUY", a_open=t, b_open=t + H1, b_close=t + 2 * H1, a_high=2, a_low=1, b_high=1.5,
                    b_low=0.9, status="pending", level=1.8, deadline=t + 3 * H1)
    store.add_candidate(crt)
    assert retire_foreign_pending(store, "TESTGOLD", fastsweep_version(RR2), t + 3 * H1) == 1
    c = store.get_candidate("TESTGOLD|x|CRT")
    assert (c.status, c.reason) == ("expired", "retired_strategy_switch")


def test_message_is_four_lines_at_symbol_precision(tmp_path):
    bars, _ = scenario(("tp",))
    eng, store = engine(tmp_path, meta=META3)
    (sig,) = drive(bars, eng)
    lines = format_signal(sig).split("\n")
    assert [ln.split(":")[0] for ln in lines] == ["\U0001F4CD Entry", "\U0001F3AF TP", "\U0001F6D1 SL", "⚖️ RR"]
    assert lines[0].endswith(f"{sig.entry:.3f}") and lines[3].endswith(f"{sig.reward_risk:.2f}")


# ------------------------------------------------------------------ scanner integration with a fake MT5-like feed
class FakeFeed:
    mode = "mt5"
    supports_ticks = False

    def __init__(self, bars, now):
        self.bars, self._now = bars, now

    def now(self):
        return self._now

    def connect(self):
        return self.status()

    def shutdown(self):
        pass

    def status(self):
        return FeedStatus(True, "connected", "fake feed")

    def meta(self):
        return META

    def closed_bars(self, tf, n):
        done = [b for b in self.bars if b.close_time <= self._now]
        return (aggregate(done, H1) if tf == "H1" else done)[-n:]

    def quote(self):
        done = [b for b in self.bars if b.close_time <= self._now]
        c = done[-1].close if done else 100.0
        return Quote(self._now - timedelta(seconds=1), c, round(c + 0.2, 6))


def make_scanner(tmp_path, bars, now, calls):
    store = SqliteStore(tmp_path / "scan.sqlite")
    settings = Settings(telegram_bot_token="1:x", telegram_test_chat_id="-1")

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(calls)}})
    feed = FakeFeed(bars, now)
    delivery = Delivery(store, settings, clock=feed.now,
                        client_factory=lambda t: TelegramClient(t, transport=httpx.MockTransport(handler)))
    active = ActiveStrategy("fastsweep", "rr2", RR2)
    return Scanner(settings, StrategyConfig(), feed, store, delivery, active=active), feed, store, delivery


def step(sc, feed, delivery, until):
    while feed._now < until:
        feed._now += timedelta(seconds=10)
        sc.scan_once()
        delivery.process_due()


def test_scanner_live_signal_after_watermark_is_sent_once_in_four_lines(tmp_path):
    bars, t0 = scenario(("tp",))
    calls = []
    sc, feed, store, delivery = make_scanner(tmp_path, bars, t0 + 20 * timedelta(minutes=1), calls)
    store.set_meta("last_m5_close", (t0 - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"))
    delivery.set_enabled(True)
    step(sc, feed, delivery, t0 + timedelta(minutes=50))
    (sig,) = store.list_signals()
    assert is_fastsweep_version(sig.config_version) and sig.confirm_close > sc.session_watermark
    assert len(calls) == 1 and calls[0]["text"] == format_signal(sig) and len(calls[0]["text"].split("\n")) == 4
    assert "parse_mode" not in calls[0]
    st = sc.strategy_state()
    assert st["readiness"]["ready"] and st["readiness"]["required"] == 50


def test_scanner_restart_after_confirmation_sends_nothing(tmp_path):
    bars, t0 = scenario(("tp",))
    calls = []
    sc, feed, store, delivery = make_scanner(tmp_path, bars, t0 + timedelta(minutes=36), calls)
    store.set_meta("last_m5_close", (t0 - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"))
    delivery.set_enabled(True)
    step(sc, feed, delivery, t0 + timedelta(minutes=50))
    assert store.list_signals() == [] and store.outbox_rows() == [] and calls == []
    c = next(c for c in store.list_candidates(1000) if c.direction == "BUY" and c.a_open == t0)
    assert c.reason == "confirmation_before_session_watermark"


def test_scanner_pause_keeps_tracking_and_resume_cancels_pending(tmp_path):
    bars, t0 = scenario(("none",), step=0.0)
    calls = []
    sc, feed, store, delivery = make_scanner(tmp_path, bars, t0 + 20 * timedelta(minutes=1), calls)
    store.set_meta("last_m5_close", (t0 - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"))
    step(sc, feed, delivery, t0 + timedelta(minutes=40))
    (sig,) = store.list_signals()
    sc.pause()
    step(sc, feed, delivery, sig.created_at + timedelta(hours=2, minutes=1))
    assert store.get_signal(sig.id).outcome_status == "expired"  # outcome tracking continues while paused
    sc.resume()
    assert not [c for c in store.pending_candidates("TESTGOLD") if is_fastsweep_version(c.config_version)]


def test_scan_at_the_exact_close_waits_for_the_first_quote_after_it(tmp_path):
    bars, t0 = scenario(("tp",))
    eng, store = engine(tmp_path)
    close = t0 + timedelta(minutes=35)
    early = lambda c, bar: (Quote(close - timedelta(seconds=1), 129.0, 129.2), close)  # stamped before the close
    i_conf = next(k for k, b in enumerate(bars) if b.close_time == close)
    for i in range(i_conf + 1):
        eng.process_bar(bars, i, early, bars[i].close_time)
    c = next(c for c in store.pending_candidates("TESTGOLD") if c.confirm_close == close)
    assert c.reason == "awaiting_first_quote_after_close" and store.list_signals() == []
    after = lambda c, bar: (Quote(close + timedelta(seconds=3), 129.0, 129.2), close + timedelta(seconds=4))
    (sig,) = eng.retry_awaiting(after, close + timedelta(seconds=4))
    assert sig.quote_time == close + timedelta(seconds=3)
    eng2, store2 = engine(tmp_path, name="late.sqlite")  # no observation within 30 s -> rejected, never late-filled
    for i in range(i_conf + 1):
        eng2.process_bar(bars, i, early, bars[i].close_time)
    late = lambda c, bar: (Quote(close + timedelta(seconds=40), 129.0, 129.2), close + timedelta(seconds=41))
    assert eng2.retry_awaiting(late, close + timedelta(seconds=41)) == []
    assert any(x.reason == "missed_confirmation_too_late" for x in store2.list_candidates(1000))


def test_api_reports_the_active_strategy_and_per_record_identity(tmp_path):
    from fastapi.testclient import TestClient
    from app.web import create_app
    app = create_app(Settings(port=8000, demo_speed=600), state_dir=tmp_path, extra_hosts=("testserver",),
                     active_strategy_loader=lambda: parse_active_strategy({"strategy": "fastsweep", "profile": "rr2"}))
    with TestClient(app) as c:
        s = c.get("/api/state").json()
        assert s["active_strategy"]["kind"] == "fastsweep" and s["active_strategy"]["reward_risk"] == 2.0
        assert s["timeframes"] == {"range": "M15", "confirmation": "M5"}
        assert s["strategy"]["version"].startswith("FastSweep-M15-M5-v1-RR2@") and s["strategy"]["max_spread_price"] == 0.5
        assert s["crt_strategy"]["version"].startswith("CRT-SMC-v1@")
        r = c.get("/api/replay?source=mt5&strategy=fastsweep").json()
        assert r["available"] is False and r["strategy"] == "fastsweep"
        assert c.get("/api/replay?source=mt5&strategy=nope").status_code == 400
        for cand in c.get("/api/candidates?limit=50").json():
            assert cand["strategy"] == ("FastSweep" if cand["config_version"].startswith("FastSweep") else "CRT-SMC-v1")
            assert cand["range_tf"] == ("M15" if cand["strategy"] == "FastSweep" else "H1")


def test_invalid_selection_fails_startup_clearly(tmp_path):
    from app.web import create_app
    with pytest.raises(ValueError):
        create_app(Settings(port=8000), state_dir=tmp_path, autostart=False,
                   active_strategy_loader=lambda: parse_active_strategy({"strategy": "fastsweep", "profile": "rr9"}))


# ------------------------------------------------------------------ retry path must honour the strict watermark
def _awaiting(tmp_path, name):
    """Persist a confirmed setup that is still waiting for its first quote at/after the close (quote stamped earlier)."""
    bars, t0 = scenario(("tp",))
    eng, store = engine(tmp_path, name=name)
    close = t0 + timedelta(minutes=35)
    early = lambda c, bar: (Quote(bar.close_time - timedelta(seconds=1), 129.0, 129.2), bar.close_time + timedelta(seconds=1))
    for i, b in enumerate(bars):
        if b.close_time > close:
            break
        eng.process_bar(bars, i, early, b.close_time)
    c = next(c for c in store.pending_candidates("TESTGOLD") if c.confirm_close == close)
    assert c.reason == "awaiting_first_quote_after_close"
    fresh = lambda c, bar: (Quote(close + timedelta(seconds=4), 129.0, 129.2), close + timedelta(seconds=5))
    return eng, store, c, close, fresh


@pytest.mark.parametrize("offset_s", [0, 3])  # new watermark EQUAL to / LATER than the stored confirmation close
def test_restart_retry_never_signals_a_confirmation_at_or_before_the_new_watermark(tmp_path, offset_s):
    _, store, c, close, fresh = _awaiting(tmp_path, f"wm{offset_s}.sqlite")
    eng2 = FastSweepEngine(RR2, "rr2", META, store, "mt5")  # process restart -> new engine, new watermark
    eng2.eligible_after = close + timedelta(seconds=offset_s)
    assert eng2.retry_awaiting(fresh, close + timedelta(seconds=5)) == []
    got = store.get_candidate(c.key)
    assert (got.status, got.reason) == ("rejected", "confirmation_before_session_watermark")
    assert store.list_signals() == [] and store.outbox_rows() == []
    assert eng2._family_signals() == []                      # no daily quota used
    assert eng2.retry_awaiting(fresh, close + timedelta(seconds=6)) == []  # consumed, not retried again


def test_retry_strictly_after_the_watermark_still_creates_exactly_one_signal(tmp_path):
    _, store, c, close, fresh = _awaiting(tmp_path, "ok.sqlite")
    eng2 = FastSweepEngine(RR2, "rr2", META, store, "mt5")
    eng2.eligible_after = close - timedelta(seconds=1)
    assert len(eng2.retry_awaiting(fresh, close + timedelta(seconds=5))) == 1
    assert eng2.retry_awaiting(fresh, close + timedelta(seconds=6)) == [] and len(store.list_signals()) == 1


def test_recovery_watermark_on_the_same_engine_rejects_a_stored_confirmation(tmp_path):
    eng, store, c, close, fresh = _awaiting(tmp_path, "rec.sqlite")
    eng.eligible_after = close + timedelta(seconds=2)  # scanner opened a new session after a stale/disconnected feed
    assert eng.retry_awaiting(fresh, close + timedelta(seconds=5)) == []
    assert store.get_candidate(c.key).reason == "confirmation_before_session_watermark" and store.list_signals() == []


def test_scanner_restart_while_awaiting_quote_sends_nothing(tmp_path):
    bars, t0 = scenario(("tp",))
    close = t0 + timedelta(minutes=35)
    calls = []
    sc, feed, store, delivery = make_scanner(tmp_path, bars, t0 + timedelta(minutes=20), calls)
    store.set_meta("last_m5_close", (t0 - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"))
    delivery.set_enabled(True)
    while feed._now < close:  # scans every 10 s; the scan AT the close sees a quote stamped 1 s before it
        feed._now += timedelta(seconds=10)
        sc.scan_once()
        delivery.process_due()
    c = next(c for c in store.pending_candidates("TESTGOLD") if c.confirm_close == close)
    assert c.reason == "awaiting_first_quote_after_close" and store.list_signals() == []
    # process restart 3 s after the close: new scanner/engine on the same database, new session watermark
    feed._now = close + timedelta(seconds=3)
    sc2 = Scanner(sc.settings, StrategyConfig(), feed, store, delivery, active=sc.active)
    for _ in range(6):
        sc2.scan_once()
        delivery.process_due()
        feed._now += timedelta(seconds=5)
    assert sc2.session_watermark >= close
    assert store.list_signals() == [] and store.outbox_rows() == [] and calls == []
    assert store.get_candidate(c.key).reason == "confirmation_before_session_watermark"
