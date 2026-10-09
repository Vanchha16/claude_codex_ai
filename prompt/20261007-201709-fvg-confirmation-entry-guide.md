# Build the complete FVG confirmation-to-entry guide in the existing dashboard

Task ID: 20261007-201709-fvg-confirmation-entry-guide
Delivery status: APPROVED FOR EXECUTION
User authorization: On 2026-10-07 the user explicitly instructed "let build something to show me how it confirm to entry. i need full, tell claude to do that", then selected "Inside the existing dashboard". This authorizes this complete read-only dashboard FVG walkthrough implementation, tests/build, and a normal restart if needed to load presentation changes while preserving current execution/Telegram/risk preferences.
Published at: 2026-10-07T13:19:42.1206310Z
Approved draft SHA-256: d0d476037e46772a48c4a00231434799fbc154886eca4f98f104938b87307402
Project root: E:\VideCode\vc_trade
Source prompt: `prompt/20261007-201709-fvg-confirmation-entry-guide.md`
Report path: `report/20261007-201709-fvg-confirmation-entry-guide-report.md`
Progress path: `report/20261007-201709-fvg-confirmation-entry-guide-progress.md`

## Goal and user authorization

The user asked: "let build something to show me how it confirm to entry. i need full, tell claude to do that", then chose "Inside the existing dashboard". Build a complete, understandable visual FVG Guide inside VC Signal. This instruction explicitly authorizes sending this task to Claude; no further send-it request is needed. Codex plans/reviews; Claude implements.

Explain what has happened, the exact next requirement, and how confirmation leads to pending limit orders and eventual fills. A price return alone is only a retest. The confirmation candle is separate. After confirmation, the three limit orders wait for a subsequent return into the zone; confirmation does not imply immediate entry or a fill. Keep the existing terminal design, navigation, charts, strategy and live controls working.

## Context and actual motivating case

Read the recent accepted repair report and Codex review: `report/20261007-192600-fvg-post-account-clock-report.md` and `report/20261007-192600-fvg-post-account-clock-codex-review.md`.

The running app is MetaQuotes-Demo DEMO/XAUUSD, FVG RR2, automatic execution ON, 10 USD total planned risk, Telegram ON. The repair passed 314 backend tests. Preserve these settings and all uncommitted work. At 13:16Z there were zero baskets and one historical SELL setup, now expired for `no_confirmation_after_retest`:

- M15 zone 4089.01–4119.18, available from C's close 12:45Z / 19:45 Bangkok.
- First later touching M5 candle closed 13:00Z / 20:00 Bangkok, high 4089.09, low 4079.74, close 4087.36. Its low froze the SELL confirmation level 4079.74.
- Later M5 closes 13:05Z and 13:10Z were 4089.47 and 4088.58: neither strictly below 4079.74. The final permitted candle closed 13:15Z without confirmation, so the setup expired then despite its outer two-hour lifetime ending 14:45Z.
- Snapshot before expiry: `.tmp/fvg-post-account-codex-review/no-signal-runtime.json`. Read fresh runtime for current state; do not hard-code the historical case as the current live setup.

## Scope and relevant files

Frontend: `frontend/src/index.template.html`, `frontend/src/input.css`, `app/static/app.js`, `app/static/nav.js`, `app/static/timefmt.js`, `app/static/fvg-display.js`, `app/static/market-chart.js`, frontend tests, generated assets using the existing build. Prefer a dedicated small guide module over making app.js unwieldy.

Backend read-only presentation support is allowed in `app/web.py` and a focused new module if needed, with API tests. Extend existing serialization additively, or introduce a narrowly scoped GET endpoint for guide data. Existing `/api/fvg` and `/api/market/bars` already provide records/candles. Expose existing stored fields such as a_open, next_open, bars_after_retest, retest/confirmation closes, reason and matching basket evidence when needed. Derive geometry using existing pure functions; do not duplicate financial rounding in a second independent implementation. No new live broker calls for tutorial/preview sizing. Never create or modify setups/baskets when reading guide data.

Rule sources to read completely: `app/fvg.py`, `app/fvg_live.py`, `app/fvg_orders.py`, and the relevant eligibility/execution paths in `app/fvg_execution.py`/`app/scanner.py`. These execution/strategy files are READ-ONLY for this task. No strategy, broker, risk, persistence, consent, default, Telegram or freshness changes. Historical version mismatches or unavailable candle data must be labelled honestly.

## Required experience

1. Add a discoverable **FVG Guide** dashboard view, linked in the sidebar and from the FVG strategy summary/selected setup. Integrate hash routing, saved selection, Back/Forward, initial view hiding and mobile navigation. Existing sections continue working. Use the existing theme and local libraries; no CDN/global installation or new framework.

2. Provide **Live / recorded setup** and clearly separate **Learning examples** modes. Live mode selects the newest active qualified setup by default, or the latest historical record if none is active, with an obvious historical/status label. Allow selecting other records, retain selection during polling, and show the exact status, last update and plain-English reason. If data is missing/stale/disconnected or FVG inactive, say so without pretending a signal exists. Show the motivating expired record if it remains available.

3. Show a visual progress path: **M15 FVG detected → qualified → M5 retest → M5 confirmation → eligibility → three pending limits → fills/outcome**. Each step says completed, waiting, failed/expired, or unavailable based on actual evidence. Keep setup qualification, signal eligibility, execution arming, broker acceptance and fills distinct. Missing future data is waiting, not passed. Display the precise next requirement prominently (e.g. "A later closed M5 candle must close below 4079.74; 1 of 3 opportunities remains"). Outer setup lifetime, confirmation-window deadline and pending-order lifetime must have distinct labels.

4. Include an annotated candle diagram/chart with A/B/C formation on M15, the zone boundaries, the first M5 retest, the frozen high/low threshold, each permitted confirmation candle and its closing-price comparison, and the confirming candle if present. Show timeframe/timezone and distinguish forming candles from closed candles. A wick crossing the level is insufficient. The retest cannot confirm itself. The strategy's M15 zone is distinct from the chart's optional visual FVG zones on arbitrary timeframes. Use a legend, readable price labels and hover/click details; never rely on color alone. Use bounded existing data reads and handle insufficient history gracefully.

5. After confirmation illustrate placing **three pending limit entries**, then a subsequent pullback that can fill one, some or all legs. Show entry depth 1%/50%/80%, exact tick-rounded entry prices, the common SL two ticks beyond the far zone edge, each leg's own RR 1:2 TP, and direction-correct geometry. Before a real confirmed basket exists, call these **preview levels**, not orders. Live lots/risk/filled states come only from the actual journal/basket; show "not sized / not submitted" when absent. Explain 10 USD total planned SL risk, equal nominal thirds before lot flooring, wider stop distance yielding fewer lots, and USD/USC conversion through the existing display helper. Actual lot-rounded losses may be lower; fees/gaps/slippage can exceed planned risk. No fabricated live volume or fill.

6. Include a concise full rule reference driven by active config/source: adjacent closed M15 A/B/C gap; trend EMA20/EMA50 with 50-bar contiguous warm-up; minimum gap/displacement against ATR14; first later closed M5 intersection; BUY later close strictly above retest high / SELL strictly below retest low within the next 3 contiguous candles; invalidation precedence and missing-bar failure; 2-hour setup lifetime. Explain signal blockers (session watermark, confirmation age <=30 seconds, setup deadline, capacity, cooldown, daily cap, spread/placement), and separate execution checks/opt-in, original-account binding, risk sizing, preflight and unknown/partial outcomes. Use plain language and expand technical detail on demand. Eligibility that has not yet run is not an already-passed live checklist.

7. Learning mode has deterministic **BUY success**, **SELL success**, and **retest without confirmation / expiry** examples, plus a failure/invalidation example. Provide Previous / Next / Reset and a candle-step scrubber; optional Play is fine but reduced motion and keyboard use must work. Advancing reveals evidence chronologically without future candles or premature entries. Invalidation wins over a same-bar confirmation; equality does not confirm; the third later candle may still confirm, otherwise it expires. Include a subsequent-return fill illustration after confirmation, explicitly fictional. All lesson controls remain local/read-only: no arming, broker preflight/send/remove, signal injection, persistence changes or Telegram messages. Do not reuse the existing replay POST as a learning control.

## Acceptance and validation

- The user can explain why the actual SELL retest was not a signal by inspecting the frozen threshold, three later closes and expiry reason. Also demonstrate a successful BUY and SELL all the way to pending orders and a later fictional fill.
- Guide state and rounding agree with existing Python rule functions. Use meaningful focused tests for strict equality, separate retest/confirm, third-candle boundary, invalidation precedence, historical/expired records, no-future reveal, direction-correct preview levels, and actual-vs-preview execution states. Read-only GETs must not mutate stores or invoke submission/removal. Do not add redundant snapshot/source-text tests as a substitute for behavior.
- Run `npm.cmd test` and `npm.cmd run build` from frontend; syntax-check added/changed JS. Run focused backend API/presentation tests and the full backend suite if backend code changes, with a fresh in-project pytest basetemp. Keep all verification fixtures isolated and deterministic.
- Visually inspect actual rendered desktop and ~390px mobile, light/dark, navigation/deep-link/Back, empty/inactive/disconnected states, historical expiry, BUY/SELL lessons and the pending-vs-filled distinction. Use a separate synthetic read-only mock app for lesson/error scenarios; never inject fixture signals into the live store. Save useful sanitized screenshots inside `.tmp/` and report what was actually viewed, including unavailable UI tools.
- No artificial live broker action, test Telegram message, MT5 login/initialize/account switch, commits/pushes, helper-tool edits or global changes. Preserve the live ON state, risk and Telegram preferences; do not disarm/re-arm or alter override files. A normal launcher restart is authorized only if required to load additive backend presentation changes, preserving preferences/journals and normal reconciliation. No restart is needed solely for static assets. Read-only runtime verification afterwards must report account context, strategy, freshness/scanner, auto state, risk, Telegram, and any naturally arising baskets/setups/exposure. Do not assume they stay at zero during implementation.

## Reply and stopping condition

Acknowledge at the exact progress path. Implement the guide, complete checks, publish the complete matching report atomically from an in-project temporary file, and stop. Include changed files, where the user opens it, walkthrough features, actual test/build results, visual evidence, runtime preservation, limitations and blockers. No self-dispatched follow-up. Codex will independently review the feature. Ask only for material requirements that cannot be resolved from this task.
