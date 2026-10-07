"""Regressions for bug 2 (chronological, period-bounded tick replay) and bug 3 (MT5 replay lifecycle)."""
from datetime import timedelta

import pytest

from app.config import StrategyConfig
from app.models import H1, M5, Bar, Quote, aggregate
from app.replay import Costs, replay
from app.scenarios import buy_setup, sell_setup

from .helpers import CONFIRM_CLOSE, META, T0, idx_at
from .test_replay import _pad

CFG = StrategyConfig()
TICKS = Costs(0.2, 0.0, "ticks")


def z(dt):
    return dt.isoformat().replace("+00:00", "Z")


def ticks(*rows):
    return [Quote(t, b, a) for t, b, a in rows]


def tick_fn(observations, sloppy=False):
    """sloppy=True ignores the requested bounds and returns unsorted ticks; the replay must filter them."""
    def fn(start, end):
        if sloppy:
            return list(reversed(observations))
        return [q for q in observations if start <= q.time <= end]
    return fn


# ---------------------------------------------------------------- bug 2: chronological tick replay
@pytest.mark.parametrize("sloppy", [False, True])
def test_tick_replay_never_settles_after_period_end(sloppy):
    bars = buy_setup(T0)
    bars = bars[: idx_at(bars, CONFIRM_CLOSE + 2 * M5) + 1]  # period ends at confirm + 15 min
    period_end = bars[-1].close_time
    obs = ticks((CONFIRM_CLOSE + timedelta(seconds=2), 2405.5, 2405.7),
                (CONFIRM_CLOSE + timedelta(minutes=5), 2406.0, 2406.2),
                (period_end + timedelta(minutes=25), 2420.0, 2420.2))  # TP only after the period
    r = replay(bars, META, CFG, TICKS, ticks_fn=tick_fn(obs, sloppy))
    (s,) = r.signals
    assert s["outcome"] == "open_at_end" and s["outcome_time"] is None


def test_tick_entry_after_period_end_does_not_fill():
    bars = buy_setup(T0, include_run=False)  # period ends exactly at the confirmation close
    obs = ticks((CONFIRM_CLOSE + timedelta(seconds=2), 2405.5, 2405.7))
    r = replay(bars, META, CFG, TICKS, ticks_fn=tick_fn(obs, sloppy=True))
    assert r.signals == []


def test_missing_ticks_fabricate_nothing():
    bars = _pad(buy_setup(T0))
    assert replay(bars, META, CFG, TICKS, ticks_fn=tick_fn([])).signals == []
    entry_only = ticks((CONFIRM_CLOSE + timedelta(seconds=2), 2405.5, 2405.7))
    (s,) = replay(bars, META, CFG, TICKS, ticks_fn=tick_fn(entry_only)).signals
    assert s["outcome"] == "open_at_end"  # bars reach TP, but no tick ever observed it


def two_setups():
    first = buy_setup(T0, include_run=False)
    gap_start, second_start = first[-1].close_time, T0 + 5 * H1
    filler = [Bar(gap_start + i * M5, M5, 2405.4, 2405.5, 2405.3, 2405.4) for i in range(int((second_start - gap_start) / M5))]
    second = buy_setup(second_start, include_run=False)
    tail = [Bar(second[-1].close_time + i * M5, M5, 2405.4, 2405.5, 2405.3, 2405.4) for i in range(24)]
    return first + filler + second + tail, CONFIRM_CLOSE + 5 * H1


@pytest.mark.parametrize("first_exit_after_second", [True, False])
def test_future_exit_does_not_release_overlap_guard(first_exit_after_second):
    bars, second_confirm = two_setups()
    exit_at = second_confirm + timedelta(minutes=50) if first_exit_after_second else CONFIRM_CLOSE + timedelta(minutes=30)
    obs = sorted(ticks((CONFIRM_CLOSE + timedelta(seconds=2), 2405.5, 2405.7),
                       (exit_at, 2420.0, 2420.2),
                       (second_confirm + timedelta(seconds=2), 2405.5, 2405.7)), key=lambda q: q.time)
    r = replay(bars, META, CFG, TICKS, ticks_fn=tick_fn(obs))
    first = r.signals[0]
    assert first["outcome"] == "tp" and first["outcome_time"] == z(exit_at)
    reasons = {}
    for seg in r.segments.values():
        for k, v in seg["reasons"].items():
            reasons[k] = reasons.get(k, 0) + v
    if first_exit_after_second:
        assert len(r.signals) == 1 and reasons.get("overlapping_active_signal") == 1
    else:
        assert len(r.signals) == 2 and "overlapping_active_signal" not in reasons


def test_tick_sell_exits_use_ask():
    bars = _pad(sell_setup(T0))
    obs = ticks((CONFIRM_CLOSE + timedelta(seconds=2), 2394.6, 2394.8),
                (CONFIRM_CLOSE + timedelta(minutes=20), 2379.9, 2380.1),  # Bid below TP, Ask still above
                (CONFIRM_CLOSE + timedelta(minutes=25), 2379.7, 2379.9))  # Ask reaches TP 2380
    (s,) = replay(bars, META, CFG, TICKS, ticks_fn=tick_fn(obs)).signals
    assert s["entry_quote"] == 2394.6 and s["outcome"] == "tp" and s["outcome_time"] == z(CONFIRM_CLOSE + timedelta(minutes=25))


def test_tick_buy_exits_use_bid():
    bars = _pad(buy_setup(T0))
    obs = ticks((CONFIRM_CLOSE + timedelta(seconds=2), 2405.5, 2405.7),
                (CONFIRM_CLOSE + timedelta(minutes=10), 2399.05, 2398.9),   # Ask below SL is irrelevant for a BUY exit
                (CONFIRM_CLOSE + timedelta(minutes=12), 2398.98, 2399.18))  # Bid touches SL
    (s,) = replay(bars, META, CFG, TICKS, ticks_fn=tick_fn(obs)).signals
    assert s["outcome"] == "sl" and s["outcome_time"] == z(CONFIRM_CLOSE + timedelta(minutes=12))


# ---------------------------------------------------------------- bug 3: MT5 replay lifecycle
class FakeMT5Feed:
    instances: list = []

    def __init__(self, symbol, terminal_path="", offset=0.0, *, fail_connect=False, fail_ticks=False):
        self.events, self.closed = [], False
        self.fail_connect, self.fail_ticks = fail_connect, fail_ticks
        FakeMT5Feed.instances.append(self)

    def connect(self):
        from app.data.base import FeedStatus
        self.events.append("connect")
        if self.fail_connect:
            return FeedStatus(False, "disconnected", "mock: terminal not running")
        return FeedStatus(True, "connected", "mock")

    def meta(self):
        return META

    def bars_range(self, tf, start, end):
        assert not self.closed, "bars read after shutdown"
        self.events.append(f"bars:{tf}")
        m5 = _pad(buy_setup(T0))
        return m5 if tf == "M5" else aggregate(m5)

    def ticks_range(self, start, end):
        assert not self.closed, "ticks_range called after shutdown"
        self.events.append("ticks")
        if self.fail_ticks:
            raise RuntimeError("mock tick failure")
        obs = [Quote(CONFIRM_CLOSE + timedelta(seconds=2), 2405.5, 2405.7),
               Quote(CONFIRM_CLOSE + timedelta(minutes=40), 2420.0, 2420.2)]
        return [q for q in obs if start <= q.time <= end]

    def shutdown(self):
        self.events.append("shutdown")
        self.closed = True


def run_mt5_cli(tmp_path, **kw):
    from app.replay import main
    FakeMT5Feed.instances = []
    out = tmp_path / "mt5-replay.json"
    code = main(["--source", "mt5", "--symbol", "MOCK-XAU", "--days", "36500", "--use-ticks", "--out", str(out)],
                feed_factory=lambda *a, **k: FakeMT5Feed(*a, **k, **kw))
    return code, FakeMT5Feed.instances[0], out


def test_mt5_cli_reads_ticks_before_shutdown(tmp_path):
    code, feed, out = run_mt5_cli(tmp_path)
    assert code == 0 and out.exists()
    assert "ticks" in feed.events and feed.events.count("shutdown") == 1 and feed.events[-1] == "shutdown"
    assert feed.events.index("ticks") < feed.events.index("shutdown")


def test_mt5_cli_cleans_up_on_tick_error(tmp_path):
    with pytest.raises(RuntimeError, match="mock tick failure"):
        run_mt5_cli(tmp_path, fail_ticks=True)
    assert FakeMT5Feed.instances[0].events[-1] == "shutdown"


def test_mt5_cli_cleans_up_when_connect_fails(tmp_path):
    code, feed, out = run_mt5_cli(tmp_path, fail_connect=True)
    assert code == 2 and feed.events == ["connect", "shutdown"] and not out.exists()
