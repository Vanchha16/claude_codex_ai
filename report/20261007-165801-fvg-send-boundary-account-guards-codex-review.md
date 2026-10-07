# Codex review: FVG broker-call guards

Reviewed task ID: 20261007-165801-fvg-send-boundary-account-guards
Source prompt: `prompt/20261007-165801-fvg-send-boundary-account-guards.md`
Claude report: `report/20261007-165801-fvg-send-boundary-account-guards-report.md`
Date: 2026-10-07
Status: NOT ACCEPTED FOR FINAL ACTIVATION — one reproducible freshness gap remains.

## Verified results

Independently ran the full backend suite: **310 passed**, zero failures, errors or skips. The three original deterministic probes now pass: only one original-account pending call after a server switch; zero calls after a 45-second journal-write delay; only the original first ticket removed after a server switch, with both foreign orders retained and cancellation unresolved.

Command: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-codex-boundary-review-20261007 --junitxml=.tmp/fvg-boundary-codex-review/backend-tests.xml`.

## Remaining failure

In `submit`, `clock_now()` is evaluated as an argument to `_call_blocker` **before** that helper calls `mt5.account_info()`. The helper then passes this captured earlier timestamp to `_ineligible`. A slow account lookup can therefore bypass the final confirmation/setup/pending deadline check despite the journal-write fix.

Independent frozen-clock fake probes advance the clock by 45 seconds inside the per-call account lookup, after the durable sending marker:

- Before leg 1: one request sent with confirmation age **45 seconds**; legs `pending, not_sent, not_sent`, state `partial`. Expected zero calls.
- Before leg 2: requests sent at ages **0 and 45 seconds**; legs `pending, pending, not_sent`, state `partial`. Expected only the timely first call.

The fix must obtain the clock AFTER the potentially blocking account lookup and immediately before eligibility is checked and the pending API is called. Retain account verification after durable journal writes, truthful not_sent classification, earlier accepted legs and idempotency. Use the existing injected/monotonic clock, without widening 30 seconds.

Evidence: `.tmp/fvg-boundary-codex-review/run-20261007-121919/` contains original probes, their results, additional-probes.json, sanitized runtime and source manifests. All probes used fresh isolated SQLite files and fake brokers; application/test/config source hashes remained unchanged during review. No artificial live broker request, signal or Telegram message occurred.

## Runtime and control action

Read-only observation at 12:19:20Z found MetaQuotes-Demo DEMO/XAUUSD, FVG RR2, scanner running without error, M15 ready 57/50, 10 USD total risk, Telegram ON, zero baskets/setups. Automatic execution was already **ON**, contrary to the reported OFF state; normal app status recorded user arming at 12:14:58Z. Codex did not perform that activation.

Because verification of the approved freshness guard failed, Codex used the normal authenticated local `/api/fvg/execution` control to turn new automatic submissions **OFF** at 12:24:35Z, restoring the task's required OFF-until-verified state. Zero baskets/setups remained. No override file was edited directly. Evidence: `.tmp/fvg-boundary-codex-review/pause-sanitized.json`.

This control creates the normal persistent user-OFF marker, so dashboard reason text says `turned OFF by you`; the actual actor for this pause was Codex. Demo-default configuration remains true, risk 10 USD and Telegram preference are preserved. Final activation remains authorized after independent verification; no new activation approval is needed.

## Next handoff

Focused draft: `prompt/drafts/20261007-192600-fvg-post-account-clock.md`.
The agent-to-agent workflow requires a separately approved dispatch. No application code was changed by Codex and no new task was published in this review.
