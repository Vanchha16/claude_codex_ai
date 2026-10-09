"""Read-only FVG Guide: explains how a recorded setup moved (or did not move) from the M15 gap to confirmation, the
three pending limits and their fills - from real stored MT5 records only (no fictional lessons or sample data).

Everything here is derived from stored records and the SAME rule functions the engine and replay use (app/fvg.py
`advance_setup`/`basket_levels`). This module never writes a
store, never creates or changes setups/baskets and never calls a broker, so a GET can never alter trading.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .fastsweep import BUY, M15
from .fvg import FvgConfig, FvgSetup, Gap, advance_setup, basket_levels
from .models import M5, Bar, SymbolMeta, aggregate, iso

QUALIFY_REASONS = {"history_not_ending_at_c", "trend_warmup", "trend_flat", "trend_against", "atr_warmup",
                   "gap_too_small", "weak_displacement"}
ELIGIBILITY_REASONS = ("confirmation_before_session_watermark", "setup_expired_at_decision", "confirmation_in_future",
                       "confirmation_too_old", "basket_already_open", "cooldown", "daily_cap", "levels_invalid",
                       "no_quote_for_eligibility_check", "stop_within_spread", "limit_on_wrong_side_of_market",
                       "duplicate_basket")
REASON_TEXT = {
    "history_not_ending_at_c": "the M15 history did not end exactly at candle C",
    "trend_warmup": "not enough contiguous M15 candles yet for the EMA20/EMA50 trend (50 needed after any break)",
    "trend_flat": "EMA20 equals EMA50: no trend direction",
    "trend_against": "the gap points against the EMA20/EMA50 trend",
    "atr_warmup": "not enough candles for ATR14",
    "gap_too_small": "the gap is smaller than max(2 ticks, 0.10 x ATR14)",
    "weak_displacement": "candle B's body is smaller than 1.0 x ATR14 (no strong displacement)",
    "m5_continuity_lost": "an M5 candle was missing or invalid, so the setup could not be followed safely",
    "setup_lifetime_elapsed": "the 2-hour setup lifetime ended before a confirmation",
    "close_beyond_far_edge": "an M5 candle closed beyond the zone's far edge (invalidation wins)",
    "no_confirmation_after_retest": "none of the 3 M5 candles after the retest closed beyond the retest level",
    "confirmation_before_session_watermark": "it confirmed before this live session started, so it is history only",
    "setup_expired_at_decision": "the setup had already expired when the decision was made",
    "confirmation_in_future": "the confirmation time was in the future at decision time",
    "confirmation_too_old": "the confirmation was older than 30 seconds when the decision was made",
    "basket_already_open": "another basket was still open on this account",
    "cooldown": "less than 30 minutes since the previous accepted basket",
    "daily_cap": "4 baskets were already accepted on this Bangkok date",
    "levels_invalid": "the zone was too narrow for three distinct entry prices",
    "no_quote_for_eligibility_check": "no live quote was available for the spread/placement check",
    "stop_within_spread": "a stop would sit inside the spread (needs spread + 1 tick)",
    "limit_on_wrong_side_of_market": "a limit price was already on the wrong side of the market",
    "duplicate_basket": "a basket for this setup already existed",
    "c_before_session_watermark": "candle C closed before this live session started (history/catch-up: never ordered)",
    "decision_too_old": "candle C was more than 30 seconds old when the decision was made (never ordered late)",
    "c_close_in_future": "candle C's close time was in the future at decision time",
    "engine_basket_open": "this engine already had an open or unresolved basket (one per engine)",
    "concurrent_risk_cap": "the open baskets' planned risk would exceed one budget per engine",
    "retired_strategy_switch_to_dual": "a legacy v1 setup closed out when the dual engines were activated",
}
DUAL_QUALIFY_REASONS = QUALIFY_REASONS
DUAL_ELIGIBILITY_REASONS = {"c_before_session_watermark", "decision_too_old", "c_close_in_future", "engine_basket_open",
                            "cooldown", "daily_cap", "concurrent_risk_cap", "levels_invalid", "stop_within_spread",
                            "limit_on_wrong_side_of_market", "no_quote_for_eligibility_check", "duplicate_basket"}


def explain(reason: Optional[str]) -> Optional[str]:
    if not reason:
        return None
    key = reason.split(" ", 1)[0].split(":", 1)[0]
    text = REASON_TEXT.get(key)
    return f"{text} ({reason})" if text and reason != key else (text or reason)


def config_view(cfg: FvgConfig) -> dict:
    return {"version": cfg.version, "ema_fast": cfg.ema_fast, "ema_slow": cfg.ema_slow,
            "trend_min_candles": cfg.trend_min_candles, "atr_period": cfg.atr_period, "gap_atr": cfg.gap_atr,
            "displacement_atr": cfg.displacement_atr, "min_gap_ticks": cfg.min_gap_ticks,
            "entry_depths": list(cfg.entry_depths), "setup_minutes": cfg.setup_minutes, "confirm_bars": cfg.confirm_bars,
            "sl_buffer_ticks": cfg.sl_buffer_ticks, "reward_risk": cfg.reward_risk,
            "max_confirmation_age_seconds": cfg.max_confirmation_age_seconds,
            "stop_spread_margin_ticks": cfg.stop_spread_margin_ticks, "max_spread_price": cfg.max_spread_price,
            "cooldown_minutes": cfg.cooldown_minutes, "max_baskets_per_day": cfg.max_baskets_per_day,
            "pending_expiry_minutes": cfg.pending_expiry_minutes}


def is_dual_record(s: FvgSetup) -> bool:
    return (s.meta or {}).get("mode") == "dual"


def record_dict(s: FvgSetup, current_version) -> dict:
    """current_version: one version string or a collection of the currently active versions."""
    version = s.key.rsplit("|", 1)[-1] if "|" in s.key else None
    current = {current_version} if isinstance(current_version, str) else set(current_version or ())
    dual = is_dual_record(s)
    return {"key": s.key, "direction": s.direction, "bottom": s.bottom, "top": s.top, "a_open": iso(s.a_open),
            "c_close": iso(s.c_close), "expires": iso(s.expires), "status": s.status, "reason": s.reason,
            "reason_text": explain(s.reason), "retest_close": iso(s.retest_close), "level": s.level,
            "bars_after_retest": s.bars_after_retest, "confirm_close": iso(s.confirm_close),
            "next_open": iso(s.next_open), "basket": (s.meta or {}).get("basket"), "version": version,
            "current_version": version in current, "engine": (s.meta or {}).get("engine") if dual else None,
            "rule_set": "dual" if dual else "legacy_v1",
            "rule_label": (f"{(s.meta or {}).get('engine')} engine (immediate limits on qualification)" if dual else
                           "Legacy v1 (M15 gap, then M5 retest and confirmation)")}


def preview_levels(direction: str, bottom: float, top: float, meta: SymbolMeta, cfg: FvgConfig) -> dict:
    """The three entries, common SL and per-leg 1:2 TPs from the engine's own basket_levels (exact tick rounding)."""
    try:
        sl, legs = basket_levels(Gap(direction, bottom, top, None, None), meta, cfg)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"sl": sl, "legs": [{"n": l.number, "pct": l.percent, "entry": l.entry, "tp": l.tp,
                                "rr": round(abs(l.tp - l.entry) / abs(l.entry - sl), 2),
                                "stop_distance": round(abs(l.entry - sl), 6)} for l in legs]}


def _bar(b: Bar, now: datetime, role: Optional[str] = None) -> dict:
    return {"t": int(b.open_time.timestamp()), "tf": "M15" if b.tf == M15 else "M5", "o": b.open, "h": b.high,
            "l": b.low, "c": b.close, "closed": b.close_time <= now, "role": role}


def window_candles(rec: dict, m5: list[Bar], cfg: FvgConfig, now: datetime) -> list[dict]:
    """The retest candle and the confirmation SLOTS after it. Slot i is the M5 candle opening exactly i-1 candles after
    the retest closed; each is replayed through the engine's own `advance_setup`, so a missing/invalid candle, the setup
    lifetime, invalidation or an earlier confirmation ends the window exactly as it ended for the engine. A candle is
    only marked as THE confirmation when the stored record confirmed on that same close."""
    if not rec.get("retest_close") or not m5:
        return []
    retest_close = datetime.fromisoformat(rec["retest_close"])
    by_open = {b.open_time: b for b in m5}
    out = []
    rb = by_open.get(retest_close - M5)
    out.append({**_bar(rb, now, "retest"), "n": 0, "verdict": "retest (cannot confirm itself)"} if rb else
               {"t": int((retest_close - M5).timestamp()), "tf": "M5", "role": "retest", "n": 0, "missing": True,
                "closed": True, "verdict": "retest candle not in the returned history"})
    sim = FvgSetup(key="guide", direction=rec["direction"], bottom=rec["bottom"], top=rec["top"], a_open=retest_close,
                   c_close=retest_close, expires=datetime.fromisoformat(rec["expires"]), status="retested",
                   next_open=retest_close, retest_close=retest_close, level=rec["level"])
    stored_confirm = datetime.fromisoformat(rec["confirm_close"]) if rec.get("confirm_close") else None
    processed = rec.get("bars_after_retest") or 0
    level = rec["level"]
    for i in range(1, cfg.confirm_bars + 1):
        if sim.status != "retested":
            break
        t_open = retest_close + (i - 1) * M5
        b = by_open.get(t_open)
        base = {"role": f"window-{i}", "n": i, "beyond": False}
        if b is None:
            if t_open + M5 > now:
                break  # not formed yet
            text = ("missing - the expected M5 candle is absent, so continuity was lost (setup invalidated)"
                    if rec.get("reason") == "m5_continuity_lost" else
                    "missing - this candle is not in the returned history, so this slot cannot be shown")
            out.append({**base, "t": int(t_open.timestamp()), "tf": "M5", "closed": True, "missing": True, "verdict": text})
            break
        row = {**_bar(b, now, base["role"]), **base}
        if b.close_time > now:
            out.append({**row, "verdict": "forming - only the CLOSE counts"})
            break
        st = advance_setup(sim, b, cfg)
        if st == "confirmed":
            if stored_confirm == b.close_time:
                row.update(verdict="closed beyond the level - confirms", beyond=True)
            elif rec["status"] == "retested" and processed < i:
                row["verdict"] = "closed beyond the level - the engine records the confirmation on its next scan"
            else:
                row["verdict"] = ("close comparison only: beyond the level in this history, but the stored record "
                                  "did not confirm on this candle")
        elif st == "invalidated":
            row["verdict"] = ("closed beyond the far edge - invalidates" if sim.reason == "close_beyond_far_edge" else
                              "invalid candle - continuity lost (setup invalidated)")
        elif st == "expired" and sim.reason == "setup_lifetime_elapsed":
            row["verdict"] = "closed after the 2-hour setup lifetime - not counted"
        elif b.close == level:
            row["verdict"] = "closed exactly at the level - equal is not beyond"
        else:
            row["verdict"] = "did not close beyond the level"
        out.append(row)
    return out


def _leg_summary(legs: list) -> dict:
    counts: dict = {}
    for l in legs:
        counts[l.get("state")] = counts.get(l.get("state"), 0) + 1
    return counts


# per-leg evidence groups (states written by app/fvg_execution.py)
ACCEPTED_LEG = {"pending", "filled_open", "partially_filled", "filled", "closed_tp", "closed_sl", "closed_other",
                "cancelled", "expired"}
FILLED_LEG = {"filled_open", "partially_filled", "filled", "closed_tp", "closed_sl", "closed_other"}
UNCERTAIN_LEG = {"unknown", "sending", "prepared"}
NOT_ACCEPTED_LEG = {"rejected", "not_sent"}


def _counts_text(counts: dict) -> str:
    return ", ".join(f"{n} {s}" for s, n in counts.items())


def steps(rec: dict, basket: Optional[dict], cfg: FvgConfig) -> list[dict]:
    """Progress path with evidence-based states: done | partial | waiting | failed | skipped | unavailable."""
    st, reason = rec["status"], rec.get("reason") or ""
    key = reason.split(" ", 1)[0].split(":", 1)[0]
    qual_failed = st == "rejected" and key in QUALIFY_REASONS
    side = "above" if rec["direction"] == BUY else "below"
    out = [{"key": "detected", "title": "M15 FVG detected", "state": "done",
            "detail": f"{rec['direction']} zone {rec['bottom']} - {rec['top']} formed when candle C closed at {rec['c_close']}."}]
    out.append({"key": "qualified", "title": "Qualified", "state": "failed" if qual_failed else "done",
                "detail": explain(reason) if qual_failed else
                "Trend, minimum gap size and candle-B displacement all passed."})
    if qual_failed:
        retest = ("unavailable", "Never watched: the gap did not qualify.")
    elif rec.get("retest_close"):
        retest = ("done", f"First later M5 candle touching the zone closed at {rec['retest_close']}; its "
                          f"{'high' if rec['direction'] == BUY else 'low'} froze the level {rec['level']}.")
    elif st == "pending":
        retest = ("waiting", "Waiting for a later closed M5 candle to trade into the zone.")
    elif st in ("invalidated", "expired"):
        retest = ("failed", explain(reason) or st)
    else:
        retest = ("unavailable", "No retest recorded.")
    out.append({"key": "retest", "title": "M5 retest", "state": retest[0], "detail": retest[1]})
    if rec.get("confirm_close"):
        conf = ("done", f"A different later M5 candle closed {side} {rec['level']} at {rec['confirm_close']}.")
    elif st == "retested":
        left = cfg.confirm_bars - (rec.get("bars_after_retest") or 0)
        conf = ("waiting", f"Needs a later M5 CLOSE strictly {side} {rec['level']}; {left} of {cfg.confirm_bars} chances left.")
    elif rec.get("retest_close") and st in ("expired", "invalidated"):
        conf = ("failed", explain(reason) or st)
    else:
        conf = ("unavailable", "Only possible after a retest.")
    out.append({"key": "confirmation", "title": "M5 confirmation", "state": conf[0], "detail": conf[1]})
    if not rec.get("confirm_close"):
        elig = ("unavailable", "Runs only after a confirmation (it has not run for this setup).")
    elif basket:
        elig = ("done", f"Accepted: basket {basket.get('id')} at {basket.get('placed_at')}.")
    elif st == "rejected":
        elig = ("failed", explain(reason) or reason)
    else:
        elig = ("waiting", "Being evaluated.")
    out.append({"key": "eligibility", "title": "Signal eligibility", "state": elig[0], "detail": elig[1]})
    return out + execution_steps(basket)


def execution_steps(basket: Optional[dict]) -> list[dict]:
    """'Three pending limits' and 'Fills and outcome' from per-leg evidence (shared by legacy and dual records)."""
    out = []
    ex = (basket or {}).get("execution") or {}
    exs = ex.get("state")
    if not basket:
        pend = ("unavailable", "No basket: the entry ladder below is a PREVIEW of the levels, not orders.")
    elif exs in ("not_submitted", "disabled") or basket.get("status") in ("alert_only", "expired_unsubmitted", "zone_invalidated"):
        pend = ("skipped", f"Automatic execution was not used ({ex.get('reason') or basket.get('status')}): "
                           "plan and Telegram alert only, no broker orders.")
    elif exs == "illustration":
        pend = ("done", "FICTIONAL lesson: three limit orders would now rest at the broker.")
    else:
        pend = None
    legs = ex.get("legs") or []
    counts = _leg_summary(legs)
    n_acc = sum(n for st_, n in counts.items() if st_ in ACCEPTED_LEG)
    n_unc = sum(n for st_, n in counts.items() if st_ in UNCERTAIN_LEG or st_ not in ACCEPTED_LEG | NOT_ACCEPTED_LEG)
    n_fill = sum(n for st_, n in counts.items() if st_ in FILLED_LEG)
    total = len(legs) or 3
    if pend is None:
        if not legs:
            pend = (("waiting", f"Outcome uncertain ({exs}); being reconciled with the broker, never resent.")
                    if exs in ("submitting", "needs_reconciliation") else
                    ("failed", ex.get("reason") or exs or "not submitted"))
        elif n_acc == total:
            pend = ("done", f"The broker accepted all {total} pending limits (legs: {_counts_text(counts)}).")
        elif n_unc:
            pend = ("waiting", f"{n_acc} of {total} limits accepted so far; {n_unc} unresolved and being reconciled "
                               f"with the broker, never resent (legs: {_counts_text(counts)}).")
        elif n_acc:
            pend = ("partial", f"Only {n_acc} of {total} limits were accepted; the rest were refused or not sent "
                              f"(legs: {_counts_text(counts)}).")
        else:
            pend = ("failed", f"No limit was accepted (legs: {_counts_text(counts)}). {ex.get('reason') or ''}".strip())
    out.append({"key": "pending", "title": "Three pending limits", "state": pend[0], "detail": pend[1]})
    if not basket or not legs or pend[0] in ("skipped", "unavailable") or (pend[0] == "failed" and not n_acc and not n_unc):
        fills = ("unavailable", "No broker orders, so no fills.")
    elif n_fill:
        extra = f" {n_unc} leg(s) still unresolved, so more fills may exist." if n_unc else ""
        fills = ("done", f"Fills so far: {_counts_text(counts)}.{extra}")
    elif n_unc:
        fills = ("waiting", f"Fill status unresolved: {n_unc} leg(s) are being reconciled with the broker, so a fill "
                            f"cannot be ruled out (legs: {_counts_text(counts)}).")
    elif counts.get("pending"):
        fills = ("waiting", "Waiting for price to return to the limit prices; confirmation alone is NOT an entry.")
    else:
        fills = ("failed", "No leg filled: " + _counts_text(counts))
    out.append({"key": "fills", "title": "Fills and outcome", "state": fills[0], "detail": fills[1]})
    return out


def next_requirement(rec: dict, basket: Optional[dict], cfg: FvgConfig) -> str:
    st, buy = rec["status"], rec["direction"] == BUY
    if st == "pending":
        return (f"A later closed M5 candle must trade into the zone {rec['bottom']} - {rec['top']} (the retest). "
                f"A close {'below ' + str(rec['bottom']) if buy else 'above ' + str(rec['top'])} invalidates. "
                f"Setup lifetime ends {rec['expires']}.")
    if st == "retested":
        left = cfg.confirm_bars - (rec.get("bars_after_retest") or 0)
        deadline = datetime.fromisoformat(rec["retest_close"]) + cfg.confirm_bars * M5
        return (f"A later closed M5 candle must CLOSE strictly {'above' if buy else 'below'} {rec['level']} "
                f"(a wick is not enough; equal is not beyond). {left} of {cfg.confirm_bars} opportunities remain; "
                f"the confirmation window ends {iso(deadline)}.")
    if basket:
        ex = basket.get("execution") or {}
        if any(l.get("state") == "pending" for l in ex.get("legs") or []):
            return f"The limit orders wait for price to return to them; unfilled legs expire {basket.get('pending_expires')}."
        return f"Basket {basket.get('id')}: {basket.get('status')}."
    if st == "confirmed":
        return "Confirmed: the eligibility checks run next."
    return f"Finished: {explain(rec.get('reason')) or st}."


def deadlines(rec: dict, basket: Optional[dict], cfg: FvgConfig) -> list[dict]:
    out = [{"label": "Setup lifetime (2 h from candle C)", "at": rec["expires"]}]
    if rec.get("retest_close"):
        out.append({"label": f"Confirmation window ({cfg.confirm_bars} M5 candles after the retest)",
                    "at": iso(datetime.fromisoformat(rec["retest_close"]) + cfg.confirm_bars * M5)})
    if basket and basket.get("pending_expires"):
        out.append({"label": "Pending-order lifetime (2 h from placement)", "at": basket["pending_expires"]})
    return out


def record_view(s: FvgSetup, basket: Optional[dict], m5: list[Bar], cfg: FvgConfig, meta: Optional[SymbolMeta],
                now: datetime) -> dict:
    """Full read-only explanation of one stored setup. `m5` are closed/forming M5 bars around it (may be empty).
    `meta` is the broker's real tick size/digits; None when unreadable, then no exact-looking preview is invented."""
    rec = record_dict(s, cfg.version)
    m5 = sorted(m5, key=lambda b: b.open_time)
    by_open = {b.open_time: b for b in aggregate([b for b in m5 if b.close_time <= now], M15)}
    abc, missing = [], []
    for i, role in enumerate("ABC"):  # each role from its expected timestamp, never from list position
        b = by_open.get(s.a_open + i * M15)
        if b is not None:
            abc.append({**_bar(b, now), "role": role})
        else:
            missing.append(role)
    after = [_bar(b, now) for b in m5 if b.open_time >= s.c_close]
    if basket:
        ex = basket.get("execution") or {}
        planned = ex.get("legs") or []
        levels = {"source": "basket", "sl": basket.get("sl"), "account_currency": ex.get("account_currency"),
                  "legs": [{**l, "volume": (planned[i] if i < len(planned) else {}).get("volume"),
                            "planned_loss": (planned[i] if i < len(planned) else {}).get("planned_loss"),
                            "state": (planned[i] if i < len(planned) else {}).get("state")}
                           for i, l in enumerate(basket.get("legs") or [])]}
    elif not rec["current_version"]:
        levels = {"source": "preview", "error": "recorded under an older rule version (" + str(rec["version"]) + "); the "
                  "current rules' levels would not be what was stored, so no preview is shown"}
    elif meta is None:
        levels = {"source": "preview", "error": "the broker's tick size and price digits are not readable right now "
                  "(feed offline), so exact preview levels cannot be computed"}
    else:
        levels = {"source": "preview", **preview_levels(s.direction, s.bottom, s.top, meta, cfg)}
    notes = []
    if not m5:
        notes.append("candles unavailable (feed offline or history not returned)")
    elif missing:
        notes.append(f"formation candle(s) {', '.join(missing)} not in the returned history")
    return {"record": rec, "steps": steps(rec, basket, cfg), "next": next_requirement(rec, basket, cfg),
            "deadlines": deadlines(rec, basket, cfg), "window": window_candles(rec, m5, cfg, now), "m15": abc,
            "m15_missing": missing, "m5": after, "levels": levels, "data_note": "; ".join(notes) or None,
            "basket": {k: basket.get(k) for k in ("id", "status", "placed_at", "pending_expires", "sl")} if basket else None}


# ====================================================================== dual engines (task 20261008-143801)
def dual_steps(rec: dict, basket: Optional[dict]) -> list[dict]:
    """CLOSED A/B/C on the engine's own timeframe -> qualification -> eligibility/preflight -> three pending limits ->
    later fills. There is no retest or confirmation stage for these records."""
    eng = rec.get("engine") or "?"
    st, reason = rec["status"], rec.get("reason") or ""
    key = reason.split(" ", 1)[0].split(":", 1)[0]
    qual_failed = st == "rejected" and key in QUALIFY_REASONS
    out = [{"key": "detected", "title": f"{eng} FVG detected", "state": "done",
            "detail": f"{rec['direction']} zone {rec['bottom']} - {rec['top']} from three adjacent CLOSED {eng} candles; "
                      f"available when candle C closed at {rec['c_close']}."},
           {"key": "qualified", "title": f"Qualified on {eng} candles", "state": "failed" if qual_failed else "done",
            "detail": explain(reason) if qual_failed else
            f"Trend, minimum gap size and candle-B displacement passed on the {eng} engine's own history."}]
    if qual_failed:
        elig = ("unavailable", "Not reached: the gap did not qualify, so no order decision was made.")
    elif basket:
        elig = ("done", f"Accepted at {basket.get('placed_at')} (C was at most 30 s old; engine slot, cooldown, daily "
                        f"total, spread and placement checks passed): basket {basket.get('id')}.")
    elif st == "rejected":
        elig = ("failed", explain(reason) or reason)
    else:
        elig = ("waiting", "Qualified: the eligibility and preflight checks run now.")
    out.append({"key": "eligibility", "title": "Eligibility and preflight", "state": elig[0], "detail": elig[1]})
    return out + execution_steps(basket)


def dual_next(rec: dict, basket: Optional[dict]) -> str:
    if basket:
        ex = basket.get("execution") or {}
        if any(l.get("state") == "pending" for l in ex.get("legs") or []):
            return (f"The three limits rest at the broker and wait for price to come back to them (a limit is not a "
                    f"market fill); unfilled legs expire {basket.get('pending_expires')}.")
        return f"Basket {basket.get('id')}: {basket.get('status')}."
    if rec["status"] == "qualified":
        return "Qualified: the order decision is being made now."
    return f"Finished: {explain(rec.get('reason')) or rec['status']}."


def dual_record_view(s: FvgSetup, basket: Optional[dict], m5: list[Bar], cfg: FvgConfig, meta: Optional[SymbolMeta],
                     now: datetime, current_versions) -> dict:
    from .fvg_dual import TF, engine_bars
    rec = record_dict(s, current_versions)
    eng = rec["engine"]
    m5 = sorted(m5, key=lambda b: b.open_time)
    closed = [b for b in m5 if b.close_time <= now]
    by_open = {b.open_time: b for b in engine_bars(closed, eng)}
    abc, missing = [], []
    for i, role in enumerate("ABC"):  # roles from expected timestamps on the engine's own timeframe
        b = by_open.get(s.a_open + i * TF[eng])
        if b is not None:
            abc.append({**_bar(b, now), "role": role})
        else:
            missing.append(role)
    after = [_bar(b, now) for b in m5 if b.open_time >= s.c_close]
    if basket:
        ex = basket.get("execution") or {}
        planned = ex.get("legs") or []
        levels = {"source": "basket", "sl": basket.get("sl"), "account_currency": ex.get("account_currency"),
                  "legs": [{**l, "volume": (planned[i] if i < len(planned) else {}).get("volume"),
                            "planned_loss": (planned[i] if i < len(planned) else {}).get("planned_loss"),
                            "state": (planned[i] if i < len(planned) else {}).get("state")}
                           for i, l in enumerate(basket.get("legs") or [])]}
    elif not rec["current_version"]:
        levels = {"source": "preview", "error": f"recorded under another rule version ({rec['version']}); no preview"}
    elif meta is None:
        levels = {"source": "preview", "error": "the broker's tick size and price digits are not readable right now "
                  "(feed offline), so exact preview levels cannot be computed"}
    else:
        levels = {"source": "preview", **preview_levels(s.direction, s.bottom, s.top, meta, cfg)}
    notes = []
    if not m5:
        notes.append("candles unavailable (feed offline or history not returned)")
    elif missing:
        notes.append(f"formation candle(s) {', '.join(missing)} not in the returned history")
    dl = [{"label": "Decision window (C close + 30 s)",
           "at": iso(s.c_close + timedelta(seconds=cfg.max_confirmation_age_seconds))}]
    if basket and basket.get("pending_expires"):
        dl.append({"label": "Pending-order lifetime (2 h from placement)", "at": basket["pending_expires"]})
    return {"record": rec, "steps": dual_steps(rec, basket), "next": dual_next(rec, basket), "deadlines": dl, "window": [],
            "m15": abc, "abc_tf": eng, "m15_missing": missing, "m5": after, "levels": levels,
            "data_note": "; ".join(notes) or None,
            "basket": {k: basket.get(k) for k in ("id", "status", "placed_at", "pending_expires", "sl", "engine")}
            if basket else None}
