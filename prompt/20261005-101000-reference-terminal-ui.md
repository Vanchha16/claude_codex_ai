# Restyle VC Signal to match the reference trading terminal

Task ID: 20261005-101000-reference-terminal-ui
Delivery status: APPROVED FOR EXECUTION
User authorization: On 2026-10-05, after reviewing the updated full redesign draft covering the side-by-side left sidebar and every dashboard section, the user explicitly said "send it". This approves this task only.
Project root: E:\VideCode\vc_trade
Source prompt: `prompt/20261005-101000-reference-terminal-ui.md`
Report path: `report/20261005-101000-reference-terminal-ui-report.md`

## Goal and context

User reference: https://vcanalyzetrading.site/ai-analysis
User requirement: "let check this website i want the UI look like this website".
Latest scope emphasis: "Build the leftsidebar build it side by side and design every make it look clean like website i send to you."
Interpretation: a persistent left navigation beside the main workspace on desktop, with a complete clean redesign of every existing section. The user subsequently authorized execution by saying "send it" for this updated design brief.

Codex inspected the real AI Analysis list page and a saved analysis detail page in the browser on October 5, after the site's session became available. No credentials were read or submitted, and no Generate Analysis action was used. Match the visual shell, palette, typography, component density and chart/detail hierarchy while keeping VC Signal's actual CRT-SMC functionality and branding.

Reference screenshots, saved locally and inspected:
- .tmp/screenshots/reference-ai-analysis-loaded-desktop.png: analysis list, grouped sidebar, header, controls and compact history rows.
- .tmp/screenshots/reference-ai-analysis-detail-desktop.png: Summary, chart, pill overlays, tabbed narrative, Evidence panel.
- .tmp/screenshots/reference-ai-analysis-detail-mobile.png: 390 px layout with compact header, stacked cards, wrapped chart controls and horizontally contained tabs.
- .tmp/screenshots/vc-signal-before-ui-redesign.png: current VC Signal baseline.

The earlier requirements-pending inspection notes in prompt/drafts/20261005-100556-reference-ai-analysis-ui.md are superseded by this concrete brief. They describe the initial login redirect, not the later accessible analysis UI.

## Observed reference design

- Charcoal/near-black page, slightly lighter sidebar and controls, white primary text, muted gray-blue secondary text.
- A subtle blue glow across the top workspace; restrained blue primary/active accents, small purple-blue branding accent, thin low-contrast borders and little shadow.
- Desktop sidebar measured 248 px; header about 56 px. Sidebar uses small uppercase group labels, slim outline icons, compact 36 px rows and an active row with a tinted background/blue marker.
- Main padding measured 24 px vertically / 32 px horizontally on desktop, 16 px horizontally at mobile width.
- Font is Inter Tight with a system sans-serif fallback; page title 26 px/600, card titles around 14 px, controls and secondary labels around 12-14 px. Numbers remain readable, with restrained bold weights.
- Cards have 16 px corner radii, 1 px borders (white at about 9% opacity), dark surface/gradient and compact 16 px inner spacing. Inputs/buttons are around 36-40 px tall with 10-12 px radii.
- List screen: heading/subtitle, compact workflow/selector area, full-width history rows with symbol/timeframe/status on the left and relative time on the right.
- Detail screen: title, wide Summary card, large dark candlestick chart card, small pill controls, tabbed description card and Evidence panel. The reference displays confidence percentages and AI narration; these are reference features, not existing VC Signal capabilities.

Measured CSS palette:
- Page: oklch(0.16 0.012 265)
- Sidebar: oklch(0.178 0.012 265)
- Header surface: oklab(0.196 -0.00113302 -0.0129505 / 0.65)
- Controls: oklch(0.215 0.014 265)
- Tabs rail: oklch(0.25 0.015 265)
- Primary text: oklch(0.97 0.004 260)
- Muted text: oklch(0.68 0.017 262)
- Primary action: oklch(0.64 0.19 267)
- Border: oklch(0.99 0 0 / 0.09)

## Scope and relevant files

- frontend/src/index.template.html: source layout, sidebar, header, cards/forms/table presentation.
- frontend/src/input.css: app-specific palette, typography, responsive surfaces, focus states and chart tokens. Prefer a coherent local theme over scattered overrides.
- frontend/package.json / package-lock.json and frontend/copy-assets.mjs only if needed for a project-local, pinned, properly licensed font asset. Do not introduce external font/CDN requests at runtime.
- app/static/app.js: restyle dynamically generated elements and, where useful, render existing selected setup/signal details in the reference-inspired detail panel.
- app/static/market-chart.js: chart font/theme integration only as needed; preserve chart behavior and market data semantics.
- app/static/nav.js: preserve recent refresh/section restoration. Change only if DOM/navigation adaptation requires it.
- Regenerate app/static/index.html and app/static/dist assets through the normal frontend build.
- Relevant documentation/notices for any added licensed font asset.

This is an existing local web project, not a Sites deployment. No backend/strategy/provider/history/Telegram configuration changes. Do not add cloud authentication, subscriptions, fabricated confidence scores, new AI services, dummy search controls, or reference-only features such as news/order blocks that our API does not provide.

## Implementation plan

1. Read handoff instructions, inspect all reference screenshots and existing UI source/bindings. Confirm the approved task and write a progress receipt before implementation.
2. Apply a reference-matching dark terminal theme. Use Inter Tight served locally if feasible, with a system fallback. Keep an accessible light-theme option and honor existing explicit saved theme choices; use dark for new visitors with no saved preference. Align chart fonts and theme tokens.
3. Build the shell as a coherent side-by-side desktop layout: approximately 248 px persistent left sidebar, the main workspace filling the remaining width, and a compact 56-64 px header over the workspace. Sidebar and workspace must scroll without overlap; give the main column min-width: 0 so charts and tables cannot push it behind the sidebar. Use reference-style VC Signal branding, uppercase navigation groups, slim icons, compact aligned labels, consistent row heights, a restrained blue active marker and clear hover/focus states. Keep the sidebar visible at ordinary laptop/desktop widths and use an off-canvas drawer at mobile widths. Preserve the existing desktop collapse affordance if present and make its collapsed presentation coherent and accessible. Keep real Pause/Resume, mode and theme controls accessible; do not copy account/admin navigation or create nonfunctional controls.
4. Preserve the current six anchor sections and their URLs/IDs. Group navigation logically (Workspace: Overview/Chart; Signals: Signals/Setups; Research: Replay; System: System and existing task panel link). Keep refresh persistence, active styling/aria-current and mobile drawer behavior.
5. Rework Overview into a compact strategy/market summary following the reference card hierarchy: actual setup state as the main message, clear symbol/Bid/Ask/freshness, small scanner/Telegram status chips, and quieter connection details. Use qualitative actual states, not invented percentages or recommendations.
6. Make Chart the large dark chart workspace with compact pill/segmented controls. Preserve all existing timeframes, Reset/Live/Expand, EMA20/EMA50/tick-volume toggles, OHLC readout, forming-candle labels, setup/signal overlays, TradingView attribution and history loading. If adding a detail card under the chart, use only existing selected record/state fields; suitable tabs are Summary, Setup, Signal details. Present rejection/cancellation/data-check reasons as factual evidence, without a fake AI label or unsupported confidence meter.
7. Design every existing section, including dynamic content: Overview summary and market status; Chart and selected-record detail; Signals filters/history; Setups lifecycle/history; Replay controls/results; System setup, Telegram and event panels. Use the reference's compact history/table language, keeping filters, meaningful columns, empty/loading/error states and row-to-chart behavior. Carry one consistent spacing/type/surface/button/badge system through all six sections. Use balanced side-by-side card grids where desktop space permits and stack them cleanly on mobile; keep the candlestick chart wide and readable. Finish table headings, form labels, secondary descriptions, disabled states and dense event/history content, not only the first screen.
8. Keep mobile at approximately 390 px fully usable: stacked cards, 16 px gutters, a compact header/drawer, wrapped chart controls, contained tab/table scrolling and no whole-page horizontal overflow.
9. Build with existing frontend scripts; use project-local pinned dependencies/cache if a font package is needed. Serve updated static assets without restarting the active backend unless genuinely required. Do not toggle the scanner or Telegram, change mode/symbol, or send messages/test messages during validation.

## Acceptance criteria

- Desktop and mobile screenshots show a close visual relationship to the reference: charcoal palette, narrow grouped sidebar, compact header, Inter Tight-like typography, subtle borders/blue accents and summary/chart/detail hierarchy.
- Desktop shows the left sidebar and main content side by side without covering each other, at common laptop and desktop widths. Mobile uses a functional drawer. All six sections, including their lower panels and dynamically rendered content, have a finished consistent design.
- VC Signal identity and actual local MT5/CRT-SMC-v1 data remain truthful. No artificial confidence percentages, AI output or financial recommendations appear.
- All six existing sections and their functional controls still work. Refresh remains on the selected section; direct anchors, manual scrolling and sidebar selection remain aligned.
- Chart interaction, selected-record overlays, filters, replay display, setup form, feed/quote status, theme switching, error/empty/disconnected/demo states and screen-reader labels remain intact.
- No new runtime CDN/external UI dependencies. If a local font is added, pin it and retain its license/notice.
- Live MT5/XAUUSDc connection, resumed scanner, enabled Telegram opt-in and existing data are unchanged by this task. No validation-triggered external messages.

## Validation

Run npm build and existing frontend tests from frontend, plus JavaScript syntax checks. Run relevant API/UI regressions if markup bindings change; do not introduce tests that merely duplicate CSS. Record actual tests separately from unavailable checks.

Use the browser to inspect 1536 px desktop and 390 px mobile layouts, all six sections, dark/light themes, chart controls, row selection/details, periodic updates, empty/error states where safely available, and a real reload of a non-Overview section. Check no application console errors; current baseline has a favicon.ico 404 only, which may be fixed with a small local VC Signal favicon if convenient.

Save local before/after screenshots in .tmp/screenshots and compare against the reference images. Keep caches, downloads and work inside this root. Do not read global credentials, automate login or install global tools. Verify targets before recursive file operations.

## Reply and stopping condition

Progress receipt: report/20261005-101000-reference-terminal-ui-progress.md.
Claude implements; Codex plans and reviews. Write any material questions/blockers to the final report path and stop dependent work.

Final report must match the Task ID and Source prompt and include outcome, changed files, screenshot paths, actual build/test/browser results, runtime-state verification and remaining issues. Publish the complete report atomically through a project-local temporary file. Stop after reporting and await another separately approved task.


