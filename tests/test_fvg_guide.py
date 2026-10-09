"""FVG Guide (read-only presentation of real records): evidence states, the real motivating case, preview vs actual, API safety."""
from datetime import datetime, timedelta

import pytest

from app.fastsweep import BUY, M15, SELL
from app.fvg import PROFILES, Gap, advance_setup, basket_levels, new_setup
from app.fvg_guide import record_view
from app.models import M5, UTC, Bar, SymbolMeta
from tests.conftest import fixture_factory

CFG = PROFILES["rr2"]
META = SymbolMeta("XAUUSD", 0.01, 0.01, 2, "test")
DAY = datetime(2026, 10, 7, tzinfo=UTC)


def at(h, m):
    return DAY.replace(hour=h, minute=m)


def real_case(third_close=4090.2, upto=None):
    """The motivating SELL case: zone 4089.01-4119.18 from C's close 12:45Z, retest closing 13:00Z (low 4079.74),
    then closes 4089.47 and 4088.58 and a third candle that does not close below 4079.74."""
    a = Bar(at(12, 0), M15, 4125, 4130, 4119.18, 4122)
    c = Bar(at(12, 30), M15, 4095, 4096, 4085, 4089)
    s = new_setup(Gap(SELL, 4089.01, 4119.18, a, c), CFG, "XAUUSD", CFG.version)
    m5 = [Bar(at(12, 45), M5, 4071.76, 4078.04, 4068.34, 4074.34), Bar(at(12, 50), M5, 4074.40, 4084.22, 4066.30, 4080.73),
          Bar(at(12, 55), M5, 4080.73, 4089.09, 4079.74, 4087.36), Bar(at(13, 0), M5, 4087.40, 4094.83, 4086.58, 4089.47),
          Bar(at(13, 5), M5, 4089.50, 4091.93, 4086.92, 4088.58), Bar(at(13, 10), M5, 4088.58, 4092.0, min(4086.5, third_close), third_close)]
    m5 = m5[:upto] if upto else m5
    for b in m5:
        advance_setup(s, b, CFG)
    return s, m5


def test_real_sell_case_explains_retest_level_three_closes_and_expiry():
    s, m5 = real_case()
    assert s.status == "expired" and s.reason == "no_confirmation_after_retest" and s.level == 4079.74
    v = record_view(s, None, m5, CFG, META, at(13, 20))
    states = {x["key"]: x["state"] for x in v["steps"]}
    assert states == {"detected": "done", "qualified": "done", "retest": "done", "confirmation": "failed",
                      "eligibility": "unavailable", "pending": "unavailable", "fills": "unavailable"}
    win = v["window"]
    assert [w["role"] for w in win] == ["retest", "window-1", "window-2", "window-3"]
    assert win[0]["l"] == 4079.74 and "cannot confirm itself" in win[0]["verdict"]
    assert [w["c"] for w in win[1:3]] == [4089.47, 4088.58] and not any(w["beyond"] for w in win[1:])
    assert "none of the 3 M5 candles" in v["next"] and v["record"]["reason_text"].startswith("none of the 3")
    labels = [d["label"] for d in v["deadlines"]]
    assert labels[0].startswith("Setup lifetime") and labels[1].startswith("Confirmation window")
    assert v["levels"]["source"] == "preview" and all("volume" not in l for l in v["levels"]["legs"])


def test_mid_window_shows_the_exact_next_requirement_and_forming_candle():
    s, m5 = real_case(upto=5)  # retest + 2 later closes seen; one chance left
    assert s.status == "retested" and s.bars_after_retest == 2
    forming = m5 + [Bar(at(13, 10), M5, 4088.58, 4090.0, 4080.0, 4081.0)]
    v = record_view(s, None, forming, CFG, META, at(13, 12))
    conf = next(x for x in v["steps"] if x["key"] == "confirmation")
    assert conf["state"] == "waiting" and "1 of 3 chances left" in conf["detail"]
    assert "strictly below 4079.74" in v["next"] and "1 of 3 opportunities remain" in v["next"]
    assert v["window"][-1]["verdict"].startswith("forming") and v["window"][-1]["closed"] is False


def test_preview_levels_match_the_engine_and_actual_basket_levels_carry_lots():
    s, m5 = real_case()
    v = record_view(s, None, m5, CFG, META, at(13, 20))
    sl, legs = basket_levels(Gap(SELL, 4089.01, 4119.18, None, None), META, CFG)
    assert v["levels"]["sl"] == sl and [l["entry"] for l in v["levels"]["legs"]] == [l.entry for l in legs]
    assert sl > 4119.18 and all(l["tp"] < l["entry"] for l in v["levels"]["legs"])  # SELL geometry
    basket = {"id": "FVG-x", "status": "orders_pending", "placed_at": "2026-10-07T13:00:01+00:00", "sl": sl,
              "pending_expires": "2026-10-07T15:00:01+00:00",
              "legs": [{"n": l.number, "pct": l.percent, "entry": l.entry, "tp": l.tp, "sl": sl, "rr": 2.0} for l in legs],
              "execution": {"state": "submitted", "account_currency": "USD",
                            "legs": [{"volume": 0.01 * (i + 1), "planned_loss": 3.0, "state": "pending"} for i in range(3)]}}
    s.confirm_close = at(13, 5)
    vb = record_view(s, basket, m5, CFG, META, at(13, 20))
    assert vb["levels"]["source"] == "basket" and [l["volume"] for l in vb["levels"]["legs"]] == [0.01, 0.02, 0.03]
    states = {x["key"]: x["state"] for x in vb["steps"]}
    assert states["pending"] == "done" and states["fills"] == "waiting"
    off = dict(basket, status="alert_only", execution={"state": "not_submitted", "reason": "automatic execution OFF"})
    assert {x["key"]: x["state"] for x in record_view(s, off, m5, CFG, META, at(13, 20))["steps"]}["pending"] == "skipped"


# ------------------------------------------------------------------ API: read-only
def test_guide_endpoints_are_read_only(tmp_path):
    from fastapi.testclient import TestClient
    from app.active_strategy import parse_active_strategy
    from app.config import Settings
    from app.web import create_app
    app = create_app(Settings(port=8000), feed_factory=fixture_factory, state_dir=tmp_path, extra_hosts=("testserver",),
                     active_strategy_loader=lambda: parse_active_strategy({"strategy": "fvg", "profile": "rr2"}))
    with TestClient(app) as c:
        ws = app.state.ws

        def forbidden(*a, **k):
            raise AssertionError("the guide must never reach execution or maintenance")
        ws._fvg_executor, ws._fvg_maintenance = forbidden, forbidden
        empty = c.get("/api/fvg/guide").json()
        assert empty["fvg_active"] is True and empty["records"] == [] and empty["selected"] is None
        ws.scanner.stop()  # the demo scanner would keep adding fixture setups; only the GETs may run from here
        s, _ = real_case()
        ws.fvg_store.add_setup(s, "XAUUSD", CFG.version)
        before = (len(ws.fvg_store.list_setups(100)), len(ws.fvg_store.baskets(limit=100)))
        d = c.get("/api/fvg/guide").json()
        recs = d["records"]
        active = [r for r in recs if r["status"] in ("pending", "retested")]
        assert d["selected"]["record"]["key"] == (active[0]["key"] if active else recs[0]["key"])  # default selection rule
        picked = c.get("/api/fvg/guide", params={"key": s.key}).json()["selected"]
        assert picked["record"]["key"] == s.key and picked["record"]["status"] == "expired"
        assert picked["record"]["level"] == 4079.74 and picked["next"].startswith("Finished")
        assert c.get("/api/fvg/guide/lessons").status_code == 404  # fictional lessons were removed
        after = (len(ws.fvg_store.list_setups(100)), len(ws.fvg_store.baskets(limit=100)))
        assert before == after
        assert ws.fvg_store.get_setup(s.key).status == "expired"


# ------------------------------------------------------------------ Codex review observations (truthful partial states)
from app.fvg import FvgSetup  # noqa: E402
from app.fvg_guide import steps, window_candles  # noqa: E402


def _confirmed_rec():
    t = at(12, 0)
    s = FvgSetup(key="XAUUSD|2026-10-07T11:15:00+00:00|" + CFG.version, direction=BUY, bottom=100, top=102,
                 a_open=t - timedelta(minutes=45), c_close=t, expires=t + timedelta(hours=2), status="confirmed",
                 retest_close=t + M5, level=103, bars_after_retest=1, confirm_close=t + 2 * M5)
    return s, record_view(s, None, [], CFG, META, t + 4 * M5)["record"]


def _pf(rec, exs, legs):
    b = {"id": "probe", "status": "orders_pending", "execution": {"state": exs, "legs": [{"state": x} for x in legs]}}
    return {x["key"]: x for x in steps(rec, b, CFG) if x["key"] in ("pending", "fills")}


@pytest.mark.parametrize("exs,legs", [("needs_reconciliation", ["unknown", "not_sent", "not_sent"]),
                                      ("submitting", ["sending", "not_sent", "not_sent"])])
def test_unresolved_legs_are_never_reported_as_no_fill(exs, legs):
    _, rec = _confirmed_rec()
    r = _pf(rec, exs, legs)
    assert r["pending"]["state"] == "waiting" and "0 of 3" in r["pending"]["detail"]
    assert r["fills"]["state"] == "waiting" and "cannot be ruled out" in r["fills"]["detail"]
    assert "No leg filled" not in r["fills"]["detail"]


def test_known_fill_stays_visible_next_to_an_unresolved_leg():
    _, rec = _confirmed_rec()
    r = _pf(rec, "needs_reconciliation", ["filled_open", "unknown", "not_sent"])
    assert r["pending"]["state"] == "waiting" and "1 of 3" in r["pending"]["detail"]
    assert r["fills"]["state"] == "done" and "1 filled_open" in r["fills"]["detail"] and "unresolved" in r["fills"]["detail"]


def test_partial_submission_is_not_three_accepted_limits():
    _, rec = _confirmed_rec()
    r = _pf(rec, "partial", ["pending", "rejected", "not_sent"])
    assert r["pending"]["state"] == "partial" and "Only 1 of 3" in r["pending"]["detail"]
    assert _pf(rec, "submitted", ["pending"] * 3)["pending"]["state"] == "done"


def test_missing_m5_candle_ends_the_window_instead_of_shifting_a_later_candle_into_it():
    s, _ = _confirmed_rec()
    t = at(12, 0)
    s.status, s.reason, s.confirm_close = "invalidated", "m5_continuity_lost", None
    gapped = [Bar(t, M5, 104, 105, 101, 102), Bar(t + 2 * M5, M5, 102, 105, 102, 104)]  # the 12:05 candle is missing
    win = record_view(s, None, gapped, CFG, META, t + 4 * M5)["window"]
    assert [w["role"] for w in win] == ["retest", "window-1"]
    assert win[1]["missing"] and not win[1]["beyond"] and "continuity" in win[1]["verdict"]
    assert not any(w.get("beyond") for w in win)


def test_window_stops_at_the_stored_confirmation():
    s, m5 = real_case()
    rec = record_view(s, None, m5, CFG, META, at(13, 20))["record"]
    rec = dict(rec, status="confirmed", reason=None, confirm_close=iso_(at(13, 5)))  # chance 1 (13:00-13:05) confirmed
    beyond = [Bar(at(13, 0), M5, 4089.0, 4089.5, 4070.0, 4075.0), Bar(at(13, 5), M5, 4075, 4076, 4060, 4061)]
    win = window_candles(rec, m5[:3] + beyond, CFG, at(13, 20))
    assert [w["role"] for w in win] == ["retest", "window-1"] and win[1]["beyond"]  # chance 2 is never drawn


def test_beyond_close_without_stored_confirmation_is_only_a_comparison():
    s, m5 = real_case()
    alt = m5[:3] + [Bar(at(13, 0), M5, 4087.4, 4090.0, 4070.0, 4075.0)]
    win = window_candles(record_view(s, None, m5, CFG, META, at(13, 20))["record"], alt, CFG, at(13, 20))
    assert not win[1]["beyond"] and "comparison only" in win[1]["verdict"]


def test_formation_roles_follow_timestamps_when_a_candle_is_missing():
    s, _ = real_case()
    b_and_c = [Bar(s.a_open + timedelta(minutes=15) + i * M5, M5, 4104, 4105, 4101, 4102) for i in range(6)]
    v = record_view(s, None, b_and_c, CFG, META, at(13, 20))
    assert [b["role"] for b in v["m15"]] == ["B", "C"] and v["m15_missing"] == ["A"] and "A" in v["data_note"]


def test_preview_is_unavailable_without_real_metadata_or_for_an_older_rule_version():
    s, m5 = real_case()
    v = record_view(s, None, m5, CFG, None, at(13, 20))
    assert "error" in v["levels"] and "legs" not in v["levels"]
    s.key = s.key.rsplit("|", 1)[0] + "|older-version"
    v = record_view(s, None, m5, CFG, META, at(13, 20))
    assert v["record"]["current_version"] is False and "older rule version" in v["levels"]["error"]


def iso_(d):
    return d.isoformat()


def test_the_third_later_candle_can_still_confirm():
    s, m5 = real_case(third_close=4079.0)  # strictly below the SELL level 4079.74 on the last permitted candle
    assert s.status == "confirmed" and s.confirm_close == at(13, 15)
    v = record_view(s, None, m5, CFG, META, at(13, 20))
    assert [w["beyond"] for w in v["window"][1:]] == [False, False, True]
    assert {x["key"]: x["state"] for x in v["steps"]}["confirmation"] == "done"
    s2, m52 = real_case(third_close=4079.74)  # equal on the third candle: expiry, not confirmation
    assert s2.status == "expired" and "equal is not beyond" in record_view(s2, None, m52, CFG, META, at(13, 20))["window"][-1]["verdict"]
