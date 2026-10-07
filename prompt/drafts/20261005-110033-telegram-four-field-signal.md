# Telegram signal message: Entry, TP, SL and RR only

Task ID: 20261005-110033-telegram-four-field-signal
Delivery status: DRAFT — DO NOT EXECUTE
User authorization: pending
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261005-110033-telegram-four-field-signal.md`
Report path: `report/20261005-110033-telegram-four-field-signal-report.md`

## Goal and context

The user explicitly instructed: "tell claude when send signal into telegram send only Entry , tp , sl , RR,". Implement this exact compact message requirement. The Telegram signal body must contain exactly these four labelled lines, in this order:

Entry: <entry price>
TP: <take-profit price>
SL: <stop-loss price>
RR: <reward/risk ratio>

Use actual signal values, symbol-digit price precision and the existing two-decimal RR formatting. No header, symbol, BUY/SELL label, ID, timestamps, strategy/explanation, footer, disclaimer, emoji or other signal-body content. This user instruction replaces older signal-message text requirements, including live/demo headers; it does not change the underlying signal data or dashboard context. Do not invent extra requested fields.

## Scope and relevant files

- app/delivery.py: format_signal and any now-unused signal-header helper.
- tests/test_delivery.py and tests/test_live_market.py: update obsolete message assertions and cover the exact new contract.
- app/web.py preview endpoint uses the shared formatter; keep preview and actual signal text consistent without unrelated API changes.
- Project-local documentation only if it describes the old message contract.

Preserve strategy, calculation of entry/TP/SL/RR, precision policy, validity checks, durable outbox, idempotency/retry behavior, opt-in and credentials, connectivity-test message formatting, UI design/navigation and database history. Do not rewrite or resend existing outbox rows or historical messages.

## Implementation plan

1. Read the prompt and project instructions; write a progress receipt to report/20261005-110033-telegram-four-field-signal-progress.md after checking approval.
2. Replace the shared signal formatter with the exact four-line contract above. Handle BUY/SELL and MT5/demo uniformly for these four fields. Leave connectivity test messages separate and unchanged.
3. Update relevant tests. Assert full string equality and mocked sendMessage payload equality (not just substring presence), precision, RR and preview consistency where suitable. Confirm delivery retries/expiry/deduplication still work.
4. Run focused and appropriate existing backend tests. All Telegram tests use mocks; do not send a real test message or synthesize a live signal to verify formatting.
5. Apply the backend formatter change to the running project. A controlled project-local gold.cmd restart is authorized if required; verify healthy startup and preserve MT5/XAUUSDc, active scanner, persisted Telegram enabled, watermark/history and delivery state. Use supported launcher only; no arbitrary process kills or global changes. Record sanitized before/after state. Avoid credentials or session tokens in outputs. If restart cannot preserve the existing state, report the issue before proceeding with the dependent runtime step.

## Acceptance criteria

- Newly queued signal messages contain exactly Entry, TP, SL and RR lines in that order, with real values and correct precision.
- Local signal preview and mocked outbound signal body agree.
- No additional signal fields or narrative remain in the body.
- Connectivity test messages and delivery semantics remain intact.
- The live application uses the new formatter after any necessary controlled restart and preserves MT5, scanner and Telegram state.
- No validation-triggered external message or replay of historical signals.

## Validation

Run focused formatter/delivery/preview tests, then the existing backend suite if practical. Report actual test commands and results, a clearly identified local example output, files changed, runtime before/after and limitations. Keep all work, caches and temp files in the project root. Do not access global credentials. Do not alter frontend, settings or strategy for this task.

## Reply and stopping condition

Claude implements; Codex plans and reviews. If material requirements are missing, write questions/blockers to the exact final report path and stop dependent work. Publish the complete report atomically through a project-local temporary file. Include matching task ID, source prompt, outcome, files changed, actual validation and remaining issues. After reporting, stop and await another separately approved task.
