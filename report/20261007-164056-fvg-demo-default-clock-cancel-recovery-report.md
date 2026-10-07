# Claude report: demo default ON and the FVG clock and cancel-recovery fixes

Task ID: 20261007-164056-fvg-demo-default-clock-cancel-recovery
Source prompt: `prompt/20261007-164056-fvg-demo-default-clock-cancel-recovery.md`
Inputs read:
- `prompt/20261007-161242-fvg-basket-review-fixes.md` and its Claude report
- `report/20261007-161242-fvg-basket-review-fixes-codex-review.md`
- `.tmp/fvg-basket-fixes-codex-review/reproduce-residuals.py` and `residual-reproduction-results.json`

Date: 2026-10-07

## 1. Outcome

| Item | Result |
|---|---|
| A. Demo default ON | **Kept**, as the user selected. Precedence is now explicit OFF → exact saved consent → verified-DEMO default. Real, contest and unknown accounts fail closed. |
| B. Old confirmations | Decisions use the current clock, and freshness is re-checked at the send boundary. Codex's probe (scan start +1 s, real decision +121 s) now produces **0** baskets, alerts and requests. |
| C. Failed cancellations | Invalidation is recorded durably and cancellation is retried until the broker shows nothing left. Codex's timeout probe now removes the remainders after recovery. |
| Strategy | **Unchanged**: version `FVG-Trend-M15-M5-v1-RR2@8a49bace`; 1/50/80 %; wick SL + 2 ticks; 1:2 TP per entry; floored lots sharing **10 USD**; spread + 1 tick and correct-side placement checks |

**Runtime** (read-only, 2026-10-07T09:49:42Z, after the restart):

| Item | State |
|---|---|
| Account | MetaQuotes-Demo, **demo**, XAUUSD |
| Strategy | FVG RR2, M15/M5 |
| Quotes | fresh (0.3 s), spread 0.36, +3 h time base |
| Scanner | no error |
| Warm-up | **47/50**, not ready |
| Automatic execution | **OFF** ("turned OFF by you"; the temporary marker was kept) |
| `default_on_for_demo_accounts` | true |
| Risk | 10 USD |
| Telegram | **ON** |
| Baskets / setups | 0 / 0 |
| Server log | no errors since start |

**Automatic execution remains OFF pending Codex's verification and the authorized final DEMO activation.** No artificial broker test orders, `order_check` calls, cancellations or Telegram messages. No account switch, commit or push. `tools/mt5_test_order.py` was not executed.

## 2. Changes

### A. Who may trade: `app/web.py` (`_fvg_armed`)

Precedence, evaluated in order:

1. **Explicit user OFF** (`state_dir/fvg_execution_user_off.json`) beats everything, including a stale or inconsistent saved opt-in. It persists across restarts and account switches until a deliberate ON, which `fvg_arm(True)` clears.
2. **Exact saved consent** (source / symbol / strategy version / server+login). This is the only path for REAL and CONTEST accounts.
3. **Demo default.** The account's `trade_mode` must be verified DEMO and `default_on_for_demo_accounts: true`. Then ON for any demo server+login, including after a demo switch.
4. **Everything else is OFF**, with distinct reasons: real-money, contest, or "account type unknown: not treated as demo". An unavailable or unknown type is never treated as demo.

Unchanged and not bypassed by the default:
- the currency, equity, risk, exposure, hedging, quote and broker-permission checks;
- the executor binding (`ExecutionPolicy` login + `account_server`, verified at every context check, so a mid-preflight switch refuses);
- the journal identity;
- cancellation and reconciliation only on the original verified account;
- legacy journals left unresolved.

Status shows `armed_by` ("you" or "default (demo account)") or the OFF reason.

### B. Current decision clock and send-time freshness: `app/fvg_live.py`, `app/fvg_execution.py`

- **Engine (`_on_confirmed`).** It takes the decision time from the live entry callback's current-clock result (`(quote, current)`; the quote timestamp is never used as wall time), or from an injectable `clock`, before capacity, alert or reservation. It applies the 30 s / future / setup-expiry checks with it. `placed_at` and the new pending expiry use that current time.
- **Executor (`submit(..., eligibility={confirm_close, setup_expires, max_age_seconds})`).** It re-checks with its current clock at three points:
  1. before preflight, by raising, so no journal row is written;
  2. after the (possibly slow) preflight, again by raising, with no journal row;
  3. **immediately before every `order_send`**:
     - before leg 1, all legs become `not_sent`, state `rejected`, nothing is sent;
     - between legs, the rest become `not_sent`, state `partial` (open and reconciled), and accepted or unknown legs are kept.

  Pending expiry passing is also checked. Submissions stay idempotent and nothing is resent.

### C. Durable invalidation and verified cancellation recovery: `app/fvg_live.py`, `app/fvg_execution.py`

- **Detection.** A valid closed M5 bar (the `tf == M5` and `is_valid()` checks are new) closing beyond the far edge records `zone_invalidated_at` durably, **separately** from the new `cancel_complete` flag. A later return inside never erases it.
- **`cancel_remaining`** re-reads the broker's current pending orders first. `None` gives `cancel_state: "unknown"`, never "empty". Only owned orders that are verifiably still pending are removed: matched by ticket, or by comment for unknown legs. A removal that actually succeeded is therefore never duplicated. After the attempt it reconciles legs from fresh evidence (fill races keep positions) and re-reads the pending orders to derive the state:

  | `cancel_state` | Meaning |
  |---|---|
  | `complete` | the re-read shows no owned pending order for this plan |
  | `pending` | owned pending orders remain |
  | `unknown` | the re-read failed (`None`) |

- **`_retry_cancel`** runs from both `reconcile()` (every scan with broker access, including while paused, stale or after reconnecting) and `manage_baskets()`:
  - cadence is 30 s per basket;
  - it acts on the original account only: `OtherAccountError` pauses it, and it resumes when that account returns;
  - repeated failures are logged once;
  - it never closes or modifies positions.

### Tests: `tests/test_fvg_review_fixes.py`

The file has 14 new tests, A/B/C sections. Two existing tests were updated:
- `tests/test_fvg_engine.py::test_real_and_contest_accounts_are_never_on_by_default`: contest and unknown accounts now have distinct reasons.
- `tests/test_fvg_review_fixes.py::test_confirmation_age_boundary`: now uses a frozen, deterministic executor clock, so 30 s equality is tested exactly. The executor now re-checks immediately before each send.

New tests:

**A.**
- demo A and demo B are both ON without an exact opt-in
- explicit OFF beats the default **and** a stale matching opt-in, and survives a restart or switch
- real, contest and unknown types are OFF despite the default; exact real consent works only on its own binding
- a mid-preflight server switch refuses submission

**B.**
- Codex's probe (scan +1 s, callback and executor clock +121 s, fresh quotes): 0 baskets, alerts and requests; the setup is consumed as `confirmation_too_old`
- slow `order_check` crossing 30 s: no send and no journal row
- 40 s between sends: leg 1 kept `pending`, legs 2–3 `not_sent`, state `partial`, idempotent with no resend

**C.**
- Codex's probe (timeout → recovery → return inside): all three remainders removed, invalidation kept, no new alert or order
- explicit removal rejection: retried on the 30 s cadence until proven
- `None` order list: unknown, nothing removed, resolved later
- a removal that actually succeeded despite a timeout answer is not repeated
- account switch: cancellation paused, then resumed when the account returns
- a partial fill during a retry keeps the position
- an invalid raw bar never invalidates

## 3. Validation actually performed

- **Full backend:** `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-20261007-164056-fvg-demo-default-clock-cancel-recovery` (fresh directory, removed afterwards) → **302 passed**, 0 failures, 0 errors, 0 skipped.
- **Focused:** `tests/test_fvg_review_fixes.py` and `tests/test_fvg_engine.py` → 73 passed.
- **Failing against the reviewed code.** I rebuilt the exact code Codex reviewed in a temporary git worktree under `.tmp/`, removed afterwards: commit `8aa297b` plus the already-applied patch scripts. **All 31 `app/` files match `.tmp/fvg-basket-fixes-codex-review/review-source-manifest.json`** with line endings normalised. Running the new tests there:
  - **11 fail**: both residual probes (B and C) and every B/C case, plus "explicit OFF beats a stale matching opt-in";
  - 6 pass by design: the age boundaries, the demo default, real/contest exact consent, and the mid-preflight switch refusal, which already existed and are preserved.
- Codex's persistent SQLite paths were **not** reused; all fixtures are isolated `tmp_path` databases.
- `node --check app/static/app.js` passes. No dashboard asset was touched in this task, so no frontend run or build was needed.
- **Runtime:** read-only `/api/state` and `/api/fvg` before (09:43:17Z: same context, auto OFF, 0 baskets) and after the restart. The restart used `.venv/Scripts/python.exe -m app.launcher restart` (PID 40384 → 22764), with the OFF marker confirmed present and auto OFF beforehand.

## 4. Not performed

- No live broker preflight, submission or cancellation; real broker timeout and retry behaviour is covered by fakes only.
- No final activation: that is Codex's authorized step after its independent verification.
- No Ruff or type checker (neither is installed).

## 5. Notes and limitations

- **What Codex's final activation does.** The "Turn ON" action clears the OFF marker and arms the exact current binding. From then on, any **verified demo** account is ON by default until the user turns it OFF. Real and contest accounts still need exact consent.
- **Retry window.** Cancellation retries continue while the basket is open. If a removal stays "unknown" because the order list is unreadable, the basket stays visible with a bounded, once-logged error, and the broker's own 2 h expiry still limits the remainders.
- **Clean decision timing.** The engine's decision time now comes from the scanner's entry callback (`feed.now()`), so `placed_at` and the 2 h pending expiry are measured from the actual decision, not the scan start.
- **Git.** Changes are uncommitted, as required by this task. They sit on top of the user's pushed `main` (`8aa297b`) together with the earlier uncommitted work (161242 and the user's tool).

## 6. Permission rejections

None.
