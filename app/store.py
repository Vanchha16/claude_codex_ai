"""Persistence: an in-memory store for replay/tests and a SQLite store for the live workstation."""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .engine import PENDING, Candidate, Signal
from .models import UTC, iso, parse_iso

_CAND_FIELDS = [f.name for f in fields(Candidate)]
_SIG_FIELDS = [f.name for f in fields(Signal)]


def _now() -> datetime:
    return datetime.now(UTC)


class MemoryStore:
    def __init__(self) -> None:
        self.candidates: dict[str, Candidate] = {}
        self.signals: dict[str, Signal] = {}
        self.events: list[tuple[datetime, str, str, str]] = []
        self.meta: dict[str, str] = {}

    def get_candidate(self, key):
        return self.candidates.get(key)

    def add_candidate(self, c):
        self.candidates.setdefault(c.key, c)

    def update_candidate(self, c):
        self.candidates[c.key] = c

    def pending_candidates(self, symbol):
        return sorted((c for c in self.candidates.values() if c.symbol == symbol and c.status == PENDING),
                      key=lambda c: c.b_close)

    def add_signal(self, s):
        if s.id in self.signals or any(x.candidate_key == s.candidate_key for x in self.signals.values()):
            return False
        self.signals[s.id] = s
        return True

    def update_signal(self, s):
        self.signals[s.id] = s

    def active_signals(self, symbol):
        return [s for s in self.signals.values() if s.symbol == symbol and s.outcome_status == "active"]

    def signals_for_symbol(self, symbol):
        return [s for s in self.signals.values() if s.symbol == symbol]

    def add_event(self, kind, message, level="info", at=None):
        self.events.append((at or _now(), level, kind, message))

    def get_meta(self, key, default=None):
        return self.meta.get(key, default)

    def set_meta(self, key, value):
        self.meta[key] = value


def _to_db(value: Any) -> Any:
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value


_DT_CAND = {"a_open", "b_open", "b_close", "pivot_time", "pivot_available", "deadline", "last_bar_close",
            "confirm_close", "created_at", "updated_at"}
_DT_SIG = {"quote_time", "confirm_close", "created_at", "valid_until", "outcome_time", "last_checked"}


class SqliteStore:
    """Thread-safe (single connection + lock) SQLite store. One database file per data mode."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        with self._lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA busy_timeout=5000")
            self._migrate()

    def _migrate(self):
        self.db.executescript(f"""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS candidates (id INTEGER PRIMARY KEY, {", ".join(f'{n} {"TEXT UNIQUE NOT NULL" if n == "key" else ""}' for n in _CAND_FIELDS)});
        CREATE INDEX IF NOT EXISTS cand_status ON candidates(symbol, status);
        CREATE TABLE IF NOT EXISTS signals (rowid_ INTEGER PRIMARY KEY, {", ".join(f'{n} {"TEXT UNIQUE NOT NULL" if n in ("id", "candidate_key") else ""}' for n in _SIG_FIELDS)});
        CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY, signal_id TEXT, kind TEXT NOT NULL, text TEXT NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT,
            valid_until TEXT, telegram_message_id INTEGER, last_error TEXT, created_at TEXT, updated_at TEXT,
            UNIQUE(signal_id, kind));
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at TEXT, level TEXT, kind TEXT, message TEXT);
        """)

    # ---- meta
    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: Optional[str]) -> None:
        with self._lock:
            self.db.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # ---- candidates
    def _cand(self, row) -> Candidate:
        d = {k: row[k] for k in _CAND_FIELDS}
        for k in _DT_CAND:
            d[k] = parse_iso(d[k])
        d["warmup"] = bool(d["warmup"])
        return Candidate(**d)

    def get_candidate(self, key):
        with self._lock:
            row = self.db.execute("SELECT * FROM candidates WHERE key=?", (key,)).fetchone()
        return self._cand(row) if row else None

    def add_candidate(self, c):
        cols = ",".join(_CAND_FIELDS)
        with self._lock:
            self.db.execute(f"INSERT OR IGNORE INTO candidates({cols}) VALUES({','.join('?' * len(_CAND_FIELDS))})",
                            [_to_db(getattr(c, n)) for n in _CAND_FIELDS])

    def update_candidate(self, c):
        sets = ",".join(f"{n}=?" for n in _CAND_FIELDS if n != "key")
        with self._lock:
            self.db.execute(f"UPDATE candidates SET {sets} WHERE key=?",
                            [_to_db(getattr(c, n)) for n in _CAND_FIELDS if n != "key"] + [c.key])

    def pending_candidates(self, symbol):
        with self._lock:
            rows = self.db.execute("SELECT * FROM candidates WHERE symbol=? AND status=? ORDER BY b_close", (symbol, PENDING)).fetchall()
        return [self._cand(r) for r in rows]

    def list_candidates(self, limit: int = 200, status: Optional[str] = None, direction: Optional[str] = None) -> list[Candidate]:
        q, args = "SELECT * FROM candidates WHERE 1=1", []
        if status:
            q += " AND status=?"; args.append(status)
        if direction:
            q += " AND direction=?"; args.append(direction)
        q += " ORDER BY b_close DESC, id DESC LIMIT ?"; args.append(limit)
        with self._lock:
            return [self._cand(r) for r in self.db.execute(q, args).fetchall()]

    def candidate_by_id(self, cid: int) -> Optional[Candidate]:
        with self._lock:
            row = self.db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
        return self._cand(row) if row else None

    def candidate_id(self, key: str) -> Optional[int]:
        with self._lock:
            row = self.db.execute("SELECT id FROM candidates WHERE key=?", (key,)).fetchone()
        return row["id"] if row else None

    # ---- signals
    def _sig(self, row) -> Signal:
        d = {k: row[k] for k in _SIG_FIELDS}
        for k in _DT_SIG:
            d[k] = parse_iso(d[k])
        d["meta"] = json.loads(d["meta"] or "{}")
        return Signal(**d)

    def add_signal(self, s):
        cols = ",".join(_SIG_FIELDS)
        with self._lock:
            cur = self.db.execute(f"INSERT OR IGNORE INTO signals({cols}) VALUES({','.join('?' * len(_SIG_FIELDS))})",
                                  [_to_db(getattr(s, n)) for n in _SIG_FIELDS])
        return cur.rowcount == 1

    def update_signal(self, s):
        sets = ",".join(f"{n}=?" for n in _SIG_FIELDS if n != "id")
        with self._lock:
            self.db.execute(f"UPDATE signals SET {sets} WHERE id=?", [_to_db(getattr(s, n)) for n in _SIG_FIELDS if n != "id"] + [s.id])

    def active_signals(self, symbol):
        with self._lock:
            rows = self.db.execute("SELECT * FROM signals WHERE symbol=? AND outcome_status='active' ORDER BY created_at", (symbol,)).fetchall()
        return [self._sig(r) for r in rows]

    def signals_for_symbol(self, symbol):
        """Unbounded history: a UI row limit must never reset strategy controls."""
        with self._lock:
            rows = self.db.execute("SELECT * FROM signals WHERE symbol=?", (symbol,)).fetchall()
        return [self._sig(r) for r in rows]

    def list_signals(self, limit: int = 200, direction: Optional[str] = None, outcome: Optional[str] = None) -> list[Signal]:
        q, args = "SELECT * FROM signals WHERE 1=1", []
        if direction:
            q += " AND direction=?"; args.append(direction)
        if outcome:
            q += " AND outcome_status=?"; args.append(outcome)
        q += " ORDER BY created_at DESC LIMIT ?"; args.append(limit)
        with self._lock:
            return [self._sig(r) for r in self.db.execute(q, args).fetchall()]

    def get_signal(self, sid: str) -> Optional[Signal]:
        with self._lock:
            row = self.db.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
        return self._sig(row) if row else None

    # ---- events
    def add_event(self, kind, message, level="info", at=None):
        with self._lock:
            self.db.execute("INSERT INTO events(at,level,kind,message) VALUES(?,?,?,?)", (iso(at or _now()), level, kind, message))
            self.db.execute("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - 2000")

    def list_events(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT at,level,kind,message FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---- outbox
    def enqueue(self, signal_id: Optional[str], kind: str, text: str, valid_until: datetime, now: datetime) -> bool:
        with self._lock:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO outbox(signal_id,kind,text,status,attempts,next_attempt_at,valid_until,created_at,updated_at)"
                " VALUES(?,?,?,'pending',0,?,?,?,?)", (signal_id, kind, text, iso(now), iso(valid_until), iso(now), iso(now)))
        return cur.rowcount == 1

    def outbox_for(self, signal_ids: list[str], kind: str) -> dict[str, dict]:
        """Read-only: the outbox row of each given signal/basket id (one row per id and kind, by the UNIQUE key)."""
        if not signal_ids:
            return {}
        marks = ",".join("?" * len(signal_ids))
        with self._lock:
            rows = self.db.execute(f"SELECT * FROM outbox WHERE kind=? AND signal_id IN ({marks})", [kind, *signal_ids]).fetchall()
        return {r["signal_id"]: dict(r) for r in rows}

    def outbox_rows(self, status: Optional[str] = None, limit: int = 200) -> list[dict]:
        q, args = "SELECT * FROM outbox", []
        if status:
            q += " WHERE status=?"; args.append(status)
        q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        with self._lock:
            return [dict(r) for r in self.db.execute(q, args).fetchall()]

    def due_outbox(self, now: datetime) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT * FROM outbox WHERE status='pending' AND next_attempt_at <= ? ORDER BY id", (iso(now),)).fetchall()
        return [dict(r) for r in rows]

    def update_outbox(self, oid: int, **values) -> None:
        values = {k: _to_db(v) for k, v in values.items()}
        values["updated_at"] = iso(_now())
        sets = ",".join(f"{k}=?" for k in values)
        with self._lock:
            self.db.execute(f"UPDATE outbox SET {sets} WHERE id=?", [*values.values(), oid])

    def recover_inflight(self) -> int:
        """A crash while 'sending' leaves the outcome unknown: never resend those blindly."""
        with self._lock:
            cur = self.db.execute("UPDATE outbox SET status='unknown', last_error='process stopped during send; outcome unknown' WHERE status='sending'")
        return cur.rowcount

    def close(self):
        with self._lock:
            self.db.close()
