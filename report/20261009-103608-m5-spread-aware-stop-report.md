# Report: 20261009-103608-m5-spread-aware-stop

- Task ID: 20261009-103608-m5-spread-aware-stop
- Source prompt: `prompt/20261009-103608-m5-spread-aware-stop.md`
- Report path: `report/20261009-103608-m5-spread-aware-stop-report.md`
- Implementer: Claude
- Outcome: **IMPLEMENTED, isolated verification only.** Nothing was activated or restarted, and no orders, cancellations or Telegram messages were sent. Consent, risk and configuration are unchanged, and nothing was committed. The running app still runs the previous version (`@f4b7f7a5`) until a separately approved restart or activation.

## What changed (behaviour)

**M5 only (dual mode).** The common stop is the base stop, which sits 2 ticks beyond the far zone edge. If needed, it is moved **outward** by the fewest whole ticks so that every leg is at least spread + 1 tick from it:
- BUY: SL ≤ base SL and ≤ every entry − room, rounded down.
- SELL: SL ≥ base SL and ≥ every entry + room, rounded up.

**Unchanged:**
- entries (1/50/80 %);
- three legs;
- the $10 basket budget with equal thirds;
- lot flooring;
- minimum-lot refusal;
- the 0.50 maximum spread;
- broker distance checks;
- the existing spread-room rule, which is still applied to the final stop.

TPs are recomputed at 1:2 from the adjusted stop. A wider stop gives the same or fewer lots, and risk is never raised to reach the broker minimum.

**How the measured spread is handled:**
- Spread comes **only** from a valid fresh live quote: valid bid/ask, age ≤ `quote_max_age_seconds` (30 s).
  - A missing quote is rejected `no_quote_for_eligibility_check`, as before.
  - A stale or invalid quote is rejected `no_quote_for_eligibility_check: quote is Ns old` / `quote invalid`. No spread is ever invented.
- The spread is converted to whole ticks, **rounded up**. Float noise (0.48999999…) counts as 49 ticks, and a fractional spread (0.4905) counts as 50.
- Spread above the 0.50 maximum: no adjustment. The basket is still refused by the unchanged spread-room rule, with a note.

**M15 and legacy v1 are unchanged:** fixed 2-tick stop, and the same refusal at a wide spread (tested).

**One immutable plan:**
- The engine chooses `(sl, legs)` once and stores them on the basket, together with the stop provenance in `basket["stop"]`: `policy`, `base_sl`, `sl`, `spread`, `moved_ticks`, `quote_time`, `bid`, `ask`.
- The Telegram message and the Guide "actual levels" read the stored basket, so they show the same numbers.
- `executor.submit(..., levels=(sl, legs), stop=stop)` hands the same plan to sizing. `build_order_plan(levels=...)` passes it through the new `verified_levels()`, which recomputes entries and TPs from the gap and that stop at the broker's precision. It **refuses** the plan if:
  - any value differs;
  - the stop is off the tick grid, or non-finite;
  - the stop is inside the base stop.
- The journal payload records the same `stop` provenance.
- The plan is never rebuilt from a later quote. If the spread widens at the preflight or send boundary, the existing `_check_spread_room` refuses the whole basket before any send. Idempotency, unknown and partial handling are untouched.
- Legacy callers (no `levels`) behave exactly as before.

**Replay:** uses the same policy with the **assumed** `costs.spread`. The output now carries:
- `stop_policy`;
- `spread_note`: "no contemporaneous quotes: … assumed spread … (not historical spread validation)".

**Guide:**
- A basket record shows the stored adjusted stop plus a provenance line.
- An M5 setup without a basket shows the base-stop preview with a note: "the spread-aware stop depends on the live spread at the decision, which is not stored…". No adjusted stop is invented.

**Signals panel:** shows the same provenance line under the zone/SL line.

## Version / provenance / activation

- `DualFvgConfig.stop_policy = (("M15","fixed"),("M5","spread_aware"))` is a new config field and is part of the digest, so the versions change:
  - dual: `FVG-Dual-M15-M5-Immediate-v2-RR2@a2d893f0` (was `@f4b7f7a5`);
  - engines: `FVG-Immediate-M15-v2-RR2@a2d893f0` and `FVG-Immediate-M5-v2-RR2@a2d893f0`.
- **The M15 version string also changes, although M15 rules are identical.** The digest covers the whole dual config. Old records keep their `@f4b7f7a5` keys and are not rewritten or migrated.
- After activation, old-version setups without a basket show "recorded under another rule version; no preview" in the Guide (existing behaviour).
- `scopes()["stop_policy"]` and the dual `describe()` rules text describe the policy.
- **Consent implications:**
  - Execution bindings include the dual strategy version, so an explicit saved opt-in for `@f4b7f7a5` would no longer match.
  - None is currently recorded. Explicit dual-version consent was still not recorded at the start of this task.
  - The current ON state is the demo-category default (`default (demo account)`). It does not depend on the version, so on the MetaQuotes-Demo account automatic execution would stay ON after activation.
  - Nothing was migrated or changed.
- **Activation requirement:** one controlled launcher restart (`.venv/Scripts/python.exe -m app.launcher restart`) loads the new code and version. It was **not** done, because this task covers implementation and isolated testing only.

## Files changed

| File | Change |
|---|---|
| `app/fvg.py` | Split `basket_levels` into `base_stop` + `legs_for_stop` (identical results). Added `spread_ticks`, `spread_aware_stop`, `StopPlan`, `spread_aware_levels`, `fixed_levels`, and the `STOP_*` policy constants. |
| `app/fvg_dual.py` | `stop_policy` config field with validation and scopes text. M5 spread-aware decision with fresh-quote check (`quote_problem`). Basket `stop` provenance. Levels and stop passed to the executor. Replay uses the policy and labels the assumed spread. |
| `app/fvg_orders.py` | `build_order_plan(levels=...)` and `verified_levels()` (recompute and refuse on any mismatch). |
| `app/fvg_execution.py` | `submit(levels=, stop=)`; journal payload stores `stop`. |
| `app/fvg_guide.py`, `app/web.py` | Basket levels carry the stored `stop`; M5 preview limitation note (`stop_policy` passed in). |
| `app/active_strategy.py` | Dual rules text mentions the M5 stop policy. |
| `app/static/fvg-display.js` | `stopNote()` display helper (stored values only; never claims a move without the stored base stop and spread). |
| `app/static/fvg-guide.js`, `app/static/fvg-signals.js` | Show the provenance line / preview note. |
| `tests/test_fvg_spread_stop.py` | New: 29 tests. |
| `frontend/tests/fvg-stop.test.mjs` | New: 2 tests, registered in `frontend/package.json`. |

## Exact example levels (fixtures)

**Approved example**
- Setup: BUY zone 4172.68–4175.02, tick 0.01, recorded spread 0.49.
- Base SL 4172.66 fails: "leg 3 stop distance 0.48 is below spread 0.49 + 1 tick(s)".
- Adjusted plan: **SL 4172.64** (moved 2 ticks).

| Leg | Entry | TP | Distance to SL |
|---|---|---|---|
| 1 | 4174.99 | 4179.69 | 2.35 |
| 2 | 4173.85 | 4176.27 | 1.21 |
| 3 | 4173.14 | 4174.14 | 0.50 |

- Every TP = entry + 2 × its distance to the SL.
- With the adjusted SL, the spread-room check passes.

**Volumes**
- Basis: fictional fake broker with a 100-unit contract, $10 USD budget, step 0.01, minimum lot 0.01.
- Lots: **0.01 / 0.02 / 0.06**. Planned losses: 2.35 / 2.42 / 3.00, total **7.77 ≤ 10**.
- Broker requests price/sl/tp/volume match the stored plan exactly:
  - (4174.99, 4172.64, 4179.69, 0.01)
  - (4173.85, 4172.64, 4176.27, 0.02)
  - (4173.14, 4172.64, 4174.14, 0.06)
- With a minimum lot of 0.10, the plan is refused with "cannot fit the minimum lot".

**Mirror SELL** (same zone)
- Entries 4172.71 / 4173.85 / 4174.56; base SL 4175.04; **SL 4175.06** (+2 ticks).
- TPs 4168.01 / 4171.43 / 4173.56.

**Live M5 engine fixture**
- Setup: zone 116.60–117.80, quote spread 0.40.
- Base SL 116.58 → **SL 116.43** (15 ticks); entries 117.78 / 117.20 / 116.84; TPs 120.48 / 118.74 / 117.66.
- The queued message shows these exact levels.
- The same fixture under the previous fixed M5 policy is refused `stop_within_spread` (leg 3 distance 0.26).

## Checks performed (actual results)

**Focused new tests:** `.venv/Scripts/python.exe -m pytest tests/test_fvg_spread_stop.py --basetemp=.tmp/pt103608e` → **29 passed**. Coverage:
- exact BUY example;
- mirror SELL;
- no adjustment (including the equality case);
- fractional, float-noisy and 0.05-grid rounding;
- invalid spreads (NaN, inf, negative, bool, None);
- version and validation;
- live M5 adjustment with stored/message consistency;
- the fixed policy still refuses;
- M15 unchanged (refusal and fixed levels);
- stale, invalid and missing quotes;
- maximum-spread refusal;
- sizing and budget, and minimum-lot refusal;
- external-level verification (inside base, off-grid, NaN, mismatched TP);
- broker requests equal the stored plan, with idempotent restart and no resend;
- spread widening between preflight and send refuses with nothing sent and no journal row;
- the base-stop plan is still refused at the broker;
- live engine + fake executor: basket, journal and broker requests agree, and the journal `stop` equals the basket `stop`;
- replay label and policy;
- Guide stored stop and preview note.

Three of my own initial test expectations were wrong (a hand-computed SELL TP, an M15 setup selector, and a spread-widening fixture that exceeded the 0.50 maximum). I corrected them; the code itself did not change after that run.

**Other runs:**
- Existing FVG tests (`-k fvg`) after the core refactor: **180 passed**.
- Full backend suite with fresh basetemp `.tmp/pt103608full`: **393 passed** (364 previous + 29 new), 1 warning (starlette/httpx deprecation). This was a single run. The intermittent `tests/test_mt5_time.py::...[2]/[3]` failures reported earlier did not occur in it; their cause is still unknown.
- Frontend: `npm run build` → exit 0; `npm test` → **64 passed, 0 failed**.

## Checks not performed

- No browser or visual check of the new provenance lines. They are plain text lines rendered with existing classes, and the content is covered by the Node tests.
- No live, runtime or MT5 check: restart and activation are out of scope. Nothing ran against the real terminal, live store or Telegram.

## Questions / notes for Codex

1. The M15 engine version string changes (`@a2d893f0`) because the digest covers the whole dual config, even though M15 behaviour is identical. Is that acceptable, or should engine versions use per-engine digests?
2. With the spread above the 0.50 maximum, M5 does not adjust and is refused by the unchanged spread-room rule. The rejection reason keeps the existing `stop_within_spread` key, and a note is recorded only when a basket is created.
3. Activation (restart) and any explicit consent for the new version need a separately approved step.
