# Claude report: read the execution clock after the final account lookup

Task ID: 20261007-192600-fvg-post-account-clock
Source prompt: `prompt/20261007-192600-fvg-post-account-clock.md`
Inputs read:
- `report/20261007-165801-fvg-send-boundary-account-guards-codex-review.md`
- my matching report for 20261007-165801
Date: 2026-10-07

## 1. Outcome

**Fixed.** The per-call freshness check now samples the clock **after** the final, potentially blocking `account_info()` lookup, immediately before the pending API call. Nothing else changed: no strategy, risk, policy, consent, default or Telegram changes.

| Codex probe | Reviewed build | This build |
|---|---|---|
| 45 s account lookup before leg 1 | 1 request sent at confirmation age 45 s; legs `pending, not_sent, not_sent`; `partial` | **0** requests; all legs `not_sent`; `rejected` (reason: confirmation 46 s old) |
| 45 s account lookup before leg 2 | requests at ages 0 s and 45 s; legs `pending, pending, not_sent` | **exactly 1** timely request; legs `pending, not_sent, not_sent`; `partial`; a repeat submit resends nothing |

**Runtime** (read-only check at 2026-10-07T12:55:24Z, after the normal launcher restart, PID 44648 → 20548, which loaded this fix):

| Item | State |
|---|---|
| Account | MetaQuotes-Demo, **demo**, XAUUSD |
| Strategy | FVG RR2 `FVG-Trend-M15-M5-v1-RR2@8a49bace` |
| Data | fresh quotes (spread 0.33); M15 ready (59/50); scanner without error |
| Automatic execution | **OFF** ("turned OFF by you") |
| Demo default | true |
| Risk | 10 USD |
| Telegram | **ON** |
| Baskets | **0** |
| Setups | **1 pending live SELL setup**: zone 4089.01–4119.18, detected at the 12:45Z M15 close, waiting for its first M5 retest, expires 14:45Z. It is strategy-generated, not artificial. With execution OFF it can lead to an alert-only basket and Telegram plan message, but **no orders**. |

**Execution state history** (from the app event log):
- Armed at 12:14:58Z and 12:26:32Z, through the normal control by the user.
- Disarmed at 12:24:35Z (Codex) and 12:48:13Z, before this task was published at 12:48:32Z.
- During this task it was already OFF at the first check (12:52:35Z). I did not change it, did not clear any override file, and did not activate anything.

No artificial broker preflight, order or removal; no injected signal; no test Telegram message; no account switch; no MT5 initialize or login from this task; no commit or push; `tools/mt5_test_order.py` was not executed.

## 2. Change: `app/fvg_execution.py` only

- `submit()` now passes the clock **function** (`clock_now`) into `_call_blocker(...)` instead of a timestamp captured before the call.
- `_call_blocker(mt5, payload, eligibility, clock, expires)`:
  1. re-reads `account_info()` and checks the immutable original server+login, as before;
  2. **then** calls `clock()` and evaluates `_ineligible()`: confirmation age ≤ 30 s (equality allowed), not in the future, setup not expired, pending lifetime not passed.

  The order is unchanged otherwise: durable "sending" save → account check → fresh clock sample and eligibility → `order_send`.
- Unchanged behaviour:
  - a known-uncalled leg (and every later leg) is `not_sent`;
  - a first-call refusal gives `rejected`; earlier accepted legs give `partial`, retained and reconciled;
  - crash or unknown outcomes are reconciled; idempotent, never resent;
  - all original-account cancellation and evidence guards from task 165801 are unchanged.

## 3. Tests: `tests/test_fvg_review_fixes.py`, 4 new

They use deterministic fakes and fresh fixtures. A fake `account_info()` advances an injected clock exactly at the per-call lookup of the target leg, after that leg's durable "sending" save. No sleeps, and Codex's SQLite paths are not reused.

| Test | Covers |
|---|---|
| `test_p1_slow_final_lookup_before_leg_1_sends_nothing` | 0 calls; all `not_sent`; `rejected` |
| `test_p2_slow_final_lookup_before_leg_2_keeps_only_the_timely_call` | exactly 1 call; legs `pending, not_sent, not_sent`; `partial`; no resend on repeat |
| `test_p3_…[setup]`, `test_p3_…[pending]` | a 25 s lookup crosses the setup deadline or the pending lifetime while the confirmation age stays ≤ 30 s: refused, 0 calls |

## 4. Validation actually performed

- **Focused:** `tests/test_fvg_review_fixes.py` → 47 passed, including the 4 new tests and the existing 30 s equality, timely three-order, account-switch, cancellation-recovery, demo-default and explicit-OFF regressions.
- **Full backend**, in a fresh basetemp removed afterwards: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-20261007-192600-fvg-post-account-clock` → **314 passed**, 0 failures, errors or skips.
- **Failing against the reviewed code.** I rebuilt it in a temporary git worktree under `.tmp/` (removed afterwards): commit `25c3314` plus the task-165801 patch script. All **31/31** `app/` files match `.tmp/fvg-boundary-codex-review/run-20261007-121919/manifest-before.json` (line endings normalised). Running the 4 new tests there: **all 4 fail**.
- No dashboard assets changed, so no frontend run or build was needed.

## 5. Not performed

- No live broker calls; real terminal behaviour is covered by fakes only.
- No activation: that is Codex's already-authorized step after its independent verification.

## 6. Practical limits

The guards run immediately around every pending call, removal and evidence adoption, and the clock is read after the last blocking lookup. Two residual windows remain that no application code can close:
- The few instructions between the final clock and account check and the broker's own handling of `order_send`.
- An account switch made externally in the terminal in that same window.

The immutable journal identity and the per-call checks keep every *later* call and all evidence on the original account.

## 7. Permission rejections

None.
