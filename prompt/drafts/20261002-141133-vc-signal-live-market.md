# VC Signal local live market and TradingView-style chart

Task ID: 20261002-141133-vc-signal-live-market
Delivery status: DRAFT — DO NOT EXECUTE
User authorization: pending
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261002-141133-vc-signal-live-market.md`
Report path: `report/20261002-141133-vc-signal-live-market-report.md`
Progress path: `report/20261002-141133-vc-signal-live-market-progress.md`

## Goal and current evidence

The user wants a real system analyzing the real gold market and sending eligible signals into Telegram, rather than a dashboard confined to demo. Use VC Signal/TailAdmin and the existing CRT-SMC-v1 rules to build and validate the operational live-market workflow.

Confirmed current target: this local Windows computer, running Exness MT5 and VC Signal together. The user explicitly wants to evaluate the real system locally first and will authorize VPS deployment later only if satisfied. Real prices and candles come from the logged-in Exness MT5 desktop terminal. The user selected dashboard first, then Telegram after a labeled test. Keep external delivery off during implementation and validation. Do not add Twelve Data/MetaApi or use any token previously pasted into chat. No server purchase, remote access, deployment or public hosting belongs to this task. Dispatch approval is still pending.

Completed/reviewed baseline: 82 tests pass, the three historical-alert/replay/lifecycle defects are repaired, TailAdmin and VC Signal branding are live. Read report/20261002-140743-tailadmin-branding-codex-review.md.

Operational gaps found in code:
- app/web.py Workstation and lifespan force demo, ignoring Settings.data_mode.
- app/config.py reads root .env, but the user intentionally keeps configuration in .venv/.env. That file contains TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_USERNAME; it also contains unrelated keys. The current app expects GOLD_TELEGRAM_BOT_TOKEN and GOLD_TELEGRAM_TEST_CHAT_ID. Codex inspected names/presence only, not printed values. No standalone Telegram group ID or GOLD_SYMBOL was found.
- No terminal64/terminal process was found during planning. The user must log in through their own Exness MT5 terminal; do not request broker passwords in chat.
- The chart is setup-selection oriented and provides no default current-market view before a setup exists.
- MT5 timestamp offset guidance contradicts the official Python API documentation; standard returned epochs are UTC.
- Live SELL outcomes currently use Bid bars plus entry spread, which is an estimate rather than historical Ask evidence.

## Scope

Relevant files include app/config.py, app/web.py, app/data/mt5.py, app/data/base.py, app/scanner.py, app/outcomes.py, app/delivery.py, app/store.py, app/launcher.py, app/server.py, frontend/src/index.template.html, app/static/app.js, frontend build sources, README.md, .env.example and tests. Change only what is needed for this live workflow. Retain TailAdmin and VC Signal branding, local loopback serving and current strategy parameters.

This is market analysis and alerts only. Preserve the no broker order execution boundary. Do not change global tools, unrelated projects or permission/security settings. Read only project-local configuration and the user-selected MT5 terminal API context. Do not dump credentials, account login numbers, balances, .env files or request URLs containing tokens into logs/reports/frontend. Keep caches, artifacts and work inside the project.

## 1. Real feed startup and configuration

- Honor an explicit configured/persisted data-source choice across restarts. A user selecting Live MT5 must restart into Live MT5; a missing terminal/symbol/history must remain an honest disconnected/not-configured live state, without fictional data substitution. Demo stays available only as an explicit separate mode.
- Load the user's existing .venv/.env through a documented project-local configuration mechanism. Preserve root .env support and process environment overrides with deterministic documented precedence. Import only recognized settings, and test conflicting keys. Do not copy every secret into a new file or frontend and do not silently overwrite the user's file.
- Accept TELEGRAM_BOT_TOKEN as an alias for the canonical token setting. Accept documented chat-ID aliases, including TELEGRAM_CHAT_ID/GOLD_TELEGRAM_CHAT_ID and existing GOLD_TELEGRAM_TEST_CHAT_ID. A bot username is not a destination group ID; TELEGRAM_PROVIDERS must not be mistaken for one. Canonical explicit settings should win conflicts consistently. Do not add AI API calls simply because OPENAI_API_KEY exists.
- Provide a real dashboard setup flow for nonsecret terminal path, exact broker symbol, source selection and Telegram destination chat ID. Keep tokens loaded server-side and expose only configured/missing/masked status. Do not prepopulate forms with secret values. Persist nonsecret choices locally with atomic writes and validation. No setup change should erase signal history.
- Connect to the user's existing MT5 terminal via read-only operations. Check connected/account/server context without logging login/balance. Show the broker/server so the user can verify Exness. Never silently switch accounts or submit login credentials.
- Discover gold candidates from the actual terminal and provide an exact-symbol selector. Never guess among XAUUSD, XAUUSDm or similarly named contracts. Require selection if multiple contracts are available. Use symbol_info tick size/point/digits and actual Bid/Ask.
- Any symbol or source change opens a new scanner session/watermark and keeps dedup/history separated by source/symbol/config. Do not replay missed confirmations into live Telegram or create historical active simulated entries.

## 2. Real-time market analysis and chart

- Live mode polls the real provider at the configured interval, with completed H1/M5 candles and valid fresh quotes. Display provider, broker/server, exact symbol, Bid/Ask, spread, quote timestamp/age, last completed H1/M5 timestamps, last scan and data-quality state.
- Add a default current-market chart with recent real M5 candles, available without selecting a signal/setup. Refresh it from the feed and keep selected historical setup inspection available. If displaying a forming candle, clearly distinguish it and never feed it into confirmation logic.
- Show actual strategy state: waiting for closed H1 range, no eligible sweep, pending structure confirmation, confirmed/consumed, invalidated, expired, rejected, paused or disconnected. Show relevant frozen range/structure/SL/TP when available. Keep decisions explainable through actual rule conditions and rejection reasons.
- Never invent a signal just to prove the system works. No eligible setup is a valid live result. Source data and each decision should have UTC timestamps and strategy version/provenance in persistent records.
- Preserve the repaired startup/reconnect watermark and dedup rules. Handle disconnects, stale/future quotes, history gaps, invalid data, symbol unavailability and market closure with visible status and bounded reconnect behavior. A healthy recovery must not release missed confirmations.

## TradingView-style interactive chart

The user additionally requests a chart in VC Signal that looks and behaves like TradingView. Replace the current static canvas chart with TradingView's official open-source Lightweight Charts library, keeping the local Exness MT5 feed as its data source. This is a custom market chart, not an embedded widget fetching another broker's prices. Use the library's candlestick/time-scale/crosshair features and implement app-specific overlays/controls. No Advanced Charts account/license or Pine Script support is part of this task.

Official docs: https://tradingview.github.io/lightweight-charts/docs (current fetched docs version 5.2)
Official source: https://github.com/tradingview/lightweight-charts

Pin an appropriate stable package version in the existing frontend lockfile, use its matching documented API, serve its production bundle locally, and retain required LICENSE/NOTICE attribution including a visible TradingView link. Keep TailAdmin notices and VC Signal branding. Do not use CDN scripts or replace the app with TradingView branding.

Required user experience:
- A prominent Chart section reachable from the sidebar and overview, with the selected broker symbol/source, latest Bid/Ask and readable candlesticks, time axis and precision-aware price axis.
- Mouse-wheel zoom, drag-to-pan, touch gestures, crosshair with UTC timestamp/OHLC readout, price/time-scale controls and a working reset-view/return-to-live action. A real fullscreen or expanded-chart action must resize correctly and return to the dashboard.
- Timeframe toolbar: 1m, 5m, 15m, 1h, 4h, 1d. In live mode request actual corresponding MT5 timeframes and distinguish missing history. Chart timeframe changes are display-only: strategy remains H1 range plus M5 confirmation. For fixture mode, derive only supported timeframes without inventing prices and label unavailable ones.
- Feed the chart real recent bars even when no signal exists; display loading/disconnected/stale/no-history states honestly. A forming candle may update from the provider if clearly labeled; analysis uses completed candles only.
- Update the last candle incrementally and append newly observed bars with ascending unique timestamps. Polling must preserve the user's zoom/pan position; returning to live should be an explicit action if the user is browsing older history. Load older actual history on demand with bounded requests, stable scroll position and no fabricated gap filling.
- For a selected setup/signal overlay the A high/low range, sweep extreme, frozen structure, entry, SL and TP with readable labels and confirmation/BUY/SELL markers. Remove old overlays when selections change. A return-to-live action restores the current market view. All overlay prices/times must match backend records.
- Include display toggles for EMA20 and EMA50 calculated only from available chart bars. These are visual aids and must not change signal rules or be described as separate confirmations. Show tick-volume histogram only if actual tick_volume is supplied; never fabricate exchange volume.
- Light/dark chart colors follow the dashboard theme; responsive size and controls work at about 1440px and 390px. Avoid clipped labels, hidden chart containers and page-wide overflow. Provide readable OHLC/status text outside the canvas for accessibility.

Engineering/validation:
- Keep chart-only timeframes/DTO fields isolated from the engine's supported H1/M5 processing. Validate symbol/timeframe/history request bounds on the backend and reuse correct UTC parsing.
- Avoid stale async responses overwriting a newly selected symbol/timeframe/source, duplicated listeners on repeated navigation, leaked chart instances or resize loops. Remove subscriptions/observers when disposing. Keep tokens exclusively server-side.
- Test actual candle mapping/order/dedup, supported timeframe validation, UTC timestamps, setup overlay data and separation of chart indicators/timeframes from strategy rules. Browser-smoke-check zoom/pan/crosshair, latest-bar update, timeframe changes, history loading, overlays, reset/live, expansion, theme, mobile sizing and failure states; do not add markup-mirroring tests.
- Build local assets and document package/version, attribution, data source and supported chart functions. Report unavailable live data or browser validation honestly. Screenshots are supporting evidence, not a substitute for real provider checks.

## 3. UTC and measured outcomes

Official MT5 Python docs state tick/bar epochs are UTC. Remove unconditional broker-offset adjustment for standard API output, and correct README/config guidance. If retaining a legacy offset setting, treat nonzero use explicitly and prevent silent double shifting. Use UTC-aware request ranges, and isolate any desired local display timezone from strategy computation. Test real UTC epochs and Bangkok display behavior without shifting source data.

For live simulated outcomes, use observed Bid ticks for BUY and Ask ticks for SELL. Do not report an estimated Ask hit from Bid bars plus entry spread as a definite measured exit. Prefer bounded chronological tick reads after entry/last checked, followed by the current quote, with sorting/validation, no future observations and reliable cleanup. If historical ticks are missing or incomplete, record/display that limitation conservatively; do not fabricate prices or an exact exit. Outcomes remain simulated price observations, never broker fills. Preserve dedup/overlap/expiry semantics.

## 4. Telegram live workflow

- Configure the existing local bot token using aliases above and a verified destination group ID. Provide server-side read-only bot/destination validation with Telegram getMe/getChat; sanitize all errors and reports. Do not infer a group from bot username or disturb another consumer by blindly polling getUpdates.
- Default delivery off until the user performs the runtime enable action. The labeled connectivity test is sent only through an explicit test-button action, not automatically during validation. The user selected dashboard first; this task does not authorize any real Telegram message. A later explicit test-button click and delivery-enable action govern sending.
- Distinguish DEMO/TEST alerts from LIVE MARKET SIGNAL alerts. Real source signals must include VC Signal, exact symbol, BUY/SELL, observed entry side/price, quote and confirmation times, SL, TP, R:R, validity, rule explanation and strategy version. Keep outcome labels accurate and do not imply executable fills or proven performance.
- Preserve durable outbox deduplication and pending/sent/failed/unknown/expired states. Do not blindly resend ambiguous timeouts/5xx. Prevent stale or historical startup/reconnection alerts. Demo alerts must never be passed off as live.
- Show connected bot/destination status and delivery state in TailAdmin. Keep the message preview fully functional. Missing target ID should have a clear setup action rather than a generic error.

## 5. Real historical validation and operation

- Extend the dashboard replay workflow to the selected real MT5 gold symbol and explicit period (default up to 60 days when provider history exists). Keep chronological development/holdout reporting and actual available history bounds/counts. Label assumptions and gaps. Do not claim mock/demo replay validates real-market performance or optimize rules against holdout.
- Keep real market chart/history availability independent from waiting for a new live signal. Do not manufacture old actionable entries to fill the Signals table; historical replay remains separately labeled.
- Provide clear launcher/run/status/log instructions for Windows and document that this computer/terminal must stay running for continuous local scanning. Do not install services/scheduled tasks or paid hosting without separate scope.

## Local Windows operation; deployment deferred

Run and validate this implementation entirely on the user's current Windows computer in E:\VideCode\vc_trade. MT5 and the local Python backend run together; the user's own Exness terminal login provides real broker prices. Keep the dashboard on loopback at http://127.0.0.1:8000/. It must continue scanning while the browser is closed as long as MT5/backend, Windows and internet remain available. Provide straightforward local start/stop/status/restart instructions and clear dependency/connection status. No VPS is needed for this evaluation.

Add a project-local cross-process ownership guard or equivalent robust protection for the scanner/delivery owner, not merely a threading.Lock. An accidental second launcher/web-worker process must not create a second live scanner or outbox sender. Test duplicate startup and clean recovery after owner termination. Keep API/frontend serving compatible with the single-owner model.

For continued operation after explicit user enablement, implement persistence of the user's runtime delivery opt-in, bound to the live source, exact symbol and configured bot/destination identity. Initially it remains disabled. Only a later user test-button/delivery-enable action may create that opt-in. Source/symbol/bot/destination changes must invalidate it or require reconfirmation. A restart may restore an existing valid explicit opt-in, without replaying historical or expired signals. Exercise this through mocks only in this task; never send a real message during implementation/validation.

The future hosting direction remains a Windows VPS running MT5 and VC Signal, but deployment is expressly deferred until the user evaluates and approves the local system. A short future-deployment note is sufficient; do not build deployment-only authentication/proxy integrations, VPS watchdogs or scheduler/service templates in this task. Do not buy/provision a server, access a remote host, change Windows power/login policy, register services/scheduled tasks, expose public ports or deploy. Do not claim unattended VPS recovery has been tested. Preserve portable nonsecret configuration and durable history so a later approved deployment can reuse them.

## Acceptance and validation

Add meaningful tests for cross-process owner protection/recovery, valid delivery opt-in persistence/invalidation, config precedence/aliases/redaction, configured live startup and restart persistence, exact-symbol selection, no demo fallback on connection failure, standard UTC epochs, current chart without a setup, live-mode message labeling, measured Bid/Ask outcomes and missing ticks, and preservation of all repaired watermark/replay behavior. Run the full existing suite plus additions using unique .tmp directories. Build local frontend assets and run relevant syntax/type checks.

After implementation, use the user's logged-in terminal for a read-only real smoke check if available: verify the selected Exness symbol, valid current Bid/Ask/UTC tick time, actual closed H1/M5 bars, scanner/chart updates across multiple scans and a real-data replay with actual returned bounds/counts. Compare prices/times against the terminal where possible. Never place orders. Telegram validation may perform getMe/getChat read-only after a target is configured; do not send a test or signal during validation absent explicit authorization.

If MT5 is not running/logged in, the symbol is not selected or destination is missing, finish all independent implementation and mock checks, then report the exact remaining setup action. Do not declare the real integration verified or live market operational based solely on mocked tests. Report separately: code complete, real data connection verified, scanner observed, historical replay observed, bot/destination verified, real message sent (if authorized), and ongoing live mode health.

Verify TailAdmin desktop/mobile states, configuration forms, current chart, mode persistence, disconnected/stale status and Telegram controls. Keep local server at http://127.0.0.1:8000/ when available and leave selected live mode running with honest status; do not reset to demo merely because live setup is incomplete. Report URL/PID and external delivery state. Keep the task panel at http://127.0.0.1:4318/ available.

## Primary technical references

https://get.exness.help/hc/en-us/articles/360011514572-MT5-Trading-guide-Desktop
https://get.exness.help/hc/en-us/articles/360012578619-Trading-account-login-and-server-details
https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py
https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py
https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py
https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py
https://core.telegram.org/bots/api#getme
https://core.telegram.org/bots/api#getchat
https://core.telegram.org/bots/api#sendmessage

## Reply and stopping condition

Claude implements; Codex reviews. After dispatch approval acknowledge the exact task at the progress path and keep it updated with implemented, tested, actually connected and blocked milestones. If requirements/permissions block dependent work, report them at the exact final path after completing independent authorized work. Do not alter permissions or invent credentials.

Publish a complete report atomically via project-local temporary file and rename. Include task ID/source prompt, outcome, changed files, architecture/config behavior, actual tests, real integration evidence and gaps, sanitized operational state and precise user actions still needed. Stop after reporting and wait for the next approved prompt.