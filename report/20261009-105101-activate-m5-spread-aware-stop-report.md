# Report: 20261009-105101-activate-m5-spread-aware-stop

- Task ID: 20261009-105101-activate-m5-spread-aware-stop
- Source prompt: `prompt/20261009-105101-activate-m5-spread-aware-stop.md`
- Report path: `report/20261009-105101-activate-m5-spread-aware-stop-report.md`
- Implementer: Claude
- Outcome: **ACTIVATED.** One controlled launcher restart. The new dual version `@a2d893f0` is running with the M5 spread-aware stop. Account, source, symbol, risk, execution and Telegram settings are preserved.
- Not done: no code changes, commits, pushes, test/manual orders, Telegram messages, consent/risk/config edits, store resets or watermark edits.

## Preconditions (read-only, before restart, ~03:55:30Z)

- Implementation report `report/20261009-103608-m5-spread-aware-stop-report.md` and the Codex review are present. The code from that task is in the working tree, uncommitted (as approved).
- No other implementation task was pending. The prompts without reports are review notes or instruction documents.
- Running app (PID 33344):
  - Source: live MT5; account server **MetaQuotes-Demo** (demo); symbol **XAUUSD**.
  - Strategy **`FVG-Dual-M15-M5-Immediate-v2-RR2@f4b7f7a5`**.
  - Auto execution **ON**, `armed_by: default (demo account)`, `armed_at: null`; risk **$10**/basket (max concurrent $20); account currency USD.
  - Telegram **enabled** (restored explicit opt-in from 2026-10-07T07:58:07Z).
  - Scanner running, not paused, no error; session watermark 01:48:02Z.
  - Quote fresh, spread 0.49.
  - **No open or unresolved baskets**; daily accepted 0/4.
- The context matched the reviewed MetaQuotes-Demo/XAUUSD context.

## Restart

- Command: `.venv/Scripts/python.exe -m app.launcher restart` (exactly once), exit 0.
- Output: `Stopped VC Signal … (PID 33344)` → `VC Signal running in the background: http://127.0.0.1:8000/ (PID 13004)`.
- `launcher status` afterwards: `Running … (PID 13004, mode mt5, scanner on)`. That is a single server, so no second scanner.

## Post-restart state (independently observed, ~03:56:06Z)

| Item | Before | After |
|---|---|---|
| Dual version | `…@f4b7f7a5` | **`FVG-Dual-M15-M5-Immediate-v2-RR2@a2d893f0`** |
| M15 engine | `FVG-Immediate-M15-v2-RR2@f4b7f7a5` | **`FVG-Immediate-M15-v2-RR2@a2d893f0`** |
| M5 engine | `FVG-Immediate-M5-v2-RR2@f4b7f7a5` | **`FVG-Immediate-M5-v2-RR2@a2d893f0`** |
| Stop-policy scope | (absent) | M15 "fixed: 2 ticks beyond the far edge"; M5 "spread-aware: base stop moved outward by whole ticks until every leg is >= spread + 1 tick from it" |
| Account / source / symbol | MetaQuotes-Demo, demo, live MT5, XAUUSD | same (connected) |
| Auto execution | ON, default (demo account), armed_at null | **ON**, default (demo account), armed_at null, reason none |
| Risk | $10 / basket, $20 concurrent, USD | same |
| Telegram | enabled, restored explicit opt-in | same (event: "external delivery restored … (new signals only)") |
| Scanner | running, no error | running, not paused, no error |
| Session watermark | 01:48:02Z | **03:56:01.199700Z (startup)**, a fresh watermark |
| Quote | fresh, spread 0.49 | fresh, bid 4178.45 / ask 4178.90, spread 0.45 |
| Open / unresolved baskets | none | none; engine slots free, no cooldown, 0/4 today |

**App events after the restart:**
- "session watermark 03:56:01.199700Z (startup): only confirmations closing after it are actionable"
- "VC Signal started: LIVE MT5 (XAUUSD); strategy FVG-Dual-M15-M5-Immediate-v2-RR2@a2d893f0; external delivery ON (restored explicit opt-in)"

**Logs:** the server log shows a clean startup for PID 13004 (`Application startup complete`), with no errors, tracebacks or warnings. There were no open baskets to reconcile, so no reconciliation evidence was expected or produced.

## Configuration hashes (SHA-256, first 16 hex; contents not printed)

| File | Before | After |
|---|---|---|
| config/active_strategy.json | 561a46f3a18e2fb1 | 561a46f3a18e2fb1 |
| config/fvg_execution.json | e2b08d935710a644 | e2b08d935710a644 |
| config/fvg_risk.json | 8eb76bea8adca7c6 | 8eb76bea8adca7c6 |
| config/local_settings.json | 9b477c436000640a | 9b477c436000640a |
| config/mt5_time.json | bb9770ec738fa056 | bb9770ec738fa056 |
| config/strategy.json | 223da3eff4729967 | 223da3eff4729967 |
| state fvg_execution_optin.json | e97122b253702229 | e97122b253702229 |
| state fvg_execution_user_off.json | missing | missing |
| state delivery_optin.json | 38faa91a02380b1a | 38faa91a02380b1a |
| .env | missing | missing |

None of these files changed, and no consent was migrated:
- The saved execution opt-in file was left as it was. It does not match the new version, and execution is ON only through the demo-account default.
- Historical setups and baskets keep their `@f4b7f7a5` versions.

## Separation of evidence

- Everything above is observed runtime state: versions, settings, health, watermark and hashes.
- The levels from the implementation report (SL 4172.64, lots 0.01/0.02/0.06, etc.) are isolated fixture results. They are **not** live outcomes.
- No live M5 basket has been created with the new policy yet. A successful startup does not prove that live orders will succeed.
- The screenshot FVGs closed before the new watermark (03:56:01Z), so they remain historical and will not be retried.
- New signals can only come from qualifying closes after the watermark. All other checks still apply: qualification, freshness, the spread maximum, broker volume and distance, risk, capacity and send boundaries.

## Checks performed

- Read-only GETs of `/api/state`, `/api/fvg` and `/api/events`, before and after the restart. The project-local script is `.tmp/act105101/snap.py`, with outputs in `.tmp/act105101/before.json` and `after.json`. It prints no credentials, login or tokens.
- `launcher status`, and the tail of the server log.
- No test suites were rerun: this task is runtime activation of already-tested code, and no code issue appeared.

## Remaining blockers / notes

- None blocking.
- Explicit dual-version execution consent for `@a2d893f0` is not recorded, which is unchanged. Automatic execution relies on the existing demo-account default, as approved.
- The current spread (0.45–0.49) is near the 0.50 maximum. Above 0.50 the M5 stop is not adjusted, and the executor's spread ceiling refuses execution.
