# Enable live alerts with minimum risk-to-reward 1:1

Task ID: 20261006-144457-minimum-rr-one-to-one
Delivery status: SUPERSEDED - DO NOT EXECUTE
User authorization: The user requested signals and explicitly accepted risk-to-reward 1:2 or 1:1. Dispatch to Claude is pending the workflow's send-it approval.
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261006-144457-minimum-rr-one-to-one.md`
Report path: `report/20261006-144457-minimum-rr-one-to-one-report.md`

## Goal and context

The user wants the real live system to accept signals with risk 1 to reward at least 1. Interpret the requested 1:1 or 1:2 as risk:reward; the engine field min_reward_risk is reward divided by risk. Set the project operational threshold to 1.0. Signals with reward/risk >= 2.0 also qualify. This is a minimum filter, not a fixed-ratio TP change. Keep TP at candle A's opposite edge and SL beyond B's sweep extreme.

The existing 60-day MT5 OHLC reconstruction (2026-08-06 07:00 UTC to 2026-10-05 06:55 UTC) produced zero signals at 1.5 and two at 1.0. At 1.0, one development signal hit TP and one later signal hit SL. Source: report/20261006-signal-frequency-test-report.md and .tmp/signal-frequency-comparison-20261006.json. This does not promise a current signal or future frequency. RR 0.5 is outside the user's accepted scope and must not be applied.

## Scope and relevant files

- Read prompt/AGENT_TO_AGENT.md and the referenced frequency-test report.
- Change only min_reward_risk in config/strategy.json from 1.5 to 1.0; retain every other configuration value.
- Update the operational rule sentence in README.md to describe reward/risk >= 1.0 in this project's configuration. The built-in fallback StrategyConfig default may remain 1.5; make this distinction clear if relevant. Do not change the engine, target/stop formulas, confirmation logic or generic default unnecessarily.
- Use app/config.py, app/strategy.py, app/engine.py, app/scanner.py and app/launcher.py for understanding and verification.
- Restart the existing project server once using its supported launcher to load the changed configuration. Preserve the selected source, symbol and existing external-delivery opt-in. Do not manually enable delivery if it was disabled, send test messages, or alter credentials.
- No fabricated signals, historical live alert backfill, orders, new dependencies, account changes or direct DB edits. Preserve existing reports and replay artifacts.

## Implementation plan

1. Acknowledge the exact approved task/source in report/20261006-144457-minimum-rr-one-to-one-progress.md. Record a sanitized pre-change API snapshot, strategy configuration and launcher health. Never print the server session token, account identifiers or Telegram secrets.
2. Make the single operational threshold change and the matching documentation edit. Confirm all other configuration values are byte-equivalent in meaning to before. Do not modify the threshold to 2.0: that is stricter and cannot address the zero-signal result under the existing geometry.
3. Run proportionate validation. Existing test coverage for build_entry already exercises RR rejection; do not add a tautological config-value test. Validate the changed JSON using load_strategy(). Validate entry math for an accepted RR between 1.0 and 1.5 and a rejected RR below 1.0 using existing representative setup/quote data or focused tests where needed.
4. Confirm the existing isolated comparison used the same engine and produced two signals at 1.0, versus zero at 1.5. Reuse .tmp/compare_signal_frequency.py if a fresh reconstruction is useful; it uses GET candle reads and a MemoryStore and never mutates live state. Do not replace the dashboard's stored replay with fictional demo results or run a competing MT5 session.
5. Restart with the supported gold.cmd / app.launcher mechanism. Verify GET /api/state exposes min_reward_risk=1.0, a new matching config version, the intended MT5 source and symbol, and a healthy scanner/feed. Report actual Telegram status, but send no manual messages. Preserve pending/history through the application's normal restart behavior; do not manufacture an immediately actionable signal.
6. Publish the complete report atomically and stop.

## Acceptance criteria

- Operational min_reward_risk is 1.0 in config/strategy.json and the running API.
- Other trading/strategy filters and target/stop geometry are unchanged.
- README describes the operative threshold accurately.
- Validation demonstrates that qualifying 1:1 or better ratios are eligible, while below-1.0 ratios remain rejected.
- Current live signal count is honestly reported; zero at the verification moment is permissible because confirmation remains required.
- Existing delivery preference is preserved without manual sends, and no historical signal is sent merely because of this change.

## Validation

Run gold.cmd test if feasible; report the actual result. If tests run with only the built-in defaults, also explicitly verify the configured 1.0 profile through load_strategy()/build_entry. Read live API health/state after restart. Do not claim unchanged tests validate live configuration without checking the API. Include the two historical signal counts and the exploratory OHLC/later-sample limitations from the frequency test. Report checks actually performed separately from unavailable checks. Keep all work and temporary artifacts inside this project.

## Reply and stopping condition

Report the exact task ID and source prompt, changed files, pre/post config versions, tests actually run, restart result, sanitized live health, actual pending/signal counts, delivery enabled status and any remaining issue. Never claim a signal was emitted unless an actual new record exists. Publish the complete report through a project-local temporary file to the exact report path. After reporting, wait for another separately approved task.

Superseded by prompt/20261006-144723-fast-sweep-strategy.md. Do not dispatch this threshold-only draft.
