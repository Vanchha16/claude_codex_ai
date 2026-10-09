# M5 common stop that accounts for spread

Task ID: 20261009-103608-m5-spread-aware-stop
Delivery status: DRAFT — DO NOT EXECUTE
User authorization: pending
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261009-103608-m5-spread-aware-stop.md`
Report path: `report/20261009-103608-m5-spread-aware-stop-report.md`
Progress path: `report/20261009-103608-m5-spread-aware-stop-progress.md`

## Goal and evidence

The user repeatedly asks how to fix missing signals/orders for the BUY M5 zones in `.img/image copy 11.png`. Read-only live inspection found that the top zone 4172.68–4175.02, closing 2026-10-09 02:45Z (09:45 Bangkok), passed qualification but was rejected because leg 3 entry 4173.14 had distance 0.48 to common SL 4172.66, below spread 0.49 plus one tick 0.01 = 0.50. No basket or signal was created. The lower zones were rejected during trend warm-up and are outside this stop-policy fix.

Proposed rule change, requiring approval: for new qualifying dual M5 setups, move the common stop outward by the minimum whole ticks necessary to meet the existing spread-plus-one-tick check for every leg. Retain the two-tick beyond-zone stop whenever it already passes. Keep entry depths 1/50/80%, three entries, per-leg 1:2 targets and the configured $10 total planned basket budget. This changes M5 stop placement; it is not a correction to a miscomputed 0.48 distance. No claim of profitability or guaranteed order acceptance.

## Scope and implementation

Read `app/fvg.py`, `app/fvg_dual.py`, `app/fvg_orders.py`, `app/fvg_execution.py`, `app/fvg_guide.py`, delivery serializers and relevant tests. Claude implements; Codex plans/reviews. Preserve existing uncommitted work.

1. Add an explicit M5-only spread-aware stop policy for dual mode. Keep M15 and legacy policy unchanged. Encode the policy in strategy/engine provenance instead of silently using the previous strategy version for changed behavior. Report version and consent implications; do not migrate old consent or rewrite historical setups/baskets/journals.
2. Preserve the original entries. Compute the base stop two ticks beyond the far zone edge. For BUY, the adjusted SL must be no greater than both the base SL and every entry minus the required spread distance; round outward down to the valid tick. For SELL, use the corresponding maximum and round outward up. Use finite validated spread/tick inputs and Decimal-compatible rounding. A missing/stale quote must not be replaced by an invented spread. Keep the existing maximum spread and broker validity checks.
3. Recalculate all three targets from the adjusted common stop at 1:2. Recalculate lots with the existing equal risk shares and round down to broker volume steps, using account-currency loss calculation. Keep the minimum-lot rejection and configured total planned-risk budget. A wider stop can reduce volume; do not increase risk to fit broker minimums.
4. Make signal levels, Guide actual levels, message levels, sizing, journal and broker requests agree on one immutable plan. `FvgExecutor.submit` currently calls `build_order_plan` with the default two-tick buffer; changing only `basket_levels` at the scanner would leave submitted stops wrong. Refactor the plan interface narrowly so the chosen levels reach sizing and execution without stale overrides or unvalidated external levels. Keep legacy callers compatible.
5. Recheck the latest spread, broker distances and all existing send-boundary rules. If conditions change and the fixed chosen plan becomes invalid, report refusal/partial/unresolved state honestly. Do not modify stops of already submitted legs, rebuild and resend an existing plan, or manufacture a new signal to bypass deduplication. Persist enough provenance to explain any adjustment and distinguish planned signal levels from broker outcomes.
6. Where replay/preview lacks contemporaneous quotes, label that limitation; never imply historical spread validation occurred. Show actual stored adjusted levels when present. Keep normal signal acceptance/alert flow: this proposal addresses the spread-room rejection, not unconditional alerts for every chart gap.

## Validation and boundaries

- Isolated regression for the exact BUY example: entries unchanged; common SL becomes 4172.64 for the recorded spread, third-leg distance 0.50, targets recalculated; adjustment passes the spread-room rule.
- Mirror SELL case, no-adjustment case, fractional spread/tick rounding, invalid/missing/stale spread, maximum-spread refusal, minimum-lot refusal and budget calculations. Verify all three stored/message/request entry/SL/TP values match exactly.
- Fake MT5 execution tests with fresh-quote changes at preflight/send boundaries; retain idempotency, unknown and partial-execution behavior. Prove M15/legacy levels and policies are unchanged.
- Frontend checks where presentation changes; build normally. Focused backend tests and full suite with fresh project-local basetemp. Report recurring unrelated test failures honestly rather than rerunning until green.
- Keep all fixtures, caches and artifacts in the project. No real orders, cancellations, Telegram messages, live-store injection, retroactive trading of the screenshot gaps, risk/configuration changes, consent changes, runtime restart, activation, commits, pushes or global installs. Deliver code and isolated verification for review; the existing running strategy stays in place during this implementation task.

## Reply

Acknowledge in the exact progress path. Report changed files, actual tests, unavailable checks, exact example levels/volumes from fixtures, new version behavior and any activation requirements. Publish the complete report atomically through a project-local temporary file. If material implementation choices cannot meet the approved contract, report them rather than changing scope. Stop after reporting and wait for the next separately approved task.
