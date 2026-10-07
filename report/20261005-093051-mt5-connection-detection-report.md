# Claude report: fix MT5 detection and disconnected Resume

Task ID: 20261005-093051-mt5-connection-detection
Source prompt: `prompt/20261005-093051-mt5-connection-detection.md`
Status: completed
Reported at: 2026-10-05

## Outcome

VC Signal is connected (read-only) to the user's running Exness MT5 terminal on the saved symbol **XAUUSDc**: a fresh quote and real closed H1/M5 history.

The three defects in the prompt are fixed:
- **Process detection** is now three-state, with a read-only fallback when the process list is denied.
- **Resume while disconnected** no longer crashes.
- **Discovery** with an unconnected terminal reports a clear 503 instead of an empty success.

As instructed, the scanner's **paused** state, the Telegram settings (delivery disabled), the source and symbol, the strategy and the history were all left unchanged. No orders, no Telegram messages or enable actions, and no machine or permission changes.

**Approval gate:** passed. The prompt is in `prompt/` with `APPROVED FOR EXECUTION`, a Task ID, Source prompt and exact Report path. Its `User authorization:` line records the user's explicit 2026-10-05 instruction ("tell claude to connect to mt5 now i already open") for this task. No report existed. Progress receipt: `report/20261005-093051-mt5-connection-detection-progress.md`. The receiver monitor was re-armed in this session.

## Changes

### `app/data/mt5.py`

**`terminal_running()` returns three states:**

| Return | Meaning |
|---|---|
| `True` | Positive evidence that `terminal64.exe` is running |
| `False` | The process list was read successfully and the terminal is absent |
| `None` | The process list could not be read |

- `tasklist` is tried first. If it fails, is denied (e.g. `ERROR: Access denied`, non-zero exit) or returns unrecognised output, a hidden, time-limited (10 s), read-only fallback runs: `powershell.exe -NoProfile -NonInteractive -Command "(Get-Process -Name terminal64 -ErrorAction SilentlyContinue).ProcessName"`.
- No disk search; nothing is launched.

**`connect()`:**
- Requires `True` before calling `initialize()`.
- `False` → "MetaTrader 5 is not running…".
- `None` → "Could not confirm that MetaTrader 5 is running (the Windows process list could not be read), so VC Signal did not call initialize()…".
- Both include `process_check` in the status details.

**New `_api()` guard:** `closed_bars`, `bars_range`, `ticks_range`, `chart_bars`, `discover_gold` and `list_symbols` raise `RuntimeError("MT5 is not connected: <status>")` instead of dereferencing an uninitialised module (`'NoneType' object has no attribute 'copy_rates_from_pos'`).

### `app/scanner.py`

**`resume()`:**
- Reads history only if the feed is healthy.
- Otherwise it clears pause and cancels pending candidates without any history read, sets `_skip_to_latest` and marks the session unhealthy.
- The first healthy scan then jumps `last_m5_close` to the latest closed M5 (the paused period is not processed) and opens a **new** eligibility watermark. Pre-session confirmations still cannot alert.

### `app/web.py`

- **`GET /api/mt5/discover`:** in live mode, if the status or a reconnect is still disconnected/error, returns **503 "MT5 not connected: <reason>"** instead of empty candidates and account. `/api/mt5/symbols` now does the same through the guard.
- **`POST /api/scanner/{pause|resume}`:** unexpected errors become a sanitised 503 instead of HTTP 500.

### `tests/test_live_market.py`

10 new regressions:
- six process-check cases, including the observed tasklist-denied + Get-Process-finds case;
- absent/unverified terminal → no `initialize()` and a clear read error (two cases);
- Resume while disconnected → no exception, nothing initialised; recovery skips the paused period and opens a fresh watermark, with no signals;
- the API: pause/resume return 200 while disconnected, and discover/symbols return 503 with the real reason.

No other files changed; the README was not needed.

## Validation actually performed

**Automated:**
- `.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .tmp/pytest/mt5fix-<ts>`: **112 passed** (102 existing + 10 new; one third-party Starlette deprecation warning).
- The new tests were not run against the old code. The original Resume failure is evidenced by three `AttributeError … copy_rates_from_pos` tracebacks in `.tmp/gold-signals/server.log` from before this fix.

**Real, read-only, this computer:**
- Process check from project Python: in this session `tasklist` returned exit 0 listing `terminal64.exe` PID 9152, and `terminal_running()` → `True`. The tasklist-denied condition Codex saw did not reproduce here; the fallback path is covered by mock tests only.
- `gold.cmd restart` (once): PID 26324 → **42512**; `gold.cmd status` shows mode mt5, scanner on.
- `GET /api/health`: `{"app":"vc-trade-gold-signals","pid":42512,"mode":"mt5","scanner_running":true,"owner":true,"owner_error":null}`.
- `GET /api/state`:
  - **Feed:** `connected` — "Connected to MT5 (read-only), symbol XAUUSDc".
  - **Broker:** Exness Technologies Ltd, server Exness-MT5Real20, account type real, terminal connected. Login and balance were not read into the report.
  - **Symbol:** XAUUSDc, tick 0.001, 3 digits.
  - **Quote:** Bid 4154.479 / Ask 4154.719, spread 0.24, quote time 2026-10-05T02:40:05Z, age 1.7 s, **fresh**.
  - **Last closed:** H1 01:00Z, M5 02:35Z; data issues none.
  - **Scanner:** running, **paused: true** (preserved); strategy state "paused".
  - **Telegram:** configured, **enabled: false**.
- `GET /api/market/bars`:
  - H1 available: last closed 00:00Z (close 4156.435) and 01:00Z (close 4160.138), plus a forming bar.
  - M5 available: 02:30Z (close 4154.633) and 02:35Z (close 4154.547), plus a forming bar.
- No errors logged since the restart marker.

**Not performed:**
- A real Resume on the live scanner: the paused state was to be preserved, and resuming is the user's choice.
- Reproducing the tasklist-denied condition on this machine: it does not occur in this session's environment.
- Telegram actions: none were authorised.

## Remaining issues

- The scanner is **paused**. Live analysis and alerts resume only when the user presses **Resume**. Telegram delivery stays off until the user enables it.
- Carried over from earlier reports, outside this task: XAUUSDc's 0.001 tick makes the tick-based strategy defaults (2-tick sweep / SL buffer = $0.002) much tighter than intended.

## Questions, missing requirements, or blockers

None.
