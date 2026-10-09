"""FVG-Dual-M15-M5-Immediate-v2: two INDEPENDENT FVG order engines (task 20261008-143801).

Rules (user-approved 2026-10-08; engineering starting values, not claimed profitable):
1. Each engine uses three adjacent valid CLOSED A/B/C candles of its OWN timeframe (M15 engine: complete M15 candles
   aggregated from closed M5; M5 engine: closed M5 candles). BUY gap A.high..C.low, SELL gap C.high..A.low, >= 1 tick,
   available only from C's close. No forming-candle decisions.
2. Qualification on that engine's own contiguous history ending at C (app.fvg.qualify, same EMA20/EMA50 >= 50 candles,
   ATR14 through B, gap >= max(2 ticks, 0.10 ATR), B body >= 1.0 ATR, trend in the gap direction; equal EMAs neither).
   A data/market gap restarts that timeframe's run. Nothing is borrowed from the other engine.
3. Qualification IS the entry event (no retest, no confirmation). C must close STRICTLY after the session watermark and
   be <= 30 s old at the decision and at every send boundary. Catch-up/resume/reconnect never submits an old gap; each
   C is recorded once (accepted or rejected with a reason) and never re-decided.
4-5. Three limits at 1/50/80 % depth of the ORIGINATING zone, common SL 2 ticks beyond the far edge, each leg 1:2
   (app.fvg.basket_levels). Risk = the configured USD budget PER BASKET (10 USD), split in thirds before lot flooring.
   Stop policy per engine (user-approved: M5 in task 20261009-103608, M15 in task 20261009-110034): BOTH engines
   use a SPREAD-AWARE common stop: that base stop, moved outward by the fewest whole ticks so every leg is >= the
   measured spread + 1 tick from it (app.fvg.spread_aware_levels; entries unchanged, TPs recomputed at 1:2, lots
   shrink with the wider stop). It needs a valid fresh quote with spread <= the 0.50 maximum; otherwise nothing is
   adjusted. The fixed policy stays available per engine (stop_policy) for comparison/rollback; legacy v1 is fixed.
6. One open/unresolved basket PER ENGINE (pending, sending, unknown, partial and filled exposure all occupy it).
7. 30-minute cooldown PER ENGINE; at most 4 accepted baskets per Bangkok date in TOTAL across both engines. At one
   decision timestamp M15 is decided before M5 (deterministic allocation of a last daily slot).
8. Pending legs expire 120 min after placement. Candle-close invalidation uses the ORIGINATING timeframe: a later closed
   M15 candle for M15 baskets, a closed M5 candle for M5 baskets (BUY close < bottom, SELL close > top); wicks and the
   other engine's closes never count. Only that basket's own pending remainder is removed.
Legacy FVG-Trend-M15-M5-v1 baskets stay managed under their recorded rules and occupy the M15 slot until resolved.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

from .fastsweep import BUY, M15, bangkok_date, ema_last
from .fvg import (STOP_FIXED, STOP_POLICIES, STOP_SPREAD_AWARE, FvgConfig, Gap, atr_last, contiguous_run, detect_gap,
                  fixed_levels, new_setup, placement_violation, qualify, spread_aware_levels, stop_within_spread)
from .fvg_execution import comment_prefix, plan_id_for
from .fvg_live import EXEC_STATUS, FvgLiveEngine, basket_is_open
from .models import M5, Bar, SymbolMeta, aggregate, iso, parse_iso

DUAL_STRATEGY = "FVG-Dual-M15-M5-Immediate-v2"
ENGINES = ("M15", "M5")               # also the deterministic decision order at one timestamp
TF = {"M15": M15, "M5": M5}
TAG = {"M15": "FVG15", "M5": "FVG5"}  # broker comment / basket id prefix per engine
LEGACY_SLOT = "M15"                   # an open legacy v1 basket occupies the M15 engine's slot
WINDOW_M5 = 600                       # the live scanner's closed-M5 window (app.scanner.M5_WINDOW["fvg"]); replay uses
                                      # the same window so EMA/ATR seeding and therefore every decision agree


@dataclass(frozen=True)
class DualFvgConfig:
    rules: FvgConfig = field(default_factory=FvgConfig)
    engines: tuple = ENGINES
    max_open_baskets_per_engine: int = 1
    cooldown_scope: str = "per_engine"     # rules.cooldown_minutes applies to each engine separately
    daily_cap_scope: str = "total"         # rules.max_baskets_per_day counts both engines together
    risk_scope: str = "per_basket"         # the configured USD budget is per basket (2 engines -> 2x concurrent)
    entry_trigger: str = "qualified_fvg"   # no retest / confirmation stage
    # per-engine common-stop policy (part of the digest, so the engine versions record it); STOP_FIXED is the
    # rollback/comparison value
    stop_policy: tuple = (("M15", STOP_SPREAD_AWARE), ("M5", STOP_SPREAD_AWARE))

    def stop_policy_for(self, engine: str) -> str:
        return dict(self.stop_policy)[engine]

    def validate(self) -> "DualFvgConfig":
        self.rules.validate()
        if tuple(self.engines) != ENGINES:
            raise ValueError("the dual mode runs exactly the M15 and M5 engines, in that order")
        if (self.max_open_baskets_per_engine, self.cooldown_scope, self.daily_cap_scope, self.risk_scope,
                self.entry_trigger) != (1, "per_engine", "total", "per_basket", "qualified_fvg"):
            raise ValueError("unsupported dual-mode scope settings")
        policy = dict(self.stop_policy)
        if set(policy) != set(ENGINES) or any(v not in STOP_POLICIES for v in policy.values()):
            raise ValueError("stop_policy needs one known policy per engine")
        return self

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, default=list).encode()).hexdigest()[:8]

    @property
    def version(self) -> str:
        return f"{DUAL_STRATEGY}-RR2@{self.digest}"

    def engine_version(self, engine: str) -> str:
        return f"FVG-Immediate-{engine}-v2-RR2@{self.digest}"

    def scopes(self) -> dict:
        r = self.rules
        return {"open_baskets": f"{self.max_open_baskets_per_engine} per engine",
                "cooldown": f"{r.cooldown_minutes} min per engine",
                "daily_cap": f"{r.max_baskets_per_day} accepted baskets per Bangkok date in total (both engines)",
                "risk": "configured USD budget per basket; up to 2 baskets (one per engine) at once",
                "tie_order": "M15 before M5 at the same decision time", "pending_expiry_minutes": r.pending_expiry_minutes,
                "stop_policy": {e: (f"spread-aware: {r.sl_buffer_ticks} ticks beyond the far edge, moved further "
                                    f"outward by whole ticks when needed so every leg is >= spread + "
                                    f"{r.stop_spread_margin_ticks} tick from it")
                                if self.stop_policy_for(e) == STOP_SPREAD_AWARE else
                                f"fixed: {r.sl_buffer_ticks} ticks beyond the far edge" for e in ENGINES},
                "decision_max_age_seconds": r.max_confirmation_age_seconds}


DUAL_PROFILE = DualFvgConfig()


def is_dual_version(version: Optional[str]) -> bool:
    return bool(version) and (version.startswith(DUAL_STRATEGY) or version.startswith("FVG-Immediate-"))


def engine_of(b: dict) -> str:
    """Slot of a basket: its engine, or the M15 slot for a legacy v1 basket."""
    return b.get("engine") or LEGACY_SLOT


def invalidation_tf(b: dict):
    return M15 if b.get("engine") == "M15" else M5  # legacy v1 baskets keep their recorded M5-close rule


# ---------------------------------------------------------------- pure rules shared by live and replay
def engine_bars(m5: list[Bar], engine: str) -> list[Bar]:
    return aggregate(m5, M15) if engine == "M15" else [b for b in m5 if b.tf == M5]


def evaluate_c(engine: str, bars: list[Bar], meta: SymbolMeta, rules: FvgConfig) -> tuple[Optional[Gap], Optional[str]]:
    """bars: this engine's candles ending at C (bars[-1]). Returns (gap or None, rejection reason or None)."""
    if len(bars) < 3:
        return None, None
    gap = detect_gap(bars[-3], bars[-2], bars[-1], meta.tick_size, TF[engine])
    if gap is None:
        return None, None
    return gap, qualify(gap, bars, rules, meta.tick_size)


def closes_beyond(direction: str, bottom: float, top: float, bar: Bar) -> bool:
    return bar.close < bottom if direction == BUY else bar.close > top


@dataclass(frozen=True)
class Occupancy:
    engine: str            # slot (legacy -> M15)
    placed_at: datetime
    open: bool             # pending/sending/unknown/partial/filled exposure, or unresolved
    risk_usd: Optional[float]  # planned risk at the broker; None = unknown (never assumed zero)


def admission(engine: str, now: datetime, occupied: list[Occupancy], dcfg: DualFvgConfig,
              risk_usd: Optional[float]) -> Optional[str]:
    """Shared capacity rule (live and replay). None = admit; else the rejection reason."""
    r = dcfg.rules
    if any(o.open and o.engine == engine for o in occupied):
        return "engine_basket_open"
    last = max((o.placed_at for o in occupied if o.engine == engine), default=None)
    if last is not None and now - last < timedelta(minutes=r.cooldown_minutes):
        return "cooldown"
    if sum(1 for o in occupied if bangkok_date(o.placed_at) == bangkok_date(now)) >= r.max_baskets_per_day:
        return "daily_cap"
    if risk_usd is not None:  # concurrent planned risk: one budget per engine at most; unknown counts as a full budget
        used = sum((o.risk_usd if o.risk_usd is not None else risk_usd) for o in occupied if o.open)
        if used + risk_usd > len(ENGINES) * risk_usd + 1e-9:
            return "concurrent_risk_cap"
    return None


def readiness(engine: str, m5: list[Bar], rules: FvgConfig, now: datetime) -> dict:
    bars = engine_bars(m5, engine)
    run = contiguous_run(bars, TF[engine])
    closes = [b.close for b in run]
    fast, slow = ema_last(closes, rules.ema_fast), ema_last(closes, rules.ema_slow)
    atr = atr_last(run, rules.atr_period)
    trend = None
    if len(run) >= rules.trend_min_candles and fast is not None and slow is not None:
        trend = "flat" if abs(fast - slow) <= 1e-9 else ("up (BUY gaps allowed)" if fast > slow else "down (SELL gaps allowed)")
    step = TF[engine]
    last = run[-1].close_time if run else (m5[-1].close_time if m5 else None)
    nxt = None
    if m5:
        t = m5[-1].close_time
        epoch = datetime(1970, 1, 1, tzinfo=t.tzinfo)
        nxt = epoch + ((t - epoch) // step + 1) * step
    eta = None
    if run and len(run) < rules.trend_min_candles:
        eta = iso(run[-1].close_time + step * (rules.trend_min_candles - len(run)))
    return {"engine": engine, "timeframe": engine, "run": len(run), "required": rules.trend_min_candles,
            "ready": len(run) >= rules.trend_min_candles, "trend": trend, "atr14": None if atr is None else round(atr, 3),
            "last_close": iso(last) if last else None, "next_close": iso(nxt) if nxt else None,
            "ready_eta": eta, "checked_at": iso(now)}


# ---------------------------------------------------------------- live
class DualFvgLiveEngine(FvgLiveEngine):
    """Both engines in ONE scanner pass (one feed owner, each closed bar once). Reconciliation, cancellation retries,
    restart recovery and other-account handling are inherited unchanged from FvgLiveEngine and cover every FVG basket
    of the symbol (legacy v1 and both dual engines)."""
    kind = "fvg"
    dual = True

    def __init__(self, dcfg: DualFvgConfig, meta: SymbolMeta, fstore, events, mode: str, *,
                 risk_fn: Callable[[], Optional[float]] = lambda: None, **kw):
        super().__init__(dcfg.validate().rules, meta, fstore, events, mode, **kw)
        self.dcfg = dcfg
        self.version = dcfg.version
        self.versions = {e: dcfg.engine_version(e) for e in ENGINES}
        self.risk_fn = risk_fn
        self.engine_eval: dict = {e: None for e in ENGINES}
        self.engine_ready: dict = {e: None for e in ENGINES}
        self._admit_lock = threading.Lock()  # reservation (basket row) + capacity check are one atomic step

    def _event(self, kind: str, msg: str, at: datetime, level: str = "info") -> None:
        if self.events is not None:
            self.events.add_event(kind, f"[FVG dual] {msg}", level, at=at)

    def retire_legacy_setups(self, now: datetime) -> int:
        """A v1 setup waiting for a retest/confirmation is never reinterpreted by the dual rules: it is closed out."""
        n = 0
        for s in self.fstore.open_setups(self.symbol):
            if s.key.rsplit("|", 1)[-1] not in self.versions.values():
                s.status, s.reason = "expired", "retired_strategy_switch_to_dual"
                self.fstore.update_setup(s)
                n += 1
        if n:
            self._event("scanner", f"{n} legacy v1 setup(s) retired (not reinterpreted by the dual rules)", now)
        return n

    # ------------------------------------------------------------------ per closed M5 bar
    def process_bar(self, m5: list[Bar], i: int, entry_fn, now: datetime) -> list:
        bar = m5[i]
        self._entry_fn = entry_fn
        history = m5[: i + 1]
        m15 = aggregate(history, M15) if bar.close_time.minute % 15 == 0 and bar.close_time.second == 0 else []
        m15_bar = m15[-1] if m15 and m15[-1].close_time == bar.close_time else None
        self._manage_bar(bar, now)                 # M5 closes: M5 baskets and legacy v1 baskets
        if m15_bar is not None:
            self._manage_bar(m15_bar, now)         # M15 closes: M15 baskets only
            self._detect("M15", m15, now)          # M15 first at a shared timestamp
        self._detect("M5", engine_bars(history, "M5"), now)
        return []

    def _detect(self, engine: str, bars: list[Bar], now: datetime) -> None:
        if len(bars) < 3:
            return
        c = bars[-1]
        gap, why = evaluate_c(engine, bars, self.meta, self.cfg)
        self.engine_eval[engine] = {"engine": engine, "a_open": iso(bars[-3].open_time), "c_close": iso(c.close_time),
                                    "evaluated_at": iso(now), "reason": why,
                                    "gap": None if gap is None else {"direction": gap.direction, "bottom": gap.bottom,
                                                                     "top": gap.top},
                                    "config_version": self.versions[engine]}
        self.last_evaluation = self.engine_eval[engine]
        if gap is None:
            return
        s = new_setup(gap, self.cfg, self.symbol, self.versions[engine])
        s.expires = gap.third.close_time + timedelta(seconds=self.cfg.max_confirmation_age_seconds)  # decision window
        s.next_open = None
        s.status, s.reason = ("rejected", why) if why else ("qualified", None)
        s.meta = {"engine": engine, "mode": "dual", "strategy_version": self.version,
                  "warmup": self.eligible_after is not None and gap.third.close_time <= self.eligible_after}
        if not self.fstore.add_setup(s, self.symbol, self.versions[engine]):
            return  # this C was already recorded/decided (poll, restart): never decided or sent again
        self._event("candidate", f"{engine} {gap.direction} FVG {gap.bottom}-{gap.top} (C closed {iso(c.close_time)}): "
                                 + (f"rejected ({why})" if why else "qualified"), now)
        if not why:
            self._decide(engine, s, gap, now)

    def _reject(self, s, reason: str, now: datetime) -> None:
        s.status, s.reason = "rejected", reason
        self.fstore.update_setup(s)
        self._event("rejected", f"{s.meta.get('engine')} {s.direction} zone {s.bottom}-{s.top}: {reason}", now)

    def occupancy(self, family: list[dict], now: datetime) -> list[Occupancy]:
        out = []
        for b in family:
            ex = b.get("execution") or {}
            state = ex.get("state")
            if state in ("not_submitted", "disabled", "preflight_rejected") or (state == "rejected" and not any(
                    l.get("state") in ("pending", "unknown", "sending") for l in ex.get("legs") or [])):
                risk = 0.0  # nothing reached the broker
            else:  # sent, partial, unknown or never recorded (planned): the recorded budget, else unknown (not zero)
                risk = b.get("risk_usd") if b.get("risk_usd") is not None else ex.get("risk_usd")
            out.append(Occupancy(engine_of(b), parse_iso(b["placed_at"]), basket_is_open(b, now), risk))
        return out

    def _decide(self, engine: str, s, gap: Gap, now: datetime) -> None:
        cfg = self.cfg
        if self.eligible_after is not None and not s.c_close > self.eligible_after:
            return self._reject(s, "c_before_session_watermark", now)  # history/catch-up: recorded, never sent
        entry_fn = getattr(self, "_entry_fn", None)
        quote = None
        if entry_fn is not None:
            quote, current = entry_fn(None, None)
            now = max(now, current) if current is not None else now
        elif self.clock is not None:
            now = max(now, self.clock())
        age = (now - s.c_close).total_seconds()
        if age < 0:
            return self._reject(s, "c_close_in_future", now)
        if age > cfg.max_confirmation_age_seconds:
            return self._reject(s, f"decision_too_old ({age:.0f}s > {cfg.max_confirmation_age_seconds}s)", now)
        zone = Gap(s.direction, s.bottom, s.top, None, None)
        try:
            plan = fixed_levels(zone, self.meta, cfg)
        except ValueError as exc:
            return self._reject(s, f"levels_invalid: {exc}", now)
        policy = self.dcfg.stop_policy_for(engine)
        stop = plan.provenance() | {"policy": policy}
        if policy == STOP_SPREAD_AWARE and entry_fn is None:
            stop["note"] = "no live quote source: base stop kept, no spread adjustment"
        if entry_fn is not None:
            if quote is None:
                return self._reject(s, "no_quote_for_eligibility_check", now)
            if policy == STOP_SPREAD_AWARE:
                problem = quote_problem(quote, now, cfg.quote_max_age_seconds)
                if problem:  # never adjust from an invented, invalid or stale spread
                    return self._reject(s, f"no_quote_for_eligibility_check: {problem}", now)
                spread = quote.ask - quote.bid
                if spread <= cfg.max_spread_price + 1e-9:
                    try:
                        plan = spread_aware_levels(zone, self.meta, cfg, spread)
                    except ValueError as exc:
                        return self._reject(s, f"levels_invalid: {exc}", now)
                    stop = plan.provenance() | {"quote_time": iso(quote.time), "bid": quote.bid, "ask": quote.ask}
                else:
                    stop["note"] = f"spread {spread:.2f} above the {cfg.max_spread_price:.2f} maximum: not adjusted"
            sl, legs = plan.sl, plan.legs
            entries = [(l.number, l.entry) for l in legs]
            why = stop_within_spread(sl, entries, quote.ask - quote.bid, cfg, self.meta.tick_size)
            if why:
                return self._reject(s, f"stop_within_spread: {why}", now)
            why = placement_violation(s.direction, entries, quote.bid, quote.ask, self.meta.tick_size)
            if why:
                return self._reject(s, f"limit_on_wrong_side_of_market: {why}", now)
        sl, legs = plan.sl, plan.legs
        risk = self.risk_fn()
        current = self.account_fn()
        pid = plan_id_for(s.key)
        expires = now + timedelta(minutes=cfg.pending_expiry_minutes)
        with self._admit_lock:  # capacity check and the durable reservation (basket row) happen together
            family = [b for b in self._family() if current is None or b.get("account_id") in (None, current)]
            why = admission(engine, now, self.occupancy(family, now), self.dcfg, risk)
            if why:
                return self._reject(s, why, now)
            others = tuple((b.get("execution") or {}).get("comment_prefix") or comment_prefix(b["plan_id"])
                           for b in family if basket_is_open(b, now) and b.get("plan_id"))
            basket = {"id": f"{TAG[engine]}-{pid}", "plan_id": pid, "setup_key": s.key, "symbol": self.symbol,
                      "version": self.versions[engine], "strategy_version": self.version, "engine": engine,
                      "timeframe": engine, "mode": self.mode, "direction": s.direction, "bottom": s.bottom, "top": s.top,
                      "sl": sl, "a_open": iso(s.a_open), "decision_close": iso(s.c_close), "placed_at": iso(now),
                      "pending_expires": iso(expires), "accepted": True, "status": "planned", "risk_usd": None,
                      "legs": [{"n": l.number, "pct": l.percent, "entry": l.entry, "tp": l.tp, "sl": sl,
                                "rr": round(abs(l.tp - l.entry) / abs(l.entry - sl), 2)} for l in legs],
                      "execution": None, "meta": {"digits": self.meta.digits, "tick_size": self.meta.tick_size},
                      "account_id": current, "stop": stop}
            if not self.fstore.add_basket(basket):
                return self._reject(s, "duplicate_basket", now)
        s.status = "accepted"
        s.meta["basket"] = basket["id"]
        self.fstore.update_setup(s)
        self._event("signal", f"{basket['id']}: {engine} {s.direction} 3 limits {[l['entry'] for l in basket['legs']]} "
                              f"SL {sl}" + (f" (moved {stop['moved_ticks']} tick(s) outward from {stop['base_sl']} for "
                                            f"spread {stop['spread']:.2f})" if stop.get("moved_ticks") else ""), now)
        try:
            self.alert_fn(basket)  # Telegram opt-in + outbox (dedup by basket id); never the submission trigger
        except Exception as exc:
            self._event("error", f"{basket['id']}: alert failed: {type(exc).__name__}", now, "error")
        try:
            executor, why = self.executor_fn()
        except Exception as exc:
            executor, why = None, f"execution unavailable: {type(exc).__name__}"
        if executor is None:
            basket["status"], basket["execution"] = "alert_only", {"state": "not_submitted", "reason": why}
        else:
            try:
                result = executor.submit(pid, gap, self.meta, now, expires, stop_spread_margin_ticks=cfg.stop_spread_margin_ticks,
                                         eligibility={"confirm_close": s.c_close, "setup_expires": expires,
                                                      "max_age_seconds": cfg.max_confirmation_age_seconds},
                                         comment_tag=TAG[engine], allowed_prefixes=others, engine=engine,
                                         levels=(sl, legs), stop=stop)
            except Exception as exc:
                result = self._classify_submit_error(executor, pid, exc)
            basket["execution"] = result
            basket["risk_usd"] = result.get("risk_usd") if "legs" in result else None  # journal rows carry the budget
            basket["status"] = EXEC_STATUS.get(result.get("state"), result.get("state", "unknown"))
            self._event("order", f"{basket['id']}: automatic execution {result.get('state')}"
                                 + (f" ({result.get('reason')})" if result.get("reason") else ""), now)
        self.fstore.update_basket(basket)

    # ------------------------------------------------------------------ candle-close invalidation per timeframe
    def _manage_bar(self, bar: Bar, now: datetime, family: Optional[list] = None) -> None:
        for b in (family if family is not None else self._family()):
            if not basket_is_open(b, bar.close_time):
                if b["status"] == "alert_only" and bar.close_time >= parse_iso(b["pending_expires"]):
                    b["status"] = "expired_unsubmitted"
                    self.fstore.update_basket(b)
                continue
            if bar.tf != invalidation_tf(b) or not bar.is_valid():
                continue  # only the ORIGINATING timeframe's closed candles invalidate (never the other engine's)
            if b.get("zone_invalidated_at") or bar.close_time <= parse_iso(b["placed_at"]):
                continue
            if not closes_beyond(b["direction"], b["bottom"], b["top"], bar):
                continue
            b["zone_invalidated_at"] = iso(bar.close_time)
            b["zone_invalidated_by"] = "M15 close" if bar.tf == M15 else "M5 close"
            if b["status"] == "alert_only":
                b["status"], b["cancel_complete"] = "zone_invalidated", True
                self.fstore.update_basket(b)
                continue
            b["cancel_complete"] = False
            self.fstore.update_basket(b)
            self._retry_cancel(b, now, force=True)  # this basket's own pending remainder only

    def manage_baskets(self, m5: list[Bar], now: datetime) -> None:
        for b in self._family():
            self._retry_cancel(b, now)
        family = [b for b in self._family() if not b.get("zone_invalidated_at") and not b.get("other_account")
                  and (basket_is_open(b, now) or b["status"] in ("alert_only", "planned"))]
        if not family:
            return
        oldest = min(parse_iso(b["placed_at"]) for b in family)
        bars = sorted([b for b in m5 if b.close_time > oldest] + [b for b in aggregate(m5, M15) if b.close_time > oldest],
                      key=lambda b: (b.close_time, b.tf))
        for bar in bars:
            self._manage_bar(bar, now, family)

    def check_deadlines(self, now: datetime) -> None:
        return None  # a qualified C is decided immediately; there is no waiting setup lifetime

    def cancel_pending(self, now: datetime, reason: str) -> None:
        return None

    # ------------------------------------------------------------------ readiness and state
    def update_readiness(self, m5: list[Bar], now: datetime) -> dict:
        self.engine_ready = {e: readiness(e, m5, self.cfg, now) for e in ENGINES}
        m15 = self.engine_ready["M15"]
        self.readiness = {"engines": self.engine_ready, "ready": all(r["ready"] for r in self.engine_ready.values()),
                          "m15_run": m15["run"], "required": m15["required"], "trend": m15["trend"],
                          "next_m15_close": m15["next_close"], "last_m15_close": m15["last_close"], "checked_at": iso(now)}
        return self.readiness

    def state_summary(self, now: datetime) -> dict:
        current = self.account_fn()
        family = [b for b in self._family() if current is None or b.get("account_id") in (None, current)]
        r = self.cfg
        engines = {}
        for e in ENGINES:
            mine = [b for b in family if engine_of(b) == e]
            open_b = [b for b in mine if basket_is_open(b, now)]
            last = max((parse_iso(b["placed_at"]) for b in mine), default=None)
            cool = last + timedelta(minutes=r.cooldown_minutes) if last else None
            setups = self.fstore.setups_for_version(self.symbol, self.versions[e], 1)
            engines[e] = {"engine": e, "version": self.versions[e], "readiness": self.engine_ready.get(e),
                          "last_evaluation": self.engine_eval.get(e),
                          "last_setup": None if not setups else {
                              "direction": setups[0].direction, "bottom": setups[0].bottom, "top": setups[0].top,
                              "c_close": iso(setups[0].c_close), "status": setups[0].status, "reason": setups[0].reason,
                              "basket": (setups[0].meta or {}).get("basket")},
                          "slot": None if not open_b else {"basket": open_b[0]["id"], "status": open_b[0]["status"],
                                                           "legacy": not open_b[0].get("engine")},
                          "cooldown_until": iso(cool) if cool and cool > now else None}
        today = bangkok_date(now)
        return {"mode": "dual", "version": self.version, "engines": engines, "scopes": self.dcfg.scopes(),
                "daily": {"date": today, "accepted": sum(1 for b in family if bangkok_date(parse_iso(b["placed_at"])) == today),
                          "cap": r.max_baskets_per_day, "scope": "total across both engines"},
                "risk_usd_per_basket": self.risk_fn(), "max_concurrent_baskets": len(ENGINES)}


# ---------------------------------------------------------------- replay (in memory; never live state/broker/Telegram)
def replay_dual(m5: list[Bar], meta: SymbolMeta, dcfg: DualFvgConfig, costs, *, risk_usd: float = 10.0,
                window: int = WINDOW_M5) -> dict:
    """Chronological simulation with the SAME pure rules and admission function as the live engine. Simulated fills
    (app.fvg_replay._step_basket) - never broker evidence. Decisions happen at C's close (age 0)."""
    from .fvg_replay import Basket, Leg, _basket_row, _segment, _step_basket
    dcfg.validate()
    r = dcfg.rules
    m5 = sorted(m5, key=lambda b: b.open_time)
    setups, baskets = [], []
    engine_of_basket: dict = {}
    funnel = {e: {"triples": 0, "raw_gaps": 0, "qualified": 0, "accepted": 0} for e in ENGINES}
    for i, bar in enumerate(m5):
        for b in baskets:
            if b.open():
                _step_basket(b, bar, costs, invalidate=False)
        history = m5[max(0, i + 1 - window): i + 1]  # exactly what the live scanner sees at this close
        m15 = aggregate(history, M15) if bar.close_time.minute % 15 == 0 else []
        m15_bar = m15[-1] if m15 and m15[-1].close_time == bar.close_time else None
        for b in baskets:  # candle-close invalidation on the originating timeframe only
            e = engine_of_basket[b.id]
            cbar = bar if e == "M5" else m15_bar
            if cbar is not None and cbar.close_time > b.placed_at and closes_beyond(b.direction, b.bottom, b.top, cbar):
                for leg in b.legs:
                    if leg.state == "pending":
                        leg.state, leg.note = "cancelled", f"zone invalidated ({e} close beyond far edge)"
        for e in ENGINES:
            if e == "M15" and m15_bar is None:
                continue
            bars = m15 if e == "M15" else engine_bars(history, "M5")
            if len(bars) < 3 or bars[-1].close_time != bar.close_time:
                continue
            funnel[e]["triples"] += 1
            gap, why = evaluate_c(e, bars, meta, r)
            if gap is None:
                continue
            funnel[e]["raw_gaps"] += 1
            row = {"engine": e, "direction": gap.direction, "bottom": gap.bottom, "top": gap.top,
                   "a_open": iso(gap.first.open_time), "c_close": iso(gap.third.close_time), "status": "rejected", "reason": why}
            setups.append(row)
            if why:
                continue
            funnel[e]["qualified"] += 1
            t = gap.third.close_time
            occ = [Occupancy(engine_of_basket[b.id], b.placed_at, b.open(), risk_usd) for b in baskets]
            why = admission(e, t, occ, dcfg, risk_usd)
            if why is None:
                try:  # replay has no contemporaneous quotes: the spread-aware stop uses the ASSUMED costs.spread
                    plan = (spread_aware_levels(gap, meta, r, costs.spread)
                            if dcfg.stop_policy_for(e) == STOP_SPREAD_AWARE and costs.spread <= r.max_spread_price + 1e-9
                            else fixed_levels(gap, meta, r))
                    sl, legs = plan.sl, plan.legs
                except ValueError as exc:
                    why = f"levels_invalid: {exc}"
            if why is None:
                entries = [(l.number, l.entry) for l in legs]
                if stop_within_spread(sl, entries, costs.spread, r, meta.tick_size):
                    why = "stop_within_spread"
                elif placement_violation(gap.direction, entries, bar.close, bar.close + costs.spread, meta.tick_size):
                    why = "limit_on_wrong_side_of_market"
            if why:
                row["reason"] = why
                continue
            b = Basket(id=f"{TAG[e]}-{gap.direction}-{iso(gap.first.open_time)}", direction=gap.direction,
                       bottom=gap.bottom, top=gap.top, sl=sl, placed_at=t,
                       pending_expires=t + timedelta(minutes=r.pending_expiry_minutes),
                       legs=[Leg(l.number, l.percent, l.entry, l.tp) for l in legs])
            baskets.append(b)
            engine_of_basket[b.id] = e
            funnel[e]["accepted"] += 1
            row["status"], row["reason"], row["basket"] = "accepted", None, b.id
    for b in baskets:
        for leg in b.legs:
            if leg.state == "pending":
                leg.state = "unfilled_at_end"
            elif leg.state == "filled" and leg.outcome is None:
                leg.outcome, leg.note = "unresolved", "history ended with the position open"
    return {"strategy": dcfg.version, "simulation": True, "symbol": meta.name, "costs": asdict(costs), "funnel": funnel,
            "stop_policy": dict(dcfg.stop_policy),
            "spread_note": (f"no contemporaneous quotes: spread checks and the spread-aware stop use the assumed "
                            f"spread {costs.spread} for every decision (not historical spread validation)"),
            "setups": setups,
            "segments": {e: _segment([b for b in baskets if engine_of_basket[b.id] == e]) for e in ENGINES}
            | {"all": _segment(baskets)},
            "baskets": [_basket_row(b) | {"engine": engine_of_basket[b.id]} for b in baskets]}


def quote_problem(quote, now: datetime, max_age_seconds: int) -> Optional[str]:
    """Why a quote cannot supply the spread for a stop adjustment (None = usable). Never substitutes a value."""
    try:
        valid = quote.is_valid()
        age = (now - quote.time).total_seconds()
    except Exception:
        return "quote unreadable"
    if not valid:
        return "quote invalid"
    if not -5 <= age <= max_age_seconds:
        return f"quote is {age:.0f}s old (> {max_age_seconds}s)"
    return None


__all__ = ["DUAL_STRATEGY", "ENGINES", "DualFvgConfig", "DUAL_PROFILE", "DualFvgLiveEngine", "Occupancy", "admission",
           "evaluate_c", "engine_bars", "readiness", "replay_dual", "is_dual_version", "engine_of"]
