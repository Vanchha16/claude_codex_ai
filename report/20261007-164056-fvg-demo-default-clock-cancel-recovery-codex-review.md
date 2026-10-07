# Codex review: demo default ON and FVG recovery task

Reviewed task ID: 20261007-164056-fvg-demo-default-clock-cancel-recovery
Source prompt: `prompt/20261007-164056-fvg-demo-default-clock-cancel-recovery.md`
Claude report: `report/20261007-164056-fvg-demo-default-clock-cancel-recovery-report.md`
Reviewer: Codex
Date: 2026-10-07
Status: **NOT ACCEPTED FOR FINAL ACTIVATION ? three reproduced broker-call boundary failures remain.**

## Outcome

The demo-default policy and both previously reported residual failures are fixed. Independently running the full backend suite produces **302 passed**, no failures, errors or skipped tests. The older slow-decision probe now creates zero alerts and zero pending requests; the cancellation-timeout probe now removes the still-owned remainder after recovery.

However, the approved requirements to refuse mid-flight account/server changes, recheck eligibility immediately before sending, and cancel only on the original account remain incomplete. Three deterministic fake-broker probes reproduce the gaps against the exact code in Claude's completed report. The authorized final activation is deferred until these concrete defects are fixed and verified. No application code or runtime preference was changed in this review.

## Confirmed remaining defects

### 1. High: account/server change between pending sends is not checked

Location: `app/fvg_execution.py:347` (per-leg loop), API call at line 360.

The account binding is checked twice during preflight, but never again between pending sends. In the probe, the first pending order succeeds on Test-Server, then the fake terminal switches to Other-Server before the next loop iteration. All three requests are sent, with server sequence:

`[Test-Server, Other-Server, Other-Server]`

The journal retains the original account identity and reports `submitted`. This contradicts section A's requirement to refuse any mid-flight account/server change; accepted exposure can be left on multiple accounts while reconciliation knows only the original identity.

Required correction: verify the bound account immediately before each pending API call, after any blocking journal write. If it changes, stop all uncalled legs, preserve any accepted/uncertain original-account legs and their journal, and never automatically resume/resend. Do not rerun the whole-basket no-exposure check after the first accepted leg, because the engine's own first pending order is now expected exposure.

### 2. Medium: blocking durable journal write bypasses final confirmation freshness

Location: `app/fvg_execution.py:349` (age check), line 358 (durable save), line 360 (send).

The check labeled immediately before each send actually runs before the durable journal save. In the probe, that save advances the injected clock by 45 seconds. The first request is then sent with a **45-second-old confirmation**, exceeding the unchanged 30-second maximum. The next iteration stops the remaining legs, but the first stale request has already been sent:

`confirmation_ages_at_send: [45.0]; mock_requests: 1; state: partial`

Required correction: recheck confirmation, setup and pending lifetime after the potentially blocking save and directly before the API call. When a call is known not to have occurred, its leg must be recorded as `not_sent`, rather than left `sending` or `unknown`. Preserve earlier accepted or genuinely uncertain legs and idempotency.

### 3. High: account/server switch between removals can cancel foreign orders

Location: `app/fvg_execution.py:510` (single owner check), line 516 (cached pending snapshot), line 523 (removal).

The account is checked once, and the initial pending list is reused across the full removal loop. After the first removal, the probe switches the fake account/server and supplies unrelated manual foreign orders with colliding ticket IDs on that other server. The remaining requests still target the original cached ticket IDs on the new account:

`servers_at_remove: [Test-Server, Other-Server, Other-Server]`
`mock_removed_tickets: [101, 102, 103]; foreign_orders_remaining: 0; cancel_state: complete`

The fake broker removed both foreign manual orders. This contradicts sections A/C's original-account-only cancellation requirement. The final refresh and empty read also use the other account and wrongly mark the original cancellation complete.

Required correction: check original-account ownership before each removal and before adopting refreshed broker evidence. Obtain current, verified pending ownership for each removal rather than trusting a batch-old snapshot. Persist any already-completed original-account progress before aborting on a switch; keep cancellation unresolved until reliable original-account evidence is available. Returning to the original account must allow bounded cancellation recovery without any foreign removal or duplicate removal of an already-disappeared ticket. Reconciliation must not adopt mixed-account query results.

These are reproduced failures in existing approved protections, not strategy changes. Application-level locks cannot prevent an account switch made externally in the terminal between broker calls.

## Independent validation and evidence

Evidence directory: `.tmp/fvg-default-clock-cancel-codex-review/`

- `backend-tests.xml`: 302 tests, 0 failures, 0 errors, 0 skipped.
- `verify-reported-build.py`: review runner; fake probes and sanitized GET observations only.
- `verified-reported-build-20261007-0955/inflight-probes.py` and `inflight-probe-results.json`: all three failures reproduced after Claude's final report.
- `verified-reported-build-20261007-0955/previous-residual-probes.py` and `residual-reproduction-results.json`: previous delayed-decision and cancellation-recovery probes now pass.
- `review-source-manifest-before.json`, `review-source-manifest-after.json`: 52 source/config files checked; no changes during the probes.
- `validation-summary.json`: structured test totals and limits.
- `runtime-sanitized.json`: local read-only observation.

Command actually run:
`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-codex-demo-default-recovery-20261007 --junitxml=.tmp/fvg-default-clock-cancel-codex-review/backend-tests.xml`

One existing Starlette/httpx deprecation warning; no test failures. No frontend assets changed in this task, so the frontend suite/build was not repeated. The existing backend regressions cover switching during preflight and switching before cancellation; they do not cover switching after the first accepted send/removal or time spent in the pre-send durable write.

Every reproduction uses an isolated fresh SQLite path and an in-process fake broker. No real MT5 initialization, order_check, order_send, removal, injected signal, or Telegram test message. No commit/push, account switch, activation or manual override-file edit.

## Runtime observation

At 2026-10-07T09:56:12Z:
- Connected MetaQuotes-Demo **DEMO**, XAUUSD, FVG RR2 version `FVG-Trend-M15-M5-v1-RR2@8a49bace`.
- Demo-default config **true**; actual automatic execution **OFF**, reason `turned OFF by you`.
- Fixed **10 USD total per basket**, Telegram **ON**, persisted.
- Scanner running without error; quote fresh, age 0.4 seconds, spread 0.31.
- M15 warm-up **47/50**, not ready; no baskets or setups.

Final activation remains authorized on the verified demo context after protections pass independent review. Do not interpret this report as revoking that authorization or requesting another activation approval.

## Next handoff

Focused repair draft: `prompt/drafts/20261007-165801-fvg-send-boundary-account-guards.md`.
The completed Claude task and report are preserved. The draft is not published or authorized for execution; the agreed agent-to-agent workflow requires a new send it for a follow-up implementation task.
