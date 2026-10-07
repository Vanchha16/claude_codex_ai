# Codex verification: FVG basket review fixes

Task ID: 20261007-161242-fvg-basket-review-fixes
Source prompt: `prompt/20261007-161242-fvg-basket-review-fixes.md`
Claude report: `report/20261007-161242-fvg-basket-review-fixes-report.md`
Status: **REPORT RECEIVED; INDEPENDENT REVIEW NOT ACCEPTED AS FULLY COMPLETE.**

Claude implemented the reviewed changes and restarted the backend. Codex reran the full application tests and inspected the result. Most original counterexamples are covered, but two residual execution/maintenance failures reproduce independently. The demo default-ON behavior also violates the task's consent criterion and the user's latest explicit choice.

## Validation and current runtime

- **288 backend tests passed**, zero failures/errors/skips, XML recorded below.
- **36 dashboard tests passed**; `node --check app/static/app.js` passed.
- Source inspection and fake-broker/feed reproductions only; no code fixes by Codex, no real orders/checks/cancellations/messages from Codex verification.
- Read-only runtime observation at 2026-10-07 09:28:18 UTC: MetaQuotes-Demo **demo**, XAUUSD, FVG RR2 `FVG-Trend-M15-M5-v1-RR2@8a49bace`, fresh quote, scanner running/error=null, **automatic execution OFF**, **Telegram ON and persisted**, fixed **10 USD** risk, warm-up **45/50**, zero baskets/setups. Preserve this disarmed state pending correction and explicit rearming.
- The project is now a Git repository; Claude reports the user created/pushed it separately and made separate requests before this task. Existing uncommitted application/helper files are not authorization for Codex to commit, push, or execute manual broker-test tools. No such actions were performed here.

## Blocking findings

### 1. High / P1 ? Slow decisions still bypass the confirmation-age limit

Locations: [confirmation age uses scan-start `now`](E:/VideCode/vc_trade/app/fvg_live.py:208), [fresh entry callback discards its current time](E:/VideCode/vc_trade/app/fvg_live.py:233), [executor accepts no confirmation-deadline context](E:/VideCode/vc_trade/app/fvg_execution.py:250).

The new guard rejects a backlog if the supplied scan-start timestamp is already late. It does not refresh that timestamp after work delays the scan. The entry callback returns a current quote and current time, but only the quote is used. The executor correctly refreshes its quote-age clock, yet never checks the confirmation's age with that clock. A fresh quote can therefore permit an old confirmation.

**Independent reproduction:** the scan timestamp is confirmation+1 second, but the current entry callback and executor clock are confirmation+121 seconds. All broker quotes are fresh against that current clock. With a configured 30-second confirmation limit, the engine still queues one plan alert and submits all three fake pending orders (`orders_pending`).

**Needed correction:** obtain a trustworthy current decision clock before basket/alert acceptance and carry immutable confirmation/expiry context to execution. Recheck it immediately before any first send, including after slow preflight. Never make quote timestamp itself stand in for current wall-clock time. If eligibility expires during a batch, preserve accepted/uncertain legs for reconciliation and stop sending the rest. Add slow-callback and slow-preflight regressions with independent injectable clocks.

### 2. Medium / P2 ? A failed cancellation is marked handled and never retried

Locations: [invalidated baskets excluded from maintenance](E:/VideCode/vc_trade/app/fvg_live.py:305), [bar management skips an invalidation marker](E:/VideCode/vc_trade/app/fvg_live.py:321), [marker written even when removal was unknown/rejected](E:/VideCode/vc_trade/app/fvg_live.py:340), [cancellation returns unknown state without raising](E:/VideCode/vc_trade/app/fvg_execution.py:484).

`cancel_remaining()` records `cancel: unknown` for a timeout/connection result and returns a payload. `_manage_bar()` then writes `zone_invalidated_at` unconditionally. Every later maintenance pass excludes this basket. Reconciliation reads exposure but does not retry the required removal, so a still-live owned remainder persists even after connectivity recovers and price returns inside the zone.

**Independent reproduction:** one owned 80% remainder returns a cancellation timeout. The basket is marked invalidated; after restoring successful fake broker access, reconciliation and catch-up over both the breach and return-inside bars send zero successful removals. Ticket 103 remains pending with `cancel: unknown`.

**Needed correction:** separate durable invalidation detection from cancellation completion. Preserve the invalidation even after a return inside, and keep resolving/retrying owned remainders until fresh authoritative broker evidence confirms they are gone. Do not retry an unknown removal blindly; first verify the same owned ticket is still pending on the correct account. Failed queries are unknown, not an empty order list. Keep filled positions and broker SL/TP untouched.

### 3. High / P1 consent requirement ? Demo default ON bypasses fresh account-bound consent

Locations: [default fallback](E:/VideCode/vc_trade/app/web.py:188), [configuration](E:/VideCode/vc_trade/config/fvg_execution.json:3).

Claude disclosed that a separate user request introduced `default_on_for_demo_accounts: true` before this task. Its currently persisted OFF marker makes the feature inert, but once the user arms again and clears that marker, a different demo account/server can become ON even when the saved exact binding does not match.

**Independent reproduction:** fake demo A is explicitly armed. Switching to fake demo B with the same login but a different server makes the saved binding mismatch; `_fvg_armed()` nevertheless returns ON via `default (demo account)`.

**Resolved user decision:** when asked whether to require fresh arming or enable every demo account, the user explicitly chose **"Require fresh arming for each account/server (Recommended)"** in this conversation. This supersedes the conflicting demo-default preference reported by Claude. Remove/disable the automatic default path for all account types. Do not merely rely on the current global OFF marker; enforce exact saved consent even after that marker has been cleared by legitimate arming.

## Evidence

- [Residual probe script](E:/VideCode/vc_trade/.tmp/fvg-basket-fixes-codex-review/reproduce-residuals.py) and [results](E:/VideCode/vc_trade/.tmp/fvg-basket-fixes-codex-review/residual-reproduction-results.json).
- [Demo consent probe results](E:/VideCode/vc_trade/.tmp/fvg-basket-fixes-codex-review/default-demo-consent-reproduction.json).
- [Validation summary](E:/VideCode/vc_trade/.tmp/fvg-basket-fixes-codex-review/validation-summary.json), [backend XML](E:/VideCode/vc_trade/.tmp/fvg-basket-fixes-codex-review/backend-tests.xml), [sanitized runtime](E:/VideCode/vc_trade/.tmp/fvg-basket-fixes-codex-review/runtime-sanitized.json), [reviewed source manifest](E:/VideCode/vc_trade/.tmp/fvg-basket-fixes-codex-review/review-source-manifest.json).

The fake probes used new isolated SQLite paths. Do not rerun their persistent paths as regression tests without fresh isolation. No real MT5 module was initialized or real trading action sent by these probes.

## Next step

Prepare one focused follow-up for the two residual failures plus the user's clarified fresh-consent policy. Keep entries 1/50/80, wick SL+2 ticks, per-entry 1:2 targets, the $10 shared risk and Telegram format/preference. Keep auto OFF; no automatic rearming, no account switch, no actual broker test orders/checks/removals, no external test message. A follow-up draft is not an approved implementation task and must not be published until separately authorized under the established workflow.
