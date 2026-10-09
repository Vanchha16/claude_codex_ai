from fastapi.testclient import TestClient

from app import APP_ID
from app.config import Settings
from app.active_strategy import ActiveStrategy
from app.web import create_app
from tests.conftest import fixture_factory


def client(tmp_path):
    app = create_app(Settings(port=8000), feed_factory=fixture_factory, state_dir=tmp_path, extra_hosts=("testserver",),
                     local_settings_path=tmp_path / "local_settings.json",  # never the workspace's real settings file
                     active_strategy_loader=lambda: ActiveStrategy("crt"))  # never depend on the workspace selection
    return TestClient(app), app.state.token


def test_health_state_and_dashboard(tmp_path):
    c, token = client(tmp_path)
    with c:
        h = c.get("/api/health").json()
        assert h["app"] == APP_ID and h["mode"] == "mt5"
        s = c.get("/api/state").json()
        assert s["mode"] == "mt5" and s["data_label"] == "MetaTrader 5 terminal data (read-only)" and "demo" not in s
        assert s["telegram"]["enabled"] is False and s["telegram"]["configured"] is False
        assert s["strategy"]["min_reward_risk"] == 1.5 and s["strategy"]["max_spread_price"] == 0.5
        assert "no orders" in s["trading"]
        page = c.get("/")
        assert page.status_code == 200 and token in page.text and "__SESSION_TOKEN__" not in page.text
        assert c.get("/static/app.js").status_code == 200


def test_mutations_require_token_and_same_origin(tmp_path):
    c, token = client(tmp_path)
    with c:
        assert c.post("/api/scanner/pause").status_code == 403
        assert c.post("/api/scanner/pause", headers={"X-Session-Token": "nope"}).status_code == 403
        bad_origin = {"X-Session-Token": token, "Origin": "http://evil.example"}
        assert c.post("/api/scanner/pause", headers=bad_origin).status_code == 403
        r = c.post("/api/scanner/pause", headers={"X-Session-Token": token})
        assert r.status_code == 200 and r.json()["paused"] is True
        r = c.post("/api/scanner/resume", headers={"X-Session-Token": token})
        assert r.json()["paused"] is False


def test_foreign_host_header_rejected(tmp_path):
    c, _ = client(tmp_path)
    with c:
        assert c.get("/api/health", headers={"Host": "attacker.example:8000"}).status_code == 403


def test_telegram_cannot_be_enabled_unconfigured(tmp_path):
    c, token = client(tmp_path)
    with c:
        r = c.post("/api/telegram/enabled", headers={"X-Session-Token": token}, json={"enabled": True})
        assert r.status_code == 400
        assert c.post("/api/telegram/test", headers={"X-Session-Token": token}).status_code == 400


def test_demo_switch_restart_and_lesson_routes_are_gone_and_change_nothing(tmp_path):
    c, token = client(tmp_path)
    with c:
        ws = c.app.state.ws
        before = (ws.mode, ws.settings.data_mode, (tmp_path / "local_settings.json").exists())
        hdr = {"X-Session-Token": token}
        for method, path, body in (("post", "/api/mode", {"mode": "demo", "confirm": True}),
                                   ("post", "/api/demo/restart", None), ("get", "/api/fvg/guide/lessons", None)):
            r = getattr(c, method)(path, headers=hdr, **({"json": body} if body is not None else {}))
            assert r.status_code in (404, 405), (path, r.status_code)
        assert c.post("/api/replay/run", headers=hdr, json={"source": "demo"}).status_code == 400
        assert c.get("/api/replay?source=demo").status_code == 400
        r = c.post("/api/setup", headers=hdr, json={"data_mode": "demo"})
        assert r.status_code == 400 and "MT5-only" in r.json()["detail"]
        assert (ws.mode, ws.settings.data_mode, (tmp_path / "local_settings.json").exists()) == before
        assert c.get("/api/outbox").json() == []


def test_fixture_feed_produces_signal_and_chart(tmp_path):
    c, token = client(tmp_path)
    with c:
        sc = c.app.state.ws.scanner
        sc.stop()  # the test drives the TEST fixture clock itself (the app has no simulated clock any more)
        sigs = []
        for _ in range(2000):
            sc.feed.advance(5)
            sc.scan_once()
            sigs = c.get("/api/signals").json()
            if sigs:
                break
        assert sigs, "the fixture should confirm its first fictional BUY"
        s = sigs[0]
        chart = c.get(f"/api/chart?signal_id={s['id']}").json()
        assert chart["candidate"]["level"] is not None and chart["signal"]["id"] == s["id"]
        bars = c.get(f"/api/market/bars?tf=M5&count=200&before={chart['window']['end']}").json()
        assert bars["available"] and bars["bars"] and bars["forming"] is None
        msg = c.get(f"/api/signals/{s['id']}/message").json()["text"]
        d = 2  # the test fixture symbol has 2 digits
        assert msg == f"📍 Entry: {s['entry']:.{d}f}\n🎯 TP: {s['tp']:.{d}f}\n🛑 SL: {s['sl']:.{d}f}\n⚖️ RR: {s['reward_risk']:.2f}"
        assert c.get("/api/outbox").json() == []  # delivery off: nothing queued
