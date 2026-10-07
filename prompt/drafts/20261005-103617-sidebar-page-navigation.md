# Switch sidebar items between separate dashboard views

Task ID: 20261005-103617-sidebar-page-navigation
Delivery status: DRAFT — DO NOT EXECUTE
User authorization: pending
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261005-103617-sidebar-page-navigation.md`
Report path: `report/20261005-103617-sidebar-page-navigation-report.md`

## Goal and context

The visual redesign task 20261005-101000-reference-terminal-ui is completed and reported. Keep its new charcoal theme, local Inter Tight, grouped 248 px sidebar, 56 px header, 72 px collapsed icon rail, mobile drawer and restyled six sections.

The user clarified the intended navigation: "I don't want main content it scroll down to view leftside. i want it use left sidebar." Codex has stated the interpretation: every sidebar item opens its own main view, with only that section visible, instead of scrolling through one long page containing all sections.

This changes the previous brief's instruction to preserve the scrolling six-section page; it needs separately approved execution. The design and live signal functionality remain as already implemented.

Current implementation: app/static/nav.js uses section anchors, scrollIntoView(), startup scroll restoration and a scroll-spy. All six sections remain rendered in a long scrolling main page. app/static/app.js also scrolls to the chart after selecting a setup/signal. Replace that navigation behavior with mutually exclusive views while preserving DOM IDs and functional bindings.

## Scope and relevant files

- frontend/src/index.template.html: main view visibility, sidebar/internal navigation bindings, initial paint and responsive layout.
- app/static/nav.js: centralized view selection, persistence and URL/back-forward integration; remove scroll-driven selection.
- app/static/app.js: startup integration, chart entry/showSelected and any view-dependent rendering/resizing.
- app/static/market-chart.js only if needed for correct dimensions when revealing Chart.
- frontend/src/input.css for view spacing/visibility if needed.
- Regenerate app/static/index.html and dist CSS through normal build.
- Focused navigation tests if needed for routing behavior; existing frontend tests and meaningful UI checks.

Do not modify backend, strategy, MT5 settings, database/history, Telegram opt-in, or the task panel. Preserve the completed reference-inspired visual styling; do not redo that task.

## Implementation plan

1. Read the completed redesign report, current navigation code and template. Write a progress receipt after checking approval.
2. Make Overview, Chart, Signals, Setups, Replay and System mutually exclusive main views. Exactly one is visible/accessible at a time. Keep inactive view DOM mounted or otherwise maintain all existing bindings safely; do not leave hidden-panel content in keyboard/screen-reader navigation. Avoid a flash of every section on initial load.
3. Keep the desktop sidebar fixed beside the workspace and header. Clicking a sidebar item changes the active view and active/aria-current state, with the new view starting at its own top. Scrolling within a long selected view must never select or reveal another view. Mobile drawer closes after choosing a view; desktop collapse/expand remains functional.
4. Preserve recognized existing URLs (#overview, #chart-section, #signals-section, #setups-section, #replay-section, #system-section) as view identifiers. Use one navigation state source and explicit transitions. Fresh/default and invalid-value handling remain safe; recognized URL hash wins over stored vcSection. Refresh stays on the selected view. Make normal browser Back/Forward work through actual view changes; remove scroll-spy and obsolete repeated scroll restoration.
5. Route internal links through the same view switch: logo opens Overview, Open market chart opens Chart, and selecting a signal/setup row switches to Chart before showing its correct overlays and detail tab. Avoid scrolling to hidden elements.
6. Handle chart initialization/resizing correctly when Chart starts hidden or is revealed again. Keep candles, indicators, selected setup overlays, history loading, live polling, timeframe switches, Reset/Live and fullscreen/fallback expansion intact. Expand and return must keep Chart as the selected view.
7. Keep all existing polling and selectors safe for inactive views; active quote/table/detail content still updates without scrolling or changing view. Preserve in-progress System edits (setupDirty) across ordinary view switches.
8. Remove spacing intended to separate sections in a long document. Each selected view should have a coherent title and aligned content beginning directly below the header, with no blank space for hidden sections. Short views fit naturally; longer views may scroll within the main workspace. Tables/tabs retain their own overflow handling.
9. Build and validate desktop/laptop/mobile. Static assets should update without a backend restart. Do not toggle scanner/Telegram, submit setup, change mode/symbol, run a replay or send messages during checks.

## Acceptance criteria

- Only the selected one of the six main views is displayed, tabbable and presented as active content. No vertical scrolling is required to get from Overview to Chart, Signals, Setups, Replay or System.
- Clicking each sidebar item changes visible content immediately, with matching active styling and aria-current. Sidebar remains available beside desktop content; mobile uses its drawer.
- Scrolling within System/Replay never switches to another view or highlights another sidebar item.
- A direct #chart-section link opens Chart alone. Refresh and Back/Forward preserve/restore the appropriate selected view. Invalid hash/storage and blocked storage do not crash the UI.
- First-load hidden Chart becomes a correctly sized candlestick chart after selection, and remains correct after returning from another view or resizing/collapsing the sidebar.
- Signals/Setups row selection opens Chart with the correct overlays/details. Logo and Open market chart use the same navigation state.
- Fullscreen/fallback Expand and return preserve the selected Chart view.
- All six existing view controls, filters, records, readonly diagnostics and responsive styling remain functional. No full-page horizontal overflow at desktop, laptop and 390 px mobile widths.
- Live MT5/XAUUSDc, active scanner, enabled persisted Telegram opt-in and existing history remain unchanged; no validation-triggered external messages.

## Validation

Run frontend build, existing frontend tests, JavaScript syntax checks and focused routing tests justified by the changed behavior. Inspect actual browser view transitions for all six sections, direct links, refresh, Back/Forward, periodic polling, hidden-chart initialization, row-to-chart navigation, fullscreen exit, desktop collapse and mobile drawer. Check that exactly one main view has nonzero visible layout at a time and inactive controls cannot be tabbed to. Check no application console errors.

Use exact CSS viewport widths around 1536, 1024 and 390 where possible; if using same-origin frames because browser zoom/window control prevents this, disclose the setup and preserve the browser's pre-test storage/navigation choices. Keep reference styles intact and save after screenshots locally in .tmp/screenshots. Do not automate authentication or access global credentials. Keep all work/caches/downloads/temp files inside this root; verify paths before recursive operations.

## Reply and stopping condition

Progress receipt: report/20261005-103617-sidebar-page-navigation-progress.md.
Claude implements; Codex plans and reviews. Write material questions/blockers to the exact final report path and stop dependent work.

Final report must include task ID, source prompt, outcome, changed files, actual tests/browser checks, screenshots, runtime-state verification and remaining issues. Publish the complete report atomically using a project-local temporary file. Stop after reporting and await another separately approved task.
