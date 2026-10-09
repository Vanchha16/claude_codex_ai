"""Exact FVG Guide links (task 20261009-083335): an explicit key is resolved directly from storage, never substituted;
its basket is found through the stored setup relationship, not a recency window. Isolated store, test feed only."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.active_strategy import parse_active_strategy
from app.config import Settings
from app.fvg import FvgSetup
from app.fvg_dual import DUAL_PROFILE
from app.web import create_app
from tests.fixture_feed import OfflineFeed

D = DUAL_PROFILE
T = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)


def setup(i, engine, minutes, status="rejected", reason="trend_warmup"):
    version = D.engine_version(engine)
    close = T + timedelta(minutes=minutes)
    step = 15 if engine == "M15" else 5
    return FvgSetup(key=f"XAUUSD|probe-{i}|{version}", direction="BUY", bottom=100, top=102,
                    a_open=close - timedelta(minutes=3 * step), c_close=close, expires=close + timedelta(seconds=30),
                    status=status, reason=reason, meta={"engine": engine, "mode": "dual"})


def basket(bid, setup_key, minutes, engine="M5"):
    placed = T + timedelta(minutes=minutes)
    return {"id": bid, "plan_id": bid.split("-", 1)[1], "setup_key": setup_key, "symbol": "XAUUSD", "engine": engine,
            "version": D.engine_version(engine), "direction": "BUY", "bottom": 100, "top": 102, "sl": 99.98,
            "placed_at": placed.isoformat(), "pending_expires": (placed + timedelta(hours=2)).isoformat(), "accepted": True,
            "status": "alert_only", "legs": [], "execution": {"state": "not_submitted"}, "account_id": None}


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(port=8000), feed_factory=lambda _: OfflineFeed(), state_dir=tmp_path,
                     local_settings_path=tmp_path / "local.json", extra_hosts=("testserver",),
                     active_strategy_loader=lambda: parse_active_strategy({"strategy": "fvg", "profile": "dual"}))
    with TestClient(app) as c:
        app.state.ws.scanner.stop()
        yield c, app.state.ws


def counts(ws):
    return len(ws.fvg_store.list_setups(100000)), len(ws.fvg_store.baskets(limit=100000))


def test_explicit_old_m15_key_and_its_old_basket_resolve_exactly(client):
    c, ws = client
    old = setup(0, "M15", 0, status="accepted", reason=None)
    old.meta["basket"] = "FVG15-old"
    ws.fvg_store.add_setup(old, "XAUUSD", D.engine_version("M15"))
    ws.fvg_store.add_basket(basket("FVG15-old", old.key, 1, engine="M15"))
    for i in range(1, 32):  # 31 newer M5 setups push the M15 setup out of the default 30-record window
        s = setup(i, "M5", 5 * i)
        ws.fvg_store.add_setup(s, "XAUUSD", D.engine_version("M5"))
    for k in range(510):  # 510 newer baskets push the M15 basket out of any 500-basket window
        ws.fvg_store.add_basket(basket(f"FVG5-n{k}", f"XAUUSD|other-{k}|x", 200 + k))
    before = counts(ws)
    d = c.get("/api/fvg/guide", params={"key": old.key}).json()
    sel = d["selected"]
    assert sel["record"]["key"] == old.key and sel["record"]["engine"] == "M15"
    assert sel["basket"]["id"] == "FVG15-old"
    keys = [r["key"] for r in d["records"]]
    assert keys.count(old.key) == 1 and "missing_key" not in d
    default = c.get("/api/fvg/guide").json()  # no key: ordinary default selection is unchanged (newest)
    assert default["selected"]["record"]["key"] == "XAUUSD|probe-31|" + D.engine_version("M5")
    assert old.key not in [r["key"] for r in default["records"]]  # the bounded window itself is unchanged
    assert counts(ws) == before  # read-only


def test_unknown_explicit_key_is_reported_missing_never_substituted(client):
    c, ws = client
    unknown = "XAUUSD|does-not-exist|" + D.engine_version("M15")
    empty = c.get("/api/fvg/guide", params={"key": unknown}).json()
    assert empty["selected"] is None and empty["missing_key"] == unknown and empty["records"] == []
    for i in range(3):
        ws.fvg_store.add_setup(setup(i, "M5", 5 * i), "XAUUSD", D.engine_version("M5"))
    before = counts(ws)
    d = c.get("/api/fvg/guide", params={"key": unknown}).json()
    assert d["selected"] is None and d["missing_key"] == unknown and "not found" in d["message"]
    assert len(d["records"]) == 3  # the selector still lists real records to choose from
    assert counts(ws) == before
