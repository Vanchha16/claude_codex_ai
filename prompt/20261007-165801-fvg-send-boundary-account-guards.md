# Close remaining FVG account and freshness gaps at broker calls

Task ID: 20261007-165801-fvg-send-boundary-account-guards
Delivery status: APPROVED FOR EXECUTION
User authorization: On 2026-10-07 the user reviewed this follow-up repair draft and explicitly replied "send it". This authorizes the unchanged repair, deterministic testing, normal restart and report scope. The previously approved final activation by Codex remains authorized on the verified MetaQuotes-Demo DEMO/XAUUSD context after independent verification; keep auto OFF during implementation. No artificial live broker test actions/messages, account switching, commits/pushes or global changes are authorized.
Published at: 2026-10-07T11:30:37.9832110Z
Approved draft SHA-256: cc90b6b4d95bf7e74541586505a9d65dddc2a404c96276736117506694950b10
Project root: E:\VideCode\vc_trade
Source prompt: `prompt/20261007-165801-fvg-send-boundary-account-guards.md`
Report path: `report/20261007-165801-fvg-send-boundary-account-guards-report.md`
Progress path: `report/20261007-165801-fvg-send-boundary-account-guards-progress.md`

## Goal and context

Complete the existing mid-flight ownership and 30-second freshness protections so the user's already-authorized demo-default automatic execution can be activated after verification. No strategy changes.

Read `report/20261007-164056-fvg-demo-default-clock-cancel-recovery-report.md` and `report/20261007-164056-fvg-demo-default-clock-cancel-recovery-codex-review.md`. The preceding repair passes all 302 backend tests and fixes both older residual probes. Codex nevertheless reproduced three additional call-boundary failures against the reported build:
1. Server switch after first accepted pending request: two more requests sent on a different server, journal still original identity.
2. Pre-send durable journal save advances the clock 45 seconds: first request sent with a stale confirmation.
3. Server switch after first removal: cached original pending tickets remove unrelated manual orders on the other server; foreign empty evidence marks original cancellation complete.

Exact fake probes/results: `.tmp/fvg-default-clock-cancel-codex-review/verified-reported-build-20261007-0955/inflight-probes.py` and `inflight-probe-results.json`.
Do not reuse these persistent SQLite paths; create fresh isolated test fixtures.

Latest read-only runtime: MetaQuotes-Demo DEMO / XAUUSD, FVG RR2, fresh quotes, healthy scanner, demo-default config true, actual auto OFF through persistent user-OFF marker, Telegram ON, fixed 10 USD combined risk. No baskets or setups, M15 warm-up 47/50 at 09:56Z.

## Scope and preservation

Change `app/fvg_execution.py` and meaningful focused tests; change `app/fvg_live.py` only if needed to preserve correct recovery/status. Preserve uncommitted work, report/prompt history and user tooling.

Preserve:
- DEMO default ON, explicit user OFF highest priority, REAL/CONTEST exact consent, unknown type fail closed for defaults.
- Original server+login policy/journal identity, idempotency and unknown-outcome reconciliation.
- M15 qualification and 50-bar warm-up; M5 retest then distinct continuation.
- 1/50/80% limits, common wick far-edge SL plus 2 ticks, per-entry 1:2 TP.
- Floored lots sharing 10 USD nominal basket loss; no redistribution or widening the budget.
- 30-second confirmation maximum with equality allowed; spread plus 1 tick eligibility and correct-side limits.
- Existing cooldown, daily cap, two-hour pending lifetime and Telegram delivery preference.

No artificial live broker preflight/order/removal, injected signal, test Telegram message, real account switching, competing MT5 initialize/login, global installs, helper edits, commits or pushes. Do not execute `tools/mt5_test_order.py`. Never output tokens, logins, bot/chat IDs, .env contents or entire private state documents.

## Implementation plan

### A. Bound account check at every pending request

Re-read the bound account immediately before each pending `order_send`, after any potentially blocking durable journal write. Guard both login and server against the immutable original policy/journal identity. The preflight account check alone is insufficient.

On a mismatch or unavailable account, stop uncalled legs with truthful not_sent state, retain accepted/uncertain original-account legs and an open reconciliation state, and never automatically continue the batch on a different account or resend it when the account returns. Preserve the original identity.

Do not call the original all-symbol no-exposure guard unchanged for every leg: earlier accepted orders in this same basket are expected exposure. Design a focused per-call ownership guard. Keep existing timely eligible three-leg submission working.

### B. Freshness after the last blocking pre-send operation

Recheck current confirmation age, future timestamps, setup expiry and pending expiry after the journal has durably saved sending, directly before the pending API call. A check before the durable write does not meet the boundary requirement.

If expiry is discovered after saving sending but before the API call, persist that this current leg and later uncalled legs were not_sent. If no prior leg was sent, record a truthful unsubmitted/rejected outcome; if an earlier leg was accepted or uncertain, preserve its journal and reconciliation without treating the entire basket as a preflight rejection. Never widen 30 seconds or blindly retry a stored basket.

Account and clock checks should share a clear per-call sequence after blocking work. Keep guard exceptions distinct from uncertain broker-call outcomes where the broker was actually called. Preserve crash/error classification and storage-recovery behavior.

### C. Original-account-only removal and evidence adoption

Before each removal, verify the original server+login and current still-pending owned ticket. Do not reuse the initial batch pending snapshot as authority after another broker call. Recheck identity after state-query operations and before adopting query evidence, including reconciliation and final cancellation-completion decisions, so mixed-account results cannot update the original journal or falsely prove completion.

If the account changes after one removal, persist the known original-account progress, stop before removing any foreign ticket, retain unresolved cancellation and the durable invalidation, and let existing bounded recovery resume when the original account returns. Do not repeat removal once authoritative original-account evidence shows the ticket gone. Preserve partially filled/open positions and all SL/TP; never close a position.

No application lock can prevent an external terminal account change; make the remaining per-call checks explicit and report their practical limits accurately.

## Acceptance criteria and meaningful regressions

Add tests that fail against the exact reviewed code, using frozen/injectable clocks and isolated fake brokers:

1. Switch server after first accepted pending call. Exactly one call on the original server; no call on the new server; original journal identity and accepted leg retained; remaining legs not_sent; repeat submit performs no resend.
2. Switch login on the same server between pending calls; identical refusal and ownership semantics.
3. Have the pre-send durable journal save advance the clock by 45 seconds. Zero stale pending calls; current leg is not_sent despite prior sending marker; accepted earlier legs remain tracked when the delay occurs before a later leg.
4. Equivalent setup/pending deadline crossing in the pre-send write refuses the uncalled leg without widening eligibility.
5. Switch server after first successful removal, with foreign/manual orders using colliding ticket IDs on the new server. No foreign removal or foreign-state adoption; cancellation remains unresolved; return to original account removes only verified still-pending original-owned remainders and never repeats an already-disappeared ticket.
6. Switch identity during broker query collection: original reconciliation/cancellation must not mark completion or adopt foreign records from a mixed-account snapshot. Preserve unresolved state for original-account recovery.
7. Existing 30-second equality, timely three-order basket, partial/unknown submission, cancellation timeout/retry, partial fills, explicit OFF and demo default tests stay passing.

Fix the three specific reproductions. Broaden checks only where needed for the same call/evidence boundary; no risk/strategy retuning.

## Validation and runtime

Run focused regression suites, then the full backend suite with a fresh local basetemp, e.g.
`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-20261007-165801-fvg-send-boundary-account-guards`.

Use deterministic fakes; no real sleeps or broker calls. Report checks actually performed separately from inferred/unavailable checks. No frontend build is needed unless dashboard assets change. Keep all artifacts inside this project and verify resolved targets before any recursive removal.

Keep auto OFF throughout implementation, tests and normal launcher restart. Verify read-only local runtime afterward: same verified DEMO/XAUUSD context, fresh healthy FVG RR2, risk 10 USD, Telegram ON, auto OFF; disclose any active/unresolved exposure. Do not clear override files or arm manually.

The preceding user-approved task already authorized Codex's final activation on the verified MetaQuotes-Demo DEMO/XAUUSD context after independent checks. This follow-up preserves that authorization; do not request a new final activation permission or enable during your implementation. Codex will verify the remaining guards and then use the normal authenticated app control to turn ON. Normal strategy-generated demo actions after activation are covered by the user's preference; artificial test actions remain excluded.

## Reply and stopping condition

Claude implements; Codex coordinates/reviews and performs final authorized runtime activation. Acknowledge the approved prompt at the exact progress path. Publish the complete matching final report atomically using an in-project temporary file then rename.

Include task/source, changed files, before/after regression evidence for the three reviewed failures, focused/full results, restart and sanitized runtime status with auto OFF, preserved protections/risk/default/Telegram, no artificial live broker tests or messages, and any limits.

Stop after reporting. Do not overwrite the preceding completed report or self-dispatch another task.
