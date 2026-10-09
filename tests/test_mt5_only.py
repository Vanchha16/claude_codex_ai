"""VC Signal is MT5-only (task 20261008-154913): the fictional demo source, fixture, routes and lessons are gone, and an
explicit "demo" request fails clearly WITHOUT side effects. Broker demo-ACCOUNT policy is unaffected (see
test_fvg_review_fixes.py for the demo-account default vs real/contest explicit consent)."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.active_strategy import ActiveStrategy
from app.config import ConfigError, Settings, load_settings, save_local_settings
from app.web import create_app
from tests.conftest import fixture_factory

ROOT = Path(__file__).resolve().parent.parent


def test_defaults_are_mt5():
    assert Settings().data_mode == "mt5"
    assert load_settings(env={}, env_files=(), local_path=Path("does-not-exist.json")).data_mode == "mt5"
    assert not hasattr(Settings(), "demo_speed")


def test_explicit_demo_is_rejected_from_env_and_from_a_saved_file_without_rewriting_it(tmp_path):
    with pytest.raises(ConfigError, match="MT5-only"):
        load_settings(env={"GOLD_DATA_MODE": "demo"}, env_files=(), local_path=tmp_path / "none.json")
    local = tmp_path / "local_settings.json"
    local.write_text(json.dumps({"data_mode": "demo", "symbol": "XAUUSD"}), encoding="utf-8")
    before = local.read_bytes()
    with pytest.raises(ConfigError, match="MT5-only"):
        load_settings(env={}, env_files=(), local_path=local)
    assert local.read_bytes() == before  # never silently migrated or rewritten
    with pytest.raises(ConfigError, match="MT5-only"):
        save_local_settings({"data_mode": "demo"}, local)
    assert local.read_bytes() == before


def test_setup_save_with_demo_changes_nothing_and_start_refuses_demo(tmp_path):
    local = tmp_path / "local_settings.json"
    save_local_settings({"symbol": "XAUUSD"}, local)
    before = local.read_bytes()
    app = create_app(Settings(port=8000), feed_factory=fixture_factory, state_dir=tmp_path / "state", extra_hosts=("testserver",),
                     local_settings_path=local, active_strategy_loader=lambda: ActiveStrategy("crt"))
    with TestClient(app) as c:
        ws = app.state.ws
        scanner = ws.scanner
        r = c.post("/api/setup", headers={"X-Session-Token": app.state.token}, json={"data_mode": "demo"})
        assert r.status_code == 400 and "MT5-only" in r.json()["detail"]
        assert local.read_bytes() == before
        with pytest.raises(ValueError, match="MT5-only"):
            ws.start("demo")
        assert ws.scanner is scanner and scanner.running and ws.mode == "mt5"  # refused before stopping anything
        assert c.get("/api/outbox").json() == []


def test_replay_cli_has_no_demo_source(tmp_path, capsys):
    from app.replay import main
    with pytest.raises(SystemExit):
        main(["--source", "demo", "--out", str(tmp_path / "x.json")])
    assert not (tmp_path / "x.json").exists()
    assert "invalid choice" in capsys.readouterr().err


def test_production_code_never_imports_test_fixtures_and_the_demo_files_are_gone():
    for path in (ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+tests\b", text, re.M), path
        assert "DemoFeed" not in text and "DEMO_FIXTURE" not in text and "demo_fixture" not in text, path
    for gone in ("app/data/demo.py", "app/demo_fixture.py", "app/scenarios.py", "data/demo/xauusd_demo_m5.json"):
        assert not (ROOT / gone).exists(), gone
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert "/api/demo/restart" not in js and "/api/mode" not in js
    html = (ROOT / "frontend/src/index.template.html").read_text(encoding="utf-8")
    for removed in ("btn-demo-restart", "btn-mode", "g-tab-learn", "g-lesson", 'value="demo"'):
        assert removed not in html, removed
