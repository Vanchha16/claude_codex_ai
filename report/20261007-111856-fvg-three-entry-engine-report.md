# Claude report: FVG trend-pullback engine with three staged entries

Task ID: 20261007-111856-fvg-three-entry-engine
Source prompt: `prompt/20261007-111856-fvg-three-entry-engine.md`
Informational review read: `prompt/20261007-111856-fvg-three-entry-engine-codex-review-notes.md` (all 6 observations addressed, see section 4)
Progress receipt: `report/20261007-111856-fvg-three-entry-engine-progress.md`
Date: 2026-10-07

## 1. Outcome

The FVG-Trend-M15-M5-v1 (RR2) build is implemented and integrated, but it is **inactive**, with automatic execution **OFF**:

- Rules, replay and live engine share one rule set.
- The execution adapter has an account-bound opt-in that defaults to OFF.
- Reconciliation and cancellation, scanner wiring, API, dashboard, README and tests are done.

Safety statements, explicitly:

- **No real orders.** No `order_send`, `order_check` or broker request of any kind was made against MT5. All execution tests use a fake broker. The only touch of the installed `MetaTrader5` package was a read-only import and introspection of exported constants: no `initialize`, no login, no account read.
- **No messages.** No Telegram or test message was sent. Delivery tests use `httpx.MockTransport`.
- **No activation and no restart.**
  - `config/active_strategy.json` is still `{"strategy": "fastsweep", "profile": "rr2"}`.
  - The live backend was not restarted, and the scanner, Telegram, mode and symbol were not toggled.
  - No execution opt-in file was created; arming was never called against a live workstation.
- **Fixed $10 combined risk is configured only for the inactive FVG build.**
  - `config/fvg_risk.json` holds `risk_usd_per_setup: 10.0`. That is a preference only and does not arm anything.
  - Execution stays disabled. The `ExecutionPolicy()` default is `enabled=False, risk_usd=None`.
  - Arming is refused while FVG is not the active strategy on live MT5.

## 2. Files changed and resulting behaviour

| File | Change |
|---|---|
| `app/fvg.py` | **Rules.** <ul><li>Gap detection; qualification (max(2 ticks, 0.1·ATR14) gap, B body ≥ 1·ATR14 with Wilder ATR through B, EMA20/50 over ≥ 50 contiguous M15 candles ending at C).</li><li>Setup state machine: first touch is the retest, a different bar among the next 3 confirms, 2 h lifetime, continuity.</li><li>A close beyond the far edge invalidates **before or at the first touch and after the retest** (review #1).</li><li>`entry_ladder` and `basket_levels` (1/50/80 %, common SL 2 ticks beyond the far edge, 1:2 TP per leg) now use exact Decimal arithmetic. Float noise had moved 117.2 → 117.19 and 118.44 → 118.45.</li></ul> |
| `app/fvg_orders.py` | Fixed USD budget → account cash (USD ×1, USC ×100, other currencies refused). Equal ⅓ shares; lots = share ÷ loss-per-lot, floored to the step. Any leg below the minimum lot rejects the whole plan; nothing is redistributed. |
| `app/fvg_execution.py` | **The only module that builds broker requests.** <ul><li>`ExecutionPolicy` defaults to OFF. `ExecutionOptIn` binds source, symbol, sha256 of the login, and strategy version.</li><li>Pre-checks: terminal/account trading flags, hedging, full trade mode, fresh quote, spread, no exposure, distances, `order_check`, margin. They are re-validated on a refreshed quote before the first send.</li><li>A durable journal row is written before any send. An unknown result is never resent and the remaining legs are left `not_sent`; a definite partial batch is reported as partial.</li><li>**Pending orders now use `ORDER_FILLING_RETURN`** (review #2).</li><li>**Reconciliation reworked** (review #4): partially filled with the remainder still resting → `partially_filled` (with `filled_volume` and `pending_volume`). Partial fill with the remainder expired or cancelled → `filled_open` + `remainder`. Closure is decided from positions and OUT/OUT_BY deals. `broker_pnl` sums **all** deals of the position(s), so entry-side commission and fees are included. Mixed exit reasons → `closed_other`.</li><li>`cancel_remaining` also removes the resting remainder of a partially filled leg; the filled part stays open with its broker SL/TP.</li></ul> |
| `app/fvg_live.py` | **Live engine.** <ul><li>Confirmation gates: watermark (strictly after), one open basket, 30 min cooldown, 4 per Bangkok date (all from persisted baskets).</li><li>Alert, then automatic submit only if the executor is ON. Status mapping goes through `EXEC_STATUS`.</li><li>**Crash recovery across both stores** (review #3): a `planned` basket counts as open (blocks new baskets). On reconcile it adopts the journal: `submitting` → `needs_reconciliation`, after which its owned orders are reconciled. With no journal row it becomes `interrupted_unsubmitted`. It is never resubmitted.</li><li>The far-edge cancel now considers the first bar that closes after placement (previously that bar was skipped).</li></ul> |
| `app/fvg_replay.py` | OHLC replay: BUY fills on Ask, SELL on Bid. A TP in the fill bar, or TP and SL in one bar, is ambiguous; the conservative view counts those legs as stops. Also covers expiry, far-edge cancel, capacity, the 70/30 split, the daily table and frequency. CLI `--bars/--spread/--slippage/--out` (default `.tmp/fvg`). |
| `app/active_strategy.py` | `fvg rr2` is selectable. It was **not selected**. |
| `app/scanner.py` | FVG engine wiring: M5 window 600; reconciliation runs every scan, even while paused. |
| `app/delivery.py` | `format_fvg_basket` (3 blocks × 4 emoji lines); `on_fvg_basket` uses the existing opt-in/outbox, dedup by basket id. |
| `app/web.py` | <ul><li>`_mt5_lock()`: **every** FVG MT5 call (executor, maintenance, status, arm) uses the connected feed's own `feed._lock`, the same lock chart/REST feed reads take (review #5).</li><li>`trading_status()`: `/api/state.trading` is now truthful (review #6). CRT/FastSweep: "disabled: … alert-only … no orders are sent; FVG … not the active strategy". FVG off: "disabled: FVG automatic execution is OFF (reason) …". FVG armed: "ENABLED: FVG automatic execution is ON – … 3 pending limit orders (fixed 10.0 USD …)". When not the owner: "disabled: this process is not the owner and never sends orders".</li><li>`GET /api/fvg`; `POST /api/fvg/execution` (enabling needs `confirm: true`, FVG active, live MT5, risk configured, supported currency, hedging).</li><li>Replay artifacts are read from and written to `ws.state_dir/replays` (test isolation fix).</li></ul> |
| `config/fvg_risk.json` | New. `risk_usd_per_setup: 10.0` with a comment that it does not arm or activate anything. |
| `frontend/src/index.template.html`, `app/static/app.js` → built `app/static/index.html`, `app/static/dist/app.css` | **System → "FVG automatic execution" card.** <ul><li>Shows ON/OFF, strategy active/inactive, status reason, the $10 budget, the $3.33 per-leg share, and % of equity (live account only).</li><li>Arm button: disabled unless FVG is active on MT5 with risk configured **and** an explicit "I understand…" checkbox is ticked. Turn OFF button.</li><li>Baskets table (only when FVG is active): entry, TP, lots, planned loss and state per leg.</li><li>Footer no longer claims the app never trades; it scopes the claim to CRT/FastSweep.</li></ul> |
| `README.md` | Replaced the blanket "It never trades" with the scoped statement. Added a "FVG-Trend-M15-M5-v1 (opt-in automatic execution, default OFF, not active)" section (rules, basket, risk, switch, safety, replay results) and a layout row for `config/fvg_risk.json`. |
| `tests/test_fvg.py`, `tests/test_fvg_execution.py` | Fake broker mirrors the installed exports. New tests: RETURN filling, partial fill with resting remainder → cancel keeps the position, partial fill with expired remainder → closed P&L including entry commission. |
| `tests/test_fvg_engine.py` (new, 26 tests) | <ul><li>Rules: ATR through B, warm-up, retest/confirm, far-edge before touch for BUY and SELL, continuity, lifetime, levels.</li><li>Replay: fill/TP, ambiguity, SL, expiry, cancel, conservative view, daily table.</li><li>Live engine with a fake broker: exactly 3 automatic requests at $10, OFF → zero requests, watermark/historical, restart dedup, cooldown/cap/open basket from persisted baskets, far-edge cancel of owned legs only, crash after sends and crash before sends.</li><li>Outbox dedup and the 3×4-line format.</li><li>Scanner integration: live confirmation submits once; a scanner started after the confirmation submits nothing.</li><li>API: inactive status and arming refused, truthful `trading` string, replay-artifact isolation, shared MT5 lock.</li></ul> |
| `tests/test_scanner.py` | `test_no_trade_execution_code_anywhere` replaced by two scoped tests: <ul><li>`order_send/order_check/positions_close/TRADE_ACTION` appear only in `app/fvg_execution.py`, and its default policy is disabled.</li><li>CRT/FastSweep/feed/replay/delivery modules never import the executor.</li></ul> |

## 3. Checks actually performed

- **Full backend suite:** `pytest -p no:cacheprovider --basetemp=.tmp/pytest-final2-<ts> --junitxml=…` → **233 tests, 0 failures, 0 errors, 0 skipped** (exit 0). This includes `test_fastsweep_live::test_api_reports_the_active_strategy_and_per_record_identity`, which now passes because replay paths use the test workstation's state dir.
- **Focused run:** `tests/test_fvg.py tests/test_fvg_execution.py tests/test_fvg_engine.py tests/test_scanner.py tests/test_delivery.py tests/test_api.py tests/test_fastsweep_live.py` → **126 tests, 0 failures**.
- **Frontend:**
  - `node --check app/static/app.js`: OK.
  - `npm run build` (tailwind + copy-assets): OK.
  - `npm test`: **28/28 pass**.
- **MT5 export introspection** (read-only import, no initialize):
  - `ORDER_FILLING_RETURN=2`, `ORDER_FILLING_FOK=0`, `ORDER_FILLING_IOC=1`.
  - `DEAL_ENTRY_IN/OUT/INOUT/OUT_BY = 0/1/2/3`.
  - `ORDER_STATE_PARTIAL=3`, `ORDER_STATE_FILLED=4`.
  - `SYMBOL_ORDER_LIMIT` and `SYMBOL_EXPIRATION_SPECIFIED` are not exported, so the documented values 2 and 4 are used (asserted in tests).
- **Cleanup:** only the basetemp directories I created this session were removed, after checking they resolve inside `.tmp/`. Codex's `pytest-codex-*` directories and the earlier `pytest-fvg-handoff-review-20261007` / `pytest-fvg-orders-20261007` directories were left alone. The saved live replays in `.tmp/gold-signals/replays/` are untouched.

## 4. Codex review observations: status

1. **Far-edge before the first touch.** Fixed in `advance_setup`. Tested for BUY and SELL; a candle beyond the near edge stays `pending`.
2. **`ORDER_FILLING_RETURN` for pending orders.** Fixed. FOK/IOC selection was removed, along with the `SYMBOL_FILLING_*` doc constants. Tested against both the fake broker and the installed package constant.
3. **Basket and journal crash window.** Fixed with an integration test: the engine raises a non-Exception "process exit" after `submit` has sent 3 orders. A new engine's `reconcile` adopts the journal → `orders_pending` with 3 owned pending legs, and re-driving all bars sends nothing more. A crash before any send → `interrupted_unsubmitted`, zero requests.
4. **Partial fills and full P&L.** Fixed and tested (see `fvg_execution.py` above).
5. **One MT5 lock.** The executor, maintenance, status and arm paths use `feed._lock`, the feed's RLock that all `MT5Feed` methods and chart reads take. Lock order is always the scanner lock, then the feed lock; nothing takes them in reverse. Unit-tested via `Workstation._mt5_lock`.
6. **Truthful `trading` status.** Fixed in both `/api/state` responses and tested (inactive, FVG off, FVG armed).

## 5. Replay (simulation on cached broker history; no tuning)

Commands:
```
.venv/Scripts/python.exe -m app.fvg_replay --bars .tmp/fastsweep/bars-m5-20260806T0700-20261005T0655.json --spread 0.20 --slippage 0.05
.venv/Scripts/python.exe -m app.fvg_replay --bars .tmp/fastsweep/bars-m5-20260806T0700-20261005T0655.json --spread 0.40 --slippage 0.10
```
Raw results:
- `.tmp/fvg/FVG-Trend-M15-M5-v1-RR2-spread0.2-slip0.05.json`
- `.tmp/fvg/FVG-Trend-M15-M5-v1-RR2-spread0.4-slip0.1.json`

Version: `FVG-Trend-M15-M5-v1-RR2@52de46c0`.

**Coverage.** 2026-08-06T07:00Z → 2026-10-05T06:55Z. That is 11,560 M5 bars and 3,852 M15 bars, with 42 M5 gaps. There are 61 calendar dates, 52 with data and 41 covered for at least 12 h (Bangkok dates). This sample was explored before; it is not untouched validation.

**Funnel (baseline).**

| Stage | Count |
|---|---|
| Raw gaps | 799 |
| Qualified | 59 |
| Retests | 38 |
| Confirmations | 16 |
| Baskets | 16 (no capacity rejections) |

Setup outcomes: trend_warmup 443, trend_against 157, weak_displacement 98, gap_too_small 42, setup_lifetime_elapsed 17, no_confirmation_after_retest 14, close_beyond_far_edge 7, m5_continuity_lost 5, confirmed 16.

**Legs (baseline 0.20/0.05).**

- 48 planned: 31 filled, 17 expired unfilled. The raw limit-fill rate is 64.6 %; this is not a win rate.
- Filled outcomes: 6 TP, 10 SL, **15 ambiguous** (14 = TP touched inside the fill bar, so the order is unknown; 1 = TP and SL in one M5 bar).
- 0 unresolved at the end of the sample.
- Leg win rate TP/(TP+SL) = 37.5 %, with ambiguous legs excluded.

By depth:

| Depth | Expired | TP | SL | Ambiguous |
|---|---|---|---|---|
| 1 % | 3 | 3 | 7 | 3 |
| 50 % | 6 | 2 | 2 | 6 |
| 80 % | 8 | 1 | 1 | 6 |

The deep legs have a TP inside the zone, so the fill bar often spans it. That is why ambiguity is high.

**Basket R** (basket R = sum of leg R ÷ 3, so 1R = the full combined budget):

| Run / period | Baseline (ambiguous excluded) | Conservative (ambiguous = stop) |
|---|---|---|
| All, 0.20/0.05 | **+0.62R** (13 baskets with R), max DD 1.70R | **−4.55R** (16 baskets), max DD 4.55R |
| Earlier 70 % (to 2026-09-17T06:56:30Z) | +0.96R (8), DD 1.70R | −1.80R (10), DD 3.45R |
| Later 30 % | −0.34R (5), DD 0.67R | −2.75R (6), DD 2.75R |
| All, 0.40/0.10 sensitivity | +0.58R, DD 1.73R | −4.41R, DD 4.41R (30 filled / 18 expired; 14 ambiguous) |

The conservative result is slightly better with higher costs because one marginal leg did not fill.

**Frequency.**
- Covered dates (41): 0.39 baskets/date, median 0, max 2; distribution 0:26 · 1:14 · 2:1. Mean 1.17 legs planned and 0.76 filled per covered date.
- All calendar dates: 0.26 baskets/date.

**Daily table (baskets per Bangkok date; `*` = covered < 12 h):**
```
08-06:0* 08-07:0 08-08:0* 08-09:0* 08-10:0 08-11:0 08-12:0 08-13:0 08-14:2 08-15:0*
08-16:0* 08-17:0 08-18:0 08-19:0 08-20:1 08-21:0 08-22:0* 08-23:0* 08-24:0 08-25:0
08-26:1 08-27:0 08-28:0 08-29:0* 08-30:0* 08-31:1 09-01:0 09-02:1 09-03:1 09-04:0
09-05:0* 09-06:0* 09-07:0 09-08:0 09-09:1 09-10:0 09-11:1 09-12:0* 09-13:0* 09-14:0
09-15:1 09-16:0 09-17:1 09-18:0 09-19:0* 09-20:0* 09-21:0 09-22:0 09-23:1 09-24:0
09-25:1 09-26:0* 09-27:0* 09-28:0 09-29:0 09-30:1 10-01:1 10-02:1 10-03:0* 10-04:0*
10-05:0*
```
Per-date leg counts and coverage hours are in the JSON `daily` array.

**Comparison with saved FastSweep rr2.**
- FastSweep rr2: −17.7R over about 2.3 signals per covered date, where 1R = one signal's risk.
- FVG: 0.39 baskets per covered date, between +0.62R and −4.55R, where 1R = one basket's combined budget (three ⅓-size legs).
- On a per-unit-of-risk basis FVG lost far less in this sample, mainly because it traded about 6× less often. The sign depends entirely on the 15 ambiguous legs, and the later 30 % is negative under both views. **This is not evidence of an edge or of profitability.**

## 6. Known limits

- OHLC replay cannot order events inside a bar. Ambiguous legs are reported, not resolved.
- Nominal SL risk is not a hard loss cap. Gaps, slippage, commission and swap can exceed $10, and lot flooring makes the planned loss ≤ $10.
- A market or data break resets the 50-candle M15 trend warm-up (about 12.5 h). Setups cannot qualify during it.
- If MT5 is unavailable after a restart, a `planned` basket keeps blocking new baskets until it can be reconciled. This is deliberate and conservative.
- Partial-fill handling is verified only against a fake broker. Real broker deal/order field semantics (for example `volume_current`, `position_id` on hedging accounts) follow the MQL5 docs but have not been exercised live.
- The dashboard % of equity needs a live MT5 account; demo and inactive builds show "—".

## 7. Checks not performed

- No live MT5 order path: by design, no real orders.
- No live Telegram send: by design.
- No live-server restart or activation, so the dashboard card was not viewed against the running backend. It was verified by build, syntax check and API tests only.

## 8. Permission denials

None in this task.

## 9. Questions / blockers

None blocking. Decisions that remain the user's (through Codex), all outside this task:
1. Whether to activate FVG (`python -m app.active_strategy fvg rr2` + restart). FVG is selectable but not selected.
2. Whether to arm automatic execution afterwards, on the dashboard with the confirmation checkbox.
3. Whether the high ambiguous share at the 50 % and 80 % depths is acceptable given the replay above.
