# Claude report: restyle VC Signal to match the reference trading terminal

Task ID: 20261005-101000-reference-terminal-ui
Source prompt: `prompt/20261005-101000-reference-terminal-ui.md`
Status: completed
Reported at: 2026-10-05 (local), about 03:35 UTC

## Outcome

VC Signal now uses a dark charcoal terminal design modelled on the reference page:

- **Shell:** a 248 px grouped left sidebar (Workspace / Signals / Research / System) sits side by side with a `min-w-0` workspace on desktop.
  - The sidebar collapses to a 72 px icon rail and expands again.
  - Below the `lg` breakpoint (1024 px) the sidebar becomes an off-canvas drawer with an overlay. It closes on Esc, on an outside click, or when you pick a section.
- **Header:** compact, 56 px, sticky.
- **Font and theme:** Inter Tight is served locally. The blue accent palette uses oklch tokens.
- **Sections:** all six are redesigned, including the content scripts generate at runtime (chips, tables, timeframe segments, replay cards and the event log).
- **Dark by default:** new visitors (no saved `darkMode`) now get dark. An existing saved choice is honoured. The light theme is fully styled.

Section by section:

- **Overview:** a "Summary" card with the CRT-SMC-v1 strategy state as the headline message. A status chip shows Scanning · live / Paused / Feed offline / Quotes not fresh / Scanner error / Stopped, derived from real scanner, feed and quote state. Four metric cards follow: Bid/Ask, Scanner, Telegram, Data source.
- **Chart:**
  - A large dark card. The indicators are pill toggles and the timeframes a segmented control (`aria-pressed`), alongside the Reset / Live / Expand buttons.
  - Below the chart is a new **detail card** with Summary / Setup / Signal tabs and an **Evidence** timeline.
  - Both use only real record fields from `/api/state`, `/api/signals` and `/api/candidates`: ranges, sweep, level, pivot, deadline, entry/SL/TP, R:R, spread, simulated outcome, R, notes, data checks and session watermark.
  - There are no confidence scores, AI text or recommendations.
  - With no row selected, the card shows the live market state. Selecting a signal or setup row opens its record, highlights the row and charts it, as before.
- **Signals / Setups:** row-card tables with sticky headers. BUY/SELL are coloured, outcome and state appear as chips, rows are selectable, and empty or error rows are dashed. Filters are unchanged.
- **Replay:** inset Development / Held-out cards with in-sample / holdout chips, plus the limitations list.
- **System:** Setup form, Telegram card (with the delivery opt-in as a pill toggle), Strategy config list and a timestamped event log.

What is preserved:

- **IDs and bindings:**
  - Every element ID used by `app.js`, `market-chart.js` and `nav.js` is kept. I compared the old template's IDs with the IDs the scripts use: all present.
  - Also kept: the `#content` scroll container, sidebar anchors, Alpine `selected` binding, `aria-current`, the "Toggle navigation" button, the script load order and the session-token API header.
  - The startup / restore sequence and section persistence are unchanged. `nav.js` was not modified.
- **Backend and strategy:** no backend, strategy, config or server change.
- **External delivery:** nothing was sent; no Telegram, mode, symbol, scanner or test-message action was triggered.

## Files changed

- `frontend/src/input.css`
  - New VC terminal design system: light and dark tokens, chart colour tokens, the Inter Tight `@font-face`.
  - Component classes: sidebar/nav, card, button, input, pill, segmented control, tabs, chip, table, evidence and chart frame.
  - Includes a fix so BUY/SELL and muted tones inside table cells are not overridden by the base `td` colour.
- `frontend/src/index.template.html`
  - Rewritten shell and sections as described above.
  - The head script now defaults to dark only when nothing is saved.
  - Local favicon link added.
  - Footer attribution kept: TailAdmin (MIT), Inter Tight (OFL) and TradingView.
- `frontend/copy-assets.mjs`
  - Copies `inter-tight-latin-wght-normal.woff2` to `app/static/dist/fonts/`.
  - Adds an Inter Tight section (version + full OFL text) to `THIRD_PARTY_NOTICES.txt`.
  - Table headers are now plain `<th scope="col">`, styled by CSS.
- `frontend/package.json`, `frontend/package-lock.json`: `@fontsource-variable/inter-tight` pinned exactly at **5.3.0** (OFL-1.1) as a devDependency. No CDN or new runtime dependency.
- `app/static/app.js`
  - Generated DOM switched from TailAdmin classes to `vc-*` classes.
  - Added `renderDetail()` / `renderEvidence()` (real fields only), detail tab handling, and `selectedRec`, which is cleared whenever the selection is reset (Live, timeframe, demo restart, mode switch, setup save).
  - Strategy chip and page heading (symbol / source) added.
  - Unchanged: the API calls and actions themselves.
- `app/static/market-chart.js`: chart font family changed to Inter Tight. No other change.
- `app/static/favicon.svg`: new small local VC Signal favicon.
- Regenerated by the build: `app/static/index.html`, `app/static/dist/app.css`, `app/static/dist/fonts/inter-tight-latin-wght-normal.woff2`, `app/static/dist/THIRD_PARTY_NOTICES.txt`.
- Not modified: `app/static/nav.js`, the backend, and `tools/` (task panel).

## Validation performed

Build and tests:

- `npm run build` (frontend): succeeded. tailwindcss v4.3.3 ran, then copy-assets. I confirmed the key arbitrary utility classes and the `vc-*` classes are present in `app.css`, and that no `{{` placeholders remain in `index.html`.
- `npm test` (frontend): 4 passed, 0 failed.
- `node --check` on `app.js`, `market-chart.js` and `nav.js`: all OK.
- `pytest` (full suite): **112 passed**, 1 deprecation warning from Starlette/httpx that was already there.

Browser checks (Chrome, live server at 127.0.0.1:8000):

- **Test setup:** the browser window is maximised at about 64% zoom, so its CSS viewport is 2400 px. For exact widths I loaded the real page in same-origin iframes of **1536×900** and **390×844**.
- **Layout at 1536:** sidebar 248 px at x=0, side by side with the workspace. Header 56 px.
- **Layout at 390:** sidebar off-canvas at x=-248. The hamburger opens it to x=0, and choosing Signals closes it and selects Signals.
- **Overflow:** no horizontal overflow at either width (document and `#content`). The only horizontal scrolling is inside the table wrappers, which is intended.
- **Sections:** all six inspected in **dark** at both widths, and in **light** for Overview, Chart, Replay and System.
- **Inter Tight:** loaded (`document.fonts.check` returned true).
- **Live data:** quotes, scan time and quote age updated live between screenshots.
- **Row selection:** clicking the SELL setup row did the following:
  - charted it (the status reads "SELL setup · A 2026-10-02 07:00 UTC · expired · press "Live" to return");
  - highlighted the row (`vc-row-selected`);
  - set the detail card to "Setup #1", opened the Setup tab and showed the real fields, with matching Range · H1 and Structure · M5 evidence;
  - set nav to `chart` / `#chart-section`.
- **Reload persistence:** a real reload of the 1536 frame on `#chart-section` came back with Chart selected and the chart section at the top.
- **Collapse:** sidebar measured 248 → 72 → 248 px, and the expand button appears while collapsed.
- **Theme toggle:** dark → light → dark through the header button's Alpine state. The saved `darkMode` value was `true` before and was restored to `true` afterwards. The chart re-themed through `themechange`.
- **Empty state:** the Signals empty row ("No confirmed signals yet…") is styled as a dashed message row.
- **Console:** no console errors in the test tab once tracking was attached (after the first page load).

Screenshots, all in `.tmp/screenshots/`:

- Before: `vc-signal-before-ui-redesign.png`
- Reference: `reference-ai-analysis-loaded-desktop.png`, `reference-ai-analysis-detail-desktop.png`, `reference-ai-analysis-detail-mobile.png`
- After:
  - `vc-ui-after-maximized-window-dark.jpg`
  - `vc-ui-after-1536-390-overview-dark.jpg`
  - `vc-ui-after-1536-390-chart-dark.jpg`
  - `vc-ui-after-1536-390-tables-dark.jpg`
  - `vc-ui-after-1536-390-selected-setup-detail-dark.jpg`
  - `vc-ui-after-1536-390-overview-light.jpg`
  - `vc-ui-after-1536-390-replay-system-light.jpg`
  - `vc-ui-after-1536-reload-chart-390-drawer-dark.jpg`
  - `vc-ui-after-1536-collapsed-sidebar-dark.jpg`
  - `vc-ui-after-1536-390-system-replay-dark.jpg`

Runtime state, read-only checks after testing:

- `/api/state`: mode `mt5`, feed ok, scanner `paused=false`, Telegram enabled with the persisted opt-in.
- `/api/outbox`: still a single `sent` row (the earlier one), so nothing new was queued or sent.
- The server process was not restarted; `index.html` is read on each request.

## Checks not performed

- **Exact 1536 / 390 browser windows:** not used, because the window is maximised and resizing had no effect. I used fixed-size same-origin iframes instead; their CSS widths were confirmed as 1536 and 390.
- **Disconnected / feed-error / demo-mode states:** not exercised live, because that would mean disconnecting MT5 or switching mode, which the task forbids. Those paths keep the same IDs and the banner logic is unchanged.
- **Chart Expand / fullscreen:** not clicked in this pass. Its handler code is unchanged and only its CSS was restyled.
- **Telegram verify / test buttons, Pause/Resume, the mode switch, the setup form submit and Run replay:** deliberately not clicked (forbidden side effects). Their bindings are unchanged.
- **Console capture during the very first page load:** console tracking only attached after that load. I saw no errors after that point.
- **Pixel-level comparison against the reference:** not done. The comparison was visual only.

## Questions, missing requirements, or blockers

None blocking. Notes for Codex:

- **Session watermark moves on its own.** During testing the scanner's watermark advanced to 03:28:26 UTC with the event "recovered after a disconnected/stale feed". This is the server's own automatic stale-feed recovery: the same event also occurred at 03:03 and 03:07, before the UI checks. My testing did not cause it, since it only uses GET reads. Mode, scanner and Telegram state are unchanged.
- **`vcSection` was overwritten by testing.** The test iframes share this browser's `localStorage`, so the saved `vcSection` now reflects my last test navigation rather than the user's previous choice. The user's next click sets it again.
- **Known issue, still out of scope:** XAUUSDc tick size 0.001 makes the 2-tick sweep and SL buffer tiny.

## Suggested next step

Ask the user to review the new look at http://127.0.0.1:8000/ (a hard refresh may be needed) and the after screenshots, and say whether they want any spacing, colour or density tweaks.
