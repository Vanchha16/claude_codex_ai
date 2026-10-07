# Claude report: local gold signal workstation (CRT-SMC-v1)

Task ID: 20261002-111340-gold-signal-v1
Source prompt: `prompt/20261002-111340-gold-signal-v1.md`
Status: completed (real MT5 data and real Telegram delivery not verified; see below)
Reported at: 2026-10-02

## Outcome

The first version of the workstation is built, tested and running at **http://127.0.0.1:8000/** in DEMO mode with external delivery OFF.

**Approval gate:** passed. The prompt has `Delivery status: APPROVED FOR EXECUTION`, a Task ID, Source prompt and Report path, and a browser-button `User authorization:`. Its SHA-256 `62b5c770…6eaa` matches `prompt/drafts/20261002-111340-gold-signal-v1.md`. A progress receipt was kept at the Progress path.

What it does:
- **Strategy:** implements CRT-SMC-v1 exactly as specified in sections A–G.
- **Data:** an interchangeable feed — fictional demo fixture or read-only MetaTrader 5.
- **Storage:** candidates, signals, the outbox and events in SQLite.
- **Scanner:** runs in a background thread, with warm-up, a live-start watermark, pause and restart recovery.
- **Outcomes:** simulated, using the Bid/Ask exit-side rules and same-bar ambiguity.
- **Telegram:** test-group delivery through a durable outbox, mock-tested only.
- **Replay:** a chronological replay CLI with a held-out segment.
- **Dashboard:** responsive, with a setup chart.
- **Launcher:** a project-local Windows launcher.

**No trading code exists.** A test fails if `order_send`, `order_check`, `positions_close` or `TRADE_ACTION` appears anywhere in `app/`.

## Files changed

All new; existing `tools/`, `prompt/`, `report/` history and `AGENT_TO_AGENT.md` were left untouched.

**Strategy and engine**
- `app/strategy.py`: pure CRT-SMC-v1 rules:
  - range sweep/reclaim
  - strict pivots that only count once confirmed
  - frozen structure level
  - confirmation and invalidation, with invalidation winning in the same bar
  - entry/SL/TP with outward tick rounding
  - freshness, spread and reward/risk checks
- `app/engine.py`: candidate lifecycle shared by live scanning and replay. Handles one-time consumption, persistent dedup keys, the overlapping-signal guard, and tick-level invalidation and deadlines on each scan.

**Data and storage**
- `app/models.py`: UTC-aware value types; bar times are OPEN times.
- `app/config.py`: validated strategy config and `.env`/environment settings.
- `app/store.py`: in-memory store (replay) and thread-safe SQLite store (WAL). Mid-send outbox rows become `unknown` on restart.
- `app/data/demo.py`: fictional feed on a simulated clock.
- `app/data/mt5.py`: read-only MT5 feed (initialize, symbol_info, symbol_info_tick, copy_rates_*, copy_ticks_range, symbols_get). It uses an explicit symbol and an optional terminal path, never logs in, and never searches the disk.
- `app/scanner.py`: single scanner per process; non-blocking.
- `app/outcomes.py`: simulated outcome tracking.

**Delivery, replay and web**
- `app/delivery.py`: Telegram sendMessage client and outbox (`pending/sent/failed/unknown/expired`, 429 `retry_after`, bounded attempts, token redaction).
- `app/replay.py`: replay and CLI over demo, CSV or MT5 sources.
- `app/demo_fixture.py`, `app/scenarios.py`, `data/demo/xauusd_demo_m5.json`: deterministic fictional fixture (dated 2030, flagged `"fictional": true`).
- `app/web.py`: FastAPI on loopback. Host-header check; state changes need the session token and same origin. No CORS.
- `app/static/index.html`, `app.js`, `styles.css`: the dashboard.
- `app/server.py`, `app/launcher.py`, `gold.cmd`: launcher (`start|stop|status|restart|replay|symbols|test`).

**Config, docs and tests**
- `config/strategy.json`, `.env.example` (empty secrets), `.gitignore`, `requirements.txt`, `pyproject.toml`.
- `README.md`: setup, MT5 switch, Telegram setup guide, the strategy definition, outcome and replay rules, security notes.
- `tests/` (63 tests): `test_strategy.py`, `test_replay.py`, `test_delivery.py`, `test_scanner.py`, `test_api.py`, `helpers.py`.
- `report/20261002-111340-gold-signal-v1-progress.md`: the progress receipt.

**Local only, git-ignored**
- `.venv/` (Python 3.12.x): fastapi 0.142.2, uvicorn 0.54.0, httpx 0.28.1, MetaTrader5 5.0.6231, numpy, pytest 9.1.1.
- `.tmp/pip-cache/`.
- `.tmp/gold-signals/`: `demo.sqlite`, `server.log`, `server.json`, `replays/`.

## Strategy and config implemented

`config/strategy.json` holds the testing defaults (not optimised); the version is `CRT-SMC-v1@<hash>`.

| Setting | Value |
|---|---|
| Sweep beyond A | ≥ 2 ticks |
| SL buffer | 2 ticks beyond the sweep extreme |
| Pivots | 2 closed bars per side; 24-bar lookback before B open |
| Confirmation window | 12 M5 bars |
| Reward/risk | ≥ 1.5 |
| Max spread | 0.50 (price units) |
| Signal age / quote age | 30 s / 30 s |
| Alert validity window | 120 s |
| Simulated-trade expiry | 24 h |

Other settings:
- Scan interval 5 s; one symbol; H1 range with M5 confirmation.
- The dashboard always starts in DEMO mode. MT5 mode requires an explicit confirmed switch and never falls back to fictional data.

## Commands and checks actually run

- `py -3.12 -m venv .venv`, then `pip install fastapi uvicorn httpx pytest MetaTrader5` with `PIP_CACHE_DIR=.tmp/pip-cache`: succeeded.
- `python -m pytest` (`-p no:cacheprovider`): **63 passed**. One deprecation warning comes from Starlette's TestClient, not this code. The tests cover:
  - **Strategy:** valid BUY and SELL; no reclaim; boundary closes; double-sided sweep; the 2-tick minimum; tick-grid rounding; absent, tied, unconfirmed and future pivots; M5 gaps; confirmation before B close; expiry; revisited and invalidated setups; same-bar invalidation precedence; continuity loss; stale quotes; spread and reward/risk rejection; missed confirmations.
  - **Replay:** next-open fill with spread and slippage; SELL Ask exits; same-bar TP/SL ambiguity; truncation (no future data); no fill without a next observation; chronological holdout isolation; tick-mode entry and outcome.
  - **Delivery (mocked network):** message format; success with message ID; 429 `retry_after`; definite 400 error; timeout → unknown, never resent; connect error → retry → expired; expired outbox; disabled and unconfigured states; token redaction; crash mid-send → unknown; test message only on explicit request.
  - **Scanner and persistence:** a live signal delivered exactly once; startup after a confirmation sends nothing historical; restart without duplicates; pause stops alerts while outcome tracking continues; the overlapping-signal guard; no trading code.
  - **API:** health, state and page; token, origin and Host checks; Telegram can't be enabled while unconfigured; mode switch needs explicit confirmation; the demo produces a signal, chart and message preview.
- `gold.cmd replay --source demo`: written to `.tmp/gold-signals/replays/`.
  - Development segment: 20 setups, 2 signals, both TP.
  - Holdout segment: 9 setups, 1 signal, SL.
  - These are **fictional fixture results only**, not performance evidence.
- `gold.cmd start`, `stop`, `status`, `start`, `status`: background start, graceful stop and restart all verified.
  - The first start reported a false failure because the venv `pythonw.exe` is a redirector stub, so its PID differs from the server's. Fixed by matching the server's recorded start time; the retest passed.
- HTTP smoke checks with curl:
  - `/api/health` returns 200 with the matching PID.
  - `/api/state` reports demo mode, the scanner running, a fresh quote and Telegram "not configured".
  - The first fictional BUY was confirmed live: entry 2405.60 (Ask), SL 2398.98, TP 2420.00, reward/risk 2.175. It later resolved at TP (+2.18R simulated).
  - The outbox is empty, because delivery is off.
  - A POST without the token returns 403, and a foreign Host header returns 403.
  - The server listens only on `127.0.0.1:8000`.
- **Browser check** (Chrome, via the browser automation tool): the dashboard rendered with the DEMO badge, quote, scanner and Telegram cards, the setup chart (A range, sweep, frozen level, entry/SL/TP, B open/close and confirmation markers), the signals and setups tables, the replay summary and the config. No console errors. Overlapping chart labels were found and fixed, then rechecked.

## Demo vs real verification

- **Verified (demo/fictional only):** the full pipeline, from scanning through candidates, signals, outcomes, dashboard and replay.
- **Not verified with real MT5 data:** no `terminal64.exe` was running and `GOLD_SYMBOL` is not set. I did not call `initialize()`, because it could launch the terminal. The MT5 adapter is untested against a live terminal: symbol metadata, Bid/Ask, server-time offset and copy_rates/ticks behaviour still need a real run.
- **Not verified with real Telegram:** no bot token or chat is configured. No network message was sent; all delivery tests used a mocked transport.

## Remaining configuration for the user

1. **MT5:** start and log in to the Exness MT5 terminal, then run `gold.cmd symbols` and put the exact gold symbol name in `.env` as `GOLD_SYMBOL`.
   - Optional: `GOLD_MT5_TERMINAL_PATH`, and `GOLD_MT5_SERVER_UTC_OFFSET_HOURS` if the server is not on UTC. Exness servers are usually UTC, but this is unconfirmed.
   - Then run `gold.cmd restart` and use **Switch to MT5…** in the dashboard.
   - A read-only real-data replay is available: `gold.cmd replay --source mt5 --days 60 [--use-ticks]`.
2. **Telegram:** follow README → "Telegram setup" (BotFather token, test group, chat ID) and set `GOLD_TELEGRAM_BOT_TOKEN` / `GOLD_TELEGRAM_TEST_CHAT_ID` in `.env`. Then run `gold.cmd restart` and press **Send labeled test message**. Turn on **External delivery** only when you want signals posted.

## Dashboard process

| | |
|---|---|
| URL | http://127.0.0.1:8000/ |
| PID | 11488 (Python server process, started hidden via the venv `pythonw.exe` stub) |
| Mode | DEMO, external delivery OFF |
| Log | `.tmp/gold-signals/server.log` |
| State record | `.tmp/gold-signals/server.json` (includes the local session token, used for graceful stop) |
| Commands | `gold.cmd start`, `gold.cmd stop`, `gold.cmd status`, `gold.cmd restart` |

The demo replays a two-day fictional fixture at 60 simulated seconds per real second (about 49 minutes). After that it shows "finished"; use **Restart demo** to replay it.

## Questions, missing requirements, or blockers

None blocking. Open items for Codex to discuss with the user:
- The exact Exness gold symbol and whether to switch to MT5 mode. This needs the user's running terminal.
- Telegram bot and test chat setup.
- `alert_valid_seconds = 120`. The prompt asked for a "short entry-validity window" without giving a number; I chose 120 s as a configurable default. Please confirm or adjust.
- Live outcome tracking approximates the SELL Ask from M5 Bid bars as Bid plus the spread at entry, in addition to live quotes each scan. This is documented in the README.

## Suggested next step

Once the terminal and symbol are configured: a separately approved task to run read-only MT5 checks (symbol metadata, quote freshness, a historical replay with ticks) and one explicit Telegram test message to the test group.
