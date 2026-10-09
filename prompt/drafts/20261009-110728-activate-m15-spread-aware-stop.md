# Activate spread-aware stops for both dual engines

Task ID: 20261009-110728-activate-m15-spread-aware-stop
Delivery status: DRAFT — DO NOT EXECUTE
User authorization: pending
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261009-110728-activate-m15-spread-aware-stop.md`
Report path: `report/20261009-110728-activate-m15-spread-aware-stop-report.md`
Progress path: `report/20261009-110728-activate-m15-spread-aware-stop-progress.md`

## Goal and reviewed state

Load the reviewed M15 extension with one controlled launcher restart. Read `report/20261009-110034-m15-spread-aware-stop-report.md` and its Codex review. Independent focused backend tests: 130 passed; frontend: 65 passed. Claude's full suite had 398 passed and the two recurring MT5-time test failures; no time/feed code changed, and their cause remains unresolved. Do not expand this activation task into a test-fixture repair.

The current live dual version is **@a2d893f0**: M5 spread-aware, M15 fixed. The reviewed code version **@dc9ff475** uses spread-aware stops for both engines and preserves M5 behavior. Both keep three original 1/50/80% entries, common stop based on the measured spread, per-leg 1:2 targets and the configured $10 planned risk per basket.

Approval authorizes one controlled restart and natural execution/delivery with the new M15 policy under the existing MetaQuotes-Demo/XAUUSD demo-account defaults and unchanged settings. Manual/test orders, messages, account/consent/risk changes and retroactive trading are outside scope.

## Activation and verification

1. Confirm implementation/report/review are complete and no other implementation is active. Inspect running app read-only; capture current version, actual source/symbol/account/server, scanner/quote health, execution/risk/Telegram state, open/unresolved baskets, owner state and configuration hashes without exposing tokens or credentials. If the reviewed MetaQuotes-Demo/XAUUSD context materially differs, report before dependent activation rather than changing bindings or consent.
2. Perform exactly one restart with `.venv/Scripts/python.exe -m app.launcher restart`, following the established launcher/owner-lock procedure. No second scanner, store reset, manual watermark change or live order manipulation. Normal startup/reconciliation establishes a fresh watermark and preserves existing exposure.
3. Verify the active dual version is `FVG-Dual-M15-M5-Immediate-v2-RR2@dc9ff475`; both engine versions end in **@dc9ff475**. Both per-engine scopes must describe the spread-aware common-stop policy. Verify live MT5 connection, running/unpaused scanner without errors, fresh quote when available, fresh startup watermark, actual execution status, $10 planned risk and preserved Telegram state. Inspect startup/reconciliation logs and compare configuration hashes.
4. Preserve all historical records and version-bound consent. Do not migrate explicit consent or toggle execution to force ON. On the reviewed demo account the existing demo default may retain ON; report what actually occurs. Any different execution state or health blocker must be explained rather than overridden.
5. Existing screenshot/history gaps remain decided and cannot be retried. Only new qualifying closes after the new watermark are actionable. No test orders/signals/messages to demonstrate success. All remaining qualification, quote/spread, sizing, broker-distance, risk, capacity, idempotency and send-boundary checks remain in force.

## Report

Acknowledge in the exact progress path. No repeat full-suite run is required for this runtime-only task unless an activation code issue appears. Publish a complete report atomically with task ID/source, restart command/outcome, actual old/new versions, both scopes, setting/hash preservation, startup watermark/owner/reconciliation evidence and remaining blockers. Distinguish healthy startup from a real new-policy broker outcome. No code changes, commits/pushes or global installs. Keep artifacts in the project. Stop after reporting.
