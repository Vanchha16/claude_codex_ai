"""FastAPI app for the local VC Signal dashboard. Loopback only; state-changing requests need the per-session token
and a same-origin request (no CORS is enabled, Host is checked to defeat DNS rebinding).

Data source: MT5 only (the user's running, logged-in terminal; read-only market data). A terminal that cannot connect
stays an honest disconnected/not-configured state; no fictional or sample data exists in the app.
Single owner: only the process holding .tmp/gold-signals/owner.lock runs the scanner and the Telegram sender.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import APP_ID
from .config import (DEMO_REMOVED, LOCAL_SETTINGS_FILE, PROJECT_ROOT, STATE_DIR, ConfigError, Settings, load_settings,
                     load_strategy, save_local_settings)
from .data.mt5 import MT5Feed
from .active_strategy import ActiveStrategy, fastsweep_version, is_fastsweep_version, load_active_strategy
from .delivery import Delivery, format_fvg_basket, format_signal
from .fvg_execution import (ExecutionJournal, ExecutionOptIn, ExecutionPolicy, MT5FvgExecutor, account_id, load_risk_usd)
from .fvg_live import FvgStore, basket_is_open
from .fvg_orders import ACCOUNT_UNITS_PER_USD
from .market import CHART_TIMEFRAMES, ChartUnavailable, validate_request
from .models import UTC, iso, parse_iso
from .owner import OwnerLock
from .scanner import Scanner
from .store import SqliteStore

STATIC = Path(__file__).resolve().parent / "static"
REPLAY_MAX_DAYS = 60
FVG_EXECUTION_FILE = PROJECT_ROOT / "config" / "fvg_execution.json"
FVG_RISK_FILE = PROJECT_ROOT / "config" / "fvg_risk.json"  # confirmed risk PREFERENCE only; never arms execution


def default_feed_factory(settings: Settings):
    return MT5Feed(settings.symbol, settings.mt5_terminal_path, settings.mt5_server_utc_offset_hours)


class Workstation:
    """Owns the active feed/store/scanner/delivery for the configured data source."""

    def __init__(self, settings: Settings, state_dir: Path = STATE_DIR, *,
                 feed_factory: Optional[Callable[[Settings], object]] = None,
                 settings_loader: Optional[Callable[[], Settings]] = None,
                 local_settings_path: Path = LOCAL_SETTINGS_FILE, delivery_client_factory=None,
                 active_strategy_loader: Callable[[], ActiveStrategy] = load_active_strategy):
        self.settings, self.state_dir = settings, state_dir
        self.active = active_strategy_loader()  # invalid selection -> fail clearly at startup
        # resolved at call time (tests replace the module default so they can never reach a real terminal)
        self.feed_factory, self.local_settings_path = feed_factory or default_feed_factory, local_settings_path
        self.settings_loader = settings_loader or (lambda: load_settings(local_path=local_settings_path))
        self.delivery_client_factory = delivery_client_factory
        self.cfg = load_strategy()
        self.lock = threading.RLock()
        self.scanner: Optional[Scanner] = None
        self.store: Optional[SqliteStore] = None
        self.delivery: Optional[Delivery] = None
        self.mode = settings.data_mode
        self.owner = OwnerLock(state_dir / "owner.lock")
        self.owner_error: Optional[str] = None
        self._delivery_stop = threading.Event()
        self._delivery_thread: Optional[threading.Thread] = None
        self.replay_running = False
        self.replay_error: Optional[str] = None
        self.fvg_store: Optional[FvgStore] = None
        self.fvg_journal: Optional[ExecutionJournal] = None
        self.fvg_risk_path = FVG_RISK_FILE
        self.fvg_optin = ExecutionOptIn(state_dir / "fvg_execution_optin.json")
        self.fvg_execution_path = FVG_EXECUTION_FILE
        self.fvg_user_off = state_dir / "fvg_execution_user_off.json"  # the user's explicit OFF beats the demo-ACCOUNT default

    def _db_path(self, mode: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", self.settings.symbol) or "no-symbol"
        return self.state_dir / f"mt5-{safe}.sqlite"  # history separated per live symbol

    def start(self, mode: Optional[str] = None) -> None:
        mode = mode or self.settings.data_mode
        if mode != "mt5":  # fail before stopping anything: no fictional source exists any more
            raise ValueError(DEMO_REMOVED if mode == "demo" else f"unsupported data source {mode!r}")
        with self.lock:
            self.stop()
            self.mode = mode
            if not self.owner.acquire():
                holder = self.owner.holder() or {}
                self.owner_error = (f"Another VC Signal process (PID {holder.get('pid', '?')}) already owns the scanner and "
                                    "Telegram sender. This process serves no scanner; stop the other one or use its URL.")
                return
            self.owner_error = None
            self.state_dir.mkdir(parents=True, exist_ok=True)
            feed = self.feed_factory(self.settings)
            self.store = SqliteStore(self._db_path(mode))
            self.store.set_meta("config", json.dumps(self.cfg.to_dict()))
            self.store.set_meta("active_strategy", json.dumps(self.active_view()))
            self.delivery = self._make_delivery()
            fvg_kw = {}
            if self.active.is_fvg:
                safe = re.sub(r"[^A-Za-z0-9._-]", "_", self.settings.symbol) or "no-symbol"
                self.fvg_store = FvgStore(self.state_dir / f"fvg-{safe}.sqlite")
                self.fvg_journal = ExecutionJournal(self.state_dir / f"fvg-execution-{safe}.sqlite")
                fvg_kw = {"fvg_store": self.fvg_store, "fvg_executor_fn": self._fvg_executor,
                          "fvg_maintenance_fn": self._fvg_maintenance, "fvg_account_fn": self._fvg_account,
                          "fvg_risk_fn": lambda: load_risk_usd(self.fvg_risk_path)}
            self.scanner = Scanner(self.settings, self.cfg, feed, self.store, self.delivery, active=self.active, **fvg_kw)
            feed.connect()
            self.scanner.start()
            self._delivery_stop.clear()
            self._delivery_thread = threading.Thread(target=self._deliver_loop, name="gold-delivery", daemon=True)
            self._delivery_thread.start()
            state = "ON (restored explicit opt-in)" if self.delivery.enabled else "OFF"
            label = f"LIVE MT5 ({self.settings.symbol or 'symbol not selected'})"
            self.store.add_event("app", f"VC Signal started: {label}; strategy {self.active_view()['version']}; "
                                        f"external delivery {state}")

    def active_view(self) -> dict:
        return self.active.describe(self.cfg.version)

    def strategy_view(self) -> dict:
        """Parameters of the ACTIVE strategy (CRT: config/strategy.json; FastSweep: its fixed profile)."""
        if self.active.is_fvg_dual:
            d = self.active.fvg_dual
            return {"version": d.version, "mode": "dual", "engine_versions": {e: d.engine_version(e) for e in d.engines},
                    "scopes": d.scopes(), **asdict(d.rules)}
        if self.active.is_fvg:
            return {"version": self.active.fvg.version, **asdict(self.active.fvg)}
        if self.active.is_fastsweep:
            return {"version": fastsweep_version(self.active.fastsweep), **asdict(self.active.fastsweep)}
        return self.cfg.to_dict()

    # ---------------------------------------------------------------- FVG execution (default OFF)
    def _mt5_module(self):
        """The ALREADY-connected MetaTrader5 module of the live feed (no initialize/login); None if unavailable."""
        feed = self.scanner.feed if self.scanner else None
        api = getattr(feed, "_api", None)
        if self.mode != "mt5" or api is None:
            return None
        try:
            return api()
        except Exception:
            return None

    def _mt5_lock(self):
        """The ONE lock that serialises every call into the shared MT5 session: the connected feed's own lock (also held
        by chart/REST reads through the feed). Executor and status calls use it too."""
        feed = self.scanner.feed if self.scanner else None
        lock = getattr(feed, "_lock", None)
        return lock if lock is not None else (self.scanner._feed_lock if self.scanner else threading.RLock())

    def _mt5_timebase(self):
        """The connected feed's time base: execution converts quote/expiry/history times exactly like the feed."""
        from .mt5_time import UTC_BASE
        feed = self.scanner.feed if self.scanner else None
        return getattr(feed, "timebase", None) or UTC_BASE

    def _fvg_binding(self, account) -> dict:
        # canonical server+login identity: legacy login-only opt-ins never match (fail closed, need new arming)
        return {"source": self.mode, "symbol": self.settings.symbol, "account": account_id(account),
                # the dual mode binds to its own version (new consent); plain v1 objects bind to the profile version
                "strategy_version": getattr(self.active, "fvg_version", None) or
                                    (self.active.fvg.version if self.active.is_fvg else None)}

    def _fvg_default_on_demo(self) -> bool:
        try:
            raw = json.loads(self.fvg_execution_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return False  # missing/invalid = no default
        return isinstance(raw, dict) and raw.get("default_on_for_demo_accounts") is True

    def _fvg_armed(self, account, mt5) -> tuple[bool, Optional[str], Optional[str]]:
        """(ON?, reason when OFF, how it is ON). Order of precedence (task 20261007-164056):
        1. the user's explicit OFF beats everything (also a stale/inconsistent saved opt-in) and persists;
        2. an exact saved binding (source/symbol/strategy version/server+login) - the only way for REAL/CONTEST;
        3. the configured category default for VERIFIED demo accounts (user's choice, any demo server+login);
        anything else - real, contest, unknown/unavailable account type - is OFF (fails closed)."""
        if self.fvg_user_off.exists():
            return False, "turned OFF by you", None
        if self.fvg_optin.matches(self._fvg_binding(account)):
            return True, None, "you"
        kind = {getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0): "demo", getattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST", 1): "contest",
                getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2): "real"}.get(getattr(account, "trade_mode", None), "unknown")
        if kind == "demo" and self._fvg_default_on_demo():
            return True, None, "default (demo account)"
        if kind == "real":
            return False, "real-money account: needs your explicit arming for this server+login", None
        if kind == "contest":
            return False, "contest account: needs your explicit arming for this server+login", None
        if kind == "unknown":
            return False, "account type unknown: not treated as demo; needs explicit arming", None
        return False, ("not armed" if self.fvg_optin.load() is None else
                       "opt-in does not match the current source/symbol/strategy/server+login"), None

    def _fvg_executor(self):
        """Called by the FVG engine (inside the scan, under the feed lock) for each newly accepted basket."""
        if not self.active.is_fvg or self.mode != "mt5":
            return None, "automatic execution needs FVG selected on the live MT5 source"
        risk = load_risk_usd(self.fvg_risk_path)
        if risk is None:
            return None, "risk not configured"
        lock = self._mt5_lock()
        with lock:
            mt5 = self._mt5_module()
            account = mt5.account_info() if mt5 is not None else None
        if account is None:
            return None, "MT5 account unavailable"
        binding = self._fvg_binding(account)
        armed, why, _ = self._fvg_armed(account, mt5)
        if not armed:
            return None, f"automatic execution OFF ({why})"
        policy = ExecutionPolicy(True, risk, account.login, "mt5", self.settings.symbol, binding["strategy_version"],
                                 account_server=getattr(account, "server", None))
        return MT5FvgExecutor(self._mt5_module, self.fvg_journal, policy, lock=lock, timebase_fn=self._mt5_timebase,
                              clock=lambda: datetime.now(UTC)), "ON"

    def _fvg_account(self) -> Optional[str]:
        """Canonical server+login identity of the connected account (never the login itself); None if unavailable."""
        if self.mode != "mt5":
            return None
        with self._mt5_lock():
            mt5 = self._mt5_module()
            account = mt5.account_info() if mt5 is not None else None
        return account_id(account) if account is not None else None

    def _fvg_maintenance(self):
        """Reconcile/cancel-only access for baskets already submitted (works while execution is OFF; never submits)."""
        if not self.active.is_fvg or self._mt5_module() is None or self.fvg_journal is None:
            return None
        return MT5FvgExecutor(self._mt5_module, self.fvg_journal, ExecutionPolicy(), lock=self._mt5_lock(),
                              timebase_fn=self._mt5_timebase)

    def fvg_status(self) -> dict:
        risk = load_risk_usd(self.fvg_risk_path)
        out = {"strategy_active": self.active.is_fvg, "auto_execution": "OFF", "reason": None, "risk_usd": risk,
               "risk_configured": risk is not None, "account_currency": None, "equity_usd": None,
               "risk_pct_of_equity": None, "armed_at": None, "armed_by": None,
               "default_on_for_demo_accounts": self._fvg_default_on_demo()}
        if not self.active.is_fvg:
            out["reason"] = "FVG is not the active strategy (inactive build)"
            return out
        out["strategy_version"] = self.active.fvg_version
        if self.active.is_fvg_dual:
            out["mode"] = "dual"
            out["risk_scope"] = "per basket"
            out["max_concurrent_risk_usd"] = None if risk is None else 2 * risk
            eng = self.scanner.engine if self.scanner else None
            if eng is not None and getattr(eng, "dual", False):
                try:
                    out["dual"] = eng.state_summary(self.scanner.feed.now())
                except Exception as exc:  # status must never fail because of a store read
                    out["dual_error"] = f"{type(exc).__name__}: {exc}"
        if self.mode != "mt5":
            out["reason"] = "automatic execution needs the live MT5 source"
            return out
        saved = self.fvg_optin.load()
        with self._mt5_lock():
            mt5 = self._mt5_module()
            account = mt5.account_info() if mt5 is not None else None
        if account is None:
            out["reason"] = "MT5 account unavailable"
            return out
        ccy = getattr(account, "currency", "")
        out["account_currency"] = ccy
        units = ACCOUNT_UNITS_PER_USD.get((ccy or "").upper())
        if units:
            out["equity_usd"] = round(account.equity / units, 2)
            if risk and account.equity > 0:
                out["risk_pct_of_equity"] = round(100 * risk / (account.equity / units), 2)
        out["account_type"] = {0: "demo", 1: "contest", 2: "real"}.get(getattr(account, "trade_mode", None), "unknown")
        armed, why, how = self._fvg_armed(account, mt5)
        if armed and how == "you" and saved:
            out["approval"] = saved.get("approval")
        if armed:
            out["auto_execution"] = "ON" if risk is not None else "OFF"
            out["armed_by"] = how
            out["armed_at"] = saved.get("armed_at") if how == "you" and saved else None
            out["reason"] = None if risk is not None else "risk not configured"
        else:
            out["reason"] = why
        return out

    def trading_status(self, fvg: Optional[dict] = None) -> str:
        """Truthful order capability for /api/state: CRT/FastSweep never send orders; FVG only when armed."""
        f = fvg if fvg is not None else self.fvg_status()
        if not self.active.is_fvg:
            return (f"disabled: {self.active_view().get('label') or self.active.kind} is alert-only with simulated outcomes "
                    "(no orders are sent); FVG automatic execution is OFF and FVG is not the active strategy")
        if f.get("auto_execution") == "ON" and self.active.is_fvg_dual:
            return (f"ENABLED: FVG dual automatic execution is ON - each engine (M15, M5) places 3 pending limit orders "
                    f"when its own FVG qualifies ({f.get('risk_usd')} USD planned SL risk per basket, at most one basket "
                    f"per engine = {2 * (f.get('risk_usd') or 0):g} USD concurrent) on this MT5 account")
        if f.get("auto_execution") == "ON":
            return (f"ENABLED: FVG automatic execution is ON - each new eligible FVG setup places 3 pending limit orders "
                    f"(fixed {f.get('risk_usd')} USD total planned SL risk) on this MT5 account")
        return f"disabled: FVG automatic execution is OFF ({f.get('reason') or 'not armed'}) - alerts only, no orders are sent"

    def fvg_arm(self, enabled: bool, approval: Optional[str] = None) -> dict:
        if not enabled:
            self.fvg_optin.disarm()  # stops NEW submissions; accepted orders keep their broker SL/TP
            self.fvg_user_off.parent.mkdir(parents=True, exist_ok=True)
            self.fvg_user_off.write_text(json.dumps({"turned_off_at": datetime.now(UTC).isoformat()}), encoding="utf-8")
            return self.fvg_status()
        if not self.active.is_fvg or self.mode != "mt5":
            raise ValueError("automatic execution can only be armed while FVG is the active strategy on live MT5")
        if load_risk_usd(self.fvg_risk_path) is None:
            raise ValueError("risk not configured (config/fvg_risk.json)")
        with self._mt5_lock():
            mt5 = self._mt5_module()
            account = mt5.account_info() if mt5 is not None else None
        if account is None:
            raise ValueError("MT5 account unavailable")
        if (getattr(account, "currency", "") or "").upper() not in ACCOUNT_UNITS_PER_USD:
            raise ValueError("account currency is not supported for the USD risk budget")
        if account.margin_mode != getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2):
            raise ValueError("three independent targets need a hedging account; netting is not supported")
        self.fvg_optin.arm(self._fvg_binding(account), datetime.now(UTC), approval=approval)
        try:
            self.fvg_user_off.unlink()
        except FileNotFoundError:
            pass
        return self.fvg_status()

    def _make_delivery(self) -> Delivery:
        kwargs = {}
        if self.delivery_client_factory:
            kwargs["client_factory"] = self.delivery_client_factory
        return Delivery(self.store, self.settings, source=self.mode,
                        symbol=self.settings.symbol if self.mode == "mt5" else "",
                        optin_path=self.state_dir / "delivery_optin.json", **kwargs)

    def reconfigure_delivery(self) -> None:
        """Telegram destination changed: rebuild the sender (re-checks/invalidates the persisted opt-in)."""
        with self.lock:
            if not self.scanner or not self.store:
                return
            if self.delivery:
                self.delivery.close()
            self.delivery = self._make_delivery()
            self.scanner.delivery = self.delivery
            self.scanner.settings = self.settings

    def _deliver_loop(self) -> None:
        while not self._delivery_stop.wait(1.0):
            try:
                if self.delivery:
                    self.delivery.process_due()
            except Exception as exc:
                if self.store:
                    self.store.add_event("error", self.settings.redact(f"delivery worker: {type(exc).__name__}: {exc}"), "error")

    def stop(self) -> None:
        with self.lock:
            self._delivery_stop.set()
            if self._delivery_thread:
                self._delivery_thread.join(5)
            if self.scanner:
                self.scanner.stop()
            if self.delivery:
                self.delivery.close()
            if self.store:
                self.store.close()
            if self.fvg_store:
                self.fvg_store.close()
            if self.fvg_journal:
                self.fvg_journal.close()
            self.scanner = self.store = self.delivery = None
            self.fvg_store = self.fvg_journal = None

    def shutdown(self) -> None:
        self.stop()
        self.owner.release()


def _record_strategy(version: str | None) -> dict:
    fs = is_fastsweep_version(version)
    return {"strategy": "FastSweep" if fs else "CRT-SMC-v1", "range_tf": "M15" if fs else "H1", "confirmation_tf": "M5"}


def _signal_dict(s) -> dict:
    return {**_record_strategy(s.config_version), "id": s.id, "mode": s.mode, "symbol": s.symbol, "direction": s.direction, "entry": s.entry, "sl": s.sl,
            "tp": s.tp, "reward_risk": s.reward_risk, "spread": s.spread, "bid": s.bid, "ask": s.ask,
            "quote_time": iso(s.quote_time), "confirm_close": iso(s.confirm_close), "created_at": iso(s.created_at),
            "valid_until": iso(s.valid_until), "config_version": s.config_version, "explanation": s.explanation,
            "outcome_status": s.outcome_status, "outcome_time": iso(s.outcome_time), "outcome_price": s.outcome_price,
            "outcome_r": s.outcome_r, "outcome_note": s.outcome_note, "candidate_key": s.candidate_key,
            "measurement_gaps": int(s.meta.get("measurement_gaps", 0)),
            "duration_minutes": None if not s.outcome_time else round((s.outcome_time - s.created_at).total_seconds() / 60, 1)}


def _cand_dict(c, cid=None) -> dict:
    return {**_record_strategy(c.config_version), "id": cid, "key": c.key, "direction": c.direction, "status": c.status, "reason": c.reason,
            "a_open": iso(c.a_open), "b_open": iso(c.b_open), "b_close": iso(c.b_close), "a_high": c.a_high,
            "a_low": c.a_low, "b_high": c.b_high, "b_low": c.b_low, "level": c.level, "pivot_time": iso(c.pivot_time),
            "pivot_available": iso(c.pivot_available), "deadline": iso(c.deadline), "confirm_close": iso(c.confirm_close),
            "warmup": c.warmup, "updated_at": iso(c.updated_at), "config_version": c.config_version, "mode": c.mode}


def create_app(settings: Optional[Settings] = None, *, state_dir: Path = STATE_DIR, autostart: bool = True,
               extra_hosts: tuple[str, ...] = (), feed_factory: Optional[Callable[[Settings], object]] = None,
               settings_loader: Optional[Callable[[], Settings]] = None,
               local_settings_path: Path = LOCAL_SETTINGS_FILE, delivery_client_factory=None,
               active_strategy_loader: Callable[[], ActiveStrategy] = load_active_strategy) -> FastAPI:
    settings = settings or (settings_loader() if settings_loader else load_settings(local_path=local_settings_path))
    ws = Workstation(settings, state_dir, feed_factory=feed_factory, settings_loader=settings_loader,
                     local_settings_path=local_settings_path, delivery_client_factory=delivery_client_factory,
                     active_strategy_loader=active_strategy_loader)
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(_app):
        if autostart:
            ws.start()  # MT5 only
        yield
        ws.shutdown()

    app = FastAPI(title="VC Signal", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.ws, app.state.token, app.state.port = ws, token, settings.port

    def allowed_hosts():
        p = app.state.port
        return {f"127.0.0.1:{p}", f"localhost:{p}", *extra_hosts}

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if host not in allowed_hosts():
            return JSONResponse({"error": "unexpected Host header"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin not in {f"http://{h}" for h in allowed_hosts()}:
                return JSONResponse({"error": "cross-origin request refused"}, status_code=403)
            if not secrets.compare_digest(request.headers.get("x-session-token", ""), token):
                return JSONResponse({"error": "missing or invalid session token"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index():
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        return html.replace("__SESSION_TOKEN__", token)

    @app.get("/api/health")
    def health():
        sc = ws.scanner
        return {"app": APP_ID, "pid": os.getpid(), "mode": ws.mode, "scanner_running": bool(sc and sc.running),
                "owner": ws.owner.held, "owner_error": ws.owner_error}

    def need_store():
        if ws.owner_error:
            raise HTTPException(503, ws.owner_error)
        if ws.store is None or ws.scanner is None:
            raise HTTPException(503, "VC Signal is restarting")
        return ws.store, ws.scanner

    def setup_view() -> dict:
        s = ws.settings
        feed_state = (ws.scanner.state.get("feed") if ws.scanner else None) or {}
        details = feed_state.get("details") or {}
        return {**s.public_status(), "candidates": details.get("candidates"),
                "account": details.get("account"), "legacy_utc_offset_hours": details.get("legacy_utc_offset_hours"),
                "time_base": details.get("time_base")}

    @app.get("/api/state")
    def state():
        if ws.owner_error:
            return {"mode": ws.mode, "owner_error": ws.owner_error, "setup": setup_view(), "strategy": ws.strategy_view(),
                    "active_strategy": ws.active_view(),
                    "trading": "disabled: this process is not the owner and never sends orders"}
        store, sc = need_store()
        feed = sc.feed
        meta = None
        try:
            meta = feed.meta().to_dict()
        except Exception:
            pass
        feed_state = sc.state["feed"] or {}
        fvg = ws.fvg_status()
        return {
            "mode": ws.mode,
            "data_label": "MetaTrader 5 terminal data (read-only)",
            "provider": (feed_state.get("details") or {}).get("provider") or "MetaTrader 5",
            "account": (feed_state.get("details") or {}).get("account"),
            "symbol": meta, "configured_symbol": ws.settings.symbol or None,
            "timeframes": ws.active_view()["timeframes"], "active_strategy": ws.active_view(),
            "scanner": {"running": sc.running, "paused": sc.paused, "last_scan": sc.state["last_scan"],
                        "error": sc.state["error"], "data_issues": sc.state["data_issues"],
                        "interval_seconds": ws.settings.scan_interval_seconds,
                        "live_start": store.get_meta("live_start"), "last_closed": sc.state.get("last_closed"),
                        "session_watermark": iso(sc.session_watermark)},
            "strategy_state": sc.strategy_state(),
            "feed": sc.state["feed"], "quote": sc.state["quote"],
            "telegram": ws.delivery.status() if ws.delivery else None,
            "strategy": ws.strategy_view(), "crt_strategy": ws.cfg.to_dict(), "setup": setup_view(),
            "fvg": fvg,
            "replay_running": ws.replay_running, "replay_error": ws.replay_error,
            "trading": ws.trading_status(fvg),
        }

    @app.get("/api/signals")
    def signals(direction: Optional[str] = None, outcome: Optional[str] = None, limit: int = 200):
        store, _ = need_store()
        return [_signal_dict(s) for s in store.list_signals(min(limit, 1000), direction, outcome)]

    @app.get("/api/candidates")
    def candidates(status: Optional[str] = None, direction: Optional[str] = None, limit: int = 200):
        store, _ = need_store()
        return [_cand_dict(c, store.candidate_id(c.key)) for c in store.list_candidates(min(limit, 1000), status, direction)]

    @app.get("/api/events")
    def events(limit: int = 100):
        store, _ = need_store()
        return store.list_events(min(limit, 500))

    @app.get("/api/outbox")
    def outbox():
        store, _ = need_store()
        rows = store.outbox_rows()
        for r in rows:
            r.pop("text", None)
        return rows

    @app.get("/api/signals/{sid}/message")
    def message_preview(sid: str):
        store, _ = need_store()
        s = store.get_signal(sid)
        if not s:
            raise HTTPException(404, "unknown signal")
        return {"text": format_signal(s), "note": "Local preview. Sent only when Telegram is configured and delivery is enabled."}

    @app.get("/api/chart")
    def chart(candidate_id: Optional[int] = None, signal_id: Optional[str] = None):
        """Backend records for a selected setup/signal (overlay prices and times come from these records)."""
        store, sc = need_store()
        sig = store.get_signal(signal_id) if signal_id else None
        c = store.candidate_by_id(candidate_id) if candidate_id else (store.get_candidate(sig.candidate_key) if sig else None)
        if c is None:
            raise HTTPException(404, "unknown candidate")
        if sig is None:
            sig = next((s for s in store.list_signals(1000) if s.candidate_key == c.key), None)
        start = c.a_open - timedelta(hours=1)
        end = (sig.outcome_time if sig and sig.outcome_time else (c.deadline or c.b_close)) + timedelta(minutes=30)
        return {"candidate": _cand_dict(c, store.candidate_id(c.key)), "signal": _signal_dict(sig) if sig else None,
                "mode": ws.mode, "window": {"start": iso(start), "end": iso(end)}}

    @app.get("/api/market/bars")
    def market_bars(tf: str = "M5", count: int = 300, before: Optional[str] = None):
        """Chart-only candles (display). Closed bars + a separately flagged forming bar. Never used by the strategy."""
        _, sc = need_store()
        try:
            before_dt = parse_iso(before) if before else None
            tf, count = validate_request(tf, count, before_dt)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        feed = sc.feed
        base = {"tf": tf, "source": ws.mode, "symbol": ws.settings.symbol or None, "server_time": iso(feed.now())}
        try:
            meta = feed.meta()
            base.update(symbol=meta.name, digits=meta.digits, tick_size=meta.tick_size)
        except Exception:
            pass
        try:
            with sc._feed_lock:
                if ws.mode == "mt5" and not feed.status().ok:
                    return {**base, "available": False, "reason": (sc.state.get("feed") or {}).get("message", "MT5 not connected"),
                            "bars": [], "forming": None}
                bars, forming = feed.chart_bars(tf, count, before_dt)
        except ChartUnavailable as exc:
            return {**base, "available": False, "reason": str(exc), "bars": [], "forming": None}
        except Exception as exc:
            return {**base, "available": False, "reason": ws.settings.redact(f"{type(exc).__name__}: {exc}"), "bars": [], "forming": None}
        reason = None if bars or forming else ("no older history returned" if before_dt else "no history returned")
        return {**base, "available": bool(bars or forming), "reason": reason,
                "bars": [b.to_dict() for b in bars], "forming": forming.to_dict() if forming else None}

    @app.get("/api/setup")
    def get_setup():
        return {**setup_view(), "chart_timeframes": list(CHART_TIMEFRAMES), "owner_error": ws.owner_error}

    @app.post("/api/setup")
    async def post_setup(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "send a JSON object")
        locked = [k for k in body if ws.settings.env_locked(k)]
        if locked:
            raise HTTPException(400, f"{', '.join(locked)} is set in the process environment and cannot be changed here")
        before = ws.settings
        try:
            save_local_settings(body, ws.local_settings_path)
            new = ws.settings_loader()
        except ConfigError as exc:
            raise HTTPException(400, str(exc))
        ws.settings = new
        restart_keys = ("data_mode", "symbol", "mt5_terminal_path")
        if any(getattr(before, k) != getattr(new, k) for k in restart_keys):
            # new source/symbol: a NEW scanner session (fresh watermark); history stays in its own per-symbol database
            ws.start(new.data_mode)
            action = "restarted with a new scanner session"
        elif before.telegram_test_chat_id != new.telegram_test_chat_id:
            ws.reconfigure_delivery()
            action = "Telegram destination updated (live delivery opt-in re-checked)"
        else:
            if ws.scanner:
                ws.scanner.settings = new
            action = "saved"
        return {"saved": True, "action": action, "setup": setup_view()}

    @app.get("/api/mt5/discover")
    def mt5_discover():
        """Gold-like symbols in the user's terminal; the user must pick one explicitly."""
        if ws.mode == "mt5" and ws.scanner:
            feed = ws.scanner.feed
            with ws.scanner._feed_lock:
                st = feed.status()
                if st.state in ("disconnected", "error"):
                    st = feed.connect()
                if st.state in ("disconnected", "error"):
                    raise HTTPException(503, f"MT5 not connected: {st.message}")
                try:
                    return {"candidates": feed.discover_gold(), "account": feed.account_context()}
                except Exception as exc:
                    raise HTTPException(503, f"MT5 unavailable: {exc}")
        probe = ws.feed_factory(Settings(mt5_terminal_path=ws.settings.mt5_terminal_path))
        st = probe.connect()
        try:
            if st.state in ("disconnected", "error"):
                raise HTTPException(503, st.message)
            return {"candidates": probe.discover_gold(), "account": probe.account_context()}
        finally:
            probe.shutdown()

    @app.get("/api/mt5/symbols")
    def mt5_symbols(pattern: str = "*XAU*"):
        if ws.mode == "mt5" and ws.scanner:
            feed = ws.scanner.feed
            with ws.scanner._feed_lock:
                if not feed.status().ok:
                    feed.connect()
                try:
                    return {"symbols": feed.list_symbols(pattern)}
                except Exception as exc:
                    raise HTTPException(503, f"MT5 unavailable: {exc}")
        probe = ws.feed_factory(Settings(mt5_terminal_path=ws.settings.mt5_terminal_path))
        st = probe.connect()
        try:
            if st.state in ("disconnected", "error"):
                raise HTTPException(503, st.message)
            return {"symbols": probe.list_symbols(pattern)}
        finally:
            probe.shutdown()

    @app.get("/api/replay")
    def replay_result(source: str = "mt5", strategy: str = "crt"):
        if source not in ("mt5", "csv"):
            raise HTTPException(400, "source must be mt5 or csv (the fictional demo source was removed)")
        if strategy not in ("crt", "fastsweep"):
            raise HTTPException(400, "strategy must be crt or fastsweep")
        if strategy == "fastsweep":
            path = ws.state_dir / "replays" / f"latest-{source}-fastsweep.json"
            if not path.exists():
                return {"available": False, "strategy": "fastsweep",
                        "hint": "Run a FastSweep replay on real MT5 history (OHLC simulation; it never touches live records)."}
            return {"available": True, "strategy": "fastsweep", "result": json.loads(path.read_text(encoding="utf-8"))}
        path = ws.state_dir / "replays" / f"latest-{source}.json"
        if not path.exists():
            hint = ("Run a replay on the selected MT5 symbol (Replay → Run real replay) once MT5 is connected."
                    if source == "mt5" else "Run a replay with the button.")
            return {"available": False, "hint": hint}
        return {"available": True, "result": json.loads(path.read_text(encoding="utf-8"))}

    @app.post("/api/replay/run")
    async def replay_run(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        source = (body or {}).get("source", "mt5")
        days = int((body or {}).get("days", REPLAY_MAX_DAYS))
        use_ticks = bool((body or {}).get("use_ticks", False))
        strategy = (body or {}).get("strategy", "crt")
        profile = (body or {}).get("profile") or (ws.active.profile if ws.active.is_fastsweep else "rr2")
        if source != "mt5":
            raise HTTPException(400, "source must be mt5 (the fictional demo source was removed)")
        if strategy not in ("crt", "fastsweep"):
            raise HTTPException(400, "strategy must be crt or fastsweep")
        if strategy == "fastsweep":
            from .fastsweep import PROFILES
            if profile not in PROFILES:
                raise HTTPException(400, "profile must be rr1 or rr2")
        if not 1 <= days <= REPLAY_MAX_DAYS:
            raise HTTPException(400, f"days must be 1-{REPLAY_MAX_DAYS}")
        if ws.replay_running:
            raise HTTPException(409, "a replay is already running")
        _, sc = need_store()
        if not (sc.state.get("feed") or {}).get("ok"):
            raise HTTPException(400, "Replay needs MT5 connected with an exact symbol selected")

        def work():
            ws.replay_running, ws.replay_error = True, None
            try:
                if strategy == "fastsweep":
                    _fastsweep_replay(days, profile)
                else:
                    from .replay import replay_from_feed
                    result = replay_from_feed(ws.scanner.feed, ws.cfg, days=days, use_ticks=use_ticks,
                                              spread=ws.settings.replay_spread_price,
                                              slippage=ws.settings.replay_slippage_price,
                                              holdout_fraction=ws.settings.holdout_fraction)
                    out = ws.state_dir / "replays"
                    out.mkdir(parents=True, exist_ok=True)
                    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
                    for path in (out / f"replay-mt5-{stamp}.json", out / "latest-mt5.json"):
                        tmp = path.with_suffix(".tmp")
                        tmp.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
                        os.replace(tmp, path)
            except Exception as exc:
                ws.replay_error = ws.settings.redact(f"{type(exc).__name__}: {exc}")
            finally:
                ws.replay_running = False
        threading.Thread(target=work, daemon=True).start()
        return {"started": True, "source": source, "days": days, "strategy": strategy,
                "profile": profile if strategy == "fastsweep" else None}

    def _fastsweep_replay(days: int, profile: str) -> None:
        """Isolated OHLC replay of FastSweep on the live feed's M5 history (read under the scanner's feed lock, no second
        MT5 session); an in-memory engine, so live candidates/signals/outbox are never touched."""
        from .fastsweep import PROFILES
        from .fastsweep_replay import Costs, frequency, replay as fs_replay
        sc = ws.scanner
        with sc._feed_lock:
            meta = sc.feed.meta()
            end = sc.feed.now()
            m5 = [b for b in sc.feed.bars_range("M5", end - timedelta(days=days), end) if b.close_time <= end]
        if not m5:
            raise ValueError("no closed M5 history returned")
        res = fs_replay(m5, meta, PROFILES[profile], Costs(ws.settings.replay_spread_price, ws.settings.replay_slippage_price),
                        holdout_fraction=ws.settings.holdout_fraction)
        res["frequency"] = frequency(res["daily"])
        res["requested_days"] = days
        res["data_label"] = (f"MT5 {meta.name}, requested last {days} days; returned {len(m5)} M5 bars from "
                             f"{iso(m5[0].open_time)} to {iso(m5[-1].close_time)} (read-only, OHLC simulation)")
        res.pop("candidates", None)  # keep the dashboard payload small; signals and the daily table are kept
        out = ws.state_dir / "replays"
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        for path in (out / f"replay-mt5-fastsweep-{profile}-{stamp}.json", out / "latest-mt5-fastsweep.json"):
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(res, indent=1), encoding="utf-8")
            os.replace(tmp, path)

    @app.get("/api/fvg")
    def fvg_view(limit: int = 50, engine: Optional[str] = None):
        """engine (optional): "M15" | "M5" | "legacy" - partitioned by STORED provenance (engine + engine version)
        BEFORE the limit, so one engine's history never crowds out the other's. Without it: all baskets (unchanged)."""
        if engine not in (None, "M15", "M5", "legacy"):
            raise HTTPException(400, "engine must be M15, M5 or legacy")
        status = ws.fvg_status()
        if not ws.active.is_fvg or ws.fvg_store is None:
            return {"status": status, "baskets": [], "setups": []}
        now = ws.scanner.feed.now() if ws.scanner else datetime.now(UTC)
        limit = max(1, min(limit, 500))
        if engine is None:
            baskets = ws.fvg_store.baskets(limit=limit)
        else:
            def mine(b):
                e, v = b.get("engine"), str(b.get("version") or "")
                if engine == "legacy":
                    return not (e in ("M15", "M5") and v.startswith(f"FVG-Immediate-{e}-"))
                return e == engine and v.startswith(f"FVG-Immediate-{engine}-")
            baskets = [b for b in ws.fvg_store.baskets(limit=100000) if mine(b)][:limit]
        sent = ws.store.outbox_for([b["id"] for b in baskets], "fvg_basket") if ws.store else {}
        for b in baskets:
            b["open"] = basket_is_open(b, now)
            b["preview"] = format_fvg_basket(b)
            row = sent.get(b["id"])
            # this basket's OWN Telegram state and its exact queued text (no secrets, no error details)
            b["delivery"] = None if row is None else {"status": row["status"], "attempts": row["attempts"],
                                                      "updated_at": row["updated_at"], "valid_until": row["valid_until"]}
            b["message"] = ({"source": "queued", "text": row["text"]} if row is not None else
                            {"source": "preview", "text": b["preview"]})
        setups = [{"key": x.key, "direction": x.direction, "bottom": x.bottom, "top": x.top, "c_close": iso(x.c_close),
                   "expires": iso(x.expires), "status": x.status, "reason": x.reason, "retest_close": iso(x.retest_close),
                   "level": x.level, "confirm_close": iso(x.confirm_close), "engine": (x.meta or {}).get("engine"),
                   "basket": (x.meta or {}).get("basket")} for x in ws.fvg_store.list_setups(min(limit, 500))]
        return {"status": status, "baskets": baskets, "setups": setups}

    @app.get("/api/fvg/guide")
    def fvg_guide(key: Optional[str] = None, limit: int = 30):
        """READ-ONLY FVG Guide data: recorded setups, the selected one's step evidence and a bounded candle window.
        Never creates/changes setups or baskets and never calls a broker (candles come from the feed's history)."""
        from . import fvg_guide as guide
        from .fvg import PROFILES
        status = ws.fvg_status()
        cfg = ws.active.fvg if ws.active.is_fvg else PROFILES["rr2"]
        dual = ws.active.fvg_dual if ws.active.is_fvg_dual else None
        current = ({dual.version, *(dual.engine_version(e) for e in dual.engines)} if dual else {cfg.version})
        sc = ws.scanner
        now = sc.feed.now() if sc else datetime.now(UTC)
        feed_state = (sc.state.get("feed") if sc else None) or {}
        quote = (sc.state.get("quote") if sc else None) or {}
        out = {"now": iso(now), "status": status, "fvg_active": bool(ws.active.is_fvg), "mode": ws.mode,
               "strategy_mode": "dual" if dual else ("legacy_v1" if ws.active.is_fvg else None),
               "display_timezone": ws.settings.display_timezone, "config": guide.config_view(cfg),
               "scopes": dual.scopes() if dual else None,
               "feed_ok": bool(feed_state.get("ok")), "quote_fresh": bool(quote.get("fresh")),
               "scanner_paused": bool(sc and sc.paused), "records": [], "selected": None}
        if not ws.active.is_fvg or ws.fvg_store is None:
            out["message"] = "FVG is not the active strategy, so there are no live FVG records to explain."
            return out
        setups = ws.fvg_store.list_setups(min(max(limit, 1), 200))
        if key:
            # an EXPLICIT key is resolved directly from storage (never limited to the recent selector window) and is
            # never substituted: a missing record is reported as missing
            chosen = ws.fvg_store.get_setup(key)
            if chosen is None:
                out["records"] = [guide.record_dict(s, current) for s in setups]
                out["missing_key"] = key
                out["message"] = "The requested setup was not found in this store; no other setup is shown in its place."
                return out
            if all(s.key != chosen.key for s in setups):
                setups = [chosen] + setups  # keep the selected record in the selector, once
        elif not setups:
            out["message"] = "No FVG setups have been recorded yet."
            return out
        else:
            chosen = next((s for s in setups if s.status in ("pending", "retested", "qualified")), setups[0])
        out["records"] = [guide.record_dict(s, current) for s in setups]
        basket = ws.fvg_store.basket_for_setup(chosen.key)  # the stored relationship, not a recency window
        is_dual = guide.is_dual_record(chosen)
        m5 = []
        try:
            meta = sc.feed.meta() if sc else None
        except Exception:
            meta = None  # never invent tick size/digits: the guide then says the preview is unavailable
        if sc and feed_state.get("ok"):
            end_at = chosen.c_close + timedelta(hours=2) if is_dual else chosen.expires
            if basket and basket.get("pending_expires"):
                end_at = max(end_at, parse_iso(basket["pending_expires"]))
            start, end = chosen.a_open - timedelta(minutes=15), min(now, end_at)
            if end - start <= timedelta(hours=6) and end > start:
                try:
                    with sc._feed_lock:
                        m5 = sc.feed.bars_range("M5", start, end)
                except Exception:
                    m5 = []
        out["selected"] = (guide.dual_record_view(chosen, basket, m5, cfg, meta, now, current,
                                                  dict(dual.stop_policy) if dual else None) if is_dual else
                           guide.record_view(chosen, basket, m5, cfg, meta, now))
        return out

    @app.post("/api/fvg/execution")
    async def fvg_execution(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        enabled = bool((body or {}).get("enabled"))
        if enabled and (body or {}).get("confirm") is not True:
            raise HTTPException(400, "arming automatic execution needs an explicit confirm: true")
        approval = (body or {}).get("approval")  # optional note: which user approval this consent records
        approval = str(approval)[:300] if approval else None
        try:
            status = ws.fvg_arm(enabled, approval=approval)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if ws.store:
            ws.store.add_event("fvg", f"automatic FVG execution {'ARMED' if enabled else 'disarmed'} by the user")
        return status

    @app.get("/api/tools")
    def tools():
        """Link to the separate agent-to-agent task panel, if its launcher recorded a loopback URL (read-only)."""
        url = None
        try:
            rec = json.loads((PROJECT_ROOT / ".tmp" / "task-panel" / "server.json").read_text(encoding="utf-8"))
            candidate = str(rec.get("url", ""))
            if candidate.startswith(("http://127.0.0.1:", "http://localhost:")):
                url = candidate
        except (OSError, ValueError):
            pass
        return {"task_panel": url}

    @app.post("/api/scanner/{action}")
    def scanner_action(action: str):
        _, sc = need_store()
        if action not in ("pause", "resume"):
            raise HTTPException(404, "unknown action")
        try:
            sc.pause() if action == "pause" else sc.resume()
        except Exception as exc:
            raise HTTPException(503, ws.settings.redact(f"{action} failed: {type(exc).__name__}: {exc}"))
        return {"paused": sc.paused}

    @app.post("/api/telegram/enabled")
    async def telegram_enabled(request: Request):
        body = await request.json()
        if not isinstance(body.get("enabled"), bool):
            raise HTTPException(400, "send {enabled: true|false}")
        need_store()
        try:
            ws.delivery.set_enabled(body["enabled"])
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return ws.delivery.status()

    @app.post("/api/telegram/test")
    def telegram_test():
        need_store()
        try:
            ws.delivery.queue_test_message()
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"queued": True, "note": "A labeled TEST MESSAGE will be sent to the configured test chat within ~1 s."}

    @app.post("/api/telegram/verify")
    def telegram_verify():
        """Read-only getMe/getChat; never sends a message."""
        need_store()
        try:
            return ws.delivery.verify()
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/admin/shutdown")
    def shutdown():
        def later():
            import time
            time.sleep(0.3)
            ws.shutdown()
            os._exit(0)
        threading.Thread(target=later, daemon=True).start()
        return {"stopping": True}

    return app
