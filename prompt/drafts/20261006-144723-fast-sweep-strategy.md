# Test a faster gold strategy targeting 3–4 signals per active day

Task ID: 20261006-144723-fast-sweep-strategy
Delivery status: DRAFT — DO NOT EXECUTE
User authorization: The user said "let change strategy i want 3 or 4 signal every day" and selected "Both 1:1 and 1:2" for risk-to-reward tests. Dispatch approval is pending the established workflow's send-it gate.
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261006-144723-fast-sweep-strategy.md`
Report path: `report/20261006-144723-fast-sweep-strategy-report.md`

## Goal and context

Replace the zero-signal research direction with a faster, fully defined candidate strategy. The user wants approximately 3–4 valid alerts per active trading day, with risk 1 to reward 1 or 2. Build and test a new opt-in strategy in replay first. Preserve CRT-SMC-v1 and its live operation until the user reviews the new evidence and explicitly selects a live profile. This supersedes the earlier unpublished draft that only lowered minimum RR to 1.0; do not execute that draft.

Frequency is a measured objective, not authorization to fabricate alerts, weaken risk below 1:1, hide zero-signal dates or claim an unachieved daily quota. The old 60-day run had zero signals at minimum RR 1.5, and two at 1.0. The user approved testing both fixed target ratios, not a ratio below 1.0.

Codex's read-only count of the same August 6–October 5 closed bar sample found 1,313 raw M15 single-sided sweep-and-return patterns across 52 Bangkok calendar dates (mean 25.25, median 30), before entry/confirmation/trend/cost/outcome filters; partial and short dates are included. This supports evaluating a faster timeframe but does not establish executable signal frequency or profitability.

## Concrete candidate: FastSweep-M15-M5-v1

Use these predeclared rules, without searching a large parameter grid:

1. Data: the existing gold symbol and read-only connected feed. Form M15 candles from complete contiguous M5 groups using app.models.aggregate. A/B are adjacent closed M15 candles; no incomplete or gap-filled groups. Test across available hours rather than inventing a minimum number of trades in each session.
2. Range: BUY when B sweeps A low by >= 2 instrument ticks, does not exceed A high, and closes strictly inside A's range. SELL mirrors it. Reject double-sided sweeps and noncontiguous pairs. The predicates mirror current CRT range rules, but the timeframe is M15.
3. Trend: computed only from closed contiguous M15 candles. EMA20 > EMA50 permits BUY; EMA20 < EMA50 permits SELL; equal values or insufficient/gapped warmup permit neither. Specify EMA initialization and readiness, require at least 50 contiguous closed M15 candles, and apply the same exact calculation in replay and any eventual live path.
4. Confirmation: after B closes, allow the next three completed M5 candles (15 minutes). BUY requires previous close <= B high and new close > B high; SELL previous close >= B low and new close < B low. Confirmation cannot occur within B. Revisit of B's sweep extreme before/in the confirming bar invalidates the setup. On a same bar, invalidation has precedence. Gaps invalidate continuity. Do not keep the old rule that touching A's far boundary cancels a fixed-target setup; that boundary is no longer its target. Freeze B extreme and confirmation level at setup creation.
5. Entry: first valid executable observation at/after confirmation close. OHLC replay uses the contiguous next M5 open with stated spread assumptions; BUY entry Ask, SELL entry Bid. Live integration is not activated in this task. Preserve freshness checks (30 seconds) and maximum spread 0.50 price units.
6. Stop: B sweep low minus 2 ticks for BUY; B sweep high plus 2 ticks for SELL, rounded outward to the instrument tick. Reject invalid order/zero risk. Preserve observed/assumed spread effects instead of disguising them in the stop geometry.
7. Target: calculate from the executable entry and stop risk, rather than A's opposite edge. Test two separate profiles: TP = entry plus/minus 1.0 * risk, and TP = entry plus/minus 2.0 * risk. Round outward so actual computed reward/risk is at least the chosen profile ratio. Apply slippage and costs to performance separately and state the difference between quoted geometry and simulated fill return.
8. Frequency controls: at most one active simulated signal per symbol, no duplicate alerts for an A/B/profile, at least 30 minutes between newly created signals, and a maximum of four new signals per Bangkok calendar day. A maximum of four is not a minimum requirement. Two-hour outcome expiry, marked using an available exit-side observation with no future quote. Invalidated or rejected candidates do not count toward the daily cap. Candidate and alert dates use Asia/Bangkok correctly; DST must not be invented for Bangkok.
9. Outcomes: reuse consistent Bid exits for BUY and Ask for SELL, next-observation execution, explicit ambiguous same-M5-bar TP/SL handling, and no optimistic intrabar ordering. No fabricated tick coverage. If several candidates compete, define deterministic chronological priority and do not pick using future outcomes.

## Implementation scope

- Read prompt/AGENT_TO_AGENT.md and report/20261006-signal-frequency-test-report.md.
- Preserve original CRT source and historical results. Prefer a new strategy module and explicit replay profile selection; do not overload the old CRT definition or silently change its timeframe/TP.
- Add necessary validated settings/profile identifiers without changing the active live config or fallback strategy selection. New artifacts should clearly identify timeframe, fixed risk:reward, controls and strategy version.
- Keep the replay path pure/in-memory; use existing supported GET /api/market/bars to acquire real candles. Do not initialize a competing MT5 session or send replay results to live signals/outbox. An independent project-local replay runner that uses the shared new strategy module is acceptable for this first phase; do not wire an unsupported live selector just for appearance.
- Use appropriate new strategy/replay tests. Do not claim tests cover live behavior if only replay is implemented.
- Update documentation with exact new rules, profile selection and measured results. Leave current server running, current min_reward_risk and Telegram opt-in unchanged. No restart, scanner/Telegram toggle, messages, orders, credentials, dependencies or direct live DB edits in this task.

## Evaluation and acceptance

Run both fixed-RR profiles on real broker history, roughly the same 60 days. Report actual data bounds and coverage. Predeclare rules above before examining profile outcomes, then run once per profile. Preserve all failures and raw counts, not only successes. Do not tune against the later segment or run unreported variants until a desirable result appears.

The already reviewed 60-day sample is exploratory, even if it is split chronologically. Keep its 70/30 split for comparability, but call the later segment a comparison period, not untouched validation. A fresh forward paper-validation period is needed before choosing live deployment; state this practical limitation without claiming profitability.

For each profile report:
- Candidate funnel, rejection reasons, confirmation count and confirmed signal count.
- Bangkok daily table including dates with zero signals; observed coverage on each date.
- Mean, median, min/max signals per date; number and percentage of dates with 0/1/2/3/4 signals; percentages reaching at least 3 and exactly 3–4.
- Separate all dates from reasonably covered dates (predeclare >= 12 hours of valid M5 data), and disclose partial/gap dates. Do not remove full zero-signal dates from the denominator. State trading-days versus 60 calendar days clearly.
- TP/SL/ambiguous/open/expired outcomes, net mean/total R, maximum drawdown and sample sizes for earlier/later periods.
- A single cost sensitivity rerun using spread 0.40 and slippage 0.10, compared with baseline spread 0.20 and slippage 0.05. This is a robustness check, not a new strategy-search grid. Preserve spread <= 0.50 acceptance.
- State whether the 3–4-per-day objective was achieved, on which percentage of covered dates, and whether the later-period/cost results support further testing. If neither meets it, report that plainly; do not compensate with arbitrary alerts or additional unapproved strategy changes.

## Required checks

Cover strict sweep/return comparisons; M15/M5 aggregation and gaps; trend warmup and no future bars; confirmation at B close vs after it; invalidation precedence; Ask/Bid entry/exit; tick rounding and actual 1:1/1:2 geometry; same-bar ambiguity; concurrent candidates and duplicate prevention; cooldown and Bangkok day rollover; daily cap counting only accepted signals; outcome expiry and period-end data; and preservation of CRT behavior. Run the existing suite and focused new tests. Keep all downloads, caches and temporary artifacts in this project.

## Report and stopping condition

Acknowledge exact task/source in report/20261006-144723-fast-sweep-strategy-progress.md. If a material requirement or design conflict prevents consistent implementation, write the question to the exact final report and stop dependent work instead of silently inventing changes.

Publish a complete report atomically with matching task ID/source, changed files, executable replay command, actual tests, full frequency/performance tables, rejected alternatives, caveats and a concrete next step. Stop after reporting. Do not activate this strategy live or dispatch another task; Codex will review with the user.
