from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol

from ..models import Bar, Quote, SymbolMeta


@dataclass
class FeedStatus:
    ok: bool
    state: str  # connected | demo | demo_finished | not_configured | disconnected | symbol_missing | error
    message: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "state": self.state, "message": self.message, "details": self.details}


class Feed(Protocol):
    mode: str  # "demo" or "mt5"

    def connect(self) -> FeedStatus: ...
    def status(self) -> FeedStatus: ...
    def meta(self) -> SymbolMeta: ...
    def now(self) -> datetime: ...
    def quote(self) -> Optional[Quote]: ...
    def closed_bars(self, tf: str, count: int) -> list[Bar]: ...
    def bars_range(self, tf: str, start: datetime, end: datetime) -> list[Bar]: ...
    def shutdown(self) -> None: ...
