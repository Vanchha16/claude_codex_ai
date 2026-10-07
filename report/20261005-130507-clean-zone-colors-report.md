# Claude report: distinct zone colours and a cleaner display

Task ID: 20261005-130507-clean-zone-colors
Source prompt: `prompt/20261005-130507-clean-zone-colors.md`
Status: completed
Reported at: 2026-10-05, about 06:00 UTC (13:00 Bangkok)

## Outcome

Chart zones now have one colour per type, matched across the rectangles, label badges, toggle swatches and the help legend. The default display is much quieter.

**Colour and labels:**
- Colour shows the type: FVG cyan, IFVG purple, OB amber, BB rose.
- Direction stays explicit through the badge arrow (▲ bullish / ▼ bearish), the pill tooltips and the help text.
- Border styles remain a second type cue: FVG solid thin, IFVG dashed, OB thicker solid, BB dotted.
- Candles keep their green/red.
- Fills are very light, and ended zones are fainter still.
- Rectangles are drawn **below** the candles. Compact badges (rounded, type-coloured, high-contrast text) are drawn just above the candles.

**Badge collisions:** an overlapping badge is **skipped, never moved**. The priority order is the newest active zone first, then the newest ended one. Rectangles always stay at their real price/time location.

**Display defaults and controls:**
- **Default:** the latest **3 active** zones per enabled type (at most 12 boxes), with ended history hidden.
- **"Recent" selector:** 3 / 5 / 10 per type.
- **History toggle** (off by default): when on, active zones come first and the newest ended zones fill the remaining per-type cap, never exceeding it.
- These controls affect rendering only. They never re-run detection or change detection results, transitions, provenance or IDs, and they add no size filter.

**Honest counts:** for example, "Shown / active: FVG 3/11 · IFVG 3/12 · OB 3/8 · BB 1/1".
- Ended zones appear as "+n ended" only when History is on.
- A toggled-off type shows as "FVG off".
- The tooltip gives drawn, active and detected counts plus the candle basis.
- The zero-data and zero-zone states are unchanged.

**Same symbol and timeframe before/after** (live XAUUSDc M5, 400 closed candles):
- **Before:** 40 boxes, all green/red, with history mixed in.
- **After:** 10 boxes (3/3/3/1). Counts were active FVG 11, IFVG 12, OB 8, BB 1, with 231 zones detected on that data.

## Actual palette

These are CSS tokens in `frontend/src/input.css`, read by the chart. The light/dark values are exactly as specified; no contrast adjustments were needed.

| Type | Dark | Light |
|---|---|---|
| FVG | `#38bdf8` | `#0284c7` |
| IFVG | `#a78bfa` | `#7c3aed` |
| OB | `#fbbf24` | `#b45309` |
| BB | `#fb7185` | `#be123c` |
| badge text | `#0b0e14` | `#ffffff` (minified to `#fff` by the CSS build) |

Fill opacity is about 0.06–0.09 (×0.4 for ended zones); outline about 0.55–0.65; badge background about 0.9 (0.55 for ended).

## Files changed

- **`app/static/smc-zones.js`:**
  - `selectForDisplay(zones, perType, {history})`: `history: false` gives active zones only. Called without options, it keeps the previous behaviour (10 per type, history included).
  - Added `normalizeDisplay()`, which bounds the preference to perType 3/5/10 and a boolean history, defaulting to 3 and off. Also `DISPLAY_CAPS` and `DISPLAY_DEFAULTS`.
  - **`detect()` is unchanged.**
- **`app/static/market-chart.js`:**
  - `ZonePrimitive` now colours by type and uses two pane views: boxes at zOrder `bottom`, badges at `normal`. It shares one geometry pass, orders by recency and skips colliding badges.
  - The colour parser accepts 3- and 6-digit hex.
  - `MarketChart` gained `setZoneDisplay()` and `_selectZones()`, which select from the cached detection result without re-detecting. `_emitZones()` now reports shown active and ended counts per type and the display options.
  - Palette comes from the `--zone-*` tokens and is reapplied in `applyTheme()`.
- **`app/static/app.js`:**
  - display preference `vcZoneDisplay.v1`, versioned and bounded, falling back safely when storage is invalid or blocked;
  - wiring for the Recent selector and History toggle;
  - honest "Shown / active" counts and tooltip;
  - the `vcIndicators.v1` toggles are unchanged.
- **`frontend/src/index.template.html`:** zone pills with type swatches and tooltips (type, colour, ▲/▼), the Recent select, the History pill, and a help colour legend with the updated defaults text.
- **`frontend/src/input.css`:** `--zone-*` tokens (light and dark), replacing the previous `--chart-zone-bull/bear`. Zone-control styles are scoped to `.vc-zone-pill`, `.vc-zone-select` and `.vc-legend`, so generic pills (EMA, volume, Telegram, replay) are unchanged.
- **`frontend/tests/zones.test.mjs`:** 4 new display tests:
  - active-only newest-first with each cap at most 3/5/10;
  - History filling the cap with the newest ended zones;
  - selection never mutating detection, and the legacy defaults unchanged;
  - bounded preference normalisation.
- **`README.md`:** the "Chart zones" display bullet now covers the palette, direction badges, the 3-active default, Recent 3/5/10, History, the "shown/active" counts, and both storage keys.
- **Regenerated by the build:** `app/static/index.html` and `app/static/dist/app.css`.
- **Not touched:** detection rules, the backend, strategy, config, database, Telegram, `nav.js` and `tools/`.

## Validation performed

**Automated:**
- `npm run build` (frontend): OK.
- `npm test`: **28 passed, 0 failed** (the existing 24 plus 4 new display tests). The existing detector tests are unchanged and still pass, which shows identical detection on identical input.
- `node --check` on every `app/static/*.js`: OK.
- Backend tests: not run (backend untouched).

**Browser** (Chrome, live dashboard, read-only):
- **Setup:** same-origin iframes at exact CSS widths of **1536** and **390**, then **1026**, because the Chrome window is maximised at about 64% zoom.
- **Storage:** the browser's pre-test values were restored at the end: `vcSection=signals`, `darkMode=true`, and both indicator keys absent.
- **Before/after:** same symbol, timeframe and frame sizes, taken before and after the change.
- **Badges:** a zoomed check confirmed readable FVG/OB/IFVG badges with no overlap.
- **Controls preserve everything:** with a selected setup record (setup #3, setup mode) on screen, each of these left the visible logical range, the timeframe, the selection, the detection cache key and the detection result object unchanged:
  - FVG off: counts showed "FVG off";
  - Recent set to 10: 29 boxes;
  - History on: 40 boxes, 11 of them ended;
  - switching to the light theme: light palette applied.
- **Preferences:** saved as `{"perType":10,"history":false}` and similar, then reset to 3 and off.
- **Light theme with a busy setting:** with 10 per type plus History over the setup, the setup's price lines and axis labels (A high, level, A low, sweep) stay legible; that screenshot is saved.
- **Hidden reveal:** Overview → Chart redrew from the cache (same key).
- **Layout:** no page overflow at 1536, 390 or 1026 px. At 1026 the controls wrap onto two rows; at 390 they wrap cleanly and the help panel and legend fit.
- **Console:** no console errors.

**Runtime** (read-only, after testing):
- mode `mt5`, XAUUSDc, feed ok, scanner running and unpaused with no error;
- Telegram enabled with the persisted opt-in;
- 0 signals, outbox unchanged (3 earlier `sent` rows).

**Watermark:** it moved from 04:37:41Z (my earlier restart) to **05:55:02Z**. The event log shows these were the app's own automatic "recovered after a disconnected/stale feed" transitions, at 04:59, 05:06 (twice), 05:24, 05:28 and 05:55. This frontend-only task (GET requests only) did not cause them.

Screenshots in `.tmp/screenshots/`:
- `vc-zones-colors-BEFORE-dark-1536-390.jpg`
- `vc-zones-colors-AFTER-dark-1536-390.jpg`
- `vc-zones-colors-AFTER-badges-zoom.png`
- `vc-zones-colors-light-cap10-history-setup.jpg`
- `vc-zones-colors-dark-1536-light-390-help.jpg`
- `vc-zones-colors-light-1026-help.jpg`

## Checks not performed or limited

- **Native window sizes:** not used. Frames were used instead (disclosed above).
- **Pan/zoom drag gestures:** not exercised by hand. The viewport was changed programmatically, and the boxes use the same chart coordinate path as the accepted previous task.
- **Real fullscreen, sidebar collapse and the mobile drawer:** not re-run in this pass. Those code paths are unchanged, and the overlay redraws on resize.
- **Live candle close:** not watched in this session. The cache and polling path is unchanged; Codex verified it in the previous review.

## Questions, missing requirements, or blockers

None.

One observation for Codex/user, outside this task's scope: the scanner logged **six** automatic stale-feed recoveries in about an hour (04:59–05:55 UTC). Each one moves the session watermark. They may be caused by quiet market periods exceeding the 30 s quote-age limit, or by brief MT5 interruptions. It could be worth a separate read-only investigation.
