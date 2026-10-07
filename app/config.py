"""Validated configuration. Strategy thresholds live in config/strategy.json; secrets come from .env / environment."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / ".tmp" / "gold-signals"
STRATEGY_FILE = PROJECT_ROOT / "config" / "strategy.json"
ENV_FILE = PROJECT_ROOT / ".env"
VENV_ENV_FILE = PROJECT_ROOT / ".venv" / ".env"
LOCAL_SETTINGS_FILE = PROJECT_ROOT / "config" / "local_settings.json"  # nonsecret dashboard choices (git-ignored)
DEMO_FIXTURE = PROJECT_ROOT / "data" / "demo" / "xauusd_demo_m5.json"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class StrategyConfig:
    """CRT-SMC-v1 parameters. Defaults are testing baselines, not optimised or proven values."""

    name: str = "CRT-SMC-v1"
    sweep_min_ticks: int = 2  # B must trade at least this many ticks beyond A's boundary
    sl_buffer_ticks: int = 2  # SL sits this many ticks beyond B's sweep extreme
    pivot_side_bars: int = 2  # closed M5 bars on each side of a swing point
    structure_lookback_bars: int = 24  # M5 bars before B open searched for the structure pivot
    confirm_max_bars: int = 12  # completed M5 bars after B close allowed for confirmation
    min_reward_risk: float = 1.5
    max_spread_price: float = 0.50  # in price units (USD per ounce for XAUUSD), not points/pips
    signal_max_age_seconds: int = 30  # live confirmation is actionable at most this long after its candle close
    quote_max_age_seconds: int = 30
    alert_valid_seconds: int = 120  # entry-validity window stated in alerts; delivery retries stop after it
    outcome_expiry_hours: float = 24.0  # active simulated signals expire after this

    def validate(self) -> "StrategyConfig":
        ints = {"sweep_min_ticks": (1, 1000), "sl_buffer_ticks": (0, 1000), "pivot_side_bars": (1, 10),
                "structure_lookback_bars": (5, 500), "confirm_max_bars": (1, 500),
                "signal_max_age_seconds": (1, 3600), "quote_max_age_seconds": (1, 3600), "alert_valid_seconds": (5, 86400)}
        for key, (lo, hi) in ints.items():
            v = getattr(self, key)
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                raise ConfigError(f"{key} must be an integer in [{lo}, {hi}], got {v!r}")
        floats = {"min_reward_risk": (0.1, 100.0), "max_spread_price": (0.0001, 1000.0), "outcome_expiry_hours": (0.1, 24 * 30)}
        for key, (lo, hi) in floats.items():
            v = getattr(self, key)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= float(v) <= hi:
                raise ConfigError(f"{key} must be a number in [{lo}, {hi}], got {v!r}")
        if self.structure_lookback_bars < 2 * self.pivot_side_bars + 1:
            raise ConfigError("structure_lookback_bars must cover at least one full pivot window")
        if not isinstance(self.name, str) or not self.name:
            raise ConfigError("name must be a non-empty string")
        return self

    @property
    def version(self) -> str:
        canonical = json.dumps(asdict(self), sort_keys=True)
        return f"{self.name}@{hashlib.sha256(canonical.encode()).hexdigest()[:8]}"

    def to_dict(self) -> dict:
        return {**asdict(self), "version": self.version}


def load_strategy(path: Path = STRATEGY_FILE) -> StrategyConfig:
    if not path.exists():
        return StrategyConfig().validate()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path.name} is not valid JSON: {exc}") from exc
    known = {f.name for f in fields(StrategyConfig)}
    raw = {k: v for k, v in raw.items() if not k.startswith("_")}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"unknown strategy settings: {sorted(unknown)}")
    return StrategyConfig(**raw).validate()


def read_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


# ---------------------------------------------------------------------------------------------------------------
# Configuration sources, lowest -> highest precedence (documented in README "Configuration"):
#   1. built-in defaults
#   2. .venv/.env                  (the user's existing file; only RECOGNISED keys below are read)
#   3. .env                        (project root, optional)
#   4. config/local_settings.json  (nonsecret choices saved from the dashboard setup form)
#   5. process environment         (always wins; the dashboard shows such settings as locked)
# For each setting the CANONICAL key wins over any alias, whatever source the alias is in; among keys of the same
# kind the higher-precedence source wins. Unrecognised keys (OPENAI_API_KEY, TELEGRAM_BOT_USERNAME,
# TELEGRAM_PROVIDERS, ...) are never read into the app. Tokens are never written to local_settings.json.
# ---------------------------------------------------------------------------------------------------------------
KEYS: dict[str, tuple[str, tuple[str, ...]]] = {
    # logical name: (canonical key, aliases)
    "data_mode": ("GOLD_DATA_MODE", ()),
    "symbol": ("GOLD_SYMBOL", ()),
    "mt5_terminal_path": ("GOLD_MT5_TERMINAL_PATH", ()),
    "mt5_server_utc_offset_hours": ("GOLD_MT5_SERVER_UTC_OFFSET_HOURS", ()),
    "telegram_bot_token": ("GOLD_TELEGRAM_BOT_TOKEN", ("TELEGRAM_BOT_TOKEN",)),
    "telegram_test_chat_id": ("GOLD_TELEGRAM_TEST_CHAT_ID", ("GOLD_TELEGRAM_CHAT_ID", "TELEGRAM_CHAT_ID")),
    "display_timezone": ("GOLD_DISPLAY_TIMEZONE", ()),
    "port": ("GOLD_PORT", ()),
    "scan_interval_seconds": ("GOLD_SCAN_INTERVAL_SECONDS", ()),
    "demo_speed": ("GOLD_DEMO_SPEED", ()),
    "replay_spread_price": ("GOLD_REPLAY_SPREAD", ()),
    "replay_slippage_price": ("GOLD_REPLAY_SLIPPAGE", ()),
}
LOCAL_SETTABLE = ("data_mode", "symbol", "mt5_terminal_path", "telegram_test_chat_id", "display_timezone")

SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._#+\-]{0,31}$")
CHAT_ID_RE = re.compile(r"^-?\d{5,20}$")


@dataclass
class Settings:
    data_mode: str = "demo"  # "demo" (fictional fixture) or "mt5" (live terminal); persisted, never silently swapped
    symbol: str = ""  # exact broker symbol chosen by the user; never guessed
    mt5_terminal_path: str = ""
    mt5_server_utc_offset_hours: float = 0.0  # LEGACY: MT5 Python API epochs are UTC; nonzero only if proven needed
    telegram_bot_token: str = field(default="", repr=False)
    telegram_test_chat_id: str = field(default="", repr=False)
    display_timezone: str = "UTC"  # display only; strategy computation is always UTC
    scan_interval_seconds: float = 5.0
    port: int = 8000
    demo_speed: float = 60.0  # simulated seconds per real second in demo mode
    replay_spread_price: float = 0.20  # OHLC replay assumption (price units)
    replay_slippage_price: float = 0.05
    holdout_fraction: float = 0.30
    state_dir: Path = STATE_DIR
    origins: dict = field(default_factory=dict, repr=False)  # logical name -> "source:KEY" (never values)

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_test_chat_id)

    @property
    def token_fingerprint(self) -> str:
        """Stable non-reversible identity of the configured bot token (binds the delivery opt-in)."""
        return hashlib.sha256(self.telegram_bot_token.encode()).hexdigest()[:16] if self.telegram_bot_token else ""

    def env_locked(self, name: str) -> bool:
        return str(self.origins.get(name, "")).startswith("environment:")

    def redact(self, text: str) -> str:
        if self.telegram_bot_token:
            text = text.replace(self.telegram_bot_token, "<redacted-token>")
        return text

    def public_status(self) -> dict:
        """Nonsecret configuration status for the dashboard (never the value of a secret)."""
        return {
            "data_mode": self.data_mode, "symbol": self.symbol or None,
            "mt5_terminal_path": self.mt5_terminal_path or None, "display_timezone": self.display_timezone,
            "telegram_token": "configured" if self.telegram_bot_token else "missing",
            "telegram_chat_id": self.telegram_test_chat_id or None,
            "origins": dict(self.origins),
            "locked_by_environment": [k for k in LOCAL_SETTABLE if self.env_locked(k)],
        }


def read_local_settings(path: Path = LOCAL_SETTINGS_FILE) -> dict:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path.name} is not valid JSON: {exc}") from exc
    return {k: v for k, v in raw.items() if k in LOCAL_SETTABLE and v is not None}


def validate_local(updates: dict) -> dict:
    """Validate nonsecret dashboard settings; returns normalised values. Raises ConfigError."""
    out = {}
    for key, value in updates.items():
        if key not in LOCAL_SETTABLE:
            raise ConfigError(f"{key} cannot be set from the dashboard")
        value = "" if value is None else str(value).strip()
        if key == "data_mode":
            if value not in ("demo", "mt5"):
                raise ConfigError("data source must be 'demo' or 'mt5'")
        elif key == "symbol":
            if value and not SYMBOL_RE.match(value):
                raise ConfigError("symbol must be the exact broker symbol name (letters, digits, . _ # + -)")
        elif key == "mt5_terminal_path":
            if value:
                pth = Path(value)
                if not pth.is_absolute() or pth.name.lower() != "terminal64.exe":
                    raise ConfigError("terminal path must be the absolute path of terminal64.exe (or empty)")
                if not pth.exists():
                    raise ConfigError("terminal64.exe was not found at that path")
        elif key == "telegram_test_chat_id":
            if value and not CHAT_ID_RE.match(value):
                raise ConfigError("Telegram chat ID must be the numeric chat ID (e.g. -100...), not a bot or @username")
        elif key == "display_timezone":
            if value not in ("UTC", "local"):
                try:
                    from zoneinfo import ZoneInfo
                    ZoneInfo(value)
                except Exception as exc:
                    raise ConfigError(f"unknown time zone {value!r}") from exc
        out[key] = value
    return out


def save_local_settings(updates: dict, path: Path = LOCAL_SETTINGS_FILE) -> dict:
    """Merge validated nonsecret settings into config/local_settings.json with an atomic replace."""
    clean = validate_local(updates)
    current = read_local_settings(path)
    current.update(clean)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".local_settings.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"_note": "Nonsecret VC Signal settings saved from the dashboard. Secrets stay in .env files.",
                       **current}, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return current


def _sources(env: dict | None, env_files: tuple[Path, ...], local_path: Path) -> list[tuple[str, dict]]:
    """Configuration sources from HIGHEST to lowest precedence."""
    local = read_local_settings(local_path)
    local_src = ("local_settings", {KEYS[k][0]: v for k, v in local.items()})
    if env is not None:  # explicit mapping (tests / embedding) replaces process env and the .env files
        return [("environment", env), local_src]
    srcs = [("environment", dict(os.environ)), local_src]
    for path in reversed(env_files):
        try:
            label = path.resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            label = path.name
        srcs.append((label, read_env_file(path)))
    return srcs


def resolve(sources: list[tuple[str, dict]]) -> tuple[dict, dict]:
    """Pick one value per logical setting. Canonical keys beat aliases; then higher-precedence sources win."""
    values, origins = {}, {}
    for name, (canonical, aliases) in KEYS.items():
        for key in (canonical, *aliases):
            hit = next(((src, mapping[key]) for src, mapping in sources
                        if key in mapping and str(mapping[key]).strip() != ""), None)
            if hit:
                values[name] = str(hit[1]).strip()
                origins[name] = f"{hit[0]}:{key}"
                break
    return values, origins


def load_settings(env: dict[str, str] | None = None, *, env_files: tuple[Path, ...] = (VENV_ENV_FILE, ENV_FILE),
                  local_path: Path = LOCAL_SETTINGS_FILE) -> Settings:
    values, origins = resolve(_sources(env, env_files, local_path))
    s = Settings(origins=origins)
    s.data_mode = (values.get("data_mode", "demo") or "demo").lower()
    if s.data_mode not in {"demo", "mt5"}:
        raise ConfigError("GOLD_DATA_MODE must be 'demo' or 'mt5'")
    s.symbol = values.get("symbol", "")
    if s.symbol and not SYMBOL_RE.match(s.symbol):
        raise ConfigError("GOLD_SYMBOL is not a valid symbol name")
    s.mt5_terminal_path = values.get("mt5_terminal_path", "")
    s.telegram_bot_token = values.get("telegram_bot_token", "")
    s.telegram_test_chat_id = values.get("telegram_test_chat_id", "")
    s.display_timezone = values.get("display_timezone", "UTC") or "UTC"
    try:
        s.mt5_server_utc_offset_hours = float(values.get("mt5_server_utc_offset_hours", "0") or 0)
        s.port = int(values.get("port", "8000") or 8000)
        s.demo_speed = float(values.get("demo_speed", "60") or 60)
        s.scan_interval_seconds = float(values.get("scan_interval_seconds", "5") or 5)
        s.replay_spread_price = float(values.get("replay_spread_price", "0.20") or 0.2)
        s.replay_slippage_price = float(values.get("replay_slippage_price", "0.05") or 0.05)
    except ValueError as exc:
        raise ConfigError(f"invalid numeric setting: {exc}") from exc
    if not 1 <= s.port <= 65535:
        raise ConfigError("GOLD_PORT out of range")
    if not 1 <= s.scan_interval_seconds <= 300:
        raise ConfigError("GOLD_SCAN_INTERVAL_SECONDS must be 1-300")
    if not 1 <= s.demo_speed <= 3600:
        raise ConfigError("GOLD_DEMO_SPEED must be 1-3600")
    if abs(s.mt5_server_utc_offset_hours) > 14:
        raise ConfigError("GOLD_MT5_SERVER_UTC_OFFSET_HOURS must be within +-14")
    return s
