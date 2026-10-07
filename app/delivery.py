"""Telegram delivery for the TEST group via Bot API sendMessage, with a durable SQLite outbox.

Telegram sendMessage has no idempotency key, so exactly-once delivery is impossible:
- definite transient failures (connection refused before the request, HTTP 429) are retried while still timely;
- ambiguous outcomes (timeouts after sending, 5xx, crash mid-send) become UNKNOWN and are never resent blindly;
- definite errors (4xx) become FAILED; anything past its validity window becomes EXPIRED.
The bot token never appears in logs, errors, the UI or the database.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import httpx

from .config import Settings
from .engine import Signal
from .models import UTC, iso, parse_iso
from .store import SqliteStore

MAX_ATTEMPTS = 4


def _fmt(px: float, digits: int) -> str:
    return f"{px:.{digits}f}"


def format_signal(sig: Signal) -> str:
    """Telegram signal body: exactly four emoji-labelled lines - Entry, TP, SL, RR - in that order (user requirements, 2026-10-05).
    Prices use the symbol's digits; RR uses two decimals. Same for BUY/SELL and live/demo; the signal data is unchanged."""
    digits = int(sig.meta.get("symbol", {}).get("digits", 2))
    return "\n".join([
        f"📍 Entry: {_fmt(sig.entry, digits)}",
        f"🎯 TP: {_fmt(sig.tp, digits)}",
        f"🛑 SL: {_fmt(sig.sl, digits)}",
        f"⚖️ RR: {sig.reward_risk:.2f}",
    ])


FVG_LEG_LABELS = ("1️⃣ First entry", "2️⃣ Second entry", "3️⃣ Third entry")


def format_fvg_basket(basket: dict) -> str:
    """Per planned limit leg: a First/Second/Third entry label, then the user's four Entry/TP/SL/RR lines. A blank line
    after every line and two between legs (user requests 2026-10-07)."""
    digits = int((basket.get("meta") or {}).get("digits", 2))
    blocks = []
    for i, leg in enumerate(basket["legs"]):
        blocks.append("\n\n".join([
            FVG_LEG_LABELS[i] if i < len(FVG_LEG_LABELS) else f"Entry {i + 1}",
            f"📍 Entry: {_fmt(leg['entry'], digits)}",
            f"🎯 TP: {_fmt(leg['tp'], digits)}",
            f"🛑 SL: {_fmt(leg['sl'], digits)}",
            f"⚖️ RR: {leg['rr']:.2f}",
        ]))
    return "\n\n\n".join(blocks)


def format_test_message(now: datetime) -> str:
    return (f"TEST MESSAGE - connectivity check from VC Signal (local gold signal dashboard) at {now:%Y-%m-%d %H:%M:%S} UTC.\n"
            "This is not a trading signal.")


@dataclass
class SendResult:
    kind: str  # ok | retry | failed | ambiguous
    message_id: Optional[int] = None
    retry_after: Optional[float] = None
    error: Optional[str] = None


class TelegramClient:
    API = "https://api.telegram.org"

    def __init__(self, token: str, transport: Optional[httpx.BaseTransport] = None, timeout: float = 10.0):
        self._token = token
        self._client = httpx.Client(transport=transport, timeout=timeout)

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "<redacted-token>") if self._token else text

    def send(self, chat_id: str, text: str) -> SendResult:
        url = f"{self.API}/bot{self._token}/sendMessage"
        try:
            r = self._client.post(url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True})
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            return SendResult("retry", error=self._redact(f"connection not established: {type(exc).__name__}"))
        except httpx.HTTPError as exc:  # read/write timeouts etc.: the message may or may not have been delivered
            return SendResult("ambiguous", error=self._redact(f"outcome unknown: {type(exc).__name__}"))
        try:
            body = r.json()
        except ValueError:
            body = {}
        desc = self._redact(str(body.get("description", "")))[:300]
        if r.status_code == 200 and body.get("ok"):
            return SendResult("ok", message_id=body.get("result", {}).get("message_id"))
        if r.status_code == 429:
            after = (body.get("parameters") or {}).get("retry_after", 5)
            return SendResult("retry", retry_after=float(after), error=f"rate limited (429): {desc}")
        if r.status_code >= 500:
            return SendResult("ambiguous", error=f"server error {r.status_code}: {desc}")
        return SendResult("failed", error=f"HTTP {r.status_code}: {desc}")

    def _get(self, method: str, params: Optional[dict] = None) -> dict:
        """Read-only Bot API call (getMe/getChat). Returns {'ok': bool, 'result' | 'error'} with secrets redacted."""
        try:
            r = self._client.get(f"{self.API}/bot{self._token}/{method}", params=params or {})
        except httpx.HTTPError as exc:
            return {"ok": False, "error": self._redact(f"{method}: {type(exc).__name__}")}
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code == 200 and body.get("ok"):
            return {"ok": True, "result": body.get("result") or {}}
        return {"ok": False, "error": self._redact(f"{method}: HTTP {r.status_code}: {body.get('description', '')}")[:300]}

    def get_me(self) -> dict:
        return self._get("getMe")

    def get_chat(self, chat_id: str) -> dict:
        return self._get("getChat", {"chat_id": chat_id})

    def close(self) -> None:
        self._client.close()


class Delivery:
    """Owns the outbox for one store. External sending happens only when `enabled` is explicitly switched on."""

    def __init__(self, store: SqliteStore, settings: Settings,
                 client_factory: Optional[Callable[[str], TelegramClient]] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC), *,
                 source: str = "demo", symbol: str = "", optin_path: Optional[Path] = None):
        self.store, self.settings, self.clock = store, settings, clock
        self._factory = client_factory or (lambda token: TelegramClient(token))
        self._client: Optional[TelegramClient] = None
        self.source, self.symbol, self.optin_path = source, symbol, optin_path
        self.enabled = False  # OFF unless a valid explicit live opt-in is restored below
        self.verified: Optional[dict] = None
        self.optin_note: Optional[str] = None
        self._lock = threading.Lock()
        recovered = store.recover_inflight()
        if recovered:
            store.add_event("delivery", f"{recovered} message(s) were mid-send when the app stopped; marked UNKNOWN (not resent)", "warning")
        self._restore_optin()

    # ---- persisted live opt-in (only ever created by the user's explicit enable action)
    def binding(self) -> dict:
        return {"source": self.source, "symbol": self.symbol, "bot": self.settings.token_fingerprint,
                "chat": self.settings.telegram_test_chat_id}

    def _restore_optin(self) -> None:
        if not self.optin_path or not self.optin_path.exists():
            return
        try:
            saved = json.loads(self.optin_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        current = self.binding()
        if self.source == "mt5" and self.configured and self.symbol and saved.get("binding") == current:
            self.enabled = True
            self.optin_note = f"restored the explicit opt-in from {saved.get('enabled_at')}"
            self.store.add_event("delivery", f"external delivery restored: {self.optin_note} (new signals only)")
            return
        if self.source != "mt5":
            return  # the live opt-in is untouched while a demo session runs; it is re-checked when live starts
        changed = [k for k in current if (saved.get("binding") or {}).get(k) != current[k]]
        self._drop_optin(f"opt-in invalidated because {', '.join(changed) or 'it was unreadable'} changed; re-enable to continue")

    def _drop_optin(self, why: str) -> None:
        try:
            if self.optin_path and self.optin_path.exists():
                self.optin_path.unlink()
        except OSError:
            pass
        self.optin_note = why
        self.store.add_event("delivery", why, "warning")

    def _save_optin(self) -> None:
        if not self.optin_path:
            return
        self.optin_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.optin_path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"binding": self.binding(), "enabled_at": iso(self.clock())}), encoding="utf-8")
        os.replace(tmp, self.optin_path)

    @property
    def configured(self) -> bool:
        return self.settings.telegram_configured

    def status(self) -> dict:
        missing = [n for n, v in (("bot token", self.settings.telegram_bot_token),
                                  ("destination chat ID", self.settings.telegram_test_chat_id)) if not v]
        return {"configured": self.configured, "enabled": self.enabled, "missing": missing,
                "state": "enabled" if self.enabled else ("disabled" if self.configured else "not configured"),
                "persisted": bool(self.enabled and self.source == "mt5"), "note": self.optin_note,
                "verified": self.verified, "mode": self.source}

    def set_enabled(self, value: bool) -> None:
        if value and not self.configured:
            raise ValueError("Telegram is not configured: add the destination chat ID in Setup (the bot token is read "
                             "server-side from .venv/.env or .env)")
        if value and self.source == "mt5" and not self.symbol:
            raise ValueError("Choose the exact MT5 symbol before enabling live delivery")
        self.enabled = bool(value)
        if self.source == "mt5":
            if value:
                self._save_optin()
                self.optin_note = "explicit opt-in saved for this source, symbol, bot and destination"
            else:
                self._drop_optin("external delivery disabled by the user")
        self.store.add_event("delivery", f"external Telegram delivery {'ENABLED' if value else 'disabled'}")

    def verify(self) -> dict:
        """Read-only getMe + getChat. Never sends a message; errors are sanitised."""
        if not self.settings.telegram_bot_token:
            raise ValueError("No bot token configured (GOLD_TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN)")
        if not self.settings.telegram_test_chat_id:
            raise ValueError("Add the destination chat ID in Setup first")
        client = self._client_for_send()
        me, chat = client.get_me(), client.get_chat(self.settings.telegram_test_chat_id)
        out = {"checked_at": iso(self.clock()), "bot_ok": me["ok"], "chat_ok": chat["ok"]}
        if me["ok"]:
            out["bot"] = {"username": me["result"].get("username"), "id": me["result"].get("id")}
        else:
            out["bot_error"] = self.settings.redact(me["error"])
        if chat["ok"]:
            r = chat["result"]
            out["chat"] = {"id": r.get("id"), "type": r.get("type"), "title": r.get("title") or r.get("username")}
        else:
            out["chat_error"] = self.settings.redact(chat["error"])
        self.verified = out
        return out

    def on_signal(self, sig: Signal) -> bool:
        """Queue a confirmed signal for the test group (only when enabled and configured)."""
        if not (self.enabled and self.configured):
            return False
        return self.store.enqueue(sig.id, "signal", format_signal(sig), sig.valid_until, self.clock())

    def on_fvg_basket(self, basket: dict) -> bool:
        """Queue a newly accepted FVG basket's three planned limits (only when enabled and configured). The alert reports
        the plan; it is never the order-submission trigger."""
        if not (self.enabled and self.configured):
            return False
        valid = parse_iso(basket["placed_at"]) + timedelta(seconds=120)
        return self.store.enqueue(basket["id"], "fvg_basket", format_fvg_basket(basket), valid, self.clock())

    def queue_test_message(self) -> None:
        if not self.configured:
            raise ValueError("Telegram is not configured")
        now = self.clock()
        self.store.enqueue(None, f"test-{now:%Y%m%d%H%M%S%f}", format_test_message(now), now + timedelta(seconds=60), now)

    def _client_for_send(self) -> TelegramClient:
        if self._client is None:
            self._client = self._factory(self.settings.telegram_bot_token)
        return self._client

    def process_due(self) -> int:
        """Send due outbox rows. Test messages are explicit user actions and go out even if signal delivery is off."""
        sent = 0
        with self._lock:
            now = self.clock()
            for row in self.store.due_outbox(now):
                is_test = row["kind"].startswith("test-")
                if not is_test and not (self.enabled and self.configured):
                    continue  # stays pending; expires below if it goes stale
                if row["valid_until"] and now > datetime.fromisoformat(row["valid_until"].replace("Z", "+00:00")):
                    self.store.update_outbox(row["id"], status="expired", last_error="signal no longer timely; not sent")
                    continue
                self.store.update_outbox(row["id"], status="sending", attempts=row["attempts"] + 1)
                result = self._client_for_send().send(self.settings.telegram_test_chat_id, row["text"])
                error = self.settings.redact(result.error or "") or None
                if result.kind == "ok":
                    self.store.update_outbox(row["id"], status="sent", telegram_message_id=result.message_id, last_error=None)
                    sent += 1
                elif result.kind == "retry" and row["attempts"] + 1 < MAX_ATTEMPTS:
                    delay = result.retry_after if result.retry_after is not None else 2 ** (row["attempts"] + 1)
                    self.store.update_outbox(row["id"], status="pending", next_attempt_at=now + timedelta(seconds=delay), last_error=error)
                elif result.kind == "ambiguous":
                    self.store.update_outbox(row["id"], status="unknown", last_error=error)
                else:
                    self.store.update_outbox(row["id"], status="failed", last_error=error)
                if result.kind != "ok":
                    self.store.add_event("delivery", f"outbox #{row['id']}: {result.kind} ({error})", "warning")
            # stale rows that were waiting while delivery was off
            for row in self.store.due_outbox(now):
                if row["valid_until"] and now > datetime.fromisoformat(row["valid_until"].replace("Z", "+00:00")):
                    self.store.update_outbox(row["id"], status="expired", last_error="signal no longer timely; not sent")
        return sent

    def close(self) -> None:
        if self._client:
            self._client.close()
