# VC Signal: local gold signal dashboard (CRT-SMC-v1)

Project folder: `vc_trade`.

A local Windows tool that analyses **one gold symbol** from **your own logged-in Exness MetaTrader 5 terminal** (read-only)
for a CRT range-sweep setup with one SMC structure confirmation. It shows the live market, setups and signals on a dashboard and,
only after you explicitly enable it, posts alerts to your Telegram destination. It is MT5-only: there is no fictional demo
mode or sample data.

> **CRT-SMC-v1 and FastSweep never trade.** They are read-only: alerts plus *simulated* outcomes (price hits, not broker fills).
> The separate, opt-in **FVG-Trend-M15-M5** build can place pending limit orders through `app/fvg_execution.py` (the only module
> that sends broker requests), but only while FVG is the active strategy on live MT5 **and** you have explicitly turned its
> automatic execution ON for that exact source/symbol/account/strategy version. It is **OFF by default and is not active.**
> CRT-SMC-v1 is a research baseline with testing-default thresholds. It is **not** a proven or profitable strategy.

## Quick start

Easiest: start your MT5 terminal, then double-click **`start.cmd`**. It starts the background server (or reports that
it is already running) and opens the dashboard in your browser.

```bat
start.cmd           :: double-click: start (if needed) + open the dashboard
gold.cmd start      :: hidden background server; prints http://127.0.0.1:<port>/ (prefers 8000)
gold.cmd status
gold.cmd stop
```

The dashboard always uses your **MT5 terminal** (read-only). A terminal that cannot connect stays an honest
*disconnected / not configured* state; no fictional or sample data exists in the app. A saved or environment data source of
`demo` (from older versions) is refused at startup with a clear message - set it to `mt5` or remove it.
External Telegram delivery is **off** unless you enabled it for the current live source/symbol/bot/destination (see Telegram).
Logs go to `.tmp/gold-signals/server.log`, and the state/PID record is `.tmp/gold-signals/server.json`.

Other commands:

```bat
gold.cmd replay --source mt5 --days 60         :: read-only MT5 history (needs GOLD_SYMBOL)
gold.cmd replay --source mt5 --days 30 --use-ticks
gold.cmd replay --source csv --m5 my_m5.csv [--ticks my_ticks.csv]
gold.cmd symbols [*XAU*]                       :: list candidate symbols in your terminal
gold.cmd build-ui                              :: rebuild the dashboard assets (see Dashboard UI)
gold.cmd test                                  :: run the test suite
```

### Setup (already done in this project)

```bat
py -3.12 -m venv .venv
set PIP_CACHE_DIR=%CD%\.tmp\pip-cache
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env      :: then fill in what you need
```

## Dashboard UI (TailAdmin)

The dashboard is built on the official **TailAdmin free** HTML/Tailwind template.

**Provenance**
- Source: https://github.com/TailAdmin/tailadmin-free-tailwind-dashboard-template
- Commit `1bd2dc42a8467ae0281cf00bd0050da4c9c4be07`, package v2.4.0, dated 2026-09-15.
- License: MIT, Copyright (c) 2023 TailAdmin.

**What was adapted**
- From `src/css/style.css`: the design tokens and utilities, including the `menu-item*` sidebar utilities.
- The sidebar and its menu items, the header with the hamburger and the small-screen overlay drawer, and the dark-mode toggler (persisted in `localStorage`).
- Metric cards, the table card, badges, the alert style, form selects, and the sidebar icons.

The template's sample revenue, customer and order data was not used; every number on the dashboard comes from this app's API.

**Changes to the upstream stylesheet** (marked `[vc_trade]` in `frontend/src/tailadmin/style.css`):
- The Google Fonts import is removed. Outfit is served locally from `@fontsource-variable/outfit`.
- Tailwind scans only the dashboard sources.

**Licenses:** `frontend/src/tailadmin/LICENSE`, plus `app/static/dist/THIRD_PARTY_NOTICES.txt`, which is served at `/static/dist/THIRD_PARTY_NOTICES.txt`.

**Normal use needs no build step and no network.** FastAPI serves the built files directly:
- `app/static/index.html`
- `app/static/app.js`
- `app/static/dist/` (`app.css`, `alpine.min.js`, the font, the notices)

**Rebuilding after changing the UI** (Node 24 + npm; dependencies pinned in `frontend/package-lock.json`, cache in `.tmp/npm-cache`):

```bat
gold.cmd build-ui     :: npm ci (first time) then: tailwindcss -> app/static/dist/app.css, render index.html, copy Alpine + font + notices
gold.cmd restart
```

| Source | Purpose |
|---|---|
| `frontend/src/index.template.html` | Page source. Edit this, not the generated `app/static/index.html`. |
| `frontend/src/input.css` | Stylesheet entry: TailAdmin styles plus app-specific additions |
| `frontend/src/tailadmin/` | The vendored TailAdmin style.css, icons and LICENSE |
| `frontend/copy-assets.mjs` | Renders the page and copies Alpine, the font and the notices |

The pristine upstream checkout used for provenance is in `vendor/tailadmin-free/`. It is git-ignored and can be re-cloned at the pinned commit.

**Sidebar sections:** Overview, Chart, Signals, Setups, Replay and System. If the separate agent-to-agent task panel is running, it is linked under Tools; its URL is read from `.tmp/task-panel/server.json`.

## Market chart (TradingView Lightweight Charts)

The Chart section uses TradingView's open-source **Lightweight Charts™ 5.2.1** (Apache-2.0, pinned in
`frontend/package-lock.json`, bundled locally as `app/static/dist/lightweight-charts.standalone.production.js`; no CDN).
Its NOTICE attribution is in `/static/dist/THIRD_PARTY_NOTICES.txt` (licence text: `/static/dist/LICENSE-lightweight-charts.txt`);
the chart shows TradingView's attribution logo and the page links to https://www.tradingview.com/. It is a custom chart fed by
VC Signal's `/api/market/bars` (your MT5 terminal), not a TradingView widget, and VC Signal keeps its own branding.

Supported functions:
- Candlesticks with a precision-aware price axis (symbol digits/tick size), UTC time axis (or your display time zone), crosshair, and an
  OHLC/tick-volume readout outside the canvas.
- Mouse-wheel zoom, drag-to-pan, touch gestures, **Reset view**, **Live** (return to the current market) and **Expand** (Fullscreen API,
  with an in-page expanded fallback; Esc / the button returns to the dashboard).
- Timeframes **1m, 5m, 15m, 1h, 4h, 1d** — display only. Each requests the matching MT5 timeframe; missing history is shown as such.
  The strategy always uses H1 + M5.
- Polling appends/updates the newest candles without moving your zoom/pan; older history loads on demand when you scroll left
  (bounded requests, no gap filling). The forming candle is drawn in a muted colour and labelled; analysis only uses closed candles.
- Selecting a setup or signal overlays A high/low, the sweep extreme, the frozen structure level, entry, SL and TP plus B/confirmation
  markers, all taken from the backend records; **Back to live** removes them.
- EMA20 / EMA50 toggles computed from the loaded closed bars (visual aids, not strategy rules) and a tick-volume histogram only when
  MT5 supplies `tick_volume` (never exchange volume).
- Light/dark colours follow the dashboard theme; responsive at desktop and ~390 px widths.

### Chart zones: FVG, IFVG, OB, BB (visual aids only)

Four toggleable price-zone overlays (`app/static/smc-zones.js` detects, a Lightweight Charts series primitive in
`app/static/market-chart.js` draws). They never feed CRT-SMC-v1, signals, Entry/TP/SL/RR or Telegram. Definitions vary between
vendors; these are this project's reproducible, close-based conventions on the **current chart timeframe**:

- **Input:** closed candles only (the forming candle can neither create, flip nor end a zone), plus the symbol tick size. A pattern
  only forms inside a contiguous run of candles (each exactly one timeframe step after the previous); a missing candle, market break,
  weekend, invalid or out-of-order bar starts a new run. Zones that already exist keep being managed by later closes.
- **FVG (Fair Value Gap):** candles i-2, i-1, i. Bullish when `low[i] - high[i-2] >= 1 tick` (zone `high[i-2]..low[i]`); bearish when
  `low[i-2] - high[i] >= 1 tick` (zone `high[i]..low[i-2]`). Equal or sub-tick gaps are not FVGs. Active from candle i.
- **IFVG (Inverse FVG):** a bullish FVG flips bearish on a later close strictly below its bottom (bearish: close strictly above its
  top). The FVG ends there and the IFVG, with the same bounds and origin, is active from that candle. A bearish IFVG ends on a close
  strictly above its top, a bullish one on a close strictly below its bottom. No further flips.
- **OB (Order Block):** pivots need two candles on each side with strict comparisons and become usable only after the 2nd right-hand
  candle closes. Only the most recently confirmed pivot high (low) is eligible, and each pivot is used at most once. A close strictly
  above that pivot high is a bullish break: the last bearish candle (close < open) before the break, at most 20 candles back and not
  before the pivot, becomes the OB with its full high-low range. Bearish mirrors this. No such candle: no OB. Active from the break
  candle. This is an OHLC structure convention, not evidence of institutional orders.
- **BB (Breaker Block):** a bullish OB closed strictly below its low becomes a bearish BB (bearish OB closed strictly above its high
  becomes a bullish BB), same bounds and origin, active from that candle. A bearish BB ends on a close strictly above its top, a
  bullish BB on a close strictly below its bottom.
- Each candle first updates existing zones, then creates new ones, so a zone never ends on its own candle. Wick touches never flip
  or end a zone.
- **Display:** colour shows the TYPE - FVG cyan, IFVG purple, OB amber, BB rose (theme tokens `--zone-fvg/-ifvg/-ob/-bb`; dark
  `#38bdf8 #a78bfa #fbbf24 #fb7185`, light `#0284c7 #7c3aed #b45309 #be123c`), matched in the chart, pill swatches and help legend.
  Direction is the badge arrow (▲ bullish, ▼ bearish); border style is a second type cue (FVG solid, IFVG dashed, OB thicker solid,
  BB dotted). Candles keep their green/red. Boxes are drawn below the candles with very light fills; compact badges sit above them,
  and an overlapping badge is skipped (newest active first), never moved. Active zones extend to the newest candle.
- **How many are drawn:** by default the newest **3 active** zones of each type (max 12). **Recent** offers 3 / 5 / 10 per type;
  **History** (off by default) also draws the most recently ended zones, faded, within the same per-type limit. These options only
  change drawing; detection always uses all loaded closed candles. The status line reads e.g. "FVG 3/11" = 3 drawn of 11 active
  ("+n ended" with History; "off" when a type is hidden). Scrolling left loads older history, which can reveal older zones.
- Preferences stay in this browser: the toggles (default on) in `vcIndicators.v1`, the Recent/History choice in `vcZoneDisplay.v1`.

## Configuration

Settings are read from these sources, lowest to highest precedence:

1. built-in defaults
2. `.venv/.env` — your existing file (only the recognised keys below are read; everything else, e.g. `OPENAI_API_KEY`, is ignored)
3. `.env` in the project root (optional)
4. `config/local_settings.json` — **non-secret** choices saved by the dashboard Setup form (git-ignored; atomic writes)
5. the process environment (wins; the dashboard shows those fields as locked)

For each setting the **canonical** key wins over any alias, in whichever source the alias appears; among keys of the same kind the
higher-precedence source wins.

| Setting | Canonical key | Accepted aliases |
|---|---|---|
| Data source (`mt5` only) | `GOLD_DATA_MODE` | — |
| Exact broker symbol | `GOLD_SYMBOL` | — |
| MT5 terminal path | `GOLD_MT5_TERMINAL_PATH` | — |
| Telegram bot token (secret) | `GOLD_TELEGRAM_BOT_TOKEN` | `TELEGRAM_BOT_TOKEN` |
| Telegram destination chat ID | `GOLD_TELEGRAM_TEST_CHAT_ID` | `GOLD_TELEGRAM_CHAT_ID`, `TELEGRAM_CHAT_ID` |
| Display time zone | `GOLD_DISPLAY_TIMEZONE` | — |

`TELEGRAM_BOT_USERNAME` and `TELEGRAM_PROVIDERS` are **not** destinations and are ignored. Tokens are never written to
`config/local_settings.json`, never sent to the browser (only "configured"/"missing" and the key name), and redacted from logs and errors.

## Live MT5 workflow (read-only)

1. Start your **Exness MetaTrader 5** terminal and log in as usual. VC Signal never logs in, never asks for or reads broker
   credentials, and only attaches to a terminal that is already running (it will not launch one).
2. Open **System → Setup**, choose *Live MT5 terminal*, press **Find** to list the gold contracts your terminal offers, pick the
   **exact** symbol (VC Signal never guesses between `XAUUSD`, `XAUUSDm`, …) and **Save setup**. Optionally set the
   `terminal64.exe` path if `initialize()` cannot find your running terminal. (`gold.cmd symbols` lists candidates from the command line.)
3. The Overview shows provider, broker/server (company, server, demo/real account type — never login or balance), symbol, Bid/Ask,
   spread, quote time/age, last closed H1/M5, last scan, data checks and the CRT-SMC-v1 strategy state. *No eligible setup* is a
   normal live result; signals are never invented.

Changing the source or symbol starts a **new scanner session** (fresh eligibility watermark). History is kept per source/symbol
(`.tmp/gold-signals/mt5-<symbol>.sqlite`); missed confirmations are never replayed into Telegram. Disconnects, stale or future-dated
quotes, history gaps and market closure are shown, with bounded reconnect attempts (15–60 s back-off).

**Time:** all strategy computation is in UTC. The MetaTrader5 Python API documents tick/bar epochs as UTC, but some trade
servers deliver their own server time (MetaQuotes-Demo was verified on 2026-10-07 at exactly +3 h). One contract,
`app/mt5_time.py`, converts every MT5 timestamp exactly once, for the feed, chart, history ranges and FVG execution (quote age,
pending-order expiry, reconciliation):
- `config/mt5_time.json` lists a **verified** offset per exact server name (`broker time = UTC + offset`). It is never guessed
  from a tick and never applied to other servers. Servers without an entry use the legacy explicit
  `GOLD_MT5_SERVER_UTC_OFFSET_HOURS` (default 0 = documented UTC). The effective time base is shown in the feed status.
- A wrong or outdated offset (e.g. after a DST change, expected for MetaQuotes-Demo on 2026-10-25: +2) makes quotes look
  stale/future, so nothing is actionable and the quote note says so; re-verify and update the entry.
- A change of trade server or account in the terminal is treated as a disconnect: the feed reconnects with that server's time
  base and the scanner opens a new session watermark.
The display time zone (e.g. Asia/Bangkok) only changes how times are shown.

## Telegram setup (test group)

1. The bot token is read server-side from `.venv/.env` (`TELEGRAM_BOT_TOKEN`) or `GOLD_TELEGRAM_BOT_TOKEN`. To create a bot, use
   **@BotFather** `/newbot` and treat the token like a password.
2. Add the bot to your destination group/channel and find its numeric **chat ID** (usually starts with `-100`; a bot username is
   not a chat ID). Enter it in **System → Setup**.
3. Press **Verify bot & destination** — a read-only `getMe` + `getChat` check (it sends nothing and never polls `getUpdates`).
4. Press **Send labeled test message** to send one TEST MESSAGE, then turn on **External delivery** when you want signals posted.

Delivery is **off by default**. Enabling it in live mode saves an explicit opt-in bound to the live source, exact symbol, bot (token
fingerprint) and destination; a restart restores it, and changing any of them invalidates it so you must re-enable. Restored opt-ins only apply to new signals — historical or expired signals are never sent.

The token is never shown in the UI, logs, errors or database. A signal message contains exactly four emoji-labelled lines, in this order
(prices at the symbol's precision, RR with two decimals):

```
📍 Entry: <entry price>
🎯 TP: <take-profit price>
🛑 SL: <stop-loss price>
⚖️ RR: <reward/risk>
```

The dashboard (signal table, detail card and message preview) still shows the full signal context.

Delivery uses a durable outbox with these states:

| State | Meaning |
|---|---|
| `pending` | Waiting to be sent, or waiting to retry |
| `sent` | Delivered; Telegram's message ID is stored |
| `failed` | Telegram gave a definite error |
| `unknown` | The outcome is uncertain; never resent automatically |
| `expired` | The signal stopped being timely before it was sent |

Telegram's `sendMessage` has no idempotency key, so exactly-once delivery cannot be promised:
- **Retried while still timely:** connection refused before sending, or HTTP 429 (Telegram's `retry_after` is honoured).
- **Marked `unknown`, never resent automatically:** timeouts, 5xx errors, and crashes mid-send.

## Strategy: CRT-SMC-v1 (our definition)

All thresholds live in `config/strategy.json` and are validated at startup. The config version, a hash of the settings, is stored with every candidate and signal.

These rules are our own version, not a universal ICT/SMC/CRT standard.

**A. Range.** A is a completed H1 candle and B is the next, contiguous, completed H1 candle. A/B is evaluated once, at B's close. A must have a positive range.

**B. Sweep and reclaim.** `tick` is the instrument's tick size; `sweep_min_ticks` defaults to 2.
- **BUY:** `B.low <= A.low - 2*tick`, `B.high <= A.high`, and `A.low < B.close < A.high`.
- **SELL:** mirrored: `B.high >= A.high + 2*tick`, `B.low >= A.low`, and `A.low < B.close < A.high`.
- **Rejected:** double-sided sweeps, closes on or outside A's boundaries, non-contiguous hours, and invalid prices.

**C. Structure level.** A swing high/low is a strict extremum with 2 **closed** M5 bars on each side. Ties are not pivots, and a pivot only becomes available when its second right-hand bar closes.
- **Search window:** the 24 M5 bars before B's open. The window must be contiguous; any gap rejects the candidate.
- **Which pivot:** BUY freezes the most recent swing high confirmed at or before B's open, strictly inside A's range. SELL freezes the most recent swing low.
- **If none exists,** the candidate is rejected.
- **The level is never relabelled** when later bars form new pivots.

**D. Confirmation.** After B closes, the engine waits up to 12 completed M5 bars (one hour) for a close that crosses the frozen level:
- **BUY:** `prev.close <= level < close`.
- **SELL:** `prev.close >= level > close`.

A confirmation that closes outside A's range is rejected. Before confirmation, the candidate is cancelled if:
- the sweep extreme is revisited, or
- the opposite range boundary is touched, or
- M5 continuity is lost, or
- the deadline passes.

Invalidation is checked against each closed bar and against every live quote on each scan. If one bar both invalidates and confirms, invalidation wins. Each candidate is consumed at most once.

**E. Entry and levels.** At confirmation the engine takes the first fresh quote: BUY at **Ask**, SELL at **Bid**.
- **SL:** 2 ticks beyond B's sweep extreme, rounded outward to the tick grid.
- **TP:** the opposite edge of A's range.
- **Required:** SL < entry < TP (mirrored for SELL), reward/risk ≥ 1.5, and spread ≤ 0.50 **in price units** (USD/oz), not points or pips.

The quote time, actual spread, symbol metadata and config version are all recorded.

**F. Timing.** A live confirmation is actionable for at most 30 s after its candle closes, and only with a quote no older than 30 s.
- If the entry check fails, the candidate is consumed with a reason. A delayed entry is never created later.
- **Session eligibility watermark.** Each session gets a fresh watermark, set to the time of its first healthy scan. A new session starts on:
  - process start or restart
  - **Resume**
  - recovery after the feed was disconnected or quotes were stale

  A confirmation is actionable only if its M5 bar closed **strictly after** the watermark; a close equal to the watermark is not actionable. Earlier confirmations are consumed inside the engine (`confirmation_before_session_watermark`), so they never create a signal, an active position or a Telegram job, even if they are less than 30 s old.

  A watermark stored in the database never authorises anything in a later session. History before the watermark is still used for ranges, swings and pending candidates, and active simulated positions keep being tracked.

  While the feed is disconnected or quotes are stale, candidates are not advanced; outcome tracking continues.

**G. Lifecycle.** Candidates, invalidations, expirations, rejections and signals are stored in SQLite with reasons.
- There is at most one signal per symbol/A/B/config version, deduplicated across restarts.
- No new signal is created while a simulated signal on the same symbol is still active.
- **Pause** stops new alerts; outcome tracking continues.

### Simulated outcomes

| | Live | Replay |
|---|---|---|
| Exit prices | **Live MT5:** measured on observed ticks (bounded chronological `copy_ticks_range` reads plus the current quote) — BUY exits on Bid, SELL exits on Ask. A failed tick read is recorded as a measurement gap; no estimate replaces it. | Same sides |
| Entry fill | First fresh quote at confirmation | Next executable observation: the next M5 open with the assumed spread and slippage, or the first valid tick within 30 s after the confirmation close and inside the replay period |
| States | pending, active, TP, SL, expired (after 24 h, configurable), ambiguous | Same |
| Same-bar TP and SL | **AMBIGUOUS**, excluded from the win rate | Same |

**Tick replay** advances with the replay clock:
- At each M5 close, each open position is checked only against ticks up to that moment. An exit is settled at its own tick timestamp, and the overlap guard is released only after the exit has actually happened.
- Ticks the data source returns outside the requested window or the replay period are discarded, and ticks are sorted by time.
- Missing ticks never create a fill or a price hit. A position whose exit isn't observed before the period ends is reported as `open_at_end`.
- Limitations: price paths between ticks are not interpolated, and candidate invalidation still uses closed M5 bars.

Replay splits history chronologically: the last 30% is a held-out segment that is never used for tuning. Its report lists:
- sample size and cost assumptions
- rejected, expired and ambiguous counts
- win rate with its explicit denominator
- mean R and maximum drawdown in R

No performance is invented when history is unavailable.

## Active strategy selection (CRT-SMC-v1 or FastSweep)

The live scanner runs exactly one strategy, chosen in `config/active_strategy.json` (no file = CRT-SMC-v1):

```
.venv/Scripts/python.exe -m app.active_strategy                     # show the current choice
.venv/Scripts/python.exe -m app.active_strategy fastsweep rr2       # FastSweep, fixed 1:2 (activated 2026-10-06)
.venv/Scripts/python.exe -m app.active_strategy crt                 # rollback to CRT-SMC-v1
gold.cmd restart                                                    # apply
```

Unknown strategies/profiles or extra keys stop startup with a clear error. CRT keeps its own `config/strategy.json`.
Each effective configuration is fingerprinted into its record version (e.g. `FastSweep-M15-M5-v1-RR2@…`), so candidate
and signal history of every strategy/profile stays separate; pending setups of a non-active strategy are closed as
`retired_strategy_switch` and never evaluated with other rules. Historical CRT records keep their H1 labels.

**FastSweep live behaviour** (`app/fastsweep_live.py`, same rule functions as the replay):
- Each newly closed M5 bar is processed once; M15 A/B is evaluated only at B's close from complete M5 groups. The EMA
  trend uses the contiguous M15 run inside a 600-bar M5 window; after every daily market break it needs 50 new
  contiguous M15 candles (~12.5 h) before setups can pass (`trend_warmup`). The dashboard shows this readiness.
- Entry at the first measured quote at/after the confirmation close, within 30 s (BUY Ask, SELL Bid, spread <= 0.50);
  a later or future-stamped quote is rejected, a current Bid revisiting B's sweep extreme cancels the setup.
- Controls come from persisted signals (restart- and profile-switch-safe): one active signal per symbol (any strategy),
  >= 30 min since the last FastSweep-family signal, max 4 FastSweep-family signals per Bangkok date (a cap).
- Only confirmations closing strictly after the session watermark (startup, restart, resume, feed recovery) alert.
- Outcomes: measured Bid/Ask ticks as before; FastSweep signals expire after 2 h, older signals keep their own expiry.
- Telegram: the same four-line Entry/TP/SL/RR message through the existing opt-in.
- The dashboard Replay offers CRT (legacy) or FastSweep (OHLC, isolated in-memory); each result shows its own strategy.

The 60-day research evidence below was negative for both profiles; activation was the user's explicit choice and does
not imply 3-4 daily signals or profitability.

## FVG-Trend-M15-M5-v1 (opt-in automatic execution, default OFF, not active)

Code: `app/fvg.py` (rules), `app/fvg_orders.py` (sizing), `app/fvg_execution.py` (MT5 requests, journal, reconciliation),
`app/fvg_live.py` (live engine), `app/fvg_replay.py` (OHLC replay). It is selectable with
`python -m app.active_strategy fvg rr2` but **has not been selected**; `config/active_strategy.json` stays FastSweep rr2.

- **Setup:** closed contiguous M5 bars, M15 from complete groups. BUY gap = [A.high, C.low], SELL = [C.high, A.low]; it must be
  >= max(2 ticks, 0.10 x ATR14), B's body >= 1 x ATR14 (Wilder ATR through B), and the EMA20/50 trend over >= 50 contiguous
  M15 candles must agree. The first M5 bar touching the zone is the retest; a *different* bar among the next 3 must close beyond
  the retest high (BUY) / low (SELL). Any M5 close beyond the far edge (before or after the retest) invalidates; lifetime 2 h.
- **Basket:** three limits at 1% / 50% / 80% depth (BUY rounded down, SELL up), one common SL two ticks beyond the far edge,
  each leg its own 1:2 TP. One open basket per symbol, 30 min cooldown, max 4 baskets per Bangkok date, pending expiry 2 h,
  a far-edge close cancels this basket's remaining pending legs (owned orders only). That far-edge check keeps running
  while the scanner is paused or catching up after stale quotes, and a resume never skips it.
- **Decision-time eligibility (rule 6):** a confirmation older than 30 s, from the future, or of an already expired setup
  is consumed as rejected (a delayed scan never acts on it). Every leg's |entry - SL| must be >= current spread + 1 tick
  (`stop_within_spread`) and every limit must rest >= 1 tick on the correct side of the market
  (`limit_on_wrong_side_of_market`), otherwise the WHOLE basket is rejected before any alert, reservation or capacity
  use; the executor repeats both on the send-time quote. Replay applies the same rules with its assumed spread (0 of the
  16 cached-history baskets are affected at 0.20, 0.33 or 0.40).
- **Account identity:** consent (opt-in), execution policy and journals are bound to the trade SERVER plus login (hashed).
  The same login on another server is another account; legacy login-only consent/journals never match and stay visible
  for manual review. Capacity counts baskets of the connected account (plus alert-only plans).
- **Risk:** fixed total planned SL risk per setup from `config/fvg_risk.json` (`risk_usd_per_setup`, currently 10 USD),
  split into three equal shares; each leg's lots are the share / MT5 loss-per-lot, rounded **down** to the lot step. If any leg
  cannot fit the minimum lot the whole basket is rejected (no redistribution). USD accounts x1, USC (cent) x100, others refused.
  Fees, gaps and slippage can make actual losses larger.
- **Who may trade (precedence):** 1) your explicit **Turn OFF** beats everything and persists across restarts and account
  switches until you turn it ON again; 2) an exact saved arming (source/symbol/strategy version/server+login) - the only
  way for REAL or CONTEST accounts; 3) `config/fvg_execution.json` `default_on_for_demo_accounts: true` - any verified
  DEMO account (also after switching demo account/server) is ON without a new click. Unknown account types fail closed.
  The dashboard shows which applies ("armed by you", "ON by default (demo account)", "turned OFF by you", ...).
- **Freshness at the send boundary:** the decision uses the current clock (not the scan start); the confirmation age
  (<= 30 s), setup expiry and pending lifetime are re-checked before preflight, after preflight and immediately before
  every send. If they lapse mid-batch the remaining legs are not sent and accepted legs stay reconciled.
- **Cancellation recovery:** a far-edge invalidation is recorded durably; removal of this basket's pending remainders is
  retried (every 30 s, after re-reading the broker's current pending orders) until the broker shows none left. An
  unreadable order list counts as unknown, never as "none", and a removal that already succeeded is not repeated.
- **Execution switch:** System -> *FVG automatic execution* (or `POST /api/fvg/execution` with `confirm: true`). Refused while FVG
  is inactive, without MT5, without risk config, with an unsupported currency or a netting account. The opt-in is bound to the
  source, symbol, a hash of the account login and the strategy version; any change turns it OFF. Telegram alerts report the plan
  and never trigger orders.
- **Safety:** pre-checks (terminal/account trading allowed, hedging, full trade mode, fresh quote, spread <= 0.50, no existing
  exposure, stop/freeze distances, `order_check`, margin), re-validated on a refreshed quote before the first send. A durable
  journal row is written before any send; a timeout/unknown result is never resent and the remaining legs are not sent.
  Pending orders use `ORDER_FILLING_RETURN`. After a restart the journal is adopted into the basket and reconciled (orders,
  positions, order history, deals: partial fills, remainders, actual P&L including entry costs); nothing is resubmitted.
  All MT5 calls share the feed's lock.

**Replay** (`python -m app.fvg_replay --bars <cached M5 json> --spread 0.20 --slippage 0.05`, OHLC simulation, 2026-08-06 ->
2026-10-05, 41 covered dates): 799 raw gaps -> 59 qualified -> 38 retests -> 16 confirmations = 16 baskets / 48 legs; 31 legs
filled (6 TP, 10 SL, 15 ambiguous: mostly the TP touched inside the fill bar). Basket R: baseline +0.62R (ambiguous legs
excluded), conservative -4.55R (ambiguous counted as stops); 70/30 split earlier +0.96R / -1.80R, later -0.34R / -2.75R.
With spread 0.40 / slippage 0.10: +0.58R / -4.41R. About 0.39 baskets per covered date (26 of 41 had none). This is **not**
evidence of an edge.

## Research: FastSweep-M15-M5-v1 (replay evidence)

A faster candidate strategy first tested in isolated replay (task 20261006-144723) and activated live with the 1:2
profile in task 20261006-151121 (see "Active strategy selection" above). Code: `app/fastsweep.py` (rules) and
`app/fastsweep_replay.py` (pure replay, controls, statistics, runner). Two profiles: `FastSweep-M15-M5-v1-RR1` (TP = 1×
risk) and `-RR2` (TP = 2× risk).

- **Candles:** M15 built with `aggregate()` from complete contiguous M5 groups; A/B are adjacent closed M15 candles.
- **Range:** the CRT predicates on M15 - B sweeps one side of A by >= 2 ticks, does not exceed the other side, and closes
  strictly inside A. Double-sided and non-adjacent pairs are rejected.
- **Trend:** EMA20 vs EMA50 of M15 closes over the contiguous run ending at B (SMA-seeded); needs >= 50 contiguous candles
  (a daily market break restarts the run). EMA20 > EMA50 allows BUY, < allows SELL, equal allows neither.
- **Confirmation:** within the next 3 closed M5 bars after B: BUY when the previous close <= B high < close (SELL mirrors
  with B low). Revisiting B's sweep extreme invalidates first; a missing M5 bar invalidates.
- **Entry / stop / target:** next contiguous M5 open (BUY Ask = open + spread, SELL Bid); stop 2 ticks beyond B's
  extreme; TP = entry ± R × risk rounded outward (R = 1 or 2). Spread <= 0.50, quote freshness 30 s.
- **Controls:** one active signal, >= 30 min between new signals, max 4 per Bangkok date (UTC+7, a cap, not a quota),
  2-hour expiry marked at the last observed close. Outcomes reuse `app/outcomes.py` (Bid/Ask exits, same-bar ambiguity).

Run (reads candles only through the running app's `GET /api/market/bars`; outputs to `.tmp/fastsweep/`):

```
.venv/Scripts/python.exe -m app.fastsweep_replay --start 2026-08-06T07:00:00Z --end 2026-10-05T06:55:00Z --profiles rr1,rr2 --spread 0.20 --slippage 0.05
```

Measured on 2026-08-06 07:00 -> 2026-10-05 06:55 UTC (11,560 M5 bars; spread 0.20, slippage 0.05): about 101-102 signals,
mean 2.3 signals per covered Bangkok date (>= 12 h of data), 3-4 signals on 46% of covered dates; simulated result
negative for both profiles (RR1 -19.3R, RR2 -17.7R). Details: `report/20261006-144723-fast-sweep-strategy-report.md`.
These are price-hit simulations on an already-inspected sample, not evidence of profitability.

## Running locally (Windows)

VC Signal runs entirely on this computer: start your MT5 terminal, then `gold.cmd start` (or `restart`), open
http://127.0.0.1:8000/, check `gold.cmd status`, read `.tmp/gold-signals/server.log`, and `gold.cmd stop` to stop. Scanning continues
with the browser closed, as long as Windows, MT5, the VC Signal process and the internet connection stay up — nothing is installed as
a service or scheduled task. Only one process may own the scanner and Telegram sender (an OS lock on `.tmp/gold-signals/owner.lock`);
a second process serves no scanner, and the lock is released automatically if the owner dies.

**Future deployment (deferred):** the intended hosting is a Windows VPS running MT5 and VC Signal together, reusing the same
non-secret settings and history. Nothing for that is built or tested yet (no services, watchdogs, remote access or public ports).

## Layout

| Path | Contents |
|---|---|
| `app/` | Strategy rules, engine, SQLite store, scanner, MT5 feed, Telegram delivery, replay, FastAPI web app, static dashboard, launcher |
| `config/strategy.json` | Validated strategy thresholds |
| `config/mt5_time.json` | Verified MT5 trade-server time offsets, bound to the exact server name |
| `config/fvg_risk.json` | FVG fixed risk budget per setup (a preference; it does not arm execution) |
| `tests/` | Strategy timing/rules, replay, delivery (mocked network), scanner/persistence, API, FVG execution (fake broker only). Test-only fictional fixture: `tests/data/xauusd_fixture_m5.json` (rebuild with `python -m tests.fixture_gen`); `tests/conftest.py` makes every test use an offline fake instead of a real terminal |
| `.tmp/gold-signals/` | Databases (`mt5-<symbol>.sqlite`, FVG stores and journals; an old `demo.sqlite` from earlier versions is left untouched and unused), logs, server record, replay results, pip cache |
| `tools/`, `prompt/`, `report/` | The agent-to-agent handoff helper and its history; not part of this app |

## Security notes

- The server listens on `127.0.0.1` only.
- Requests with an unexpected `Host` header are refused.
- Requests that change state need the per-session token embedded in the page, and must come from the same origin. No CORS is enabled.
- `.env` and `.tmp/` are git-ignored. `server.json` holds the session token so `gold.cmd stop` can shut down gracefully; it stays local.
