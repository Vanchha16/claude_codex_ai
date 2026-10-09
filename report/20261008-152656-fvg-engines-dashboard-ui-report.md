# Claude report: FVG Engines page and dashboard-wide interaction polish

Task ID: 20261008-152656-fvg-engines-dashboard-ui
Source prompt: `prompt/20261008-152656-fvg-engines-dashboard-ui.md`
User clarification applied: `prompt/20261008-152656-fvg-engines-dashboard-ui-user-clarification.md` ("don't add many text on website let implement and clean it")
Status: completed
Reported at: 2026-10-08 ~08:51Z

## Outcome

A dedicated **FVG Engines** view now exists at `http://127.0.0.1:8000/#engines-section`. You can reach it from:
- the sidebar ("FVG Engines", under Signals);
- the Overview "FVG engines" card, which has one button per engine;
- the System FVG card's "Open FVG Engines →" link.

The page is presentation-only and read-only. It has no backend change, so no restart was needed.

**Header:** symbol, LIVE/DEMO, feed, scanner, quote freshness and last scan time. After a failed refresh it adds "REFRESH FAILED … · data from …".

**Summary strip:**
- auto execution and its actual source (e.g. "ON · demo default");
- risk "$10 per basket · max $20", from effective values, with a tooltip noting that this is nominal risk, not a hard loss limit;
- slots occupied out of 2;
- today's baskets against the shared cap;
- cooldown scope.

**Two engine cards:** M15 left and M5 right on desktop; stacked M15 then M5 on mobile. Each card shows:
- separate **Analysis** and **Broker slot** chips, such as Warming up / Watching for FVG / FVG rejected / FVG accepted / Unavailable (feed offline), versus Slot free / Pending limits (n of 3 accepted) / Filled exposure / Outcome unresolved / Alert only;
- one short next-action sentence from real evidence, e.g. "Warming up: 43/50 M15 candles · ready ~10:30 if no gap", "Ready · no FVG on the last M5 close" or "Last SELL gap rejected: gap too small";
- a warm-up progress bar capped at the required count, with the actual run count;
- trend and ATR14;
- its OWN candlestick chart, using the existing `MarketChart` fixed at M15 or M5. It has an OHLC hover readout labelled closed/FORMING, a local Reset view, and the library's pan and zoom. It draws the stored strategy FVG bounds (dashed), A/B/C markers at the record's expected candle times, and stored basket SL/entry/TP lines only. Previews are not drawn, and the chart's optional visual zone detector stays off on these charts;
- a compact zone line, slot line, and per-leg rows. Each leg row is a native disclosure showing ticket, filled/pending volume, retcode, cancel state and comment from the journal. Lots and planned loss go through `VCFvgDisplay.legRisk` (USD/USC);
- a **Details** disclosure, closed by default, with last/next close, the conditional warm-up ETA, the decision record (labelled latest or historical selection), the rule checks, the history selector and **Explain in FVG Guide**.

Records come from `/api/fvg` and are filtered by `engine` and the engine version (`FVG-Immediate-<engine>-…`). Legacy v1 records never appear as dual FVGs, and a legacy open basket shows in the M15 slot labelled "legacy v1". Without journal data a basket shows "not sized / not submitted". Unknown or sending legs show as unresolved, never "no fill", and partial acceptance shows the accepted count.

Rule checks claim only what the stored first failure proves. Checks before it are marked passed, the failing one failed, and later ones "not evaluated". An unrecognised reason claims nothing, and with no record no check is claimed.

### Clarification applied (clean, minimal text)

- **Intro paragraphs:** removed from Overview, Chart, Setups, System and the new view. Signals and Replay keep only a short truthfulness label ("Simulated outcomes · not broker fills" / "Simulated · held-out last 30%").
- **FVG Guide:** the long intro became a closed "About this guide" disclosure, and the chart legend a closed "Legend".
- **System:** the setup, Telegram, strategy-config and FVG-execution notes are closed "Details" disclosures. Their element IDs and dynamic content are unchanged.
- **Engine cards and summaries:** they now show short status text, compact numbers and the chart. Timestamps, checks, history and per-leg detail stay reachable in Details or leg disclosures (closed by default).
- **Kept visible:** error, disconnection, stale and inactive states.

## Interaction map (each meaningful click, and its feedback)

Every enabled button, link, nav item, tab, pill, timeframe button, select/input and clickable table row now gets:
- hover feedback (enabled only);
- a `:focus-visible` ring;
- `:active` pressed feedback (same on touch);
- selected state (aria-pressed/aria-selected) and disabled styling.

Control feedback is about 150 ms and panel motion about 210 ms, using transform/opacity only. A real view change fades/slides the new view in once. This is triggered in `nav.js` only on a genuine change: never the first paint, never polls. It doesn't delay routing. Opened disclosure content reveals once.

Existing async buttons get `aria-busy` (spinner, double activation blocked) until their request settles, on success or failure. The same handler runs with the same event, so semantics are unchanged. These are: Pause/Resume, Restart demo, Switch source, automatic-execution ON/OFF, the Telegram test/verify buttons, Replay run and MT5 Find. The engines view shows a thin loading bar only while `/api/fvg` is outstanding, removed on failure.

| View | Meaningful clicks → result |
|---|---|
| Sidebar / header | Nav items → view (hash, history, active item; the mobile drawer closes as before); existing header buttons unchanged, plus busy feedback |
| Overview | M15/M5 engine buttons → FVG Engines, scrolled to and focusing that engine's panel; existing Guide/Chart buttons |
| Chart | Timeframe buttons and indicator pills (now with consistent pressed/hover), Reset/Live/Expand; chart pan/zoom/hover untouched |
| Signals / Setups | Rows (Enter/Space or click) select the record and show its detail/chart, as before, now with hover/focus/pressed row feedback |
| FVG Engines | Reset view (that chart only), history rows → select that engine record (its zone/A/B/C/basket levels on its own chart, labelled historical), leg rows expand their journal details, Details expands decision evidence, Explain → exact record in FVG Guide (disabled with a tooltip when the engine has no record) |
| FVG Guide | Tabs, record select, lesson controls (unchanged), now with consistent feedback; About/Legend disclosures |
| Replay | Run (busy feedback), source/strategy selects |
| System | Setup/Telegram/arming controls unchanged in semantics; Details disclosures; "Open FVG Engines →" |

No inspection action arms, disarms, submits, cancels, changes settings or runs a replay. The execution controls and their confirmation stay in System and are unchanged.

## Files changed

Frontend only; nothing committed or pushed. The previous tasks' uncommitted work is preserved.

- **`app/static/fvg-engines.js` (new):**
  - pure helpers: `recordsFor`, `basketsFor`, `legCounts`, `brokerState`, `analysisState`, `nextAction`, `ruleChecks`, `keepSelection`, a `latest` request-generation guard, `legRows`, `trendText`, `parseKey`;
  - the browser view: built once, then updated in place. Unchanged lists aren't re-rendered, so focus, open legs and Details survive polling;
  - two independent `MarketChart` instances, GET-only data, stale-response guards, and last-good-data with a stale label.
- **`app/static/app.js`:**
  - emits `vc:state` and `vc:state-error`, so the existing poll is reused;
  - busy wrapper on async buttons;
  - shorter System engines summary;
  - dual-mode page kicker (it showed "? / ?");
  - object-valued strategy-config fields are shown as text (previously "[object Object]", a leftover from the dual task).
- **`app/static/nav.js`:** the `engines` view, and the enter transition on real view changes.
- **`frontend/src/index.template.html`**, plus the generated `app/static/index.html`: the engines view and its panel template, the sidebar item, the Overview engine card, the System link, and the intro/notes cleanup and disclosures described above.
- **`frontend/src/input.css`**, plus the generated `app/static/dist/app.css`:
  - the interaction system and reduced-motion overrides;
  - action-card, record-row, leg and progress styles;
  - the engines layout;
  - the `@source` for the new script.
- **`frontend/package.json`:** the new test file is included.
- **Tests:** `frontend/tests/fvg-engines.test.mjs` (new) and `frontend/tests/nav.test.mjs` (new view, deep link, Back/Forward, enter-transition class).

## Validation performed

- **Frontend:** `npm.cmd test` gives **52 passed**. The tests cover:
  - per-engine record isolation, with legacy v1 never counting as dual and legacy baskets in the M15 slot;
  - warm-up / ready-no-gap / rejected / offline;
  - pending / partial (1 of 3) / unknown / sending / filled / alert-only slot states;
  - leg rows with and without journal data;
  - rule-check evidence from the first stored failure;
  - selection preservation and fallback;
  - the stale-response generation guard;
  - key parsing;
  - the router's deep link, saved view, Back/Forward and enter class.
- **Build and syntax:** `npm.cmd run build` succeeded, and `node --check` passed on `fvg-engines.js`, `app.js`, `nav.js` and `fvg-guide.js`.
- **Backend:** no backend code changed in this task, so no backend suite or restart was needed.
- **Live app, read-only**, in Chrome (screenshots in `.tmp/fvg-engines-screens/`):
  - Both engine panels and own-timeframe charts render with real MT5 data (`01`, `03`, `08`). M15: warming up 43/50 with ETA; M5: ready, last SELL gap rejected "gap too small", zone drawn.
  - A layout bug, a CSS class collision in the rule-check list (`02`), was found and fixed (`03`).
  - **Network check:** with `fetch` instrumented, I exercised both Resets, history selection, the Details disclosure, every view, the Overview engine card, Explain → Guide and Back. Only **GET** requests were made, to `/api/state`, `/api/fvg`, `/api/market/bars`, `/api/fvg/guide` and the existing table GETs. There were zero non-GET requests.
  - **Keyboard:** Enter on the focused Overview M5 card opened the view and focused `engine-M5`. Focus rings are visible (`07`).
  - **Transition coverage:** measured `transition-duration > 0` on every visible interactive control in all eight views and the sidebar. This found the uncovered Chart timeframe buttons, which I fixed.
  - **Touch targets:** no visible interactive target under 28 px on the engines page at 390 px.
  - **Console:** no errors after a clean reload and stepping through all views.
- **Isolated mock:** a throwaway dual DEMO instance on port 8014 with a temp store, seeded with FICTIONAL records by `.tmp/guide-visual/seed_engines_mock.py`, which refuses paths outside `.tmp`. It never touched the live store, MT5 or Telegram, and is now stopped.
  - M15 slot with an UNKNOWN leg: "1/3 accepted · 0 filled · 1 unresolved", leg 2 "UNKNOWN – being reconciled, never resent", leg 3 "not sent". M5 slot with filled exposure (`04`).
  - A historical closed partial basket selected: TP / refused / not sent, labelled "selected, not the current slot" (`05`).
  - The selection survived refreshes.
  - Disconnected (state response rewritten in that tab only): "FEED OFFLINE", "Unavailable (feed offline)", "Feed offline."
  - Failed refresh (`fetch` rejected in that tab only): "REFRESH FAILED … · data from …".
  - 390 px light and dark, stacked panels, no page overflow (`06`, `09`). `09` shows the compact default and the expanded Details side by side.
  - Overview engine cards with hover and focus (`07`).
- **Reduced motion:** the `@media (prefers-reduced-motion: reduce)` rules are present in the built CSS. They remove transitions/animations and pressed transforms; the Overview→panel scroll uses `behavior:auto`. This was confirmed from the built CSS and the code only. The browser tool can't emulate the OS setting, so it was not exercised live.
- **Runtime after delivery, read-only** (08:50:27Z):
  - Account and version: MetaQuotes-Demo (demo), XAUUSD, `FVG-Dual-M15-M5-Immediate-v2-RR2@f4b7f7a5`.
  - Data and scanner: feed ok, quotes fresh, scanner running with no error.
  - Execution: auto **ON via demo default** (`armed_at` null; the explicit dual consent is still the open item from the previous task, not touched here); $10 per basket, max $20.
  - Telegram: ON.
  - Engines: M15 43/50 warming up; M5 130 ready, trend down.
  - Records: **0 baskets**, 0/4 today; natural dual setups: M5 SELL rejected `gap_too_small`, M15 BUY rejected `trend_warmup`.

## Checks not performed

- **Real `prefers-reduced-motion` emulation and a physical touch device:** these were verified from the CSS and code only (see above).
- **Light theme in the main window:** checked in 390 px iframes; the desktop screenshots are dark.
- **A screen reader:** not used. Native buttons, details and labels were used, plus `aria-pressed` and `aria-busy`.
- **A real broker basket:** pending, filled and unknown states were shown only with fictional mock records.

## Questions, missing requirements, or blockers

None for this task. The explicit dual-version consent from the previous task remains open; it was intentionally not touched.

## Suggested next step

Codex reviews the engines view (data mapping in `fvg-engines.js`) and the clarification cleanup.
