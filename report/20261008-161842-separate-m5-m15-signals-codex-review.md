# Codex review: separate M5 and M15 signals

Later deeper review: `report/20261008-163422-separate-signals-code-review.md` reproduces three defects in signal status, exact Guide links and engine refresh-error handling. Consult that review before relying on the initial proportionate review conclusion below.

Task ID: 20261008-161842-separate-m5-m15-signals
Source prompt: `prompt/20261008-161842-separate-m5-m15-signals.md`
Claude report: `report/20261008-161842-separate-m5-m15-signals-report.md`
Reviewed: 2026-10-08

Read the matching COMPLETE report. Claude reports separate engine panels/history, per-basket messages and System lists, 362 backend tests, 56 frontend tests, successful build/syntax and one controlled restart.

Independent verification:

- `tests/test_fvg_signals.py` plus `tests/test_delivery.py`: 15 passed in 2.18s with a fresh project-local basetemp. These exercise two independent simultaneous baskets/messages, deduplication, provenance filtering before per-engine limits, read-only API behavior and delivery regressions. The full 362-test backend suite was not independently rerun.
- Frontend suite: 56 passed, zero failures.
- Read the additive `/api/fvg` filter and parameterized `outbox_for` lookup. Basket partition uses stored engine and version before the response limit; queued text belongs to its own basket. The filter applies to baskets; the existing `setups` list in that response remains unfiltered. New signal views use baskets.
- Live read-only state: MT5, healthy feed and running scanner, original dual strategy version, automatic execution ON, risk $10 and Telegram enabled. M5/M15/legacy filtered GETs return no baskets at review time, consistent with no live accepted dual signals yet. No test messages or broker orders sent.
- Viewed saved isolated mock `01-MOCK-signals-M15-M5-separate-with-queued-message.jpg`: visibly distinct engine panels, own journal statuses, leg tables and a single-basket Telegram message. Artifact inspection only, not independent interactive browser QA.

No blocking issue found in these checks. Actual live broker/Telegram examples are still unavailable because no live dual basket has occurred; two-message behavior was verified with isolated test evidence. The existing explicit dual-version consent remains a separate open item, as reported by Claude. The API currently partitions a bounded 100000-basket history in memory; a future larger-history optimization can push this predicate into storage if necessary.
