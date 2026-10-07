# Codex real MT5 connection check

User confirmed terminal and setup completed. Read-only checks performed on 2026-10-02 around 09:03 UTC (16:03 Bangkok).

- Local app http://127.0.0.1:8000/ healthy, PID 1908, single owner, mt5 mode.
- Running MT5 terminal found. Feed connected read-only to Exness with exact symbol XAUUSDc.
- Fresh actual Bid/Ask quote changed between checks: 4181.176/4181.416 then 4181.839/4182.079, spread 0.240. These are point-in-time observations, not a recommendation.
- M1, M5, M15, H1, H4, D1 each returned 50 closed bars plus a forming candle. Closed bars were ordered, unique, and had consistent OHLC bounds.
- Scanner running every five seconds, not paused, no scanner error or data issues; session watermark 08:52:36 UTC. Latest closed M5/H1 both closed 09:00 UTC.
- Actual strategy state: pending SELL structure confirmation after 09:00 UTC B close. No signal created at the check time. A pending candidate is not an entry signal.
- Telegram status shows successful user-initiated bot and destination verification. Destination type is private, not group/supergroup. Delivery remains disabled. No Telegram verification calls or messages were sent by Codex.
- Real historical replay and live outcome accuracy are not yet independently validated. Outcome-expiry finding in report/20261002-155413-live-market-codex-review.md remains unresolved.

## Direct website MCP attempt

At the user's request, attempted direct website inspection. cua.getState returned no apps or browsers; creating an in-app browser returned Browser is not available: iab. Initialized the installed computer-use skill's @oai/sky package via node_repl, then sky.list_apps failed with Computer Use native pipe is unavailable: failed to connect native pipe: The system cannot find the file specified. (os error 2).

Therefore no direct live UI inspection was completed by Codex. Backend data verification above is independent; earlier screenshot/browser claims remain attributed to Claude. No application source or runtime settings were changed.