# Claude report: VC Signal local live market and TradingView-style chart

Task ID: 20261002-141133-vc-signal-live-market
Source prompt: `prompt/20261002-141133-vc-signal-live-market.md`
Status: partially completed. Code is complete and mock/demo-verified. Real MT5 and Telegram integration are NOT verified, because no MT5 terminal was running and no Telegram destination is configured.
Reported at: 2026-10-02

## Outcome summary

| Item | Result |
|---|---|
| Code complete | **Yes.** All scoped features are implemented; 102 Python tests and 4 JS tests pass. |
| Real data connection verified | **No.** No `terminal64.exe` process was running on this computer. |
| Scanner observed | Yes, in demo (live updates, signals, outcomes) and in live MT5 mode (an honest *disconnected* state). Not yet observed on real prices. |
| Historical replay observed on real data | **No** (needs a connected terminal and a selected symbol). Demo replay works. |
| Bot/destination verified | **No.** The bot token is found server-side, but no destination chat ID is configured, so getMe/getChat was not run. |
| Real Telegram message sent | **No** (not authorised by this task; none sent). |
| Ongoing live mode health | VC Signal is running at http://127.0.0.1:8000/ (PID 1908) in persisted **LIVE MT5** mode. It is waiting for the terminal (state `disconnected`, reconnect back-off 15–60 s). External delivery is **OFF**. |

**Approval gate:** passed. The prompt has `APPROVED FOR EXECUTION`, a Task ID, Source prompt and Report path, and a browser-button `User authorization:`. Its draft SHA-256 `c18c3caa…8470` matches. The progress receipt was kept updated at `report/20261002-141133-vc-signal-live-market-progress.md`.

## Architecture and configuration behaviour

### 1. Configuration (`app/config.py`)

**Sources, lowest → highest precedence:**
1. defaults
2. `.venv/.env`
3. root `.env`
4. `config/local_settings.json` — non-secret, written atomically by the dashboard, git-ignored
5. process environment

**Key resolution:**
- The canonical key beats any alias, in whichever source the alias appears; among keys of the same kind, the higher-precedence source wins.
- Recognised keys only: `GOLD_*`, plus the aliases `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `GOLD_TELEGRAM_CHAT_ID`.
- Ignored: `TELEGRAM_BOT_USERNAME`, `TELEGRAM_PROVIDERS`, `OPENAI_API_KEY` and every other key in `.venv/.env`.

**Secrets:**
- Tokens are never written to local settings or sent to the frontend. The frontend sees only "configured"/"missing" plus the source key name, e.g. `.venv/.env:TELEGRAM_BOT_TOKEN`.
- Checked live: the real token value appears in none of `/`, `/api/state`, `/api/setup`, `/api/events`, the JS files, or `server.log`.
- The user's `.venv/.env` was not modified or copied. Only key names were inspected; the token value was used in-process for the check above.

**Validation:**
- Exact-symbol format.
- Terminal path must be an absolute `terminal64.exe` that exists.
- Chat ID must be numeric; `@username` is rejected.
- IANA time zone.
- Fields set in the process environment are locked in the UI.

### 2. Persisted live source, sessions and the single owner

**Startup (`app/web.py` Workstation):**
- Starts in the persisted `data_mode`; it is no longer forced to demo.
- Live MT5 that cannot connect stays an honest `disconnected` / `symbol_selection_required` / `symbol_missing` state. The demo fixture is never substituted.

**Setup form and mode switch:**
- The Setup form (`POST /api/setup`) and the mode switch persist choices.
- Changing source, symbol or terminal path restarts with a **new scanner session**, i.e. a fresh eligibility watermark, preserving the earlier repairs.
- History is separated per live symbol: `.tmp/gold-signals/mt5-<symbol>.sqlite`. Demo history stays fictional.
- Changing only the chat ID rebuilds the delivery sender, which re-checks the opt-in.

**Cross-process owner guard (`app/owner.py`):**
- An OS-level exclusive lock on `.tmp/gold-signals/owner.lock`: `msvcrt` on Windows, `fcntl` elsewhere, held for the process lifetime.
- A second process cannot start a scanner or outbox sender; it reports `owner_error` and serves no scanner.
- The OS releases the lock if the owner dies, so recovery needs no cleanup.

### 3. MT5 (`app/data/mt5.py`), read-only

**Calls used:** `initialize` (no credentials), `terminal_info`, `account_info` (only server, company and account type are exposed — never login or balance), `symbol_info`, `symbol_info_tick`, `symbol_select`, `copy_rates_*`, `copy_ticks_range`, `symbols_get`. No order functions exist; a test enforces this.

**Behaviour:**
- **Attaches only to a user-started terminal:** a `tasklist` process check runs before `initialize()`, because `initialize()` would otherwise try to launch a terminal. Bounded reconnect back-off is 15→60 s.
- **Symbol discovery:** gold candidates (`*XAU*`, `*GOLD*`) come from the terminal. An explicit choice is always required; nothing is guessed.
- **Instrument data:** tick size, point and digits come from `symbol_info`; Bid/Ask from `symbol_info_tick`.
- **UTC:** epochs are taken as UTC, unshifted. A legacy offset applies only when explicitly nonzero, and is then reported in the status. Request ranges are UTC-aware. The display time zone affects formatting only.
- **Chart bars:** M1/M5/M15/H1/H4/D1 with `tick_volume`, ascending unique times, the forming bar flagged separately, and `before` paging.
- **Tick reads:** an error raises instead of returning an empty list, so it is recorded as a measurement gap.

### 4. Strategy state and quote checks

**Scanner (`app/scanner.py`):**
- Future-dated quotes (more than 5 s ahead) and invalid quotes are not fresh. Last closed H1/M5 times are recorded.
- Strategy state comes from real records: *paused*, *disconnected*, *symbol selection required*, *waiting for fresh quotes*, *pending structure confirmation* (with frozen range/level/deadline), *no eligible sweep* (last H1 pair), the last setup's status and reason, or *waiting for the next closed H1 range*.
- The engine records the last A/B evaluation, including the config version.
- The startup / restart / same-scan-reconnect watermark rules are unchanged; all earlier regressions pass.

### 5. Measured outcomes (`app/outcomes.py` `track_measured`)

**Live MT5:**
- Exits are settled only on observed ticks: BUY on the Bid, SELL on the Ask.
- Ticks are read in bounded chronological chunks (6 h × up to 8 per scan) after `last_checked`, plus the current fresh quote.
- The exit is recorded at the observed tick price and time; ticks after "now" are ignored.
- A failed tick read is recorded (`measurement_gaps`, shown in the Signals table) and never replaced by a bar estimate. `last_checked` does not advance past a gap.
- Expiry is marked at the last observed exit-side tick, or with no R if none was observed.

**Demo:** keeps the bar/quote estimate path. SELL bar hits are explicitly labelled `ESTIMATE`.

### 6. Telegram (`app/delivery.py`)

**Labels:**
- Live: **"LIVE MARKET SIGNAL - VC Signal (MT5 market data; alert only)"**.
- Demo: **"DEMO TEST SIGNAL - VC Signal - DEMO DATA (fictional prices; not a market signal)"**.
- Both include symbol, side, observed entry side/price and quote time, confirmation time, SL, TP, R:R, validity window, explanation and strategy version.

**Read-only verification:** `POST /api/telegram/verify` calls getMe + getChat only — no sendMessage, no getUpdates — with sanitised errors.

**Opt-in:**
- Off by default.
- In live mode, the user's enable action saves an opt-in bound to source + exact symbol + bot token fingerprint (SHA-256 prefix) + chat ID.
- A restart restores it for **new** signals only. Changing any binding invalidates and deletes it.
- Demo enablement lasts for the session only.
- The outbox states and the no-blind-resend rule are unchanged.

### 7. Market chart (TradingView Lightweight Charts™ 5.2.1)

**Packaging:**
- Pinned in `frontend/package-lock.json`.
- The bundle is copied unmodified to `app/static/dist/lightweight-charts.standalone.production.js`; no CDN.
- Apache-2.0 licence text is at `/static/dist/LICENSE-lightweight-charts.txt`. The upstream NOTICE text ("TradingView Lightweight Charts™ / Copyright (с) 2025 TradingView, Inc. https://www.tradingview.com/", fetched from the official repo at v5.2.1) is in `/static/dist/THIRD_PARTY_NOTICES.txt`.
- The TradingView attribution logo is on the chart, with visible links to https://www.tradingview.com/. VC Signal and TailAdmin branding and notices are kept.

**`app/static/market-chart.js`:**
- Chart: candlesticks, precision from the symbol, crosshair, and an OHLC/tick-volume readout outside the canvas.
- Toolbar: 1m–1d timeframes (display only), Reset view, Live/Back to live, and Expand (Fullscreen API with an in-page fallback).
- Updates: incremental live updates that keep zoom/pan; older history loads on scroll; stale-response protection via a request generation counter.
- Setup overlays come straight from `/api/chart` backend records: price lines for A high/low, sweep, level, entry, SL, TP, plus B and BUY/SELL markers.
- Indicators: EMA20/EMA50 on closed bars only, and a tick-volume histogram only when supplied (disabled for demo).
- Theme-aware; disposes its subscriptions.

**Backend `GET /api/market/bars`:** validates timeframe, count (1–1000) and the UTC `before` time; returns `available: false` with a reason instead of fabricating data.

### 8. Real historical replay

- `replay_from_feed()` replays from the already-connected live feed without shutting it down; `POST /api/replay/run {source: "mt5", days ≤ 60, use_ticks}`.
- The label carries the actual returned bounds and counts. Development/holdout reporting is unchanged.
- The CLI path keeps its own feed with `finally` cleanup.

## Changed files

**Backend:**
- `app/config.py`
- `app/web.py`
- `app/data/mt5.py`
- `app/data/demo.py` (chart bars; forming candle built only from prices up to sim-now; 1m reported unavailable)
- `app/scanner.py`
- `app/outcomes.py`
- `app/engine.py`
- `app/delivery.py`
- `app/replay.py`
- `app/market.py` (new: chart-only DTOs and validation, isolated from the engine)
- `app/owner.py` (new)

**Frontend:**
- `frontend/src/index.template.html` (Chart section, Overview strategy state and market source, Setup form, Telegram card, real replay controls)
- `frontend/src/input.css`
- `frontend/src/tailadmin/icons.json` (+2 TailAdmin icons)
- `frontend/copy-assets.mjs`
- `frontend/package.json` and `package-lock.json` (+`lightweight-charts` 5.2.1; `npm test`)
- `frontend/tests/timefmt.test.mjs` (new)
- `app/static/app.js` (rewritten for the new UI)
- `app/static/market-chart.js` and `app/static/timefmt.js` (new)
- Regenerated `app/static/index.html` and `app/static/dist/*`

**Tests:**
- `tests/test_live_market.py` (new, 20 tests)
- `tests/fake_mt5.py` (new; a mock MetaTrader5 module that asserts no credentials are passed)
- Updated label/chart assertions in `tests/test_api.py` and `tests/test_delivery.py` for the new message labels and the `/api/market/bars` split

**Docs and config:** `README.md`, `.env.example`, `.gitignore` (adds `config/local_settings.json`).

**Runtime (git-ignored):**
- `config/local_settings.json` containing only `{"data_mode": "mt5"}` (the live source selected for validation).
- `.tmp/gold-signals/mt5-no-symbol.sqlite`, `owner.lock` / `owner.json`.

## Tests and checks actually run

**Automated:**
- `.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .tmp/pytest/<unique>`: **102 passed** (one third-party Starlette warning). Repeated several times; two test races were found and fixed by making the tests deterministic.
- New tests cover:
  - config sources, aliases and precedence, including canonical-beats-alias across files, env lock and secret exclusion;
  - chat-ID and symbol validation;
  - exact-symbol selection with several contracts, broker context without login/balance, and no silent contract switching;
  - UTC epochs unshifted, plus a flagged legacy offset;
  - chart bars ascending/unique with forming flag, tick volume and `before` paging;
  - honest disconnected state;
  - persisted live source across restart with no demo fallback;
  - setup flow → exact symbol → new session, with chart requests creating no candidates and bad timeframe/count rejected;
  - demo chart available without any setup, and 1m unavailable;
  - LIVE vs DEMO labels;
  - SELL needs an Ask tick and BUY uses the Bid, with future ticks ignored;
  - tick gaps recorded rather than estimated, including scanner integration with tick reads and a failed read;
  - opt-in persistence, restore, invalidation (chat/symbol/source) and disable;
  - verify uses only getMe/getChat and redacts the token;
  - the cross-process owner lock with real subprocesses: refused while held, recovered after the owner is killed, and a second process refused while the app owns it;
  - never launching a terminal, and reconnect back-off.
- All earlier watermark, replay and reconnect regressions pass.
- `npm test` (Node `--test`): **4 passed**. UTC and Asia/Bangkok display formatting (+7 h, day rollover) without shifting the source instant.
- `npm run build` (Tailwind 4.3.3 + copy-assets) succeeded. `node --check` passed on `app.js`, `market-chart.js` and `timefmt.js`. Every app.js element ID exists in the page, with no duplicates.

**Browser** (Chrome via the extension, against the running app; demo data for chart behaviour):
- Timeframes: 1m shows "not available in the fictional demo fixture"; 15m/1h give correct 900/3600 s spacing.
- EMA20 has 85 points from 104 closed bars; tick volume is disabled for demo.
- **Real mouse** wheel zoom and drag-to-pan changed the visible range; the crosshair readout showed UTC time and OHLC, labelled "(forming candle)".
- Live polling over 20+ s appended new candles in ascending order and tracked the forming candle, with no console errors. Earlier it threw "Cannot update oldest data"; this was found and fixed with tail-only updates and a full redraw fallback.
- Setup selection: all 7 overlay prices matched the backend record exactly; markers B, B close and "BUY AB5F52"; Back to live cleared them.
- Reset view restores the setup window in setup mode and fits content in live mode.
- Expand: the real Fullscreen API resized the chart to 2350×1090; the Exit button restored 1438×480 with no page overflow.
- Theme: the chart background switched #101828 ↔ #fff with the theme; your theme was left unchanged.
- 390 px (iframe harness): no overflow, toolbar wraps, chart 305×340 px.
- Setup/Telegram card: chat ID `@my_bot` rejected (400, clear message); token shown as configured from `.venv/.env:TELEGRAM_BOT_TOKEN` (value hidden); destination "missing"; Verify and Enable disabled.
- Switched to live MT5 via the API (mode persisted) and restarted: status `mode mt5`, the banner and strategy state show the actionable "MetaTrader 5 is not running…" message, and the chart shows the same reason instead of data.
- The only remaining console errors came from a Chrome extension's own content script, not from VC Signal.

**Screenshots** (`.tmp/screenshots/live-market/`):
- `demo-chart-desktop-dark.jpg`
- `setup-overlays-desktop.jpg`
- `mobile-390-chart.jpg`
- `system-setup-telegram.jpg`
- `live-mt5-disconnected.jpg`

**Not performed:**
- Any real MT5 read: terminal not running.
- Real replay: requires a connected terminal and a symbol.
- getMe/getChat: no destination configured.
- Any Telegram send: not authorised.
- Touch-device pinch: library-supported, not tested on hardware.
- Screen-reader testing.

## Local operational state (sanitised)

| | |
|---|---|
| URL | http://127.0.0.1:8000/ |
| PID | 1908 |
| Owner lock | held |
| Mode | **LIVE MT5** (persisted) |
| Feed | disconnected — terminal not running |
| Symbol | not selected |
| Telegram | token configured (alias), destination missing, delivery **OFF** |
| Log | `.tmp/gold-signals/server.log` |
| Commands | `gold.cmd start / stop / status / restart` |

The task panel (http://127.0.0.1:4318/) was not touched. Nothing was installed as a service or scheduled task.

## Precise user actions still needed

1. Start your **Exness MetaTrader 5** desktop terminal and log in. VC Signal attaches automatically within about 15–60 s; it never launches the terminal or logs in.
2. Dashboard → **System → Setup** → **Find**, then choose the exact gold contract (e.g. XAUUSD vs XAUUSDm, as shown by your terminal) → **Save setup**. Check that the broker/server shown is Exness.
3. Enter your Telegram destination **numeric chat ID** in Setup and press **Verify bot & destination** (read-only).
4. When you are ready: **Send labeled test message**, then enable **External delivery**.
5. Optional: **Replay → Real MT5 history** (up to 60 days) for development/holdout statistics on real data.

Codex can then dispatch a follow-up to perform and record the read-only real-data smoke check: symbol, Bid/Ask/UTC tick, closed H1/M5, scans over time, and replay bounds/counts.

## Remaining limitations

- Live outcome measurement depends on MT5 tick history availability; gaps are recorded, not filled.
- Tick-replay limitations are unchanged (no interpolation between ticks).
- The forming candle is display-only and approximate in demo.
- The demo fixture has no tick volume and no 1m data.
- Continuous scanning requires this PC, MT5, VC Signal and the internet to stay up. VPS deployment is deferred and untested.

## Questions, missing requirements, or blockers

**Blocked for real verification only:** no running MT5 terminal, no selected symbol, and no Telegram destination chat ID. These need the user actions above; no code work is blocked.
