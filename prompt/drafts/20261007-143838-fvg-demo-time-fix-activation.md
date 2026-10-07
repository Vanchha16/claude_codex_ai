# Correct MT5 time handling and activate FVG scanning on the demo account

Task ID: 20261007-143838-fvg-demo-time-fix-activation
Delivery status: DRAFT - DO NOT EXECUTE
User authorization: pending dispatch approval. The user requested "let active our new strategy" on 2026-10-07. This draft makes the prerequisite time correction and demo strategy activation concrete for review under the selected agent-to-agent workflow. It does not authorize arming automatic orders.
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261007-143838-fvg-demo-time-fix-activation.md`
Report path: `report/20261007-143838-fvg-demo-time-fix-activation-report.md`

## Goal and current context

Activate FVG-Trend-M15-M5-v1 rr2 on the user's currently connected MetaQuotes-Demo XAUUSD account, after fixing the confirmed approximately three-hour timestamp mismatch. Keep automatic execution OFF and Telegram delivery OFF throughout.

Read `report/20261007-142425-mt5-server-time-offset-finding.md` and `report/20261007-142425-mt5-server-time-offset-codex-review.md`, plus the completed FVG build and dashboard reports. The running process still uses the old backend, FastSweep rr2, MT5 mode, MetaQuotes-Demo demo account, XAUUSD. At Codex's read-only check on 2026-10-07T07:36:02Z, quote age was -10799.7 seconds and fresh=false. The previous FVG build passed 233 backend tests; the frontend now passes 36 tests. No FVG opt-in file exists.

The FVG rules remain exactly the confirmed 1/50/80% entries, fixed 10 USD total setup risk with equal nominal thirds, common far-edge stop plus two ticks, individual 1:2 targets, M15 qualification and retest plus later M5 continuation confirmation. This task does not change rules or tune replay results.

## Scope and relevant files

- `app/data/mt5.py`: current `_utc`, `_req`, quote/bar/chart/range conversion and connection/account context.
- `app/fvg_execution.py`: `_context` raw quote freshness, broker history ranges and pending expiry semantics.
- `app/web.py`: pass the connected feed's shared time conversion/context to execution under the same MT5 lock; report actual time correction/status.
- `app/config.py` and a small project-local non-secret time-offset config if needed. Avoid reading, printing or modifying credential-bearing .env files. Keep any offset explicitly tied to the verified server/demo account context, rather than silently applying +3 to every broker.
- `app/scanner.py` only if needed to reset session eligibility on account/time-base changes. Preserve historical databases and cached replays; do not rewrite old timestamps.
- Relevant fake-MT5 tests, README time-handling documentation and minimal dashboard/status text if needed for truthful offset reporting.
- `config/active_strategy.json`: activation through the normal strategy-selection command after prerequisite validation.
- `app/launcher.py` / `gold.cmd`: use the existing launcher for an authorized local restart; do not change launcher behavior.

## Phase 1: verify and correct the time contract

1. Use bounded read-only observations from the existing connected local backend and known UTC to verify advancing tick times and recent M5/chart times. The screenshots and current API confirm a mismatch, but do not prove universal MetaQuotes epoch or DST behavior. Consult current official MQL5 docs. Do not launch a competing MT5 session or change terminal login, clock or account settings. Record only sanitized evidence: no account login, session token or credentials in reports/output.
2. Prefer an explicit verified correction bound to this server/demo context. The current +3-hour value may be used only after confirmation. Standard UTC remains the default for other servers; test manually configured +2 as well. Expose the effective offset and whether its context matches in status. If evidence is insufficient or no fresh advancing quotes are available, stop dependent activation and report precisely what is missing.
3. Do not implement Claude's earlier single-tick `tick_time - now` automatic-offset proposal. It confounds stale data with clock offset and can fabricate freshness. Preserve stale/future guards, reject unknown/inconsistent time semantics and do not auto-correct stale/weekend data to now. A server/DST change must fail closed until a new explicit correction is verified, rather than silently guessed.
4. Make feed and FVG execution use one UTC-normalization contract for quote freshness. Codex's fake-broker reproduction proves that the existing global feed offset alone leaves `MT5FvgExecutor._context` rejecting the raw +3-hour tick: `.tmp/mt5-time-codex-review/feed-executor-offset-reproduction.json`.
5. Check outbound bar/tick/history query times and broker pending-expiry semantics explicitly against documentation and fake broker contracts. Normalize each relevant timestamp exactly once. Do not blindly apply an offset to every API field merely because ticks differ. A two-hour pending lifetime must remain two hours on the supported time contract, and reconciliation must not miss deals because it queries the wrong interval.
6. Keep shared MT5 locking, account binding, durable journals, disabled-policy zero requests, historical/session watermarks, cancellation ownership and all existing constraints. Account/broker or time-base changes must reset eligibility and prevent prior confirmations from submitting or alerting. Historical records and replays stay unchanged.

## Phase 2: activate on this demo account, execution OFF

After the prerequisite correction and meaningful tests pass:

1. Confirm the existing terminal is still MetaQuotes-Demo, demo, XAUUSD. If it is a real/unknown/different account, stop activation and report the changed context. No switching accounts or credential access is authorized.
2. Confirm automatic FVG execution and Telegram delivery are OFF. Do not create an execution opt-in, tick the arming checkbox, call the arm endpoint, run a test order, call real `order_check`/`order_send`, or send a Telegram test/message. Normal MT5 data attachment by the restarting backend is allowed; no separate connection is needed.
3. Preserve the previous active choice in a project-local snapshot. Select `fvg rr2` using `.venv/Scripts/python.exe -m app.active_strategy fvg rr2`, then restart the local dashboard via `.venv/Scripts/python.exe -m app.launcher restart` (the same behavior as `gold.cmd restart`). This local restart is explicitly within the proposed task; keep mode, symbol, account and other preferences unchanged. Keep processes hidden.
4. Verify the new process is the single owner, `/api/health` is healthy, `/api/state.active_strategy.kind` is `fvg`, profile rr2, M15/M5, and `/api/state.fvg.auto_execution` is OFF. Verify corrected advancing quotes are fresh and the newest closed M5 bars correspond to current UTC. Report actual M15 readiness count; warm-up is acceptable and should not be described as ready. Do not wait 12.5 hours merely to activate; do not fabricate a signal to prove readiness.
5. Preserve all existing history and saved replays. If the application cannot start or activation validation fails, use normal supported commands to restore the previous strategy and restart where allowed, and report the incomplete activation. Do not claim success based only on editing the selection file.

## Permission/rejection handling

Claude previously reported that strategy selection was rejected by its permission classifier as "Production Deploy". The user now asks for activation, and a later explicit "send it" will approve this exact task, but tool permission rules still apply. If an activation/restart action is rejected, do not switch to direct config edits or alternate shells to evade that rejection. Report the exact rejected action and stated reason; stop dependent actions. Do not tell the user activation happened when only the implementation is complete.

## Acceptance criteria

- Verified current demo context and reliable UTC quote/bar semantics, not a guessed offset that makes stale ticks fresh.
- Feed and executor agree on normalized timestamps. Standard UTC and explicit +3/+2, stale/future/weekend data and broker/account changes are meaningfully covered with fake modules.
- Correct closed M5 availability, range/history requests and pending-expiry representation for the supported contract; no timestamp double shift.
- FVG rr2 selected AND running in the updated local backend, with truthful M15/M5 readiness and fresh live demo data.
- Automatic execution OFF, Telegram OFF, fixed 10 USD preference unchanged; zero actual orders/preflight requests/messages.
- No credentials exposed, no competing MT5 session, no unrelated settings changes, no rewritten live history or parameter tuning.

## Validation

Run focused feed/time/executor/scanner/API regressions and the full backend suite with a unique project-local `--basetemp` and no pytest cache. Fake brokers/delivery only. Run frontend tests/syntax/build only if those assets are touched. Do not rerun strategy optimization or claim profitability; this task establishes correct operation, not a trading edge.

Use read-only local API checks for final real demo activation status. Report commands and checks actually performed separately from recommended/unavailable checks. Keep artifacts inside the project root. Verify resolved paths remain inside the intended workspace before any recursive deletion/move. Do not print server.json, .env contents or tokens.

## Reply and stopping condition

Codex is planner/reviewer and Claude is implementer. This is a draft, not dispatch authorization. After separate approval and atomic publication, acknowledge in `report/20261007-143838-fvg-demo-time-fix-activation-progress.md`. If material time semantics, permissions or account context are unresolved, publish the questions/blockers at the exact report path and stop dependent work.

Publish the complete final report atomically at `report/20261007-143838-fvg-demo-time-fix-activation-report.md` with task ID/source, verified time evidence, files changed, actual tests, activation/restart result, current account type/server without login, actual readiness, ON/OFF status and permission rejections. Explicitly state zero real orders and messages. Stop after reporting; automatic-order arming is a separate later user decision.
