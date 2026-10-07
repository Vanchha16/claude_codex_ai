# Claude code review: full codebase (findings for Codex)

Document type: INFORMATIONAL REVIEW sent at the user's direct request. The user first asked "review code at all and report me back", then "report to codex". This is not a reply to an approved task. **No code was changed.**
Author: Claude (implementer)
Date: 2026-10-07T08:19Z

## Live state at review time

| Item | State |
|---|---|
| Active strategy | FVG rr2, on MetaQuotes-Demo (demo), XAUUSD |
| Time base | +3 h, `config/mt5_time.json` |
| Automatic execution | **OFF** (no opt-in file) |
| Telegram | OFF |

Nothing is currently at risk. Findings 1 and 2 should be resolved before the user arms automatic execution.

## Scope and method

- **Read in full:** `app/fvg.py`, `app/fvg_orders.py`, `app/fvg_execution.py`, `app/fvg_live.py`, `app/scanner.py`, `app/data/mt5.py`, `app/mt5_time.py`, the security and FVG paths in `app/web.py`, `app/delivery.py`, `app/launcher.py` (stop path), and the `_step_basket` fill logic in `app/fvg_replay.py`.
- **Lighter coverage:** CRT `engine.py`/`strategy.py`, FastSweep live/replay, `outcomes.py` and the frontend were only skimmed for safety issues. In the frontend I checked HTML sinks: there is no `innerHTML`, `insertAdjacentHTML`, `document.write` or `eval`.
- **Evidence runs** (read-only, local computation only): a narrow-zone geometry calculation, and a placement check over the saved replay baseline. No broker requests, no messages, no restarts.

## Findings, most severe first

### 1. Medium-high: narrow zones produce legs that stop out at the instant they fill

Locations: `app/fvg.py:272` (`basket_levels`), `app/fvg.py:165` (gap minimum), `app/fvg_execution.py:208` (`_check_distances`).

**Mechanism.**
- The common SL is only 2 ticks beyond the far edge, so leg n's stop distance is (1 − depth) · width + 0.02.
- A BUY limit fills on Ask = entry while Bid = entry − spread. If the stop distance is ≤ spread, Bid is already at or through the SL at fill, so the leg loses its full ~$3.33 share immediately. SELL is symmetric (fill on Bid, stop on Ask).
- `_check_distances` enforces only the broker's `trade_stops_level` (often 0), not the spread.
- Qualification allows zones down to max(2 ticks, 0.10 · ATR14), roughly 0.3–0.6 on gold M15.

**Evidence.** The spread is 0.35, as observed on MetaQuotes-Demo in `/api/state`:

| Zone width | 80 % leg stop distance | 50 % leg stop distance |
|---|---|---|
| 0.50 | 0.12, instant stop | 0.27, instant stop |
| 0.80 | 0.18, instant stop | 0.42 |
| 1.20 | 0.26, instant stop | 0.62 |
| 1.60 | 0.34, instant stop | 0.82 |
| 2.00 | 0.42 | 1.02 |

The cached replay contained no zone narrower than 2.37 (16 baskets), so the reported replay results do not reflect this. It is reachable live.

**Suggested direction (a Codex/user decision):** before submission, reject any leg, or the whole basket, whose |entry − SL| ≤ current spread + margin. A minimum zone width relative to the spread would also work. The replay should apply the same rule so live and replay stay aligned.

### 2. Medium: far-edge cancellation of live pending orders stops while paused, and resume skips it

Locations: `app/scanner.py:241` (`if self.paused: return`) and `:243` (`if not fresh: return`), both before `process_bar`, which is where `FvgLiveEngine._manage_open_baskets` runs; and `app/scanner.py:100` (`resume()` → `_set_watermark_to_latest()`).

**Mechanism.**
- While paused, no M5 bars are processed, so a close beyond the far edge never cancels that basket's remaining broker limits.
- On resume, `last_m5_close` jumps to the latest bar, so the paused period is **never** evaluated for open baskets. The limits stay live until fill, SL/TP or the 2 h expiry.
- During stale-quote periods the cancel is only delayed: catch-up happens once quotes are fresh again.
- Broker reconciliation does still run while paused (`app/scanner.py`, before the paused check).

**Suggested direction:** keep running `_manage_open_baskets` over newly closed bars even when paused or stale (it affects only already-submitted baskets). Process the skipped bars for open baskets before the resume skip-ahead. New setups and confirmations stay blocked as today.

### 3. Medium-low: an exception after the journal is created is mislabelled as preflight_rejected

Locations: `app/fvg_live.py:237–239` (catch-all around `executor.submit`) and `app/fvg_execution.py:279–306` (`journal.save` calls after `create`).

**Mechanism.**
- If a `journal.save` (SQLite error) or any other exception occurs after `journal.create` and after one or more `order_send` calls, the engine records `{"state": "preflight_rejected"}`.
- That state is not in `OPEN_EXEC_STATES`, so the basket is never reconciled or managed: no far-edge cancel, and the dashboard says rejected while broker orders exist.
- The symbol-exposure check prevents duplicate baskets, and the orders keep their broker SL/TP/expiry, so the damage is bounded.

**Suggested direction:** in the except branch, if `journal.get(pid)` exists, adopt it as `needs_reconciliation`, the same way `_recover_planned` does.

### 4. Low-medium: an account switch with open baskets causes an error every scan and blocks the basket indefinitely

Locations: `app/fvg_live.py:283`, and `app/fvg_execution.py:325` (`cannot reconcile on another account`).

**Mechanism.** After the terminal switches accounts (the feed now reconnects correctly with a new session), each scan (every 5 s) logs an error event per open basket. The basket stays "open" forever, so `basket_already_open` blocks new baskets on the new account. This is fail-safe, but it bloats the event log and is confusing.

**Suggested direction:** mark the basket `other_account` once, log it once, and exclude it from capacity until the original account returns.

### 5. Low (policy check): rejected and alert-only baskets consume the cap and the cooldown

Location: `app/fvg_live.py:205–207`.

Any accepted basket counts toward the 4-per-Bangkok-day cap and starts the 30-minute cooldown, even when it was `preflight_rejected` (for example, spread too wide) and nothing traded. This matches the replay, where every basket is counted. Confirm that this is intended.

### 6. Low: the second pre-send context check uses the scan-start `now`

Location: `app/fvg_execution.py:270`.

The refreshed tick is aged against the `now` captured at scan start, with a −5 s future tolerance. A slow scan or slow preflight (several `order_check`/margin calls) could make a genuinely fresh tick look about 5 s in the future and reject the whole basket. **Suggested direction:** use `datetime.now(UTC)` for the refreshed check.

### 7. Low: when price is already beyond a leg at placement, live and replay differ

**Mechanism.** Live `_check_distances` rejects the **whole** basket if any limit is already on the wrong side of the market at confirmation. This can happen when the retest bar sits fully inside the zone and the confirmation close stays inside it too. The replay places all three legs regardless and treats them as fillable.

**Evidence:** in the saved baseline, 0 of 16 baskets had any leg on the wrong side of the market at placement (checked against confirmation close ± the 0.20 spread). The difference is real but rare.

### 8. Informational

- **DST:** MetaQuotes-Demo is expected to move from +3 to +2 around 2026-10-25. The app will fail closed, with the quote note "~1 h behind", until `config/mt5_time.json` is re-verified and updated.
- **Observed spread:** the demo spread is 0.35, close to the replay's cost-sensitivity case (0.40, −4.41R conservative) rather than the baseline (0.20).
- **Telegram content:** the FVG alert is queued before submission and contains only Entry/TP/SL/RR. It does not say whether orders were actually placed or rejected. This is per spec, but it could mislead once execution is armed.

## Verified as sound

- **Execution isolation:**
  - `order_send`/`order_check` exist only in `app/fvg_execution.py`; the default policy is OFF.
  - The opt-in is bound to source, symbol, an account hash and strategy version.
  - The journal entry is written before each send, an unknown result is never resent, and the remaining legs are marked not_sent.
  - Cancellation is limited to owned orders; there is one shared feed lock.
  - `Workstation.stop()` closes the databases only after the scan releases the feed lock, so no in-flight submission can hit a closed journal.
- **Sizing:** lots are floored to the step, a leg below the minimum lot rejects the whole plan, and the USC conversion is explicit. Spread does not increase the planned loss amount; it only moves the effective trigger, which is finding 1.
- **Web:** loopback Host allow-list (blocks DNS rebinding), Origin check, constant-time session-token compare on every non-GET, no CORS, and the arming endpoint needs `confirm: true`.
- **Telegram:** ambiguous results are never resent, the token is redacted, and the opt-in is bound.
- **Watermark/restart:** historical confirmations cannot alert or submit. Planned/journal crash recovery works without resubmission. A server or account change starts a new session.
- **Launcher:** the force-kill only targets a PID whose health check identifies this app.

## Status

No code was changed. The user was offered fixes for 1, 2, 3 and 6, either directly or through a Codex task. Claude is waiting for a separately approved prompt before implementing anything.
