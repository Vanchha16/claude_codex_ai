# Claude report: harden the three-entry FVG basket engine

Task ID: 20261007-161242-fvg-basket-review-fixes
Source prompt: `prompt/20261007-161242-fvg-basket-review-fixes.md`

Inputs read in full:
- `report/20261007-151829-full-code-review-codex.md`
- `report/20261007-151949-full-code-review-findings.md`
- `report/20261007-152543-claude-full-code-review-codex-response.md`
- `prompt/AGENT_TO_AGENT.md` (roles)

Date: 2026-10-07

## 1. Outcome

All eight confirmed issues are fixed and covered by regression tests. The trading rules are unchanged: 1/50/80 % entries, the wick-based common SL 2 ticks beyond the far edge, each leg's own 1:2 TP, a fixed 10 USD combined budget in equal thirds, and the same capacity rules.

**Runtime after the approved restart**, checked at 2026-10-07T09:26:14Z:

| Item | State |
|---|---|
| Strategy | FVG RR2 (`FVG-Trend-M15-M5-v1-RR2@8a49bace`) |
| Account | MetaQuotes-Demo, demo, XAUUSD |
| Quotes | fresh; time base +3 h from `config/mt5_time.json` |
| Warm-up | 45/50 (not ready) |
| Risk | 10 USD |
| Telegram | ON (preserved) |
| Automatic execution | **OFF**; fresh, explicit server-bound arming is needed |
| Baskets / setups | 0 / 0 |
| Scanner / server log | no errors since start |

**Zero real broker orders, `order_check` calls or cancellations, and zero Telegram messages** were made by this task. No MT5 terminal settings or account were changed.

Correction acknowledged: the "Live state" line in my earlier informational review (08:19Z) was wrong. Automatic execution had been armed at 07:52Z, and I had not re-checked. Codex's 08:21Z observation was the accurate one.

## 2. Runtime boundary actions

1. **09:15:19Z, read-only check before any change.** MetaQuotes-Demo, demo, XAUUSD, FVG `…@c6b66f7d`; automatic execution **ON** (armed by the user); Telegram ON; risk 10 USD; warm-up 45/50; **0 baskets, 0 setups**, so no active FVG exposure.
2. **Disarmed** through the normal authenticated local control (`POST /api/fvg/execution {"enabled": false}`). The session token was used in memory only and never printed. The result was OFF ("turned OFF by you").
3. Implemented the fixes and ran the focused and full checks.
4. **Restarted** with `.venv/Scripts/python.exe -m app.launcher restart` (PID 32772 → 40384), then re-checked the runtime (section 1).

Nothing was re-armed.

## 3. Fixes and regression coverage per finding

New test file: `tests/test_fvg_review_fixes.py` (21 tests). Other new or updated tests are named per finding.

**Proof that the regressions catch the old behaviour.** I ran `tests/test_fvg_review_fixes.py` against the pre-task code: git commit `8aa297b`, the repo the user created at about 08:40Z, checked out as a temporary worktree under `.tmp/` and removed afterwards. Two name shims stood in for APIs that did not exist then.
- **17 of 21 failed** on the old code.
- 4 passed, as expected:
  - three boundary/control cases: the 30 s confirmation is accepted, a genuine preflight failure stays rejected, and a tick exactly at the deadline counts;
  - the far-edge breach-then-return case, because that commit already contained the user-directed pause fix described in finding 7.

### Finding 1: consent and ownership bound to server + login (high)

**Files:** `app/fvg_execution.py`, `app/web.py`, `app/fvg_live.py`, `app/scanner.py`.

- **Canonical identity.** `account_id(account)` = `"srv1-" + sha256("mt5-account:{server}|{login}")[:16]`. The login is never stored or shown. The legacy login-only `account_fp` is kept only so legacy data can be recognised; it is never accepted.
- **Consent.** The opt-in binding (`Workstation._fvg_binding`) uses `account_id`. A legacy login-only opt-in therefore never matches; it fails closed and is not upgraded.
- **Policy.** `ExecutionPolicy` has a new required field, `account_server`. `_context` rejects a different login **or** server against the originally bound pair, not only against the feed's current time-base server.
- **Journal.** It records `account_id` and `account_server` before any send. `reconcile` and `cancel_remaining` check the original identity:
  - another account raises `OtherAccountError`;
  - a legacy journal without server identity raises `UnverifiableAccountError`. It is kept, never deleted or adopted, and shown as "legacy journal without server identity: ownership unverifiable; needs manual review".
- **Capacity.** Capacity is scoped to the connected account: new `account_fn`, where the workstation supplies the current `account_id`, and baskets record `account_id`. Baskets of other accounts stay tracked but do not block the current account. They are reconciled again when their account returns, without resubmission. Repeated unavailable-account and error conditions are logged **once**, not every scan.

**Tests:**
- same login on another server: different identity, submission refused, 0 requests
- server switch: reconcile and cancel refused, 0 removals
- a legacy opt-in never matches
- a legacy journal stays tracked and unresolved, logged once
- capacity scoped by account
- existing opt-in tests updated to the server-bound identity

### Finding 2: stale confirmations rejected at the decision boundary (high)

**Files:** `app/fvg.py` (new `max_confirmation_age_seconds = 30`), `app/fvg_live.py`.

`_on_confirmed` runs these checks after the session watermark and **before** any capacity check, alert, reservation or broker call:

| Condition | Rejection reason |
|---|---|
| decision time ≥ setup expiry | `setup_expired_at_decision` |
| confirmation in the future | `confirmation_in_future` |
| confirmation older than 30 s | `confirmation_too_old` |

The setup is consumed as `rejected` and is never re-emitted. The final pre-send quote checks use the real clock (`clock=` in `web.py`, introduced earlier today on the user's direct request) with feed/executor time-base agreement.

**Tests:**
- a backlog processed 3 h late with a fresh quote: no alert, no basket, no request; re-driving does not re-emit
- age boundary: 30 s accepted, 31 s rejected, −2 s rejected

### Finding 3: post-send exceptions recovered (high)

**File:** `app/fvg_live.py` (`_classify_submit_error`).

| Situation | Result |
|---|---|
| No journal row (it is written before any send) | `preflight_rejected` |
| Journal row exists | the payload is adopted as `needs_reconciliation`: open, reconciled, never resent |
| Journal unreadable | `needs_reconciliation` with `uncertain: true` and an explicit reason; recovery is retried every scan |

When the journal becomes readable again:
- if the row exists, the plan is reconciled;
- if no row exists, the basket becomes `interrupted_unsubmitted` with "nothing was sent", which follows because the row is written before any send.

`executor_fn` failures are also contained. Crash recovery of `planned` baskets (`_recover_planned`) is unchanged.

**Tests:**
- unreadable journal → uncertain → resolved from storage
- genuine preflight failure stays rejected with no journal row
- existing: a save failure after the first send is adopted (`test_fvg_engine`)

### Finding 4: fills racing a remainder cancellation (medium)

**File:** `app/fvg_execution.py`.

- **Removal is not a final state.** A successful `TRADE_ACTION_REMOVE` now only records `leg["cancel"]`. The leg's state comes from a fresh read of orders, positions, history orders and deals (`_refresh`), never from the stale stored state.
- **Cancelled legs are re-checked.** `cancelled` and `expired` legs are no longer skipped while the basket is open; a late IN deal upgrades them to `filled_open` and onwards.
- **Delayed history.** A removal whose order is not yet in history leaves the leg `pending`, with the cancel recorded.
- **Closing rule.** A basket is `closed` only when:
  1. all legs are terminal;
  2. no position of this plan is open (by magic + `FVG-<plan>-` comment, or by a recorded position id);
  3. that terminal state was seen on reconciles at least 60 s apart.
- Positions and their broker SL/TP are never touched.

**Tests:**
- a partial fill since the last reconcile is kept as `filled_open`, with remainder cancelled and filled volume 0.6; the basket never closes while the position is open
- delayed history keeps the leg open until evidence arrives
- a cancelled leg is re-examined and the basket closes only after settling

The fake broker now moves removed orders to history as CANCELED.

### Finding 5: invalid M5 constituents rejected before aggregation (medium)

**File:** `app/models.py` (`aggregate`).

A higher-timeframe group is skipped if **any** constituent is not M5 or not `is_valid()`. The resulting gap breaks `contiguous_run` and warm-up. This is shared by live, replay, readiness, FastSweep and chart aggregation.

**Tests:**
- an invalid middle constituent voids its M15 group and breaks the run
- a wrong-timeframe constituent is skipped
- Codex's case (candle A with high < open) produces no gap and no basket

### Finding 6: legacy outcome expiry enforced before recovered ticks (medium)

**File:** `app/outcomes.py`.

- **`track_measured`:**
  - stops at the signal's deadline, so a later TP or SL never overrides expiry;
  - settles `expired` **at the deadline** using the last eligible observed exit-side price;
  - keeps tick-gap annotations.
- **`track_live`** (bar and quote estimates): ignores bars opening at or after the deadline and quotes after it, and settles at the deadline. This aligns with tick replay, which already clipped at expiry.
- FVG broker positions are unaffected (a separate lifecycle).

**Tests:**
- a TP at 150 min after a 2 h expiry gives `expired` at 120 min at the 119-min Bid
- a tick exactly at the deadline still counts
- a bar after the deadline is ignored

### Finding 7: far-edge pending maintenance through pause, resume and stale periods (medium)

**Files:** `app/fvg_live.py` (`manage_baskets`), `app/scanner.py`.

Part of this was already implemented earlier today on the user's direct request (in `8aa297b`):
- maintenance runs every scan, including while paused;
- it is idempotent;
- it re-scans all closed bars since placement, so a return inside the zone never erases a breach;
- resume's skip-ahead affects only new-entry eligibility.

This task adds the trusted-context rule. Maintenance runs only when quotes are **fresh**, so after stale or disconnected periods it catches up over all bars since placement once data is trusted again. Broker reconciliation continues regardless.

**Tests:**
- far-edge breach then return inside: the owned remainders are cancelled
- maintenance waits while quotes are stale (0 removals) and applies the skipped breach once fresh
- existing: cancel while paused, not skipped by resume

### Finding 8: spread-inside-stop baskets blocked and replay eligibility aligned (medium)

**Files:** `app/fvg.py`, `app/fvg_live.py`, `app/fvg_execution.py`, `app/fvg_replay.py`.

This **replaces** the 2 × spread rule I added earlier today on the user's request with the approved rule.

- **Stop distance.** Every leg's `|entry − SL| ≥ current spread + 1 tick` (`stop_spread_margin_ticks = 1`; equality passes). Otherwise the **whole basket** is rejected:
  - before any basket, alert or capacity use (live quote, `stop_within_spread`);
  - again on the send-time broker quote (executor backstop).
- **Placement.** Every limit must rest at least 1 tick on the correct side of the market: BUY below the Ask, SELL above the Bid (`limit_on_wrong_side_of_market`). Live enforces this before the basket; the executor's existing distance check enforces it at send time.
- **Replay** applies both rules with its assumed spread (bid = confirmation close, ask = bid + spread).

**Tests:**
- Codex's example (BUY [116.60, 117.80], 80 % entry 116.84, SL 116.58, distance 0.26) is **rejected at spread 0.33**, with no basket, alert or request, and accepted at 0.25 (equality)
- boundary 0.25 passes, 0.26 is rejected
- SELL symmetric
- an eligible wider gap
- executor backstop on a 0.33 send-time spread
- replay at 0.33 rejects it; placement helper for BUY and SELL

### Text corrections

- `app/__init__.py` and the `app/scanner.py` docstrings no longer say the app "never trades".
- The dashboard's MT5 mode-switch confirmation now says CRT/FastSweep never trade and FVG places pending orders only when automatic execution is ON for this server+login.
- README: rule-6 eligibility and the server+login identity are documented.
- Telegram's Entry/TP/SL/RR plan blocks are unchanged and still describe a plan, not proof of placement.

## 4. Replay acceptance (cached history, no tuning)

Command: `.venv/Scripts/python.exe -m app.fvg_replay --bars .tmp/fastsweep/bars-m5-20260806T0700-20261005T0655.json --spread S --slippage L --out .tmp/fvg/161242`

| Spread / slippage | Confirmations | Baskets | `stop_within_spread` | `limit_on_wrong_side_of_market` | Baseline / conservative R |
|---|---|---|---|---|---|
| 0.20 / 0.05 | 16 | 16 | 0 | 0 | +0.624 / −4.547 |
| 0.33 / 0.05 | 16 | 16 | 0 | 0 | +0.624 / −4.204 |
| 0.40 / 0.10 | 16 | 16 | 0 | 0 | +0.581 / −4.408 |

Acceptance is unchanged from the original baseline: the narrowest cached-history 80 % stop distance is 0.49, which is at least 0.41. This is not evidence of profitability.

## 5. Checks actually performed

- **Full backend:** `pytest -p no:cacheprovider --basetemp=.tmp/pytest-161242f-<ts> --junitxml=…` gives **288 tests, 0 failures, 0 errors, 0 skipped** (exit 0). The basetemp was removed afterwards.
- **New regressions:** `tests/test_fvg_review_fixes.py`, 21/21 pass on the new code. Against commit `8aa297b`: 17 fail, 4 pass, as explained in section 3.
- **Frontend:** `npm.cmd test` 36/36 pass; `node --check app/static/app.js` passes. The template was unchanged, so no asset build was needed.
- **Runtime:** read-only `/api/health`, `/api/state` and `/api/fvg` before and after; the disarm call; the launcher restart (section 2).

## 6. Not performed

- The reviewer reproduction scripts were not rerun against their saved SQLite files, per the prompt. Isolated regressions replace them.
- No live broker preflight, submission, cancellation or expiry, and no Telegram message. Live broker acceptance, fills and expiry remain unverified.
- No Ruff or type-checker run; neither is installed.

## 7. Items for Codex and the user

1. **"Default ON for demo accounts" conflicts with this task's consent criterion.**
   - At about 09:10Z, before this task was published at 09:14Z, the user directly asked me to make automatic execution default ON. I added `config/fvg_execution.json` (`default_on_for_demo_accounts: true`):
     - DEMO accounts are ON without a per-account click, unless the user explicitly turned it OFF, which persists in `state_dir/fvg_execution_user_off.json`;
     - real and contest accounts are never ON by default.
   - **It is currently inert:** this task's disarm wrote the OFF marker, so the state is OFF as required.
   - However, once the user turns ON again (which clears the marker), switching to *another demo* account would be ON without new consent. That conflicts with "no account/server switch reuses consent".
   - **Decision needed:** keep the demo default as the user requested, or remove it. I did not remove a feature the user explicitly asked for.
2. **Re-arming** is required for automatic orders (System → FVG automatic execution, on the intended server+login). Legacy opt-ins never match.
3. **Git.** The project is now a git repository: `main`, pushed to the user's GitHub at the user's request. This task's changes are **not committed**. The user also asked for `tools/mt5_test_order.py`, a manual demo-only test-order tool the user runs themselves (outside `app/`). It is also uncommitted, and no agent ran it.
4. **Limits:**
   - A legacy journal stays "unverifiable" until manual review.
   - After a long stale period, far-edge cancellation waits for fresh data; the broker's own 2 h expiry still bounds the remainders.
   - Closing a basket needs about 60 s of settled terminal state.

## 8. Permission rejections

None in this task.
