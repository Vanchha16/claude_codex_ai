"""Pure sizing for the three FVG limit legs (no MT5 connection, no submission).

Risk model confirmed by the user: a FIXED total budget per setup (configured: 10 USD), split into equal nominal
shares (budget / 3) per leg. Each leg's lots = its share / (account-currency loss of 1 lot from its entry to the common
SL), rounded DOWN to the broker lot step. Wider stop distance -> fewer lots. A leg that cannot fit the minimum lot within
its share rejects the WHOLE plan; shares are never increased or redistributed. Nominal SL risk is not a hard loss cap
(fees, gaps and slippage can exceed it).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_FLOOR
from typing import Callable

from .fastsweep import BUY
from .fvg import PROFILES, FvgConfig, Gap, basket_levels
from .models import SymbolMeta

# Explicitly supported account currencies -> account units per 1 USD. Cent accounts report USC (US cents).
ACCOUNT_UNITS_PER_USD = {"USD": 1.0, "USC": 100.0}


def account_cash_risk(risk_usd: float, account_currency: str) -> float:
    """Convert the USD budget to account-currency units; unknown currencies are rejected, never assumed to be USD."""
    if not isinstance(risk_usd, (int, float)) or isinstance(risk_usd, bool) or not math.isfinite(risk_usd) or risk_usd <= 0:
        raise ValueError("risk budget is not configured (needs a positive USD amount)")
    units = ACCOUNT_UNITS_PER_USD.get((account_currency or "").upper())
    if units is None:
        raise ValueError(f"account currency {account_currency!r} is not supported for USD risk (supported: USD, USC)")
    return risk_usd * units


@dataclass(frozen=True)
class PlannedOrder:
    number: int
    percent: float
    direction: str
    entry: float
    sl: float
    tp: float
    volume: float
    planned_loss: float   # account currency, at the limit price to the common SL, before costs


def floor_to_step(raw: float, step: float) -> float:
    s = Decimal(str(step))
    return float((Decimal(str(raw)) / s).to_integral_value(rounding=ROUND_FLOOR) * s)


def build_order_plan(gap: Gap, meta: SymbolMeta, cash_risk: float, loss_per_lot: Callable[[str, float, float], float], *,
                     volume_min: float, volume_max: float, volume_step: float, sl_buffer_ticks: int = 2,
                     percentages=(1.0, 50.0, 80.0), cfg: FvgConfig | None = None) -> tuple[PlannedOrder, ...]:
    """loss_per_lot(direction, entry, sl) returns a POSITIVE account-currency loss for one lot.
    cash_risk is the combined nominal loss (account currency) if all legs fill and stop at the common SL."""
    if any(not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0 for x in (cash_risk, volume_min, volume_max, volume_step)):
        raise ValueError("risk and broker volume limits must be finite and positive")
    if volume_min > volume_max or not isinstance(sl_buffer_ticks, int) or sl_buffer_ticks < 1:
        raise ValueError("invalid volume limits or stop buffer")
    cfg = replace(cfg or PROFILES["rr2"], sl_buffer_ticks=sl_buffer_ticks, entry_depths=tuple(percentages)).validate()
    sl, legs = basket_levels(gap, meta, cfg)
    share = cash_risk / len(legs)
    out = []
    for leg in legs:
        loss = loss_per_lot(gap.direction, leg.entry, sl)
        if not isinstance(loss, (int, float)) or not math.isfinite(loss) or loss <= 0:
            raise ValueError("broker loss calculation must be finite and positive")
        volume = floor_to_step(min(share / loss, volume_max), volume_step)  # never round upward
        if volume < volume_min - 1e-12:
            raise ValueError(f"entry {leg.number} cannot fit the minimum lot within its {share:.2f} risk share")
        out.append(PlannedOrder(leg.number, leg.percent, gap.direction, leg.entry, sl, leg.tp, volume, loss * volume))
    if sum(p.planned_loss for p in out) > cash_risk + 1e-8:
        raise ValueError("rounded order plan exceeds the combined risk budget")
    return tuple(out)


__all__ = ["ACCOUNT_UNITS_PER_USD", "account_cash_risk", "PlannedOrder", "build_order_plan", "floor_to_step", "BUY"]
