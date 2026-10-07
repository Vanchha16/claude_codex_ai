# Claude finding: MetaQuotes-Demo server time breaks live freshness (needs a Codex decision)

Document type: INFORMATIONAL FINDING sent at the user's direct request ("send report to codex"). Not a reply to an approved task. No implementation was done.
Author: Claude (implementer)
Date: 2026-10-07 (about 07:24 UTC)
Related completed tasks: `20261007-111856-fvg-three-entry-engine`, `20261007-135946-fvg-dashboard-risk-labels`, `20261007-141139-fvg-sidebar-execution-copy`

## 1. Context (user's direct requests in the Claude session)

1. The user logged the MT5 terminal into a **MetaQuotes-Demo** account and asked Claude to "connect with MT5 again… use demo account for test our new strategy". The terminal title showed "Demo Account - Hedge"; the balance is about 10,000 USD. The login number is deliberately not repeated here.
2. Claude checked read-only through `GET /api/health` and `GET /api/state`:
   - The running backend is already in `mt5` mode on symbol `XAUUSD` and attached to MetaQuotes-Demo (MetaQuotes Ltd., demo).
   - Telegram delivery is OFF; active strategy is FastSweep rr2.
   - The backend process predates the FVG build: its `trading` string is still the legacy hard-coded text.
3. Claude then tried to select FVG with `python -m app.active_strategy fvg rr2`. **The Claude Code permission classifier denied this** (reason: "Production Deploy"). Claude did not work around it.
   - No restart was attempted. `config/active_strategy.json` is unchanged (`fastsweep rr2`).
   - Claude gave the user the commands to run themselves (`! .venv/Scripts/python.exe -m app.active_strategy fvg rr2`, `! gold.cmd restart`) and told them that arming stays their own dashboard action.
4. The user then shared a dashboard screenshot showing the banner "quote timestamp is in the future (clock skew or invalid data); nothing actionable" and asked what it means. This report explains it.

## 2. Finding

The screenshot shows the following:

| Field | Value |
|---|---|
| Quote time | 2026-10-07 10:22:16 UTC, "-10799.7s · NOT FRESH" |
| Last scan | 2026-10-07 07:22:16 UTC |
| Last closed M5 | 07:15:00 UTC |
| Strategy state | Waiting For Fresh Quotes |
| Spread | 0.35 |
| Data source | MetaTrader 5 terminal (read-only), MetaQuotes Ltd. · MetaQuotes-Demo |

The skew is 10,799.7 s, which is 3 hours.

**Cause.**
- `app/data/mt5.py:189-191` `_utc()` treats MT5 epochs as UTC ("MT5 epochs are UTC; only an explicit legacy offset shifts them").
- That holds for the Exness servers used until now. MetaQuotes-Demo stamps ticks and rates in **server time, currently UTC+3** (EET/EEST).
- No offset is configured: `GOLD_MT5_SERVER_UTC_OFFSET_HOURS` defaults to 0, and no `legacy_utc_offset_hours` appears in status.

**Consequences (fail-safe, but the live feed is effectively blind):**
- Every quote looks 3 h in the future and is rejected as not fresh, so nothing is actionable.
- `closed_bars()` drops bars whose close time is after "now". All bars from the last 3 hours are therefore excluded, and the "last closed M5 07:15 UTC" is really the 04:15 UTC candle.
- `bars_range` and `ticks_range` requests are shifted the same way.
- FastSweep produces no signals. FVG, if activated and armed, would also do nothing: the executor's fresh-quote pre-check rejects it.
- No wrong signal or order can result. The data is simply unusable on this broker.

Claude verified this only from the user's screenshot and the source code. It did not take a direct read-only tick sample from the terminal.

## 3. Options (Codex/user decision)

### A. Configuration only, no code change

- Put `GOLD_MT5_SERVER_UTC_OFFSET_HOURS=3` in the project-root `.env` (or the process environment) and restart.
- The existing code then subtracts 3 h on read and adds it back on requests, and the status shows `legacy_utc_offset_hours`.
- Limits:
  - MetaQuotes switches to UTC+2 when European DST ends (expected Sunday 2026-10-25). A fixed 3 would then make quotes look about 1 h old: blind again, still fail-safe.
  - The setting must go back to 0 when returning to Exness (UTC).
  - `.env` also holds the Telegram token, so the user should make the edit, or explicitly allow an append without reading the file.

### B. Small code change (Claude recommends this for broker-agnostic testing)

- Detect the server offset automatically. Offset = (latest tick `time_msc`) − (local UTC clock), rounded to the nearest 15 minutes.
- Accept it only if the terminal is connected and the tick is recent relative to the terminal's own last-tick time.
- Re-check on reconnect and periodically, so DST changes and broker switches are handled.
- Report the detected offset in feed status; let an explicit `GOLD_MT5_SERVER_UTC_OFFSET_HOURS` override it.
- Keep the existing future-timestamp guard as a backstop.
- Edge cases to specify:
  - Market closed or weekend: the last tick is old, so keep the last known offset or refuse to guess.
  - Half-hour offset servers.
  - Session watermark and history records must stay in true UTC. Offsets were 0 until now, so existing records are unaffected.
- Tests: fake MT5 module with +3, +2, 0 and a stale tick; quote and bar freshness; range-request shifting.

## 4. Still pending from the user

Testing FVG on this demo account also needs, in order:
1. The time fix (A or B).
2. Selecting FVG (`app.active_strategy fvg rr2`). The classifier blocked Claude, so the user runs it or grants permission.
3. A backend restart.
4. The FVG M15 warm-up: 50 contiguous M15 candles, about 12.5 h after any break.
5. The user's own dashboard arming (checkbox plus **Turn automatic execution ON**). This is bound to source, symbol, account hash and strategy version.

Account facts relevant to arming, taken from the screenshot only:
- The account is hedging and the balance currency is USD, so both pass the arming pre-checks.
- The fixed 10 USD per setup is about 0.1 % of the demo balance.

## 5. Actions taken

- Read-only HTTP status reads of the running local backend.
- One denied attempt to change the active strategy. Nothing changed: no config edit, no restart, no MT5 initialize, no broker request, no Telegram message, no arming.

Claude is waiting for a separately approved prompt before implementing anything.
