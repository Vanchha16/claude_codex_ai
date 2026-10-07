# Claude report: MT5 time fix and FVG activation on the demo account

Task ID: 20261007-143838-fvg-demo-time-fix-activation
Source prompt: `prompt/20261007-143838-fvg-demo-time-fix-activation.md`
Inputs read:
- `report/20261007-142425-mt5-server-time-offset-finding.md`
- `report/20261007-142425-mt5-server-time-offset-codex-review.md`
- `.tmp/mt5-time-codex-review/feed-executor-offset-reproduction.json`
- the in-task note `prompt/20261007-143838-fvg-demo-time-fix-activation-codex-review-notes.md` (addressed, see 3.4)
Date: 2026-10-07

## 1. Outcome

- **Phase 1 (time contract): done and tested.** There is now one UTC-normalisation contract for every MT5 timestamp. The offset is explicit, verified and bound to the server name. The feed and the FVG executor share it. A server or account change resets the session.
- **Phase 2 (activation): done.**
  - FVG rr2 is selected and running in the restarted local backend (PID 18424, single owner) on MetaQuotes-Demo (demo), XAUUSD.
  - Quotes are fresh and advancing. The newest closed M5 bar matches current UTC.
  - M15 readiness is **39/50 (warm-up, not ready)**.
- **Automatic execution is OFF and Telegram is OFF.**
- **Zero real orders, zero `order_check`/`order_send` calls, zero Telegram messages.** No arming, no opt-in file, no test order, no account switch, no credential access. `.env` and `server.json` were not read or printed.

## 2. Verified time evidence (read-only; no login, token or credentials recorded)

**Observations before the fix.** These were read-only reads of the running old backend (FastSweep) through `/api/state` and `/api/market/bars`, around 07:40:23–07:41:13Z:

- The host clock was `2026-10-07T07:40:23Z`. An external HTTP `Date` header gave `Wed, 07 Oct 2026 07:40:24 GMT`, so the host clock is correct to within about 1 s.
- Four quote samples were taken about 12 s apart:

  | Host UTC | Quote time | Quote age |
  |---|---|---|
  | 07:40:25 | 10:40:19.804 | −10799.1 s |
  | 07:40:37 | 10:40:35.477 | −10799.8 s |
  | 07:40:49 | 10:40:45.048 | −10799.3 s |
  | 07:41:01 | 10:41:00.430 | −10799.7 s |

  The quote times **advance with wall time** at a constant lead of 3 h, less sub-second delivery latency. That is a clock offset, not stale data: a stale tick would not advance, and its age would be positive.
- The newest forming M5 bar (`copy_rates_from_pos`) had epoch `1791369600` = 10:40:00Z while true UTC was 07:41. The rates carry exactly the same +3 h.

**Documentation.** The MetaTrader5 Python docs (`copy_rates_range`) say the terminal stores times "in UTC time zone (without the shift)" and that range datetimes should be UTC. The observed server contradicts this. The docs (`symbol_info_tick`, `MqlTradeRequest.expiration`, `ORDER_TIME_*`) do not state a time base for tick times or the pending expiration. `TimeTradeServer` describes trade-server time, computed in the terminal.

**Conclusion and contract.** On this server, broker epoch = UTC + 3 h for ticks and rates. The order expiration is treated in the same broker base, so the 2 h lifetime stays 2 h for the broker. Every value is converted exactly once:
- incoming tick and rate epochs: `to_utc`
- outgoing range datetimes and the expiration: `to_broker`
- reconciliation history ranges: `to_broker`, widened by ±1 day; rows are still matched only by ticket, comment and magic.

The +3 entry is bound to `MetaQuotes-Demo` only. Other servers keep documented UTC unless they get their own verified entry or the explicit legacy env offset.

**After the fix.** Read-only `/api/state` samples at 07:48:03–07:48:35Z showed:

| Field | Value |
|---|---|
| Quote age | 0.8, 0.7, 0.1 s; `fresh: true`; no note |
| Last closed M5 | open 07:40, close 07:45 (sampled at 07:48: the newest closed bar) |
| Time base | `{"server": "MetaQuotes-Demo", "utc_offset_hours": 3.0, "source": "mt5_time.json (verified for this server)"}` |
| Session watermark | 07:47:47Z |

## 3. Files changed and behaviour

### 3.1 Time contract

- **`app/mt5_time.py` (new).**
  - `TimeBase(offset_hours, server, source)` with `to_utc()` and `to_broker()`. `to_broker` refuses naive datetimes.
  - `load_server_offsets()` reads `config/mt5_time.json` and validates it: numbers only, within ±14 h, in quarter-hour steps. An invalid file raises an error, so the app fails closed.
  - `resolve_time_base(server, legacy)` picks the verified entry for that exact server, else the explicit legacy `GOLD_MT5_SERVER_UTC_OFFSET_HOURS`, else UTC.
  - Nothing is ever inferred from a tick. Codex's caution about single-tick inference is followed.
- **`config/mt5_time.json` (new, non-secret).**
  - `{"servers": {"MetaQuotes-Demo": {"utc_offset_hours": 3, "verified_at": "2026-10-07T07:41:01Z"}}}`.
  - Its comment records the evidence and the expected DST change (to +2 around 2026-10-25), which needs re-verification.
- **`app/data/mt5.py`.**
  - The feed resolves its time base for the connected server on every `connect()` and reports it in status details (`time_base`). An invalid time config gives a `error` status, not a guess.
  - `_utc` and `_req` delegate to the time base, so quotes, `closed_bars`, `chart_bars` and range or tick requests are each converted once.
  - `status()` treats a changed **trade server**, or a changed **account on the same server**, as a disconnect. Account changes are detected with a private sha256 of server+login that is never shown or stored. The scanner's existing unhealthy → reconnect → **new session watermark** path then runs under the newly resolved time base.
  - `legacy_utc_offset_hours` is still reported when the legacy env applies.

### 3.2 FVG executor (same contract, under the same feed lock)

`app/fvg_execution.py`. `MT5FvgExecutor` takes `timebase_fn`, which the workstation sets to the connected feed's time base.
- `_context` refuses execution if the account's server differs from the time base's server. Quote age is `now − to_utc(tick)`, so a +3 h tick is fresh under the verified base. Under a wrong base it is still rejected, and a genuinely stale tick is still stale.
- The expiration is `to_broker(expires)`. The journal payload records the `time_base` it used.
- `reconcile` queries the history in broker time with a ±1 day margin, so a mis-set offset cannot hide a plan's deals.

Default policy, journal, ownership, locking and zero-request-when-OFF are unchanged.

### 3.3 Wiring, status and documentation

- **`app/web.py`.** `_mt5_timebase()` is passed to both the armed and the maintenance executors. `/api/setup` exposes `time_base`.
- **`app/scanner.py`.** When a quote is stale or in the future by about a whole quarter-hour multiple of at least 0.9 h, the quote note adds: "the quote is ~N h ahead/behind: the MT5 server time offset may be wrong or changed, e.g. DST; verify config/mt5_time.json". This is a statement of fact only; nothing is shifted automatically.
- **`README.md`.** The Time paragraph is rewritten (verified per-server contract, DST behaviour, server/account change → new session), and a layout row for `config/mt5_time.json` was added.

### 3.4 Codex in-task note

Codex observed that a same-server account change was not detected. **Fixed**: see the identity check in 3.1. The scanner-level test below shows a new, later session watermark after the account changes.

### 3.5 Tests

`tests/test_mt5_time.py` is new, with 22 tests, all against fake modules:
- Round trip; naive datetimes refused.
- Resolution: server-bound entry, other server stays UTC, legacy env, missing file. Five invalid config shapes fail closed, including at `connect()`. The project config holds the verified entry.
- Feed with verified **+3 and +2**:
  - quotes equal true UTC;
  - the newest closed M5 bar is current and the forming bar is excluded;
  - the chart's forming bar is correct;
  - an outgoing range is shifted exactly once.
- An unverified +3 server stays UTC and therefore looks future. A standard UTC server is unchanged.
- A server change disconnects, and the reconnect uses the new server's time base.
- **Same-server account change**: the feed disconnects without naming the login, and the scanner reconnects with a **new, later watermark**.
- Scanner checks:
  - Correct offset: fresh quotes and a session opens.
  - Wrong or changed offsets (actual 2 / configured 3, 3/2, 3/0): never actionable, no watermark, and the note says "~1 h behind/ahead" or "~3 h ahead".
- **Codex's reproduction now passes.** A +3 tick with the feed's +3 base reaches a successful fake submit (3 requests). Expiration is `T + 5 h` broker epoch (2 h lifetime + 3 h base). The reconcile history range is in broker time.
- The executor rejects a UTC base, a wrong +2 base, a base for a different server, and a genuinely stale tick under the right base. Each case makes zero requests.

## 4. Checks actually performed

| Check | Result |
|---|---|
| Focused: `test_mt5_time.py`, `test_live_market.py`, `test_fvg_execution.py` (before the account fix) | 82 tests, 0 failures |
| `test_mt5_time.py` after the account fix | 22/22 |
| Full backend: `pytest -p no:cacheprovider --basetemp=.tmp/pytest-tfull2-<ts> --junitxml=…` | **255 tests, 0 failures, 0 errors, 0 skipped** (exit 0); basetemp removed afterwards |
| Frontend | Not run: no frontend assets were touched |

**Live activation** (approved actions, run under the user's explicit "send it"):
1. Checked context read-only: MetaQuotes-Demo, demo, XAUUSD, Telegram OFF, no FVG opt-in file.
2. Snapshot of the previous choice saved to `.tmp/activate/active_strategy.before-20261007-143838.json` (`{"strategy":"fastsweep","profile":"rr2"}`).
3. `.venv/Scripts/python.exe -m app.active_strategy fvg rr2` → "saved: fvg profile rr2". **No permission rejection this time.**
4. `.venv/Scripts/python.exe -m app.launcher restart` → stopped PID 37728, started PID 18424 in the background.
5. Read-only verification:
   - `/api/health` reports `owner: true`, scanner running, mode mt5.
   - `/api/state` reports:

     | Field | Value |
     |---|---|
     | `active_strategy` | `fvg`, profile `rr2`; timeframes M15/M5 |
     | Account | `MetaQuotes-Demo`, `demo` |
     | Quote and time base | fresh, `time_base` as in section 2 |
     | `strategy_state` | "trend warm-up", readiness `m15_run 39 / required 50, ready: false`, next M15 close 08:00Z |
     | `fvg.auto_execution` | `OFF` ("not armed"), `risk_usd` 10.0, account currency USD, 0.1 % of equity |
     | `telegram.enabled` | false |
     | `trading` | "disabled: FVG automatic execution is OFF (not armed) - alerts only, no orders are sent" |

   - `/api/fvg`: 0 baskets, 0 setups.
   - `server.log`: no errors from the new process. Two older `AttributeError` tracebacks (log lines 204–372) predate several earlier restarts.

History databases and saved replays were not touched.

## 5. Not performed / limits

- No arming, test order, `order_check` or `order_send`, and no Telegram send, by design. The live automatic-order path is therefore unexercised; it is covered by fake brokers only.
- Waited for no M15 readiness. Warm-up is 39/50, so about 11 more contiguous M15 closes are needed. Readiness should be reached around 10:45 UTC if no market break intervenes.
- The expiration time base on a real broker is inferred from the tick/rate base plus MQL5 trade-server conventions. The docs do not state it explicitly. It should be confirmed (by checking the order's expiry in the terminal) on the first armed demo basket.
- DST: MetaQuotes-Demo is expected to move to +2 around 2026-10-25. Until `config/mt5_time.json` is re-verified and updated, the app will fail closed with a "~1 h behind" quote note.

## 6. Permission rejections

None in this task. The earlier rejection ("Production Deploy") happened outside an approved task. This time, both the strategy selection and the launcher restart ran normally.

## 7. Rollback (not performed)

```
.venv/Scripts/python.exe -m app.active_strategy fastsweep rr2
.venv/Scripts/python.exe -m app.launcher restart
```

## 8. Questions / blockers

None. Arming automatic execution on this demo account remains a separate decision for the user, made in the dashboard (System → FVG automatic execution, confirmation checkbox).
