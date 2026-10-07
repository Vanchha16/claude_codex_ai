# Fix MT5 detection and disconnected Resume

Task ID: 20261005-093051-mt5-connection-detection
Delivery status: DRAFT — DO NOT EXECUTE
User authorization: pending
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261005-093051-mt5-connection-detection.md`
Report path: `report/20261005-093051-mt5-connection-detection-report.md`

## Goal and context

The user requested project startup, confirmed MT5 is running, then invoked agent-to-agent. VC Signal serves http://127.0.0.1:8000/ with HTTP 200, but incorrectly reports the terminal is absent.

Codex observations on October 5:
- tasklist /FI "IMAGENAME eq terminal64.exe" /NH reports ERROR: Access denied.
- Get-Process -Name terminal64 finds PID 9152 at C:\Program Files\MetaTrader 5\terminal64.exe.
- Project Python can run powershell.exe -NoProfile -NonInteractive -Command '(Get-Process -Name terminal64 -ErrorAction SilentlyContinue).ProcessName', returning terminal64 and exit code 0.
- terminal_running() in app/data/mt5.py mistakes failed tasklist enumeration for absence.
- GET /api/state shows saved mt5/XAUUSDc, disconnected feed, no quote, scanner running but paused, Telegram disabled.
- Server log: Resume -> _set_watermark_to_latest -> MT5Feed.closed_bars crashes with AttributeError because self._mt5 is None.
- GET /api/mt5/discover returns empty candidates/account despite connection failure.

Claude readiness is dated October 2; current receiver readiness is not confirmed. This draft authorizes no execution.

## Scope and relevant files

app/data/mt5.py, app/scanner.py, app/web.py for this connection flow; focused regressions in tests/test_live_market.py, tests/test_scanner.py, tests/test_api.py and existing mocks. README.md only if needed.

Preserve source/symbol, paused state during restart, Telegram settings, strategy rules and history. Historical outcome-expiry findings are outside this task.

## Implementation plan

1. Read existing handoff instructions and relevant source/tests.
2. Distinguish failed process enumeration from a successful empty list. Add a bounded hidden read-only fallback for denied/unavailable tasklist; the demonstrated Get-Process command is one option. Require positive evidence of terminal64.exe before initialize(). Never launch an absent terminal, search disk for terminals or read broker credentials.
3. Make disconnected/uninitialized Resume safe. Defer healthy-feed history reads as necessary. Preserve fresh-session eligibility and prevent alerts from pre-session confirmations.
4. Surface failed discovery connections accurately instead of a misleading successful empty result.
5. Add regressions for denied tasklist with a visible terminal, actual absence/fallback failure without initialize calls, disconnected Resume/recovery, and failed discovery as appropriate.
6. Run relevant checks, then gold.cmd restart once. Verify saved XAUUSDc connection read-only; preserve paused state and disabled Telegram. If real IPC access is denied, report the precise limitation and user-run launch command. Do not weaken guards or change machine permissions.

## Acceptance criteria

- Detect the running terminal under observed tasklist-denied conditions.
- Absence/inability to positively detect the process never triggers initialize() and terminal launch.
- Disconnected Resume avoids HTTP 500/uninitialized-module dereference; recovery establishes a safe new eligibility watermark.
- Failed discovery reports a clear diagnostic.
- Keep exact symbol XAUUSDc; no silent alternate contract.
- Restarted dashboard is healthy. Report actual connection, quote freshness, H1/M5 history, or remaining IPC/broker/configuration blockers.
- No orders, Telegram messages/enable actions, global installs, unrelated changes or machine-permission changes.

## Validation

Use .venv/Scripts/python.exe with project-local temporary directories. Run focused affected tests and any checks required by changed behavior. Real read-only checks: process presence, gold.cmd status, GET /api/health, GET /api/state, GET /api/market/bars for H1/M5. Never print broker login/balance, bot token, session token or other secrets. Distinguish mock results from real connectivity.

Report actual checks separately from unavailable checks. Keep work/downloads/caches/temporary artifacts inside this project. Verify absolute targets before recursive deletion/moving; never follow links outside the project.

## Reply and stopping condition

Claude implements; Codex plans and reviews. Write material questions/blockers to the exact report path and stop dependent work. Do not invent requirements or start another task.

Report task ID, source prompt, outcome, changed files, actual validation and remaining issues. Publish the complete report through a project-local temporary file and rename if supported. Stop and wait for the next separately approved task.
