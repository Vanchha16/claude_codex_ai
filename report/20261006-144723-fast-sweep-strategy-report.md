# Claude report: FastSweep-M15-M5-v1 replay test (3–4 signals per active day, 1:1 and 1:2)

Task ID: 20261006-144723-fast-sweep-strategy
Source prompt: `prompt/20261006-144723-fast-sweep-strategy.md`
Status: completed (replay research only; nothing activated live)
Reported at: 2026-10-06, about 08:10 UTC (15:10 Bangkok)

## Outcome in plain language

I built FastSweep-M15-M5-v1 exactly as predeclared, as a separate research module, and ran it once per profile on the same ~60 days of real XAUUSDc history.

**Frequency:** it produces **about 2.3 signals per covered trading day** (mean; median 2). It reaches 3–4 signals on **46% of covered dates** (19 of 41). So the 3–4-per-day objective is met on fewer than half of the covered days, and **not on average**.

**Results:** both profiles were **negative** over about 100 simulated signals each:

| Profile | Win rate | Break-even win rate | Total R | Mean R per signal |
|---|---:|---:|---:|---:|
| 1:1 (RR1) | 37.8% | above 50% | **−19.3R** | −0.19 |
| 1:2 (RR2) | 22.1% | above 33.3% | **−17.7R** | −0.18 |

- **Later comparison period:** both profiles were still negative, by less (RR1 −2.5R and RR2 −1.9R, over 30 signals each).
- **Costs:** the cost-sensitivity rerun (spread 0.40, slippage 0.10) made both slightly worse.
- **Why it loses:** losses come from too few wins, not from costs. The average stop distance is about 11 price units, so costs move each result by only about 0.01R.

**Recommendation:** these results **do not support live deployment or forward testing as-is**. Nothing was tuned afterwards; per the task, there is no unreported variant.

## Rules implemented (predeclared, unchanged after seeing results)

Code: `app/fastsweep.py` (rules) and `app/fastsweep_replay.py` (replay, controls, statistics, runner). Profiles: `FastSweep-M15-M5-v1-RR1` and `-RR2` (`PROFILES["rr1"]`, `PROFILES["rr2"]`; `FastSweepConfig.validate()` accepts only RR 1.0 or 2.0 and spread ≤ 0.50).

1. **M15 candles:** built by `app.models.aggregate(m5, M15)`. Only complete, contiguous groups of three M5 bars count, so a missing M5 bar means no M15 candle. A and B must be adjacent (`noncontiguous_m15` otherwise).
2. **Range** (`evaluate_range`), the same predicates as CRT on M15 (a test asserts parity with `app.strategy.evaluate_range` on identical prices):
   - BUY: `B.low ≤ A.low − 2 ticks`, `B.high ≤ A.high`, and `A.low < B.close < A.high` (strict). SELL mirrors this.
   - Both sides swept: `double_sided_sweep`. Neither side swept: `no_sweep`, counted but not recorded.
3. **Trend** (`trend_permits`):
   - EMA20 and EMA50 of M15 closes over the **contiguous** closed-M15 run ending at B (B included).
   - Each EMA is seeded with the simple average of its first N closes, then `ema = close·k + ema·(1−k)`, `k = 2/(N+1)`.
   - Ready only when the run has at least 50 candles (`trend_warmup` otherwise).
   - EMA20 > EMA50 allows BUY, EMA20 < EMA50 allows SELL, equal allows neither (`trend_flat`). A setup against the trend is `trend_against`.
   - Only past closed candles are used.
4. **Confirmation** (`confirm_step`):
   - Uses the next 3 closed M5 bars (opening at B close, +5 and +10 min); a bar inside B is ignored.
   - BUY confirms when `prev.close ≤ B.high < close`; SELL when `prev.close ≥ B.low > close`.
   - Revisiting B's sweep extreme (BUY low ≤ B low, SELL high ≥ B high) invalidates, and it **takes precedence** over a same-bar confirmation.
   - A missing or invalid M5 bar gives `m5_continuity_lost`.
   - B's extremes are frozen at creation. A's far edge plays no role.
5. **Entry:** the contiguous next M5 open after confirmation. BUY at Ask (= open + assumed spread), SELL at Bid. Quote freshness 30 s; spread ≤ 0.50. No contiguous next bar gives `no_quote`.
6. **Stop:** B low − 2 ticks, rounded down (BUY); B high + 2 ticks, rounded up (SELL).
7. **Target:** `entry ± R·risk`, rounded **outward** to the 0.001 tick. Quoted RR averaged exactly 1.0000 and 2.0000 (2.0001 in one cost run, from rounding). Costs are applied to the simulated fill (entry ± slippage) and to SL and expiry exits, not to the geometry.
8. **Controls**, in this order inside each M5 bar:
   1. entries due at the bar open, oldest first, checked against the state at that open;
   2. outcomes of active signals;
   3. pending confirmations;
   4. a new A/B pair at an M15 close.

   The controls themselves:
   - at most **one active signal**;
   - **≥ 30 min** between new signals;
   - **≤ 4 new signals per Bangkok date** (fixed UTC+7, no DST); this is a cap, not a quota;
   - rejected and invalidated setups do not count;
   - one setup key per A/B/direction (duplicate prevention).
9. **Outcomes:**
   - Reuse `app.outcomes.bar_hit` and `settle`: BUY exits on Bid; SELL exits on Ask (= Bid + spread).
   - TP and SL inside one M5 bar is `ambiguous` (no optimistic ordering).
   - TP is a limit (no slippage); SL pays slippage.
   - **Expiry 2 h** after entry is marked at the last observed bar close at or before the expiry time (never a later quote); slippage applies.
   - If data ends first, the signal is `open_at_end` (none occurred).

**Simplifications to note:**
- **Pending setups:** two pending setups cannot overlap, since a confirmation window (15 min) ends at the next pair's evaluation. Priority is chronological (oldest B first).
- **Fill price:** in OHLC replay the "first executable observation" is the next M5 open.

## Data and coverage

- **Source:** real broker history via the running app's `GET /api/market/bars`, paginated M5, the only interface used. It was fetched once and cached to `.tmp/fastsweep/bars-m5-20260806T0700-20261005T0655.json`, so all four runs used identical inputs.
- **Period:** 2026-08-06 07:00 → 2026-10-05 06:55 UTC (same as earlier reviews): **11,560 M5 bars**, **3,852 M15 candles**, 3,851 adjacent pairs.
- **Split:** the 70/30 chronological split is at 2026-09-17 06:56:30 UTC. The later 30% is a **comparison period, not untouched validation**, because this sample was already inspected in earlier tasks.
- **Calendar:** 61 Bangkok calendar dates (2026-08-06 → 2026-10-05):
  - **41 covered dates** (≥ 12 h of valid M5 data, predeclared);
  - **11 partial dates**: 2026-08-06, and every Saturday (Bangkok) 08-08, 08-15, 08-22, 08-29, 09-05, 09-12, 09-19, 09-26, 10-03, plus 10-05 (data ends 13:55 Bangkok);
  - **9 no-data dates**, all Sundays (Bangkok): 08-09, 08-16, 08-23, 08-30, 09-06, 09-13, 09-20, 09-27, 10-04.
- **Trading days:** 52 Bangkok dates have any data. Gold's weekend closure makes "60 calendar days" about 43 full trading days.

## Candidate funnel (identical for both profiles until the controls stage)

| Stage | Count |
|---|---:|
| Adjacent M15 pairs | 3,851 |
| `no_sweep` (not recorded) | 474 |
| **Recorded candidates** | **3,377** |
| Range rejected: `buy_sweep_close_not_inside_a` 821, `sell_sweep_close_not_inside_a` 776, `double_sided_sweep` 423, `noncontiguous_m15` 42, `buy_sweep_but_b_high_above_a_high` 2 | 2,064 |
| **Valid sweep-and-return** (matches Codex's independent count of 1,313) | **1,313** |
| Trend rejected: `trend_warmup` 682, `trend_against` 328 | 1,010 |
| Pending, entering M5 confirmation | 303 |
| Invalidated: `sweep_extreme_revisited` 102, `m5_continuity_lost` 5 | 107 |
| Expired: `no_confirmation_within_window` | 75 |
| **Confirmed** | **121** (earlier 81, later 40) |
| RR1 controls/entry: `active_signal` 15, `daily_cap` 2, `no_quote` 2, `cooldown` 0 | 19 |
| RR2 controls/entry: `active_signal` 17, `daily_cap` 1, `no_quote` 2, `cooldown` 0 | 20 |
| **Signals** | **RR1 102 · RR2 101** |

**The warm-up rule is the main limit on frequency.** It rejected 682 of the 1,313 valid setups (52%). Gold's daily market break creates an M15 gap, so the contiguous run (and the 50-candle readiness) restarts every trading day: roughly the first 12.5 hours of each day after the break cannot produce a trend decision. This follows directly from the predeclared rule ("at least 50 contiguous closed M15 candles"). I did **not** change it; whether to allow the EMA to bridge the daily break is a decision for Codex and the user.

## Frequency (signals per Bangkok date; baseline costs)

| Denominator | Dates | Mean | Median | Min / max | 0 | 1 | 2 | 3 | 4 | ≥ 3 | Exactly 3–4 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RR1: covered dates (≥ 12 h) | 41 | **2.32** | 2 | 0 / 4 | 5 (12.2%) | 5 (12.2%) | 12 (29.3%) | 10 (24.4%) | 9 (22.0%) | **46.3%** | 46.3% |
| RR1: dates with any data | 52 | 1.96 | 2 | 0 / 4 | 10 (19.2%) | 10 (19.2%) | 13 (25.0%) | 10 (19.2%) | 9 (17.3%) | 36.5% | 36.5% |
| RR1: all calendar dates | 61 | 1.67 | 2 | 0 / 4 | 19 (31.1%) | 10 (16.4%) | 13 (21.3%) | 10 (16.4%) | 9 (14.8%) | 31.1% | 31.1% |
| RR2: covered dates (≥ 12 h) | 41 | **2.32** | 2 | 0 / 4 | 5 (12.2%) | 5 (12.2%) | 12 (29.3%) | 10 (24.4%) | 9 (22.0%) | **46.3%** | 46.3% |
| RR2: dates with any data | 52 | 1.94 | 2 | 0 / 4 | 11 (21.2%) | 9 (17.3%) | 13 (25.0%) | 10 (19.2%) | 9 (17.3%) | 36.5% | 36.5% |
| RR2: all calendar dates | 61 | 1.66 | 2 | 0 / 4 | 20 (32.8%) | 9 (14.8%) | 13 (21.3%) | 10 (16.4%) | 9 (14.8%) | 31.1% | 31.1% |

Zero-signal dates stay in every denominator. The cap of 4 was reached on 9 dates and only removed 1–2 candidates.

**Was the objective met?** The 3–4 per active day objective was **not achieved on average**. It was met on 46.3% of covered dates (both profiles); 53.7% of covered dates had 0–2 signals.

## Performance (simulated price hits; R = result ÷ quoted stop risk, fill-adjusted)

| Profile, costs | Period | Signals | TP | SL | Expired | Ambiguous | Win rate TP/(TP+SL) | Total R | Mean R | Max drawdown (R) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RR1, 0.20 / 0.05 | earlier | 72 | 22 | 39 | 11 | 0 | 36.1% | −16.83 | −0.234 | 17.36 |
| | later | 30 | 9 | 12 | 9 | 0 | 42.9% | −2.50 | −0.083 | 4.31 |
| | **all** | **102** | 31 | 51 | 20 | 0 | 37.8% | **−19.34** | −0.190 | 21.25 |
| RR2, 0.20 / 0.05 | earlier | 71 | 10 | 40 | 20 | 1 | 20.0% | −15.86 | −0.227 | 17.89 |
| | later | 30 | 5 | 13 | 12 | 0 | 27.8% | −1.86 | −0.062 | 5.31 |
| | **all** | **101** | 15 | 53 | 32 | 1 | 22.1% | **−17.72** | −0.177 | 23.20 |
| RR1, 0.40 / 0.10 | all | 102 | 31 | 51 | 20 | 0 | 37.8% | −20.67 | −0.203 | 22.30 |
| | earlier / later | 72 / 30 | | | | | | −17.78 / −2.89 | | |
| RR2, 0.40 / 0.10 | all | 101 | 15 | 53 | 32 | 1 | 22.1% | −19.36 | −0.194 | 24.48 |
| | earlier / later | 71 / 30 | | | | | | −17.01 / −2.35 | | |

No signal was `open_at_end`. Direction split: RR1 49 BUY / 53 SELL; RR2 49 BUY / 52 SELL.

**Quoted geometry vs simulated fill:**
- **Stop distance:** averaged 11.07 price units (median 9.52, min 2.95, max 32.15).
- **Baseline costs:** a TP averaged **+0.994R** (RR1) or **+1.994R** (RR2) instead of +1/+2; an SL averaged **−1.013R**.
- **Higher costs:** +0.988R / +1.987R and −1.025R.
- **Expired trades:** averaged +0.075R (RR1) and +0.19R (RR2).

Costs are therefore a minor factor; the negative totals come from the win rate.

**Later period:** it was less negative, but on only 30 signals per profile. That is a small sample from an already-inspected period, so it does not support further testing as-is.

## Bangkok daily table (baseline costs; zero and partial dates included)

| Bangkok date | Day | M5 bars | Coverage h | Covered (>=12h) | Candidates | Confirmations | RR1 signals | RR2 signals |
|---|---|---:|---:|:---:|---:|---:|---:|---:|
| 2026-08-06 | Thu | 120 | 10.0 | partial | 35 | 0 | 0 | 0 |
| 2026-08-07 | Fri | 276 | 23.0 | yes | 79 | 1 | 1 | 1 |
| 2026-08-08 | Sat | 48 | 4.0 | partial | 15 | 4 | 1 | 1 |
| 2026-08-09 | Sun | 0 | 0.0 | no data | 0 | 0 | 0 | 0 |
| 2026-08-10 | Mon | 228 | 19.0 | yes | 65 | 2 | 2 | 2 |
| 2026-08-11 | Tue | 276 | 23.0 | yes | 81 | 2 | 2 | 2 |
| 2026-08-12 | Wed | 276 | 23.0 | yes | 77 | 4 | 4 | 4 |
| 2026-08-13 | Thu | 276 | 23.0 | yes | 81 | 0 | 0 | 0 |
| 2026-08-14 | Fri | 276 | 23.0 | yes | 85 | 2 | 2 | 2 |
| 2026-08-15 | Sat | 48 | 4.0 | partial | 13 | 1 | 1 | 1 |
| 2026-08-16 | Sun | 0 | 0.0 | no data | 0 | 0 | 0 | 0 |
| 2026-08-17 | Mon | 228 | 19.0 | yes | 63 | 0 | 0 | 0 |
| 2026-08-18 | Tue | 276 | 23.0 | yes | 84 | 4 | 3 | 3 |
| 2026-08-19 | Wed | 276 | 23.0 | yes | 77 | 1 | 1 | 1 |
| 2026-08-20 | Thu | 276 | 23.0 | yes | 83 | 4 | 4 | 4 |
| 2026-08-21 | Fri | 276 | 23.0 | yes | 80 | 1 | 1 | 1 |
| 2026-08-22 | Sat | 48 | 4.0 | partial | 16 | 2 | 2 | 2 |
| 2026-08-23 | Sun | 0 | 0.0 | no data | 0 | 0 | 0 | 0 |
| 2026-08-24 | Mon | 228 | 19.0 | yes | 63 | 0 | 0 | 0 |
| 2026-08-25 | Tue | 276 | 23.0 | yes | 78 | 3 | 3 | 3 |
| 2026-08-26 | Wed | 276 | 23.0 | yes | 82 | 4 | 4 | 4 |
| 2026-08-27 | Thu | 276 | 23.0 | yes | 80 | 5 | 4 | 4 |
| 2026-08-28 | Fri | 276 | 23.0 | yes | 84 | 3 | 3 | 3 |
| 2026-08-29 | Sat | 48 | 4.0 | partial | 11 | 1 | 1 | 1 |
| 2026-08-30 | Sun | 0 | 0.0 | no data | 0 | 0 | 0 | 0 |
| 2026-08-31 | Mon | 228 | 19.0 | yes | 65 | 2 | 2 | 2 |
| 2026-09-01 | Tue | 276 | 23.0 | yes | 85 | 4 | 4 | 4 |
| 2026-09-02 | Wed | 276 | 23.0 | yes | 77 | 3 | 3 | 3 |
| 2026-09-03 | Thu | 276 | 23.0 | yes | 84 | 3 | 3 | 3 |
| 2026-09-04 | Fri | 276 | 23.0 | yes | 81 | 5 | 4 | 4 |
| 2026-09-05 | Sat | 48 | 4.0 | partial | 16 | 1 | 1 | 0 |
| 2026-09-06 | Sun | 0 | 0.0 | no data | 0 | 0 | 0 | 0 |
| 2026-09-07 | Mon | 228 | 19.0 | yes | 70 | 0 | 0 | 0 |
| 2026-09-08 | Tue | 246 | 20.5 | yes | 75 | 4 | 3 | 3 |
| 2026-09-09 | Wed | 276 | 23.0 | yes | 80 | 3 | 2 | 2 |
| 2026-09-10 | Thu | 276 | 23.0 | yes | 80 | 3 | 2 | 2 |
| 2026-09-11 | Fri | 276 | 23.0 | yes | 79 | 0 | 0 | 0 |
| 2026-09-12 | Sat | 48 | 4.0 | partial | 15 | 1 | 1 | 1 |
| 2026-09-13 | Sun | 0 | 0.0 | no data | 0 | 0 | 0 | 0 |
| 2026-09-14 | Mon | 227 | 18.92 | yes | 65 | 1 | 1 | 1 |
| 2026-09-15 | Tue | 276 | 23.0 | yes | 76 | 4 | 4 | 4 |
| 2026-09-16 | Wed | 276 | 23.0 | yes | 81 | 3 | 3 | 3 |
| 2026-09-17 | Thu | 276 | 23.0 | yes | 82 | 2 | 2 | 2 |
| 2026-09-18 | Fri | 276 | 23.0 | yes | 84 | 3 | 2 | 2 |
| 2026-09-19 | Sat | 48 | 4.0 | partial | 14 | 0 | 0 | 0 |
| 2026-09-20 | Sun | 0 | 0.0 | no data | 0 | 0 | 0 | 0 |
| 2026-09-21 | Mon | 228 | 19.0 | yes | 66 | 3 | 3 | 3 |
| 2026-09-22 | Tue | 276 | 23.0 | yes | 83 | 4 | 2 | 2 |
| 2026-09-23 | Wed | 276 | 23.0 | yes | 81 | 3 | 2 | 2 |
| 2026-09-24 | Thu | 276 | 23.0 | yes | 80 | 5 | 3 | 3 |
| 2026-09-25 | Fri | 276 | 23.0 | yes | 81 | 3 | 3 | 3 |
| 2026-09-26 | Sat | 48 | 4.0 | partial | 13 | 0 | 0 | 0 |
| 2026-09-27 | Sun | 0 | 0.0 | no data | 0 | 0 | 0 | 0 |
| 2026-09-28 | Mon | 228 | 19.0 | yes | 65 | 1 | 1 | 1 |
| 2026-09-29 | Tue | 276 | 23.0 | yes | 80 | 2 | 2 | 2 |
| 2026-09-30 | Wed | 276 | 23.0 | yes | 80 | 5 | 4 | 4 |
| 2026-10-01 | Thu | 276 | 23.0 | yes | 82 | 3 | 2 | 2 |
| 2026-10-02 | Fri | 276 | 23.0 | yes | 84 | 6 | 4 | 4 |
| 2026-10-03 | Sat | 48 | 4.0 | partial | 13 | 0 | 0 | 0 |
| 2026-10-04 | Sun | 0 | 0.0 | no data | 0 | 0 | 0 | 0 |
| 2026-10-05 | Mon | 107 | 8.92 | partial | 28 | 0 | 0 | 0 |

"Candidates" are recorded M15 setups whose B closed on that Bangkok date. Coverage = valid M5 bars × 5 min.

## Files changed

- **`app/fastsweep.py` (new):** `FastSweepConfig` (validated), `PROFILES`, `evaluate_range`, `ema_last`, `trend_permits`, `Setup`/`new_setup`, `confirm_step`, `build_levels`, and a Bangkok date helper (fixed UTC+7).
- **`app/fastsweep_replay.py` (new):**
  - pure in-memory `replay()` with controls and outcome tracking;
  - `frequency()` statistics and the Bangkok daily table;
  - `fetch_m5()` (GET-only) and the CLI `main()`.
- **`tests/test_fastsweep.py` (new):** 18 tests covering:
  - strict sweep and inside-close boundaries, plus parity with CRT's `evaluate_range`;
  - M15 aggregation with a gapped M5 group;
  - SMA-seeded EMA, the 49 vs 50 warm-up, and trend up/down/flat;
  - confirmation never inside B, needing a strict cross, invalidation precedence, a gap invalidating, and window expiry;
  - BUY Ask / SELL Bid, outward rounding, 1:1 and 1:2 geometry, and spread, stale and old-quote rejections;
  - replay checks: entry, fill and TP, RR2, SL, same-bar ambiguity, one active signal and 2 h expiry, period end, cooldown, the Bangkok day rollover (17:00 UTC) with the cap counting only accepted signals, and the daily table with partial dates;
  - no future bars changing earlier decisions (prefix test);
  - config rejecting RR 0.5 and spread above 0.50.
- **`README.md`:** new "Research: FastSweep-M15-M5-v1 (replay only, not live)" section with the rules, run command and measured summary.
- **Not changed:** CRT-SMC-v1 (`app/strategy.py`, `app/engine.py`, `app/replay.py`), `config/strategy.json` (still `CRT-SMC-v1@193949a6`, `min_reward_risk` 1.5), the live scanner, Telegram, the database and the frontend. The earlier unpublished "min RR 1.0" draft was not executed.

## Executable replay command

```
.venv/Scripts/python.exe -m app.fastsweep_replay --start 2026-08-06T07:00:00Z --end 2026-10-05T06:55:00Z --profiles rr1,rr2 --spread 0.20 --slippage 0.05
.venv/Scripts/python.exe -m app.fastsweep_replay --start 2026-08-06T07:00:00Z --end 2026-10-05T06:55:00Z --profiles rr1,rr2 --spread 0.40 --slippage 0.10
```

**Outputs** (in `.tmp/fastsweep/`):
- `FastSweep-M15-M5-v1-RR{1,2}-spread{0.2,0.4}-slip{0.05,0.1}.json`: config, period, funnel, segments, full daily table, frequency, every signal and every candidate;
- the cached bars file;
- `daily-table.md`.

## Tests actually run

- `.venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp=<unique .tmp path> tests/test_fastsweep.py`: **18 passed**. Two fixture mistakes were corrected along the way: an invalid OHLC bar, and a rising fixture that hit block 1's TP. Neither was a rule change.
- Full backend suite with a unique project-local `--basetemp`: **131 passed** (113 existing + 18 new), 1 deprecation warning from Starlette/httpx that was already there.
- Frontend `npm test`: **28 passed**.
- The temporary basetemp directories were removed after confirming their paths were under `.tmp/pytest-fastsweep-*` and not symlinks.

These tests cover the **replay** implementation only. Nothing is wired live, and no claim is made about live behaviour.

## Runtime state (read-only, after the runs)

- VC Signal: PID 24304, live MT5 XAUUSDc, feed ok, scanner running and unpaused with no error.
- Strategy `CRT-SMC-v1@193949a6`, min RR 1.5.
- Telegram enabled with the persisted opt-in.
- 0 signals.

**Not caused by this task:**
- **Outbox:** it shows a test message at 2026-10-06 07:40:57 UTC (14:40:57 Bangkok), together with "delivery disabled by the user" and then re-enabled at 07:40:53–56 UTC. Both happened **before this task was dispatched** (14:47 Bangkok), from the dashboard. I sent no messages and changed no toggles.
- **Watermark:** it moved to 05:50:43Z through the app's automatic stale-feed recoveries, also before this task.

## Alternatives not taken (by instruction)

- **No grid search or unreported variants.** I did not tune the RR, trend, warm-up, windows, caps or sessions.
- **No ratio below 1:1.**
- **No live selector**, and nothing wired into the scanner or Telegram.
- **No quota filling.** I did not relax the daily cap into a quota, or compensate for missing frequency with arbitrary alerts.

## Caveats

- **What the simulation is:** OHLC price-hit simulation with assumed spread and slippage. It is not broker fills, and there is no tick replay.
- **Inspected sample:** the sample was already inspected, so the later 30% is only a comparison period. Any candidate needs a **fresh forward paper period** before a live decision.
- **Small samples:** about 100 signals in total, and 30 per profile in the later period, so the confidence intervals are wide. A negative total here is not proof the idea can never work. But nothing in these results supports profitability or live use.
- **Coverage:** M15 contiguity and the daily market break limit coverage; see the warm-up note in the funnel section.

## Concrete next step (for Codex and the user; not started)

Decide whether to stop this direction or to approve a **single, predeclared** follow-up before any live work. For example, letting the EMA trend bridge only the routine daily break (to address the 52% warm-up loss), tested on new forward data rather than this sample. Otherwise, keep CRT-SMC-v1 live and paper-track FastSweep on new data without alerts.

## Questions, missing requirements, or blockers

None blocking. One design consequence needs a decision: the predeclared "≥ 50 contiguous M15 candles" warm-up interacts with the daily market break and removes about half of the valid setups.
