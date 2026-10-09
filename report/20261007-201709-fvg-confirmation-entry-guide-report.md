# Claude report: FVG confirmation-to-entry guide in the dashboard

Task ID: 20261007-201709-fvg-confirmation-entry-guide
Source prompt: `prompt/20261007-201709-fvg-confirmation-entry-guide.md`
Review observations addressed: `prompt/20261007-201709-fvg-confirmation-entry-guide-review-observations.md` (all six; see below)
Status: completed
Reported at: 2026-10-08 (around 07:45Z)

## Outcome

A read-only **FVG Guide** view is built into the existing dashboard. Open it at `http://127.0.0.1:8000/#guide-section`, from the sidebar (Signals → **FVG Guide**), from the overview FVG card's **FVG guide: how it confirms** button, or with **Explain in FVG Guide** on any FVG basket row. That last link opens the Guide on that basket's setup.

- **Live / recorded mode**
  - Default selection: the newest pending or retested setup, else the newest record. Any stored record can be picked from a list, and the choice survives the 10-second polling.
  - The header shows LIVE or HISTORICAL with the status and a plain-English reason, plus a runtime line: data mode, FVG active, feed, quote freshness, scanner paused, automatic execution, risk and update time.
  - Progress path: M15 detected → qualified → M5 retest → M5 confirmation → eligibility → three pending limits → fills. Each step shows one of Completed, Partly done, Waiting, Failed/expired, Not used or Not reached, with a symbol so state never depends on colour alone.
  - A prominent **What must happen next** box, and three separately labelled deadlines: setup lifetime, confirmation window and pending-order lifetime.
  - An annotated SVG chart:
    - candles: M15 A/B/C, then M5 candles with hover/focus tooltips;
    - the zone band, the retest marked **R**, the frozen confirm level, and confirmation slots tagged ✓, ✗ or … (forming);
    - entry, SL and TP lines once a basket exists.
  - A confirmation-window list, using closing prices only.
  - An entry ladder:
    - Without a basket it shows **PREVIEW levels (not orders)**: tick-exact via `basket_levels`, lots "not sized", state "not submitted".
    - With a basket it shows **Actual basket levels**, with lots and planned loss from the execution journal via `VCFvgDisplay.legRisk`.
  - A risk explanation and the rule reference, both driven by config.
- **Learning (fictional) mode:** four deterministic lessons, each candle replayed through the real `advance_setup` / `basket_levels` / `_step_basket`:
  - BUY success;
  - SELL success (mirrored);
  - retest without confirmation (an exactly-equal close, then expiry);
  - invalidation winning over a wick through the level.

  Controls are Previous, Next, Reset, a step scrubber (arrow keys work), and Play/Pause (slower when reduced motion is set). Frames reveal candles in time order and never show future candles. After confirmation, the ladder shows the three pending limits and later fictional fills.
- **The motivating SELL case** is reproduced from the stored record:
  - level 4079.74;
  - chances 1–3 closed at 4089.47, 4088.58 and 4094.25, each "did not close beyond the level";
  - confirmation Failed; eligibility, limits and fills Not reached;
  - next: "Finished: none of the 3 M5 candles after the retest closed beyond the retest level".

### Codex review observations: all addressed

1. **Unknown or sending legs are no longer reported as "no fill".** Legs are grouped as accepted, filled, uncertain (`unknown`/`sending`/`prepared`) or not accepted.
   - With uncertain legs, the limits step is **Waiting**, e.g. "0 of 3 limits accepted so far; 1 unresolved and being reconciled".
   - The fills step is **Waiting**: "a fill cannot be ruled out".
   - A known fill stays visible beside an unresolved leg (fills **Completed**, with "1 leg(s) still unresolved, so more fills may exist").
2. **Partial submission is shown as partial.** `pending, rejected, not_sent` gives **Partly done**: "Only 1 of 3 limits were accepted; the rest were refused or not sent". Completed requires all three accepted.
3. **No invented inputs.**
   - The API no longer substitutes 0.01 tick / 2 digits. If broker metadata can't be read, the preview says exact levels can't be computed.
   - Records from older rule versions show no preview, with "recorded under an older rule version … no preview is shown".
   - The risk text no longer falls back to $10 when risk is unavailable.
4. **Confirmation slots follow the expected M5 timestamps.**
   - Slot i is the candle opening exactly i−1 candles after the retest closed. Each slot is replayed with `advance_setup` on a copy, so the window ends wherever the engine's window ended: missing or invalid candle, setup lifetime, invalidation, or an earlier confirmation.
   - A missing slot is listed as **missing** and nothing after it is drawn.
   - A candle is marked as *the* confirmation (`beyond: true`, ✓) only when the stored record confirmed on that same close. Otherwise it reads "close comparison only … the stored record did not confirm on this candle", or "the engine records the confirmation on its next scan" if the engine simply hasn't processed it yet.
   - Lessons use the same server-side slot builder.
5. **A/B/C roles come from expected timestamps** (`a_open + i·M15`). Missing formation candles are listed in `m15_missing` and in the data note, e.g. "formation candle(s) A not in the returned history".
6. **A forming candle reads as forming**, e.g. "Chance n · M5 forming, closes HH:MM · price now …". A missing one reads "M5 HH:MM candle → missing …".

### Also fixed during visual review

- Right-margin price labels overlapped when prices were close. They are now spread at least 12 px apart, kept inside the plot, with leader lines (`spreadLabels`).
- The first axis label was clipped; edge labels are now anchored inside the plot.
- Raw ISO timestamps in step text are shown in the display time zone.
- At ~390 px the chart had shrunk until its text was unreadable. It now keeps a 620 px minimum width and scrolls sideways inside its own frame; the page itself has no horizontal scroll.
- The two tab labels were shortened ("Live / recorded", "Learning (fictional)") so the tab strip fits at 390 px.

## Files changed

Nothing is committed or pushed.

- `app/fvg_guide.py` (new): read-only presentation module.
  - Reason texts.
  - `config_view`, `record_dict`.
  - `preview_levels`, which uses `basket_levels`.
  - `window_candles`: slot replay with `advance_setup`.
  - `steps`: per-leg evidence states.
  - `next_requirement`, `deadlines`, `record_view`: timestamp-based A/B/C and honest preview availability.
  - Lessons: fictional bars, a `qualify` gate, `advance_setup` / `_step_basket` frames with server-built windows.

  It never writes a store or calls a broker.
- `app/web.py`:
  - `GET /api/fvg/guide?key=&limit=` returns runtime flags, records and the selected record view. Candles come from a bounded `bars_range` (≤ 6 h) only when the feed is OK. Metadata is `None` when unreadable.
  - `GET /api/fvg/guide/lessons` returns config and lessons.
  - No other routes changed.
- `app/static/fvg-guide.js` (new, UMD `VCGuide`):
  - pure helpers `stepLook`, `clampFrame`, `layoutChart`, `spreadLabels`;
  - renderers for steps, ladder, chart, live, risk, lesson and rules;
  - polling only while visible;
  - `openRecord(key)`.

  It makes GET requests only.
- `app/static/app.js`: an **Explain in FVG Guide** button on each FVG basket row, which opens that setup in the Guide. Nothing else changed.
- `app/static/nav.js`: a `guide` view was added to the router.
- `frontend/src/index.template.html`, plus the generated `app/static/index.html`:
  - the head view map;
  - the script tag;
  - the sidebar link;
  - the overview button;
  - the full `#guide-section` markup.
- `frontend/src/input.css`, plus the generated `app/static/dist/app.css`: guide styles, the leader-line style, the `.vc-link` style, and the chart's scroll-inside-frame rule.
- `frontend/package.json`: the test script includes `tests/fvg-guide.test.mjs`.
- Tests: `tests/test_fvg_guide.py` (new, 19 tests) and `frontend/tests/fvg-guide.test.mjs` (new, 6 tests).

Read-only, not modified: `app/fvg.py`, `app/fvg_live.py`, `app/fvg_orders.py`, `app/fvg_execution.py`, `app/scanner.py`, persistence, consent, Telegram, and the risk and override files.

## Validation performed

- **Backend, focused:** `pytest tests/test_fvg_guide.py --basetemp=.tmp/pytest-guide-focused` gives **19 passed**. The tests cover:
  - the real SELL case explanation;
  - mid-window next requirement and a forming candle;
  - preview levels equal to `basket_levels`, with SELL geometry;
  - actual basket lots from the journal; alert-only shown as skipped;
  - no future candles in lessons;
  - BUY and SELL success reaching pending limits and then a later fill;
  - equal close not confirming, then expiry;
  - invalidation precedence;
  - the third later candle confirming, and equality on the third candle expiring;
  - unknown and sending legs not reported as no-fill;
  - a known fill beside an unknown leg;
  - partial submission not counting as three limits;
  - a missing M5 candle ending the window;
  - the window stopping at the stored confirmation;
  - a beyond-close without a stored confirmation shown as comparison only;
  - A/B/C roles with a missing A;
  - preview unavailable without metadata or for an older version;
  - API read-only: scanner stopped, executor and maintenance replaced with functions that fail if called, setup and basket counts unchanged, record status unchanged.
- **Backend, full suite** with a fresh basetemp: one run had **1 failure**, `tests/test_mt5_time.py::test_verified_server_offset_normalises_quotes_bars_and_ranges_exactly_once[2]`. That file is unchanged since commit `168fdf8` and this task did not touch it. It then passed alone (22 passed), and two further full runs gave **333 passed** each, so it looks intermittent (see Questions).
- **Frontend:** `npm.cmd test` gives **42 passed**, including new tests for label spreading and the "Partly done" state.
- **Build and syntax:**
  - `npm.cmd run build` succeeded.
  - `node --check` passed on `fvg-guide.js`, `app.js` and `nav.js`.
  - `py_compile` passed on `app/fvg_guide.py` and `app/web.py`.
- **Codex resume probes:** re-ran `.tmp/fvg-guide-codex-review/resume-probes.py` against the new code; results are in `.tmp/fvg-guide-screens-probe.json`.
  - unknown/sending → Waiting / Waiting;
  - partial → Partly done;
  - gapped window → retest, then a missing slot (not a confirmation);
  - missing A → roles B, C;
  - older version → preview unavailable.
- **Visual (Chrome, real rendered app).** Screenshots are in `.tmp/fvg-guide-screens/`.
  - Desktop, dark, live MT5:
    - a fresh rejected setup (trend warm-up), `01`;
    - the real expired SELL with its confirmation window, `02`.
  - Lessons:
    - BUY last frame with fills, `03`;
    - zoomed label spreading, `04`;
    - no-confirmation lesson at the equal-close step, `05`.
    - Checked through the DOM: SELL shows only "1 ✓" after confirmation, invalidation shows "1 ✗", no-confirmation shows "1 ✗ 2 ✗ 3 ✗".
  - Mobile 390 px, light theme (the app in a 390 px iframe, since the browser window could not be resized):
    - the live view, `06`;
    - the chart before the fix (too small), `07`, and after (readable, scrolls in its frame), `08`.
    - Measured: document overflow 0, `#content` overflow 0, tab strip overflow 0.
  - Inactive and empty states, using separate throwaway **demo** instances with temp state under `.tmp/guide-visual/`. They used no MT5, no live store, no Telegram token, and are now stopped.
    - CRT active: "FVG is not the active strategy…", with the rule reference still shown, `09`.
    - FVG demo: the lesson ladder shows "pending limit (waiting)" ×3 at confirmation versus "filled → TP / filled → TP / pending" on the last frame, `10`.
    - The API test also covers the empty FVG state (`records == []`, `selected is None`).
  - Navigation:
    - overview button → `#guide-section`, Guide shown;
    - sidebar Setups, then Back → Guide;
    - Back → Overview; Forward → Guide;
    - the sidebar item is marked active.
  - Controls: Reset (Previous disabled), Next, Play/Pause, and ArrowRight on the focused "Candle step" scrubber all work.
  - Console: no errors after a clean reload.
  - Disconnected, partially verified: earlier on 2026-10-08, with MT5 closed, `/api/state` reported feed `ok: false`. The Guide was not rendered in that state.
    - The runtime line ("feed OFFLINE"), the candle skip and its data note, and the unreadable-metadata preview message are all driven by the same flag. They are covered in code and in unit tests (`meta=None`, empty `m5`), not by a screenshot.
  - `11`–`13` are screenshots from the first session, 2026-10-07.
- **Restart:** one normal `app.launcher restart` loaded the backend changes. It took no MT5 login, initialize or switch action. The terminal had been reopened by the user beforehand.
- **Read-only runtime after the work** (2026-10-08 ~07:45Z):
  - Account: MetaQuotes-Demo, demo, XAUUSD.
  - Strategy: FVG (3 limits, 1:2).
  - Feed and data: feed OK, quote fresh, scanner running without error, trend warm-up 38/50.
  - Preferences: automatic execution **ON (armed by you)**, risk **$10**, Telegram **ON**.
  - Trading state: **0 baskets**. There are 10 recorded setups, all formed naturally by the live scanner: the historical expired SELL, plus rejections for `trend_warmup`, `trend_against` and `weak_displacement`. No positions are reported.

## Checks not performed

- **Real dark/light theme toggle in the main window:** light theme was set on the iframe document (`data-theme="light"`) rather than through the header toggle. Dark was the user's current theme.
- **A real browser setting for reduced motion:** the code path, a slower Play interval, was inspected; the OS setting was not emulated.
- **A real broker basket in the Guide:** none existed naturally, so actual lots, legs and states were verified only through unit tests with journal-shaped data, never by placing orders.
- **Screen-reader pass:** not performed. The chart has an `aria-label` and focusable candles with `<title>` tooltips, but this was not tested with assistive technology.

## Questions, missing requirements, or blockers

None for this task.

For Codex: `tests/test_mt5_time.py::…exactly_once[2]` failed once in a full run and passed in every later run. It may be order- or timing-dependent. It is outside this task's scope, so I did not change it.

## Suggested next step

Codex reviews the Guide, especially the per-leg evidence wording and the slot replay in `window_candles`. Then the user decides whether to commit.
