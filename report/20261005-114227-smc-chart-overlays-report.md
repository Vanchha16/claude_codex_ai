# Claude report: FVG, IFVG, Order Block and Breaker Block chart overlays

Task ID: 20261005-114227-smc-chart-overlays
Source prompt: `prompt/20261005-114227-smc-chart-overlays.md`
Status: completed
Reported at: 2026-10-05, about 04:55 UTC (11:55 Bangkok)

## Outcome

The Chart view now has four independently toggleable price-zone overlays next to EMA20/EMA50/Tick volume: **FVG, IFVG, OB and BB**. They are display-only.

**What does not change:** CRT-SMC-v1, signal confirmation, Entry/TP/SL/RR, Telegram, the backend, config and the database.

**How it is built:**
- **Detection:** a pure, deterministic module, `app/static/smc-zones.js`, built from closed candles and the symbol tick size.
- **Drawing:** a Lightweight Charts **series primitive** in `app/static/market-chart.js`. It draws semi-transparent rectangles attached to the real price and time scales, in the candle pane, below the candles. It doesn't intercept pan, zoom or touch.

**What the user sees:**
- Each pill has a tooltip, and there is a compact "Active zones: FVG n · IFVG n · OB n · BB n" line. Its tooltip shows active and detected counts and the candle basis.
- An "About zones" disclosure explains the four types and the close-based rules.
- The new toggles default to on for a fresh preference.
- Choices are stored in a versioned, allowlisted `vcIndicators.v1` (booleans only; blocked storage falls back to session-only). EMA/volume selections are kept.

**Live result** on XAUUSDc M5 with 400 closed candles, at the time of the check:
- active: FVG 14, IFVG 12, OB 6, BB 2;
- detected: 92 / 78 / 29 / 23;
- the newest 10 of each type are drawn.

These are real annotations from the MT5 feed. No invented zones.

## Definitions actually implemented

The full text is in `app/static/smc-zones.js`, README "Chart zones", and the in-app "About zones".

- **Input and contiguity:**
  - Only closed candles (`forming:true` bars are ignored even if passed) and the tick size are used. Comparisons use a float tolerance of tick×1e-6.
  - A bar continues a segment only if it is exactly one timeframe step after the previous one. A gap, an invalid or non-finite OHLC bar, or an out-of-order or duplicate bar starts a new segment.
  - Patterns form only inside one segment. Existing zones keep being managed by later closes.
- **FVG:** bars i-2, i-1, i.
  - Bullish if `low[i] - high[i-2] >= 1 tick`, zone `[high[i-2], low[i]]`.
  - Bearish if `low[i-2] - high[i] >= 1 tick`, zone `[high[i], low[i-2]]`.
  - It activates on bar i, available once that bar closes. A zero or sub-tick gap is not an FVG.
- **IFVG:**
  - A bullish FVG flips to a bearish IFVG on a later close strictly below its bottom; a bearish FVG flips on a close strictly above its top.
  - The FVG ends there (`inverted`). The IFVG keeps the bounds, origin and parent ID and activates on the flip bar.
  - A bearish IFVG ends on a close strictly above its top, a bullish one strictly below its bottom.
  - There are no flip chains, and wick touches don't count.
- **Pivots:** two bars on each side with strict comparisons, usable only after the second right-hand bar closes. Only the most recently confirmed pivot high or low is eligible, and each pivot is consumed once.
- **OB:**
  - A bullish break is a close strictly above the eligible pivot high. The source is the last bearish candle (close < open) before the break bar, searched back at most 20 bars and not before the pivot. The zone is its full high–low range.
  - A bearish OB mirrors this.
  - If there is no opposite-colour candle there is no OB, but the pivot is still consumed.
  - The OB activates on the break bar.
- **BB:**
  - A bullish OB closed strictly below its low becomes a bearish BB; a bearish OB closed strictly above its high becomes a bullish BB. It keeps the bounds and origin and activates on that bar.
  - A bearish BB ends on a close strictly above its top, a bullish one on a close strictly below its bottom. No flip chains.
- **Order per bar:** manage existing zones, then structure breaks (OBs), then FVGs, then confirm pivots (usable from the next bar). A zone never ends on its own bar.
- **IDs:** `${type}-${dir}-${origin}-${activation}`.
- **Display:**
  - Colour shows direction: green ▲ bullish, red ▼ bearish (theme tokens `--chart-zone-bull` / `--chart-zone-bear` in dark and light).
  - Border shows type: FVG solid thin, IFVG dashed, OB thicker solid, BB dotted. Each zone is labelled with direction and type.
  - Zones start at the activation candle. Active zones extend to the newest drawn candle; ended zones are drawn faded up to the candle that ended them.
  - The display cap is the newest 10 per type (active first, then most recently ended), at most 40 in total. Detection always uses all loaded closed candles.
  - Overlapping labels are skipped, but rectangles are always drawn.

## Files changed

- **`app/static/smc-zones.js` (new):**
  - `detect(bars, {tick, step})` returns `{zones, stats}`;
  - `selectForDisplay(zones, 10)`, `counts(zones)`, `validBar`, `TYPES`, `NAMES`;
  - UMD-style, so it runs in the browser as `window.VCZones` and in Node via `require`.
- **`app/static/market-chart.js`:**
  - `ZonePrimitive`: attached to the candle series, z-order "bottom", media-coordinate drawing, label collision skip; `detachPrimitive` runs in `dispose()`.
  - `_updateZones()` is called from `_render()` and after incremental poll updates.
  - Detection is cached under a key of tf|tick|bar count|first time|last time|last OHLC. It recomputes only when closed data changes, never per draw.
  - `setIndicator()` handles zone toggles without re-setting data, so the viewport is untouched. Theme colours are reapplied in `applyTheme()`.
  - Chart overlays, markers, polling, older-history and setup logic are unchanged.
- **`app/static/app.js`:** indicator preference (`vcIndicators.v1`, versioned and allowlisted), pills wiring for all 7 indicators, and the `renderZoneCounts()` status line, which also covers the empty and no-data states.
- **`frontend/src/index.template.html`:** `smc-zones.js` script, loaded before `market-chart.js`; FVG/IFVG/OB/BB pills with tooltips; the counts line; the "About zones" `<details>`.
- **`frontend/src/input.css`:** zone colour tokens (light and dark), pill separator, help panel styles.
- **`frontend/tests/zones.test.mjs` (new):** 13 tests.
- **`frontend/package.json`:** the test script includes `tests/zones.test.mjs`.
- **`README.md`:** new "Chart zones" section with the conventions, display cap and preference key.
- **Regenerated by the build:** `app/static/index.html` and `app/static/dist/app.css`.
- **Not touched:** the backend, strategy, config, database and history, Telegram, `nav.js`, and `tools/`.

## Validation performed

**Automated:**
- `npm run build`: OK.
- `npm test`: **24 passed, 0 failed** (4 timefmt + 7 nav + 13 zones).
- `node --check` on every `app/static/*.js`: OK.
- Backend tests: not run, since the backend was untouched (per the prompt).

**The zone tests** use fictional fixtures only. They cover:
- bullish and bearish FVG, an exactly-one-tick gap, equal and sub-tick gaps, and 3-digit tick precision (0.001 with float error);
- FVG→IFVG on a close strictly below the bottom (wick-only and at-edge don't flip), activation at the flip, the IFVG's far-edge end, and no flip chain;
- bullish OB from the last bearish candle at the break, close-equal-to-pivot not breaking, a consumed pivot not re-breaking (a second break above it while below a newer pivot), no opposite candle meaning no OB, and the mirrored bearish OB;
- OB→BB on a strict close, the BB's far-edge end, and equality at the edges;
- gap, NaN, duplicate and forming bars; empty and null input;
- a **prefix property** on a 400-bar seeded random walk that exercises all 4 types: for every prefix, no zone activates after the last bar, origin ≤ activation, every full-history zone already active at the prefix exists with identical bounds, origin and parent, and its `end` matches (null if it ends later);
- determinism, unique IDs, and the display cap with active zones first.

**Browser** (Chrome, live dashboard, read-only GET API, no backend restart):
- **Setup:** the Chrome window is maximised at about 64% zoom, so I used same-origin iframes at exact CSS widths of **1536 and 390**, then **1026**. The browser's pre-test `vcSection=signals`, `darkMode=true` and `vcIndicators.v1` (absent) were restored at the end.
- **Live M5 load:** counts appeared and 40 zones were drawn. No page overflow at 1536, 390 or 1026 px; at 1026 the pills fit on one row.
- **First pass looked busy.** At this tick size (0.001), even 1-tick gaps qualify. Without changing the agreed definitions, I lowered fill opacity, ended active zones at the newest candle instead of the pane edge, and skipped overlapping labels. Both passes have screenshots.
- **Toggles:**
  - FVG off kept the identical visible logical range, saved the preference and left IFVG visible and computed;
  - OB off left BB visible and computed (23 BBs);
  - EMA20 on and off kept the viewport and the zones;
  - every toggle was restored.
- **Alignment:** zoomed to the last 45 candles. For example, the bearish OB activated at 04:00 [4143.115–4146.705] and the bearish FVG at 02:50 [4148.089–4152.445] start at their activation candles and sit on those prices.
- **Timeframes and history:**
  - switching to H1 gave a new key, with counts FVG 10 · IFVG 13 · OB 5 · BB 3;
  - older-history prepend on H1 (400 → 700 bars) moved the first time back, recomputed, and revealed more zones;
  - back to M5 recomputed again.
- **Setup row:** selecting setup #3 switched to Chart, loaded 600 M5 candles with the 4 price lines plus zones, and showed the setup status. Reset kept setup mode and the zones; Live returned to live with the lines cleared and zones recomputed.
- **Other:**
  - switching to Overview and back to Chart redrew the zones;
  - light theme picked up the light zone tokens (`#0f9f6e` / `#d92d4b`);
  - Expand fallback and close kept the Chart view and the zones;
  - the mobile "About zones" panel opened and wrapped with no overflow.
- **Console:** no console errors in the test tab.

**Runtime** (sanitized, read-only after testing):
- mode `mt5`, XAUUSDc, feed ok, scanner running and unpaused with no error;
- watermark unchanged at 2026-10-05T04:37:41Z;
- Telegram enabled with the persisted opt-in;
- 0 signals, outbox unchanged (3 earlier `sent` rows);
- no restart, toggle, setup submit, replay or message.

Screenshots in `.tmp/screenshots/`:
- `vc-zones-first-pass-dense-1536-390.jpg` (before the readability tuning)
- `vc-zones-dark-1536-390.jpg`
- `vc-zones-dark-1536-chart-pane.png`
- `vc-zones-dark-zoomed-alignment.png`
- `vc-zones-light-1536-390-help.jpg`
- `vc-zones-dark-1026.jpg`

## Checks not performed or limited

- **Sidebar collapse and drawer:** collapse was clicked in the 1536 frame, but its screenshot wasn't kept. The drawer flow is unchanged from the previous task. The zones are drawn per chart frame, so a resize only redraws them, as the 1026 frame showed.
- **Live polling over a new candle close:** not watched across a real M5 close in this session. The poll path calls `_updateZones()`, and the cache key includes the last bar's time and OHLC, so a new or revised closed bar triggers recomputation.
- **Real browser fullscreen:** not available (background window). The in-page Expand fallback was verified.
- **No pixel-level automated test of the drawing.** The rectangle coordinates come straight from `timeToCoordinate` / `priceToCoordinate`. Alignment was checked visually on zoomed screenshots and against the zone data.

## Limitations and notes

- **Dense zones on fine-tick symbols.** With the agreed "≥ 1 tick" FVG minimum, XAUUSDc (tick 0.001) produces many small FVGs and IFVGs. The display cap and quiet styling keep the chart readable, and each type can be toggled. A minimum-size filter (for example in ticks or ATR) would change the agreed definition, so it is left as an option for Codex and the user.
- **Gaps split patterns.** Contiguity is strict: market breaks and weekends split segments, so on H4 and D1 no pattern spans a weekend. This is conservative, as the prompt required ("not across missing candles").
- **Results depend on loaded history.** Zones depend on the history loaded on the chart; scrolling left can reveal older origins, as disclosed in README and the help text.

## Questions, missing requirements, or blockers

None.
