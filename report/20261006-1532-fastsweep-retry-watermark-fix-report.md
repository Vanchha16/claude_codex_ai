# Claude report: fix FastSweep retry watermark bypass

Task ID: 20261006-1532-fastsweep-retry-watermark-fix
Source prompt: `prompt/20261006-1532-fastsweep-retry-watermark-fix.md`
Parent task: 20261006-151121-activate-fastsweep-live
Status: completed — fix applied, tested, and loaded into the live server
Reported at: 2026-10-06, about 08:40 UTC (15:40 Bangkok)

(The prompt's "Project root" line reads `E:\VideCodec_trade`, an escaping typo. The work was done in the project root `E:\VideCode\vc_trade`, the same one as the source and report paths.)

## Outcome

**The bypass is closed.** A confirmed FastSweep setup that is waiting for its first quote at/after the close can no longer become a signal if its confirmation closed **at or before** the current session watermark. This holds after a restart, a resume or a feed recovery. Such a confirmation is now **consumed** as `rejected / confirmation_before_session_watermark`, not left pending to retry again. The valid strictly-after-watermark waiting path still produces exactly one signal.

**Live:** the fix is loaded with one supported restart. rr2 is still selected, the feed and scanner are healthy, Telegram is unchanged, and there are no new signals or outbox rows.

## Change

`app/fastsweep_live.py` only, plus tests:

- **New `_eligible(c)`:** the strict predicate `eligible_after is None or confirm_close > eligible_after`.
- **`_confirm()`, the common final creation gate for every path:** it checks `_eligible` **first**. If the check fails, it closes the candidate as rejected with `confirmation_before_session_watermark` and returns no signal. All later rules are untouched: active signal, cooldown, Bangkok cap, the live-quote revisit, `build_levels` (quote age, 30 s window, 5 s clock-skew tolerance), and duplicate protection.
- **`retry_awaiting()`:** it checks `_eligible` **before** the waiting-for-quote logic, so an ineligible stored confirmation is consumed immediately rather than waiting or retrying.
- **Unchanged:** the bar-close path already checked the watermark, and now also passes through the shared gate in `_confirm`.

Not changed: `config/active_strategy.json` (rr2), price rules, EMA warm-up, stop/target geometry, the feed, source and symbol, the delivery opt-in, history, the schema, credentials and the frontend.

## Reproduced before / fixed after

Script: `.tmp/wmfix/repro.py`, using a fresh temporary database, not Codex's diagnostic database.
1. `scenario` + `engine`, driven through the confirmation bar close (t0 + 35 min). The entry callback gives a quote stamped 1 s before the close and a decision 1 s after it, so the candidate stays `pending / awaiting_first_quote_after_close`.
2. A new `FastSweepEngine` on the same `SqliteStore`, with `eligible_after = confirm_close + 3 s`, then `retry_awaiting` with a fresh quote and decision at `confirm_close + 5 s`.

| | Signals created | Candidate afterwards |
|---|---|---|
| Before fix | **1** (wrong) | `confirmed` |
| After fix | **0** | `rejected / confirmation_before_session_watermark` |

## Tests added (`tests/test_fastsweep_live.py`)

- **New watermark equal to, or 3 s later than, the stored confirmation close** (`test_restart_retry_never_signals_a_confirmation_at_or_before_the_new_watermark`, parametrized):
  - 0 signals;
  - the candidate is rejected with `confirmation_before_session_watermark`;
  - the outbox is empty;
  - FastSweep family signals (the daily quota) are unchanged at 0;
  - a second retry also gives nothing (the confirmation was consumed).
- `test_retry_strictly_after_the_watermark_still_creates_exactly_one_signal`: exactly one signal, and no duplicate on a further retry.
- `test_recovery_watermark_on_the_same_engine_rejects_a_stored_confirmation`: a recovery watermark set on the existing engine rejects the stored confirmation.
- `test_scanner_restart_while_awaiting_quote_sends_nothing`:
  - a fake feed with mocked Telegram;
  - the scan at the exact close leaves the setup awaiting a quote;
  - a new `Scanner`/engine on the same database 3 s later (new watermark);
  - 0 signals, 0 outbox rows, 0 mock sends, and the candidate is rejected with `confirmation_before_session_watermark`.

None of these tests contacts the real Telegram destination.

## Tests run

| Command (with a unique project-local `--basetemp`, removed afterwards) | Result |
|---|---|
| `pytest tests/test_fastsweep_live.py tests/test_fastsweep.py` | **44 passed** (Codex's 39 + 5 new) |
| `pytest tests/test_regressions_watermark.py tests/test_regressions_reconnect.py tests/test_scanner.py` | **14 passed** |
| `pytest` (full backend) | **157 passed**, 1 deprecation warning from Starlette/httpx that was already there |

The frontend was not rebuilt or retested; it is unchanged since the parent task (28 passed there).

## Restart and live state (sanitized, read-only API)

One supported `gold.cmd restart` (PID 28644 → 38132).

| | Before restart | After restart |
|---|---|---|
| mode / symbol / feed | mt5 / XAUUSDc / ok, fresh quote | mt5 / XAUUSDc / ok, fresh quote |
| scanner | running, unpaused, no error | running, unpaused, no error |
| active strategy | fastsweep / rr2 / `FastSweep-M15-M5-v1-RR2@ca054bc1` / RR 2.0 | same (`python -m app.active_strategy`: fastsweep profile rr2) |
| Telegram | enabled, persisted, `enabled` | enabled, persisted, `enabled` (opt-in restored, "new signals only") |
| session watermark | 08:27:58Z | **08:35:39Z** (startup) |
| signals | 0 | 0 |
| FastSweep candidates | 1 (A 08:00Z: `sell_sweep_close_not_inside_a`) | 1 (unchanged) |
| outbox | 4 earlier `sent` | 4 earlier `sent`; nothing new |
| readiness | trend warm-up 42/50 | trend warm-up **42/50**; last M15 close 08:30Z, next 08:45Z |

- **No historical replay on restart:** the restart created no signal, no candidate and no outbox message.
- **First live evaluation:** the live engine evaluated its first M15 pair at 08:30Z (rejected at the range stage).
- **Readiness:** the EMA trend becomes available after 8 more contiguous M15 candles, around 10:30 UTC (17:30 Bangkok) if no gap occurs.

## Permissions

- **Reads:** no denials in this task. As instructed, I did not try to read the modified parent prompt.
- **Actions:** everything required, including the restart, completed.

## Questions, missing requirements, or blockers

None.
