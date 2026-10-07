# Investigate why the 60-day MT5 replay has zero signals

Task ID: 20261005-135654-investigate-zero-replay-signals
Delivery status: DRAFT — DO NOT EXECUTE
User authorization: pending
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261005-135654-investigate-zero-replay-signals.md`
Report path: `report/20261005-135654-investigate-zero-replay-signals-report.md`

## Goal and evidence

User supplied screenshot .img/image copy 6.png and explicitly asked: "ask claude why has no signal 60 day ?". Diagnose the existing zero-signal 60-day MT5 replay; distinguish strategy filters, unavailable/invalid historical data and implementation defects. This is investigation, not permission to tune rules or implement a fix.

Screenshot: XAUUSDc, requested last 60 days, returned 11560 M5 / 963 H1 bars, period 2026-08-06T07:00:00Z to 2026-10-05T06:55:00Z, development 592 candidates (465 rejected, 75 invalidated, 52 expired), holdout 242 (190 rejected, 31 invalidated, 21 expired), both zero signals. Screenshot cost text is OHLC-assumed even though Use ticks is on and Run replay disabled; do not infer the completed result used ticks from control state alone.

Codex GET /api/replay?source=mt5 at dispatch returned the same period/candidate counts, config CRT-SMC-v1@193949a6, but costs now say tick Bid/Ask. An immutable local copy of the actual response is .tmp/20261005-135654-investigate-zero-replay-signals-snapshot.json. Anchor to that saved result and explain any screenshot/result-mode discrepancy instead of conflating separate runs.

Important saved reason counts across development + holdout:
- no_quote: 32 + 3 = 35.
- reward_risk_below_minimum: 0 + 7 = 7.
- buy/sell sweep close outside A: 137+65 + 144+53 = 399.
- double_sided_sweep: 78+33 = 111.
- sweep_extreme_revisited: 53+25 = 78.
- opposite_boundary_touched: 22+6 = 28.
- no_confirmation_within_window: 52+21 = 73.
- noncontiguous_hours: 30+12 = 42.
- no_confirmed_swing_high_inside_a: 17+5 = 22; swing low: 21+8 = 29.
- insufficient_m5_history: 6+4 = 10.
Do not stop at "strategy is strict". Explain especially why 35 confirmed candidates have no quote and why the remaining 7 fail RR. Verify the counts and stage interpretation.

## Read-only investigation

1. Read project instructions, screenshot and saved replay JSON, current state, app/replay.py, app/engine.py, app/strategy.py, app/feeds MT5/history code, relevant replay tests and config/strategy.json. Write progress receipt to report/20261005-135654-investigate-zero-replay-signals-progress.md.
2. Reconcile the total funnel: H1 pairs examined, sweep/range checks, available structure, M5 confirmation, entry/quote/spread/RR checks, final signals. Show counted stages supported by records; separate known totals from reconstructed/inferred ones. Note that no_sweep pairs may not become candidates.
3. Trace no_quote exactly in the completed run's source mode. In tick replay, check historical tick availability/read limits, callback exceptions/empty reads, date range, timestamp bounds and freshness window (first valid tick after confirmation); distinguish market gaps from swallowed MT5 errors. In OHLC mode, check next-bar continuity and price construction. Verify source mode rather than attributing one mode's failure to the other.
4. Inspect data coverage: requested vs returned dates/bar counts, duplicate/invalid bars, expected market closures vs actual missing candles, H1/M5 alignment, structure lookback, symbol precision/tick size and costs. Inspect recorded replay errors/logs without secrets.
5. If useful, reconstruct a small number of concrete failed confirmations from read-only paginated /api/market/bars history (within supported count limits), and run an isolated in-memory diagnostic on identical period/config with outputs solely under .tmp. The live result does not retain candidate rows; clearly distinguish such reconstructed broker-history evidence from original stored replay evidence. Never claim a reconstructed quote/tick value was retained in the original run.
6. Produce at least one concrete no_quote example if evidence can be obtained safely, and one RR failure with confirmation time, direction, intended entry, SL/TP, distance/cost calculation and configured threshold. Do not invent numbers when unavailable. Assess whether current code behavior matches its rules or identifies a concrete defect, and describe a minimal proposed remedy if supported.
7. Check UI source/output mismatch and whether "Use ticks" is just the next run setting while old results are still displayed. Confirm whether disabled Run replay reflects an active run or stale UI state with current API evidence.

## Preservation

No application code edits, strategy tuning, weakening validation to force signals, live replay POST, restart, scanner/Telegram toggle, mode/symbol/config changes, external Telegram messages or orders. Do not modify saved latest replay outputs, live database/history or session watermark. Do not start a competing MT5 session or separately initialize/shutdown the terminal connection. Historical data may be read through existing supported running-app interfaces only. If safe historical tick retrieval is unavailable, state that limitation instead of adding an endpoint or bypassing the live connection.

All temporary diagnostic scripts, fixtures, output and cache paths stay in this project; no global credentials/account/chat/token output. Use relevant existing tests only if needed to substantiate suspected defects; a full suite is not necessary for a diagnosis.

## Acceptance and report

Explain in plain language why this replay's 834 candidate records produced 0 signals, with a clear breakdown separating initial invalid setups from confirmed setups rejected at entry. Address the observed 35 no_quote and 7 minimum-RR failures with evidence and limitations. Do not state the strategy can never signal or is profitable/unprofitable based solely on this incomplete replay. Show UTC and Bangkok times for concrete examples. Cite project-relative code locations and actual local data sources.

Claude investigates; Codex reviews. Publish the complete final report atomically through a project-local temporary file to the exact report path, matching task ID/source, sources/actions, findings, factual funnel, concrete examples, suspected defects vs verified behavior, limitations and proposed next step. If materially blocked, report verified facts and missing evidence. Stop after reporting; fixes require a separately approved task.
