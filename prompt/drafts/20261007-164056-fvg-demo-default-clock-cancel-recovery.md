# Keep demo auto execution default ON and complete FVG recovery fixes

Task ID: 20261007-164056-fvg-demo-default-clock-cancel-recovery
Delivery status: DRAFT - REQUIREMENTS PENDING - DO NOT EXECUTE
User authorization: pending dispatch approval of this revised task. The latest user instruction is "let set auto excute on default". In the context of Claude's disclosed demo-default feature, this supersedes the earlier choice to require fresh arming for every demo account/server. The user wants automatic execution default ON for DEMO accounts; real/contest accounts still require explicit current-binding arming. Do not execute until this revised task is published as APPROVED FOR EXECUTION.
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261007-164056-fvg-demo-default-clock-cancel-recovery.md`
Report path: `report/20261007-164056-fvg-demo-default-clock-cancel-recovery-report.md`
Progress path: `report/20261007-164056-fvg-demo-default-clock-cancel-recovery-progress.md`
Supersedes unpublished draft: `prompt/drafts/20261007-163615-fvg-consent-clock-cancel-recovery.md`

## Goal and context

Preserve the user's newest demo-default-ON preference and fix the two residual failures discovered after the original hardening task: late decisions can bypass confirmation freshness, and failed pending-order cancellation is never retried after recovery.

Read `prompt/20261007-161242-fvg-basket-review-fixes.md`, its Claude report, and `report/20261007-161242-fvg-basket-review-fixes-codex-review.md`. The consent-removal proposal in that review is superseded by the latest user instruction; the two reproduced recovery defects remain in scope. Do not remove the demo-default policy on the basis of the earlier preference.

The last reviewed running app is MetaQuotes-Demo DEMO, XAUUSD, FVG RR2, auto execution OFF through a persistent temporary OFF marker, Telegram ON, fixed 10 USD total risk, fresh data, no scanner error. `config/fvg_execution.json` already specifies `default_on_for_demo_accounts: true`; the explicit OFF marker currently takes precedence. Codex independently verified 288 backend and 36 dashboard tests pass, but the two residual fake probes still fail.

Preserve the confirmed strategy: M15 trend/FVG qualification, 50-bar warm-up, M5 retest then distinct continuation confirmation, three 1/50/80% limits, common wick far-edge SL+two ticks, per-entry 1:2 TP, independently floored lots sharing 10 USD nominal risk, existing accepted-basket cooldown/cap/pending-expiry semantics, spread+one-tick eligibility and correct-side placement checks. No strategy retuning or risk redistribution.

## Scope and relevant files

- `app/web.py`, `config/fvg_execution.json`, relevant tests/README/dashboard text: demo-only default, persistent user OFF and truthful status.
- `app/fvg_live.py`, `app/fvg_execution.py`, `app/scanner.py` as needed: trustworthy current decision time, final execution eligibility and durable cancellation recovery.
- Focused regression tests under `tests/`, especially executor/engine/API/scanner suites and `test_fvg_review_fixes.py`.

Do not execute `tools/mt5_test_order.py`, modify helper tooling, commit/push, install global tools or alter unrelated settings. Preserve uncommitted work and historical state. Keep all artifacts inside this workspace and never expose credentials, session tokens, login/bot/chat identifiers, .env contents or entire private state files.

## Implementation plan

### A. Demo default ON, explicit consent for real/contest, user OFF always respected

Keep `default_on_for_demo_accounts: true`. Once the temporary user OFF override is cleared by the authorized activation phase below, an eligible DEMO account may submit under the configured default without a separate arming click after each demo account/server switch. This is the user's newly selected category-level preference, not an accidental reuse of another account's saved opt-in.

REAL and CONTEST accounts must never inherit that default. They require a saved exact source/symbol/strategy/server-plus-login binding. An unavailable/unknown account or account type is not proof of DEMO and must fail closed. Preserve all supported currency, equity, risk, exposure, hedging, quote and broker permission checks; default ON does not bypass them.

Explicit user OFF must beat the demo default and any inconsistent/stale saved consent. That preference persists through restart and account switches until a subsequent deliberate ON action. Do not clear the temporary OFF marker during implementation. Update status/docs to distinguish ON from the demo default, explicitly armed ON and explicit OFF.

All submissions must still capture the current server-plus-login in their policy/journal and refuse any mid-flight account/server change. Reconciliation/cancellation must operate only on the original basket's verified account; the demo default never authorizes adopting or canceling another account's orders. Keep legacy journals unresolved when ownership cannot be proven.

Tests: default-enabled DEMO A and another DEMO B can be ON without exact opt-in when no OFF override exists; explicit OFF persists and wins; real/contest/unknown are OFF without exact consent even when the demo default is true; exact explicit real-account consent works only on its own binding; restart persists defaults/OFF; mid-preflight account/server change refuses submission and foreign-account cancellation. No actual account switching or broker requests.

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


## Runtime and authorized activation boundary

Keep automatic execution OFF throughout Claude's implementation, fake-broker tests and restart. Do not clear the temporary OFF marker or arm anyone while the two remaining defects are unverified. Preserve Telegram ON and the fixed 10 USD combined basket risk. Recheck actual context through read-only local API observations without a competing MT5 session.

After focused/full tests pass, restart through the existing launcher with auto still OFF and verify healthy fresh FVG RR2 DEMO/XAUUSD data, risk, Telegram and readiness. If there is active exposure or an unresolved ownership/runtime issue, report it and stop dependent activation without deleting journals or altering positions.

Claude must publish its report and stop with the process disarmed. **Dispatch approval of this revised task also authorizes Codex, after independent verification of both residual failures and the default-policy regressions, to turn automatic execution ON through the normal authenticated app control on the currently connected MetaQuotes-Demo DEMO/XAUUSD context. No extra approval is required for that already-approved final activation.** Codex must first verify that the account is still DEMO and the risk and protections match this task. Do not activate a real/contest account under this demo instruction.

That final deliberate ON action may clear the temporary OFF override and create the exact current account binding using existing controls. Future eligible DEMO sessions use the selected default unless the user explicitly turns OFF. The app may then execute normal strategy-qualified DEMO orders and Telegram alerts under the user's automatic-execution preference. Do not inject a test signal, place an artificial broker test order/check/cancellation, or send an external test message to prove activation. Distinguish any normal strategy-generated actions observed after activation from artificial testing.

## Acceptance and validation

The two independently reproduced failures must be prevented by meaningful isolated regressions that fail against the currently reviewed code:

- `.tmp/fvg-basket-fixes-codex-review/residual-reproduction-results.json`: cancellation timeout remains pending after recovery; a 121-second-old confirmation still submits three orders.
- `.tmp/fvg-basket-fixes-codex-review/reproduce-residuals.py`: reviewer probe logic. Do not reuse its saved persistent SQLite paths; use isolated fixtures.

`.tmp/fvg-basket-fixes-codex-review/default-demo-consent-reproduction.json` now illustrates the explicitly selected demo-default behavior, rather than a defect. Its mismatched-demo binding result is allowed under section A only when account type is verified DEMO, user OFF is absent and execution safety checks pass. All real/contest/unknown, mid-flight switch and original-journal ownership protections remain mandatory.

Run focused regressions and full backend: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-20261007-164056-fvg-demo-default-clock-cancel-recovery` with a fresh directory. Keep genuinely timely eligible three-order fixtures passing. Run frontend tests/syntax/build as needed for touched assets. No unrelated helper suite, strategy optimization or global dependency installation.

Do not mask failures by widening the 30-second limit, removing the spread guard, moving SL, increasing risk, ignoring unknown account types or treating elapsed time as proof that an uncertain order disappeared. Keep performed tests, source inspection, inferred coverage, unavailable checks and actual runtime observations separate.

## Reply and stopping condition

Claude is implementer; Codex is planner/reviewer and final authorized runtime operator. Acknowledge only the approved execution prompt at the exact Progress path. If material requirements are blocked, publish the precise question at the Report path and stop dependent actions.

Publish the complete final report atomically at `report/20261007-164056-fvg-demo-default-clock-cancel-recovery-report.md` with task ID/source, changed files, focused/full tests, default-policy and both residual regressions, restart/runtime status with auto OFF pending Codex verification, preserved rules/$10 budget/Telegram, no artificial real broker tests or messages, and unresolved limitations. Stop after reporting; Codex performs the separately described verification and authorized final DEMO activation.
