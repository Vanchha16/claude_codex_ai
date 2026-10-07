"""One UTC-normalisation contract for every MetaTrader 5 timestamp (feed, chart, history and FVG execution).

The official Python API documents tick/bar epochs and range arguments as UTC. Some trade servers deliver them in
their own server time instead (verified 2026-10-07: MetaQuotes-Demo ticks and M5 rates were exactly +3 h ahead of
an externally checked UTC clock, advancing with wall time, i.e. an offset, not stale data). Such a correction is
NEVER guessed from a tick: it must be listed for that exact server name in config/mt5_time.json after verification.

    broker epoch = UTC epoch + offset          to_utc(): broker -> UTC     to_broker(): UTC -> broker

Every value crosses the boundary exactly once: received tick/bar epochs through to_utc, outgoing range datetimes and
the pending-order expiration through to_broker. Servers without an entry use the legacy explicit
GOLD_MT5_SERVER_UTC_OFFSET_HOURS (default 0 = documented UTC). A wrong offset (e.g. after a DST change) is not
auto-corrected: quotes then look stale or future and the scanner/executor freshness guards fail closed.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MT5_TIME_FILE = PROJECT_ROOT / "config" / "mt5_time.json"
MAX_OFFSET_HOURS = 14


class TimeConfigError(ValueError):
    pass


@dataclass(frozen=True)
class TimeBase:
    offset_hours: float = 0.0
    server: Optional[str] = None      # the trade server this base was resolved for (None = not bound to a server)
    source: str = "default UTC"       # where the offset came from (shown in status)

    @property
    def offset(self) -> timedelta:
        return timedelta(hours=self.offset_hours)

    def to_utc(self, epoch_seconds: float) -> datetime:
        return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc) - self.offset

    def to_broker(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            raise ValueError("naive datetime: MT5 requests need an explicit UTC datetime")
        return dt.astimezone(timezone.utc) + self.offset

    def to_dict(self) -> dict:
        return {"server": self.server, "utc_offset_hours": self.offset_hours, "source": self.source}


UTC_BASE = TimeBase()


def _valid_offset(v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise TimeConfigError("utc_offset_hours must be a number")
    if abs(v) > MAX_OFFSET_HOURS or abs(v * 4 - round(v * 4)) > 1e-9:
        raise TimeConfigError("utc_offset_hours must be within +-14 in quarter-hour steps")
    return float(v)


def load_server_offsets(path: Path = MT5_TIME_FILE) -> dict[str, float]:
    """{server name: verified offset hours}. Missing file = no server-bound corrections. Invalid file = error."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TimeConfigError(f"{path.name} is unreadable: {exc}") from exc
    servers = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        raise TimeConfigError(f"{path.name} needs a 'servers' object")
    out = {}
    for name, entry in servers.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(entry, dict):
            raise TimeConfigError(f"{path.name}: invalid server entry {name!r}")
        out[name] = _valid_offset(entry.get("utc_offset_hours"))
    return out


def resolve_time_base(server: Optional[str], legacy_offset_hours: float = 0.0, path: Path = MT5_TIME_FILE) -> TimeBase:
    """The time base for the CONNECTED server: its verified entry, else the explicit legacy offset, else UTC."""
    offsets = load_server_offsets(path)
    if server and server in offsets:
        return TimeBase(offsets[server], server, f"{path.name} (verified for this server)")
    legacy = _valid_offset(legacy_offset_hours)
    if legacy:
        return TimeBase(legacy, server, "GOLD_MT5_SERVER_UTC_OFFSET_HOURS (legacy, all servers)")
    return TimeBase(0.0, server, "default UTC (documented MT5 API behaviour)")
