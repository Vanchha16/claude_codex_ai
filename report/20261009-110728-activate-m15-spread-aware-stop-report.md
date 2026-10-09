# Report: 20261009-110728-activate-m15-spread-aware-stop

- Task ID: 20261009-110728-activate-m15-spread-aware-stop
- Source prompt: `prompt/20261009-110728-activate-m15-spread-aware-stop.md`
- Report path: `report/20261009-110728-activate-m15-spread-aware-stop-report.md`
- Implementer: Claude
- Outcome: **ACTIVATED.**
  - One controlled launcher restart.
  - Live dual version is now `@dc9ff475`, with spread-aware stops on both engines.
  - Account, source, symbol, risk, execution and Telegram settings are preserved.
- Not done: no code changes, commits, pushes, test/manual orders or messages, consent/risk/config edits, store or watermark edits.

## Preconditions (read-only, ~06:35:50Z)

- The implementation report `report/20261009-110034-m15-spread-aware-stop-report.md` and its Codex review are present. No other implementation task was active.
- Running app (PID 13004):
  - Account/source/symbol: live MT5, **MetaQuotes-Demo** (demo, USD), **XAUUSD**.
  - Strategy **`@a2d893f0`**. Scopes: M15 "fixed: 2 ticks beyond the far edge"; M5 spread-aware.
  - Auto execution **ON** via `default (demo account)`, `armed_at null`; risk **$10**/basket; Telegram **enabled**.
  - Scanner running and not paused, no error; watermark 03:56:01Z.
  - Quote fresh, spread 0.30. **No open or unresolved baskets**; daily accepted **3/4**.
- The context matched the reviewed one.

### Recorded for context: live outcomes under `@a2d893f0` since 03:56Z

These are real records, read-only. I did not act on them.

| Basket | Placed | Zone | Stop | Execution |
|---|---|---|---|---|
| `FVG5-0ce92ed6135eb330` (M5 BUY) | 04:30Z | 4180.12–4181.67 | **moved 2 ticks** (base 4180.10 → SL 4180.08, measured spread 0.34) | submitted; all three legs filled and **closed_sl** |
| `FVG5-cc769e42dd8f8505` (M5 BUY) | 05:05Z | 4178.41–4181.81 | not moved | **preflight_rejected** |
| `FVG5-c6753592f99ef818` (M5 BUY) | 05:40Z | 4192.29–4199.17 | not moved | **preflight_rejected** |

- **4:30 basket:** legs 0.02 / 0.04 / 0.09 lots; broker P&L −3.14 / −3.24 / −3.15 (≈ −9.53 total, within the $10 nominal budget). This was the first real broker outcome with a spread-adjusted stop.
- **The two refused baskets:**
  - Reason (both): "entry 1 cannot fit the minimum lot within its 3.33 risk share".
  - The cause is wide zones, which make leg 1's stop distance too large for 0.01 lot within its $3.33 share. This is the existing minimum-lot rule, not the stop policy.
  - These refused baskets still count toward the daily cap, which is why it shows 3/4 (see the earlier review finding about preflight-refused baskets consuming capacity).

## Restart

- Command: `.venv/Scripts/python.exe -m app.launcher restart` (exactly once), exit 0.
- Output: "Stopped … (PID 13004)" → "running in the background … (PID 20836)".
- `launcher status`: "Running … (PID 20836, mode mt5, scanner on)", a single server.

## Post-restart state (observed ~06:36:25Z)

| Item | Before | After |
|---|---|---|
| Dual version | `…@a2d893f0` | **`FVG-Dual-M15-M5-Immediate-v2-RR2@dc9ff475`** |
| Engine versions | `…-M15-…@a2d893f0`, `…-M5-…@a2d893f0` | **`FVG-Immediate-M15-v2-RR2@dc9ff475`**, **`FVG-Immediate-M5-v2-RR2@dc9ff475`** |
| M15 scope | fixed: 2 ticks beyond the far edge | **spread-aware**: 2 ticks beyond the far edge, moved further outward by whole ticks when needed so every leg is >= spread + 1 tick from it |
| M5 scope | spread-aware | **spread-aware** (same text as M15) |
| Account / symbol | MetaQuotes-Demo, demo, connected, XAUUSD | same |
| Auto execution | ON, default (demo account) | **ON**, default (demo account), armed_at null, no reason |
| Risk | $10, USD | $10, USD |
| Telegram | enabled (restored explicit opt-in 2026-10-07) | same |
| Scanner | running, no error | running, not paused, no error |
| Session watermark | 03:56:01Z | **06:36:25.695823Z (startup)**, fresh |
| Quote | fresh, spread 0.30 | fresh, bid 4189.91 / ask 4190.34, spread 0.43 |
| Open baskets / slots | none / free | none / free; daily 3/4 (Bangkok date, unchanged) |

- **Events:** "session watermark 06:36:25.695823Z (startup) …"; "VC Signal started: LIVE MT5 (XAUUSD); strategy FVG-Dual-M15-M5-Immediate-v2-RR2@dc9ff475; external delivery ON (restored explicit opt-in)".
- **Server log** (PID 20836): clean startup; 0 error, traceback, exception or warning lines.
- **Reconciliation:** no open or unresolved baskets existed, so there was nothing to reconcile. The owner field is not exposed by `/api/state` (null). The launcher reports a single running instance.

## Configuration hashes (SHA-256 prefix, before = after)

| File | Hash |
|---|---|
| config/active_strategy.json | 561a46f3a18e2fb1 |
| config/fvg_execution.json | e2b08d935710a644 |
| config/fvg_risk.json | 8eb76bea8adca7c6 |
| config/local_settings.json | 9b477c436000640a |
| config/mt5_time.json | bb9770ec738fa056 |
| config/strategy.json | 223da3eff4729967 |
| fvg_execution_optin.json | e97122b253702229 |
| delivery_optin.json | 38faa91a02380b1a |
| fvg_execution_user_off.json | missing |
| .env | missing |

No differences. Consent and historical records are untouched.

## Evidence separation

- A healthy startup is **not** evidence of a new-policy M15 broker outcome. No M15 basket has been decided under `@dc9ff475` yet.
- The 04:30Z M5 outcome above is a real broker result, but it was under the previous `@a2d893f0` policy (whose M5 numbers are identical).
- Only new qualifying closes after 06:36:25Z are actionable. Earlier gaps stay historical.
- With 3 of the 4 daily baskets already used (Bangkok date 2026-10-09), **only one more basket can be accepted today** across both engines.

## Checks performed

- Read-only API snapshots before and after the restart: `.tmp/act110728/before.json` and `after.json`, from the script `.tmp/act105101/snap.py`.
- Basket and event reads, `launcher status`, and the server log.
- No test suites (runtime-only task; no code issue appeared).

## Blockers / notes

- None blocking.
- The daily cap is nearly used (3/4), partly by two preflight-refused baskets. Changing that rule needs a separate decision.
- Explicit consent for `@dc9ff475` is not recorded. Execution is ON through the existing demo-account default.
