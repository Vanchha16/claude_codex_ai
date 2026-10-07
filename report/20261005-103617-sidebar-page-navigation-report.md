# Claude report: switch sidebar items between separate dashboard views

Task ID: 20261005-103617-sidebar-page-navigation
Source prompt: `prompt/20261005-103617-sidebar-page-navigation.md`
Status: completed
Reported at: 2026-10-05, about 03:50 UTC

## Outcome

The dashboard no longer scrolls through one long page. Each sidebar item opens its own main view: Overview, Chart, Signals, Setups, Replay or System. Exactly one view is displayed at a time. Inactive views are kept in the DOM, so every ID, binding and polling target keeps working, but they carry `hidden`. That takes them out of layout, tab order and the accessibility tree.

The completed reference styling is kept unchanged: theme, Inter Tight, the 248 px sidebar, the 72 px rail, the 56 px header and the mobile drawer.

**Single navigation state**

`app/static/nav.js` is now a small view router and the only source of navigation state. It drives:
- the visible view (`html[data-view]` plus `hidden` on the inactive sections);
- the Alpine `selected` value, which controls sidebar active styling and `aria-current`;
- the URL hash;
- the remembered `vcSection`;
- real history entries.

The sidebar, the logo and "Open market chart" use `@click.prevent` and set `selected`. An Alpine `$watch` routes that through `VCNav.go()`.

The scroll-spy, the user-input gating and the repeated startup scroll restoration are all removed. Scrolling never changes the view.

**URLs, storage and history**

- The existing anchors are the view identifiers: `#overview`, `#chart-section`, `#signals-section`, `#setups-section`, `#replay-section`, `#system-section`.
- Load priority: a recognised hash, then a valid stored `vcSection`, then Overview. Invalid hashes or stored values, malformed percent-encoding and blocked storage all fall back safely.
- The initial URL is normalised with `replaceState`. Each user navigation adds a `pushState` entry. `popstate` and `hashchange` restore the view without adding new entries, so browser Back/Forward move between views.
- Each view switch resets `#content` to the top.

**No flash on load**

An inline head script, beside the theme script, sets `html[data-view]` before first paint, using the same hash > storage > Overview logic. CSS shows only the matching `.vc-view`, so no other section paints. If no `data-view` is set, Overview is shown.

**Row selection**

Selecting a signal or setup row now calls `VCNav.go("chart")` first. It then draws the record's overlays and fills the detail card (Setup or Signal tab). The old `scrollIntoView` to the chart is gone.

**Layout per view**

- A shared context line ("XAUUSDc · H1 / M5 · CRT-SMC-v1 · Live MT5 data (read-only)") and the warning banner sit above the views.
- Each view starts with its own title and description:
  - Overview
  - Chart
  - Signals
  - Setups & lifecycle
  - Replay
  - System
- Inside the cards:
  - The card headings that duplicated the view titles became card titles: "Signal records", "Evaluated ranges" and "Replay run".
  - "Price Chart" is now an `h3` under the Chart view `h2`.
  - The section heading IDs (`overview-title`, `signals-title`, …) are kept and referenced by each section's `aria-labelledby`.
- The long-document spacing (`mt-8`, `scroll-mt-20`) is removed.

**Chart**

- **Sizing:** Lightweight Charts `autoSize` (ResizeObserver) re-sizes the chart when it is revealed. It worked in the browser when the page loaded on a different view and when switching back and forth. It also re-sized on sidebar collapse and when the frame width changed.
- **Expand:** Expand and its return keep the Chart view and hash.
- **No chart code change:** `market-chart.js` was not changed in this task.
- **System edits:** in-progress System edits (`setupDirty`) survive ordinary view switches.

## Files changed

- **`app/static/nav.js`:** rewritten as the view router: `go`, `onChange`, hash/storage/history handling, popstate/hashchange. It no longer has a scroll-spy or scroll restoration. `remember` and `setSelected` remain as compatibility aliases of `go`.
- **`frontend/src/index.template.html`:**
  - the head script sets the initial `data-view`;
  - `x-init` now uses `VCNav.go`;
  - the eight navigation links use `@click.prevent` (logo, six sidebar items, "Open market chart");
  - sections are `.vc-view`;
  - per-view headers and the shared context line were added;
  - long-page spacing was removed.
- **`frontend/src/input.css`:** `.vc-view` visibility rules keyed on `html[data-view]`.
- **`app/static/app.js`:** `showSelected(open)` switches to Chart before drawing; the `VCNav.restore/done` calls are removed from startup. Polling, actions and the API layer are unchanged.
- **`frontend/tests/nav.test.mjs` (new):** 7 focused routing tests that load the real `nav.js` in a `vm` sandbox with a fake window, document, storage and history. They cover:
  - a fresh visit;
  - hash beating storage;
  - invalid and malformed values;
  - blocked storage;
  - one visible view with scroll reset and history push;
  - no duplicate history entries;
  - Back/Forward;
  - change listeners.
- **`frontend/package.json`:** the `test` script also runs `tests/nav.test.mjs`.
- **Regenerated by the build:** `app/static/index.html` and `app/static/dist/app.css`.
- **Not modified:** the backend, strategy and config, MT5 settings, the database and history, Telegram state, `market-chart.js`, and `tools/` (task panel).

## Validation performed

Automated:

- **`npm run build`** (frontend): succeeded.
- **`npm test`:** **11 passed, 0 failed** (4 timefmt + 7 new nav routing tests).
- **`node --check`** on `app.js`, `nav.js`, `market-chart.js` and `timefmt.js`: all OK.
- **`pytest`:** **112 passed** (1 deprecation warning that was already there).

Browser (Chrome, live server, no backend restart):

- **Setup:** the Chrome window is maximised at about 64% zoom (CSS viewport 2400 px) and could not be resized. I therefore used same-origin iframes at exact CSS widths: **1536**, **390**, **1023/1026** (straddling the 1024 `lg` breakpoint), plus the top-level tab for the Expand test.
- **Storage:** I recorded the browser's pre-test values (`vcSection=signals`, `darkMode=true`) and restored them at the end.
- **Background tab:** the window reports `visibilityState=hidden`, so it only paints when screenshotted. Chart sizes were therefore measured after a forced paint.
- **Sidebar clicks (1536):** all six sidebar items each showed exactly one view with nonzero layout. `aria-current` and `.vc-nav-active` were on the matching item, the hash matched, and `#content.scrollTop` was 0. No focusable controls inside hidden views were rendered or tabbable (count 0 for every view).
- **Scrolling in System:** scrolling to the bottom with a real wheel event kept System and its hash (scrollTop stayed about 199).
- **Back/Forward:** Back went Replay, then Setups; Forward went to Replay. Each restored the correct single view.
- **Logo and Open market chart:** the logo opened Overview and "Open market chart" opened Chart, both through the same state.
- **Polling:** waited 6.5 s on Chart; it stayed on Chart and the hash didn't change.
- **Row selection:** clicking the SELL setup in Setups switched to Chart with the hash and `aria-current` on Chart. It showed status "SELL setup · A 2026-10-02 07:00 UTC · expired…", the detail scope "Setup #1" and the Setup tab, with scrollTop 0. The screenshot shows the sweep, A high/low, level, B and B-close overlays.
- **Expand fallback:** in the iframe (fullscreen not allowed) the in-page expanded panel opened. The button closed it, Esc closed it, and Chart stayed selected each time.
- **Expand in the top-level tab:** a real mouse click on Expand was refused real fullscreen because the window is in the background, so the code fell back to the in-page expanded panel. A real click on "Close expanded chart" returned to the Chart view and the chart re-measured to 1499 px wide.
- **Hidden-chart start (390):** the frame loaded on Overview, where the chart width was 0. I opened the drawer and chose Chart: the drawer closed (x=-248), the view became Chart with scrollTop 0, and after painting the chart canvases were 242+70 px wide, filling the 314 px chart width.
- **Re-reveal (1536):** Chart → Overview → Chart restored the same canvas sizes (1180×452).
- **Sidebar collapse (1026 px):** the sidebar went to 72 px, and the chart width followed: 670 → 846 px. The 1180 px figure I first measured at 1536 was taken before any paint, so it doesn't count; the collapse was confirmed after painting.
- **1023 vs 1026 px:** at 1023 the sidebar is an off-canvas drawer (below `lg`); at 1026 it is static at x=0 with content starting at 248 px.
- **No horizontal overflow** at 1536, 1023, 1026 or 390 px.
- **System edits:** an edited (unsaved) System field survived Chart → System after a 3.5 s poll. A real reload on `#system-section` reopened System alone and, as expected, discarded the unsaved edit.
- **Reload on a non-Overview view:** `#chart-section` and `#system-section` both reloaded into their own view only.
- **Console:** no application console errors after a fresh load with tracking attached, nor during the Expand tests.

Screenshots in `.tmp/screenshots/`:

- `vc-views-1536-390-overview.jpg`
- `vc-views-1536-chart-selected-setup-390-chart.jpg`
- `vc-views-1536-signals-390-setups.jpg`
- `vc-views-1536-setups-390-signals.jpg`
- `vc-views-1536-replay-390-system.jpg`
- `vc-views-1536-system-390-replay.jpg`
- `vc-views-1023-chart-drawer-layout.jpg`
- `vc-views-1026-chart-sidebar.jpg`
- `vc-views-chart-expanded-fallback.jpg`

Runtime state, read-only checks after testing:

- `/api/state`: mode `mt5`, symbol `XAUUSDc`, feed ok, scanner running with `paused=false` and no error, Telegram enabled with the persisted opt-in.
- `/api/outbox`: still a single, earlier `sent` row, so no messages were sent.
- Not done: no scanner or Telegram toggle, no setup submit, no mode or symbol change, no replay run.

## Checks not performed

- **Real browser fullscreen (`requestFullscreen`):** Chrome refused it because the automation window is in the background, so the in-page fallback is what I verified. Fullscreen exit uses the existing `fullscreenchange` handler, which only updates the button text. Nothing in that path calls the navigation code, so the view cannot change.
- **Exact native window widths:** not used because the maximised window can't be resized; same-origin frames were used instead (disclosed above).
- **Screen-reader software:** I didn't run an actual screen reader. Exclusion of hidden views relies on the `hidden` attribute / `display: none`, which I verified.
- **Disconnected / demo states:** not exercised live, because that would mean changing mode or disconnecting MT5.

## Questions, missing requirements, or blockers

None.

Notes:

- **Back button behaviour:** browser Back/Forward now step through visited views, because each sidebar click adds a history entry. That is what was requested, and it means Back leaves the dashboard only after stepping back through the visited views.
- **Shared context line:** the line above every view title shows the real symbol and source, so each view also gives the live context.

## Suggested next step

Ask the user to hard-refresh http://127.0.0.1:8000/ and try the sidebar to confirm the separate-view behaviour matches what they wanted.
