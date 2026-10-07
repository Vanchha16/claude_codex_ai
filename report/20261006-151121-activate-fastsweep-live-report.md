# Claude report: integrate and activate FastSweep RR2 on the live gold scanner

Task ID: 20261006-151121-activate-fastsweep-live
Source prompt: `prompt/20261006-151121-activate-fastsweep-live.md`
Status: completed — FastSweep 1:2 is live. One open question about a prompt change made during execution (see "Blocker / question").
Reported at: 2026-10-06, about 08:35 UTC (15:35 Bangkok)

## Outcome

FastSweep-M15-M5-v1 with the user-selected **1:2 profile (rr2)** is integrated and **running live** on the existing MT5 XAUUSDc feed and scanner, with the existing Telegram opt-in preserved.

- **Version:** `FastSweep-M15-M5-v1-RR2@ca054bc1`.
- **Restart:** one supported `gold.cmd restart` (PID 24304 → 28644) after all checks passed.
- **Fixes:** both review defects are fixed and covered by regression tests.
- **CRT preserved:** CRT-SMC-v1 remains selectable for rollback, and all history is preserved.
- **No messages:** no manual test message, fabricated signal or historical backfill was sent.

## Blocker / question (please review)

**What happened:** while I was executing, after all checks had passed and immediately after the activation restart completed, the monitor reported that `prompt/20261006-151121-activate-fastsweep-live.md` **was modified**. I tried to read the modified file, but **Claude Code's permission system denied that read**. I did not try to get around the denial, so **I have not seen the change**.

**What I did instead:**
- Everything in this report follows the version of the prompt I read at the start: approved, profile rr2, activation authorized.
- The service was already restarted under that version. I verified it is healthy (below) and left it running, because the prompt forbids leaving a broken server, and an unseen edit is not grounds for a further live change.

**What I need from Codex:** if the modification changes the scope (for example, a hold or a different profile), tell me and I will act on a separately approved instruction.

**Rollback** is one command plus a restart:

```
.venv/Scripts/python.exe -m app.active_strategy crt
gold.cmd restart
```

## Pre-change snapshot (sanitized)

Saved to `.tmp/activate/pre-snapshot.json`:
- mode `mt5`, XAUUSDc, feed ok;
- scanner running, unpaused, no error;
- watermark 2026-10-06T05:50:43Z;
- strategy `CRT-SMC-v1@193949a6`;
- Telegram enabled with the persisted opt-in;
- 0 signals, 0 active signals, 17 candidates, 0 pending;
- outbox: 4 earlier `sent` test messages.

## What was implemented

1. **Selection:** `app/active_strategy.py` with `config/active_strategy.json`.
   - The file contains `{"strategy": "fastsweep", "profile": "rr2"}`. With no file, CRT runs.
   - Unknown strategies, unknown profiles, extra keys and invalid JSON stop startup with a clear error.
   - Saving is validate-then-atomic-replace; there is a CLI `python -m app.active_strategy [crt | fastsweep rr1|rr2]`.
   - Effective settings are fingerprinted into the version (`…-RR2@ca054bc1`; RR1 differs).
   - CRT keeps `config/strategy.json` unchanged.
   - `Workstation`/`create_app` accept an injectable `active_strategy_loader`. The existing API tests now inject CRT explicitly, so they no longer depend on the workspace selection.
2. **Live engine:** `app/fastsweep_live.py` `FastSweepEngine`, reusing `app/fastsweep.py` rule functions unchanged.
   - **Stored in the existing tables, no schema change.** In candidate records: `level` = B high (BUY) / B low (SELL), `deadline` = B close + 3 M5 bars, `last_bar_close` = confirmation progress. The key and `config_version` include the fingerprinted version.
   - **Bar processing:** each closed M5 bar is processed once, and M15 A/B is evaluated only at B's close from complete closed M5 groups (`aggregate`).
   - **Trend:** the EMA uses the contiguous M15 run ending at B inside a 600-bar M5 window. It has the same SMA seed and ≥ 50-candle readiness as the replay, and no future bars.
   - **Own records only:** the engine processes only records with its own version. Pending setups of another strategy or profile are closed as `expired / retired_strategy_switch` (`retire_foreign_pending`), never evaluated. This applies to both engines at creation.
3. **Scanner and web integration** (`app/scanner.py`, `app/web.py`):
   - **Single path:** the same single scanner, feed lock and owner. Pause/resume, reconnect and the session watermark are unchanged; only confirmations closing **strictly after** the watermark can alert. Historical confirmations become `confirmation_before_session_watermark` with no signal, no outbox row and no quota use.
   - **API:** `/api/state` adds `active_strategy` (kind, profile, version, label, RR, rules, controls). `timeframes` now follows the active strategy (M15/M5). `strategy` holds the active parameters, and `crt_strategy` keeps the CRT config.
   - **Records:** candidate and signal API rows carry `strategy` and `range_tf` (FastSweep M15; historical CRT keeps H1).
   - **Strategy state:** FastSweep has its own state (trend warm-up with readiness and ETA, pending M5 confirmation, last M15 pair, next M15 close).
4. **Review defect 1 (midnight):** `_daily` in `app/fastsweep_replay.py` now spans every Bangkok date touched by a bar open or a candidate, confirmation or signal time. A date it adds this way has 0 bars, so it is never counted as covered. Exact-midnight regression test added.
5. **Review defect 2 (entry timing):** `build_levels` rejects:
   - an entry more than 30 s after the confirmation close, even with a fresh quote (`missed_confirmation_too_late`);
   - a quote older than the confirmation;
   - a quote later than the decision time (`quote_in_future`; live allows the scanner's existing 5 s clock-skew tolerance, replay allows 0);
   - stale, invalid or too-wide quotes.

   Tests cover a fresh quote 10 minutes late and future quotes.
6. **Live entry semantics:**
   - **Waiting for a quote:** the scanner treats a bar as closed by clock time, so the first scan can hold a quote stamped just *before* the confirmation close. To honour the rule "first observation at/after the close", a confirmed setup **waits** (still pending, `confirm_close` set, reason `awaiting_first_quote_after_close`) and is retried each scan for up to 30 s. It is then entered or rejected; it is never filled late.
   - **Before entry:** the current measured Bid is checked for a revisit of B's sweep extreme (`sweep_extreme_revisited_live_quote`). A completed-bar revisit still takes precedence over a same-bar confirmation.
7. **Controls from persisted signals** (restart- and profile-switch-safe):
   - one active signal per symbol (any strategy, including a pre-existing CRT signal);
   - ≥ 30 min since the last **FastSweep-family** signal (any profile or version);
   - ≤ 4 FastSweep-family signals per Bangkok date (CRT signals and rejected or past-context candidates are excluded);
   - atomic duplicate protection (`INSERT OR IGNORE` on the signal ID plus the candidate key).
8. **Outcomes:** `app/outcomes.py` now uses each signal's own `meta.outcome_expiry_hours`, which is 2 h for FastSweep. Older signals without it keep the CRT 24 h. Measured Bid/Ask tick tracking and gap handling are unchanged.
9. **Telegram:** unchanged four-line emoji Entry/TP/SL/RR body. FastSweep signals carry symbol metadata, so prices print at symbol precision.
10. **Dashboard** (`frontend/src/index.template.html`, `app/static/app.js`, rebuilt):
    - **Labels from the active strategy:** header "M15 / M5 · FastSweep · 1:2", "Strategy state (FastSweep · 1:2)", "Last closed M5 · M15 trend 41/50 (warm-up)", the config panel version, and generic sidebar/chart wording.
    - **Labels from each record:** detail rows show the strategy and version, and "A candle (H1|M15)". The evidence groups say "Range · H1|M15" and "Confirmation · M5 (break of B)" for FastSweep.
    - **Replay:** a strategy choice of "CRT-SMC-v1 (legacy, not active)" or "FastSweep (active)". FastSweep replays use the shared rules in memory (OHLC only, ticks disabled, MT5 only), read history under the scanner's feed lock (no second MT5 session), and are saved separately as `latest-mt5-fastsweep.json`. CRT results are explicitly labelled as not FastSweep.
11. **Docs:** README "Active strategy selection" covers the selection, the rollback commands, live behaviour, the warm-up behaviour and the user-authorized activation, and keeps the negative research evidence. The research section is retitled accordingly.

## Files changed

- **New:** `app/active_strategy.py`, `app/fastsweep_live.py`, `tests/test_fastsweep_live.py` (21 tests), `config/active_strategy.json`.
- **Modified:**
  - `app/fastsweep.py` (`build_levels`)
  - `app/fastsweep_replay.py` (`_daily`)
  - `app/scanner.py`
  - `app/web.py`
  - `app/outcomes.py` (per-signal expiry)
  - `app/static/app.js`
  - `frontend/src/index.template.html`
  - `tests/test_fastsweep.py` (one assertion now expects `missed_confirmation_too_late`, which precedes `stale_quote`)
  - `tests/test_api.py`, `tests/test_live_market.py` (inject the CRT selection)
  - `README.md`
- **Regenerated:** `app/static/index.html` and `app/static/dist/app.css`.
- **Not changed:** CRT rules and config (`app/strategy.py`, `app/engine.py`, `app/replay.py`, `config/strategy.json`), the delivery code, the database schema and history, and the Telegram settings and opt-in.

## Checks actually run

- **Focused:** `pytest tests/test_fastsweep_live.py tests/test_fastsweep.py` gave 36 passed. Three live tests first failed for test-design reasons:
  - the bare engine doesn't track outcomes, so active signals blocked later setups;
  - a scan exactly at the close held an earlier-stamped quote.

  The second exposed a real live-entry gap, which I fixed (item 6). Nothing was weakened.
- **Full backend:** `pytest` with a unique project-local `--basetemp` gave **152 passed** (113 existing + 18 replay + 21 live), with 1 Starlette/httpx deprecation warning that was already there. The temp dirs were path-checked and removed.
- **Frontend:** `npm run build` OK; `npm test` **28 passed**; `node --check` on every `app/static/*.js` OK.
- **New tests cover:**
  - selection, fingerprints and invalid choices (including a clear startup failure);
  - live/replay parity of range, trend and confirmation decisions, and identical 1:2 geometry;
  - EMA warm-up;
  - invalidation precedence and the live-quote revisit;
  - restart without duplicates;
  - the watermark edge (exactly at the watermark gives no signal, strictly after gives a signal);
  - persisted cooldown across profiles, and the Bangkok cap (excluding CRT, with previous-date signals not counting);
  - an active CRT signal blocking FastSweep while keeping its 24 h expiry;
  - the 2 h FastSweep expiry;
  - foreign pending setups retired;
  - the four-line message at 3-digit precision;
  - the scanner with a fake feed: a live signal after the watermark delivered once as four lines with no `parse_mode`, a restart after confirmation sending nothing, and pause tracking outcomes while resume cancels pending;
  - waiting for the first quote after the close (and rejection after 30 s);
  - API labels and replay identity;
  - the midnight daily table;
  - the late and future quote fixes.

  All use fake feeds, mocked Telegram and project-local temp databases.
- **Cached replay comparison after the fixes:** both profiles were re-run on the identical cached bars into `.tmp/fastsweep/post-fix/`. Segments, every signal, the daily table, frequency and every candidate are **identical** to the original results (RR1 −19.3372R, RR2 −17.7181R; 2.317 signals per covered date; 46.3% of dates with 3–4). The fixes do not affect that sample.
- **Browser** (read-only, a 1536 px iframe on the live dashboard):
  - the labels shown above, and the replay strategy options;
  - FastSweep replay with ticks disabled, and the CRT replay result labelled "not the FastSweep strategy";
  - no console errors;
  - the browser's stored section and theme preferences restored afterwards.

## Activation result (sanitized live state after restart)

| Item | Value |
|---|---|
| Server | PID 28644, http://127.0.0.1:8000/ |
| Feed | MT5 XAUUSDc, ok, fresh quote |
| Scanner | running, unpaused, no error |
| Active strategy | `fastsweep` / `rr2`, `FastSweep-M15-M5-v1-RR2@ca054bc1`, reward/risk 2.0, M15/M5 |
| Session watermark | 2026-10-06T08:27:58Z (startup) |
| Telegram | enabled, persisted opt-in restored (`restored the explicit opt-in … (new signals only)`) |
| Readiness | **trend warm-up 41/50** contiguous M15 candles; EMA trend available around **10:30 UTC (17:30 Bangkok)** if no gap |
| Next evaluation | each M15 close (next was 08:30 UTC). Pairs before readiness are recorded as `trend_warmup` |
| Records | 17 historical CRT candidates unchanged; 0 FastSweep candidates yet; 0 signals; no CRT pending setup needed retiring |
| Outbox | unchanged: 4 earlier `sent` test messages; nothing new queued |

Startup event: "VC Signal started: LIVE MT5 (XAUUSDc); strategy FastSweep-M15-M5-v1-RR2@ca054bc1; external delivery ON (restored explicit opt-in)".

## Limitations and notes

- **Evidence:** the activation does not change the evidence. In replay, both profiles were negative, and 3–4 signals occurred on only 46% of covered days.
- **Daily warm-up:** after every daily market break, roughly the first 12.5 hours produce no setups (`trend_warmup`). Today's first possible FastSweep setup is after about 10:30 UTC.
- **Live costs:** live entries use the measured Bid/Ask, not the replay's assumed spread.
- **Outcome tracking:** outcomes remain simulated price observations. No order is ever placed, modified or closed.
- **Dashboard replay:** the FastSweep option is OHLC only. It reads M5 history via the existing connected feed under the scanner lock, so a long request briefly delays a scan.

## Questions, missing requirements, or blockers

- **The prompt changed mid-task, and I could not read it** (see the top section). Please confirm whether the change affects the completed activation.
- No other blockers.
