# Claude report: why today's live setups were rejected

Task ID: 20261005-143121-explain-live-setup-rejections
Source prompt: `prompt/20261005-143121-explain-live-setup-rejections.md`
Status: completed (read-only diagnosis; no changes)
Reported at: 2026-10-05, about 07:35 UTC (14:35 Bangkok)

## Short answer for the user

Today's setups were not rejected by the reward-to-risk check. They failed **earlier**, at the H1 candle check, because the second candle (B) did not behave as the strategy requires.

**What a valid setup needs.** Candle B must sweep **one** side of candle A's range by at least 2 ticks (0.002), then **close back strictly inside** A's range.
- A sweep above A's high, then a close back inside, is a possible **SELL**.
- A sweep below A's low, then a close back inside, is a possible **BUY**.

**What actually happened:**
- **#5 (13:00–14:00 Bangkok):** B pushed above A's high, but **closed 14.29 above it** (4155.196 vs 4140.902). That is a breakout, not a sweep-and-return, so there was no SELL.
- **#4 (11:00–12:00 Bangkok):** B dropped below A's low, but **closed 4.78 below it** (4131.390 vs 4136.171). Again a breakout, so there was no BUY.
- **#2 (09:00–10:00 Bangkok):** B swept **both** sides of A (above its high **and** below its low). Direction is ambiguous, so it was rejected.
- **#3** was the one valid setup today, a BUY. It never confirmed, and price fell back through its sweep low at 11:14:08 Bangkok, so it was cancelled (invalidated).
- **#1** is an older setup from 2 October that was cancelled when the scanner was paused. That isn't a market rejection.

Every decision matches the coded rules and the actual candles. **No defect was found.** Right now there are **no pending setups and no signals**, nothing failed RR or delivery, and the feed and scanner are healthy.

## Evidence table

H1 prices come from `GET /api/market/bars?tf=H1&count=12`, which is the live MT5 feed (XAUUSDc, 3 digits, tick 0.001). Candidate fields come from `/api/candidates` and the immutable snapshot `.tmp/20261005-143121-explain-live-setup-rejections-snapshot.json`; they are identical, and no new records arrived. Sweep margin = `sweep_min_ticks` 2 × 0.001 = **0.002**.

| ID / status | Candles (Bangkok; UTC) | A range (low – high) | B high / low / **close** | Rule check (code order) | Result |
|---|---|---|---|---|---|
| **#5** rejected | A 12:00–13:00, B 13:00–14:00, decided 14:00:02 (A 05:00Z, B 06:00Z, decided 07:00:02Z) | 4130.277 – 4140.902 | 4156.018 / 4134.239 / **4155.196** | High swept: 4156.018 ≥ 4140.904 ✓ (by 15.114). Low not swept: 4134.239 > 4130.275. B low not below A low ✓. **Close strictly inside A?** It needs 4130.277 < close < 4140.902; actual 4155.196 is **14.294 above** A high ✗ | `sell_sweep_close_not_inside_a` ✔ correct |
| **#4** rejected | A 10:00–11:00, B 11:00–12:00, decided 12:00:03 (A 03:00Z, B 04:00Z) | 4136.171 – 4146.705 | 4143.647 / 4124.308 / **4131.390** | Low swept: 4124.308 ≤ 4136.169 ✓ (by 11.863). High not swept: 4143.647 < 4146.707. B high not above A high ✓. **Close inside?** It needs 4136.171 < close < 4146.705; actual 4131.390 is **4.781 below** A low ✗ | `buy_sweep_close_not_inside_a` ✔ correct |
| **#3** invalidated | A 09:00–10:00, B 10:00–11:00, valid BUY at 11:00; invalidated 11:14:08.861 (A 02:00Z; 04:14:08.861Z) | 4139.409 – 4163.288 | 4146.705 / 4136.171 / 4143.143 | Low swept by 3.238; close inside ✓, so a **BUY candidate**. It needed an M5 close above the frozen level **4162.945** before 12:00 Bangkok. A live Bid tick at or below the sweep low **4136.171** came first. | `sweep_extreme_revisited_live_tick` ✔ correct |
| **#2** rejected | A 08:00–09:00, B 09:00–10:00, decided 10:00:02 (A 01:00Z, B 02:00Z) | 4151.779 – 4161.611 | 4163.288 / 4139.409 / 4142.993 | High swept: 4163.288 ≥ 4161.613 ✓ (by 1.677). **And** low swept: 4139.409 ≤ 4151.777 ✓ (by 12.370). Both sides were swept, so the direction is ambiguous. | `double_sided_sweep` ✔ correct |
| **#1** expired | SELL from 2026-10-02 (A 14:00 Bangkok); expired 2026-10-05 09:46:07 Bangkok (02:46:07Z) | 4177.523 – 4192.306 | 4196.273 / 4179.260 | Pending when the scanner was paused; cancelled when the scanner resumed | `cancelled_by_pause`: expiry, not a market rejection |

**Further detail on #3:** the M5 closes after B were 4139.735 and 4139.648, about 23 below the level. The 11:10 Bangkok M5 bar's low was 4134.801. The **exact triggering tick price is not stored**; only its time and reason are. This was covered in `report/20261005-112721-investigate-last-setup-invalidation-report.md`.

**Pairs with no record:**
- **A 11:00 / B 12:00 Bangkok (B closed 06:00Z):** B's range 4130.277–4140.902 stayed inside A's 4124.308–4143.647, so there was **no sweep** on either side. `no_sweep` pairs are intentionally not stored.
- **A 07:00 / B 08:00 Bangkok (B closed 02:00Z = 09:00 Bangkok):** this pair would also have been rejected: a SELL sweep, but the close of 4160.138 was above A's high of 4158.244. It was **not evaluated live**, because the events show the app started at 09:26 Bangkok, paused at 09:27 and resumed at 09:46. Only later closes are evaluated.

**Next evaluation:** the next H1 pair (A 13:00, B 14:00 Bangkok) will be evaluated when B closes at 15:00 Bangkok (08:00Z).

## Code checked

- **`app/strategy.py`, `evaluate_range()` (about lines 26–55):**
  - `margin = sweep_min_ticks × tick` (0.002), with float tolerance `tick × 1e-6` only;
  - `swept_low = B.low ≤ A.low − margin`, `swept_high = B.high ≥ A.high + margin`;
  - both swept gives `double_sided_sweep`; neither gives `no_sweep`, which is not recorded;
  - otherwise the opposite side must not exceed A, and the close must satisfy **`A.low < B.close < A.high`** (strict) or the result is `*_sweep_close_not_inside_a`.
  - The recorded reasons and the candle values above follow exactly this order.
- **`app/engine.py`:**
  - A/B evaluation at B's close (about lines 120–150); `no_sweep` returns without a record.
  - `on_quote()` (about lines 209–218) is the live-tick invalidation, Bid ≤ sweep extreme for a BUY, appending `_live_tick` and storing the tick time.
- **`app/strategy.py`:** `invalidation_by_price()` and `invalidation_by_quote()` (Bid).
- **`config/strategy.json`:** `sweep_min_ticks` 2, `confirm_max_bars` 12, `min_reward_risk` 1.5. RR is only checked after an M5 confirmation; no setup today reached that stage.

## Current state

Read-only, `GET /api/state`, `/api/signals`, `/api/outbox`, `/api/events`, at about 07:33Z:
- mode `mt5`, XAUUSDc, feed ok, quote fresh;
- scanner running, unpaused, no error;
- Telegram delivery enabled;
- strategy state "rejected" (the last pair was #5);
- **no pending candidates, 0 signals**;
- the outbox holds only 3 earlier `test` messages, all `sent`, so **no live signal ever reached RR or delivery**.

The session watermark is 05:55:02Z (12:55 Bangkok). It came from repeated automatic "recovered after a disconnected/stale feed" events between 04:59 and 05:55Z. That is history; the feed is healthy now. These recoveries matter only for confirmations, not for the range rejections above.

## Checks performed

- Read the snapshot (BOM-tolerant). I noted the PowerShell wrapper (`value`/`Count`), and that its `signal_count: 1` is a serialisation artefact: the live API returns 0 signals.
- Read current candidates, events, state, signals and outbox.
- Fetched today's closed H1 candles from the chart API and recomputed every comparison against the code above.
- No M5 fetch was needed for this question.
- No POST, restart, toggle, config or code change, no messages, and no separate MT5 session.

## Defects vs correct behaviour

**All five records are correct applications of the coded rules. No defect was found.**

Two notes:
- The "close strictly inside A" rule deliberately treats strong breakouts (#4, #5) as non-setups. This is the CRT idea of sweep-and-return.
- `no_sweep` pairs and pairs during pause or downtime leave no record. This is intentional, but it means the Setups table doesn't show every hour.

## Limitations

- **Candle values:** B close values are not stored in candidate records. They come from the broker's H1 history read now, consistent with the stored high and low values; the stored highs and lows match exactly.
- **The #3 tick:** the price that invalidated #3 is not retained.
- **The unevaluated pair:** whether the app ran before 09:26 Bangkok today is not visible beyond the start/pause/resume events.

## Questions, missing requirements, or blockers

None.
