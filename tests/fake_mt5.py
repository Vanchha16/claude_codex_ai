"""Minimal stand-in for the MetaTrader5 Python module (read-only calls only). No terminal, no network."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np

RATE_DTYPE = [("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"),
              ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")]
TICK_DTYPE = [("time", "<i8"), ("bid", "<f8"), ("ask", "<f8"), ("last", "<f8"), ("volume", "<u8"),
              ("time_msc", "<i8"), ("flags", "<u4"), ("volume_real", "<f8")]
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}


class FakeMT5:
    COPY_TICKS_INFO = 2

    def __init__(self, *, now: datetime, symbols=("XAUUSD", "XAUUSDm"), connected=True, init_ok=True,
                 tick_error=False, base_price=2400.0):
        self.now = now
        self.symbols = list(symbols)
        self.connected, self.init_ok, self.tick_error = connected, init_ok, tick_error
        self.base = base_price
        self.calls: list[str] = []
        self.ticks: list[tuple[float, float, float]] = []  # (epoch seconds, bid, ask)
        self.last_tick = None  # (epoch, bid, ask)
        for name in ("M1", "M5", "M15", "H1", "H4", "D1"):
            setattr(self, f"TIMEFRAME_{name}", name)

    # --- lifecycle / context
    def initialize(self, path=None, **kw):
        self.calls.append("initialize")
        assert not kw, "VC Signal must never pass login credentials to initialize()"
        return self.init_ok

    def last_error(self):
        return (-10005, "IPC timeout")

    def shutdown(self):
        self.calls.append("shutdown")

    def terminal_info(self):
        return SimpleNamespace(connected=self.connected, name="MetaTrader 5", company="Exness Technologies Ltd", build=5000)

    def account_info(self):
        return SimpleNamespace(login=12345678, balance=1000.0, server="Exness-MT5Trial", company="Exness Technologies Ltd",
                               trade_mode=0)

    # --- symbols
    def symbols_get(self, group=None):
        pat = (group or "*").strip("*").upper()
        return [SimpleNamespace(name=n, description=f"Gold vs US Dollar ({n})", path=f"Metals\\{n}", visible=True,
                                digits=3 if n.endswith("m") else 2, trade_tick_size=0.001 if n.endswith("m") else 0.01,
                                spread=16) for n in self.symbols if pat in n.upper()]

    def symbol_info(self, name):
        if name not in self.symbols:
            return None
        s = self.symbols_get("*")[self.symbols.index(name)]
        return SimpleNamespace(**vars(s), point=s.trade_tick_size, trade_mode=4)

    def symbol_select(self, name, enable):
        return True

    def symbol_info_tick(self, name):
        if self.last_tick is None:
            t = self.now.timestamp()
            self.last_tick = (t, self.base, self.base + 0.2)
        t, bid, ask = self.last_tick
        return SimpleNamespace(time=int(t), bid=bid, ask=ask, time_msc=int(t * 1000))

    # --- history
    def _series(self, tf, end_epoch, count):
        step = TF_SECONDS[tf]
        last_open = (int(end_epoch) // step) * step
        rows = []
        for i in range(count - 1, -1, -1):
            t = last_open - i * step
            o = self.base + (t // step % 7) * 0.1
            rows.append((t, o, o + 0.5, o - 0.5, o + 0.2, 100 + i, 16, 0))
        return np.array(rows, dtype=RATE_DTYPE)

    def copy_rates_from_pos(self, symbol, tf, start, count):
        self.calls.append(f"rates_pos:{tf}")
        return self._series(tf, self.now.timestamp(), count)

    def copy_rates_from(self, symbol, tf, date_from, count):
        self.calls.append(f"rates_from:{tf}")
        return self._series(tf, date_from.timestamp() - TF_SECONDS[tf], count)

    def copy_rates_range(self, symbol, tf, date_from, date_to):
        step = TF_SECONDS[tf]
        n = int((date_to.timestamp() - date_from.timestamp()) // step)
        return self._series(tf, date_to.timestamp() - step, max(n, 1))

    def copy_ticks_range(self, symbol, date_from, date_to, flags):
        self.calls.append("ticks")
        if self.tick_error:
            return None
        lo, hi = date_from.timestamp(), date_to.timestamp()
        rows = [(int(t), b, a, 0.0, 0, int(t * 1000), 6, 0.0) for t, b, a in self.ticks if lo <= t <= hi]
        return np.array(rows, dtype=TICK_DTYPE)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)
