# Claude report: FVG send-boundary account and freshness guards

Task ID: 20261007-165801-fvg-send-boundary-account-guards
Source prompt: `prompt/20261007-165801-fvg-send-boundary-account-guards.md`
Inputs read:
- `report/20261007-164056-fvg-demo-default-clock-cancel-recovery-report.md`
- `report/20261007-164056-fvg-demo-default-clock-cancel-recovery-codex-review.md`
- `.tmp/fvg-default-clock-cancel-codex-review/verified-reported-build-20261007-0955/inflight-probe-results.json`
Date: 2026-10-07

## 1. Outcome

All three reviewed call-boundary failures are fixed in `app/fvg_execution.py` only. No strategy, risk or policy change was made.

**Before and after:**

| Codex probe | Reviewed build (`25c3314`) | This build |
|---|---|---|
| Server switch after the first accepted pending call | 3 requests: `[Test-Server, Other-Server, Other-Server]`; state `submitted` | Exactly **1** call, on the original account. Legs `pending, not_sent, not_sent`; state `partial`; original identity kept; a repeat submit sends nothing. |
| Pre-send journal write advances the clock 45 s | 1 request sent with a 45 s-old confirmation | **0** requests; all legs `not_sent` despite the earlier "sending" marker; state `rejected` |
| Server switch after the first removal (colliding foreign tickets) | removed `[101, 102, 103]`, including 2 foreign manual orders; `cancel_state: complete` | removes **only 101** on the original server; foreign orders untouched; `cancel_state: unknown`. When the original account returns, removes 102 and 103 only, never repeats 101, then `complete`. |

**Runtime:** The app was **not running** when this task started (no response at 11:32Z). The last log entry was the 09:49Z start (PID 22764), which probably ended with the previous session or host. I started it with the normal launcher `restart` (PID 29056).

Read-only check at 2026-10-07T12:06:40Z:

| Item | State |
|---|---|
| Account | MetaQuotes-Demo, **demo**, XAUUSD |
| Strategy | FVG RR2 `FVG-Trend-M15-M5-v1-RR2@8a49bace` |
| Feed / quotes | OK; fresh; spread 0.27; time base +3 h |
| Scanner | no error |
| Warm-up | **56/50, ready**; state "waiting for a qualified FVG" |
| Automatic execution | **OFF** ("turned OFF by you"; the override marker was kept) |
| `default_on_for_demo_accounts` | true |
| Risk | 10 USD |
| Telegram | **ON** |
| Baskets / setups | 0 / 0, no active or unresolved exposure |
| Server log | no errors since start |

No artificial broker preflight, order or removal; no injected signal; no Telegram message; no account switch; no MT5 initialize or login from this task; no commit or push; `tools/mt5_test_order.py` was not executed. **Automatic execution stays OFF for Codex's verification and its already-authorized final DEMO activation.**

## 2. Changes (`app/fvg_execution.py`)

### A + B. One per-call guard after the last blocking operation

In `submit()`, each leg now runs this sequence:

1. Mark the leg `sending` and save the journal durably. This blocking write is still before the API call, so a crash still leaves `sending`, which becomes `unknown` on recovery.
2. **Then** `_call_blocker()`, directly before `order_send`:
   - re-reads `account_info()` and requires the **immutable original identity**: `account_id` from the journal, plus the policy's login **and** server;
   - re-checks `_ineligible()`: confirmation age ≤ 30 s (equality allowed), not in the future, setup not expired, and pending lifetime not passed.
3. If blocked, the call is known not to have happened. This leg and all later legs are recorded `not_sent`:
   - with no earlier call, the state is `rejected`;
   - with an earlier accepted leg, the state is `partial`. It stays open and reconciled on the original account, and is never resumed or resent.

The whole-symbol no-exposure check is **not** rerun per leg, because this basket's own accepted orders are expected exposure. A guard stop is a normal returned state, kept distinct from a broker call with an uncertain outcome (`unknown` / `needs_reconciliation`).

### C. Original-account-only removal and evidence adoption

**`cancel_remaining()`:** for **every** removal it:
1. checks the original identity;
2. re-reads the current pending orders, never trusting the batch-old snapshot;
3. checks identity again after the read;
4. checks identity once more immediately before `order_send(TRADE_ACTION_REMOVE)`.

Original-account progress is saved after each call. If the identity changes, it saves `cancel_state: unknown` and raises `OtherAccountError` before any foreign ticket is touched. The engine marks the basket `other_account` (logged once) and keeps both the durable invalidation and `cancel_complete: false`. Bounded recovery resumes when the original account returns: the account flag clears on the next successful reconcile, and the 30 s retry continues. The final completion read is also identity-verified before and after, so a foreign empty list can never mark the cancellation complete.

**`_refresh()`** (used by `reconcile` and cancellation) checks identity **before and after** collecting orders, positions, history and deals. A snapshot that mixes accounts is rejected with `OtherAccountError` before any journal mutation.

Positions and their SL/TP are never closed or modified. Fill-race handling (re-reading the evidence after a removal) is unchanged.

**Practical limit:** an application-level lock cannot stop an external terminal account switch. The checks are made immediately around every pending call, every removal and every evidence adoption. A switch inside the few microseconds between the last check and the broker call remains theoretically possible. The journal and per-call identity still keep later calls and evidence on the original account.

## 3. Tests: `tests/test_fvg_review_fixes.py`, 9 new

They use isolated fake brokers and frozen or injectable clocks: no real sleeps, no Codex SQLite paths. `TwoAccountBroker` keeps separate pending books per server+login.

| Test | Covers |
|---|---|
| `test_r1_r2_…[server, login]` | switch after the first accepted pending call: exactly 1 call on the original account; legs `pending, not_sent, not_sent`; original identity kept; no resend on repeat |
| `test_r3_…` | the durable pre-send write advances the clock 45 s: 0 calls, all legs `not_sent` |
| `test_r3b_…` | the same delay before leg 2: leg 1 kept `pending`, legs 2–3 `not_sent`, `partial` |
| `test_r4_…[setup, pending]` | setup deadline or pending lifetime crossed inside the write (age still ≤ 30 s): 0 calls, without widening eligibility |
| `test_r5_…` | switch after the first removal, with colliding foreign manual tickets: no foreign removal or adoption, cancellation unresolved; return removes only the verified original remainders, never repeating 101 |
| `test_r6_…` | switch during query collection: reconcile adopts nothing; the final completion read on another account never yields `complete` |

## 4. Validation actually performed

- **Full backend**, in a fresh directory removed afterwards: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-20261007-165801-fvg-send-boundary-account-guards` → **310 passed**, 0 failures, errors or skips. This keeps the existing 30 s equality, timely three-order basket, partial and unknown submission, cancel timeout/retry, partial fill, explicit OFF and demo-default tests passing.
- **Focused:** the 9 new regressions pass.
- **Failing against the reviewed code.** I ran the new tests in a temporary git worktree of commit `25c3314` under `.tmp/`, removed afterwards. That commit matches Codex's `review-source-manifest-before.json` on **50 of 52 files: every app and config file**. Only two *test* files differed, and those were replaced by the new tests anyway. Result: **all 9 new regressions fail** there.
- The full suite ran before the patch was applied too (302 passed with the guard patch, then 310 with the new tests).
- No dashboard assets changed, so no frontend run or build was needed.

## 5. Not performed

- No live broker calls of any kind; real-terminal switching behaviour is covered by fakes only.
- No final activation (Codex's authorized step).
- No Ruff or type checker (neither is installed).

## 6. Preserved

- DEMO default ON; explicit user OFF has the highest priority; REAL and CONTEST need exact consent; an unknown account type fails closed.
- Server+login identity; idempotency; unknown-outcome reconciliation.
- Strategy (M15 qualification, 50-bar warm-up, M5 retest then distinct continuation, 1/50/80 %, wick far-edge SL + 2 ticks, per-entry 1:2 TP).
- Floored lots sharing **10 USD**.
- 30 s confirmation maximum with equality allowed; spread + 1 tick; correct-side limits; cooldown, daily cap and 2 h pending lifetime.
- Telegram preference.
- Uncommitted work (the code change and new tests) is left uncommitted as instructed. Prompt and report history are untouched.

## 7. Permission rejections

None.
