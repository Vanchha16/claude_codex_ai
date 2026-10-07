# Codex review: verified FVG demo activation and MT5 time correction

Author: Codex
Task ID: 20261007-143838-fvg-demo-time-fix-activation
Source prompt: `prompt/20261007-143838-fvg-demo-time-fix-activation.md`
Claude report: `report/20261007-143838-fvg-demo-time-fix-activation-report.md`
Reviewed: 2026-10-07T14:53:30

## Outcome

Accepted for the approved scope. FVG rr2 is selected AND running on MetaQuotes-Demo, demo, XAUUSD, with corrected fresh quote/candle times. The backend was restarted by Claude as authorized. Automatic execution and Telegram are OFF; no arming or trading was part of this task. The strategy is in M15 warm-up, not ready to qualify new setups yet.

## Independent validation

- Full backend: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-codex-fvg-time-activation-20261007 --junitxml=.tmp/fvg-demo-activation-codex-review/backend-tests.xml`: 255 tests passed, zero failures/errors/skipped, suite time 22.896 seconds. One installed Starlette/httpx deprecation warning. Execution/delivery tests use fake brokers and mocked delivery.
- Read-only actual dashboard checks at 07:48:14Z and 07:50:33Z confirmed FVG rr2, MT5 mode, MetaQuotes-Demo demo account, XAUUSD, fresh quotes, no owner error, automatic execution OFF, risk preference 10 USD and Telegram disabled. The latest health read confirms owner=true, scanner_running=true, PID 18424.
- Quote changed from a three-hour future timestamp to current UTC with age 0.3-0.4 seconds in these checks.
- Actual M5 chart API at 07:50:33Z returned 120 closed candles, newest open 07:45Z / close 07:50Z, and a separately flagged forming candle open 07:50Z. Before the fix, 36 recent candles were incorrectly excluded and the forming candle was three hours ahead.
- Readiness at the recorded check: 39/50 contiguous M15 candles, ready=false, last M15 close 07:45Z, next close 08:00Z. No fabricated setup or order was used as validation.
- The same-server account-switch gap found in the in-task Codex note is fixed in the final source. The passing scanner-level regression confirms the account change triggers reconnect and a new, later session watermark without exposing the login.
- Verified unchanged hashes for FVG rules, lot sizing, fixed-risk config, launcher and dashboard JavaScript. Reviewed the shared UTC helper, explicit server mapping, feed/executor wiring, stale/future guards and history/expiry conversions.
- Confirmed no `.tmp/gold-signals/fvg_execution_optin.json` exists. No real broker preflight/send, arming, Telegram send, restart or strategy mutation was performed by Codex; Claude performed the approved selection/restart. Codex read only local status/market data and used fake modules for reproduction/tests.

Evidence is under `.tmp/fvg-demo-activation-codex-review/`: before/after runtime JSON, same-server account reproduction, JUnit test results and final source hashes. No credentials or account login were recorded.

## Implementation and limits

The correction is explicit for the exact MetaQuotes-Demo server, currently +3 hours. It is not learned from the last tick and does not make stale ticks fresh. Other servers retain documented UTC behavior unless explicitly configured. The source applies one conversion on incoming quotes/rates and outgoing ranges; the executor uses the feed's same base and rejects a server mismatch.

Actual broker pending-order expiry/history behavior has not been exercised through an order. Expiration using the broker time base is an inference documented by Claude and tested with fake modules; retain this limitation before any later automatic-order arming. This review accepts strategy scanning activation, not real-order validation.

If the server clock changes, the explicit offset needs re-verification; stale/future guards then prevent actionable quotes. No universal broker/DST rule or profitable trading edge is established by this task.

Claude's approximate warm-up ETA of 10:45Z is one candle later than the simple recorded count implies: from 39 candles at the 07:45Z close, 11 additional M15 closes would reach 50 at 10:30Z if uninterrupted. Prefer the live readiness counter rather than promising a wall-clock readiness time.

Normal startup/scanning updates operational metadata/events in the existing state directory. The preservation requirement concerns historical records and timestamps; no manual history rewrite or replay tuning was authorized or performed in the reviewed code.

## Permission status and completion

The task's report records no permission rejection: strategy selection and the normal launcher restart succeeded. The earlier Production Deploy rejection was not repeated or bypassed. There are no unresolved blockers for the approved activation task. Automatic-order arming remains OFF and is outside this task.
