# Claude report: keep the current dashboard section after refresh

Task ID: 20261005-094921-preserve-dashboard-section
Source prompt: `prompt/20261005-094921-preserve-dashboard-section.md`
Status: completed
Reported at: 2026-10-05

## Outcome

A browser refresh now keeps the dashboard section you were on instead of jumping back to Overview.

**Order of precedence on load:**
1. a recognised URL anchor (`#overview`, `#chart-section`, `#signals-section`, `#setups-section`, `#replay-section`, `#system-section`);
2. the remembered section in browser localStorage (key `vcSection`, values allow-listed);
3. Overview.

**How the selection stays in sync:**
- The sidebar highlight / `aria-current`, the URL anchor and the remembered value move together.
- They update when you navigate with the sidebar, the logo, **Open market chart**, or by clicking a signal/setup row (which jumps to Chart).
- They also update when you scroll the page yourself.
- The restore runs again after the dashboard data has filled the layout. Periodic API polling never moves the page or changes the selection.

**Not changed:** live MT5 (XAUUSDc, connected), the resumed scanner, and Telegram delivery (enabled, saved opt-in). Nothing was toggled and no messages were sent. No backend restart was needed: static files are served from disk; the server PID is unchanged at 42512.

**Approval gate:** passed. The prompt is in `prompt/` with `APPROVED FOR EXECUTION`, a Task ID, Source prompt and Report path. Its `User authorization:` line records the user's explicit instruction "tell claude when refresh don't back to overwrite" for this task. Progress receipt: `report/20261005-094921-preserve-dashboard-section-progress.md`.

## Changed files

- **`app/static/nav.js` (new, about 80 lines), the section-persistence helper:**
  - Works out the initial section (anchor > storage > Overview) with allow-listed IDs.
  - All `localStorage` access is in try/catch; when storage is blocked it falls back to Overview and the URL anchor.
  - `remember()` uses `history.replaceState`, which adds no history entries.
  - `restore()` scrolls the app's scroll container (`#content`) to the section. It stops once the user has interacted.
  - A `hashchange` handler supports back/forward and deep links.
  - A scroll-spy runs **only after real user input** (wheel, touch, keys, mouse) and picks the section at the top 35% of the view. Layout shifts from polling therefore never change the selection.
- **`frontend/src/index.template.html`:**
  - Loads `/static/nav.js` (deferred, before the other scripts).
  - Alpine `selected` starts from `VCNav.initial()` instead of `'overview'`.
  - `$watch('selected', VCNav.remember)` keeps the highlight, anchor and storage aligned.
- **`app/static/index.html`:** regenerated from the template with `npm run build`.
- **`app/static/app.js`:**
  - Restores the section immediately and again once state, tables and replay have loaded (plus a final pass 800 ms later, after which the scroll-spy is enabled).
  - Clicking a signal/setup row now also marks Chart as the current section.

No backend, strategy, configuration, chart-settings or TailAdmin design changes. `frontend/copy-assets.mjs` is unchanged; `nav.js` is served directly from `app/static`.

## Validation actually performed

**Build and tests:**
- `npm run build` (Tailwind 4.3.3 + copy-assets): succeeded. `npm test`: 4 passed.
- `node --check` passed for `nav.js` and `app.js`.
- `.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .tmp/pytest/nav-<ts>`: **112 passed** (one third-party Starlette warning).

**Browser checks** (Chrome, real reloads of http://127.0.0.1:8000/ with live MT5 data):
- **Fresh state** (no anchor, no stored value): opens Overview, Overview active, scroll 0.
- **Each section, via its sidebar link, then reload:**

  | Section | Restored | Sidebar active | Section top (px from container top) |
  |---|---|---|---|
  | Signals | yes | yes | 96 |
  | Chart | yes | yes | 96 |
  | Setups | yes | yes | 96 |
  | Replay | yes | yes | 95 |
  | System | yes | yes | 126 (last section; page at bottom) |

  96 px is the `scroll-mt-24` offset below the sticky header.
- **Anchor beats a conflicting stored value:** `#replay-section` with stored `system` opened Replay.
- **Invalid values:** invalid anchor `#bogus` + invalid stored `xyz` → Overview, no errors.
- **Blocked storage:** the page loaded with `localStorage` throwing a `SecurityError` (test frame) → Overview, no errors, and sidebar navigation still worked.
- **Polling:** on System, scroll position unchanged over 10 s (2186 → 2186). On Signals, selection, anchor and scroll were unchanged over 15 s of polling.
- **Real mouse-wheel scroll** to the bottom moved the active item to System, and the reload restored System.
- **Mobile 390 px** (test frame): the drawer opened, the Replay link closed it and navigated, the reload restored Replay at the top, with no horizontal overflow.
- **Chart functions:** the live chart has 400 XAUUSDc candles; a setup-row click switched to Chart with overlays, and "Back to live" returned to the live chart. No console errors from VC Signal.
- **Runtime state after testing:** mode mt5, feed connected, scanner not paused, Telegram enabled with persisted opt-in — all unchanged.
- **Cleanup:** the test-time `vcSection` value was removed from this browser's storage, so the user's next anchor-less visit starts at Overview.

**Bug found and fixed during testing:** the first version of the scroll-spy reacted to scroll events caused by layout shifts during polling. It could switch the remembered section to Chart between a sidebar click and a refresh. The spy is now gated on real user input and uses the 35%-of-view rule. Re-tested as above.

**Test-tool notes:**
- At this Chrome profile's 80% page zoom, some automated pointer clicks missed their targets. After one real sidebar click and one real mouse-wheel scroll, the remaining section-switch checks used `element.click()` on the actual sidebar links, which runs the same anchor and Alpine handlers.
- The blocked-storage check used a same-origin `srcdoc` frame with an injected `<base>` tag. During that check the parent tab's selection changed, but a clean parent reload afterwards held Signals for 15 s. The change is attributed to the test harness.

**Not performed:**
- Physical touch devices; browsers other than Chrome.

## Remaining issues

- None for this task.
- Carried over, outside scope: XAUUSDc's 0.001 tick makes the tick-based strategy defaults (2-tick sweep / SL buffer) much tighter than intended.

## Questions, missing requirements, or blockers

None.
