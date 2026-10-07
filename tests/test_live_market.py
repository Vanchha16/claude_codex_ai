"""Live-market workflow (task 20261002-141133): configuration, persisted live source, exact symbol, UTC epochs,
chart-only market data, measured Bid/Ask outcomes, delivery opt-in, Telegram verification and the
cross-process owner guard. Everything here uses mocks: no MT5 terminal, no Telegram network."""
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, Settings, load_settings, save_local_settings
from app.data.mt5 import MT5Feed
from app.active_strategy import ActiveStrategy
from app.delivery import Delivery, TelegramClient, format_signal
from app.engine import Signal
from app.models import M5, UTC, Quote
from app.outcomes import track_measured
from app.owner import OwnerLock
from app.config import StrategyConfig
from app.store import SqliteStore
from app.web import create_app

from .fake_mt5 import FakeMT5, utc

NOW = utc(2026, 9, 30, 10, 2, 30)
CFG = StrategyConfig()
TOKEN = "123456:LIVE-TOKEN-xyz"


# ------------------------------------------------------------------ configuration
def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_config_sources_aliases_and_precedence(tmp_path, monkeypatch):
    venv_env = write(tmp_path / ".venv" / ".env", "TELEGRAM_BOT_TOKEN=alias-token\nTELEGRAM_CHAT_ID=-1001111111\n"
                     "TELEGRAM_BOT_USERNAME=my_bot\nTELEGRAM_PROVIDERS=telegram\nOPENAI_API_KEY=sk-secret\n")
    root_env = write(tmp_path / ".env", "GOLD_TELEGRAM_TEST_CHAT_ID=-1002222222\nGOLD_SYMBOL=XAUUSD\n")
    local = tmp_path / "local_settings.json"
    for k in [k for k in list(__import__("os").environ) if k.startswith(("GOLD_", "TELEGRAM_"))]:
        monkeypatch.delenv(k, raising=False)
    s = load_settings(env_files=(venv_env, root_env), local_path=local)
    assert s.telegram_bot_token == "alias-token" and s.origins["telegram_bot_token"].endswith(":TELEGRAM_BOT_TOKEN")
    assert s.telegram_test_chat_id == "-1002222222"  # canonical key beats the alias in another file
    assert s.symbol == "XAUUSD"
    # local dashboard settings override .env files; the process environment overrides everything
    save_local_settings({"symbol": "XAUUSDm"}, local)
    assert load_settings(env_files=(venv_env, root_env), local_path=local).symbol == "XAUUSDm"
    monkeypatch.setenv("GOLD_SYMBOL", "XAUUSD.r")
    s2 = load_settings(env_files=(venv_env, root_env), local_path=local)
    assert s2.symbol == "XAUUSD.r" and s2.env_locked("symbol")
    # a canonical key in a LOWER-precedence file still beats an alias in a higher one
    write(venv_env, "GOLD_TELEGRAM_BOT_TOKEN=canonical-token\n")
    write(root_env, "TELEGRAM_BOT_TOKEN=alias-in-root\n")
    assert load_settings(env_files=(venv_env, root_env), local_path=local).telegram_bot_token == "canonical-token"
    # unrecognised keys are never imported and secrets never appear in the public status
    status = json.dumps(s.public_status())
    for secret in ("alias-token", "sk-secret", "my_bot"):
        assert secret not in status and secret not in repr(s)
    assert "OPENAI_API_KEY" not in status and s.redact("x alias-token y") == "x <redacted-token> y"


def test_bot_username_is_not_a_chat_id_and_local_settings_never_hold_tokens(tmp_path):
    local = tmp_path / "local_settings.json"
    with pytest.raises(ConfigError, match="numeric chat ID"):
        save_local_settings({"telegram_test_chat_id": "@my_bot"}, local)
    with pytest.raises(ConfigError):
        save_local_settings({"symbol": "XAU USD"}, local)
    with pytest.raises(ConfigError, match="cannot be set"):
        save_local_settings({"telegram_bot_token": "123:abc"}, local)
    saved = save_local_settings({"telegram_test_chat_id": "-1009876543210", "data_mode": "mt5"}, local)
    assert saved["data_mode"] == "mt5" and "token" not in local.read_text(encoding="utf-8").lower().replace("tokens", "")


# ------------------------------------------------------------------ MT5 feed (mocked module)
def test_exact_symbol_required_when_several_gold_contracts(tmp_path):
    fake = FakeMT5(now=NOW)
    feed = MT5Feed("", module=fake)
    st = feed.connect()
    assert not st.ok and st.state == "symbol_selection_required"
    assert [c["name"] for c in st.details["candidates"]] == ["XAUUSD", "XAUUSDm"]
    acct = st.details["account"]
    assert acct["server"] == "Exness-MT5Trial" and "login" not in acct and "balance" not in acct
    feed = MT5Feed("XAUUSDm", module=fake)
    st = feed.connect()
    assert st.ok and feed.meta().tick_size == 0.001 and feed.meta().digits == 3  # metadata from symbol_info
    assert not MT5Feed("XAUUSD.pro", module=fake).connect().ok  # never silently switches contracts


def test_mt5_epochs_are_utc_without_shift(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    fake = FakeMT5(now=now)
    feed = MT5Feed("XAUUSD", module=fake)
    feed.connect()
    q = feed.quote()
    assert q.time == now and q.time.tzinfo is not None  # epoch taken as UTC, unshifted
    bars = feed.closed_bars("M5", 3)
    expected_last_open = datetime.fromtimestamp((int(now.timestamp()) // 300) * 300 - 300, tz=timezone.utc)
    assert bars[-1].open_time == expected_last_open and bars[-1].close_time <= feed.now()  # forming bar excluded
    legacy = MT5Feed("XAUUSD", server_utc_offset_hours=2, module=FakeMT5(now=now))
    st = legacy.connect()
    assert st.details["legacy_utc_offset_hours"] == 2  # explicit, visible, never applied silently
    assert legacy.quote().time == now - timedelta(hours=2)


def test_chart_bars_ascending_unique_forming_and_tick_volume():
    fake = FakeMT5(now=datetime.now(UTC))
    feed = MT5Feed("XAUUSD", module=fake)
    feed.connect()
    bars, forming = feed.chart_bars("M15", 20)
    times = [b.time for b in bars]
    assert times == sorted(set(times)) and len(bars) == 20
    assert forming is not None and forming.forming and forming.time > times[-1]
    assert all(b.volume is not None for b in bars)  # actual tick_volume passed through
    older, none = feed.chart_bars("M15", 10, before=datetime.fromtimestamp(times[0], tz=UTC))
    assert none is None and older[-1].time < times[0]
    assert "rates_pos:M15" in fake.calls and not any(c.startswith("ticks") for c in fake.calls)


def test_missing_terminal_is_honest_disconnected_state():
    st = MT5Feed("XAUUSD", module=FakeMT5(now=NOW, init_ok=False)).connect()
    assert not st.ok and st.state == "disconnected" and "initialize failed" in st.message


# ------------------------------------------------------------------ persisted live source (API)
class StaticFeedFactory:
    def __init__(self, fake):
        self.fake = fake

    def __call__(self, settings):
        return MT5Feed(settings.symbol, settings.mt5_terminal_path, module=self.fake)


def make_client(tmp_path, *, fake=None, data_mode="mt5", symbol=""):
    local = tmp_path / "local_settings.json"
    if not local.exists():
        save_local_settings({"data_mode": data_mode, "symbol": symbol}, local)
    loader = lambda: load_settings(env={"GOLD_TELEGRAM_BOT_TOKEN": TOKEN}, local_path=local)
    app = create_app(loader(), state_dir=tmp_path / "state", extra_hosts=("testserver",), settings_loader=loader,
                     active_strategy_loader=lambda: ActiveStrategy("crt"),
                     local_settings_path=local, feed_factory=StaticFeedFactory(fake or FakeMT5(now=NOW, init_ok=False)))
    return TestClient(app), app.state.token, local


def test_configured_live_source_survives_restart_without_demo_fallback(tmp_path):
    c, token, local = make_client(tmp_path)
    with c:
        st = c.get("/api/state").json()
        assert st["mode"] == "mt5" and st["feed"]["state"] == "disconnected" and st["demo"] is None
        assert st["strategy_state"]["state"] == "disconnected"
        bars = c.get("/api/market/bars?tf=M5").json()
        assert bars["available"] is False and bars["bars"] == []  # no fictional substitute
    c2, _, _ = make_client(tmp_path)  # "restart": same persisted settings
    with c2:
        assert c2.get("/api/state").json()["mode"] == "mt5"


def test_setup_flow_selects_exact_symbol_and_opens_new_session(tmp_path):
    fake = FakeMT5(now=datetime.now(UTC))
    c, token, local = make_client(tmp_path, fake=fake)
    h = {"X-Session-Token": token}
    with c:
        st = c.get("/api/state").json()
        assert st["feed"]["state"] == "symbol_selection_required"
        assert c.post("/api/setup", headers=h, json={"symbol": "bad symbol!"}).status_code == 400
        r = c.post("/api/setup", headers=h, json={"symbol": "XAUUSDm"}).json()
        assert "new scanner session" in r["action"]
        assert json.loads(local.read_text(encoding="utf-8"))["symbol"] == "XAUUSDm"
        for _ in range(40):
            st = c.get("/api/state").json()
            if st["feed"] and st["feed"]["ok"] and st["scanner"]["session_watermark"]:
                break
            time.sleep(0.1)
        assert st["symbol"]["name"] == "XAUUSDm" and st["account"]["server"] == "Exness-MT5Trial"
        assert st["scanner"]["session_watermark"] is not None
        assert c.post("/api/scanner/pause", headers=h).json()["paused"] is True
        with c.app.state.ws.scanner._feed_lock:  # let any scan already in flight finish; later scans are paused
            pass
        before = len(c.get("/api/candidates").json())
        bars = c.get("/api/market/bars?tf=H4&count=50").json()
        assert bars["available"] and bars["symbol"] == "XAUUSDm" and len(bars["bars"]) == 50
        c.get("/api/market/bars?tf=M1&count=100")
        assert len(c.get("/api/candidates").json()) == before  # chart requests never create strategy candidates
        assert c.get("/api/market/bars?tf=W1").status_code == 400
        assert c.get("/api/market/bars?tf=M5&count=5000").status_code == 400


def test_demo_chart_without_any_setup_and_unavailable_m1(tmp_path):
    c, token, local = make_client(tmp_path, data_mode="demo")
    with c:
        m5 = c.get("/api/market/bars?tf=M5&count=50").json()
        assert m5["available"] and m5["source"] == "demo" and len(m5["bars"]) == 50
        assert m5["forming"] is None or m5["forming"]["forming"] is True
        m1 = c.get("/api/market/bars?tf=M1").json()
        assert m1["available"] is False and "not available" in m1["reason"]
        assert c.get("/api/signals").json() == []


# ------------------------------------------------------------------ messages
def make_signal(mode="mt5", direction="SELL", created=NOW):
    return Signal(id="SIG-1", candidate_key="XAUUSD|k|v", symbol="XAUUSD", mode=mode, direction=direction,
                  entry=2400.0 if direction == "SELL" else 2400.2, sl=2405.0 if direction == "SELL" else 2395.0,
                  tp=2390.0 if direction == "SELL" else 2410.0, reward_risk=2.0, spread=0.2, bid=2400.0, ask=2400.2,
                  quote_time=created, confirm_close=created - timedelta(seconds=1), created_at=created,
                  valid_until=created + timedelta(seconds=120), config_version="CRT-SMC-v1@x", explanation="e",
                  meta={"symbol": {"digits": 2}}, last_checked=created)


def test_messages_are_four_fields_for_every_mode_and_side():
    sell = "📍 Entry: 2400.00\n🎯 TP: 2390.00\n🛑 SL: 2405.00\n⚖️ RR: 2.00"
    buy = "📍 Entry: 2400.20\n🎯 TP: 2410.00\n🛑 SL: 2395.00\n⚖️ RR: 2.00"
    assert format_signal(make_signal("mt5", "SELL")) == sell == format_signal(make_signal("demo", "SELL"))
    assert format_signal(make_signal("mt5", "BUY")) == buy == format_signal(make_signal("demo", "BUY"))


# ------------------------------------------------------------------ measured outcomes
def q(sec, bid, ask):
    return Quote(NOW + timedelta(seconds=sec), bid, ask)


def test_sell_exit_needs_an_observed_ask_tick():
    sig = make_signal("mt5", "SELL")
    assert not any(track_measured(sig, [q(10, 2389.9, 2390.1)], NOW + timedelta(seconds=11), CFG) and
                   sig.outcome_status != "active" for _ in [0])  # Bid below TP, Ask still above: no hit
    assert sig.outcome_status == "active"
    assert track_measured(sig, [q(20, 2389.7, 2389.9)], NOW + timedelta(seconds=21), CFG)
    assert sig.outcome_status == "tp" and sig.outcome_price == 2389.9 and "Ask tick" in sig.outcome_note


def test_buy_exit_uses_bid_and_future_observations_are_ignored():
    sig = make_signal("mt5", "BUY")
    changed = track_measured(sig, [q(5, 2394.99, 2395.3), q(500, 2411, 2411.2)], NOW + timedelta(seconds=6), CFG)
    assert changed and sig.outcome_status == "sl" and sig.outcome_price == 2394.99  # Bid touched SL; t+500s ignored


def test_tick_gap_is_recorded_not_estimated():
    sig = make_signal("mt5", "SELL")
    assert track_measured(sig, [], NOW + timedelta(minutes=5), CFG, gap="10:00..10:05: tick history unavailable")
    assert sig.outcome_status == "active" and sig.meta["measurement_gaps"] == 1
    track_measured(sig, [], NOW + timedelta(hours=25), CFG)
    assert sig.outcome_status == "expired" and sig.outcome_r is None  # no observed exit-side tick to mark


def test_scanner_reads_ticks_and_records_gaps(tmp_path):
    from app.delivery import Delivery as D
    from app.scanner import Scanner
    fake = FakeMT5(now=datetime.now(UTC), symbols=("XAUUSD",))
    feed = MT5Feed("XAUUSD", module=fake)
    feed.connect()
    store = SqliteStore(tmp_path / "s.sqlite")
    t0 = datetime.now(UTC) - timedelta(minutes=10)
    sig = make_signal("mt5", "SELL", created=t0)
    store.add_signal(sig)
    sc = Scanner(Settings(), CFG, feed, store, D(store, Settings(), source="mt5", symbol="XAUUSD"))
    fake.ticks = [((t0 + timedelta(minutes=2)).timestamp(), 2389.9, 2390.1),
                  ((t0 + timedelta(minutes=3)).timestamp(), 2389.6, 2389.8)]
    sc.scan_once()
    (after,) = store.list_signals()
    assert after.outcome_status == "tp" and after.outcome_price == 2389.8 and "ticks" in fake.calls
    sig2 = make_signal("mt5", "SELL", created=t0)
    sig2.id, sig2.candidate_key = "SIG-2", "XAUUSD|k2|v"
    store.add_signal(sig2)
    fake.tick_error = True
    sc.scan_once()
    s2 = store.get_signal("SIG-2")
    assert s2.outcome_status == "active" and s2.meta.get("measurement_gaps") == 1


# ------------------------------------------------------------------ delivery opt-in + Telegram verification
def make_delivery(tmp_path, *, source="mt5", symbol="XAUUSD", chat="-1001234567890", transport=None):
    store = SqliteStore(tmp_path / f"d-{source}-{symbol}-{chat}.sqlite")
    s = Settings(telegram_bot_token=TOKEN, telegram_test_chat_id=chat)
    factory = (lambda t: TelegramClient(t, transport=transport)) if transport else None
    return Delivery(store, s, client_factory=factory, source=source, symbol=symbol, optin_path=tmp_path / "optin.json")


def test_delivery_optin_persists_only_for_the_same_live_binding(tmp_path):
    d = make_delivery(tmp_path)
    assert d.enabled is False  # never on by default
    d.set_enabled(True)
    saved = (tmp_path / "optin.json").read_text(encoding="utf-8")
    assert TOKEN not in saved and "XAUUSD" in saved
    assert make_delivery(tmp_path).enabled is True  # restart restores the explicit opt-in
    assert make_delivery(tmp_path, source="demo", symbol="").enabled is False  # demo never inherits it
    assert (tmp_path / "optin.json").exists()
    changed = make_delivery(tmp_path, chat="-1009999999999")
    assert changed.enabled is False and "chat" in changed.optin_note and not (tmp_path / "optin.json").exists()
    d2 = make_delivery(tmp_path)
    assert d2.enabled is False  # invalidated opt-in requires a new explicit enable
    d2.set_enabled(True)
    assert make_delivery(tmp_path, symbol="XAUUSDm").enabled is False


def test_disable_removes_optin(tmp_path):
    d = make_delivery(tmp_path)
    d.set_enabled(True)
    d.set_enabled(False)
    assert not (tmp_path / "optin.json").exists() and make_delivery(tmp_path).enabled is False


def test_verify_uses_getme_getchat_only_and_redacts(tmp_path):
    seen = []

    def handler(request):
        seen.append(request.url.path.rsplit("/", 1)[-1])
        if request.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"id": 42, "username": "vc_signal_bot"}})
        return httpx.Response(400, json={"ok": False, "description": f"Bad Request: chat not found {TOKEN}"})
    d = make_delivery(tmp_path, transport=httpx.MockTransport(handler))
    out = d.verify()
    assert seen == ["getMe", "getChat"]  # read-only: no sendMessage, no getUpdates
    assert out["bot"]["username"] == "vc_signal_bot" and out["chat_ok"] is False
    assert TOKEN not in json.dumps(out) and "chat not found" in out["chat_error"]


# ------------------------------------------------------------------ cross-process owner guard
HOLD = """
import sys, time
sys.path.insert(0, {root!r})
from pathlib import Path
from app.owner import OwnerLock
lock = OwnerLock(Path({path!r}))
print("acquired" if lock.acquire() else "refused", flush=True)
time.sleep(60)
"""


def test_second_process_cannot_own_scanner_and_recovers_after_owner_dies(tmp_path):
    path = tmp_path / "owner.lock"
    root = str(Path(__file__).resolve().parent.parent)
    child = subprocess.Popen([sys.executable, "-c", HOLD.format(root=root, path=str(path))], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "acquired"
        mine = OwnerLock(path)
        assert mine.acquire() is False
        assert mine.holder()["pid"] != __import__("os").getpid()  # recorded owner is the other process
        child.kill()
        child.wait(10)
        for _ in range(50):
            if mine.acquire():
                break
            time.sleep(0.1)
        assert mine.held  # the OS released the dead owner's lock: clean recovery
        mine.release()
    finally:
        if child.poll() is None:
            child.kill()


def test_second_app_in_same_state_dir_serves_no_scanner(tmp_path):
    c1, _, _ = make_client(tmp_path, data_mode="demo")
    with c1:
        loader = lambda: load_settings(env={}, local_path=tmp_path / "local_settings.json")
        lock = OwnerLock(tmp_path / "state" / "owner.lock")
        child = subprocess.Popen([sys.executable, "-c", (
            "import sys, json; sys.path.insert(0, %r)\n"
            "from pathlib import Path\nfrom app.owner import OwnerLock\n"
            "print(OwnerLock(Path(%r)).acquire())") % (str(Path(__file__).resolve().parent.parent), str(lock.path))],
            stdout=subprocess.PIPE, text=True)
        out, _ = child.communicate(timeout=30)
        assert out.strip() == "False"  # another process cannot become a second scanner/sender
        assert c1.get("/api/health").json()["owner"] is True


def test_never_launches_a_terminal_and_backs_off_reconnects(tmp_path, monkeypatch):
    import app.data.mt5 as mt5mod
    from app.delivery import Delivery as D
    from app.scanner import Scanner
    fake = FakeMT5(now=NOW, init_ok=False)
    feed = MT5Feed("XAUUSD", module=fake)
    feed.require_running_terminal = True
    monkeypatch.setattr(mt5mod, "terminal_running", lambda: False)
    st = feed.connect()
    assert st.state == "disconnected" and "not running" in st.message and "initialize" not in fake.calls
    monkeypatch.setattr(mt5mod, "terminal_running", lambda: True)
    feed.require_running_terminal = False
    store = SqliteStore(tmp_path / "b.sqlite")
    sc = Scanner(Settings(), CFG, feed, store, D(store, Settings(), source="mt5", symbol="XAUUSD"))
    for _ in range(5):
        sc.scan_once()
    assert fake.calls.count("initialize") == 1  # bounded back-off between failed reconnects


# ---------------------------------------------------------------- task 20261005-093051: detection + disconnected Resume
import subprocess as _sp

import app.data.mt5 as _mt5mod


def _fake_runner(tasklist, powershell):
    """tasklist/powershell: (returncode, stdout) or None (command could not run)."""
    def run(args, timeout):
        spec = tasklist if args[0] == "tasklist" else powershell
        return None if spec is None else _sp.CompletedProcess(args, spec[0], spec[1], "")
    return run


@pytest.mark.parametrize("tasklist,powershell,expected", [
    ((1, "ERROR: Access denied\n"), (0, "terminal64\n"), True),          # observed on 2026-10-05: denied, but running
    ((1, "ERROR: Access denied\n"), (0, ""), False),                     # fallback enumerated: genuinely absent
    ((1, "ERROR: Access denied\n"), (1, ""), None),                      # neither could enumerate: unknown
    (None, None, None),
    ((0, "INFO: No tasks are running which match the specified criteria.\n"), None, False),
    ((0, "terminal64.exe   9152 Console  6  160,572 K\n"), None, True),
])
def test_terminal_detection_is_tri_state(monkeypatch, tasklist, powershell, expected):
    monkeypatch.setattr(_mt5mod, "_run_hidden", _fake_runner(tasklist, powershell))
    assert _mt5mod.terminal_running() is expected


@pytest.mark.parametrize("seen,word", [(None, "Could not confirm"), (False, "not running")])
def test_unverified_or_absent_terminal_never_initializes(monkeypatch, seen, word):
    fake = FakeMT5(now=NOW)
    feed = MT5Feed("XAUUSDc", module=fake)
    feed.require_running_terminal = True
    monkeypatch.setattr(_mt5mod, "terminal_running", lambda: seen)
    st = feed.connect()
    assert not st.ok and word in st.message and "initialize" not in fake.calls
    with pytest.raises(RuntimeError, match="not connected"):
        feed.closed_bars("M5", 3)  # clear error, never AttributeError on an uninitialised module


def test_resume_while_disconnected_then_safe_recovery(tmp_path, monkeypatch):
    from app.delivery import Delivery as D
    from app.scanner import Scanner
    feed = MT5Feed("XAUUSD")  # real-module path; the process check keeps the module untouched
    feed.require_running_terminal = True
    monkeypatch.setattr(_mt5mod, "terminal_running", lambda: False)
    store = SqliteStore(tmp_path / "r.sqlite")
    sc = Scanner(Settings(), CFG, feed, store, D(store, Settings(), source="mt5", symbol="XAUUSD"))
    sc.scan_once()
    sc.pause()
    sc.resume()  # previously: AttributeError 'NoneType' object has no attribute 'copy_rates_from_pos'
    assert sc.paused is False and store.get_meta("paused") == "0"
    assert feed._mt5 is None and not feed._initialized  # nothing was initialised or launched
    # recovery: the terminal appears; the first healthy scan skips the paused period and opens a NEW watermark
    now = datetime.now(UTC)
    fake = FakeMT5(now=now, symbols=("XAUUSD",))
    feed._mt5, feed.require_running_terminal = fake, False
    sc._next_connect = 0
    before = time.time()
    sc.scan_once()
    assert sc.state["feed"]["ok"] and sc.session_watermark is not None
    assert sc.session_watermark.timestamp() >= before - 1
    latest_close = feed.closed_bars("M5", 1)[-1].close_time
    assert store.get_meta("last_m5_close") == latest_close.isoformat().replace("+00:00", "Z")
    assert store.list_signals() == []


def test_api_resume_and_discovery_report_disconnected_clearly(tmp_path):
    c, token, local = make_client(tmp_path, fake=FakeMT5(now=NOW, init_ok=False), symbol="XAUUSDc")
    h = {"X-Session-Token": token}
    with c:
        assert c.post("/api/scanner/pause", headers=h).status_code == 200
        r = c.post("/api/scanner/resume", headers=h)
        assert r.status_code == 200 and r.json()["paused"] is False
        d = c.get("/api/mt5/discover")
        assert d.status_code == 503 and "not connected" in d.json()["detail"].lower()
        assert "initialize failed" in d.json()["detail"]
        assert c.get("/api/mt5/symbols").status_code == 503
