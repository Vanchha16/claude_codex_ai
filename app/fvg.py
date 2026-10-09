"""FVG-Trend-M15-M5-v1: closed-candle FVG trend pullback with three staged limit entries (pure rule functions).

Predeclared v1 rules (task 20261007-111856; engineering starting values, not claimed profitable):
1. Closed contiguous M5 Bid candles; complete M15 groups only (app.models.aggregate). A/B/C are adjacent closed M15
   candles. BUY zone [A.high, C.low] if C.low > A.high (by >= 1 tick); SELL zone [C.high, A.low] if C.high < A.low.
   The zone exists only from C's close; C's own M5 bars can never retest it.
2. Qualification: gap >= max(2 ticks, 0.10 * ATR14) and B's directional body >= 1.0 * ATR14, ATR = Wilder ATR seeded
   with the SMA of 14 true ranges, computed over the contiguous M15 run through B (not C). Trend: EMA20 vs EMA50
   (SMA-seeded) over the contiguous closed M15 run ending at C, >= 50 candles; EMA20 > EMA50 allows BUY, < SELL, equal
   neither. Any market/data break restarts the run (warm-up).
3. Retest/confirmation: the FIRST later closed M5 bar intersecting the zone is the retest; its high (BUY) / low (SELL)
   is frozen. A DIFFERENT one of the next 3 contiguous closed M5 bars must close strictly beyond that level. Invalidation
   wins: a close beyond the zone's far edge (BUY close < bottom, SELL close > top), or a missing/invalid M5 bar. Setup
   lifetime: 2 hours from C's close. No stale setup is ever acted on after startup/restart/resume/reconnect (watermark).
4. Three limit entries at 1% / 50% / 80% depth (BUY measured down from the top, SELL up from the bottom), BUY rounded
   down / SELL up to the tick; a zone too narrow for three distinct prices is rejected.
5. One common SL 2 ticks beyond the far edge (rounded outward); each TP = its own entry +/- 2 * |entry - SL| (outward).
6. Eligibility at the decision boundary (task 20261007-161242): the confirmation must be at most 30 s old and its setup
   unexpired; every leg's |entry - SL| must be >= current spread + 1 tick (equality passes), and every limit must rest
   at least 1 tick on the correct side of the market; otherwise the WHOLE basket is rejected before any alert,
   reservation or broker call. Entries, the wick-based common SL, TPs and risk are unchanged.
Capacity, risk sizing and execution live in app/fvg_orders.py, app/fvg_replay.py, app/fvg_live.py, app/fvg_execution.py.
"""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .fastsweep import BUY, SELL, M15, ema_last
from .models import M5, Bar, SymbolMeta, round_down_to_tick, round_up_to_tick

STRATEGY = "FVG-Trend-M15-M5-v1"


@dataclass(frozen=True)
class FvgConfig:
    reward_risk: float = 2.0
    ema_fast: int = 20
    ema_slow: int = 50
    trend_min_candles: int = 50
    atr_period: int = 14
    gap_atr: float = 0.10
    displacement_atr: float = 1.0
    min_gap_ticks: int = 2
    entry_depths: tuple = (1.0, 50.0, 80.0)   # % depth into the zone from the near edge
    setup_minutes: int = 120                  # zone/setup lifetime from C's close
    confirm_bars: int = 3                     # M5 bars after the retest
    sl_buffer_ticks: int = 2
    quote_max_age_seconds: int = 30
    max_spread_price: float = 0.50
    cooldown_minutes: int = 30
    max_baskets_per_day: int = 4              # per Asia/Bangkok date; a cap, not a quota (12 legs max)
    pending_expiry_minutes: int = 120         # unfilled limit legs expire 2 h after placement
    stop_spread_margin_ticks: int = 1         # every leg's |entry - SL| >= current spread + this many ticks (rule 6)
    max_confirmation_age_seconds: int = 30    # a live confirmation older than this at decision time is never acted on

    def validate(self) -> "FvgConfig":
        if self.reward_risk != 2.0:
            raise ValueError("FVG v1 supports the chosen 1:2 target only")
        depths = tuple(self.entry_depths)
        if len(depths) != 3 or any(not isinstance(p, (int, float)) or not math.isfinite(p) or not 1 <= p <= 100 for p in depths):
            raise ValueError("need three entry depths between 1% and 100%")
        if not depths[0] < depths[1] < depths[2]:
            raise ValueError("entry depths must be strictly increasing")
        for name in ("ema_fast", "ema_slow", "trend_min_candles", "atr_period", "min_gap_ticks", "setup_minutes",
                     "confirm_bars", "sl_buffer_ticks", "quote_max_age_seconds", "cooldown_minutes",
                     "max_confirmation_age_seconds",
                     "max_baskets_per_day", "pending_expiry_minutes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not self.ema_fast < self.ema_slow <= self.trend_min_candles:
            raise ValueError("need ema_fast < ema_slow <= trend_min_candles")
        if isinstance(self.stop_spread_margin_ticks, bool) or not isinstance(self.stop_spread_margin_ticks, int) \
                or self.stop_spread_margin_ticks < 0:
            raise ValueError("stop_spread_margin_ticks must be a non-negative integer")
        for name in ("gap_atr", "displacement_atr", "max_spread_price"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.max_spread_price > 0.50:
            raise ValueError("max_spread_price cannot exceed 0.50")
        return self

    @property
    def version(self) -> str:
        digest = hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:8]
        return f"{STRATEGY}-RR2@{digest}"


PROFILES = {"rr2": FvgConfig()}


def is_fvg_version(version: Optional[str]) -> bool:
    return bool(version) and version.startswith(STRATEGY + "-")


# ---------------------------------------------------------------- 1. gap geometry
@dataclass(frozen=True)
class Gap:
    direction: str
    bottom: float
    top: float
    first: Bar
    third: Bar

    @property
    def midpoint(self) -> float:
        return (self.bottom + self.top) / 2


def detect_gap(a: Bar, b: Bar, c: Bar, tick: float, tf=M15) -> Optional[Gap]:
    """Three adjacent valid CLOSED candles of ONE timeframe `tf` (M15 for v1; M15 or M5 for the dual engines)."""
    if not math.isfinite(tick) or tick <= 0:
        raise ValueError("tick size must be finite and positive")
    if any(x.tf != tf or not x.is_valid() for x in (a, b, c)):
        return None
    if a.close_time != b.open_time or b.close_time != c.open_time:
        return None
    eps = tick * 1e-6
    if c.low - a.high >= tick - eps:
        return Gap(BUY, a.high, c.low, a, c)
    if a.low - c.high >= tick - eps:
        return Gap(SELL, c.high, a.low, a, c)
    return None


# ---------------------------------------------------------------- 2. qualification
def contiguous_run(bars: list[Bar], tf=M15) -> list[Bar]:
    """Valid adjacent suffix of `tf` candles; no indicator survives a market/data break."""
    run: list[Bar] = []
    for b in bars:
        if b.tf != tf or not b.is_valid():
            run = []
            continue
        if run and run[-1].close_time != b.open_time:
            run = []
        run.append(b)
    return run


def atr_last(bars: list[Bar], period: int) -> Optional[float]:
    """Wilder ATR: SMA of the first `period` true ranges, then (prev*(n-1)+tr)/n. Needs period+1 bars."""
    if len(bars) < period + 1:
        return None
    trs = [max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close)) for a, b in zip(bars, bars[1:])]
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period
    return value


def qualify(gap: Gap, history: list[Bar], cfg: FvgConfig, tick: float) -> Optional[str]:
    """`history`: closed candles of the gap's OWN timeframe ending at C (no later bars). Returns None or a reason."""
    run = contiguous_run(history, gap.third.tf)
    if not run or run[-1].close_time != gap.third.close_time:
        return "history_not_ending_at_c"
    if len(run) < cfg.trend_min_candles:
        return "trend_warmup"
    closes = [b.close for b in run]
    fast, slow = ema_last(closes, cfg.ema_fast), ema_last(closes, cfg.ema_slow)
    if fast is None or slow is None:
        return "trend_warmup"
    if abs(fast - slow) <= 1e-9:
        return "trend_flat"
    if (BUY if fast > slow else SELL) != gap.direction:
        return "trend_against"
    atr = atr_last(run[:-1], cfg.atr_period)  # through B only
    if atr is None or atr <= 0:
        return "atr_warmup"
    if gap.top - gap.bottom + tick * 1e-6 < max(cfg.min_gap_ticks * tick, cfg.gap_atr * atr):
        return "gap_too_small"
    middle = run[-2]
    body = middle.close - middle.open if gap.direction == BUY else middle.open - middle.close
    if body + tick * 1e-6 < cfg.displacement_atr * atr:
        return "weak_displacement"
    return None


# ---------------------------------------------------------------- 3. retest and confirmation
@dataclass
class FvgSetup:
    key: str
    direction: str
    bottom: float
    top: float
    a_open: datetime
    c_close: datetime          # available from here
    expires: datetime          # c_close + setup lifetime
    status: str = "pending"    # pending | retested | confirmed | invalidated | expired | rejected
    reason: Optional[str] = None
    next_open: Optional[datetime] = None
    retest_close: Optional[datetime] = None
    level: Optional[float] = None
    bars_after_retest: int = 0
    confirm_close: Optional[datetime] = None
    meta: dict = field(default_factory=dict)


def new_setup(gap: Gap, cfg: FvgConfig, symbol: str, version: str) -> FvgSetup:
    return FvgSetup(key=f"{symbol}|{gap.first.open_time.isoformat()}|{version}", direction=gap.direction,
                    bottom=gap.bottom, top=gap.top, a_open=gap.first.open_time, c_close=gap.third.close_time,
                    expires=gap.third.close_time + timedelta(minutes=cfg.setup_minutes), next_open=gap.third.close_time)


def advance_setup(s: FvgSetup, bar: Bar, cfg: FvgConfig) -> str:
    """Advance with one newly CLOSED M5 bar (in time order). Returns the setup status."""
    if s.status not in ("pending", "retested") or bar.open_time < s.c_close:
        return s.status
    if bar.open_time != s.next_open or not bar.is_valid():
        s.status, s.reason = "invalidated", "m5_continuity_lost"
        return s.status
    if bar.close_time > s.expires:
        s.status, s.reason = "expired", "setup_lifetime_elapsed"
        return s.status
    buy = s.direction == BUY
    far_break = bar.close < s.bottom if buy else bar.close > s.top
    s.next_open = bar.close_time
    if s.status == "pending":
        if far_break:  # a close beyond the far edge kills the zone before OR at the first touch (even a full gap)
            s.status, s.reason = "invalidated", "close_beyond_far_edge"
            return s.status
        if bar.low <= s.top and bar.high >= s.bottom:  # first intersecting bar = the retest
            s.status, s.retest_close, s.level = "retested", bar.close_time, (bar.high if buy else bar.low)
        return s.status
    s.bars_after_retest += 1                            # a DIFFERENT later bar: the retest can't confirm itself
    if far_break:                                        # invalidation has precedence
        s.status, s.reason = "invalidated", "close_beyond_far_edge"
    elif (bar.close > s.level) if buy else (bar.close < s.level):
        s.status, s.confirm_close = "confirmed", bar.close_time
    elif s.bars_after_retest >= cfg.confirm_bars:
        s.status, s.reason = "expired", "no_confirmation_after_retest"
    return s.status


# ---------------------------------------------------------------- 4-5. three-leg geometry
@dataclass(frozen=True)
class EntryLevel:
    number: int
    percent: float
    price: float


def entry_ladder(gap: Gap, meta: SymbolMeta, percentages=(1.0, 50.0, 80.0)) -> tuple[EntryLevel, ...]:
    """Three entry prices (planning only). BUY measured down from the top, SELL up from the bottom; BUY rounded down /
    SELL up, so rounding never gives a shallower retracement. Rejects a zone too narrow for three distinct prices."""
    if gap.direction not in (BUY, SELL) or not 0 < gap.bottom < gap.top:
        raise ValueError("invalid FVG direction or bounds")
    if not math.isfinite(meta.tick_size) or meta.tick_size <= 0:
        raise ValueError("tick size must be finite and positive")
    if len(percentages) != 3 or any(not math.isfinite(p) or not 1 <= p <= 100 for p in percentages):
        raise ValueError("need three FVG depths between 1% and 100%")
    if not percentages[0] < percentages[1] < percentages[2]:
        raise ValueError("entry depths must be strictly increasing")
    out = []
    for n, percent in enumerate(percentages, 1):
        # exact decimal arithmetic: binary float noise must not push an exact tick price one tick deeper/shallower
        top, bottom = Decimal(repr(gap.top)), Decimal(repr(gap.bottom))
        depth = (top - bottom) * Decimal(repr(float(percent))) / 100
        price = (round_down_to_tick(float(top - depth), meta.tick_size, meta.digits) if gap.direction == BUY else
                 round_up_to_tick(float(bottom + depth), meta.tick_size, meta.digits))
        if not gap.bottom - meta.tick_size * 1e-6 <= price <= gap.top + meta.tick_size * 1e-6:
            raise ValueError("rounded entry falls outside the FVG")
        out.append(EntryLevel(n, percent, price))
    if len({x.price for x in out}) != 3:
        raise ValueError("FVG is too narrow for three distinct entry levels")
    return tuple(out)


@dataclass(frozen=True)
class LegLevels:
    number: int
    percent: float
    entry: float
    tp: float


def basket_levels(gap: Gap, meta: SymbolMeta, cfg: FvgConfig) -> tuple[float, tuple[LegLevels, ...]]:
    """Common SL (2 ticks beyond the far edge, outward) and each leg's own 1:2 TP (outward). Raises if invalid."""
    buy = gap.direction == BUY
    D = lambda x: Decimal(repr(float(x)))  # exact decimals: float noise must not move a level by a tick
    buffer = cfg.sl_buffer_ticks * D(meta.tick_size)
    sl = (round_down_to_tick(float(D(gap.bottom) - buffer), meta.tick_size, meta.digits) if buy else
          round_up_to_tick(float(D(gap.top) + buffer), meta.tick_size, meta.digits))
    if sl <= 0:
        raise ValueError("shared stop must be positive")
    legs = []
    for lv in entry_ladder(gap, meta, tuple(cfg.entry_depths)):
        d = abs(D(lv.price) - D(sl))
        if d <= 0:
            raise ValueError("entry equals stop")
        reward = D(cfg.reward_risk) * d
        tp = (round_up_to_tick(float(D(lv.price) + reward), meta.tick_size, meta.digits) if buy else
              round_down_to_tick(float(D(lv.price) - reward), meta.tick_size, meta.digits))
        if tp <= 0:
            raise ValueError("target must be positive")
        legs.append(LegLevels(lv.number, lv.percent, lv.price, tp))
    return sl, tuple(legs)


def stop_within_spread(sl: float, entries, spread: float, cfg: FvgConfig, tick: float) -> Optional[str]:
    """Rule 6a: a reason if any leg's entry-to-stop distance is below spread + margin ticks (equality passes)."""
    if not math.isfinite(spread) or spread < 0:
        return "invalid spread"
    need = spread + cfg.stop_spread_margin_ticks * tick
    for n, entry in entries:
        distance = abs(entry - sl)
        if distance + tick * 1e-6 < need:
            return (f"leg {n} stop distance {distance:.2f} is below spread {spread:.2f} + "
                    f"{cfg.stop_spread_margin_ticks} tick(s); the stop would sit inside the spread at the fill")
    return None


def placement_violation(direction: str, entries, bid: float, ask: float, tick: float) -> Optional[str]:
    """Rule 6b: a reason if any limit would not rest at least 1 tick on the correct side of the market (BUY below the
    Ask, SELL above the Bid) - the same placement rule the live preflight enforces."""
    for n, entry in entries:
        distance = (ask - entry) if direction == BUY else (entry - bid)
        if distance + tick * 1e-6 < tick:
            return f"leg {n} limit {entry} is not on the resting side of the market (bid {bid}, ask {ask})"
    return None


def gap_from_setup(s: FvgSetup, first: Bar, third: Bar) -> Gap:
    return Gap(s.direction, s.bottom, s.top, first, third)


def m15_ready(m5_close: datetime) -> bool:
    return m5_close.minute % 15 == 0 and m5_close.second == 0


__all__ = ["STRATEGY", "FvgConfig", "PROFILES", "is_fvg_version", "Gap", "detect_gap", "contiguous_run", "atr_last",
           "qualify", "FvgSetup", "new_setup", "advance_setup", "EntryLevel", "entry_ladder", "LegLevels",
           "basket_levels", "stop_within_spread", "placement_violation", "M5"]
