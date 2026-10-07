"""Explicitly armed MT5 pending-limit adapter for FVG baskets, with a durable per-leg journal.

THIS IS THE ONLY MODULE THAT CAN SEND BROKER REQUESTS. CRT-SMC-v1, FastSweep and the data feed stay read-only.
- No initialize/login: the workstation passes the ALREADY-connected MetaTrader5 module and calls under its feed lock.
- Default OFF. Submission requires ALL of: an explicit execution opt-in bound to source/symbol/account/strategy version
  (separate from the Telegram opt-in), a configured positive USD risk budget, a supported account currency (USD, or
  USC cent accounts converted explicitly), a hedging account, a healthy fresh quote, broker preflight of all three legs,
  margin, and no existing orders/positions on the symbol.
- Durable journal row before every send ("sending"); a missing/timeout result becomes "unknown" and is NEVER resent.
  Partial batches are reported as partial. Reconciliation reads broker orders, positions, order history and deals.
- Cancellation only removes pending orders this engine owns (magic + comment + ticket).
Constants not exported by the MetaTrader5 Python package (verified on 5.0.6231) use the documented MQL5 values:
SYMBOL_ORDER_LIMIT=2, SYMBOL_EXPIRATION_SPECIFIED=4
(https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants).
Pending limits always use ORDER_FILLING_RETURN, as MQL5 Order Properties requires for pending orders regardless of
the symbol's market execution/filling flags (https://www.mql5.com/en/docs/constants/tradingconstants/orderproperties).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from .fastsweep import BUY
from .fvg import Gap
from .fvg_orders import account_cash_risk, build_order_plan
from .models import SymbolMeta
from .mt5_time import UTC_BASE, TimeBase

MAGIC = 761007
DOC_CONSTANTS = {"SYMBOL_ORDER_LIMIT": 2, "SYMBOL_EXPIRATION_SPECIFIED": 4}
TERMINAL_LEG_STATES = {"rejected", "cancelled", "expired", "closed_tp", "closed_sl", "closed_other", "not_sent"}


class OtherAccountError(ValueError):
    """The terminal is logged into a different account/server than the one this plan was submitted on."""


class UnverifiableAccountError(OtherAccountError):
    """A legacy journal without server identity: ownership cannot be proven on any connected account."""


def const(mt5, name: str) -> int:
    value = getattr(mt5, name, None)
    return DOC_CONSTANTS[name] if value is None else value


def account_fp(login) -> str:
    """LEGACY login-only fingerprint (pre 20261007-161242). Never accepted as consent or ownership proof any more."""
    return hashlib.sha256(f"mt5-login:{login}".encode()).hexdigest()[:12]


def account_id(account) -> str:
    """Canonical account identity = trade SERVER + login, hashed so the login is never stored or shown. The same login
    on another server is another account (consent, journals, submission, reconciliation and cancellation)."""
    server, login = getattr(account, "server", None), getattr(account, "login", None)
    return "srv1-" + hashlib.sha256(f"mt5-account:{server}|{login}".encode()).hexdigest()[:16]


def plan_id_for(setup_key: str) -> str:
    return hashlib.sha256(setup_key.encode()).hexdigest()[:16]


def leg_comment(plan_id: str, number: int) -> str:
    return f"FVG-{plan_id}-L{number}"  # <= 31 characters (MT5 comment limit)


# ---------------------------------------------------------------- policy, risk preference and opt-in
@dataclass(frozen=True)
class ExecutionPolicy:
    enabled: bool = False
    risk_usd: Optional[float] = None
    account_login: Optional[int] = None
    source: Optional[str] = None
    symbol: Optional[str] = None
    strategy_version: Optional[str] = None
    account_server: Optional[str] = None   # the trade server of the explicitly bound account (with account_login)

    def validate(self) -> "ExecutionPolicy":
        if self.risk_usd is not None and (isinstance(self.risk_usd, bool) or not isinstance(self.risk_usd, (int, float))
                                          or not math.isfinite(self.risk_usd) or self.risk_usd <= 0):
            raise ValueError("risk_usd must be a positive finite USD amount")
        if self.enabled and (self.risk_usd is None or self.account_login is None or not self.account_server
                             or not self.symbol or self.source != "mt5" or not self.strategy_version):
            raise ValueError("automatic execution needs a risk budget and an explicit mt5/symbol/server+login/version binding")
        return self


def load_risk_usd(path: Path) -> Optional[float]:
    """The confirmed risk PREFERENCE (does not arm anything). Missing/invalid -> None = 'risk not configured'."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        value = raw.get("risk_usd_per_setup")
    except (OSError, ValueError, AttributeError):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


class ExecutionOptIn:
    """Persisted explicit arming of automatic execution, bound to source/symbol/account/strategy version."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Optional[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def matches(self, binding: dict) -> bool:
        saved = self.load()
        return bool(saved and saved.get("binding") == binding)

    def arm(self, binding: dict, at: datetime) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".fvg_optin.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"binding": binding, "armed_at": at.isoformat()}, fh)
        os.replace(tmp, self.path)

    def disarm(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------- journal
class ExecutionJournal:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS fvg_execution (plan_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.commit()
        self.lock = threading.RLock()

    def get(self, plan_id):
        with self.lock:
            row = self.db.execute("SELECT payload FROM fvg_execution WHERE plan_id=?", (plan_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def create(self, plan_id, payload):
        with self.lock:
            cursor = self.db.execute("INSERT OR IGNORE INTO fvg_execution VALUES (?,?)", (plan_id, json.dumps(payload)))
            self.db.commit()
            return cursor.rowcount == 1

    def save(self, plan_id, payload):
        with self.lock:
            self.db.execute("UPDATE fvg_execution SET payload=? WHERE plan_id=?", (json.dumps(payload), plan_id))
            self.db.commit()

    def rows(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM fvg_execution")]

    def close(self):
        with self.lock:
            self.db.close()


# ---------------------------------------------------------------- executor
class MT5FvgExecutor:
    def __init__(self, module_fn: Callable[[], object], journal: ExecutionJournal, policy: ExecutionPolicy,
                 lock: Optional[threading.RLock] = None, timebase_fn: Optional[Callable[[], TimeBase]] = None,
                 clock: Optional[Callable[[], datetime]] = None):
        """timebase_fn: the CONNECTED feed's time base (app/mt5_time.py), so quote age, the pending expiration and
        history ranges use exactly the same UTC conversion as the feed. Default: documented UTC.
        clock: the real UTC clock for quote-age checks (the caller's `now` may be the scan start); default: the
        caller's `now` advanced by the elapsed monotonic time inside submit()."""
        self.module_fn, self.journal, self.policy = module_fn, journal, policy.validate()
        self.lock = lock or threading.RLock()
        self.timebase_fn = timebase_fn or (lambda: UTC_BASE)
        self.clock = clock

    @property
    def mt5(self):
        return self.module_fn()

    def _context(self, symbol: str, now: datetime):
        mt5 = self.mt5
        if mt5 is None:
            raise ValueError("MT5 is not connected")
        terminal, account, info, tick = mt5.terminal_info(), mt5.account_info(), mt5.symbol_info(symbol), mt5.symbol_info_tick(symbol)
        if any(x is None for x in (terminal, account, info, tick)):
            raise ValueError("MT5 trading context is unavailable")
        if account.login != self.policy.account_login or getattr(account, "server", None) != self.policy.account_server:
            raise ValueError("MT5 account/server differs from the explicitly bound server+login")
        tb = self.timebase_fn()
        if tb.server is not None and getattr(account, "server", None) != tb.server:
            raise ValueError("MT5 trade server differs from the server whose time base is in use")
        if symbol != self.policy.symbol:
            raise ValueError("symbol differs from the explicitly bound symbol")
        if not terminal.connected or not getattr(terminal, "trade_allowed", False) or getattr(terminal, "tradeapi_disabled", True):
            raise ValueError("MT5 terminal does not permit Python trading")
        if not getattr(account, "trade_allowed", False) or not getattr(account, "trade_expert", False):
            raise ValueError("account does not permit automated trading")
        if account.margin_mode != mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING:
            raise ValueError("three independent targets require a hedging account; netting is not supported")
        if info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            raise ValueError("symbol is not fully tradable")
        stamp = (getattr(tick, "time_msc", 0) or 0) / 1000 or tick.time
        age = (now - tb.to_utc(stamp)).total_seconds()  # the feed's own conversion: no second, different offset
        if not math.isfinite(tick.bid) or not math.isfinite(tick.ask) or tick.bid <= 0 or tick.ask < tick.bid or not -5 <= age <= 30:
            raise ValueError("invalid or stale MT5 quote")
        if tick.ask - tick.bid > 0.50 + 1e-9:
            raise ValueError("spread exceeds 0.50")
        orders, positions = mt5.orders_get(symbol=symbol), mt5.positions_get(symbol=symbol)
        if orders is None or positions is None:
            raise ValueError("cannot verify existing symbol exposure")
        if orders or positions:
            raise ValueError("existing orders or positions on the symbol block another FVG basket")
        if not math.isfinite(account.equity) or account.equity <= 0:
            raise ValueError("invalid account equity")
        return account, info, tick

    @staticmethod
    def _check_distances(plan, info, tick, tick_size) -> None:
        min_distance = max(info.trade_stops_level * info.point, tick_size)
        for leg in plan:
            buy = leg.direction == BUY
            distance = tick.ask - leg.entry if buy else leg.entry - tick.bid  # a limit must rest beyond the market
            if (distance + 1e-9 < min_distance or abs(leg.entry - leg.sl) + 1e-9 < min_distance
                    or abs(leg.tp - leg.entry) + 1e-9 < min_distance):
                raise ValueError(f"leg {leg.number}: limit/SL/TP violates the broker distance rules at the current quote")

    @staticmethod
    def _check_spread_room(plan, tick, margin_ticks: int, tick_size: float) -> None:
        """Rule 6a on the actual broker quote: every stop >= spread + margin ticks from its entry (equality passes)."""
        spread = tick.ask - tick.bid
        need = spread + margin_ticks * tick_size
        for leg in plan:
            distance = abs(leg.entry - leg.sl)
            if distance + tick_size * 1e-6 < need:
                raise ValueError(f"leg {leg.number}: stop distance {distance:.2f} is below spread {spread:.2f} + "
                                 f"{margin_ticks} tick(s); whole basket rejected")

    @staticmethod
    def _ineligible(eligibility: Optional[dict], at: datetime, expires: datetime) -> Optional[str]:
        """Decision context carried from the engine, re-checked with the CURRENT clock at every send boundary."""
        if at >= expires:
            return "the pending-order lifetime has already passed"
        if not eligibility:
            return None
        age = (at - eligibility["confirm_close"]).total_seconds()
        if age < 0:
            return "the confirmation is in the future"
        if at >= eligibility["setup_expires"]:
            return "the setup has expired"
        if age > eligibility["max_age_seconds"]:
            return f"the confirmation is {age:.0f}s old (> {eligibility['max_age_seconds']}s)"
        return None

    def submit(self, plan_id: str, gap: Gap, meta: SymbolMeta, now: datetime, expires: datetime, *,
               stop_spread_margin_ticks: int = 1, eligibility: Optional[dict] = None) -> dict:
        """Automatic submission of one basket. Never retried after a journal row exists (idempotent).
        eligibility = {"confirm_close", "setup_expires", "max_age_seconds"}: checked with the current clock before
        preflight, after preflight and immediately before EVERY send; stale context sends nothing new."""
        if not self.policy.enabled:
            return {"state": "disabled", "reason": "automatic execution is OFF; no orders submitted"}
        if self.policy.risk_usd is None:
            return {"state": "disabled", "reason": "risk not configured; no orders submitted"}
        started = time.monotonic()

        def clock_now() -> datetime:  # quote ages against the time of each check, not the scan start
            return self.clock() if self.clock else now + timedelta(seconds=time.monotonic() - started)

        with self.lock:
            old = self.journal.get(plan_id)
            if old is not None:
                return old  # includes unknown/in-progress states after a restart: never resend
            if expires <= now or now.tzinfo is None or expires.tzinfo is None:
                raise ValueError("pending-order expiry must be in the future, in UTC")
            why = self._ineligible(eligibility, clock_now(), expires)
            if why:
                raise ValueError(f"no longer eligible: {why}")
            account, info, tick = self._context(meta.name, clock_now())
            mt5 = self.mt5
            cash = account_cash_risk(self.policy.risk_usd, getattr(account, "currency", ""))

            def loss(direction, entry, stop):
                result = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY if direction == BUY else mt5.ORDER_TYPE_SELL,
                                               meta.name, 1.0, entry, stop)
                if result is None or not math.isfinite(result) or result >= 0:
                    raise ValueError("MT5 could not calculate the stop loss in account currency")
                return -result

            broker_meta = SymbolMeta(meta.name, info.trade_tick_size, info.point, info.digits, "mt5")  # current precision
            plan = build_order_plan(gap, broker_meta, cash, loss, volume_min=info.volume_min,
                                    volume_max=info.volume_max, volume_step=info.volume_step)
            if not info.order_mode & const(mt5, "SYMBOL_ORDER_LIMIT"):
                raise ValueError("symbol does not permit limit orders")
            if not info.expiration_mode & const(mt5, "SYMBOL_EXPIRATION_SPECIFIED"):
                raise ValueError("broker does not support a specified pending-order expiry")
            filling = mt5.ORDER_FILLING_RETURN  # pending orders: RETURN regardless of the market filling flags
            self._check_distances(plan, info, tick, broker_meta.tick_size)
            self._check_spread_room(plan, tick, stop_spread_margin_ticks, broker_meta.tick_size)
            requests, margin = [], 0.0
            for leg in plan:
                buy = leg.direction == BUY
                request = {"action": mt5.TRADE_ACTION_PENDING, "symbol": meta.name, "volume": leg.volume,
                           "type": mt5.ORDER_TYPE_BUY_LIMIT if buy else mt5.ORDER_TYPE_SELL_LIMIT,
                           "price": leg.entry, "sl": leg.sl, "tp": leg.tp, "magic": MAGIC,
                           "comment": leg_comment(plan_id, leg.number), "type_filling": filling,
                           "type_time": mt5.ORDER_TIME_SPECIFIED,
                           "expiration": int(self.timebase_fn().to_broker(expires).timestamp())}  # broker time base
                check = mt5.order_check(request)
                if check is None or check.retcode != 0:
                    raise ValueError(f"broker preflight rejected FVG leg {leg.number} (retcode {getattr(check, 'retcode', None)})")
                required = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL, meta.name, leg.volume, leg.entry)
                if required is None or not math.isfinite(required) or required < 0:
                    raise ValueError("broker margin calculation failed")
                margin += required
                requests.append(request)
            if not math.isfinite(account.margin_free) or margin > account.margin_free:
                raise ValueError("the three orders exceed available margin")
            # Immediately before the first send: re-read account/exposure AND re-validate the limits on the fresh quote.
            _, info2, tick2 = self._context(meta.name, clock_now())
            self._check_distances(plan, info2, tick2, broker_meta.tick_size)
            self._check_spread_room(plan, tick2, stop_spread_margin_ticks, broker_meta.tick_size)
            why = self._ineligible(eligibility, clock_now(), expires)  # a slow preflight can age the confirmation
            if why:
                raise ValueError(f"no longer eligible after preflight: {why}")
            payload = {"plan_id": plan_id, "symbol": meta.name, "account_id": account_id(account),
                       "account_server": getattr(account, "server", None),
                       "account_currency": getattr(account, "currency", ""), "state": "prepared",
                       "expires": expires.isoformat(), "created_at": now.isoformat(),
                       "time_base": self.timebase_fn().to_dict(), "risk_usd": self.policy.risk_usd,
                       "cash_risk_account_ccy": cash, "nominal_planned_loss": sum(p.planned_loss for p in plan),
                       "legs": [{**asdict(p), "state": "prepared", "ticket": None, "comment": leg_comment(plan_id, p.number)}
                                for p in plan]}
            if not self.journal.create(plan_id, payload):  # durable reservation before any send
                return self.journal.get(plan_id)
            accepted = {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}
            for i, request in enumerate(requests):
                leg = payload["legs"][i]
                why = self._ineligible(eligibility, clock_now(), expires)
                if why:  # immediately before THIS send: stale context never sends; accepted legs stay reconciled
                    for rest in payload["legs"][i:]:
                        rest["state"] = "not_sent"
                    payload["state"] = "partial" if i else "rejected"
                    payload["reason"] = f"stopped before leg {leg['number']}: {why}"
                    self.journal.save(plan_id, payload)
                    return payload
                leg["state"], payload["state"] = "sending", "submitting"
                self.journal.save(plan_id, payload)  # written BEFORE order_send: a crash leaves "sending" = unknown
                try:
                    result = mt5.order_send(request)
                except Exception:
                    result = None
                if result is None or result.retcode in (mt5.TRADE_RETCODE_TIMEOUT, mt5.TRADE_RETCODE_CONNECTION):
                    leg["state"], payload["state"] = "unknown", "needs_reconciliation"
                    for rest in payload["legs"][i + 1:]:
                        rest["state"] = "not_sent"
                    self.journal.save(plan_id, payload)
                    return payload  # earlier accepted legs stay visible; never send the rest blindly
                leg["retcode"] = result.retcode
                if result.retcode not in accepted or not result.order:
                    leg["state"], payload["state"] = "rejected", ("partial" if i else "rejected")
                    for rest in payload["legs"][i + 1:]:
                        rest["state"] = "not_sent"
                    self.journal.save(plan_id, payload)
                    return payload
                leg["state"], leg["ticket"] = "pending", result.order
                self.journal.save(plan_id, payload)
            payload["state"] = "submitted"
            self.journal.save(plan_id, payload)
            return payload

    # ---------------------------------------------------------------- after submission
    FINAL_LEG_STATES = {"prepared", "not_sent", "rejected", "closed_tp", "closed_sl", "closed_other"}
    SETTLE_SECONDS = 60  # a basket is closed only after its terminal state was seen twice, >= 60 s apart

    def _owned(self, x, payload, leg) -> bool:
        return (getattr(x, "symbol", None) == payload["symbol"] and getattr(x, "magic", None) == MAGIC and
                (x.ticket == leg["ticket"] if leg.get("ticket") else getattr(x, "comment", "") == leg["comment"]))

    def _now(self) -> datetime:
        return self.clock() if self.clock else datetime.now(timezone.utc)

    @staticmethod
    def _check_owner(account, payload) -> None:
        """Ownership = the ORIGINAL server+login recorded before any send; legacy journals cannot prove it."""
        if "account_id" not in payload:
            raise UnverifiableAccountError("legacy execution journal without server identity: ownership cannot be "
                                           "verified on any account; left unresolved for manual review")
        if account is None or account_id(account) != payload["account_id"]:
            raise OtherAccountError("the connected MT5 server+login is not the account this plan was submitted on")

    def reconcile(self, plan_id: str, now: datetime) -> Optional[dict]:
        """Read broker state after submission/restart; never resubmits or guesses. Broker results are real outcomes,
        never labelled as simulated price hits."""
        with self.lock:
            payload = self.journal.get(plan_id)
            if payload is None:
                return None
            mt5 = self.mt5
            if mt5 is None:
                return payload
            self._check_owner(mt5.account_info(), payload)
            self._refresh(mt5, plan_id, payload, now)
            return payload

    def _refresh(self, mt5, plan_id: str, payload: dict, now: datetime) -> None:
        # broker time base, with a wide margin: a mis-set or changed offset must never hide this plan's deals
        # (rows are matched by ticket/comment/magic, so the wider window cannot adopt foreign records)
        tb = self.timebase_fn()
        start = tb.to_broker(datetime.fromisoformat(payload["created_at"])) - timedelta(days=1)
        end = tb.to_broker(now) + timedelta(days=1)
        pending = mt5.orders_get(symbol=payload["symbol"])
        positions = mt5.positions_get(symbol=payload["symbol"])
        history = mt5.history_orders_get(start, end)
        deals = mt5.history_deals_get(start, end)
        if pending is None or positions is None or history is None or deals is None:
            return  # cannot read now: keep the last known states
        states = {mt5.ORDER_STATE_PLACED: "pending", mt5.ORDER_STATE_STARTED: "pending",
                  mt5.ORDER_STATE_CANCELED: "cancelled", mt5.ORDER_STATE_EXPIRED: "expired",
                  mt5.ORDER_STATE_REJECTED: "rejected", mt5.ORDER_STATE_PARTIAL: "partially_filled"}
        out_entries = {mt5.DEAL_ENTRY_OUT, getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)}
        open_ids = {getattr(p, "identifier", getattr(p, "ticket", None)) for p in positions}
        for leg in payload["legs"]:
            # cancelled/expired legs are re-examined while the basket is open: a fill can race the removal and its
            # deals can appear in history later; only truly final states are skipped
            if leg["state"] in self.FINAL_LEG_STATES:
                continue
            live = [x for x in pending if self._owned(x, payload, leg)]
            past = [x for x in history if self._owned(x, payload, leg)]
            if len(live) + len(past) > 1 and not leg.get("ticket"):
                leg["note"] = "several matching orders; needs manual review"
                continue
            order = (live or past or [None])[0]
            if order is None:
                continue  # unknown stays unknown (also a removal whose history is not visible yet); no resend
            leg["ticket"] = order.ticket
            ins = [d for d in deals if getattr(d, "order", None) == order.ticket and d.entry == mt5.DEAL_ENTRY_IN]
            pos_ids = {d.position_id for d in ins if getattr(d, "position_id", None)}
            if not pos_ids and order.state in (mt5.ORDER_STATE_FILLED, mt5.ORDER_STATE_PARTIAL):
                pos_ids = {getattr(order, "position_id", 0) or order.ticket}
            filled = round(sum(getattr(d, "volume", 0.0) for d in ins), 8)
            if not ins and order.state == mt5.ORDER_STATE_FILLED:
                filled = getattr(order, "volume_initial", None)
            remaining = getattr(live[0], "volume_current", None) if live else 0.0
            leg["filled_volume"], leg["pending_volume"] = filled, remaining
            if not pos_ids:
                leg["state"] = "pending" if live else states.get(order.state, "unknown")
                continue
            leg["position_id"] = sorted(pos_ids)[0] if len(pos_ids) == 1 else sorted(pos_ids)
            if live:  # filled volume open AND a pending remainder still resting at the broker
                leg["state"] = "partially_filled"
                continue
            if order.state != mt5.ORDER_STATE_FILLED:
                leg["remainder"] = states.get(order.state, "unknown")  # e.g. partial fill, remainder cancelled/expired
            pos_deals = [d for d in deals if getattr(d, "position_id", None) in pos_ids]
            closes = [d for d in pos_deals if d.entry in out_entries]
            if pos_ids & open_ids or not closes:
                leg["state"] = "filled_open"
                continue
            # actual broker result: every deal of the position(s), entry-side commission/fees included
            leg["broker_pnl"] = round(sum(getattr(x, "profit", 0.0) + getattr(x, "commission", 0.0) + getattr(x, "swap", 0.0)
                                          + getattr(x, "fee", 0.0) for x in pos_deals), 2)
            leg["exit_price"] = closes[-1].price
            reasons = {d.reason for d in closes}
            leg["state"] = ("closed_tp" if reasons == {mt5.DEAL_REASON_TP} else
                            "closed_sl" if reasons == {mt5.DEAL_REASON_SL} else "closed_other")
        legs = payload["legs"]
        prefix = f"FVG-{plan_id}-"
        plan_positions = [p for p in positions if getattr(p, "magic", None) == MAGIC
                          and str(getattr(p, "comment", "") or "").startswith(prefix)]
        leg_positions = {pid for l in legs for pid in (l.get("position_id") if isinstance(l.get("position_id"), list)
                                                       else [l.get("position_id")]) if pid}
        exposed = bool(plan_positions) or bool(leg_positions & open_ids)
        if all(l["state"] in TERMINAL_LEG_STATES or l["state"] == "prepared" for l in legs) and not exposed:
            since = payload.get("terminal_since")
            if since is None:
                payload["terminal_since"] = now.isoformat()
            elif (now - datetime.fromisoformat(since)).total_seconds() >= self.SETTLE_SECONDS:
                payload["state"] = "closed"
        else:
            payload.pop("terminal_since", None)
            if any(l["state"] == "unknown" for l in legs):
                payload["state"] = "needs_reconciliation"
        self.journal.save(plan_id, payload)

    def cancel_remaining(self, plan_id: str, why: str, now: Optional[datetime] = None) -> Optional[dict]:
        """Remove only THIS basket's still-pending orders (own magic/comment/ticket); never closes a position or touches
        its broker SL/TP. Every attempt first reads the broker's CURRENT pending orders: a ticket is (re)removed only
        while it is verifiably still pending and owned, so an earlier unknown/timeout removal is retried safely and a
        removal that actually succeeded is never duplicated. payload["cancel_state"]:
          "complete" - a successful re-read shows no owned pending order left for this plan;
          "pending"  - owned pending orders remain (rejected/unknown removal): retry later;
          "unknown"  - the broker's pending orders could not be read (None): never assumed empty.
        A successful removal proves only that the REMAINDER is gone; legs are re-read from fresh evidence."""
        with self.lock:
            payload = self.journal.get(plan_id)
            mt5 = self.mt5
            if payload is None or mt5 is None:
                return payload
            self._check_owner(mt5.account_info(), payload)
            pending = mt5.orders_get(symbol=payload["symbol"])
            if pending is None:
                payload["cancel_state"] = "unknown"
                self.journal.save(plan_id, payload)
                return payload
            for leg in payload["legs"]:
                live = [x for x in pending if self._owned(x, payload, leg)]
                if not live:
                    continue  # nothing of this leg is pending now (filled/expired/removed): evidence decides below
                ticket = live[0].ticket
                leg["ticket"] = leg.get("ticket") or ticket
                try:
                    result = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket, "magic": MAGIC})
                except Exception:
                    result = None
                leg["cancel_attempts"] = int(leg.get("cancel_attempts", 0)) + 1
                if result is None or result.retcode in (mt5.TRADE_RETCODE_TIMEOUT, mt5.TRADE_RETCODE_CONNECTION):
                    leg["cancel"] = "unknown"
                elif result.retcode == mt5.TRADE_RETCODE_DONE:
                    leg["cancel"] = why  # remainder removed; the state comes from the evidence below
                else:
                    leg["cancel"] = f"rejected ({result.retcode})"
            self.journal.save(plan_id, payload)
            self._refresh(mt5, plan_id, payload, now or self._now())
            after = mt5.orders_get(symbol=payload["symbol"])
            if after is None:
                payload["cancel_state"] = "unknown"
            else:
                still = [x for x in after if any(self._owned(x, payload, leg) for leg in payload["legs"])]
                payload["cancel_state"] = "pending" if still else "complete"
            self.journal.save(plan_id, payload)
            return payload


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
