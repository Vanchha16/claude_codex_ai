# Claude report: name the website VC Signal

Task ID: 20261002-135624-vc-signal-branding
Source prompt: `prompt/20261002-135624-vc-signal-branding.md`
Status: completed
Reported at: 2026-10-02

## Outcome

The website is now branded **VC Signal**, with that exact capitalization and spacing. This is a presentation-only change.

**Approval gate:** passed. The prompt has `APPROVED FOR EXECUTION`, a Task ID, Source prompt and Report path, and a browser-button `User authorization:`. Its draft SHA-256 `daf83b93…f4d2` matches `prompt/drafts/20261002-135624-vc-signal-branding.md`.

**Sequencing:** this ran only after task 20261002-133945-tailadmin-dashboard was finished and its report published. The approved prompt and its draft were not modified.

## Changed files

**Website (canonical source, then regenerated)**
- `frontend/src/index.template.html`:
  - Document title: `VC Signal`.
  - Header `<h1>`: `VC Signal`, shown on desktop and mobile.
  - Sidebar brand: a `VS` monogram tile (`aria-hidden`) plus "VC Signal", with the sub-label "Gold · XAUUSD signals" (instrument description kept).
  - Home link accessible name: `aria-label="VC Signal home"`.
- `app/static/index.html`: regenerated with `npm run build` (in `frontend/`). The compiled CSS was rebuilt too; no new utilities were needed. The TailAdmin attribution comment, notices and license are unchanged.

**Other user-facing strings**
- `app/web.py`: FastAPI title `VC Signal`; event-log entry "VC Signal started in … mode"; HTTP 503 detail "VC Signal is restarting" (both visible in the dashboard).
- `app/delivery.py`: Telegram connectivity test text now reads "TEST MESSAGE - connectivity check from VC Signal (local gold signal dashboard)…". Still labelled TEST MESSAGE and not a signal.
- `app/launcher.py`, `app/server.py`, `gold.cmd`: launcher and server log messages say VC Signal.
- `app/__init__.py`: module docstring.
- `README.md`: title "VC Signal: local gold signal dashboard (CRT-SMC-v1)", with a note that the project folder is `vc_trade`.

**Not renamed** (backend and protocol identifiers): `APP_ID = "vc-trade-gold-signals"` (used by the health check and launcher), the Python package `app`, the `vc_trade` folder, `.tmp/gold-signals/`, `gold.cmd`, API paths, and the task panel's branding. Gold, XAUUSD and CRT-SMC-v1 labels are kept wherever they describe the instrument or the rules.

**Monogram:** I followed the prompt's literal "VS" (V and S, the initials of VC Signal). Change the tile text in the template if "VC" was intended.

## Validation actually performed

- `npm run build` (Tailwind CLI 4.3.3 + `copy-assets.mjs`): succeeded.
- `node --check app/static/app.js`: OK.
- `<title>VC Signal</title>` is in the served HTML, and the old product name no longer appears there.
- `.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .tmp/pytest/vc-brand-<ts>`: **82 passed** (one third-party Starlette deprecation warning). No decorative tests were added.
- `gold.cmd restart`, needed for the Python string changes. The output reads "Stopped VC Signal at http://127.0.0.1:8000/ (PID 18572)" and "VC Signal running in the background: http://127.0.0.1:8000/ (PID 26984)".
- **Browser** (Chrome; same-origin iframes at exact 1440×900 and 390×844, because the browser's page zoom is 80%):
  - `document.title` is `VC Signal` at both widths.
  - The header `<h1>` "VC Signal" is visible at both widths.
  - The sidebar brand "VS VC Signal Gold · XAUUSD signals" is visible on desktop; on mobile it sits in the closed drawer.
  - The home link's accessible name is "VC Signal home".
  - No "Gold Signal Workstation" or "Workstation" text is on the page, and there are no console errors.
  - Screenshots: `.tmp/screenshots/vc-signal/desktop-sidebar-header.png`, `.tmp/screenshots/vc-signal/mobile-390-header.png`.
- **Health:** `{"app":"vc-trade-gold-signals","pid":26984,"mode":"demo","scanner_running":true}`. Telegram is `configured: false, enabled: false`. No broker calls or Telegram messages were made.

## Local server state

http://127.0.0.1:8000/ (PID 26984), demo mode, external delivery off. Log: `.tmp/gold-signals/server.log`. The task panel was not touched.

## Remaining issues

- Monogram text "VS" vs "VC": see above.
- Past entries in previously generated reports and existing demo databases (event-log history) may still contain the old wording. Only current website branding was changed.

## Questions, missing requirements, or blockers

None.
