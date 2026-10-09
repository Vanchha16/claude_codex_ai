# Build and activate independent M15 and M5 FVG order engines

Task ID: 20261008-143801-dual-timeframe-fvg-engines
Delivery status: APPROVED FOR EXECUTION
User authorization: On 2026-10-08 the user explicitly said "send it" after reviewing the independent M15/M5 engines, immediate qualified-FVG pending orders, one concurrent basket per engine, $10 per basket/$20 total planned risk, and the final draft. This authorizes implementation, validation and activation on the currently configured XAUUSD demo account, including the draft defaults of 30-minute cooldown per engine and four accepted baskets daily total. Published at 2026-10-08T07:48:16.0036094Z; approved draft SHA-256: 3d20a52c327a3b760fef3dc967428fceb37d1ec15eb44e86bd8e912bb408130e.
Project root: E:\VideCode\vc_trade
Source prompt: `prompt/20261008-143801-dual-timeframe-fvg-engines.md`
Report path: `report/20261008-143801-dual-timeframe-fvg-engines-report.md`
Progress path: `report/20261008-143801-dual-timeframe-fvg-engines-progress.md`

## Goal and settled requirements

The user requested two FVG engines together and clarified: "when have FVG the system place the order. m15 analyze by m15. m5 analyze by m5 and it both analyze each together. engin by engin."

The user explicitly chose:
- Immediately when its FVG passes qualification; no separate retest/confirmation.
- Allow one M15 basket and one M5 basket together; $10 risk per basket ($20 total planned risk).

Implement two independent engines running concurrently. M15 detects/qualifies its own M15 FVGs; M5 detects/qualifies its own M5 FVGs. Neither needs the other's direction, readiness, zone or approval. Each can submit a basket of three pending limits immediately when its own newly closed candle C creates a qualifying FVG and the shared broker/eligibility checks pass. Two baskets mean up to six legs. This is a new strategy version. Preserve legacy M15-FVG/M5-retest-confirmation v1 as a rollback/historical rule set.

## Exact strategy rules

1. Each engine uses three adjacent valid CLOSED A/B/C candles on its own timeframe. BUY gap A.high..C.low; SELL gap C.high..A.low, separated by at least one tick, available only after C closes. No forming-bar decisions.
2. Qualification uses that engine's OWN contiguous history ending at C: EMA20/EMA50 with 50-candle minimum, ATR14 through B, gap >= max(2 ticks, 0.10 ATR14), directional B body >=1.0 ATR14, trend in the gap direction. Equal EMAs allow neither. Preserve decimal/tick boundary behavior. Data/market gaps reset the relevant timeframe's run. Apply this existing rule family independently to M15/M5; do not remove warm-up or borrow indicators across timeframes.
3. Qualification is the entry event: NO retest or subsequent confirmation. Candle C must close strictly after the current healthy-session watermark and be <=30 seconds old at the actual decision/send boundary. Historical loading, catch-up, resume and reconnect never retroactively submit a qualified gap. Record skipped/rejected gaps with reasons; do not resend them when conditions improve.
4. Use the originating engine's zone for three limits at 1%/50%/80% depth, common SL two ticks beyond the far edge, and each leg's own 1:2 TP. Reuse existing exact rounding and sizing. Reject the whole basket if distinct prices, stop/spread distance, correct resting side, quote freshness, lot minimum or broker preflight fails. Never substitute a market order. A raw detected gap without qualification is not an order.
5. Risk is $10 total planned SL risk PER basket, equally split into three nominal thirds before lot flooring. One M15 and one M5 basket can coexist: $20 concurrent planned risk, not $10 across six legs. Retain USD/USC conversion and no redistribution. This is nominal risk; fees/gaps/slippage may exceed it.
6. One open or unresolved basket PER ENGINE, including pending legs and remaining filled exposure. Same/opposite directions can coexist under the existing hedging-account requirement. Pending/sending/unknown/partial outcomes occupy their engine's slot; a deadline or attempted removal alone never proves capacity is free.
7. Operational defaults approved with this task: 30-minute cooldown PER ENGINE; four accepted baskets per Bangkok day TOTAL across both engines, not four each. Simultaneous qualified M15/M5 gaps can both be accepted when slots/risk/daily cap allow. At identical decision timestamps process M15 then M5 deterministically to allocate a final shared daily slot. Expose these scopes explicitly in configuration/API/UI/versioning.
8. Pending legs expire 120 minutes after placement. Candle-close zone invalidation uses the originating timeframe: a later closed M15 candle for M15, or closed M5 candle for M5, BUY close <bottom / SELL close >top. Wicks and the other engine's closes do not satisfy that rule. Preserve existing common quote-based invalidation/broker protections, clearly distinguishing them from candle-close invalidation. Remove only that basket's owned pending remainder; do not cancel the other engine's orders or close existing filled positions.

## Architecture and compatibility

One scanner/feed owner supplies validated closed M5 and complete derived M15 bars chronologically. Process each close once. Extract focused timeframe-aware pure rules and engine state rather than duplicating two large live engines. Each engine has its own timeframe/config/version, IDs, readiness, processed-close watermark, zones, rejection reasons, cooldown and occupied slot.

One shared order manager enforces atomic capacity/daily reservations, total planned risk, account/source/symbol binding, quote/spread/placement guards and durable sends through `app/fvg_execution.py`. Preserve send-boundary account/clock checks, original-account reconciliation/cancellation, owner locks, unknown/partial evidence and never-resend behavior. Every basket records engine, originating zone, decision close, original account and risk. Independent analysis must not become a hidden confluence requirement.

Keep CRT, FastSweep and legacy FVG selectable. Fingerprint the new mode/configs, namespace engine/setup/basket/journal IDs, retain additive backwards-compatible storage, and never reinterpret a v1 setup as a new dual signal. Do not inherit version-specific consent silently; activation records new explicit consent for the approved dual rules.

Existing legacy baskets remain managed under their recorded rules. Same-account/symbol legacy FVG exposure occupies the M15 slot and contributes its recorded risk/daily history until resolved; unavailable identity/risk is not assumed zero. Activation never cancels exposure merely to free a slot. Preserve all uncommitted work and existing journals.

Provide chronological replay using the same pure rules and distinguish simulation from real broker evidence. Tests/replays never send to broker/Telegram.

## Dashboard and Guide

Show both engines together: timeframe, closed-bar readiness and next close, trend/ATR, detected zones, qualification/rejection reasons, decisions, cooldown and occupied basket. Shared summary shows the two slots, $10 per basket/up to $20 concurrent planned risk, and total daily count. Every order/chart/log/Telegram basket identifies M15 or M5.

New Guide path: CLOSED A/B/C FVG -> qualification -> eligibility/preflight -> three pending limits -> later fills. Pending limits are not immediate market fills. Retest/confirmation is shown only for explicitly labelled legacy records. Preserve truthful accepted-leg counts and unknown/partial evidence. Include deterministic examples for both engines, simultaneous same/opposite directions, one warming up while the other is ready, rejected sizing/spread, and pending versus filled/unknown states. Learning controls remain read-only.

## Scope and activation after approval

Read `app/fvg.py`, `app/fvg_live.py`, `app/fvg_replay.py`, `app/fvg_orders.py`, `app/fvg_execution.py`, `app/scanner.py`, `app/active_strategy.py`, `app/web.py`, `app/models.py`, dashboard/Guide source and tests. Prefer focused modules and additive loaders/migrations.

The previous Guide task has published its matching final report: `report/20261007-201709-fvg-confirmation-entry-guide-report.md`. Read it and the review-observations file; retain its fixes. Do not re-execute that completed task.

The user's recorded "send it" approval authorizes implementing, validating, selecting and activating this dual mode on the currently configured XAUUSD DEMO account, automatic execution ON, $10 per basket, and the limits above. Validate before activation. Record the real task approval through the existing consent mechanism for the actual new versions/account/source/symbol. A normal launcher restart is within that final scope. Preserve Telegram's current preference and journals. Natural future qualifying setups may create the requested orders after activation.

If the account changes, is unavailable, or is not demo at activation, report the blocker; do not login/switch/initialize MT5 or use a substitute account. No synthetic live signal injection, artificial live test order/removal, test Telegram message, destructive database migration, global changes, commit or push. Do not cancel exposure for testing. Keep work/caches/fixtures in this project.

## Acceptance and verification

- Independent M15/M5 detection, qualification, warm-up and immediate-C triggers; neither readiness nor direction depends on the other engine. Correct BUY/SELL geometry, strict boundaries, no forming/future evidence, continuity resets and watermark/freshness gating.
- Simultaneous admission with atomic shared daily cap and deterministic tie handling, per-engine cooldown/capacity, $10 each/$20 concurrently, no duplicate sends across polls/restarts, and correct legacy/unresolved exposure accounting.
- Minimum-lot/resting-price/spread rejection, send-boundary account changes and partial/unknown sends neither fabricate acceptance/fills nor release slots or cause resends. Cancellation touches only bound owned orders.
- Live/replay fixtures agree; historical v1 records/orders/consent remain correctly interpreted. Read-only Guide GETs cannot submit/cancel/change execution.
- Run meaningful focused and full backend tests with fresh in-project basetemp; frontend tests/build and changed-JS syntax checks. Report any recurrence of the intermittent MT5-time test noted in the Guide report honestly.
- Visually verify desktop/mobile, light/dark, both engines, current/legacy Guide, warm-up/disconnected and pending/filled/unknown distinctions using isolated mocks for synthetic scenarios. Document unavailable checks accurately.
- After activation, read-only runtime verification reports account context, versions, feed/scanner freshness, execution, risk/slots/daily counts, Telegram, and naturally arising setups/baskets/exposure; do not assume zero exposure.

## Reply and stopping condition

Codex plans/reviews; Claude implements only the approved published prompt. Acknowledge at the exact progress path. Publish the full final report atomically through an in-project temporary file: rules/config defaults, changed files, actual tests/build/visual evidence, migration/rollback, activation/consent and runtime evidence. Stop after reporting; no self-dispatched follow-up. Ask only for material missing requirements unresolved by this specification.
