# Correct FVG dollar-risk and timeframe labels in the dashboard

Task ID: 20261007-135946-fvg-dashboard-risk-labels
Delivery status: APPROVED FOR EXECUTION
User authorization: the user explicitly replied "send it" on 2026-10-07 to the reviewed follow-up draft for the two dashboard fixes. This authorizes presentation changes and their project-local validation only; no activation, arming, live-server restart, real broker requests or Telegram messages.
Published at: 2026-10-07T07:04:33.220365+00:00
Project root: E:\VideCode\vc_trade
Source prompt: `prompt/20261007-135946-fvg-dashboard-risk-labels.md`
Report path: `report/20261007-135946-fvg-dashboard-risk-labels-report.md`
Parent completed task: `20261007-111856-fvg-three-entry-engine`

## Goal and context

Codex reviewed the completed FVG build and independently passed all 233 backend tests and 28 existing frontend tests. Two dashboard errors still violate the original requirement to display risk and strategy information accurately. Read `report/20261007-111856-fvg-three-entry-engine-codex-review.md` and the two reproduction JSON files under `.tmp/fvg-codex-review/`.

1. The basket renderer prefixes raw account-currency `planned_loss` with a dollar sign. On USC cent accounts, 333.33 USC displays as $333.33 instead of approximately $3.33 USD.
2. The last-closed status uses H1/M5 wording for FVG even though the strategy runs M15/M5 and supplies M15 readiness.

This task corrects presentation only. The user's confirmed entries remain 1/50/80%, fixed 10 USD total setup risk, equal nominal thirds, common far-edge SL and individual 1:2 targets. FastSweep rr2 remains active and automatic FVG execution remains OFF.

## Scope and relevant files

- `app/static/app.js`: money/risk rendering and last-closed status branch.
- `frontend/tests/` and `frontend/package.json` if needed to add a focused test to the normal test command.
- A small project-native display helper if it provides a clean test seam; keep the change proportional.
- `frontend/src/index.template.html` and copied `app/static/index.html` only if loading such a helper requires them.
- Read-only contract references: `app/fvg_orders.py`, `app/fvg_execution.py`, `app/active_strategy.py`, `app/fvg_live.py` readiness fields.

Do not alter strategy rules, risk sizing, broker requests, persistence formats, cached history, existing live settings, credentials, active config, arming controls or delivery behavior. Do not restart the live server, activate/arm FVG, initialize MT5, perform broker requests or send Telegram messages.

## Implementation plan

1. Render each leg's planned loss using `b.execution.account_currency`. For USD, display the correct USD amount; for USC, convert cents to USD by dividing by 100 and make the currency clear (optionally also show original USC units). Account-unit values in the API/storage stay unchanged. The displayed per-leg values should be the actual lot-rounded losses, not forced to $3.33. Keep top-level fixed USD budget and equity percentage accurate.
2. For absent or unsupported currency on old/unusual records, show a clearly labeled account-currency/unknown amount or unavailable conversion. Never attach a USD dollar sign to raw unknown units. Avoid NaN or fabricated zero for missing values.
3. Use FVG's M15/M5 status and its `m15_run`, `required` and `ready` values. Preserve FastSweep M15/M5 and CRT H1/M5 behavior. Do not change the scanner to fabricate an H1 FVG dependency.
4. Add focused regression tests that exercise the actual display functions/branches for USD, USC, absent/unknown currency, FVG warm-up/ready state, and unchanged CRT/FastSweep labels. Existing frontend tests alone did not cover these paths.
5. Build project assets if needed and inspect a synthetic FVG dashboard state at desktop and narrow/mobile widths without using the live backend or changing real execution state. A mocked UI is fine; label the report accordingly.

## Acceptance criteria

- `account_currency="USC", planned_loss=333.33` displays about $3.33 USD, never $333.33 USD. `account_currency="USD", planned_loss=3.33` displays $3.33 USD.
- Missing/unknown currency does not silently convert or falsely claim USD.
- Actual lot-rounded per-leg planned risk remains represented; fixed setup risk is still 10 USD and sizing is unchanged.
- FVG last-closed caption/readiness uses M15/M5; CRT and FastSweep retain their correct existing timeframes.
- The focused regressions run through the normal frontend test command. Syntax, build and applicable existing tests pass.
- No live orders, messages, activation, arming or restart. No application changes outside the presentation/test scope.

## Validation

Run `node --check app/static/app.js`, the focused new tests through `npm.cmd test` in `frontend/`, and `npm.cmd run build` as appropriate. Use fake/synthetic values and local UI inspection only. Run backend regression checks only if a backend contract is touched, which is not expected. Do not repeat replay/tuning for a presentation correction.

Report checks actually performed separately from recommended/unavailable checks. Keep all artifacts inside the project root. Before any recursive deletion/move, verify resolved targets stay inside the intended workspace.

## Reply and stopping condition

Codex is planner/reviewer and Claude is implementer. This task is separately approved and atomically published. Acknowledge in `report/20261007-135946-fvg-dashboard-risk-labels-progress.md`, implement, and publish the complete final report atomically at `report/20261007-135946-fvg-dashboard-risk-labels-report.md` with matching task ID/source, files changed, tests, synthetic UI evidence and remaining issues. State that FVG remains inactive and OFF and no live actions were performed. Stop after reporting and wait for the next separately approved task.
