# Claude report: independent M15 and M5 FVG order engines

Task ID: 20261008-143801-dual-timeframe-fvg-engines
Source prompt: `prompt/20261008-143801-dual-timeframe-fvg-engines.md`
Status: completed. The dual mode is implemented, validated and ACTIVE on the configured XAUUSD demo account. One open item: the new explicit consent record for the dual version has not been recorded (see "Activation and consent").
Reported at: 2026-10-08 ~08:21Z (the user asked to report now)

## Outcome

Two independent FVG engines (M15 and M5) now run together in one scanner pass. Each engine:
- detects A/B/C on its OWN closed candles of its timeframe;
- qualifies on its OWN contiguous history (warm-up, EMA, ATR and data-gap resets per timeframe);
- places three pending limits immediately when its own C closes with a qualifying gap. There is no retest or confirmation stage.

A shared admission rule decides whether a basket can be placed:
- one open or unresolved basket per engine;
- a 30-minute cooldown per engine;
- at most 4 accepted baskets per Bangkok date in TOTAL across both engines;
- when both engines decide at the same timestamp, M15 is decided before M5;
- $10 planned risk per basket, so at most $20 concurrently.

Legacy FVG-Trend-M15-M5-v1 remains selectable (`fvg`/`rr2`) as a rollback. Its baskets keep their recorded rules and occupy the M15 slot.

## Rules and config defaults (as implemented)

- **Mode and versions:** mode `fvg`/`dual` → `FVG-Dual-M15-M5-Immediate-v2-RR2@f4b7f7a5`. The engine versions are `FVG-Immediate-M15-v2-RR2@f4b7f7a5` and `FVG-Immediate-M5-v2-RR2@f4b7f7a5`. The digest covers the shared rule parameters and the scope settings.
- **Detection and qualification:** each engine runs the existing `app.fvg.detect_gap` and `app.fvg.qualify`, now timeframe-aware (defaults unchanged for v1). The rules are:
  - EMA20/EMA50 trend over at least 50 contiguous candles of that timeframe;
  - ATR14 through B;
  - gap ≥ max(2 ticks, 0.10 ATR);
  - B body ≥ 1.0 ATR;
  - trend in the gap direction; equal EMAs allow neither direction.
- **Decision timing:**
  - C must close strictly after the session watermark, otherwise the record is rejected with `c_before_session_watermark`.
  - C must be ≤ 30 s old at the decision, otherwise `decision_too_old`. The executor re-checks this freshness at every send.
  - Each C is recorded once through an `INSERT OR IGNORE` key, so polls and restarts never re-decide or resend it.
- **Levels and risk:**
  - Entries at 1/50/80 % depth of the originating zone, common SL 2 ticks beyond the far edge, and a 1:2 TP per leg, all via the existing `basket_levels`. Exact rounding and sizing are reused.
  - Spread, placement, minimum-lot and preflight failures reject the whole basket.
  - Risk is the `config/fvg_risk.json` budget ($10) PER BASKET, split into thirds before lot flooring.
- **Capacity:**
  - A basket occupies its engine's slot while it is pending, sending, unknown, partial or has filled exposure. A deadline alone never frees the slot.
  - Unknown risk is counted as a full budget, never zero.
  - An open legacy v1 basket occupies the M15 slot.
- **Pending expiry and invalidation:**
  - Pending legs expire 120 min after placement.
  - Candle-close invalidation uses the originating timeframe: M15 baskets only on complete M15 closes, M5 baskets on M5 closes. Wicks and the other engine's closes never count.
  - Only that basket's owned pending remainder is removed; filled positions are kept.
- **Broker:**
  - Leg comments are `FVG15-<plan>-Ln` / `FVG5-<plan>-Ln`, and basket IDs `FVG15-…` / `FVG5-…`.
  - The executor's "no existing exposure on the symbol" preflight now allows ONLY the MAGIC-owned orders and positions of the other still-open basket(s), matched by comment prefix. Anything else on the symbol still blocks.
  - Legacy calls pass no prefixes and behave exactly as before.
  - These are unchanged: send-boundary account/clock checks, the original-account ownership checks, reconciliation, verified cancellation, and the unknown/partial never-resend rule.

## Files changed

Nothing is committed or pushed. The Guide task's uncommitted files from the previous report are still present and were extended.

- **`app/fvg_dual.py` (new):**
  - `DualFvgConfig` (scopes and versions);
  - pure `evaluate_c`, `admission`/`Occupancy`, `readiness` and `closes_beyond`;
  - `DualFvgLiveEngine`, which subclasses `FvgLiveEngine` and inherits reconcile, cancel retries, restart recovery and other-account handling for every FVG basket of the symbol;
  - `replay_dual`, which uses the same rules and the live scanner's 600-M5 window, and labels its results as simulation.
- **`app/fvg.py`:** `detect_gap`, `contiguous_run` and `qualify` are timeframe-aware (default M15).
- **`app/fvg_execution.py`:**
  - engine-tagged `leg_comment` and new `comment_prefix`;
  - `submit(comment_tag, allowed_prefixes, engine)`;
  - the `_foreign` exposure filter;
  - the journal stores `comment_prefix` and `engine`;
  - `ExecutionOptIn.arm(…, approval=)` records an optional approval note.
- **`app/fvg_live.py`:** `FvgStore.open_setups` and `setups_for_version` (read helpers).
- **`app/fvg_replay.py`:** `_step_basket(…, invalidate=True)`. The default behaviour is unchanged.
- **`app/active_strategy.py`:** the `fvg`/`dual` profile, `is_fvg_dual`, `fvg_version` and the dual description.
- **`app/scanner.py`:**
  - builds `DualFvgLiveEngine` for dual mode;
  - closes out waiting v1 setups as `retired_strategy_switch_to_dual`, so they are never reinterpreted;
  - reports the dual state.
- **`app/web.py`:**
  - consent binding to `fvg_version`;
  - dual status (engines, slots, daily total, $20 concurrent), the trading text and the approval note;
  - `/api/fvg` setups carry the engine;
  - Guide endpoints serve the dual path, with legacy records and lessons labelled.
- **`app/delivery.py`:** dual Telegram messages get a first line such as "M5 FVG · BUY · 3 pending limits". The legacy format is unchanged.
- **`app/fvg_guide.py`:**
  - shared `execution_steps`, which keeps the truthful accepted/unknown/partial counts from the Guide review;
  - `dual_steps`, `dual_record_view`, and dual reason texts;
  - five deterministic fictional dual lessons plus a broker-states example.
- **`app/static/fvg-guide.js`:** dual record view, multiple zones per chart, A/B/C on M5, dual and broker-state lessons, and dual rules with the legacy rules labelled.
- **`app/static/app.js`:** an engines table in the FVG card, per-basket risk text, a dual description, and an engine label on each basket row.
- **`frontend/src/index.template.html` and `frontend/src/input.css`**, plus the generated `index.html` and `app.css`: the engines table, neutral Guide copy, and the M5 zone style.
- **`config/active_strategy.json`:** now `{"strategy": "fvg", "profile": "dual"}`, set by the user. The previous content is saved at `.tmp/active_strategy.before-dual.json`.
- **Tests:** `tests/test_fvg_dual.py` (new, 27 tests), an updated lesson assertion in `tests/test_fvg_guide.py`, and a new chart test in `frontend/tests/fvg-guide.test.mjs`.

## Validation performed

- **Backend focused:** `pytest tests/test_fvg_dual.py` gives **27 passed**. The tests cover:
  - own-timeframe detection;
  - independent readiness (M5 ready while M15 warms up);
  - an M5 data gap resetting only M5;
  - immediate M5 and M15 baskets at C, with no retest or confirmation;
  - old and pre-watermark C recorded but never ordered;
  - each C decided once across polls and restarts;
  - an M15 and an M5 basket coexisting;
  - one slot per engine;
  - per-engine cooldown;
  - the shared daily total with M15 winning the last slot;
  - unknown or larger legacy risk not treated as zero;
  - a legacy v1 basket occupying the M15 slot;
  - partial, unknown and sending outcomes keeping their slot;
  - M15 baskets ignoring M5 closes and being invalidated on the M15 close, and M5 baskets on their M5 close;
  - the executor allowing only the other engine's own exposure;
  - two live baskets sending six engine-tagged legs at $10 each;
  - an unknown send never resent;
  - replay decisions matching live decisions;
  - legacy v1 still selectable, with waiting v1 setups retired;
  - dual Guide views and lessons;
  - read-only Guide and lesson endpoints in dual mode.
- **Backend full:** with a fresh in-project basetemp, the final runs gave **360 passed**. In one intermediate run, two tests failed intermittently. One was the previously reported `tests/test_mt5_time.py::test_verified_server_offset_normalises_quotes_bars_and_ranges_exactly_once[2]`, so it has **recurred**. The other's name was not captured. The next runs passed in full. Four repeat runs meant to capture the failure were stopped by Claude Code for low system memory and left no output, and they were not restarted.
- **Frontend:** `npm.cmd test` gives **43 passed**, `npm.cmd run build` succeeds, and `node --check` passes on `fvg-guide.js` and `app.js`.
- **Visual:** checked on an isolated **dual DEMO** instance on port 8013, with temp state, the fictional fixture, no MT5 and no Telegram token. It is now stopped. Screenshots are in `.tmp/fvg-dual-screens/`.
  - Overview summary: "M15: warm-up 22/50; M5: waiting …", baskets today 0/4 total.
  - System card: the engines table and "$10 per basket · up to $20 at once".
  - Guide live dual M15 record: steps detected → qualified (failed: trend warm-up) → eligibility → limits → fills, with the "no retest/confirmation window" text.
  - All seven dual lessons, checked through the DOM: M15 basket with later TP fill; M5 ready while M15 warms up; M15+M5 same direction; M15 BUY open plus M5 SELL basket; rejected for the stop inside the spread; broker states pending/filled/unknown/partial.
  - 390 px light theme: no page overflow; the chart scrolls inside its own frame.
  - No console errors after a clean reload and stepping through every lesson.
- **Activation:** a read-only runtime check at 2026-10-08 08:20:50Z found:
  - Strategy: `FVG-Dual-M15-M5-Immediate-v2-RR2@f4b7f7a5`.
  - Account and data: MetaQuotes-Demo (**demo** account), XAUUSD; feed connected, quote fresh; scanner running with no error.
  - Engines:
    - M15: warm-up 41/50, so it can't qualify yet.
    - M5: ready, trend down, SELL gaps allowed.
  - Automatic execution: **ON**, $10 per basket, $20 at most concurrently; Telegram ON.
  - Trading state: daily 0/4 total; **0 baskets**; no dual setups recorded yet in this session.
  - Server log: no errors since the restart.

## Activation and consent

- On 2026-10-08, my own activation step (select dual, restart, record consent) was denied by Claude Code's permission classifier, and a following read-only check was also denied. I did not retry or work around either.
- The user then ran the two commands: `.venv\Scripts\python.exe -m app.active_strategy fvg dual` → "saved: fvg profile dual", and `.\gold.cmd restart` → new PID 25192. This was a normal launcher restart: no MT5 login, initialize or account switch.
- **Consent record: NOT yet recorded for the dual version.**
  - Automatic execution is ON with `armed_by = "default (demo account)"`, through the user's existing `config/fvg_execution.json` demo-account default (2026-10-07). The saved explicit opt-in is still bound to the v1 version `FVG-Trend-M15-M5-v1-RR2@8a49bace`, so it correctly does NOT match the dual version. Nothing was inherited silently.
  - The user was asked to click "Turn automatic execution ON" (System view, confirmation tick) to record the explicit dual-version binding. As of 08:20:50Z that hadn't happened (`armed_at` is None).
  - Natural qualifying gaps can create real demo orders now, under the demo default.
- **Rollback:** `.venv\Scripts\python.exe -m app.active_strategy fvg rr2` then `gold.cmd restart`. The v1 version and its saved opt-in binding are unchanged. Storage changes are additive (same tables, new fields), and journals are untouched.

## Checks not performed

- No real broker order, removal or Telegram message was produced for testing. Live submission was exercised only with the fake MT5 broker in tests.
- The live dashboard after activation was checked only through the API, not with screenshots.
- No screen-reader pass was done.
- I could not identify the cause of the intermittent full-suite failures (one recurring in `test_mt5_time.py`, one unnamed).

## Questions, missing requirements, or blockers

1. **Dual-version consent.** Should the user's demo-account default stand as consent, or must the explicit dual-version arming be recorded? The user was asked to click it. The approval note can be recorded with `POST /api/fvg/execution {"enabled": true, "confirm": true, "approval": "<text>"}`.
2. **The intermittent `test_mt5_time` failure recurred.** Should a separate task investigate it?

## Suggested next step

Codex reviews the dual engine (`app/fvg_dual.py` admission and invalidation, and the executor's `allowed_prefixes` exposure rule) and confirms the consent decision with the user.
