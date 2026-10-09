"""Which strategy the live scanner runs: CRT-SMC-v1 (default, rollback), FastSweep-M15-M5-v1, FVG-Trend-M15-M5-v1
("fvg"/"rr2", kept as rollback) or the independent M15 + M5 FVG engines ("fvg"/"dual").

Persisted in config/active_strategy.json, e.g. {"strategy": "fastsweep", "profile": "rr2"} or {"strategy": "crt"}.
No file means CRT (the original behaviour). Unknown strategies/profiles or extra keys fail clearly at startup.
CRT keeps its own config/strategy.json; FastSweep parameters are the predeclared FastSweepConfig profile values.
Every effective configuration is fingerprinted into its version string, so persisted candidate/signal records of
different strategies or profiles never collide and are never processed by another strategy's rules.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .config import PROJECT_ROOT
from .fastsweep import PROFILES, STRATEGY, FastSweepConfig
from .fvg import PROFILES as FVG_PROFILES, STRATEGY as FVG_STRATEGY, FvgConfig
from .fvg_dual import DUAL_PROFILE, DUAL_STRATEGY, DualFvgConfig

ACTIVE_STRATEGY_FILE = PROJECT_ROOT / "config" / "active_strategy.json"
KINDS = ("crt", "fastsweep", "fvg")
FASTSWEEP_FAMILY = STRATEGY  # version prefix shared by every FastSweep profile/config


def fastsweep_version(cfg: FastSweepConfig) -> str:
    digest = hashlib.sha256(json.dumps(asdict(cfg), sort_keys=True).encode()).hexdigest()[:8]
    return f"{cfg.version}@{digest}"


def is_fastsweep_version(version: Optional[str]) -> bool:
    return bool(version) and version.startswith(FASTSWEEP_FAMILY)


@dataclass(frozen=True)
class ActiveStrategy:
    kind: str                                   # "crt" | "fastsweep" | "fvg"
    profile: Optional[str] = None               # "rr1" | "rr2" for fastsweep; "rr2" (legacy v1) or "dual" for fvg
    fastsweep: Optional[FastSweepConfig] = None
    fvg: Optional[FvgConfig] = None             # FVG rule parameters (v1 profile, or the dual engines' shared rules)
    fvg_dual: Optional[DualFvgConfig] = None    # set only for the independent M15 + M5 engines

    @property
    def is_fvg_dual(self) -> bool:
        return self.kind == "fvg" and self.fvg_dual is not None

    @property
    def fvg_version(self) -> Optional[str]:
        """The version that execution consent binds to: the dual mode's own version, or the v1 profile's."""
        if not self.is_fvg:
            return None
        return self.fvg_dual.version if self.fvg_dual is not None else self.fvg.version

    @property
    def is_fvg(self) -> bool:
        return self.kind == "fvg"

    @property
    def is_fastsweep(self) -> bool:
        return self.kind == "fastsweep"

    def describe(self, crt_version: str) -> dict:
        if self.is_fvg_dual:
            d, cfg = self.fvg_dual, self.fvg
            return {"kind": "fvg", "mode": "dual", "name": DUAL_STRATEGY, "profile": self.profile, "version": d.version,
                    "engine_versions": {e: d.engine_version(e) for e in d.engines},
                    "label": "FVG dual · M15 + M5 · 3 limits · 1:2", "reward_risk": cfg.reward_risk,
                    "timeframes": {"engines": list(d.engines)},
                    "rules": (f"Two independent engines (M15 and M5), each on its own closed A/B/C candles: FVG with "
                              f"EMA{cfg.ema_fast}/{cfg.ema_slow} trend (>= {cfg.trend_min_candles} contiguous candles of "
                              f"that timeframe), gap >= max({cfg.min_gap_ticks} ticks, {cfg.gap_atr:g} ATR{cfg.atr_period}) "
                              f"and a {cfg.displacement_atr:g} ATR middle body. A qualified gap places three limits at "
                              f"{'/'.join(f'{p:g}%' for p in cfg.entry_depths)} depth immediately (no retest/confirmation), "
                              f"common SL {cfg.sl_buffer_ticks} ticks beyond the zone"
                              + ("".join(f" ({'/'.join(sa)}: moved further outward when needed so every leg is >= spread + "
                                         f"{cfg.stop_spread_margin_ticks} tick from it)"
                                         for sa in [[e for e in d.engines if d.stop_policy_for(e) == "spread_aware"]] if sa))
                              + f", each TP 1:{cfg.reward_risk:g}"),
                    "controls": {"open_baskets_per_engine": d.max_open_baskets_per_engine,
                                 "cooldown_minutes_per_engine": cfg.cooldown_minutes,
                                 "max_baskets_per_bangkok_day_total": cfg.max_baskets_per_day,
                                 "pending_expiry_minutes": cfg.pending_expiry_minutes,
                                 "decision_max_age_seconds": cfg.max_confirmation_age_seconds,
                                 "risk": "configured USD budget per basket (one basket per engine at once)",
                                 "tie_order": "M15 before M5"}}
        if self.is_fvg:
            cfg = self.fvg
            return {"kind": "fvg", "name": FVG_STRATEGY, "profile": self.profile, "version": cfg.version,
                    "label": "FVG · 3 limits · 1:2", "reward_risk": cfg.reward_risk,
                    "timeframes": {"range": "M15", "confirmation": "M5"},
                    "rules": (f"M15 FVG with EMA{cfg.ema_fast}/{cfg.ema_slow} trend, gap >= max({cfg.min_gap_ticks} ticks, "
                              f"{cfg.gap_atr:g} ATR{cfg.atr_period}) and a {cfg.displacement_atr:g} ATR middle body; first M5 "
                              f"retest, then an M5 close beyond the retest bar within {cfg.confirm_bars} bars; three limits at "
                              f"{'/'.join(f'{p:g}%' for p in cfg.entry_depths)} depth, common SL {cfg.sl_buffer_ticks} ticks "
                              f"beyond the zone, each TP 1:{cfg.reward_risk:g}"),
                    "controls": {"one_open_basket": True, "cooldown_minutes": cfg.cooldown_minutes,
                                 "max_baskets_per_bangkok_day": cfg.max_baskets_per_day,
                                 "pending_expiry_minutes": cfg.pending_expiry_minutes}}
        if self.is_fastsweep:
            cfg = self.fastsweep
            return {"kind": "fastsweep", "name": STRATEGY, "profile": self.profile, "version": fastsweep_version(cfg),
                    "label": f"FastSweep · 1:{cfg.reward_risk:g}", "reward_risk": cfg.reward_risk,
                    "timeframes": {"range": "M15", "confirmation": "M5"},
                    "rules": (f"M15 sweep-and-return of A, EMA{cfg.ema_fast}/EMA{cfg.ema_slow} trend "
                              f"(>= {cfg.trend_min_candles} contiguous M15 candles), confirmation by an M5 close beyond B "
                              f"within {cfg.confirm_bars} bars, stop {cfg.sl_buffer_ticks} ticks beyond B, "
                              f"fixed 1:{cfg.reward_risk:g} target"),
                    "controls": {"one_active_signal": True, "cooldown_minutes": cfg.cooldown_minutes,
                                 "max_signals_per_bangkok_day": cfg.max_signals_per_day,
                                 "outcome_expiry_hours": cfg.outcome_expiry_hours}}
        return {"kind": "crt", "name": "CRT-SMC-v1", "profile": None, "version": crt_version, "label": "CRT-SMC-v1",
                "reward_risk": None, "timeframes": {"range": "H1", "confirmation": "M5"},
                "rules": "H1 sweep-and-return, M5 structure break, target A's opposite edge, minimum RR from config/strategy.json",
                "controls": {"one_active_signal": True}}


def parse_active_strategy(raw: dict) -> ActiveStrategy:
    if not isinstance(raw, dict):
        raise ValueError("active strategy must be a JSON object")
    extra = set(raw) - {"strategy", "profile", "_comment"}
    if extra:
        raise ValueError(f"unknown active-strategy keys: {', '.join(sorted(extra))}")
    kind = raw.get("strategy")
    if kind not in KINDS:
        raise ValueError(f"unknown strategy {kind!r}; use one of {', '.join(KINDS)}")
    if kind == "crt":
        if raw.get("profile") not in (None, ""):
            raise ValueError("strategy 'crt' takes no profile")
        return ActiveStrategy("crt")
    if kind == "fvg":
        profile = raw.get("profile")
        if profile == "dual":
            dual = DUAL_PROFILE.validate()
            return ActiveStrategy("fvg", "dual", fvg=dual.rules, fvg_dual=dual)
        if profile not in FVG_PROFILES:
            raise ValueError(f"unknown FVG profile {profile!r}; use one of {', '.join(FVG_PROFILES)} or dual")
        return ActiveStrategy("fvg", profile, fvg=FVG_PROFILES[profile].validate())
    profile = raw.get("profile")
    if profile not in PROFILES:
        raise ValueError(f"unknown FastSweep profile {profile!r}; use one of {', '.join(PROFILES)}")
    return ActiveStrategy("fastsweep", profile, PROFILES[profile].validate())


def load_active_strategy(path: Path = ACTIVE_STRATEGY_FILE) -> ActiveStrategy:
    if not path.exists():
        return ActiveStrategy("crt")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc
    return parse_active_strategy(raw)


def save_active_strategy(choice: dict, path: Path = ACTIVE_STRATEGY_FILE) -> ActiveStrategy:
    """Validate first, then write atomically (a bad choice never replaces a good file)."""
    parsed = parse_active_strategy(choice)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"strategy": parsed.kind} | ({"profile": parsed.profile} if parsed.profile else {})
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".active_strategy.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)
    return parsed


def main(argv=None) -> int:
    """python -m app.active_strategy [crt | fastsweep rr1|rr2 | fvg rr2|dual]  (shows the current choice without args)."""
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        a = load_active_strategy()
        print(f"active strategy: {a.kind}" + (f" profile {a.profile}" if a.profile else "") + f"  ({ACTIVE_STRATEGY_FILE})")
        return 0
    choice = {"strategy": args[0]} | ({"profile": args[1]} if len(args) > 1 else {})
    a = save_active_strategy(choice)
    print(f"saved: {a.kind}" + (f" profile {a.profile}" if a.profile else "") + " - restart with: gold.cmd restart")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
