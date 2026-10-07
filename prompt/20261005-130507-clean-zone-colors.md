# Give chart zones distinct colors and a cleaner display

Task ID: 20261005-130507-clean-zone-colors
Delivery status: APPROVED FOR EXECUTION
User authorization: On 2026-10-05, after reviewing the distinct type colors and cleaner recent-zone display proposal, the user explicitly said "send it". This authorizes this visual refinement task only.
Project root: E:\VideCode\vc_trade
Source prompt: `prompt/20261005-130507-clean-zone-colors.md`
Report path: `report/20261005-130507-clean-zone-colors-report.md`

## Goal and context

User asks: "make it different color and easy look and clean" after the FVG/IFVG/OB/BB chart overlays were delivered. Make each zone type immediately distinguishable and reduce visible clutter. This is visual chart refinement only; preserve the agreed detection rules and all backend/strategy/signal/Telegram behavior.

Current renderer uses only direction-based green/red for all four types, a 10-per-type display cap, and faded ended zones. Dense one-tick zones can produce too many overlapping boxes and labels. Existing code and reports: app/static/market-chart.js, app/static/smc-zones.js, app/static/app.js, frontend/src/index.template.html, frontend/src/input.css, README.md; report/20261005-114227-smc-chart-overlays-report.md and -codex-review.md.

## Concrete design

Use separate colors by TYPE consistently in rectangles, label badges, toggle swatches and counts/legend:
- FVG: cyan/blue (dark #38bdf8, light #0284c7).
- IFVG: purple (dark #a78bfa, light #7c3aed).
- OB: amber (dark #fbbf24, light #b45309).
- BB: rose (dark #fb7185, light #be123c).

Keep direction explicit with ▲/▼ and Bull/Bear in tooltip/help; direction must not be lost when type determines color. Preserve the existing distinct border styles as a second cue, and keep candles in their existing green/red. Small visual adjustments to these colors are routine if needed for contrast; document actual palette.

Make fills very light, outlines calm and labels readable (compact type badge, collision avoidance). Draw behind candles, clip to the pane and keep price/time axes, crosshair and existing CRT/entry/TP/SL overlays legible. Prioritize the most recent active labels when overlap requires skipping; never move a rectangle away from its real price/time location.

To reduce clutter without changing calculation:
- Default to the latest 3 ACTIVE zones of EACH type (maximum 12 boxes), instead of 10 with ended history mixed in.
- Add a compact Recent zones choice (3 / 5 / 10 per type) and a History toggle, off by default. When History is on, use active zones first and newest ended zones to fill the selected per-type cap, not to exceed it.
- Keep full loaded-history detection, zone transitions, provenance and IDs unchanged; these controls affect rendering only. No minimum-size/ATR filter or changed FVG/OB definition.
- Clearly distinguish shown counts from detected/active counts when capped (for example FVG 3/14, with a concise tooltip). When a type is toggled off, don't imply its hidden boxes are showing. Zero data/zero active zones remain truthful.
- Match each indicator pill's swatch/accent to the on-chart color, with subtle tinted checked states. Scope CSS to zone controls so generic EMA/volume/Telegram/replay pills are not unintentionally restyled.
- Keep controls and About zones compact, wrapping cleanly on mobile; retain the fixed sidebar and separate main views.

## Implementation scope

Claude implements; Codex plans/reviews. Read existing project instructions, write progress receipt after approval checks.

- app/static/market-chart.js: type palette, label styling/order, rendering cap/history settings integration.
- app/static/smc-zones.js: display-selection helper only if needed (do NOT change detect rules); retain its existing defaults for callers unless explicitly supplying new display options.
- app/static/app.js: display preferences, controls and truthful counts. Retain the existing allowlisted indicator booleans and users' saved toggles. Add safe versioned/bounded display options without clobbering unrelated preferences; invalid/blocked storage falls back safely.
- frontend/src/index.template.html / input.css: swatches, compact controls, theme palette and help.
- README.md: visual/color legend, defaults and display limit.
- Focused frontend tests for display-selection limits/history/off states/preferences if appropriate; normal build regenerates app/static/index.html and dist CSS.

Toggling type, changing cap or history, and switching theme must preserve viewport, timeframe, selected record and detection result. Preserve polling/new closed bar updates, older history, setup overlays, Reset/Live, hidden Chart reveal, sidebar collapse/drawer and Expand. No renderer/listener duplication.

No backend edits/restart, strategy/config/database/history changes, MT5 mode/symbol change, scanner/Telegram toggle, replay run or test message. Do not expose credentials or automate login. Keep all work and temp/cache artifacts in this project.

## Acceptance and verification

- Four visibly distinct type colors, consistently matched between chart and controls in dark/light.
- Default display at most 3 active zones per enabled type; ended history hidden by default, existing detection counts unchanged on identical input.
- Users can choose 3/5/10 and show ended history without altering detector/strategy. Counts honestly describe what is displayed.
- Candles and price levels are clearer than before, labels do not overlap, and controls remain readable at 1536/1024/390 CSS widths.
- Existing 24 frontend tests stay green; run focused meaningful display-selection tests, normal build and JS syntax checks.
- Browser review: same-symbol/timeframe before/after screenshots for fair comparison; dark/light, all type toggles, cap and History behavior, zoom/pan, selection, view/resize, no page overflow/console errors. Disclose iframe viewport use and preserve pre-test storage/theme/navigation choices.
- Read-only runtime check confirms MT5 feed, scanner and Telegram state intact.

## Reply and stopping condition

Progress receipt: report/20261005-130507-clean-zone-colors-progress.md.
Final report: exact path above, matching task ID/source, outcome, actual color palette, changed files, test commands/results, browser screenshots, runtime and limitations. Publish complete report atomically via project-local temporary file. If material questions/blockers arise, report them and stop dependent work. Stop after reporting and await another separately approved task.

