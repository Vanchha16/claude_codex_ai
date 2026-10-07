# Claude report: FVG dashboard risk and timeframe labels

Task ID: 20261007-135946-fvg-dashboard-risk-labels
Source prompt: `prompt/20261007-135946-fvg-dashboard-risk-labels.md`
Parent completed task: `20261007-111856-fvg-three-entry-engine`
Inputs read: `report/20261007-111856-fvg-three-entry-engine-codex-review.md`, `.tmp/fvg-codex-review/cent-risk-reproduction.json`, `.tmp/fvg-codex-review/timeframe-caption-reproduction.json`
Date: 2026-10-07

## 1. Outcome

Both display defects are fixed. The changes are presentation and tests only.

**What did not change:**
- Strategy rules, risk sizing, broker requests, persistence formats, the API, active config, arming controls and delivery.
- FVG is still **inactive**: `config/active_strategy.json` is still `{"strategy":"fastsweep","profile":"rr2"}`.
- Automatic execution is still **OFF**: there is no `.tmp/gold-signals/fvg_execution_optin.json`.
- The fixed 10 USD setup budget and the 1/50/80 % equal-thirds plan are unchanged.

**No live actions were taken:** no orders, no broker requests, no MT5 initialize, no Telegram messages, no activation or arming, and no live-server restart.

## 2. Files changed

| File | Change |
|---|---|
| `app/static/fvg-display.js` (new) | A small display helper using the same UMD pattern as `smc-zones.js`: `window.VCFvgDisplay` in the browser, `module.exports` in tests. It has two functions, below this table. |
| `app/static/app.js` | <ul><li>The basket renderer now calls `VCFvgDisplay.legRisk(p.planned_loss, ex.account_currency)` with the label "planned loss …". It no longer passes raw account units to the USD `money()` formatter.</li><li>The status-card caption and the evidence panel's "Session" line both use `VCFvgDisplay.lastClosed(...)`.</li><li>`money()` is still used for the top-level fixed USD budget and the per-leg share. Those values are genuinely in USD.</li></ul> |
| `frontend/src/index.template.html` → built `app/static/index.html` | Loads `/static/fvg-display.js` before `app.js`. |
| `frontend/tests/fvg-display.test.mjs` (new) | 8 focused regression tests (section 3). |
| `frontend/package.json` | Adds the new test file to the normal `npm test` command. |

**`legRisk(amount, currency)`:**

| Account currency | Example input | Displayed |
|---|---|---|
| `USD` | 3.33 | `$3.33 USD` |
| `USC` (cent account) | 333.33 | `$3.33 USD (333.33 USC)`: divided by 100, original units still shown |
| Another currency, e.g. `EUR` | 12.5 | `12.50 EUR (no USD conversion)` |
| Missing or blank | 333.33 | `333.33 account units (currency unknown, not converted)` |

- A missing, non-numeric or non-finite amount returns `null`, so nothing is shown: no NaN and no made-up zero.
- The conversions mirror `ACCOUNT_UNITS_PER_USD` in `app/fvg_orders.py`.
- Each leg shows its actual lot-rounded loss as stored, not a forced $3.33.

**`lastClosed(kind, lastClosed, readiness, fmtT)`:**
- `fvg` and `fastsweep` show "Last closed M5 · M15 trend" and the value `M5 <time> · <m15_run>/<required> M15 (ready|warm-up)`, or `—` when readiness is missing.
- CRT, or an unknown kind, keeps "Last closed H1 / M5" with `H1 <time> · M5 <time>`.
- The scanner was not changed, and no H1 dependency was invented for FVG.

## 3. Checks actually performed

- `node --check app/static/app.js`: OK. `node --check app/static/fvg-display.js`: OK.
- `npm.cmd run build` in `frontend/`: OK. The built `app/static/index.html` contains the new script tag.
- `npm.cmd test` in `frontend/`: **36 tests, 36 pass, 0 fail**. That is the 28 existing tests plus 8 new ones:
  - USD unchanged.
  - USC 333.33 shows "$3.33 USD (333.33 USC)" and never "$333.33".
  - Unknown, blank or null currency gets no `$` and no `USD`; EUR is not converted.
  - Missing, NaN, Infinity or string amounts render as `null`.
  - Lot-rounded values (3.10 USD; 298 USC → $2.98) are shown as given.
  - FVG warm-up and ready captions use M5/M15 with no H1; readiness missing → `—`.
  - FastSweep keeps M5 · M15; CRT and undefined keep H1 / M5.
  - A source guard: `app.js` calls `lastClosed` in both places, passes `legRisk` `p.planned_loss` and `ex.account_currency`, no longer has `money(p.planned_loss)`, and has no hard-coded "Last closed H1".
- Backend: `pytest tests/test_api.py` → 6 passed. This was a sanity check only, because the built `index.html` changed. No backend contract was touched, so the full suite was not rerun.

**Synthetic UI inspection (mocked, not live).**
- Harness: `.tmp/ui-mock/mock_server.py`.
  - It served the unchanged `app/static` on 127.0.0.1:8766.
  - The `/api/state` shape came from a demo-mode test app on a throw-away state dir. That dir has since been deleted. No MT5, no Telegram.
  - Values were overridden with fictional ones: FVG active, USC account, M15 warm-up 12/50.
  - Three fictional baskets: USC, USD, and an old record without a currency.
  - Every POST returned 403, so nothing could be armed.
- I viewed it in Chrome.
  - Desktop: the System card and the Overview caption.
  - About 390 px wide: two 390 px same-origin iframes. Window resizing did not apply because the browser window stayed 1920 px wide.
- Findings:
  - The USC legs read "planned loss $3.33 USD (333.33 USC)", "$3.18 USD (318.00 USC)" and "$2.98 USD (298.00 USC)". "$333.33" appears nowhere on the page.
  - USD legs show "$3.33 USD".
  - The old record shows "333.33 account units (currency unknown, not converted)" and "not sized" for unsent legs.
  - The caption reads "Last closed M5 · M15 trend — M5 2026-10-07 06:55:00 UTC · 12/50 M15 (warm-up)".
  - At 390 px the page has no horizontal overflow (scrollWidth 388 = innerWidth 388). The baskets table scrolls inside its own container, like the other tables, and the legs text wraps readably.
  - No console errors after console tracking began. Tracking started after the page had loaded, so load-time messages were not captured.
- Screenshots:
  - `.tmp/ui-mock/screens/desktop-system-fvg-card.jpg`
  - `.tmp/ui-mock/screens/desktop-overview-caption.jpg`
  - `.tmp/ui-mock/screens/narrow-390-overview-and-baskets.jpg`
  - `.tmp/ui-mock/screens/narrow-390-legs-column.png`
- The mock server was stopped and the browser tab closed.

## 4. Checks not performed

- The updated dashboard was not checked against the running live backend: the live server was not restarted, by instruction.
- No real USC or USD account data was used; all values were synthetic.
- The CRT and FastSweep captions were checked through unit tests, not visually in the mock. The mock ran with FVG active.

## 5. Remaining issues (not changed: outside this task's two-defect scope)

- The sidebar footer text, which existed before this work, still says "Alerts and simulated outcomes only. No orders are ever sent." It is visible in the screenshots. For FastSweep and CRT this is true. If FVG were ever activated and armed it would be inaccurate, because the page footer and `/api/state.trading` were already corrected in the parent task but this line was not. I recommend a one-line follow-up if Codex agrees.

## 6. Permission denials

None.

## 7. Questions / blockers

None.
