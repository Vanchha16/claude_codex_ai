"""Pure, in-memory replay for FastSweep-M15-M5-v1 (research only; never writes live state, signals or the outbox).

Frequency controls (predeclared): at most one active simulated signal per symbol; no duplicate setup per A/B/profile;
>= 30 minutes between newly created signals; at most 4 new signals per Asia/Bangkok calendar date (a cap, not a
quota). Rejected/invalidated candidates never count toward the cap. Deterministic order inside each M5 bar:
(1) entries due at the bar open (oldest setup first), checked against controls as of that open; (2) outcomes of
active signals on the bar; (3) pending confirmations with the closed bar; (4) a new A/B pair if the bar closes an M15
candle. Outcomes reuse app.outcomes (BUY exits on Bid, SELL on Ask = Bid + spread; TP+SL inside one bar = AMBIGUOUS;
TP is a limit, SL and expiry marks pay slippage). Expiry after 2 h is marked at the last observed bar close at or
before the expiry time - never a later quote.

Runner (reads real candles only through the running app's GET /api/market/bars; no MT5 session of its own):
    .venv/Scripts/python.exe -m app.fastsweep_replay --start 2026-08-06T07:00:00Z --end 2026-10-05T06:55:00Z
"""
from __future__ import annotations

import argparse
import json
import statistics
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .engine import Signal
from .fastsweep import (BANGKOK, BUY, M15, PROFILES, FastSweepConfig, Setup, bangkok_date, build_levels,
                        confirm_step, evaluate_range, new_setup, trend_permits)
from .models import M5, UTC, Bar, Quote, SymbolMeta, aggregate, iso, parse_iso
from .outcomes import bar_hit, settle

COVERED_HOURS = 12.0  # predeclared: a Bangkok date is "reasonably covered" with >= 12 h of valid M5 data


@dataclass(frozen=True)
class Costs:
    spread: float = 0.20
    slippage: float = 0.05


def replay(m5: list[Bar], meta: SymbolMeta, cfg: FastSweepConfig, costs: Costs, *,
           holdout_fraction: float = 0.30) -> dict:
    cfg.validate()
    if costs.spread > cfg.max_spread_price + 1e-12:
        raise ValueError("assumed spread exceeds the 0.50 acceptance limit")
    m5 = sorted(m5, key=lambda b: b.open_time)
    if not m5:
        raise ValueError("no M5 bars")
    m15 = aggregate(m5, M15)
    m15_by_close = {b.close_time: j for j, b in enumerate(m15)}
    run_start = []  # index of the first candle of the contiguous M15 run containing j
    for j, b in enumerate(m15):
        run_start.append(run_start[j - 1] if j and m15[j - 1].close_time == b.open_time else j)

    funnel = {"m15_candles": len(m15), "pairs": 0, "no_sweep": 0}
    candidates: list[Setup] = []
    pending: list[Setup] = []
    awaiting: list[Setup] = []
    signals: list[Signal] = []
    active: list[Signal] = []
    last_bar: dict[str, tuple[datetime, float]] = {}
    daily_count: dict[str, int] = {}
    last_created: Optional[datetime] = None
    keys: set[str] = set()
    expiry = timedelta(hours=cfg.outcome_expiry_hours)

    def reject(s: Setup, reason: str) -> None:
        s.status, s.reason = "rejected", reason

    def expire_mark(sig: Signal, at: datetime, close: Optional[float], note: str) -> None:
        if close is None:
            sig.outcome_status, sig.outcome_time, sig.outcome_note = "expired", at, note + "; no observation, R not marked"
            return
        px = close - costs.slippage if sig.direction == BUY else close + costs.spread + costs.slippage
        settle(sig, "expired", at, px, note, entry=sig.meta["fill"])

    for bar in m5:
        t = bar.open_time
        # (1) entries at this bar's open (the first executable observation after the confirmation close)
        for s in sorted(awaiting, key=lambda x: x.b_close):
            if t != s.confirm_close:
                reject(s, "no_quote")          # no contiguous next M5 observation
                continue
            day = bangkok_date(t)
            if active:
                reject(s, "active_signal")
            elif last_created is not None and t - last_created < timedelta(minutes=cfg.cooldown_minutes):
                reject(s, "cooldown")
            elif daily_count.get(day, 0) >= cfg.max_signals_per_day:
                reject(s, "daily_cap")
            else:
                q = Quote(t, bar.open, round(bar.open + costs.spread, 6))
                lv, why = build_levels(s, q, t, meta, cfg)
                if lv is None:
                    reject(s, why)
                    continue
                fill = lv.entry + costs.slippage if s.direction == BUY else lv.entry - costs.slippage
                sig = Signal(id=f"FS-{s.direction}-{iso(s.a_open)}", candidate_key=s.key, symbol=meta.name, mode="replay",
                             direction=s.direction, entry=lv.entry, sl=lv.sl, tp=lv.tp,
                             reward_risk=round(lv.reward_risk, 4), spread=round(q.spread, 6), bid=q.bid, ask=q.ask,
                             quote_time=t, confirm_close=s.confirm_close, created_at=t, valid_until=t + timedelta(seconds=120),
                             config_version=cfg.version, explanation="FastSweep M15 sweep-and-return + M5 break of B",
                             meta={"fill": round(fill, 6), "risk": round(lv.risk, 6), "a_open": iso(s.a_open),
                                   "b_high": s.b_high, "b_low": s.b_low})
                s.status = "signal"
                signals.append(sig)
                active.append(sig)
                daily_count[day] = daily_count.get(day, 0) + 1
                last_created = t
        awaiting = []

        # (2) outcomes of active signals on this bar
        for sig in list(active):
            exp_at = sig.created_at + expiry
            seen = last_bar.get(sig.id)
            if t >= exp_at:  # a gap crossed the expiry: mark at the last observation at/before it, never this bar
                expire_mark(sig, seen[0] if seen else exp_at, seen[1] if seen else None,
                            f"expired after {cfg.outcome_expiry_hours:g}h (data gap); marked at last observed close")
                active.remove(sig)
                continue
            hit = bar_hit(sig, bar, costs.spread)
            fill = sig.meta["fill"]
            if hit == "ambiguous":
                settle(sig, "ambiguous", bar.close_time, None, "TP and SL inside one M5 bar; excluded from win rate")
            elif hit == "tp":
                settle(sig, "tp", bar.close_time, sig.tp, "TP touched (limit, no slippage)", entry=fill)
            elif hit == "sl":
                px = sig.sl - costs.slippage if sig.direction == BUY else sig.sl + costs.slippage
                settle(sig, "sl", bar.close_time, px, "SL touched (stop slippage applied)", entry=fill)
            elif bar.close_time >= exp_at:
                expire_mark(sig, bar.close_time, bar.close, f"expired after {cfg.outcome_expiry_hours:g}h at bar close")
            last_bar[sig.id] = (bar.close_time, bar.close)
            if sig.outcome_status != "active":
                active.remove(sig)

        # (3) pending confirmations with this closed bar
        for s in list(pending):
            st = confirm_step(s, bar, cfg)
            if st != "pending":
                pending.remove(s)
                if st == "confirmed":
                    awaiting.append(s)

        # (4) new A/B pair when this bar closes an M15 candle
        j = m15_by_close.get(bar.close_time)
        if j:
            a, b = m15[j - 1], m15[j]
            funnel["pairs"] += 1
            rc = evaluate_range(a, b, meta.tick_size, cfg)
            if rc.reason == "no_sweep":
                funnel["no_sweep"] += 1
                continue
            direction = rc.direction
            s = new_setup(a, b, direction or "NONE", meta.name)
            s.meta["trend"] = None
            if rc.direction is None:
                reject(s, rc.reason)
            else:
                trend, why = trend_permits(m15[run_start[j]: j + 1], cfg)
                s.meta["trend"] = why
                if trend is None:
                    reject(s, why)
                elif trend != direction:
                    reject(s, "trend_against")
            if s.key in keys:
                reject(s, "duplicate_setup")
            keys.add(s.key)
            candidates.append(s)
            if s.status == "pending":
                pending.append(s)

    for s in pending:
        s.status, s.reason = "pending_at_end", "history ended inside the confirmation window"
    for s in awaiting:
        reject(s, "no_quote")
    for sig in active:
        sig.outcome_status, sig.outcome_note = "open_at_end", "history ended before TP/SL/expiry"

    start, end = m5[0].open_time, m5[-1].close_time
    split = start + (end - start) * (1 - holdout_fraction)
    return {
        "strategy": cfg.version, "config": asdict(cfg), "costs": asdict(costs), "symbol": meta.name,
        "tick_size": meta.tick_size, "digits": meta.digits,
        "period": {"start": iso(start), "end": iso(end), "m5_bars": len(m5), "m15_bars": len(m15)},
        "split_at": iso(split), "funnel": funnel,
        "segments": {"earlier": _segment([s for s in signals if s.confirm_close < split], [c for c in candidates if c.b_close < split]),
                     "later": _segment([s for s in signals if s.confirm_close >= split], [c for c in candidates if c.b_close >= split]),
                     "all": _segment(signals, candidates)},
        "daily": _daily(m5, candidates, signals),
        "signals": [_sig_row(s) for s in signals],
        "candidates": [_cand_row(c) for c in candidates],
    }


def _segment(signals: list[Signal], candidates: list[Setup]) -> dict:
    by_status: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for c in candidates:
        by_status[c.status] = by_status.get(c.status, 0) + 1
        if c.reason:
            reasons[c.reason] = reasons.get(c.reason, 0) + 1
    confirmed = sum(1 for c in candidates if c.confirm_close is not None)
    outcomes: dict[str, int] = {}
    for s in signals:
        outcomes[s.outcome_status] = outcomes.get(s.outcome_status, 0) + 1
    rs = [s.outcome_r for s in sorted(signals, key=lambda s: s.created_at)
          if s.outcome_status in ("tp", "sl", "expired") and s.outcome_r is not None]
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    tp, sl = outcomes.get("tp", 0), outcomes.get("sl", 0)
    quoted = [s.reward_risk for s in signals]
    return {"candidates": len(candidates), "candidates_by_status": by_status, "reasons": dict(sorted(reasons.items())),
            "confirmations": confirmed, "signals": len(signals), "outcomes": outcomes,
            "win_rate_tp_over_tp_sl": None if tp + sl == 0 else round(tp / (tp + sl), 4),
            "r_sample": len(rs), "total_r": round(sum(rs), 4), "mean_r": None if not rs else round(statistics.fmean(rs), 4),
            "max_drawdown_r": round(dd, 4),
            "quoted_rr_mean": None if not quoted else round(statistics.fmean(quoted), 4)}


def _daily(m5: list[Bar], candidates: list[Setup], signals: list[Signal]) -> list[dict]:
    # The table spans every Bangkok date touched by a bar OPEN or a candidate/confirmation/signal time: a period
    # ending exactly at Bangkok midnight assigns its last B close (and anything confirmed then) to the next date.
    stamps = [m5[0].open_time, m5[-1].open_time] + [c.b_close for c in candidates] +              [c.confirm_close for c in candidates if c.confirm_close is not None] + [s.created_at for s in signals]
    days = sorted({bangkok_date(t) for t in stamps})
    d, end = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    rows = {}
    while d <= end:
        rows[d.isoformat()] = {"date": d.isoformat(), "weekday": d.strftime("%a"), "m5_bars": 0, "coverage_h": 0.0,
                               "candidates": 0, "confirmations": 0, "signals": 0}
        d += timedelta(days=1)
    for b in m5:
        if b.is_valid():
            rows[bangkok_date(b.open_time)]["m5_bars"] += 1
    for c in candidates:
        rows[bangkok_date(c.b_close)]["candidates"] += 1
        if c.confirm_close is not None:
            rows[bangkok_date(c.confirm_close)]["confirmations"] += 1
    for s in signals:
        rows[bangkok_date(s.created_at)]["signals"] += 1
    for r in rows.values():
        r["coverage_h"] = round(r["m5_bars"] * 5 / 60, 2)
        r["covered"] = r["coverage_h"] >= COVERED_HOURS
    return list(rows.values())


def frequency(daily: list[dict]) -> dict:
    def stats(rows: list[dict]) -> dict:
        n = [r["signals"] for r in rows]
        if not n:
            return {"dates": 0}
        dist = {str(k): sum(1 for x in n if x == k) for k in range(0, 5)}
        return {"dates": len(n), "mean": round(statistics.fmean(n), 3), "median": statistics.median(n),
                "min": min(n), "max": max(n), "distribution": dist,
                "pct_distribution": {k: round(100 * v / len(n), 1) for k, v in dist.items()},
                "pct_at_least_3": round(100 * sum(1 for x in n if x >= 3) / len(n), 1),
                "pct_3_to_4": round(100 * sum(1 for x in n if 3 <= x <= 4) / len(n), 1)}
    return {"all_calendar_dates": stats(daily),
            "dates_with_any_data": stats([r for r in daily if r["m5_bars"] > 0]),
            "covered_dates_ge_12h": stats([r for r in daily if r["covered"]]),
            "partial_dates": [r["date"] for r in daily if 0 < r["m5_bars"] and not r["covered"]],
            "no_data_dates": [r["date"] for r in daily if r["m5_bars"] == 0]}


def _cand_row(c: Setup) -> dict:
    return {"key": c.key, "dir": c.direction, "a_open": iso(c.a_open), "b_close": iso(c.b_close),
            "b_close_bkk": c.b_close.astimezone(BANGKOK).strftime("%Y-%m-%d %H:%M"), "a_low": c.a_low, "a_high": c.a_high,
            "b_low": c.b_low, "b_high": c.b_high, "b_close_price": c.b_close_price, "status": c.status, "reason": c.reason,
            "trend": c.meta.get("trend"), "confirm_close": iso(c.confirm_close) if c.confirm_close else None}


def _sig_row(s: Signal) -> dict:
    return {"id": s.id, "dir": s.direction, "created_utc": iso(s.created_at),
            "created_bkk": s.created_at.astimezone(BANGKOK).strftime("%Y-%m-%d %H:%M"), "entry": s.entry, "sl": s.sl,
            "tp": s.tp, "quoted_rr": s.reward_risk, "fill": s.meta["fill"], "outcome": s.outcome_status,
            "outcome_time": iso(s.outcome_time) if s.outcome_time else None, "outcome_price": s.outcome_price,
            "r": s.outcome_r, "note": s.outcome_note}


# ---------------------------------------------------------------- runner (read-only GET /api/market/bars)
def fetch_m5(api: str, start: datetime, end: datetime) -> tuple[list[Bar], dict]:
    bars: dict[int, dict] = {}
    meta: dict = {}
    before = end
    while True:
        q = urllib.parse.urlencode({"tf": "M5", "count": 1000, "before": before.strftime("%Y-%m-%dT%H:%M:%SZ")})
        with urllib.request.urlopen(f"{api}/api/market/bars?{q}", timeout=60) as r:
            d = json.load(r)
        meta = meta or {"symbol": d.get("symbol"), "digits": d.get("digits"), "tick_size": d.get("tick_size")}
        for b in d.get("bars", []):
            if b["time"] >= start.timestamp():
                bars[b["time"]] = b
        if not d.get("bars") or d["bars"][0]["time"] <= start.timestamp():
            break
        before = datetime.fromtimestamp(d["bars"][0]["time"], UTC)
    out = []
    for ts in sorted(bars):
        b = bars[ts]
        o = datetime.fromtimestamp(ts, UTC)
        if o + M5 <= end:
            out.append(Bar(o, M5, b["open"], b["high"], b["low"], b["close"]))
    return out, meta


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="FastSweep-M15-M5-v1 replay (research only)")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--profiles", default="rr1,rr2")
    ap.add_argument("--spread", type=float, default=0.20)
    ap.add_argument("--slippage", type=float, default=0.05)
    ap.add_argument("--holdout", type=float, default=0.30)
    ap.add_argument("--out", type=Path, default=Path(".tmp/fastsweep"))
    args = ap.parse_args(argv)
    start, end = parse_iso(args.start), parse_iso(args.end)
    args.out.mkdir(parents=True, exist_ok=True)
    cache = args.out / f"bars-m5-{start:%Y%m%dT%H%M}-{end:%Y%m%dT%H%M}.json"
    if cache.exists():  # identical inputs for every profile and cost run
        raw = json.loads(cache.read_text(encoding="utf-8"))
        meta_d, m5 = raw["meta"], [Bar(parse_iso(b[0]), M5, *b[1:]) for b in raw["bars"]]
    else:
        m5, meta_d = fetch_m5(args.api.rstrip("/"), start, end)
        cache.write_text(json.dumps({"meta": meta_d, "bars": [[iso(b.open_time), b.open, b.high, b.low, b.close] for b in m5]}),
                         encoding="utf-8")
    meta = SymbolMeta(meta_d["symbol"], meta_d["tick_size"], meta_d["tick_size"], meta_d["digits"], "mt5")
    costs = Costs(args.spread, args.slippage)
    for name in args.profiles.split(","):
        res = replay(m5, meta, PROFILES[name.strip()], costs, holdout_fraction=args.holdout)
        res["frequency"] = frequency(res["daily"])
        out = args.out / f"{res['strategy']}-spread{costs.spread:g}-slip{costs.slippage:g}.json"
        out.write_text(json.dumps(res, indent=1), encoding="utf-8")
        f, a = res["frequency"]["covered_dates_ge_12h"], res["segments"]["all"]
        print(f"{res['strategy']} spread {costs.spread} slip {costs.slippage}: signals {a['signals']} "
              f"outcomes {a['outcomes']} total R {a['total_r']} | covered dates {f.get('dates')} mean {f.get('mean')}/day "
              f">=3: {f.get('pct_at_least_3')}% -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
