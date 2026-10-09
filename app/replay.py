"""Chronological replay / backtest of CRT-SMC-v1 using the live engine and the same availability rules.

No future bars: at each M5 close the engine only sees bars that have closed. Entries fill at the NEXT
executable observation after the confirmation close (next M5 open with assumed spread + slippage for
OHLC data, or the first Bid/Ask tick at/after the close when tick data is supplied). Results are
SIMULATED price hits, not broker fills, and say nothing about future profitability.

CLI:  python -m app.replay --source csv --m5 path/to/m5.csv [--ticks path/to/ticks.csv]
      python -m app.replay --source mt5 --symbol <EXACT_SYMBOL> --days 60 [--use-ticks]
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from .config import STATE_DIR, StrategyConfig, load_settings, load_strategy
from .engine import Engine, Signal
from .models import UTC, Bar, Quote, SymbolMeta, aggregate, iso, parse_iso
from .outcomes import bar_hit, quote_hit, settle
from .store import MemoryStore
from .strategy import BUY

TickFn = Callable[[datetime, datetime], list[Quote]]


@dataclass
class Costs:
    spread: float
    slippage: float
    source: str  # "ohlc-assumed" or "ticks"

    def describe(self) -> str:
        if self.source == "ticks":
            return f"tick Bid/Ask; entry slippage {self.slippage}, stop slippage {self.slippage} (price units)"
        return (f"OHLC Bid bars; assumed spread {self.spread} and slippage {self.slippage} (price units); "
                "entry no earlier than the next M5 open after confirmation")


@dataclass
class ReplayResult:
    symbol: str
    config_version: str
    data_label: str
    costs: str
    period: dict
    split_at: str
    segments: dict
    signals: list = field(default_factory=list)
    limitations: list = field(default_factory=list)


def _stats(signals: list[Signal], candidates: list) -> dict:
    by_status: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for c in candidates:
        by_status[c.status] = by_status.get(c.status, 0) + 1
        if c.reason:
            reasons[c.reason] = reasons.get(c.reason, 0) + 1
    outcomes: dict[str, int] = {}
    for s in signals:
        outcomes[s.outcome_status] = outcomes.get(s.outcome_status, 0) + 1
    tp, sl = outcomes.get("tp", 0), outcomes.get("sl", 0)
    rs = [s.outcome_r for s in sorted(signals, key=lambda s: s.created_at)
          if s.outcome_status in ("tp", "sl", "expired") and s.outcome_r is not None]
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "candidates": len(candidates), "candidates_by_status": by_status, "reasons": reasons,
        "signals": len(signals), "outcomes": outcomes,
        "win_rate": None if tp + sl == 0 else round(tp / (tp + sl), 4),
        "win_rate_denominator": f"{tp} TP / ({tp} TP + {sl} SL); excludes ambiguous, expired and still-open signals",
        "mean_r": None if not rs else round(statistics.fmean(rs), 4),
        "mean_r_sample": f"{len(rs)} signals with a definite simulated exit (TP, SL or expiry mark)",
        "total_r": round(sum(rs), 4), "max_drawdown_r": round(max_dd, 4),
    }


def replay(m5: list[Bar], meta: SymbolMeta, cfg: StrategyConfig, costs: Costs, *, h1: Optional[list[Bar]] = None,
           ticks_fn: Optional[TickFn] = None, holdout_fraction: float = 0.30, data_label: str = "") -> ReplayResult:
    m5 = sorted(m5, key=lambda b: b.open_time)
    if len(m5) < cfg.structure_lookback_bars + 12:
        raise ValueError("not enough M5 history to replay")
    h1 = sorted(h1 if h1 is not None else aggregate(m5), key=lambda b: b.open_time)
    h1_by_close = {b.close_time: i for i, b in enumerate(h1)}
    m5_open = [b.open_time for b in m5]
    period_end = m5[-1].close_time
    store = MemoryStore()
    eng = Engine(cfg, meta, store, mode="replay")
    fills: dict[str, float] = {}
    last_tick: dict[str, Quote] = {}

    def observed(start: datetime, end: datetime, include_start: bool) -> list[Quote]:
        """Ticks inside [start|(start, end] clipped to the replay period, valid and chronological, whatever the
        callback returns (it may ignore bounds or ordering)."""
        end = min(end, period_end)
        if end < start:
            return []
        out = [q for q in ticks_fn(start, end)
               if (q.time >= start if include_start else q.time > start) and q.time <= end and q.is_valid()]
        return sorted(out, key=lambda q: q.time)

    def entry_fn(c, conf_bar: Bar):
        if ticks_fn is not None:
            window = observed(conf_bar.close_time, conf_bar.close_time + timedelta(seconds=cfg.signal_max_age_seconds), True)
            first = window[0] if window else None
            return first, (first.time if first else conf_bar.close_time + timedelta(seconds=cfg.signal_max_age_seconds + 1))
        j = bisect.bisect_left(m5_open, conf_bar.close_time)
        if j >= len(m5) or m5[j].open_time != conf_bar.close_time:
            return None, conf_bar.close_time  # no contiguous next observation -> not fillable
        nxt = m5[j]
        return Quote(nxt.open_time, nxt.open, round(nxt.open + costs.spread, 6)), nxt.open_time

    def on_signal(sig: Signal):
        fill = sig.entry + costs.slippage if sig.direction == BUY else sig.entry - costs.slippage
        fills[sig.id] = fill
        sig.meta["fill_price"] = round(fill, 6)
        sig.meta["fill_note"] = "simulated fill = observed entry side adjusted by slippage"
        sig.last_checked = sig.quote_time  # outcome observations start strictly after the entry tick/open

    expiry = timedelta(hours=cfg.outcome_expiry_hours)
    for i, bar in enumerate(m5):
        prev = m5[i - 1] if i else None
        if ticks_fn is not None:
            # advance each active position with the replay clock: only ticks up to this bar's close are known now
            for sig in store.active_signals(meta.name):
                _advance_with_ticks(sig, observed, bar.close_time, cfg, costs, fills[sig.id], last_tick)
        else:
            for sig in store.active_signals(meta.name):
                if bar.open_time < sig.quote_time:
                    continue
                fill = fills[sig.id]
                hit = bar_hit(sig, bar, costs.spread)
                if hit == "ambiguous":
                    settle(sig, "ambiguous", bar.close_time, None, "TP and SL inside one M5 bar; excluded from win rate")
                elif hit == "tp":
                    settle(sig, "tp", bar.close_time, sig.tp, "TP touched (limit, no slippage)", entry=fill)
                elif hit == "sl":
                    px = sig.sl - costs.slippage if sig.direction == BUY else sig.sl + costs.slippage
                    settle(sig, "sl", bar.close_time, px, "SL touched (stop slippage applied)", entry=fill)
                elif bar.close_time >= sig.created_at + expiry:
                    px = bar.close - costs.slippage if sig.direction == BUY else bar.close + costs.spread + costs.slippage
                    settle(sig, "expired", bar.close_time, px, f"expired after {cfg.outcome_expiry_hours}h at bar close", entry=fill)
        for sig in eng.on_m5_bar(bar, prev, entry_fn):
            on_signal(sig)
        j = h1_by_close.get(bar.close_time)
        if j:
            lo = bisect.bisect_left(m5_open, h1[j].open_time - cfg.structure_lookback_bars * timedelta(minutes=5))
            eng.evaluate_hour(h1[j - 1], h1[j], m5[lo: i + 1], bar.close_time)

    for sig in store.active_signals(meta.name):
        sig.outcome_status, sig.outcome_note = "open_at_end", "history ended before TP/SL/expiry"

    start, end = m5[0].open_time, m5[-1].close_time
    split = start + (end - start) * (1 - holdout_fraction)
    cands = list(store.candidates.values())
    sigs = sorted(store.signals.values(), key=lambda s: s.created_at)
    segments = {
        "development": _stats([s for s in sigs if s.confirm_close < split], [c for c in cands if c.b_close < split]),
        "holdout": _stats([s for s in sigs if s.confirm_close >= split], [c for c in cands if c.b_close >= split]),
    }
    limitations = [
        "Simulated price hits only; not broker fills and not evidence of future profitability.",
        "Same-bar TP/SL is AMBIGUOUS and excluded from the win rate.",
        "No parameters were optimised; the holdout segment is reported separately and never used for tuning.",
    ]
    if ticks_fn is None:
        limitations.append("OHLC-only history: spread and slippage are assumptions, SELL exits use Bid + assumed spread.")
    else:
        limitations.append("Tick replay: entry is the first valid tick within the freshness window after the confirmation "
                           "close; exits are checked only on observed ticks inside the replay period (gaps between ticks are "
                           "not interpolated); candidate invalidation still uses closed M5 bars.")
    return ReplayResult(symbol=meta.name, config_version=cfg.version, data_label=data_label, costs=costs.describe(),
                        period={"start": iso(start), "end": iso(end), "m5_bars": len(m5), "h1_bars": len(h1)},
                        split_at=iso(split), segments=segments,
                        signals=[_sig_row(s, split) for s in sigs], limitations=limitations)


def _advance_with_ticks(sig: Signal, observed, now: datetime, cfg: StrategyConfig, costs: Costs, fill: float,
                        last_tick: dict) -> None:
    """Process the ticks in (last_checked, now] for one active position. Exits use the actual Bid (BUY) or Ask (SELL)
    of an observed tick at its own timestamp; nothing after `now` (or after the replay period) is ever consulted."""
    expiry_at = sig.created_at + timedelta(hours=cfg.outcome_expiry_hours)
    upto = min(now, expiry_at)
    start = sig.last_checked or sig.quote_time
    for q in observed(start, upto, False) if upto > start else []:
        last_tick[sig.id] = q
        hit = quote_hit(sig, q)
        if hit == "tp":
            settle(sig, "tp", q.time, sig.tp, "TP touched by tick (limit, no slippage)", entry=fill)
            return
        if hit == "sl":
            px = sig.sl - costs.slippage if sig.direction == BUY else sig.sl + costs.slippage
            settle(sig, "sl", q.time, px, "SL touched by tick (stop slippage applied)", entry=fill)
            return
    sig.last_checked = max(start, upto)
    if now >= expiry_at:
        last = last_tick.get(sig.id)
        if last is None:
            settle(sig, "expired", expiry_at, None, "expired with no tick observed after entry; R not marked")
        else:
            px = last.bid if sig.direction == BUY else last.ask
            settle(sig, "expired", expiry_at, px, "expired; marked at the last observed exit-side tick", entry=fill)


def _sig_row(s: Signal, split: datetime) -> dict:
    return {"id": s.id, "segment": "development" if s.confirm_close < split else "holdout", "direction": s.direction,
            "confirm_close": iso(s.confirm_close), "entry_quote": s.entry, "fill": s.meta.get("fill_price"),
            "sl": s.sl, "tp": s.tp, "reward_risk": s.reward_risk, "outcome": s.outcome_status,
            "outcome_r": s.outcome_r, "outcome_time": iso(s.outcome_time), "note": s.outcome_note}


# ------------------------------------------------------------------ data loading (user-supplied history only)
def load_csv_bars(path: Path) -> list[Bar]:
    """CSV columns: time (ISO-8601 UTC bar OPEN time), open, high, low, close."""
    from .models import M5
    out = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Bar(parse_iso(row["time"]), M5, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])))
    return out


def load_csv_ticks(path: Path) -> TickFn:
    """CSV columns: time (ISO-8601 UTC), bid, ask."""
    with path.open(newline="", encoding="utf-8") as fh:
        ticks = sorted((Quote(parse_iso(r["time"]), float(r["bid"]), float(r["ask"])) for r in csv.DictReader(fh)), key=lambda q: q.time)
    times = [q.time for q in ticks]

    def fn(start: datetime, end: datetime) -> list[Quote]:
        return ticks[bisect.bisect_left(times, start): bisect.bisect_right(times, end)]
    return fn


def replay_from_feed(feed, cfg: StrategyConfig, *, days: int, use_ticks: bool, spread: float, slippage: float,
                     holdout_fraction: float, now: Optional[datetime] = None) -> ReplayResult:
    """Replay real history read from an ALREADY CONNECTED feed (e.g. the dashboard's live MT5 feed, which must
    not be shut down). Uses the actual returned bounds/counts; nothing is filled in."""
    if days < 1:
        raise ValueError("days must be positive")
    meta = feed.meta()
    end = (now or datetime.now(UTC))
    start = end - timedelta(days=days)
    m5 = [b for b in feed.bars_range("M5", start, end) if b.close_time <= end]
    h1 = [b for b in feed.bars_range("H1", start, end) if b.close_time <= end]
    if not m5:
        raise ValueError(f"no closed M5 history returned for {meta.name} in the last {days} days")
    ticks_fn = feed.ticks_range if use_ticks else None
    costs = Costs(spread, slippage, "ticks" if ticks_fn else "ohlc-assumed")
    label = (f"MT5 {meta.name} ({getattr(feed, 'mode', 'mt5')}), requested last {days} days; returned {len(m5)} M5 / {len(h1)} H1 bars "
             f"from {iso(m5[0].open_time)} to {iso(m5[-1].close_time)} (read-only)")
    return replay(m5, meta, cfg, costs, h1=h1, ticks_fn=ticks_fn, holdout_fraction=holdout_fraction, data_label=label)


def main(argv: Optional[list[str]] = None, *, feed_factory=None) -> int:
    """`feed_factory` lets tests inject a mock MT5 feed; by default the real read-only MT5Feed is used."""
    ap = argparse.ArgumentParser(description="Replay CRT-SMC-v1 on history (simulated outcomes only).")
    ap.add_argument("--source", choices=["csv", "mt5"], default="mt5",
                    help="mt5 = history from your MT5 terminal; csv = your own exported bars (no fictional source)")
    ap.add_argument("--m5", type=Path, help="CSV of M5 bars (csv source)")
    ap.add_argument("--ticks", type=Path, help="optional CSV of Bid/Ask ticks (csv source)")
    ap.add_argument("--symbol", help="exact MT5 symbol (mt5 source)")
    ap.add_argument("--tick-size", type=float, default=0.01, help="tick size for csv source")
    ap.add_argument("--digits", type=int, default=2)
    ap.add_argument("--days", type=int, default=60, help="history length for mt5 source")
    ap.add_argument("--use-ticks", action="store_true", help="mt5: fetch Bid/Ask ticks around each signal")
    ap.add_argument("--spread", type=float)
    ap.add_argument("--slippage", type=float)
    ap.add_argument("--holdout", type=float)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    settings = load_settings()
    cfg = load_strategy()
    spread = settings.replay_spread_price if args.spread is None else args.spread
    slippage = settings.replay_slippage_price if args.slippage is None else args.slippage
    holdout = settings.holdout_fraction if args.holdout is None else args.holdout
    ticks_fn, h1 = None, None
    if args.source == "csv":
        if not args.m5:
            ap.error("--m5 is required for csv source")
        m5 = load_csv_bars(args.m5)
        meta = SymbolMeta(args.symbol or args.m5.stem, args.tick_size, args.tick_size, args.digits, "csv")
        ticks_fn = load_csv_ticks(args.ticks) if args.ticks else None
        label = f"CSV {args.m5.name}"
    else:
        symbol = args.symbol or settings.symbol
        if not symbol:
            ap.error("set --symbol or GOLD_SYMBOL to the exact broker symbol (use `gold.cmd symbols` to list candidates)")
        if feed_factory is None:
            from .data.mt5 import MT5Feed as feed_factory
        feed = feed_factory(symbol, settings.mt5_terminal_path, settings.mt5_server_utc_offset_hours)
        # The connection must stay open for the whole replay: tick reads are lazy (one call per signal window).
        # shutdown() runs in `finally`, so it also happens on partial initialisation, read errors and replay errors.
        try:
            st = feed.connect()
            if not st.ok:
                print(f"MT5 not available: {st.message}")
                return 2
            result = replay_from_feed(feed, cfg, days=args.days, use_ticks=args.use_ticks, spread=spread,
                                      slippage=slippage, holdout_fraction=holdout)
            label = result.data_label
        finally:
            feed.shutdown()
    if args.source != "mt5":
        costs = Costs(spread, slippage, "ticks" if ticks_fn else "ohlc-assumed")
        result = replay(m5, meta, cfg, costs, h1=h1, ticks_fn=ticks_fn, holdout_fraction=holdout, data_label=label)
    out = args.out or STATE_DIR / "replays" / f"replay-{args.source}-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    if args.out is None:  # an explicit --out (e.g. tests) never replaces the dashboard's "latest" result
        latest = STATE_DIR / "replays" / f"latest-{args.source}.json"
        latest.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    print(f"Replay ({label}) written to {out}")
    for name, seg in result.segments.items():
        print(f"  {name}: candidates={seg['candidates']} signals={seg['signals']} outcomes={seg['outcomes']} "
              f"win_rate={seg['win_rate']} [{seg['win_rate_denominator']}] mean_r={seg['mean_r']} max_dd_r={seg['max_drawdown_r']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
