# Add FVG, IFVG, Order Block and Breaker Block chart overlays

Task ID: 20261005-114227-smc-chart-overlays
Delivery status: APPROVED FOR EXECUTION
User authorization: On 2026-10-05, after choosing chart overlays only and reviewing the concrete FVG/IFVG/OB/BB draft, the user explicitly said "send it". This authorizes this chart-overlay task only; signal rules and Telegram behavior remain unchanged.
Project root: E:\VideCode\vc_trade
Source prompt: `prompt/20261005-114227-smc-chart-overlays.md`
Report path: `report/20261005-114227-smc-chart-overlays-report.md`

## Goal and agreed scope

User requested: "let add indicator FVG and IFVG and Order block and BB breacker block." The user explicitly selected "Chart overlays only (Recommended)" when asked about scope.

Add four real, independently toggleable price-zone overlays to the existing Chart view: FVG (Fair Value Gap), IFVG (Inverse Fair Value Gap), OB (Order Block), BB (Breaker Block). Keep the reference-style sidebar/view UI clean. These are visual OHLC-derived annotations on the selected chart timeframe. They do not change CRT-SMC-v1, signal confirmation, entry/TP/SL/RR, Telegram messages or trading behavior.

Use closed candles only. Current forming candles may still display, but cannot create, flip or invalidate zones. Indicator definitions vary; implement and document the explicit reproducible project conventions below rather than implying an exact copy of another vendor.

## Sources and project files

Read existing project instructions and relevant code:
- app/static/market-chart.js: Lightweight Charts 5.2.1, closed/forming candles, live polling, older history, selected setup M5 view, theme, EMA/volume and lifecycle.
- app/static/app.js: indicator checkbox wiring, status callbacks, sidebar navigation integration.
- frontend/src/index.template.html and frontend/src/input.css: pill toggles, chart controls, chart palette and responsive layout.
- frontend/copy-assets.mjs, frontend/package.json: normal build and focused Node tests.
- A new project-local pure detection module, renderer module and tests may be added where appropriate. No new dependency or global install is necessary.

Primary references consulted by Codex (for concepts/API, not code copying):
- https://docs.luxalgo.com/platform/algos/price-action-concepts/imbalances — three-candle FVG and polarity reversal for IFVG.
- https://docs.luxalgo.com/platform/algos/price-action-concepts/order-blocks — OB/BB concepts and close vs wick mitigation variations.
- https://tradingview.github.io/lightweight-charts/docs/plugins/series-primitives — supported series-attached overlays, drawing/lifecycle.
- https://tradingview.github.io/lightweight-charts/plugin-examples/ — official rectangle primitive example.

## Detection conventions

Make calculations a pure, deterministic function of ordered, unique closed OHLC bars and symbol tick size. Record origin, activation and end times separately. Require valid finite OHLC; reject/segment invalid data and gaps rather than forming patterns across missing candles. No future information may appear before it becomes available. Reloading identical history yields identical zones.

1. FVG: three consecutive closed bars (i-2, i-1, i). Bullish when low[i] > high[i-2], zone [high[i-2], low[i]]. Bearish when high[i] < low[i-2], zone [high[i], low[i-2]]. Require positive gap at least one symbol tick, with floating tolerance; equality/zero gap is not FVG. Activation is when third bar closes. Only later closed bars manage that zone.
2. IFVG: an existing bullish FVG flips bearish only on a subsequent closed candle strictly below its lower edge; bearish FVG flips bullish only on a close strictly above its upper edge. Wick touches alone do not flip it. End the original FVG at the flip, keep its bounds/provenance and activate IFVG at that flip (not retroactively at original formation). No repeated flip chains. A bearish IFVG ends when a later close strictly exceeds its upper edge; bullish IFVG ends when close strictly drops below its lower edge.
3. OB: OHLC-based structure-break convention, not proof of institutional orders. Identify confirmed pivot highs/lows with two closed bars on each side and strict comparisons; pivot becomes available only after its right-hand confirmation bars close. A bullish break is a closed candle crossing strictly above the latest eligible unconsumed pivot high; bearish mirrors below pivot low. Each pivot is consumed at most once; wick-only breaks do not qualify. The source for bullish OB is the last bearish candle before the break, searched back at most 20 bars and not before that pivot; bearish uses the last bullish candle. Skip when no opposite candle exists. Use the source candle full low/high range (doji is neither bullish nor bearish). OB activates at break confirmation, not source time. Explain this convention in help/README.
4. BB: a bullish OB broken by a later closed candle strictly below its low becomes a bearish BB; bearish OB broken strictly above its high becomes bullish BB. End the OB, activate BB at the break with original bounds/provenance. No same-bar or wick-only flip, and no repeated flip chains. Bearish BB ends on a later close strictly above its high; bullish BB ends on a close strictly below its low.

On each bar, manage already-active zones before creating new ones so a zone cannot invalidate itself on creation. For pivot or duplicate events define stable IDs from type/origin/activation/direction. Touches may be shown as retests if helpful, but do not silently erase an FVG/OB on a wick touch under this close-based convention. Normal later zone transitions are not lookahead/repainting. Loading additional older context can reveal additional origins; disclose loaded-history limits.

## Rendering and UX

- Add pills named FVG, IFVG, OB, BB, alongside existing EMA20/EMA50/volume. Retain current selections for existing indicators. New overlays default enabled on a fresh preference state so they are visible; use a versioned/allowlisted persisted indicator preference safely if adding persistence. No token/config storage changes.
- Distinguish bullish/bearish with subtle colors and explicit direction plus type labels; distinguish zone types with border style/accent as needed. Keep candles, crosshair, entry/SL/TP and strategy evidence readable in dark and light themes. No fake zones if none exist; show compact per-type counts and useful empty/no-data state.
- Use semi-transparent price/time rectangles attached to actual chart scales, preferably a Lightweight Charts series primitive. Clip to the candle pane, keep zones below candles and labels readable, and do not cover price/time axes or intercept pan/zoom/touch.
- Zone rendering starts at activation time and stops at actual end time; source candle time can be provided in info/help. Do not render IFVG/BB as if active before their flip. Bound drawing to the latest 10 relevant zones of each type (40 total) and document this display cap. Do not cap detection history in a way that lets hidden older zones incorrectly reappear or miss transitions.
- Controls and concise help must wrap cleanly on 390 px mobile and laptop widths. Explain expansions (Fair Value Gap, Inverse Fair Value Gap, Order Block, Breaker Block), chosen close-based invalidation, OB convention and current timeframe via tooltips/help. Keep technical implementation details out of ordinary user flows.
- Toggle each independently without resetting viewport, selection or existing EMA/volume state. IFVG must still calculate when FVG rendering is off, and BB when OB rendering is off.
- Recompute/update safely for initial load, live bar close, revised last closed bar, older history prepend, timeframe/symbol changes, selected setup history, Live/Reset, theme changes, hidden Chart reveal, resize/sidebar collapse and expanded chart. Drop stale asynchronous responses and clear stale zones on unavailable/error datasets. Preserve existing chart markers/price lines and sidebar selected state.
- Do not attach duplicate renderers/listeners or leak them; detach/dispose cleanly. Cache zone detection until closed data changes, not on every crosshair draw. Preserve zoom/pan and older-history positioning.

## Boundaries

No backend/strategy/config/database/history/Telegram edits, no scanner pause/resume, no mode/symbol change, no external message or replay run. No backend restart should be required for frontend-only changes. Keep all work/download/cache/temp paths inside the project; preserve unrelated user changes. Do not automate authentication or read global credentials.

## Validation and acceptance

Write meaningful detection fixtures/tests for both directions, exact boundaries and tick precision, FVG-to-IFVG and OB-to-BB transitions, expired/ended zones, confirmed-pivot availability, no opposite candle, duplicate breaks, gap handling, empty/invalid data and exclusion of forming candles. Include prefix tests proving no event activation before available closed data; historical origin may be earlier but cannot be activation. Test IFVG/BB independent toggles and merged-history identity where appropriate.

Run normal frontend build and tests, JS syntax checks, and browser checks on live dashboard with read-only backend interactions. Backend tests are not required if backend untouched. Verify toggles, zone alignment on pan/zoom/price-scale changes and older history, M5/H1 timeframe switching, setup row overlays, Live/Reset, dark/light, hidden view switching, collapse/drawer and expanded chart. Verify no full-page horizontal overflow around 1536/1024/390 CSS px and no app console errors. Disclose exact native vs iframe viewport use. If live bars do not exercise all four types, verify the detector with clearly labelled local fixtures and do not invent market annotations. Do not change live feed/scanner/Telegram state for validation. Save screenshots under .tmp/screenshots and preserve pre-test navigation/theme preferences.

## Reply and stopping condition

Claude implements; Codex plans/reviews. Write progress to report/20261005-114227-smc-chart-overlays-progress.md after approval checks. If a material requirement is missing, write questions/blockers to the exact final report and stop dependent work. Publish complete final report atomically through a project-local temporary file. Include matching task ID/source, outcome, definitions actually implemented, changed files, commands/results, browser/screenshots, sanitized runtime state and limitations. Stop after reporting and await another separately approved task.

