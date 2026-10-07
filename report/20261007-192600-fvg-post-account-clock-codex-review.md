# Codex review: clock after the final account lookup

Task ID: 20261007-192600-fvg-post-account-clock
Source prompt: `prompt/20261007-192600-fvg-post-account-clock.md`
Claude report: `report/20261007-192600-fvg-post-account-clock-report.md`
Date: 2026-10-07
Status: ACCEPTED — independently verified; previously authorized final DEMO activation completed.

## Verified change

`submit()` passes the existing clock function into `_call_blocker`. The helper reads the original server+login account first, then samples that clock and checks confirmation freshness/future time, setup expiry and pending lifetime before sending. The durable sending marker still precedes account verification. Earlier accepted legs, truthful not_sent classification, partial states, idempotency, crash recovery and original-account cancellation/evidence guards are preserved.

Only `app/fvg_execution.py` and `tests/test_fvg_review_fixes.py` changed for implementation. Codex maintained handoff/review files and independent verification scripts, without implementing application changes. No commit or push.

## Independent verification

- Full backend: **314 tests passed**, zero failures, errors or skips. Command: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-codex-post-account-20261007-1256 --junitxml=.tmp/fvg-post-account-codex-review/backend-tests.xml`. One existing Starlette/httpx deprecation warning remains.
- Eight isolated fake-broker timing cases passed: 45-second lookup before leg 1 sends nothing; before leg 2 keeps only its timely first accepted leg; setup expiry, pending expiry with and without eligibility, future confirmation, exact 30-second equality, and timely three-leg submission. Repeat submission resends nothing in every case.
- The original account-switch, delayed journal-write and cancellation probes passed. Only the original-account request/removal occurred; foreign orders remained untouched, cancellation stayed unresolved until original-account recovery.
- Reviewed app/test/config hashes remained unchanged across probes and matched again immediately before activation. The runtime process started after the changed source file, confirming the restart loaded this build.

Evidence: `.tmp/fvg-post-account-codex-review/backend-tests.xml`, `.tmp/fvg-post-account-codex-review/run-20261007-125646-361036/results.json`, and `.tmp/fvg-boundary-codex-review/run-20261007-125645/`.

Before dispatch, independent probes still reproduced both slow-account failures on the earlier code: requests at confirmation ages 45 seconds and 0/45 seconds respectively. Evidence: `.tmp/fvg-boundary-codex-review/run-20261007-124742/additional-probes.json`. Claude additionally reports all four new regressions fail on its reconstructed earlier build; that separate reconstruction was not rerun by Codex.

## Runtime and activation

At 12:47:43Z Codex observed execution ON again, one natural setup and zero baskets. The normal app status recorded arming at 12:26:32Z. At 12:48:13Z Codex restored OFF through the normal authenticated app control pending verification, before publication of this task. Evidence: `.tmp/fvg-boundary-codex-review/run-20261007-124742/pause-sanitized.json`. The dashboard wording "turned OFF by you" refers to the normal persistent marker; Codex was the actor for this pause.

After independent checks passed, Codex completed the previously authorized activation through `/api/fvg/execution` with `enabled: true, confirm: true` at **12:58:31Z / 19:58:31 Bangkok**. Before and after the control, the verified context was MetaQuotes-Demo **DEMO/XAUUSD**, FVG RR2, **10 USD** total planned risk, Telegram ON, scanner running without error, fresh quote, and M15 ready **59/50**. Runtime PID: 20548. Automatic execution is now **ON**.

At activation there were **zero baskets and zero open baskets**, plus one natural pending SELL setup, zone 4089.01–4119.18, expiry 14:45Z. Activation permits future normal eligible strategy submissions; no artificial broker request, injected signal or test Telegram message was made. No terminal account switching or competing MT5 initialize/login was performed.

Evidence: `.tmp/fvg-post-account-codex-review/pre-activation-sanitized.json` and `activation-sanitized.json`.

## Practical limit

The application cannot make the final account check and broker call atomic against an external terminal account switch, nor control latency inside the broker call. These remaining external windows are distinct from the repaired stale timestamp captured before account lookup. Existing per-call and evidence ownership guards remain in place.

No permission rejection occurred. The approved task is complete; no further Claude task was dispatched.
