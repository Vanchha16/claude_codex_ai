# Report: 20261009-110034-m15-spread-aware-stop

- Task ID: 20261009-110034-m15-spread-aware-stop
- Source prompt: `prompt/20261009-110034-m15-spread-aware-stop.md`
- Report path: `report/20261009-110034-m15-spread-aware-stop-report.md`
- Implementer: Claude
- Outcome: **IMPLEMENTED, isolated verification only.**
  - Both dual engines now default to the existing spread-aware common-stop policy.
  - Nothing was restarted or activated: the running app stays on `@a2d893f0` (M5 spread-aware, M15 fixed) until a separately approved activation.
  - No orders, Telegram messages, consent, risk or config changes, commits or pushes.

## Changes (narrow; reuses the generic policy, plan and executor path)

- **`app/fvg_dual.py`**
  - `DualFvgConfig.stop_policy` default is now `(("M15","spread_aware"),("M5","spread_aware"))`. `STOP_FIXED` is still accepted per engine for comparison or rollback.
  - The module docstring states that both engines use the spread-aware policy.
  - The scope text now names the base: "spread-aware: 2 ticks beyond the far edge, moved further outward by whole ticks when needed so every leg is >= spread + 1 tick from it".
  - There is no M15-specific calculation or sender. The same `_decide` → `spread_aware_levels` → `submit(levels=, stop=)` path is used, with the same quote-freshness, maximum-spread, verified-levels and send-boundary checks.
- **`app/active_strategy.py`:** the dual rules text lists the spread-aware engines from the config. It now reads "(M15/M5: moved further outward when needed …)".
- **`app/fvg_guide.py`:** comment only. The preview limitation note already applies per engine via `stop_policy`, so M15 previews now carry it too.
- **`app/static/fvg-guide.js`:**
  - New `stopRule()`: the dual "Orders" rule now shows the server's per-engine stop-policy text instead of a hard-coded "2 ticks". It falls back to that text for an older server.
  - `stopRule` is exported for tests.
- **Tests:**
  - `tests/test_fvg_spread_stop.py`: 36 tests (was 29); M15 cases added and the version and policy assertions updated.
  - `frontend/tests/fvg-stop.test.mjs`: one Guide stop-rule test added.
- Legacy v1 is unchanged (fixed stop), and historical records are untouched.

## Versions / activation implications

- **New expected versions:**
  - dual `FVG-Dual-M15-M5-Immediate-v2-RR2@dc9ff475`;
  - engines `FVG-Immediate-M15-v2-RR2@dc9ff475` and `FVG-Immediate-M5-v2-RR2@dc9ff475`.
- **Previous versions:** `@a2d893f0`, currently running. The comparison config `M5_ONLY` reproduces `@a2d893f0` exactly in the tests.
- Both labels change; M5's numbers do not (tested).
- **Activation** needs a separately approved controlled restart, `.venv/Scripts/python.exe -m app.launcher restart`.
- **Consent:** explicit consent is version-bound and none exists for `@dc9ff475`. On the demo account, execution remains ON through the demo-account default, as in the M5 activation. Nothing was migrated.

## M15 fixture examples (fictional, isolated stores)

**BUY**
- Setup: M15 BUY zone 116.60–117.80, quote spread 0.40.
- The fixed stop is refused: base SL 116.58, "leg 3 stop distance 0.26".
- New policy: **SL 116.43** (moved 15 ticks; leg 3 is 0.41 = spread + 1 tick from the SL).
- Entries 117.78 / 117.20 / 116.84 (unchanged); TPs **120.48 / 118.74 / 117.66** (1:2).

**SELL** (price-mirrored scenario)
- Setup: zone 122.20–123.40.
- Base SL 123.42 → **SL 123.57** (15 ticks).
- Entries 122.22 / 122.80 / 123.16; TPs **119.52 / 121.26 / 122.34**.

**Spread 0.20:** the M15 base stop already passes, so it is not moved (SL 116.58, moved 0, policy spread_aware).

**Fake-executor M15 flow** (spread 0.40):
- These all agree exactly: the stored basket, the Telegram message text, the Guide actual levels (including volumes), the journal legs, and the broker requests (price/sl/tp; comments `FVG15-<plan>-L1..3`).
- The journal `stop` equals the basket `stop`, and planned loss ≤ $10.
- A repeat run on the same C sends nothing.

## Validation (actual)

- `tests/test_fvg_spread_stop.py`: **36 passed**. New coverage:
  - M15 BUY/SELL admitted with the minimum move and M15 provenance;
  - M15 base stop that already passes does not move;
  - explicit fixed-M15 regression (both `M5_ONLY` and all-fixed configs) keeps the previous refusal and the fixed levels;
  - M5 numbers identical under the new default vs `@a2d893f0`;
  - wide spread on both engines gives two separate baskets, messages and slots;
  - the M15 fake-executor agreement test;
  - M15 Guide preview note present, and absent for a fixed-policy engine.
- Focused regressions (stop policy, dual, execution, Guide, Guide-exact, signals, sizing): **130 passed**.
- **Full backend suite** (fresh basetemp `.tmp/pt110034full`): **398 passed, 2 failed.**
  - Failures: the known intermittent `tests/test_mt5_time.py::test_verified_server_offset_normalises_quotes_bars_and_ranges_exactly_once[2]` and `[3]`.
  - Assertion: `bars[-1].open_time` was 04:00 where 03:55 was expected (`tests/test_mt5_time.py:95`).
  - The run happened around the real 04:00 UTC boundary. This suggests the fake feed's bar window depends on the wall clock rather than the test's fixed `NOW`. That is an unverified hypothesis.
  - The failures are unrelated to this change (no time/feed code touched). Per the prompt, I did not rerun to get a green result.
- Frontend: `npm run build` exit 0; `npm test` **65 passed, 0 failed**.

## Not performed

- No browser visual check of the Guide rules or provenance text; the content is covered by the Node tests.
- No live restart or activation (out of scope).

## Questions / blockers

- None blocking.
- Possible follow-up: investigate the clock dependence of `test_mt5_time` (it recurs).
