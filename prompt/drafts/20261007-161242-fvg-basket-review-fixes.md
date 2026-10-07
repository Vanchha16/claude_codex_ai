# Finish and harden the confirmed three-entry FVG basket engine

Task ID: 20261007-161242-fvg-basket-review-fixes
Delivery status: DRAFT - REQUIREMENTS PENDING - DO NOT EXECUTE
User authorization: pending review of the concrete task. The user requested "let tell claude to build" after reading both code reviews and the basket explanation. No execution prompt has been published yet.
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261007-161242-fvg-basket-review-fixes.md`
Report path: `report/20261007-161242-fvg-basket-review-fixes-report.md`
Progress path: `report/20261007-161242-fvg-basket-review-fixes-progress.md`

## Goal and context

Finish the existing FVG basket engine by fixing the eight independently confirmed issues from the two reviews. This is maintenance of the already-built strategy, not a replacement strategy or a duplicate initial build. Preserve the user-confirmed trading rules below. Do not invent different entries, move the shared stop to a candle close, increase risk, tune profitability, or implement a new strategy.

Read these authoritative context files in full:

- `report/20261007-151829-full-code-review-codex.md`: six confirmed defects with reproductions.
- `report/20261007-151949-full-code-review-findings.md`: Claude's informational review, not a completed fix task.
- `report/20261007-152543-claude-full-code-review-codex-response.md`: two more confirmed cases, corrections to Claude's runtime assumptions, and qualification of suggested remedies.
- `prompt/AGENT_TO_AGENT.md`: roles, approval gate and report contract.

Runtime must be rechecked, not assumed from Claude's earlier OFF status. Last verified at 2026-10-07 08:21:46 UTC: MetaQuotes-Demo **demo**, XAUUSD, FVG rr2, automatic execution **ON**, Telegram **ON** and persisted, fixed risk 10 USD, warm-up 41/50, no scanner error. Review reproductions used fake brokers/feeds only. The existing application's tests passed: 255 backend, 36 dashboard, 11 bridge, 34 helper-panel; the eight failure cases are missing from those existing checks. No source fixes have yet been made by Codex.

## Rules to preserve

- M15 FVG qualification with EMA20/EMA50 trend and ATR14, the existing displacement/gap rules and 50 contiguous M15 warm-up after a break.
- First M5 retest, then a distinct later closed M5 continuation confirmation within the next three M5 bars.
- Three pending limit orders at **1%, 50%, 80%** depth measured from the near edge into the FVG.
- One shared stop **two ticks beyond the wick-defined far edge of the FVG**. Keep the wick edge rather than replacing it with a candle-close stop.
- Each entry has its own **1:2 reward/risk** target.
- Fixed **10 USD combined nominal planned SL risk per basket**, equal thirds before volume flooring. Lot size depends on each entry-to-stop distance and broker loss-per-lot. Preserve USD/USC conversion, supported currency checks and minimum-lot whole-plan rejection. Do not silently redistribute rejected-leg risk or increase volumes.
- One open basket for the applicable account/symbol; 30-minute cooldown; four accepted baskets per Bangkok day; two-hour setup/pending lifetimes as already configured. Keep accepted-basket counting semantics; this task does not switch the cap to fills or successful sends.
- Telegram's three four-field Entry/TP/SL/RR plan blocks and existing deduplication remain supported alongside automatic execution.

## Scope and relevant files

Primary implementation: `app/fvg_execution.py`, `app/fvg_live.py`, `app/fvg.py`, `app/fvg_orders.py` only if needed, `app/scanner.py`, `app/models.py`, `app/outcomes.py`, `app/fvg_replay.py`, `app/replay.py`, `app/web.py`. Shared identity/time helpers in `app/data/mt5.py` / `app/mt5_time.py` may be reused or minimally extended; preserve verified time normalization.

Tests: the relevant FVG/executor/scanner/feed/API/outcome/replay suites under `tests/`, with additional regressions for the concrete cases below. Minimal dashboard/API/docs changes only to show truthful execution, account-binding and maintenance states. No agent-to-agent helper changes are needed.

Do not read or print credentials, bot/chat identifiers, account logins, session tokens, or whole server/opt-in/.env files in reports. Preserve history, outbox state, opt-ins, settings and databases; no recursive cleanup of live state. This project has no root Git repository.

## Implementation plan

### 1. Bind consent and broker ownership to server plus login ? high priority

The current `account_fp(login)` and `_fvg_binding` omit the server. Use one explicit canonical server-plus-login identity consistently for opt-in, in-memory policy, execution journals, submission, reconciliation and cancellation. Check the originally bound identity, not merely the current feed time-base server. Both same-login/different-server and different-login/same-server switches must fail closed.

A legacy login-only opt-in must not be silently upgraded or accepted as consent for a server binding. Preserve the existing document/history but leave it unarmed until new explicit user arming. Do not discard old execution journals or assume they are safe to adopt on the currently connected account. Where an old journal lacks provable original server identity, retain it in a visible unresolved/account-unavailable state and explain the limitation. Existing orders must remain recoverable on their actual originating account.

Scope basket capacity by the proper account identity without dropping other-account orders from tracking. Avoid logging the same unavailable-account error every five seconds. Return to the original account must restore reconciliation without resubmission. Keep the cap based on accepted baskets within that account context.

### 2. Reject stale confirmations at the decision boundary ? high priority

Before any basket reservation, alert or broker call, check decision-time setup expiry and confirmation freshness in addition to the existing session watermark. Use an explicit **30-second maximum live confirmation age**, consistent with the existing freshness scale; zero-age synchronous replay confirmations remain eligible. Reject negative/future or expired confirmation context rather than granting another two-hour pending lifetime to old history. Record a clear consumed/rejected reason so the next scan cannot re-emit it.

Use a trustworthy current clock at final live execution/pre-send checks rather than aging a refreshed quote against an old scan-start timestamp. Keep feed/executor time-base agreement, stale/future quote guards, explicit verified broker offset and no automatic offset guessing. Preserve fake-clock testability.

### 3. Recover after post-send exceptions ? high priority

Do not label all `submit()` exceptions `preflight_rejected`. If a durable journal exists or sending may have begun, adopt its state into an open `needs_reconciliation` lifecycle. A genuine preflight failure with no possible send may remain rejected. If journal reads themselves fail, represent uncertainty conservatively and retry recovery when storage is available; do not invent proof that nothing was sent.

Crash recovery and maintenance must include these uncertain baskets, even after restart. Never resend uncertain legs or blindly finish an interrupted batch. Recover broker ownership using the durable pre-send reservation, identity, magic/comment/ticket and historical evidence.

### 4. Preserve positions when a fill races with pending cancellation

A successful `TRADE_ACTION_REMOVE` proves removal of a pending remainder, not that the leg has no position. Do not make a leg permanently terminal based on the last stored `pending` state. Reconcile fresh order/deal/position evidence after removal, including a partial or complete fill between scans and a delayed history response. Keep filled volume, remaining volume, realized outcome and basket exposure truthful. Never permanently skip a cancelled/expired remainder while its filled position is open or unresolved.

Only remove this basket's owned pending orders. Do not close a position or remove its broker SL/TP as part of a remainder cancellation.

### 5. Reject invalid M5 constituents before aggregation

Every constituent of a higher-timeframe group must be a valid M5 bar with the expected timeframe, OHLC values and continuity. An invalid candle must not become valid by taking another candle's high/low. Skip invalid groups and retain the resulting time gap so contiguous M15 warm-up cannot bridge over malformed data. Apply the same contract to live, replay and readiness consumers of shared aggregation.

### 6. Enforce legacy outcome expiry before evaluating recovered ticks

For CRT/FastSweep measured signal outcomes, process ticks only up to the signal's configured expiry. A post-expiry TP/SL must not override expiry. Settle at the deadline using the last eligible observed exit-side price, retain tick-gap annotations and do not interpolate unavailable ticks. Align equivalent live/replay and relevant bar-estimate behavior.

Do not apply this legacy outcome-expiry rule to force-close an already-filled FVG broker position when a pending remainder expires.

### 7. Apply far-edge pending maintenance through pause/resume

Keep new setup/confirmation generation blocked while paused, but continue managing already-submitted FVG baskets over trustworthy newly closed M5 bars. A far-edge close during pause must cancel owned remaining limits. On resume, process any skipped maintenance bars before advancing the new-entry eligibility marker. Handle stale/disconnected periods conservatively: use only trusted bar/account context and reconcile when broker access is unavailable; do not let a return inside the zone erase a prior invalidation.

Preserve the different purposes of maintenance progress and new-signal eligibility. Keep filled positions and their SL/TP intact.

### 8. Block spread-inside-stop baskets and align replay eligibility

At final preflight, reject the **whole basket** if any leg has entry-to-stop distance smaller than **current spread plus one symbol tick**. Equality at that minimum may pass. This specifies the smallest extra tick margin without altering entry percentages, common stop placement or total risk. Record a clear reason and queue no misleading executable plan after a failed eligibility gate.

Recheck the constraint with the fresh pre-send quote. Apply equivalent spread/broker-placement assumptions to FVG replay using its declared cost model; replay must not accept pending limits live would reject because they are already on the wrong side of the market. Preserve uncertainty labeling for bar fills, and report any changed replay acceptance counts without optimization or retuning.

The independently reproduced example is a valid 1.20-wide BUY FVG [116.60,117.80], 80% entry 116.84, shared SL 116.58, stop distance 0.26 and spread 0.33. It must be rejected by the new eligibility guard. Also test an eligible wider gap and symmetric SELL behavior.

Keep the existing Telegram Entry/TP/SL/RR format. Plan messages still must not be represented as proof of broker placement. Update any remaining misleading "no trades are placed" text to describe current armed FVG capability and actual acceptance state.

## Runtime and activation boundary

After task dispatch approval, use the normal authenticated local app control to **temporarily disarm automatic execution before implementation/restart**. This is necessary because the existing armed policy has the reviewed defects and its legacy identity binding must be invalidated. Verify actual current server/account type/symbol and preserve the 10 USD risk preference and Telegram user's ON preference.

Do not arm a new server-bound opt-in yourself, do not switch accounts, do not alter MT5 terminal settings, and do not send real order/check/cancel requests or test Telegram messages. Use fake brokers and delivery for all regression checks. Keep existing broker SL/TP and orders untouched; if real active exposure is discovered, report it and preserve its journal/ownership information rather than deleting it. Use only bounded read-only broker/API verification of current exposure if needed.

A normal local backend restart to load completed code is included only after focused/full checks pass and auto is verified OFF. Restart through the existing launcher under its feed lock/owner checks; no competing MT5 connection. Recheck updated FVG RR2, fresh quote/time normalization, readiness, risk preference, actual disabled execution state and Telegram preference. If arming/restart is blocked or active exposure makes migration unsafe, report the precise blocker and stop dependent activation rather than silently forcing it.

Final automatic execution remains **OFF pending fresh explicit server-bound rearming**. Telegram remains ON if it was ON at implementation start. State this accurately in the report. No real test trade or external test message is authorized by this task.

## Acceptance criteria

- All eight counterexamples are prevented or conservatively recovered, with specific regression tests that fail against old behavior.
- No account/server switch reuses consent; old login-only consent never silently arms a new binding; original orders remain tracked/recoverable.
- Delayed healthy scans cannot alert or submit expired/older-than-30-second confirmations.
- Every potentially sent order remains in an uncertainty/reconciliation lifecycle across errors and restart, with no blind resend.
- Partial-fill/cancellation races retain open positions and truthful basket state, including delayed evidence.
- Invalid constituent data breaks aggregation/warm-up consistently in live/replay.
- Legacy expiry accounting agrees across observation/replay boundaries; FVG filled-position lifecycle remains distinct.
- Paused-period invalidation is applied to existing pending remainders without creating new signals or closing filled positions.
- Spread-distance and placement gates agree between live and replay, while accepted entries, wick SL, TP rules and risk sizing remain unchanged.
- Existing known good timely wide-gap setups still produce the specified three legs in fake broker tests. Rejected/uncertain states remain visible and idempotent.
- Runtime is truthful after any approved restart: FVG RR2 active, fixed risk 10 USD, auto OFF pending rearm, user's Telegram preference preserved, no credential leakage and zero actual test orders/messages.

## Validation

Use the reviewer reproductions as evidence, but do not rerun their saved SQLite paths against existing rows. Add proper isolated test fixtures/regression tests instead:

- `.tmp/full-code-review-20261007/reproduce.py` and `reproduction-results.json`.
- `.tmp/full-code-review-20261007/reproduce-additional.py` and `additional-reproduction-results.json`.
- `.tmp/claude-review-20261007/reproduce-claude-findings.py` and `additional-findings-reproduction.json`.

Run focused relevant backend regressions, then the full suite, e.g. `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-20261007-161242-fvg-basket-review-fixes`. Use fresh unique project-local test databases. Add boundary cases for server/login changes, exact confirmation age/expiry, journal read/save errors around each send, partial fills around cancellation, invalid OHLC/timeframes, expiry ticks, pause-and-return-inside sequences, and BUY/SELL spread-distance/placement checks.

Run dashboard `npm.cmd test` in `frontend/` and required asset build/syntax checks only when those files are changed. Use existing local tools, project caches and isolated fixtures; no global dependency installation or unrelated helper changes. No live broker preflight/submission/cancellation is a regression test. Do not claim the previous 336 tests cover the new cases merely because they passed.

Report tests actually run separately from recommended, unavailable or inferred checks. Report actual runtime state with timestamp. Do not claim live broker acceptance, successful expiration, profitability or fixes active in the running process unless specifically observed.

## Reply and stopping condition

Codex is the planner/reviewer; Claude is the implementer. Acknowledge the approved task at the exact Progress path. Only one implementation task is authorized at a time. If material scope/runtime/ownership requirements are blocked, publish questions at the exact Report path and stop dependent work; do not choose unrelated strategies or send another task.

Publish the complete report atomically at `report/20261007-161242-fvg-basket-review-fixes-report.md` with task ID/source prompt, outcome, files changed, actual focused/full validation, regression coverage per finding, migration behavior, restart result, current ON/OFF flags, preserved $10 risk, readiness and any unresolved limitation. State zero actual test orders/checks/cancellations/messages. Report the need for new explicit arming.

After reporting, stop and wait for Codex's review and the next separately approved instruction.
