# Project code review ? Codex

Review date: 7 October 2026. Review-only operation; no application code fixes or Claude implementation task dispatched.

**Result: six confirmed defects, including three high-priority execution defects.** The 336 existing tests pass, but they do not cover the reproduced failure paths below. Fix findings 1?3 before relying on continued automatic execution; then address the cancellation race and data validation. Finding 6 affects legacy signal reporting rather than FVG broker positions.

## Scope and method

Reviewed first-party backend strategy, feed, scanner, execution, persistence, delivery, web controls, outcome/replay logic, dashboard logic and asset pipeline, plus the agent-to-agent bridge/task-panel execution and approval paths. This was a project-wide audit with the deepest review on trading and lifecycle logic; it is not a claim that every presentation/style line has been exhaustively inspected.

Excluded dependency internals, `node_modules`, the virtual environment, vendor UI assets, and generated third-party bundles. Used source inspection, existing automated tests, syntax/type checks, generated-template consistency checks, and isolated reviewer reproductions. Broker reproductions used the existing test fake broker or a fake submitter; **this review sent no MT5 orders or external test messages**. Read-only requests inspected the already-running local application. No settings, arming state, running services, or strategy parameters were changed.

The workspace root has no Git repository, so verification used SHA-256 snapshots: **90 inventoried source files compared, zero changes**. Reviewer scripts, evidence, and this report are separate audit artifacts.

## Confirmed findings

### 1. High / P1 ? Arming can carry to another MT5 server that reuses a login number

**Locations:** [account fingerprint](E:/VideCode/vc_trade/app/fvg_execution.py:48), [saved arming binding](E:/VideCode/vc_trade/app/web.py:167), [submission account check](E:/VideCode/vc_trade/app/fvg_execution.py:178), [reconciliation identity check](E:/VideCode/vc_trade/app/fvg_execution.py:325), [cancellation identity check](E:/VideCode/vc_trade/app/fvg_execution.py:402).

The execution identity is derived solely from the login. If execution is armed on Server A and the terminal switches to Server B with the same login number, the saved opt-in still matches. The feed can correctly reconnect and update its time base to Server B; the executor's time-base server check then checks against that new current server, not the server on which the user originally armed execution.

**Reproduction:** two fake accounts with the same login and different servers produced equal execution bindings; the original opt-in matched the second account, and submission accepted all three fake pending orders. This demonstrates a consent-binding defect; it does not claim that a live account switch occurred.

**Impact:** subsequent eligible orders can execute on an account/server other than the account explicitly armed. Reconciliation and cancellation share the same incomplete identity boundary.

**Fix:** bind opt-in, execution policy, and execution journal to a canonical server-plus-login identity, and enforce it at submission, reconciliation, and cancellation. Legacy login-only saved opt-ins should fail closed and require deliberate rearming rather than silently inheriting consent. Add same-login/different-server regression coverage. MT5 exposes both fields in [its official account information API](https://www.mql5.com/en/docs/python_metatrader5/mt5accountinfo_py).

### 2. High / P1 ? A delayed healthy scan can submit an expired historical confirmation

**Locations:** [confirmation acceptance](E:/VideCode/vc_trade/app/fvg_live.py:197), [new pending expiry based on current time](E:/VideCode/vc_trade/app/fvg_live.py:215), [scanner processing of accumulated bars](E:/VideCode/vc_trade/app/scanner.py:278), [deadline cleanup after bar processing](E:/VideCode/vc_trade/app/scanner.py:293).

The engine validates the session watermark but does not reject a confirmation because it is old relative to decision time or because the setup has already expired at decision time. Setup advancement checks historical bar time. If the process is suspended or blocked between healthy scans, its next scan can receive a fresh quote while processing older accumulated M5 bars. No intervening unhealthy observation necessarily resets the watermark. Deadline cleanup occurs after processing those bars, and acceptance creates a fresh two-hour pending lifetime from the current time.

**Reproduction:** the full bar-driven FVG/retest/confirmation path was processed with decision time three hours after confirmation. It still called the fake submitter once and recorded `orders_pending`. A separate direct confirmation reproduction also queued a plan alert despite the setup being expired.

**Impact:** execution may begin hours after the setup was actionable, even with a current broker quote. Fresh-quote checks alone do not establish fresh-signal eligibility.

**Fix:** enforce setup expiry and an explicit confirmation-age bound at the final acceptance boundary, before alerts, basket reservation, or order submission. Consume/reject stale confirmations without replaying them on the next scan. Test long suspension followed by fresh quotes, backlog processing, and expiry-boundary behavior; preserve ordinary timely live confirmations.

### 3. High / P1 ? A post-send exception becomes a false preflight rejection and stops reconciliation

**Locations:** [broad exception classification](E:/VideCode/vc_trade/app/fvg_live.py:237), [open-state reconciliation filter](E:/VideCode/vc_trade/app/fvg_live.py:278), [journal update after broker acceptance](E:/VideCode/vc_trade/app/fvg_execution.py:304).

The engine labels any exception from `submit()` as `preflight_rejected`. However, an exception can occur after an order has reached the broker?for example, when saving the accepted ticket to the execution journal fails. A basket saved as `preflight_rejected` is excluded from subsequent reconciliation. Restart recovery adopts a journal only for a basket still marked `planned`, so this state can persist across maintenance/restart.

**Reproduction:** the fake broker accepted the first pending order. An injected journal I/O failure on the following save left the durable journal at `submitting`, with the first leg `sending`. The basket was recorded as `preflight_rejected`; another maintenance pass left it there rather than recovering the accepted order.

**Impact:** an accepted broker order is no longer represented by the application's active basket lifecycle. Its broker SL/TP are not removed by this failure, but application tracking, cancellation and outcome reporting can be lost. Existing broker-exposure checks still block another submission, so this finding does not assert immediate duplicate exposure.

**Fix:** distinguish a genuine no-send preflight rejection from submission uncertainty. If a durable journal exists or sending may have begun, keep the basket in reconciliation and adopt the journal without resubmitting. Test journal failures immediately before and after sends, partial batch acceptance, and restart recovery.

### 4. Medium / P2 ? Cancellation can hide a position filled since the previous reconciliation

**Locations:** [pending-order removal](E:/VideCode/vc_trade/app/fvg_execution.py:394), [terminal-state assignment based on stale leg state](E:/VideCode/vc_trade/app/fvg_execution.py:416), [terminal legs skipped during reconciliation](E:/VideCode/vc_trade/app/fvg_execution.py:344).

A pending leg may partially fill after the last reconciliation and before cancellation. `cancel_remaining()` sees the still-live pending remainder, removes it, then chooses the terminal state using the stored leg state. If that stored state is still `pending`, it writes `cancelled` instead of preserving the filled position. Reconciliation permanently skips this terminal leg and can mark the whole basket closed.

**Reproduction:** the fake broker had a partially filled first order and one open position while the stored leg still said `pending`. After cancellation, all three pending remainders were removed, the first leg was `cancelled`, filled volume was unrecorded, and reconciliation marked the basket `closed` while the fake broker still held that position.

**Impact:** application exposure/P&L tracking becomes incorrect. The filled position retains its broker SL/TP; canceling its pending remainder does not close the position.

**Fix:** treat a successful removal as cancellation of the remainder, not proof of a flat position. Reconcile fresh order/deal/position evidence before finalizing the leg and basket, including fills racing with removal. Test partial fill followed immediately by cancellation without a prior reconciliation. Relevant broker evidence is available through the official [order history](https://www.mql5.com/en/docs/python_metatrader5/mt5historyordersget_py) and [deal history](https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py) APIs.

### 5. Medium / P2 ? Aggregation can hide an invalid M5 candle and still qualify an FVG

**Locations:** [higher-timeframe aggregation](E:/VideCode/vc_trade/app/models.py:103), [FVG detection from aggregated history](E:/VideCode/vc_trade/app/fvg_live.py:172), [warm-up computation](E:/VideCode/vc_trade/app/fvg_live.py:323).

Aggregation checks group size/alignment/continuity but does not validate every constituent candle or its M5 timeframe. An invalid constituent high below its open can be hidden by another constituent's larger high, producing an apparently valid M15 candle. FVG qualification validates those aggregated candles, so malformed source data can qualify a setup and contribute to warm-up.

**Reproduction:** one M5 constituent in FVG candle A was changed to `high < open`. The M5 candle was invalid, the aggregated M15 A was valid, and detection recorded a `pending` FVG with no rejection reason.

**Impact:** source-data integrity and the intended warm-up/reset boundary are bypassed. This is a malformed-input reproduction, not evidence that the current broker supplied corrupt candles. Shared aggregation also affects other strategies and replay consumers.

**Fix:** exclude any higher-timeframe group containing an invalid constituent or a non-M5 timeframe. Preserve the resulting time gap so contiguous warm-up cannot bridge over it. Test invalid constituent candles whose aggregate would otherwise appear valid, wrong timeframes, and consistent live/replay readiness behavior.

### 6. Medium / P2 ? Legacy measured outcomes can credit a TP/SL reached after expiry

**Locations:** [measured outcome loop](E:/VideCode/vc_trade/app/outcomes.py:96), [expiry evaluated after tick hits](E:/VideCode/vc_trade/app/outcomes.py:124), [tick replay's existing expiry clipping](E:/VideCode/vc_trade/app/replay.py:193).

After an outage or delayed scan, measured tracking evaluates recovered observations all the way to the current time before checking the signal's outcome expiry. A TP/SL tick after that expiry can therefore settle the signal as a hit. Tick replay already limits observation processing to the expiry deadline, so live reporting and replay disagree.

**Reproduction:** a legacy FastSweep signal had a two-hour outcome expiry, a safe tick at minute 119, and a TP tick at minute 150. Tracking at hour three reported `tp` at minute 150 instead of expiry at minute 120.

**Impact:** legacy CRT/FastSweep signal history and performance statistics can report incorrect outcomes. This does **not** imply that an already-filled FVG broker position should close at its pending-order expiry; that is a different lifecycle.

**Fix:** stop evaluating outcome ticks at the signal expiry, settle expiry at that deadline using the last eligible observed exit-side price, and retain measurement-gap information. Add before/at/after-expiry tick cases and verify equivalent live/replay results.

## Validation and evidence

| Check | Result |
|---|---:|
| Backend `pytest` | 255 passed |
| Dashboard `npm test` | 36 passed |
| Agent bridge tests | 11 passed |
| Task-panel tests | 34 passed |
| **Existing tests total** | **336 passed** |
| Task-panel TypeScript typecheck | Passed |
| Python source syntax parsing | 49 files passed |
| First-party JS/MJS syntax checks | 21 files passed |
| Generated dashboard HTML vs source template | Matches |
| Duplicate generated HTML IDs | None |
| Inventoried source files changed during review | 0 / 90 |

Existing passing tests do not invalidate the confirmed counterexamples. Reviewer reproductions are separate audit scripts; regression tests and fixes have not been added to the application. One existing Starlette/httpx deprecation warning appeared. Ruff was not installed, so no Ruff result is claimed. No live broker order submission, fill, cancellation, pending-expiration acceptance, or browser end-to-end interaction was exercised.

Evidence:

- [Initial reproduction script](E:/VideCode/vc_trade/.tmp/full-code-review-20261007/reproduce.py) and [results](E:/VideCode/vc_trade/.tmp/full-code-review-20261007/reproduction-results.json): findings 1, 2 and 4.
- [Additional reproduction script](E:/VideCode/vc_trade/.tmp/full-code-review-20261007/reproduce-additional.py) and [results](E:/VideCode/vc_trade/.tmp/full-code-review-20261007/additional-reproduction-results.json): integrated confirmation path and findings 3, 5 and 6.
- [Validation summary](E:/VideCode/vc_trade/.tmp/full-code-review-20261007/validation-summary.json), [backend test XML](E:/VideCode/vc_trade/.tmp/full-code-review-20261007/backend-tests.xml).
- [Source manifest before](E:/VideCode/vc_trade/.tmp/full-code-review-20261007/source-manifest-before.json) and [after](E:/VideCode/vc_trade/.tmp/full-code-review-20261007/source-manifest-after.json).
- [Sanitized final runtime snapshot](E:/VideCode/vc_trade/.tmp/full-code-review-20261007/runtime-final-sanitized.json).

## Runtime at review completion

Observed 2026-10-07 15:16?15:17 Bangkok time (08:16?08:17 UTC): FVG M15/M5 RR2 active on MetaQuotes-Demo **demo**, XAUUSD; scanner running without an error; automatic execution **ON**; Telegram **ON** and persisted. Fixed risk remains **$10 total per three-order basket**. Warm-up is **41/50 contiguous M15 candles**, not ready; the FVG store contains zero setups and zero baskets. These observations describe current application state, not successful real broker execution.

Both enabled flags were preserved. This review did not disarm execution, rearm it, change the strategy, restart services, or send alerts.

## Recommended fix order

1. Complete the server/account consent boundary and stale-confirmation rejection before further autonomous trading.
2. Recover every potentially sent order after exceptions; no uncertain order should be represented as a preflight rejection.
3. Resolve the partial-fill cancellation race and raw-candle validation.
4. Correct legacy outcome expiry accounting and add meaningful regression cases for all six findings.

Minor maintenance: some older read-only claims remain in documentation and the MT5 mode-switch notice even though armed FVG execution can place orders. Refresh those statements to match current behavior. This is separate from the six reproduced defects.
