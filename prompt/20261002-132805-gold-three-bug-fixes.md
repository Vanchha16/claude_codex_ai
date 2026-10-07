# Fix the three confirmed gold signal bugs

Task ID: 20261002-132805-gold-three-bug-fixes
Delivery status: APPROVED FOR EXECUTION
User authorization: Browser-button approval. The user clicked "Send to Claude" in the local task panel for task 20261002-132805-gold-three-bug-fixes at 2026-10-02T06:31:18.251Z, approving the reviewed draft prompt/drafts/20261002-132805-gold-three-bug-fixes.md with SHA-256 2ec580710f4425b085838a3af201401397061fdf63762dacc14a2850390b29c0.
Project root: E:\VideCode\vc_trade
Source prompt: prompt/20261002-132805-gold-three-bug-fixes.md
Report path: `report/20261002-132805-gold-three-bug-fixes-report.md`
Progress path: `report/20261002-132805-gold-three-bug-fixes-progress.md`

## Goal and evidence

Repair the three defects independently reproduced by Codex when reviewing 20261002-111340-gold-signal-v1. The existing 63 tests passed but missed these cases. Retain the agreed CRT plus SMC rules and defaults.

1. Scanner started at 2030-01-07T06:10:05 created a signal and called mocked Telegram for a confirmation already closed at 06:10:00. app/scanner.py checks created_at instead of confirm_close, establishes live_start only without persisted history, and filters delivery after Engine already creates the signal/active position.
2. Tick replay with period end 2026-09-20T03:15:00 reported TP at 03:50:00. app/replay.py resolves ticks immediately from on_signal through a future 24-hour window. Early settlement also releases the active-position overlap guard before the exit occurs.
3. A mocked MT5 CLI observed shutdown followed by ticks_range and failed. app/replay.py closes the feed before replay uses its lazy bound ticks_range callback.

## Scope

Inspect app/scanner.py, app/engine.py, app/replay.py, app/data/mt5.py and related outcome/store/models code; update tests/test_scanner.py, tests/test_replay.py and relevant documentation. Change only what these three repairs require.

Preserve the dashboard, persistent deduplication/history, existing active simulated positions, pause/resume, and no broker order execution. Use mocks for MT5 and Telegram. Do not configure secrets, connect to a real broker, enable external delivery, or send real Telegram messages. Keep all work/cache/temp inside this project. Do not change global tools, permissions, security settings, or unrelated projects.

## Implementation and acceptance

### Startup, restart and reconnect eligibility

Establish a fresh session eligibility watermark on startup, process restart, and recovery after disconnected/stale feed intervals. An old persisted watermark must not authorize missed confirmations. Define boundary equality and reset transitions explicitly; ordinary fresh scans must still permit valid new confirmations.

Warm up historical range/swing context without creating actionable signals, active entries, or outbox jobs from confirmations before the current watermark, even within the 30-second freshness window. Prevent Engine/store side effects, rather than only suppressing Telegram. Preserve existing outcome tracking and persistent deduplication. Genuinely new confirmations after the watermark can create one signal and one mocked alert.

### Chronological tick replay

Advance observations and simulated outcomes with replay time. Never settle an exit before its timestamp or release overlap protection using a future exit. Bound entry and outcome observations to the supplied replay period; filter callback observations outside requested bounds and maintain chronological ordering.

Use actual Bid for BUY exits and Ask for SELL exits, preserving configured cost/slippage semantics, entry freshness and invalidation precedence. Candidate invalidation/entry must not use future information. Keep positions active until observed exit or expiry occurs. Report open_at_end if history ends first. Later ticks must not fabricate an in-period fill, exit or expiry. Missing ticks must not fabricate fills/price hits. Document remaining simulation limitations.

### MT5 lifecycle

Keep the connection alive for all required tick/history reads and replay, or preload bounded observations before closing. Use reliable cleanup (such as finally) on success and failure, including partial initialization where applicable. No lazy callback may read a closed feed. Test this without a real MT5 terminal.

## Validation

Add meaningful regressions covering:

- Startup five seconds after confirmation creates no actionable signal/active entry/outbox/mocked send.
- Restart with persisted history across confirmation and reconnect/recovery within 30 seconds suppress missed confirmations.
- New eligible confirmation still works; repeat scans/restarts deduplicate and preserve existing outcome tracking.
- Replay truncated before a future TP/SL remains open_at_end with no exit beyond period.end; include out-of-period entry ticks and missing ticks.
- Opportunities before the first trade's future exit cannot overlap; opportunities after an observed exit follow normal rules. Cover BUY/SELL exit sides and chronological invalidation where affected.
- Mocked MT5 CLI --use-ticks reads before shutdown; cleanup also happens on tick/replay errors.

Show regressions expose the original failures where practical. Run the full existing suite plus regressions with .venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp <unique directory under .tmp>, plus relevant replay/demo smoke checks. Verify localhost health/state and external delivery off. Restart the local demo only if necessary to run repaired code; report URL and process state. Do not alter the separate task panel unnecessarily.

Keep test databases/replay outputs/caches inside the project. Before recursive delete/move verify the resolved targets remain in the intended project directory and do not follow links outside it. Distinguish actual checks from unavailable real integration checks.

## Reply and stopping condition

Claude implements; Codex reviews. After approval acknowledge this exact task in its progress path. If material requirements/permissions block work, report the blocker at the exact report path and stop dependent work.

Publish a complete final report via project-local temporary file and rename. Include task ID, source prompt, outcome, files changed, each repair, regression evidence, actual validation, local server state, remaining limitations and unavailable real integrations. Stop after reporting; wait for a separately approved next task.