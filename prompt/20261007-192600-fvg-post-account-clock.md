# Read the execution clock after the final account lookup

Task ID: 20261007-192600-fvg-post-account-clock
Delivery status: APPROVED FOR EXECUTION
User authorization: On 2026-10-07 the user explicitly replied "Send it" to the question identifying this draft, its final account-lookup clock fix, regression tests, and OFF-until-verified scope. Previously authorized final Codex activation remains limited to independently verified MetaQuotes-Demo DEMO/XAUUSD.
Published at: 2026-10-07T12:48:32.1086129Z
Approved draft SHA-256: cfea87d484253c685bf758082535e46c7181f8c8b81608c3ace6b439d92d126e
Project root: E:\VideCode\vc_trade
Source prompt: `prompt/20261007-192600-fvg-post-account-clock.md`
Report path: `report/20261007-192600-fvg-post-account-clock-report.md`
Progress path: `report/20261007-192600-fvg-post-account-clock-progress.md`

## Goal and context

Finish the existing immediate-before-send freshness protection. Read `report/20261007-165801-fvg-send-boundary-account-guards-codex-review.md` and Claude's matching report. All 310 backend tests and the three prior probes pass, but the new account lookup occurs after `clock_now()` was captured. A 45-second lookup delay causes a stale pending request before the following iteration stops.

Exact fake reproductions: `.tmp/fvg-boundary-codex-review/verify.py`, results in `.tmp/fvg-boundary-codex-review/run-20261007-121919/additional-probes.json`. Do not reuse their persistent SQLite paths.

Codex found execution already ON, then restored OFF through the normal authenticated control after failed verification. Keep OFF throughout implementation/restart. Final Codex activation on verified MetaQuotes-Demo DEMO/XAUUSD is already authorized once checks pass.

## Scope and implementation

Change `app/fvg_execution.py` and focused regression tests only. Sample the existing injected/monotonic clock AFTER the final potentially blocking `account_info()` lookup, then evaluate confirmation freshness/future time, setup expiry and pending expiry directly before the API call. Passing a precomputed timestamp into a blocking helper is insufficient. Preserve the immutable account check after the durable journal write.

Known uncalled legs must remain not_sent, first-call refusal rejected, earlier accepted legs partial and retained, crash/unknown outcomes reconciled, repeat submit never resent. Preserve all new original-account cancellation/evidence guards and every existing risk/strategy/default/consent/Telegram rule. No strategy or policy changes; no helper-tool edits, global installs, commits or pushes.

## Acceptance criteria

Use deterministic fake brokers, injectable clocks and fresh fixtures. Regressions must fail against the current reviewed code:

1. Final account lookup before leg 1 advances 45 seconds: zero calls, all not_sent, rejected.
2. Final account lookup before leg 2 advances 45 seconds: exactly one timely call, accepted first leg retained, remaining not_sent, partial, no resend on repeat.
3. Setup or pending deadline crossed during the final account lookup is refused even while confirmation age remains <=30 seconds.
4. Existing exact 30-second equality, timely three-call submission, account-switch and cancellation recovery regressions remain passing.

## Validation and runtime

Run focused regressions then full backend pytest using a fresh basetemp inside `.tmp/`. Keep tests deterministic; no sleeps or live broker preflight/order/removal, injected signals, test Telegram messages, terminal switching or competing MT5 initialize/login. Never execute `tools/mt5_test_order.py` or print credentials/private identifiers.

If needed restart with the normal launcher while preserving OFF. Verify read-only runtime on MetaQuotes-Demo DEMO/XAUUSD, healthy FVG RR2, ready/fresh data, 10 USD risk, Telegram ON, auto OFF and disclose baskets/setups/unresolved exposure. Do not clear override files or activate. Codex will independently verify and perform the already-authorized final activation. No frontend build needed unless assets change.

## Reply and stopping condition

Claude implements; Codex coordinates/reviews. Acknowledge at the progress path, publish the complete matching report atomically from an in-project temporary file, and stop. Include changed files, before/after regressions, actual focused/full test results, sanitized runtime OFF, and practical external account-switch limits. No self-dispatched follow-up.
