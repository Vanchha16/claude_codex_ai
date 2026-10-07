"""Pure, in-memory research replay for FVG-Trend-M15-M5-v1 (never touches live state, orders or Telegram).

Same rule functions as the live engine (app/fvg.py). Simulated execution, all on closed OHLC Bid bars:
- A confirmed setup places three limits at the confirmation bar's close; they rest from the next bar.
- BUY limit fills when Ask (= Bid low + spread) <= entry; SELL limit fills when Bid high >= entry. Fill = the limit price
  (no price improvement assumed). Exits: BUY on Bid (TP if high >= tp, SL if low <= sl); SELL on Ask (Bid + spread).
- No intrabar ordering is assumed. In the FILL bar a touched TP may have happened BEFORE the fill -> "ambiguous";
  a touched SL in the fill bar must come after the fill (price crosses the entry first) -> SL. In later bars TP and SL
  in the same bar -> "ambiguous". Ambiguous legs are excluded from the baseline R and counted as -1R (plus slippage) in the
  conservative sensitivity.
- SL exits pay `slippage`; TP is a limit. Unfilled legs expire 2 h after placement; remaining unfilled legs are
  cancelled when a bar closes beyond the zone's far edge. Open positions keep SL/TP until hit (no forced close);
  positions still open at the end are "unresolved".
- Research normalisation: each leg carries an equal 1/3 risk share, so a basket's nominal R = sum(leg R) / 3.
Capacity: one open basket per symbol, >= 30 min between accepted baskets, <= 4 accepted baskets per Bangkok date.
Runner: .venv/Scripts/python.exe -m app.fvg_replay --bars .tmp/fastsweep/bars-m5-20260806T0700-20261005T0655.json
"""
from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .fastsweep import BANGKOK, BUY, M15, bangkok_date
from .fvg import (PROFILES, FvgConfig, FvgSetup, Gap, advance_setup, basket_levels, detect_gap, new_setup, qualify,
                  placement_violation, stop_within_spread)
from .models import M5, UTC, Bar, SymbolMeta, aggregate, iso, parse_iso

COVERED_HOURS = 12.0


@dataclass(frozen=True)
class Costs:
    spread: float = 0.20
    slippage: float = 0.05


@dataclass
class Leg:
    number: int
    percent: float
    entry: float
    tp: float
    state: str = "pending"        # pending | filled | expired | cancelled | unfilled_at_end
    outcome: Optional[str] = None  # tp | sl | ambiguous | unresolved
    fill_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    r: Optional[float] = None
    worst_r: Optional[float] = None  # ambiguous legs: the stop outcome (with slippage), used by the conservative view
    note: str = ""


@dataclass
class Basket:
    id: str
    direction: str
    bottom: float
    top: float
    sl: float
    placed_at: datetime
    pending_expires: datetime
    legs: list = field(default_factory=list)

    def open(self) -> bool:
        return any(l.state == "pending" or (l.state == "filled" and l.outcome is None) for l in self.legs)


def _leg_r(b: Basket, leg: Leg, exit_px: float) -> float:
    risk = abs(leg.entry - b.sl)
    return round(((exit_px - leg.entry) if b.direction == BUY else (leg.entry - exit_px)) / risk, 4)


def _step_basket(b: Basket, bar: Bar, costs: Costs) -> None:
    if bar.open_time < b.placed_at:
        return
    buy = b.direction == BUY
    ask_low, ask_high = bar.low + costs.spread, bar.high + costs.spread
    for leg in b.legs:
        if leg.state == "pending":
            if bar.open_time >= b.pending_expires:
                leg.state, leg.note = "expired", "limit expired unfilled after 2 h"
                continue
            filled = ask_low <= leg.entry if buy else bar.high >= leg.entry
            if not filled:
                continue
            leg.state, leg.fill_time = "filled", bar.close_time
            tp_hit = bar.high >= leg.tp if buy else ask_low <= leg.tp
            sl_hit = bar.low <= b.sl if buy else ask_high >= b.sl
            if tp_hit:  # the TP may have traded before the limit filled (order unknown)
                leg.outcome, leg.exit_time, leg.note = "ambiguous", bar.close_time, "TP touched in the fill bar; order unknown"
                leg.worst_r = _leg_r(b, leg, b.sl - costs.slippage if buy else b.sl + costs.slippage)
            elif sl_hit:  # price crosses the entry before reaching the stop beyond it
                leg.outcome, leg.exit_time = "sl", bar.close_time
                leg.r = _leg_r(b, leg, b.sl - costs.slippage if buy else b.sl + costs.slippage)
            continue
        if leg.state == "filled" and leg.outcome is None:
            tp_hit = bar.high >= leg.tp if buy else ask_low <= leg.tp
            sl_hit = bar.low <= b.sl if buy else ask_high >= b.sl
            if tp_hit and sl_hit:
                leg.outcome, leg.exit_time, leg.note = "ambiguous", bar.close_time, "TP and SL inside one M5 bar"
                leg.worst_r = _leg_r(b, leg, b.sl - costs.slippage if buy else b.sl + costs.slippage)
            elif tp_hit:
                leg.outcome, leg.exit_time, leg.r = "tp", bar.close_time, _leg_r(b, leg, leg.tp)
            elif sl_hit:
                leg.outcome, leg.exit_time = "sl", bar.close_time
                leg.r = _leg_r(b, leg, b.sl - costs.slippage if buy else b.sl + costs.slippage)
    far_break = bar.close < b.bottom if buy else bar.close > b.top
    if far_break:  # zone invalidated: cancel only this basket's remaining unfilled legs
        for leg in b.legs:
            if leg.state == "pending":
                leg.state, leg.note = "cancelled", "zone invalidated (close beyond far edge)"


def replay(m5: list[Bar], meta: SymbolMeta, cfg: FvgConfig, costs: Costs, *, holdout_fraction: float = 0.30) -> dict:
    cfg.validate()
    if costs.spread > cfg.max_spread_price + 1e-12:
        raise ValueError("assumed spread exceeds the 0.50 acceptance limit")
    m5 = sorted(m5, key=lambda b: b.open_time)
    m15 = aggregate(m5, M15)
    by_close = {b.close_time: j for j, b in enumerate(m15)}
    version = cfg.version
    funnel = {"m15_candles": len(m15), "triples": 0, "raw_gaps": 0, "qualified": 0, "retests": 0, "confirmations": 0}
    setups: list[FvgSetup] = []
    live: list[FvgSetup] = []
    baskets: list[Basket] = []
    last_accept: Optional[datetime] = None
    per_day: dict[str, int] = {}

    for bar in m5:
        for b in baskets:
            if b.open():
                _step_basket(b, bar, costs)
        for s in list(live):
            st = advance_setup(s, bar, cfg)
            if st not in ("pending", "retested"):
                live.remove(s)
            if st == "confirmed":
                t = s.confirm_close
                day = bangkok_date(t)
                if any(b.open() for b in baskets):
                    s.status, s.reason = "rejected", "basket_already_open"
                elif last_accept is not None and t - last_accept < timedelta(minutes=cfg.cooldown_minutes):
                    s.status, s.reason = "rejected", "cooldown"
                elif per_day.get(day, 0) >= cfg.max_baskets_per_day:
                    s.status, s.reason = "rejected", "daily_cap"
                else:
                    try:
                        sl, legs = basket_levels(Gap(s.direction, s.bottom, s.top, None, None), meta, cfg)
                    except ValueError as exc:
                        s.status, s.reason = "rejected", f"levels_invalid: {exc}"
                        continue
                    entries = [(l.number, l.entry) for l in legs]
                    if stop_within_spread(sl, entries, costs.spread, cfg, meta.tick_size):
                        s.status, s.reason = "rejected", "stop_within_spread"  # same rule 6a as live (assumed spread)
                        continue
                    if placement_violation(s.direction, entries, bar.close, bar.close + costs.spread, meta.tick_size):
                        s.status, s.reason = "rejected", "limit_on_wrong_side_of_market"  # rule 6b, as the live preflight
                        continue
                    b = Basket(id=f"FVG-{s.direction}-{iso(s.a_open)}", direction=s.direction, bottom=s.bottom, top=s.top,
                               sl=sl, placed_at=t, pending_expires=t + timedelta(minutes=cfg.pending_expiry_minutes),
                               legs=[Leg(l.number, l.percent, l.entry, l.tp) for l in legs])
                    baskets.append(b)
                    s.meta["basket"] = b.id
                    last_accept = t
                    per_day[day] = per_day.get(day, 0) + 1
        j = by_close.get(bar.close_time)
        if j is not None and j >= 2:
            funnel["triples"] += 1
            gap = detect_gap(m15[j - 2], m15[j - 1], m15[j], meta.tick_size)
            if gap is not None:
                funnel["raw_gaps"] += 1
                s = new_setup(gap, cfg, meta.name, version)
                why = qualify(gap, m15[: j + 1], cfg, meta.tick_size)
                if why:
                    s.status, s.reason = "rejected", why
                else:
                    funnel["qualified"] += 1
                    live.append(s)
                setups.append(s)

    for s in live:
        s.status, s.reason = "pending_at_end", "history ended before retest/confirmation"
    for b in baskets:
        for leg in b.legs:
            if leg.state == "pending":
                leg.state = "unfilled_at_end"
            elif leg.state == "filled" and leg.outcome is None:
                leg.outcome, leg.note = "unresolved", "history ended with the position open"
    funnel["retests"] = sum(1 for s in setups if s.retest_close is not None)
    funnel["confirmations"] = sum(1 for s in setups if s.confirm_close is not None)

    start, end = m5[0].open_time, m5[-1].close_time
    split = start + (end - start) * (1 - holdout_fraction)
    return {
        "strategy": version, "config": asdict(cfg), "costs": asdict(costs), "symbol": meta.name,
        "tick_size": meta.tick_size, "digits": meta.digits,
        "period": {"start": iso(start), "end": iso(end), "m5_bars": len(m5), "m15_bars": len(m15),
                   "m5_gaps": sum(1 for a, b in zip(m5, m5[1:]) if b.open_time != a.close_time)},
        "split_at": iso(split), "funnel": funnel,
        "setup_reasons": _count(s.reason or s.status for s in setups),
        "segments": {"earlier": _segment([b for b in baskets if b.placed_at < split]),
                     "later": _segment([b for b in baskets if b.placed_at >= split]),
                     "all": _segment(baskets)},
        "daily": _daily(m5, baskets),
        "baskets": [_basket_row(b) for b in baskets],
    }


def _count(items) -> dict:
    out: dict = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items()))


def _basket_r(b: Basket, conservative: bool) -> Optional[float]:
    total, any_resolved = 0.0, False
    for leg in b.legs:
        if leg.state != "filled":
            continue
        if leg.outcome in ("tp", "sl"):
            total += leg.r
            any_resolved = True
        elif leg.outcome == "ambiguous" and conservative:
            total += leg.worst_r  # worst case: the stop (with stop slippage)
            any_resolved = True
    return round(total / len(b.legs), 4) if any_resolved else (0.0 if all(l.state != "filled" for l in b.legs) else None)


def _segment(baskets: list[Basket]) -> dict:
    legs = [l for b in baskets for l in b.legs]
    states = _count(l.state for l in legs)
    outcomes = _count(l.outcome for l in legs if l.state == "filled")
    filled = [l for l in legs if l.state == "filled"]
    tp, sl = outcomes.get("tp", 0), outcomes.get("sl", 0)
    out = {"baskets": len(baskets), "legs": len(legs), "leg_states": states, "filled_leg_outcomes": outcomes,
           "raw_fill_rate": None if not legs else round(len(filled) / len(legs), 4),
           "leg_win_rate_tp_over_tp_sl": None if tp + sl == 0 else round(tp / (tp + sl), 4),
           "by_depth": {f"{p:g}%": _count((l.state if l.state != "filled" else f"filled:{l.outcome}")
                                         for b in baskets for l in b.legs if l.percent == p)
                        for p in sorted({l.percent for l in legs})}}
    for mode in ("baseline", "conservative"):
        rs = [r for r in (_basket_r(b, mode == "conservative") for b in sorted(baskets, key=lambda x: x.placed_at)) if r is not None]
        eq = peak = dd = 0.0
        for r in rs:
            eq += r
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        out[mode] = {"baskets_with_r": len(rs), "net_basket_r": round(sum(rs), 4),
                     "mean_basket_r": None if not rs else round(statistics.fmean(rs), 4), "max_drawdown_r": round(dd, 4)}
    out["baseline"]["note"] = "ambiguous legs excluded; unresolved legs excluded"
    out["conservative"]["note"] = "ambiguous legs counted as their stop outcome (about -1R incl. slippage); unresolved excluded"
    return out


def _daily(m5: list[Bar], baskets: list[Basket]) -> list[dict]:
    stamps = [m5[0].open_time, m5[-1].open_time] + [b.placed_at for b in baskets]
    days = sorted({bangkok_date(t) for t in stamps})
    d, end = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    rows = {}
    while d <= end:
        rows[d.isoformat()] = {"date": d.isoformat(), "weekday": d.strftime("%a"), "m5_bars": 0, "baskets": 0,
                               "legs_planned": 0, "legs_filled": 0}
        d += timedelta(days=1)
    for b in m5:
        if b.is_valid():
            rows[bangkok_date(b.open_time)]["m5_bars"] += 1
    for b in baskets:
        r = rows[bangkok_date(b.placed_at)]
        r["baskets"] += 1
        r["legs_planned"] += len(b.legs)
        r["legs_filled"] += sum(1 for l in b.legs if l.state == "filled")
    for r in rows.values():
        r["coverage_h"] = round(r["m5_bars"] * 5 / 60, 2)
        r["covered"] = r["coverage_h"] >= COVERED_HOURS
    return list(rows.values())


def frequency(daily: list[dict]) -> dict:
    def stats(rows):
        if not rows:
            return {"dates": 0}
        n = [r["baskets"] for r in rows]
        return {"dates": len(rows), "mean_baskets": round(statistics.fmean(n), 3), "median_baskets": statistics.median(n),
                "max_baskets": max(n), "mean_legs_planned": round(statistics.fmean(r["legs_planned"] for r in rows), 3),
                "mean_legs_filled": round(statistics.fmean(r["legs_filled"] for r in rows), 3),
                "zero_basket_dates": sum(1 for x in n if x == 0),
                "distribution": {str(k): sum(1 for x in n if x == k) for k in range(5)}}
    return {"all_calendar_dates": stats(daily), "dates_with_any_data": stats([r for r in daily if r["m5_bars"]]),
            "covered_dates_ge_12h": stats([r for r in daily if r["covered"]])}


def _basket_row(b: Basket) -> dict:
    return {"id": b.id, "dir": b.direction, "zone": [b.bottom, b.top], "sl": b.sl, "placed_utc": iso(b.placed_at),
            "placed_bkk": b.placed_at.astimezone(BANGKOK).strftime("%Y-%m-%d %H:%M"),
            "baseline_r": _basket_r(b, False), "conservative_r": _basket_r(b, True),
            "legs": [{"n": l.number, "pct": l.percent, "entry": l.entry, "tp": l.tp, "state": l.state, "outcome": l.outcome,
                      "fill": iso(l.fill_time) if l.fill_time else None, "exit": iso(l.exit_time) if l.exit_time else None,
                      "r": l.r, "worst_r": l.worst_r, "note": l.note} for l in b.legs]}


def load_bars(path: Path) -> tuple[list[Bar], SymbolMeta]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    m = raw["meta"]
    return [Bar(parse_iso(b[0]), M5, *b[1:]) for b in raw["bars"]], SymbolMeta(m["symbol"], m["tick_size"], m["tick_size"], m["digits"], "mt5")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="FVG-Trend-M15-M5-v1 research replay (in memory)")
    ap.add_argument("--bars", type=Path, required=True, help="cached M5 bars JSON (from app.fastsweep_replay)")
    ap.add_argument("--spread", type=float, default=0.20)
    ap.add_argument("--slippage", type=float, default=0.05)
    ap.add_argument("--holdout", type=float, default=0.30)
    ap.add_argument("--out", type=Path, default=Path(".tmp/fvg"))
    args = ap.parse_args(argv)
    m5, meta = load_bars(args.bars)
    res = replay(m5, meta, PROFILES["rr2"], Costs(args.spread, args.slippage), holdout_fraction=args.holdout)
    res["frequency"] = frequency(res["daily"])
    res["bars_source"] = str(args.bars)
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"{res['strategy'].split('@')[0]}-spread{args.spread:g}-slip{args.slippage:g}.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    a, f = res["segments"]["all"], res["frequency"]["covered_dates_ge_12h"]
    print(f"{res['strategy']} spread {args.spread} slip {args.slippage}: baskets {a['baskets']} legs {a['legs']} "
          f"states {a['leg_states']} outcomes {a['filled_leg_outcomes']} baseline {a['baseline']['net_basket_r']}R "
          f"conservative {a['conservative']['net_basket_r']}R | covered {f.get('dates')} mean {f.get('mean_baskets')}/day -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
