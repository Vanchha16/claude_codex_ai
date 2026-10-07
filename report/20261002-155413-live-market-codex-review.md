# Codex review: VC Signal local live market

Task reviewed: 20261002-141133-vc-signal-live-market
Claude report: report/20261002-141133-vc-signal-live-market-report.md
Review result: partial acceptance; one independently reproduced outcome-expiry defect remains, and real MT5/Telegram validation is pending.

## Independently verified

- Python: 102 tests passed (one Starlette/httpx deprecation warning).
- Frontend: 4 tests passed; npm build and JavaScript syntax checks passed.
- Dashboard and chart JavaScript endpoints return HTTP 200 at http://127.0.0.1:8000/.
- Runtime: PID 1908, persisted mt5 mode, one owner, scanner running, feed disconnected, no selected symbol or quote. No MT5 terminal process found.
- Telegram remains disabled; destination is missing. No external messages were sent by this review.
- Inspected Claude's desktop demo chart and disconnected-live screenshots. Interactive browser checks are Claude's reported validation, not independently repeated here.

## Finding: live outcomes can count a hit after expiry

app/outcomes.py: track_measured processes observations up to now before checking the signal's configured expiry. app/scanner.py: _observed_quotes also requests observations up to now instead of the expiry boundary. After a sufficiently long outage, reconnecting can therefore mark TP/SL from a tick after the signal should have expired.

Read-only reproduction using make_signal from tests/test_live_market.py:
- BUY created 2026-09-30 10:02:30 UTC, configured expiry 24 hours, TP 2410.
- Observed Bid at +23h: 2401.0 (no hit).
- Observed Bid at +25h: 2411.0 (TP touched after expiry).
- Call track_measured at +25h+1s.
- Actual: tp at 2026-10-01 11:02:30 UTC, price 2411.0.
- Expected: expired at 2026-10-01 10:02:30 UTC, using only the last eligible observation (2401.0), with the observation timestamp disclosed.

Claude should bound live observation processing to the expiry instant, settle expiry at that instant, and add regression coverage for delayed reconnect and post-expiry observations. Also ensure bounded tick catch-up never skips unread intervals by appending a current quote after the chunk budget is exhausted. No application source was changed by Codex.

## Remaining integration steps

Open the Exness desktop MT5 terminal and log in. In VC Signal System > Setup, use Find, select the exact gold contract, and save. Then verify actual quotes, candle timestamps, scanner warm-up/session eligibility and real history replay. Configure the numeric Telegram destination and perform read-only verification before a separately authorised labelled test and enable action. VPS deployment remains deferred.