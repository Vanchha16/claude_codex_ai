# Codex review: FVG three-entry engine

Author: Codex (independent reviewer)
Parent task ID: 20261007-111856-fvg-three-entry-engine
Source prompt: `prompt/20261007-111856-fvg-three-entry-engine.md`
Claude report: `report/20261007-111856-fvg-three-entry-engine-report.md`
Review date: 2026-10-07T13:59:46

## Outcome

Claude completed the approved implementation. The FVG strategy is selectable but inactive; the active config remains FastSweep rr2. Fixed risk preference is 10 USD per entire three-leg setup. No live execution opt-in is present at `.tmp/gold-signals/fvg_execution_optin.json`. Codex did not activate, arm, restart, access a live MT5 session, send broker requests or send Telegram messages during review.

Backend validation passes, including the six implementation observations supplied during the active task. Two dashboard defects remain, independently reproduced against the final JavaScript. The build is not yet fully accepted against the accurate-dashboard criteria. A follow-up draft exists but is not dispatched.

## Independent validation

- Full backend: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-codex-fvg-final-20261007-1425 --junitxml=.tmp/fvg-codex-final-tests.xml`: 233 passed, zero failures/errors/skipped; suite time 23.433 seconds. One installed Starlette/httpx deprecation warning. Broker and delivery checks are fake/mocked.
- Frontend: `npm.cmd test` in `frontend/`: 28 passed. These are the existing time formatting/navigation/chart-zone tests, not coverage of the new basket-risk renderer.
- `node --check app/static/app.js`: passed.
- Actual `renderFvgBaskets` extracted from final source and run in an isolated DOM stub: cent-account display bug reproduced. Evidence: `.tmp/fvg-codex-review/cent-risk-reproduction.json`.
- Actual last-closed/timeframe branch extracted from `refreshState` and run with FVG state: H1 caption reproduced. Evidence: `.tmp/fvg-codex-review/timeframe-caption-reproduction.json`.
- JavaScript SHA256 at review: `9c54da3890010acc984f162c3fcb59a2175abff4e45ad2c812b055075861e96a`.
- Reviewed final source for far-edge invalidation, pending RETURN filling, planned/journal crash recovery, partial fills and full deal-cost P&L, shared MT5 feed lock and truthful execution status. Their relevant backend tests passed in the independent suite.
- Parsed the saved baseline/sensitivity replay artifacts and checked counts/results against Claude's report. Codex did not run a further parameter search or tune the strategy.
- Claude reports a successful frontend build and installed-MT5 constant introspection. These are Claude's checks, not repeated by Codex in this final pass.
- No full rendered dashboard check against a running updated backend was performed. The two specific JavaScript paths were exercised in isolation.

## Remaining findings

### 1. Cent-account planned risk has a false USD label

`app/fvg_orders.py` defines `planned_loss` in account-currency units. `app/fvg_execution.py` includes `account_currency` in the execution payload. `app/static/app.js:235` sends the raw amount to the USD `money()` formatter without using that currency.

For a supported USC cent account, a leg with `planned_loss=333.33` is approximately $3.33 USD. The actual renderer displays `$333.33`, a 100x misleading dollar amount. This is a display defect; USD-to-USC risk-budget conversion and lot sizing are correct in the backend and covered by the passing suite. Fix the formatter without changing the risk budget or stored account-currency values. Missing/unsupported currency must never be assumed to be USD.

### 2. FVG last-closed status incorrectly labels H1

`refreshState` chooses M5/M15 trend wording only for `kind === "fastsweep"`. FVG falls through to CRT's `Last closed H1 / M5` caption and ignores its M15 warm-up readiness. FVG's active metadata and rules correctly use M15/M5. Make this status consistent while preserving CRT H1/M5 and FastSweep behavior.

## Replay implications

Baseline cached history: 16 baskets, 48 planned legs, 31 fills, 17 expired unfilled; 6 TP, 10 SL and 15 ambiguous filled legs. Basket R is sum of leg R divided by three. Ambiguous-excluded total is +0.624R; conservative ambiguous-as-stop total is -4.547R. The later chronological 30% is negative under both views. The sample was already explored and does not establish profitability. These are offline OHLC results, not broker executions or a promise about returns.

## Follow-up

Draft: `prompt/drafts/20261007-135946-fvg-dashboard-risk-labels.md`

Fix only the two demonstrated display defects and add focused regressions. Keep FVG inactive and execution OFF, with no live-server restart. Under the explicitly selected agent-to-agent workflow, a fresh user "send it" is required before this new task is published. Do not append new requirements to the completed parent task or re-execute it.
