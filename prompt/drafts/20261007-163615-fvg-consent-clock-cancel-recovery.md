# Complete FVG account consent, decision-time freshness and cancellation recovery

Task ID: 20261007-163615-fvg-consent-clock-cancel-recovery
Delivery status: SUPERSEDED - DO NOT EXECUTE
User authorization: pending dispatch approval. The user selected "Require fresh arming for each account/server (Recommended)" after Claude disclosed the conflicting demo-default feature. This settles the policy; it does not itself dispatch this follow-up task.
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261007-163615-fvg-consent-clock-cancel-recovery.md`
Report path: `report/20261007-163615-fvg-consent-clock-cancel-recovery-report.md`
Progress path: `report/20261007-163615-fvg-consent-clock-cancel-recovery-progress.md`

Superseded by: `prompt/drafts/20261007-164056-fvg-demo-default-clock-cancel-recovery.md` after the latest user instruction "let set auto excute on default". Historical contents below are no longer the selected policy.

## Goal and context

Complete the previous approved hardening task by correcting three independently verified acceptance failures. Read the original task `prompt/20261007-161242-fvg-basket-review-fixes.md`, Claude's matching report, and `report/20261007-161242-fvg-basket-review-fixes-codex-review.md` in full.

The updated FVG RR2 process is running on MetaQuotes-Demo demo/XAUUSD, auto OFF, Telegram ON, fixed 10 USD total risk, fresh data, no baskets/setups at the last review. Codex independently ran 288 backend and 36 dashboard tests, all passing, but the residual fake probes show failures outside that coverage. Do not claim all criteria complete until these are corrected and covered.

Preserve the confirmed strategy: M15 trend/FVG qualification, 50-bar warm-up, M5 retest then separate continuation confirmation, three 1/50/80% limits, common wick far-edge SL+two ticks, per-entry 1:2 TP, independently floored lots sharing 10 USD nominal risk, existing accepted-basket cooldown/cap/pending-expiry semantics, spread+one-tick eligibility and correct-side placement checks. No strategy retuning or risk redistribution.

## Scope and relevant files

- `app/web.py`, `config/fvg_execution.json`, narrowly relevant dashboard/README text: exact account-bound consent only.
- `app/fvg_live.py`, `app/fvg_execution.py`, `app/scanner.py` only as needed: trustworthy current decision time, final execution expiry check, durable invalidation with pending cancellation recovery.
- Focused regression tests under `tests/`, especially `test_fvg_review_fixes.py`, executor/engine/API/scanner suites.

Do not modify helper tooling, execute `tools/mt5_test_order.py`, commit/push changes, install global tools or alter unrelated settings. Preserve existing uncommitted work and historical state. Keep all artifacts inside this workspace; never print credentials, session tokens, login/bot/chat identifiers, .env contents or entire private state files.

## Implementation plan

### A. Enforce the user's fresh account/server arming choice

Require a saved opt-in matching current source, symbol, strategy version and canonical server-plus-login identity for submission on **every** account type. Remove the demo default automatic-ON fallback. Set the demo-default configuration false/remove its authorization semantics and update misleading docs/UI as appropriate; do not leave a path that a true legacy flag can use to arm an unrelated account.

An absent or mismatched opt-in is OFF even if `default_on_for_demo_accounts` is true and no user-OFF marker exists. Exact current consent may persist across restart, and existing other-account execution journals must remain recoverable on their proper account. Legacy login-only consent remains invalid. Do not rearm anyone automatically or silently upgrade consent.

Tests must exercise actual workstation/API decision paths, not only hash inequality: explicit demo A consent; same-login different-server demo B; different-login same-server; unarmed demo, real and contest accounts; legacy consent; explicit OFF; valid exact consent; restart persistence. Demonstrate that no executor/order submission is made for an unarmed switched account after the global OFF marker would have been cleared by legitimate arming A.

### B. Use current decision time and enforce freshness at sending

The remaining failure: `_on_confirmed()` tests the supplied scan-start `now`, then fetches `(quote,current_time)` and discards current_time. Executor freshness uses the actual current clock for quotes, but receives no confirmation/expiry context, so an old confirmation can be sent on a fresh quote.

Obtain a trustworthy current decision clock before capacity/reservation/alerts; use the existing live entry callback's current-time result or an explicit injectable current clock, not the quote timestamp. Carry immutable confirmation close, setup deadline and max-age context into execution. Recheck 30-second confirmation age, future timestamps and setup/pending expiry at the final submission boundary, including after slow preflight and immediately before first send. Stale/expired context must produce no new send and remain consumed/idempotent.

If a batch has already accepted or potentially sent a leg when eligibility expires, preserve that journal and open reconciliation state, stop sending remaining legs, and never mislabel accepted/uncertain exposure as preflight rejection or blindly resend. Use current time for creation/placement/pending-expiry semantics rather than granting stale context a new lifetime. Preserve normalized MT5/feed time and the existing quote guards.

Tests: scan-start=confirmation+1 s, entry callback/executor current clock=confirmation+121 s with fresh quotes must create zero executable basket/alert/request; slow `order_check` advances an injectable clock across 30 s or setup expiry before first send; a delay between sends must preserve accepted/unknown legs without sending stale remaining legs. Keep 30 s equality allowed, 31 s/future rejected and timely valid setup behavior. Use deterministic independent clocks; no real sleeps or broker calls.

### C. Preserve invalidation and retry unresolved pending cancellations

The remaining failure: a timeout removal returns `cancel: unknown`, then the engine writes `zone_invalidated_at`; subsequent maintenance permanently excludes that basket and never resolves/removes the still-live owned remainder after recovery.

Separate the durable detection of zone invalidation from proof that cancellation is complete. Preserve the invalidation event even if price returns inside or old bars leave the history window. Continue recovery for the basket while owned pending remainders are unresolved, including through pause/resume and broker reconnection on the correct original account.

Before retrying any unknown removal, query authoritative current broker state and verify that the exact owned ticket remains pending on the correct bound account. Queries returning None/errors mean unknown, not zero pending orders. Retry verified still-owned remainders with bounded cadence; do not send a blind duplicate trade or close/modify positions. A successful removal may still race a fill: preserve partial/full positions, SL/TP and the new fill-reconciliation behavior. Cancellation is complete only when reliable broker evidence shows no owned pending remainder; unknown histories/read failures remain visible and tracked.

Use valid closed M5 bars to detect new invalidation. Retry a durably detected invalidation without requiring another far-edge breach. If the account is unavailable, retain the state until the original account returns. Keep repeated failure logs bounded.

Tests: timeout/connection error followed by recovery and a return inside; explicit removal rejection with still-live order; None order/history query; unknown removal that actually succeeded (no duplicate removal once disappearance is proven); partial fill during retry; account/server switch refusing cancellation and return restoring recovery; invalid raw M5 bars not generating an invalidation; no new setup/order/alert caused by maintenance.

## Runtime boundary

Keep automatic execution OFF throughout and after the task. Do not clear the user's OFF marker or arm a new consent. Preserve Telegram's ON preference and fixed risk 10 USD. Check current runtime/context before changes using bounded read-only API observations, avoiding a competing MT5 session.

After focused/full checks pass, a normal restart through the existing launcher to load the corrections is authorized with task dispatch. If actual exposure or ownership migration creates a blocker, report it and preserve broker orders/journals. No real `order_check`, `order_send`, cancellation, manual test-order tool or external test message is authorized for validation. Fake brokers/feeds/delivery only. Do not change terminal accounts/settings.

Final read-only runtime verification must show fresh FVG RR2 demo data, scanner health, actual auto OFF, Telegram preference preserved, $10 budget and readiness. Report actual observations; do not claim successful live broker fills/expiry or profitability.

## Acceptance and validation

All three independent counterexamples below must be prevented, with meaningful isolated regressions that fail against the currently reviewed code:

- `.tmp/fvg-basket-fixes-codex-review/residual-reproduction-results.json`: one timed-out removal remains pending after recovery, and a 121-second-old confirmation submits three orders.
- `.tmp/fvg-basket-fixes-codex-review/default-demo-consent-reproduction.json`: mismatched demo B becomes ON through the demo default.
- `.tmp/fvg-basket-fixes-codex-review/reproduce-residuals.py`: reviewer probe logic; do not reuse its persistent SQLite paths. Add isolated fixtures instead.

Run focused relevant regressions and full backend: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-20261007-163615-fvg-consent-clock-cancel-recovery` with a fresh local test directory. Existing tests must still pass for genuinely timely eligible three-order setups. Run frontend tests/syntax and any required asset build if changed; no unrelated helper suite or optimization needed.

Keep real operations distinct from fake tests, source inspection, inferred coverage and unavailable checks. Do not mask regressions by widening the approved 30-second age, removing spread guard, changing the SL, raising risk, ignoring account changes or assuming that elapsed time proves an uncertain order absent.

## Reply and stopping condition

Claude is implementer; Codex is planner/reviewer. Acknowledge only the approved execution prompt at the exact Progress path. If material requirements are blocked, write the precise questions at the Report path and stop dependent actions.

Publish the final complete report atomically at `report/20261007-163615-fvg-consent-clock-cancel-recovery-report.md` with task ID/source, files changed, actual tests and coverage for A/B/C, disarmed consent state, runtime/restart observations, unchanged risk/rules, zero actual test orders/checks/cancellations/messages and unresolved limitations. Stop after reporting; a new arming instruction is separate.
