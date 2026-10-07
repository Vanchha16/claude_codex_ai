# Claude report: why the 60-day MT5 replay has zero signals

Task ID: 20261005-135654-investigate-zero-replay-signals
Source prompt: `prompt/20261005-135654-investigate-zero-replay-signals.md`
Status: completed (read-only diagnosis; no fixes)
Reported at: 2026-10-05, about 07:30 UTC (14:30 Bangkok)

## Answer in plain language

The replay found **834 setup records**, and **42** of them reached a valid M5 confirmation. None of the 42 became a signal, for two reasons.

1. **The reward-to-risk rule cannot be met by these setups (the main cause).**
   - For a BUY, entry happens at or above the confirmation level, the target is candle A's high, and the stop sits just below candle B's sweep low. A SELL mirrors this.
   - With the 1.5 minimum RR, a setup can only pass if its confirmation level lies in the **lowest 40%** of the distance from stop to target.
   - In all 42 confirmed setups the level sat at **41%–96%** of that distance (median 66%). So even a perfect fill exactly at the level would have been below 1.5 RR.
   - Their actual RR ranged from **0.02 to 1.26** (median 0.34).
   - The earlier OHLC run shows this directly: all 42 were rejected for `reward_risk_below_minimum`.
2. **In the tick run, 35 of the 42 never got a price.** No tick came back in the 30-second window after the confirmation close, so they were recorded as `no_quote`.
   - The market was active at those times. For example, the 2026-08-06 10:15 UTC M5 bar had 627 ticks, about 2 per second.
   - So this most likely means the terminal did not return tick history for those older dates, rather than a quiet market.
   - It does not change the outcome: the same 35 also fail the RR rule when priced from bars.

This is the implemented rule set behaving as written. It is **not** evidence that the strategy can never signal, nor of profitability either way. It says that, on these 60 days, the combination "target = A's opposite edge, stop = sweep extreme ± 2 ticks, entry after an M5 close beyond the structure level, minimum RR 1.5" left no setup eligible.

## Sources and actions (all read-only)

- **Read:**
  - the screenshot `.img/image copy 6.png`;
  - Codex's saved API snapshot `.tmp/20261005-135654-investigate-zero-replay-signals-snapshot.json` (unmodified; read BOM-tolerant);
  - the stored results `.tmp/gold-signals/replays/replay-mt5-20261005-065535.json` and `replay-mt5-20261005-065618.json`, and `latest-mt5.json` (byte-identical to the 065618 file);
  - `GET /api/state` and `/api/events`, `config/strategy.json`;
  - code: `app/replay.py`, `app/strategy.py`, `app/engine.py`, `app/data/mt5.py`, `app/market.py`, `app/web.py`.
- **Reconstruction:**
  - Script: `.tmp/diag_replay/diag.py`, output `.tmp/diag_replay/out.json`.
  - It fetched the same period's closed bars through the running app's supported `GET /api/market/bars`, in pages of 1000: M5 for 2026-08-06 07:00 → 2026-10-05 06:55 UTC (11,560 bars) and H1 (963 bars).
  - It then re-ran the pure `app.replay.replay()` in **OHLC mode** in a separate process, using an in-memory store, no MT5 connection and no app state.
  - That recovers per-candidate records, which the saved result does not keep.
  - It reproduced the saved OHLC run **exactly**: 592 and 242 candidates, with every reason count identical, including `reward_risk_below_minimum` 32 + 10.
- **Also read:** M5 tick volume for example bars, via the same chart API.
- **Not done:** no POST requests, no replay run, no restart, no code, config or strategy edits, no MT5 session of my own, no messages. Saved replay files and the live database are untouched.

## Two runs, and the screenshot vs API mismatch

| Run (UTC / Bangkok) | Mode | Entry-stage outcome of the 42 confirmations |
|---|---|---|
| 06:55:35 / 13:55:35 | **OHLC** ("OHLC Bid bars; assumed spread 0.2…") | 42 × `reward_risk_below_minimum` (dev 32, holdout 10) |
| 06:56:18 / 13:56:18 | **Ticks** ("tick Bid/Ask; entry slippage 0.05…") | 35 × `no_quote` (dev 32, holdout 3) + 7 × `reward_risk_below_minimum` (holdout) |

- **What the screenshot shows:** it was taken at 13:55 Bangkok and shows the **OHLC** result, the newest saved result at that moment. "Use ticks" was ticked and **Run replay was disabled** because the second (tick) run was in progress.
- **Use ticks is a setting, not a description:** the checkbox only sets the mode for the next run; it does not describe the displayed result.
- **Codex's snapshot:** it was taken after the tick run finished, so it shows the tick costs text.
- **Now:** `GET /api/state` reports `replay_running: false` and `replay_error: null`, so the disabled button was the in-progress state at screenshot time, not stale UI.
- **Same data in both runs:** period, bar counts and every pre-entry reason are identical. Only the entry pricing differs.

## Factual funnel (both runs, development + holdout)

| Stage | Count | Source |
|---|---|---|
| H1 bars returned | 963 | saved result |
| Consecutive A/B pairs | 962 | reconstruction |
| `no_sweep` pairs, which are not recorded as candidates by design (`app/engine.py` about lines 127–133) | 127 | reconstruction |
| **Candidate records** | **834** | saved result |

The 962 pairs minus 127 `no_sweep` gives 835 against 834 recorded. The difference is one boundary pair: `buy_sweep_close_not_inside_a` is 203 in the raw pair count versus 202 recorded. I did not chase it further; it doesn't affect the conclusion.

Breakdown of the 834 records (all from the saved result):

| Stage | Count |
|---|---|
| A/B not contiguous (`noncontiguous_hours`: market break or gap) | 42 |
| Range rejected: `double_sided_sweep` | 111 |
| Range rejected: sweep candle did not close back inside A (buy 137+65, sell 144+53) | 399 |
| No usable structure: no swing high inside A 22, no swing low 29, insufficient M5 history 10 | 61 |
| **Pending setups that started M5 confirmation** | **221** |
| invalidated: `sweep_extreme_revisited` 78, `opposite_boundary_touched` 28 | 106 |
| expired: `no_confirmation_within_window` (12 M5 bars) | 73 |
| **Confirmed** (an M5 close beyond the level) | **42** |
| Entry stage (OHLC run): `reward_risk_below_minimum` | 42 |
| Entry stage (tick run): `no_quote` 35 + `reward_risk_below_minimum` 7 | 42 |
| **Signals** | **0** |

The 42 confirmations split 32 in development and 10 in holdout. Development's `no_quote` count of 32 equals all of development's confirmations, so **every** development confirmation got no tick.

## The 7 (and 42) RR failures

The RR code is `app/strategy.py` → `build_entry()`, at about lines 186–209:
- **BUY:** entry = Ask; SL = sweep extreme − 2 ticks, rounded down; TP = A high; RR = (TP − entry) / (entry − SL).
- **SELL:** mirrored, with entry = Bid.
- **Threshold:** `min_reward_risk` 1.5 (`config/strategy.json`).

Reconstructed figures for the confirmed setups are in `.tmp/diag_replay/out.json`. They use OHLC pricing: entry = next M5 open, plus 0.2 for a BUY's Ask.

| Measure | Value |
|---|---|
| RR, min / median / max | 0.02 / 0.34 / 1.26 |
| RR ≥ 1.0 | 2 of 42 |
| RR ≥ 1.5 | 0 of 42 |
| Level position in [SL → TP], min / median / max | 0.406 / 0.659 / 0.96 |

A level position of at most 0.40 is required for RR ≥ 1.5, even with entry exactly at the level.

**Example A** (closest to passing). SELL confirmed **2026-10-02 12:05 UTC = 19:05 Bangkok**, holdout:
- **The setup:** A = 4165.806–4186.002; B swept to 4188.434; frozen level 4179.260.
- **The price levels:** entry (Bid at the next open) 4178.436; SL = 4188.434 + 2 × 0.001 = 4188.436, rounded **up** to the 0.001 tick, giving **4188.437**; TP = 4165.806.
- **The calculation:** reward 12.630, risk 10.001, **RR 1.263 < 1.5**. It would need entry ≥ 4179.385. Even entering exactly at the 4179.260 level gives 13.454 / 9.177 = **1.466**.
- **Status:** reconstructed from broker bars; the stored result keeps reason counts only. The tick run's 7 RR failures are all in holdout, and this is one of the holdout confirmations, but the stored tick result does not say which 7, so I can't confirm the tick-run RR for this specific setup.

**Example B** (typical). BUY confirmed **2026-08-27 11:55 UTC = 18:55 Bangkok**, development:
- **The setup:** A = 4577.479–4600.624; sweep 4568.909; level 4599.350, which sits at 96% of the stop-to-target distance.
- **The price levels:** entry 4599.993, SL 4568.906, TP 4600.624.
- **The calculation:** reward 0.631, risk 31.087, **RR 0.02**.

**Why this happens:** the structure level is a swing high (or low) **inside A**, formed before B, and for most setups it sits near A's far edge. The 2-tick buffer is tiny on XAUUSDc (0.002), so the stop is almost exactly at the sweep extreme. The confirmation therefore uses up most of the room to the target.

**This is the rule as written**, not an arithmetic defect. Rounding, side (Ask/Bid) and ordering all match the code and config.

## The 35 no_quote

**How it works:**
- In tick mode (`app/replay.py` → `entry_fn`, about lines 113–117), the entry is the **first valid tick in [confirmation close, close + 30 s]** (`signal_max_age_seconds` 30).
- If there is none, it returns no quote and `build_entry` records `no_quote`.
- The ticks come from `MT5Feed.ticks_range()` (`app/data/mt5.py`, about lines 224–235), which calls `copy_ticks_range`. It raises only when MT5 returns `None` (an error). An **empty array is returned silently as "no ticks"**.
- Because the run finished without `replay_error`, every one of these reads returned without error, possibly empty. The tick run completed, so no exception propagated.
- The code does not record how many reads came back empty.

**Evidence that this is missing tick history, not a quiet market:**
- **All 32 development confirmations** (2026-08-06 → 2026-09-16) were `no_quote`. They are all on weekdays during trading hours, for example Thu 2026-08-06 10:15 UTC (17:15 Bangkok, London session).
- The M5 bar starting at that confirmation close had **tick_volume 627** (about 2 ticks/s), as did its neighbours (640, 589). A 30-second window would normally hold dozens of ticks.
- In holdout, only 3 of 10 were `no_quote`, and 7 got a real tick and were then priced (and failed RR). This pattern fits tick history being available only for roughly the most recent couple of weeks. Which 3 holdout confirmations lacked ticks is not retained.

**Concrete no_quote example:** SELL confirmed **2026-08-06 10:15 UTC = 17:15 Bangkok**:
- the tick run recorded no tick in 10:15:00–10:15:30 UTC (all development confirmations were `no_quote`);
- bar tick volume 627 (reconstructed via the chart API);
- had it been priced, the OHLC run shows **RR 0.604**, so it would still have failed.

**What I could not verify:** I could not read the actual tick history for those dates. There is no tick endpoint, and a separate MT5 session was not allowed. So "the terminal returned an empty tick array for older dates" is a **strong inference, not a recorded fact**. The exact earliest available tick time is unknown.

**Suspected defect (diagnostic, not the cause of zero signals):**
- The tick replay cannot tell **"terminal has no tick history for this date"** apart from **"no tick within 30 s"**; both are reported as `no_quote`.
- The result also doesn't show the tick coverage it actually had.
- That makes the tick run look like a market or entry problem when it is a data-coverage problem.

## Data coverage checks

- **Period:** requested 60 days; returned 11,560 M5 and 963 H1 bars from 2026-08-06 07:00 to 2026-10-05 06:55 UTC. That is consistent with gold trading about 23 h/day, 5 days/week.
- **Contiguity:** 42 A/B pairs were non-contiguous (daily breaks and weekends) and are recorded as such.
- **Symbol and holdout:** tick size 0.001, 3 digits (from the bar API). The holdout split is 2026-09-17 06:56:30 UTC.
- **No data problems surfaced:** no invalid or duplicate-bar problem appeared; the reconstruction from the same broker bars reproduced every count. Both runs logged no replay error.

## Verified behaviour vs suspected defects

- **Verified as designed:**
  - range, structure, invalidation and expiry filters;
  - entry geometry and the 1.5 RR rejection;
  - OHLC next-open pricing (+0.2 assumed spread);
  - tick-window entry (first tick within 30 s).
  - The zero-signal result follows from these rules on this data.
- **Suspected defect (reporting):**
  - empty tick reads are indistinguishable from a genuine "no tick in window", and coverage isn't reported;
  - the "Use ticks" control sits next to an older result without saying which mode that result used (the costs line does say it, in small text).

## Proposed next steps (for Codex and the user; none are authorized here)

1. **Decide whether the geometry is intended.** "TP = A's opposite edge, entry after a close beyond an inner swing, min RR 1.5" is structurally hard to meet. Any change (TP definition, RR threshold, level choice) is a strategy decision. It should be tested properly (the holdout must not be used for tuning), not tuned to force signals.
2. **Optional small, separately approved fix:**
   - in tick replay, record tick-read coverage, for example the first and last available tick per window, and an empty-read count;
   - label confirmations whose bar shows market activity but no returned ticks as `tick_history_unavailable` instead of `no_quote`;
   - show the result's mode prominently next to the controls.
3. **To get tick coverage now:** run tick replays only over the recent period where the terminal has ticks, or use OHLC mode. For these 60 days the RR rule already decides the result in either mode.

## Limitations

- **What was rebuilt:** the per-candidate details (levels, RR, times) come from the read-only reconstruction using today's broker bars for the same period, not from the original stored run, which keeps only counts. The exact reproduction of every count supports, but does not prove, identical inputs.
- **Tick values:** no tick values were retained or read. The tick-history explanation for `no_quote` is an inference, as stated above.
- **Unidentified setups:** which 3 holdout confirmations were `no_quote`, and which 7 were priced, is not retained.
