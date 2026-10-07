# Claude report: investigate why the latest setup was invalidated

Task ID: 20261005-112721-investigate-last-setup-invalidation
Source prompt: `prompt/20261005-112721-investigate-last-setup-invalidation.md`
Status: completed (read-only investigation)
Reported at: 2026-10-05, about 04:35 UTC (11:35 Bangkok)

## Summary for the user

**What it was.** This was a **pending BUY setup (#3), not a signal.** It was never confirmed, so it never produced Entry/TP/SL/RR and nothing was sent to Telegram.

**The setup.**
- The 09:00–10:00 Bangkok H1 candle (A) ranged from 4139.409 to 4163.288.
- The next H1 candle (B) dipped to **4136.171**, sweeping below A's low, then closed back inside at 4143.143.
- To become a BUY signal, an M5 candle then had to **close above 4162.945**, the last confirmed swing high inside A, before 12:00 Bangkok.

**What happened.**
- Price never got near that level. The M5 closes after B were 4139.735 and 4139.648, about 23 below the trigger.
- Price then **fell back through the sweep low**. At **11:14:08 Bangkok (04:14:08 UTC)** a live Bid tick at or below 4136.171 invalidated the setup.
- The 11:10 Bangkok M5 candle shows the drop: low 4134.801, which is below 4136.171.

**Why it was invalidated.** A BUY setup is invalidated when price falls back through the sweep extreme, because the "liquidity grab and reversal" idea has failed. The result matches the implemented rule exactly, and I found no defect.

## Evidence and sources (all read-only)

### Candidate record

Source: `GET /api/chart?candidate_id=3`, local API.

| Field | Value | Bangkok (UTC+7) |
|---|---|---|
| id / key | 3 / `XAUUSDc\|2026-10-05T02:00:00Z\|CRT-SMC-v1@193949a6` | |
| direction / status / reason | BUY / **invalidated** / `sweep_extreme_revisited_live_tick` | |
| A candle (H1) | open 2026-10-05 02:00 UTC; high **4163.288**, low **4139.409** | 09:00 |
| B candle (H1) | 03:00–04:00 UTC; high 4146.705, **low 4136.171** (the sweep extreme) | 10:00–11:00 |
| frozen M5 structure level | **4162.945** (pivot high at the 02:25 UTC bar, usable from 02:40 UTC) | 09:25 / 09:40 |
| confirmation deadline | 2026-10-05 05:00 UTC | 12:00 |
| confirm_close | **null** (never confirmed) | |
| updated_at (the invalidating tick time) | **2026-10-05T04:14:08.861Z** | **11:14:08.861** |

### Events

Source: `GET /api/events`.

| UTC | Bangkok | Event |
|---|---|---|
| 04:00:04.929 | 11:00:04 | `candidate`: "BUY candidate A=2026-10-05T02:00:00Z: pending" |
| 04:05:09.414 | 11:05:09 | `scanner`: "session watermark … (startup)", from the controlled restart in task 20261005-110033 |
| 04:14:08.861 | 11:14:08 | `invalidated`: "BUY 2026-10-05T02:00:00Z: sweep_extreme_revisited_live_tick" |

Other records:
- **Signals:** `GET /api/signals` returns 0 signals in this session, so no signal ever existed for this setup.
- **Outbox:** contains no signal rows.

### Bar data

Source: `GET /api/market/bars`. These are the chart's Bid OHLC bars from the running server's existing MT5 feed; symbol digits 3, tick size 0.001.

H1 bars:

| UTC | Bangkok | O | H | L | C |
|---|---|---|---|---|---|
| 02:00 (A) | 09:00 | 4160.081 | 4163.288 | 4139.409 | 4142.993 |
| 03:00 (B) | 10:00 | 4142.683 | 4146.705 | **4136.171** | 4143.143 |

The M5 bars that define the structure level, a pivot high with 2 bars on each side:

| UTC | Bangkok | H |
|---|---|---|
| 02:15 | 09:15 | 4160.852 |
| 02:20 | 09:20 | 4161.180 |
| **02:25** | **09:25** | **4162.945** (pivot) |
| 02:30 | 09:30 | 4159.584 |
| 02:35 | 09:35 | 4155.633 (the pivot becomes usable when this bar closes, at 02:40) |

The M5 bars after B closed:

| UTC | Bangkok | O | H | L | C | vs level 4162.945 | vs sweep 4136.171 |
|---|---|---|---|---|---|---|---|
| 04:00 | 11:00 | 4143.364 | 4143.647 | 4139.693 | 4139.735 | close 23.210 below | low above |
| 04:05 | 11:05 | 4139.788 | 4141.310 | 4138.367 | 4139.648 | close 23.297 below | low above |
| **04:10** | **11:10** | 4139.828 | 4139.828 | **4134.801** | 4134.801 | close below | **low 1.370 below the sweep** |
| 04:15 | 11:15 | 4135.098 | 4135.892 | 4130.825 | 4133.224 | (setup already invalid) | |

## Code trace

### Live-tick invalidation

- **Where it runs:** `app/engine.py` → `on_quote()`, at about lines 209–218. It runs on every scan for each pending candidate, once `quote.time >= b_close`.
- **What it calls:** `invalidation_by_quote(setup, quote)` in `app/strategy.py`, at about lines 164–166, which runs `invalidation_by_price(setup, quote.bid, quote.bid)`.
- **Price field:** **Bid**, the same series as the chart and bar data.
- **Rule for BUY** (`app/strategy.py`, `invalidation_by_price`, about lines 131–141):
  - `low <= sweep_extreme` gives `sweep_extreme_revisited`;
  - otherwise `high >= a_high` gives `opposite_boundary_touched`.
- **Comparisons are inclusive** (`<=` / `>=`), and the sweep check runs first.
- **Effect:** the engine appends `_live_tick` to the reason, sets `updated_at` to the **tick's own time** (`quote.time`, MT5 UTC epoch), stores the candidate and adds the event.

So the recorded fact is that a quote at 04:14:08.861 UTC had **Bid ≤ 4136.171**.

### Bar-close confirmation (never reached)

- **Where it runs:** `app/engine.py` → `on_m5_bar()` → `confirm_step()` in `app/strategy.py`, at about lines 144–161, for each newly closed M5 bar.
- **Order of checks:**
  1. the deadline;
  2. continuity;
  3. invalidation by the bar's high and low;
  4. confirmation: for a BUY, `prev.close <= level < bar.close` and the close must be inside A.
- **Same-bar priority:** invalidation beats confirmation in the same bar.
- **Watermark:** a confirmation is actionable only if its close is after the session watermark (`eligible_after`).
- **Deadline:** `b_close + confirm_max_bars(12) × 5 min` = 04:00 + 60 min = 05:00 UTC, which matches the record.

### Was there an eligible M5 confirmation before the invalidation?

No.
- The only M5 bars that closed between B's close and the invalidation were 04:00 (closed 04:05) and 04:05 (closed 04:10). They closed at 4139.735 and 4139.648, both far below the 4162.945 level, so no cross occurred.
- The watermark is irrelevant here: no confirmation existed to be accepted or rejected.
- The 04:10 bar, closing at 04:15, would have invalidated the setup by its own low (4134.801 ≤ 4136.171) even without the live-tick check.
- The live tick merely caught it about 52 s earlier.

### Does the result match the rule?

Yes, consistently:
- it was a BUY, so the sweep extreme is B.low = 4136.171;
- price went back below it during the 04:10 M5 bar, and the bar's low is 4134.801;
- a Bid tick inside that bar's interval (04:14:08.861) triggered the inclusive `<=` check.

The opposite-boundary rule (A high 4163.288) was never touched after B.

**The restart did not affect this setup.** The controlled restart at 04:05:09 UTC (11:05:09 Bangkok) happened while the candidate was pending; the candidate persisted and continued to be checked normally. A restart only moves the watermark, which matters for confirmations, not invalidations.

No defect found, so no fix is proposed.

## Limitations: observed vs inferred

- **Exact tick price not retained.** The app stores the invalidating tick's **time** (`updated_at` = 04:14:08.861Z) and the reason, but **not its Bid value**. The event message has no price either.
  - Proven: Bid ≤ 4136.171 at that time.
  - Supporting evidence: the 04:10–04:15 M5 bar's Bid low of 4134.801.
  - The exact tick Bid is not available.
- **I didn't fetch MT5 tick history.** The app has no API for it, and the prompt forbids a separate MT5 initialization or a competing session, so I did not use one.
- **Bar values come from the live MT5 feed** through the app's chart endpoint. They are the broker's current history for those bars, read just now; they are not a snapshot the scanner stored at decision time. They match the stored candidate fields exactly: A high/low, B low and the pivot level.

## Current state

Unchanged by this investigation, which used only GET requests:
- live MT5 (XAUUSDc), feed ok;
- scanner running, unpaused;
- Telegram delivery on (persisted opt-in);
- session watermark 04:05:09Z;
- no signals, and no new candidate since #3 at the time of reading.

## Actions performed

- Wrote the progress receipt.
- Read `/api/chart?candidate_id=3`, `/api/events`, and `/api/market/bars` for M5 and H1, saved to temporary files under `.tmp/` and deleted afterwards.
- Read `.tmp/gold-signals/server.log` (event lines only, filtered).
- Read `config/strategy.json` and the code in `app/strategy.py`, `app/engine.py` and `app/web.py`.
- No edits, restart, toggles, setup submissions, replay, resends or messages.

## Questions, missing requirements, or blockers

None.

## Suggested next step

None required. Optionally, Codex could propose storing the invalidating tick's Bid in the event message, so future invalidations show the exact price. That would be a separate, approved change.
