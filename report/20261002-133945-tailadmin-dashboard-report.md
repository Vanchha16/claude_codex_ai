# Claude report: TailAdmin admin dashboard and remaining reconnect correction

Task ID: 20261002-133945-tailadmin-dashboard
Source prompt: `prompt/20261002-133945-tailadmin-dashboard.md`
Status: completed
Reported at: 2026-10-02

## Outcome

Both parts are done.

**Approval gate:** passed. The prompt has `APPROVED FOR EXECUTION`, a Task ID, Source prompt and Report path, and a browser-button `User authorization:`. Its draft SHA-256 `7c25462d…a319` matches `prompt/drafts/20261002-133945-tailadmin-dashboard.md`.

1. **Reconnect gap (prerequisite, done first):** a reconnect that succeeds within the same scan now opens a new session watermark. A confirmation missed while disconnected is consumed without a signal, active entry, outbox job or send. A genuinely new confirmation after recovery still produces exactly one signal and one mocked alert.
2. **TailAdmin dashboard:** the official free TailAdmin HTML/Tailwind template is integrated into the existing FastAPI app and served locally at http://127.0.0.1:8000/, with no CDN and no separate dev server.
   - All existing controls, data, chart, filters, message preview, replay, config and event log work through the unchanged APIs.
   - Template sample data and metrics were not used.

## Changed files

**Reconnect fix**
- `app/scanner.py` — `_ensure_connected()` sets `_unhealthy = True` as soon as feed status is not OK, *before* calling `connect()`. The recovered scan therefore always calls `_open_session(...)`.
- `tests/test_regressions_reconnect.py` (new) — the exact Codex reproduction, plus a control test.

**Dashboard (generated / served)**
- `app/static/index.html` — regenerated from the template; the TailAdmin layout.
- `app/static/app.js` — rewritten for the new markup:
  - TailAdmin badge variants;
  - keyboard-selectable table rows;
  - loading, empty and error rows;
  - summary cards from real API data;
  - closeable message preview;
  - theme-aware chart redrawn on resize and theme change, with staggered time labels;
  - task-panel link.

  API calls, session-token header and confirmations are unchanged; obsolete bindings were removed.
- `app/static/dist/app.css`, `alpine.min.js`, `fonts/outfit-latin-wght-normal.woff2`, `THIRD_PARTY_NOTICES.txt` — built assets.
- `app/static/styles.css` — **deleted** (obsolete; nothing references it).

**Dashboard build sources**
- `frontend/package.json`, `frontend/package-lock.json` — pinned: tailwindcss 4.3.3, @tailwindcss/cli 4.3.3, @tailwindcss/forms 0.5.10, alpinejs 3.17.2, @fontsource-variable/outfit 5.2.8.
- `frontend/src/index.template.html` — page source.
- `frontend/src/input.css` — stylesheet entry: TailAdmin import, local `@font-face`, chart palette from TailAdmin tokens, visible `:focus-visible` ring, `[hidden]` rule.
- `frontend/src/tailadmin/style.css` — vendored TailAdmin `src/css/style.css`. Header added; Google Fonts import removed; `@import "tailwindcss" source(none)`. Both changes are marked `[vc_trade]`.
- `frontend/src/tailadmin/icons.json` — sidebar SVG icons extracted verbatim from TailAdmin `partials/sidebar.html`.
- `frontend/src/tailadmin/LICENSE` — TailAdmin MIT license.
- `frontend/copy-assets.mjs` — renders `index.html`, copies Alpine and the font, writes the notices.

**Backend and launcher**
- `app/web.py` — new read-only `GET /api/tools`. It returns the task-panel URL from `.tmp/task-panel/server.json`, loopback URLs only; no token is involved.
- `app/launcher.py`, `gold.cmd` — new `gold.cmd build-ui` (npm ci on first use with `.tmp/npm-cache`, then `npm run build`).

**Docs and ignores**
- `README.md` — new "Dashboard UI (TailAdmin)" section: provenance, what was adapted, license, build/run.
- `.gitignore` — adds `frontend/node_modules/` and `vendor/tailadmin-free/`.

**Not tracked** (git-ignored)
- `vendor/tailadmin-free/` — pristine upstream clone.
- `frontend/node_modules/`, `.tmp/npm-cache`, `.tmp/pytest/*`, `.tmp/screenshots/tailadmin/*`.

No changes to the task panel (`tools/`), strategy rules or defaults, API contracts, security checks, `.env`, or global configuration.

## Reconnect regression evidence

**Before the fix** (`.tmp/pytest/ta-reconnect-before.txt`): **2 failed**.
- `test_same_scan_reconnect_opens_new_watermark_and_blocks_missed_confirmation`: the watermark stayed `2030-01-07 05:30:05` instead of resetting to `06:10:05`, matching Codex's observation.
- The control test failed the same way.

**After the fix:** both pass, and the full suite gives **82 passed**: 80 existing plus 2 new.
- **Missed confirmation:** the 06:10:00 confirmation seen at 06:10:05 after the same-scan reconnect creates no signal, no active entry, no outbox row and no mocked Telegram call. The reason is `confirmation_before_session_watermark`.
- **Control:** after reconnecting at 06:09:40, the 06:10:00 confirmation produces exactly one signal and one mocked send. Repeat scans add no duplicates.

## TailAdmin provenance and license

| | |
|---|---|
| Repository | https://github.com/TailAdmin/tailadmin-free-tailwind-dashboard-template (official free edition, HTML/Tailwind + Alpine.js) |
| Pinned commit | `1bd2dc42a8467ae0281cf00bd0050da4c9c4be07`, 2026-09-15, "refactor: remove global keyboard shortcut for focusing search input" |
| Version | `package.json` v2.4.0 |
| License | MIT, Copyright (c) 2023 TailAdmin, kept in `frontend/src/tailadmin/LICENSE` and `/static/dist/THIRD_PARTY_NOTICES.txt` |
| How obtained | `git clone --depth 1` into `vendor/tailadmin-free/` (project-local) |

The notices file also lists Alpine.js (MIT), Tailwind CSS and @tailwindcss/forms (MIT), and the Outfit font (SIL OFL 1.1).

**Components used**
- Design tokens and utilities from `style.css`: theme colours, typography, breakpoints, `menu-item*`, `no-scrollbar`, `custom-scrollbar`, shadows.
- Sidebar: `partials/sidebar.html` structure, menu-item active/inactive states, sidebar icons.
- Header: `partials/header.html` hamburger and dark-mode toggler.
- `partials/overlay.html` (small-screen drawer overlay).
- Metric cards (`metric-group-01`), table card (`table-01`), badge variants (`badge-01`), warning alert style, form select style (`form-elements.html`).
- The theme manager pattern: `localStorage.darkMode`, applied before first paint.

**Not used:** charts (ApexCharts), maps, calendar, dropzone, i18n, sample data, or the TailAdmin logo (the brand mark here is a plain "Au" tile).

## Build and run

- **Normal use** needs no build: `gold.cmd start | stop | status | restart` serves the committed built assets from `app/static`.
- **After editing the UI:** `gold.cmd build-ui`, then `gold.cmd restart`. The build runs Tailwind CLI 4.3.3 → `app/static/dist/app.css`, then `node copy-assets.mjs`.
- A real build bug was found and fixed during validation: Tailwind was scanning the *generated* `index.html`, which is written after the CSS step, so new template classes (such as `xl:sticky`) were missing. It now scans `frontend/src/index.template.html`.

## Tests and checks actually run

- `.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .tmp/pytest/<unique dir>`: **82 passed**. The one warning is Starlette's TestClient deprecation (third-party). Each run used its own directory under `.tmp/pytest/`.
- **Frontend:**
  - `npm run build`: succeeded.
  - `node --check app/static/app.js`: OK.
  - No duplicate element IDs in `index.html`, and every `$("id")` used by `app.js` exists.
  - The generated CSS was checked for the responsive utilities used (`xl:sticky`, `xl:static`, `xl:translate-x-0`).
- **HTTP:** `/`, `/static/app.js`, `/static/dist/app.css`, `/static/dist/alpine.min.js`, the woff2 font, `/static/dist/THIRD_PARTY_NOTICES.txt` and `/api/tools` all return 200. The removed `/static/styles.css` returns 404. The page makes no CDN or Google Fonts requests.
- **Browser smoke test** (Chrome, real UI loaded from http://127.0.0.1:8000/, with no console errors in the top frame). Chrome's page zoom is 80% for this origin, so exact widths were tested inside same-origin iframes of exactly 1440×900 and 390×844:
  - **Layout:** no page-wide horizontal overflow at 1440 or 390. Wide tables scroll inside their cards. The desktop sidebar is static and the header sticky; on mobile the sidebar is a drawer and the header scrolls away.
  - **Mobile drawer:** the hamburger opens it (`aria-expanded` updates). It closes on a nav link, the overlay, Escape, and a click outside.
  - **Navigation:** sidebar links scroll to Overview, Signals, Setups, Replay and System and update the active item.
  - **Theme:** light/dark toggles, persists across reloads (`localStorage.darkMode`), and the chart recolours. I restored your original light setting afterwards.
  - **Filters:** side SELL → "No signals match the filters."; outcome tp → 1 row; setup state rejected → only rejected rows.
  - **Chart:** a setup row selected with the keyboard (Enter) charts it; the chart redraws on resize. At 390 px the time labels are staggered and legible.
  - **Message preview:** opens with "TEST SIGNAL - DEMO DATA (fictional prices)…" and closes.
  - **Pause/Resume:** the button text and scanner card change correctly.
  - **Mode switch:** declining the confirmation (stubbed `confirm()` returning false, so no native dialog) does not switch; mode stays demo.
  - **Demo replay:** the button disables while running; development and holdout cards render with limitations.
  - **Restart demo:** signals reset to 0 and the empty states show.
  - **Task panel link:** points to http://127.0.0.1:4318/.
  - **Mock states:** with `/api/state` rewritten to an MT5-disconnected state, the banner shows the actionable MT5 message, the symbol shows "not configured", the quote "—", the age "no quote", and Restart demo is hidden. With fetch failing, the banner says it cannot reach the local server, the scanner shows "unreachable", and the replay box shows an error. Telegram "not configured" was checked live: the toggle and test button are disabled.
- **Screenshots** in `.tmp/screenshots/tailadmin/`: `desktop-1440-light.jpg`, `desktop-1440-dark.jpg`, `mobile-390-drawer-open.jpg`, `mobile-390-chart.png`. Because of the 80% browser zoom and the iframe harness, these captures show the app inside a grey test frame.

## Local server state

| | |
|---|---|
| URL | http://127.0.0.1:8000/ |
| PID | 18572 (restarted once to serve the new UI and the scanner fix) |
| Health | `{"app":"vc-trade-gold-signals","pid":18572,"mode":"demo","scanner_running":true}` |
| Telegram | `configured: false, enabled: false` |
| Log | `.tmp/gold-signals/server.log` |
| Commands | `gold.cmd status / stop / restart` |

The task panel (http://127.0.0.1:4318/) was not touched.

## Remaining limitations

- **Browser checks:** done in Chrome at 80% page zoom, using iframes for exact widths. No other browsers, screen readers or real touch devices were tested. Contrast follows TailAdmin's palette and was not measured with an audit tool.
- **Unchanged behaviour:** the native `confirm()` dialogs for mode switch, enabling delivery and the test message are kept as they were.
- **Live SELL outcomes:** still estimated from Bid bars plus the entry spread between quotes (unchanged, documented).
- **Real integrations not verified:** no MT5 terminal was used (all disconnected/MT5 checks are mocks) and no Telegram message was sent.

## Questions, missing requirements, or blockers

None.

## Suggested next step

Codex reviews the reconnect fix and the UI. Real MT5/Telegram verification remains for a separately approved task once the terminal, `GOLD_SYMBOL` and the test bot are configured.
