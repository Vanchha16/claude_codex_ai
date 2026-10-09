# Activate the reviewed M5 stop policy

Task ID: 20261009-105101-activate-m5-spread-aware-stop
Delivery status: APPROVED FOR EXECUTION
User authorization: User explicitly said “send it” after reviewing this exact activation draft. Approval covers one controlled restart and natural execution/delivery under the existing demo-account defaults and unchanged settings with the reviewed new M5 policy.
Published at: 2026-10-09T03:54:51.9595149Z
Approved draft SHA256: 878FC2DFCE9B58E56DEB37323A8DEA9A0FD2AD6BE63E41DE38355AD78BD1811D
Project root: E:\VideCode\vc_trade
Source prompt: `prompt/20261009-105101-activate-m5-spread-aware-stop.md`
Report path: `report/20261009-105101-activate-m5-spread-aware-stop-report.md`
Progress path: `report/20261009-105101-activate-m5-spread-aware-stop-progress.md`

## Goal and reviewed state

Load the implemented M5 spread-aware common-stop policy with one controlled launcher restart. The completed implementation is `report/20261009-103608-m5-spread-aware-stop-report.md`; read the Codex review beside it. Independent checks passed 103 backend and 64 frontend tests; Claude's full backend run passed 393 tests. No implementation changes are required in this activation task.

Read-only state at review: old dual version `FVG-Dual-M15-M5-Immediate-v2-RR2@f4b7f7a5` is running; MT5 MetaQuotes-Demo account, XAUUSD; automatic execution ON through the existing demo-account default; $10 planned risk per basket. The implementation was approved only for code and isolated testing, so this draft separately requests live activation.

Approval of this task authorizes the controlled restart and continuation of natural automatic execution/delivery under the existing demo-account defaults and unchanged settings, with the new M5 policy. It does not authorize manual/test orders, retroactive entry on screenshot gaps, fabricated signals, consent migration, risk changes, or manual Telegram messages.

## Implementation boundaries

1. Confirm the reviewed implementation report is complete and its code is present; no other implementation task may be active. Do not reimplement, broadly change code, commit or push.
2. Inspect the running app read-only and privately capture source/symbol/account/server binding, execution and Telegram status, risk, strategy version, scanner health, owner state and currently open/unresolved baskets. Record configuration hashes without exposing credentials or session tokens. If the source, symbol or account materially differs from the reviewed MetaQuotes-Demo/XAUUSD context, report that change before dependent activation; do not edit account bindings or consent to force activation.
3. Perform exactly one controlled restart through the established launcher: `.venv/Scripts/python.exe -m app.launcher restart`. Follow the existing project restart/owner-lock procedure, avoiding a second scanner. Do not reset stores, remove exposure journals, alter watermarks manually or manipulate live orders. Existing reconciliation handles exposure and the normal startup establishes a fresh session watermark.
4. Verify read-only that the active version is `FVG-Dual-M15-M5-Immediate-v2-RR2@a2d893f0` and both engine versions end in `@a2d893f0`. M5 scope must describe the spread-aware policy; M15 scope must describe the fixed two-tick policy. The whole-config digest changes both version labels, while M15 behavior stays fixed.
5. Verify MT5 feed and scanner health, fresh quote when the market provides one, fresh startup watermark, and preserved account/source/symbol, $10 risk, execution status and Telegram settings. Compare config hashes. Read logs for startup/reconciliation errors. Do not claim live order success merely because startup succeeds.
6. Preserve historical records and all version-bound consent. Do not transfer old explicit consent to the new version or toggle execution. On the reviewed demo account, the existing demo default may retain ON; report the actual post-restart state. If execution remains OFF or health blocks natural execution, report why rather than overriding it.
7. The screenshot FVGs were already decided and remain historical; they must not be retried. Natural signals may occur for new qualifying closes after the fresh watermark. Other qualification, freshness, spread, broker-volume/distance, risk, capacity and send-boundary checks continue to apply.

## Acceptance and reporting

No repeat full-suite runs are needed unless activation reveals a code issue. This is runtime verification of already tested code. Clearly separate independently observed runtime state from the implementation's isolated examples. Do not send a test signal/order/message just to demonstrate the change.

Acknowledge in the exact progress path. Publish a complete report atomically with task ID/source, command and restart outcome, old/new versions, actual health and setting preservation, watermark/reconciliation evidence, configuration hash comparisons, and any remaining blocker. Keep artifacts inside this project. Stop after reporting and wait for the next separately approved task.
