# Codex review: FVG / IFVG / OB / BB chart overlays

Task ID: 20261005-114227-smc-chart-overlays
Source prompt: prompt/20261005-114227-smc-chart-overlays.md
Claude report: report/20261005-114227-smc-chart-overlays-report.md
Reviewed: 2026-10-05
Outcome: accepted within the chart-only scope.

Independent code review:
- Pure closed-OHLC detector with tick-size precision, two-sided pivot confirmation, close-based inversions, stable provenance and forming/invalid/gap handling.
- Lightweight Charts series primitive draws zones on chart coordinates below candles; no input interception. Independent IFVG/BB rendering does not depend on FVG/OB being visible.
- Price/time rectangles are anchored to the activation candle's chart timestamp (candle open); detector also records available=activation+timeframe for the actual closing availability. They are generated only after the candle closes. This chart convention is documented in help/report.
- Detection cap applies only to drawing, not the full loaded-history calculation. New preferences are allowlisted/versioned; default all four new types on.
- Backend strategy and Telegram changes were outside scope and were not made.

Independent tests:
- 13 zone-detector tests passed; then complete frontend npm.cmd test passed 24 tests, including navigation/time formatting. No backend tests rerun for this frontend-only change.

Independent top-level browser check at 1920 x 945 CSS px:
- Fresh full navigation loaded delivered assets, Chart alone visible, all four overlay toggles enabled.
- 400 closed M5 bars, 40 drawn zones; active FVG 14 / IFVG 12 / OB 6 / BB 2 at initial check.
- Real label clicks turned FVG and OB off independently, left IFVG and BB on, and preserved logical visible range exactly (169 to 406). Preferences reflected the clicks and were restored afterwards.
- No horizontal page overflow; console errors and warnings both zero.
- Watched the actual 05:00 UTC M5 boundary: chart advanced from 400 to 401 closed bars, latest closed time 1791176100, forming time 1791176400; zone cache key changed and IFVG active count became 13. This verifies the live candle-close update that Claude had not watched.
- Saved and visually inspected .tmp/screenshots/codex-smc-chart-review.png; also viewed Claude's zoomed dark chart and light desktop/mobile help screenshots.
- Restored original /#chart-section URL and removed the indicator preference created by our test (it was absent before review). Theme and original section were not changed.

Claude's attributed checks: build, JavaScript syntax, exact-width iframe desktop/mobile/laptop layouts, H1/M5 switches, older-history prepend, selected setup overlays, Reset/Live, theme, hidden view reveal, and expanded-chart fallback. Native fullscreen unavailable; exact native window sizes were not used. No automated pixel-level renderer test. Many small zones qualify at a one-tick minimum; users can control each type and the display is capped.

Independent read-only runtime check after review: MT5/XAUUSDc healthy with fresh quotes, scanner active/no error and Telegram enabled. No backend restart or live state mutation by Codex; no signal/message created for validation. Codex made no application edits.
