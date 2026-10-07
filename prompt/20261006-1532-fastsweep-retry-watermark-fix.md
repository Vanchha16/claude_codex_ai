# Complete the approved FastSweep activation: fix retry watermark bypass

Task ID: 20261006-1532-fastsweep-retry-watermark-fix
Delivery status: APPROVED FOR EXECUTION
User authorization: On 2026-10-06 the user explicitly instructed "Approve let active new" and selected "1:2 - risk 1, target reward 2". This is the necessary correction to complete that already-authorized activation under its original strict session-watermark acceptance requirement. No new trading rules, profile choice or expanded objective is authorized. Do not request approval again for this existing scope. The parent activation report says it could not read Codex's mid-task verification note because Claude Code's permission system denied the read; this new unchanged file delivers that reproduced bug as a fresh handoff, without changing or bypassing any permissions.
Project root: E:\VideCodec_trade
Source prompt: `prompt/20261006-1532-fastsweep-retry-watermark-fix.md`
Report path: `report/20261006-1532-fastsweep-retry-watermark-fix-report.md`
Parent task: 20261006-151121-activate-fastsweep-live
Selected live profile: rr2, risk:reward 1:2; already active

## Exact required correction

Read the completed parent report and this complete new prompt. Do not try to read any denied file or override permissions. Acknowledge in report/20261006-1532-fastsweep-retry-watermark-fix-progress.md. This file contains the full verification note; reading the modified parent prompt is unnecessary.

The missing eligibility check is in FastSweepEngine.retry_awaiting / _confirm. A pending candidate can already have confirm_close persisted while waiting for the first executable post-close quote. Recreating the engine after restart sets eligible_after later than that confirm_close, but retry_awaiting still calls _confirm and creates a signal. The normal process_bar watermark check is bypassed because there is no new confirmation bar. This violates the parent task's requirement that confirmations at or before the new session watermark create NO signal, NO daily quota use and NO outbox/send.

Codex independently reproduced it using tests.test_fastsweep_live.scenario and engine:
- Drive only through t0 + 35 minutes (the confirmation bar close), with entry callback quote.time = bar.close_time - 1 second and decision now = bar.close_time + 1 second. The candidate remains pending with confirm_close set and reason awaiting_first_quote_after_close.
- Recreate FastSweepEngine against the same SqliteStore, set eligible_after = confirm_close + 3 seconds.
- Call retry_awaiting with a valid fresh quote and decision time = confirm_close + 5 seconds. Current code creates 1 signal. Required result is zero and reason confirmation_before_session_watermark.
- A local diagnostic database is .tmp/codex-activation-watermark-20261006-1527/t.sqlite. It is NOT live state and already contains the reproduced wrong signal; do not reuse it as clean test input.

Fix the strict eligibility predicate at the common final creation gate (_confirm is appropriate) so EVERY path, including retry, checks confirm_close > eligible_after before signal creation. Context confirmations at/equal/before the watermark must be consumed as rejected, not left pending to retry again. Preserve the valid post-watermark waiting-for-first-quote path and all existing price, quote-age, clock-skew tolerance, cooldown/cap and duplicate rules.

Add regression tests for persisted waiting-for-quote candidates reconstructed with a NEW watermark equal to and later than confirm_close, checking zero signals, unchanged quota and zero outbox/mock sends. Also test ordinary strictly-after-watermark retry still produces exactly one signal. A reconnect/recovery watermark on the same engine must also reject a pre-recovery stored confirmation. No test may send to the real Telegram destination.

## Scope, validation and completion

Change app/fastsweep_live.py and relevant tests only, plus a short documentation note if needed. Do not change active_strategy.json, profile rr2, strategy price rules, EMA warmup, target/stop geometry, feed/source/symbol, delivery opt-in, history, database schema or credentials. Do not create fake live records, manually send a message, reset the cap or place orders.

Run the focused FastSweep replay/live tests (existing Codex run: 39 passed) and regressions for watermarks/reconnect/resume. The parent full suite already passed 152 backend and 28 frontend tests; rerun the backend if needed for the final guard change, but there is no reason to rebuild unchanged frontend assets.

After tests pass, perform one supported restart to load the fix into the existing healthy live server. Verify rr2 remains selected, feed/scanner are healthy and Telegram preference is unchanged. Check that no historical signal or new outbox message was created by restart. No manual sends. Recheck warmup readiness and report it truthfully. If restart cannot start the service, use the parent's supported rollback and report it.

Publish a complete report atomically with matching task ID/source, changed files, exact tests and results, reproduced-before/fixed-after evidence, restart result, actual sanitized API state and signal/outbox counts, and any actual permission denial. If a tool denies a required read/action, say exactly what was denied and do not claim the fix or restart completed. Stop after reporting.
