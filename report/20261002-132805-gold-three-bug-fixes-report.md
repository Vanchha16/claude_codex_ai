# Claude report: fix the three confirmed gold signal bugs

Task ID: 20261002-132805-gold-three-bug-fixes
Source prompt: `prompt/20261002-132805-gold-three-bug-fixes.md`
Status: completed
Reported at: 2026-10-02

## Outcome

All three defects Codex reproduced are fixed. The agreed CRT-SMC-v1 rules and defaults are unchanged.

**Approval gate:** passed. The prompt has `APPROVED FOR EXECUTION`, a Task ID, Source prompt, Report path and a browser-button `User authorization:`. Its draft SHA-256 `2ec58071…29c0` matches `prompt/drafts/20261002-132805-gold-three-bug-fixes.md`.

New regression tests reproduce each original failure before the fix and pass after it. The full suite is **80 passed**: 63 existing tests plus 17 new ones.

## Files changed

| File | Change |
|---|---|
| `app/engine.py` | Adds `Engine.eligible_after`, the session eligibility watermark. A confirmation whose bar closed at or before it is consumed as `rejected / confirmation_before_session_watermark`. No entry check runs and no `Signal`, active position or outbox job is created. |
| `app/scanner.py` | Keeps an in-memory session watermark that is never restored from the database. It is opened on the first healthy scan after process start or restart, on Resume, and on recovery after a disconnected feed or stale quotes. While the feed is unhealthy, candidates are not advanced; outcome tracking continues. The old `created_at >= live_start` delivery filter is removed, because the engine now stops ineligible signals before any side effect. |
| `app/replay.py` | Tick replay is chronological and bounded to the replay period. The MT5 CLI keeps the feed open through the replay and closes it in `finally`. Adds a `feed_factory` test hook. An explicit `--out` no longer overwrites the dashboard's `latest-*.json`. |
| `README.md` | Documents the watermark rules (boundary, reset events, unhealthy-feed behaviour) and the tick-replay rules and limitations. |
| `tests/test_regressions_watermark.py` | New: 6 regressions for bug 1. |
| `tests/test_regressions_replay.py` | New: 11 regressions for bugs 2 and 3. |
| `tests/test_scanner.py` | One assertion updated: the existing "startup after confirmation" test now expects the more specific reason `confirmation_before_session_watermark` instead of `missed_confirmation_too_late`. It still checks that no signal and no send happen. |

No other files were changed. The dashboard UI, store schema, dedup keys, pause/resume, outcome tracking and the task panel (`tools/`) are untouched.

## Repairs

### 1. Startup, restart and reconnect eligibility

**Rule:** a confirmation is actionable only if `confirm_close > session_watermark` (strictly greater). A close equal to the watermark closed before this session could observe it live.

**What resets the watermark** (to the time of that scan):
- the first healthy scan of a new Scanner, i.e. process start or restart;
- `resume()`;
- the first healthy scan after any scan where the feed status was not OK or the quote was stale (older than 30 s or invalid).

**What does not reset it:** ordinary healthy scans.

**Other effects:**
- The `live_start` value in the database now only records the current watermark for display; it is never read back to authorise anything.
- Warm-up context (H1 ranges, swings, pending candidates) is still built from history.
- Active simulated positions keep being tracked through restarts, and persistent deduplication is unchanged.

### 2. Chronological tick replay

- **Order:** on each M5 close the replay first advances every active position using only ticks in `(last_checked, bar close]`, then processes candidates. An exit is settled at its own tick timestamp, so the overlap guard is released only after the observed exit.
- **Bounds:** every tick read goes through one filter. Ticks are clipped to the requested window **and** the replay period end, invalid quotes are dropped, and the rest are sorted by time. A callback that ignores bounds or ordering cannot leak future or out-of-period ticks.
- **Entry:** the first valid tick in `[confirm close, confirm close + 30 s]` inside the period. If there is none, there is no fill.
- **Exits:** BUY exits use Bid and SELL exits use Ask, from actual ticks. TP fills at TP; SL applies the configured stop slippage. The entry fill keeps the existing slippage semantics.
- **Expiry:** at `created_at + 24 h`, only once the replay clock reaches it. The position is marked at the last observed exit-side tick before expiry, or with no R if none was observed.
- **End of history:** a position still open becomes `open_at_end`.
- **Unchanged:** candidate invalidation still uses closed M5 bars only, which uses no future information.

### 3. MT5 replay lifecycle

`connect`, bar reads, the lazy `ticks_range` reads and the replay all happen inside one `try`, with `feed.shutdown()` in `finally`. Cleanup happens exactly once on:
- success;
- a failed connect (partial initialisation);
- a tick-read or replay error.

## Regression evidence

**Before the fix** (`pytest --basetemp .tmp/pytest/before-fix` on the new tests): `11 failed, 6 passed`. Saved in `.tmp/pytest/before-fix-summary.txt`.
- Startup 5 s after confirmation: a signal was created, then queued and sent through mocked Telegram.
- Restart across confirmation with persisted history: a signal was created.
- Recovery 5 s after a disconnect: a signal was created.
- Recovery after stale quotes: no signal, but the wrong reason (`quote_older_than_confirmation_close`).
- Tick replay truncated before TP: `tp` was reported after the period end, in both normal and sloppy-callback variants.
- Entry tick after period end: a fill was made outside the period.
- Overlap test: a future exit released the guard, so 2 signals were created instead of 1.
- MT5 CLI tests: errors, because the test hook did not exist yet. The original bug was reproduced directly by patching in the fake feed: `ticks_range called after shutdown | events: ['connect', 'bars:M5', 'bars:H1', 'shutdown']` (saved in `.tmp/pytest/before-fix-mt5.txt`).

**After the fix:** `.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .tmp/pytest/after-fix` gave **80 passed**. The one warning is Starlette's TestClient deprecation, not this code.

The new regressions cover:
- startup 5 s after a confirmation (no signal, active position, outbox job or mocked send);
- restart across a confirmation with persisted history;
- recovery within 30 s after a disconnect and after stale quotes;
- a new eligible confirmation creating one signal and one mocked alert, with repeat scans not duplicating it;
- a restart that keeps tracking an existing active position to TP, without duplicate candidates;
- tick replay truncated before a future TP (strict and sloppy callbacks) → `open_at_end`;
- an entry tick after the period end → no fill;
- missing ticks → no fill or price hit;
- the overlap guard with the first exit before and after the second confirmation;
- SELL exits on Ask and BUY exits on Bid;
- the MT5 CLI reading ticks before shutdown, plus cleanup on tick errors and on a failed connect.

## Validation actually performed

- The full suite and regressions, as above. Test databases and temp files are under `.tmp/pytest/`.
- `gold.cmd replay --source demo`: same fictional results as before (development: 2 TP; holdout: 1 SL). The OHLC path is unchanged.
- `gold.cmd restart`, needed so the dashboard runs the repaired code:
  - `/api/health` → `{"app":"vc-trade-gold-signals","pid":27448,"mode":"demo","scanner_running":true}`
  - `/api/state` → Telegram `configured: false, enabled: false`; scanner error none.
  - Event log: `session watermark 2030-01-07T05:30:05Z (startup)`.
  - The first fictional BUY confirmation at 06:10:00 (after the watermark) created exactly one signal.
  - `/api/outbox` is `[]`.

## Local server state

| | |
|---|---|
| URL | http://127.0.0.1:8000/ |
| PID | 27448 |
| Mode | DEMO, external delivery OFF |
| Log | `.tmp/gold-signals/server.log` |
| Commands | `gold.cmd status`, `gold.cmd stop`, `gold.cmd restart` |

The separate task panel was not touched.

## Remaining limitations

- **Tick replay:** prices between ticks are not interpolated; a TP/SL touched only between two observed ticks is missed. Candidate invalidation in replay uses closed M5 bars, not ticks.
- **Tick entry timing:** the entry tick can be up to 30 s after the confirmation close. The signal is recorded in that bar's iteration, timestamped at the tick.
- **Long stale periods (for example weekends):** they pause candidate processing. At the next healthy scan a new watermark opens, so anything that would have confirmed during the gap is consumed as non-actionable. This is by design.

## Unavailable real integrations

- **MT5:** no MetaTrader 5 terminal or symbol was used. All MT5 lifecycle checks used a mock feed, and no broker connection was made.
- **Telegram:** no real messages were sent. All delivery checks used `httpx.MockTransport`, and external delivery stayed off.

## Questions, missing requirements, or blockers

None.

## Suggested next step

Codex reviews these fixes. Real MT5 and Telegram checks remain for a separately approved task once the user has configured the terminal, `GOLD_SYMBOL` and the test bot.
