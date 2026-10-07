# Add emojis to the compact Telegram signal design

Task ID: 20261005-113521-telegram-signal-emoji-design
Delivery status: DRAFT — DO NOT EXECUTE
User authorization: pending
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261005-113521-telegram-signal-emoji-design.md`
Report path: `report/20261005-113521-telegram-signal-emoji-design-report.md`

## Goal and context

User instruction: "tell claude to design the signal send to telegram, add emoji". Add a clear emoji to each of the existing four fields while keeping the previously requested Entry, TP, SL, RR only message. The new instruction supersedes the prior prohibition on emoji, but does not ask for other fields or headers.

Use this clean four-line design, without blank lines or extra text:

📍 Entry: <entry price>
🎯 TP: <take-profit price>
🛑 SL: <stop-loss price>
⚖️ RR: <reward/risk>

Maintain actual signal values, symbol-digit price precision and two-decimal RR. Keep plain UTF-8 text (no Markdown/HTML parse-mode dependency). No header, symbol, side, IDs, timestamps, explanatory paragraphs or footer. Each field remains clearly labelled; the emoji complements its label.

## Scope and implementation

Claude implements; Codex plans and reviews. Read instructions and write a progress receipt to report/20261005-113521-telegram-signal-emoji-design-progress.md.

- app/delivery.py: update only the shared format_signal design, preserving all delivery behavior and format_test_message.
- tests/test_delivery.py, tests/test_live_market.py, tests/test_api.py: update exact-format assertions for the emoji design, retain actual outbound mocked payload equality, symbol precision, BUY/SELL and mode coverage, and preview consistency.
- README.md: update the four-line message example.
- Keep frontend, strategy, settings, calculations, retries, outbox history and delivery opt-in unchanged. Do not rewrite or resend old messages.

Run focused backend tests and appropriate checks. No real Telegram test/demo message, synthetic signal, replay or bot API call is authorized by this design request. Existing automatic delivery stays enabled for genuine valid signals.

Apply the changed formatter to the running project via the supported gold.cmd restart if required. Use a controlled restart only after checks; preserve MT5/XAUUSDc, active scanner, persisted Telegram opt-in, history and delivery state, and report the normal startup watermark transition accurately. No arbitrary process kills or competing MT5 sessions. Do not expose tokens or destination/account identifiers.

## Acceptance and validation

- Exactly four emoji-labelled lines in the agreed order, with real values and unchanged precision.
- Local preview, stored new outbox body and mocked Telegram payload agree.
- No unrelated message content or parse-mode change.
- Focused tests pass; existing retry, deduplication and expiry semantics remain intact.
- Running backend loads the updated formatter; feed, scanner and Telegram state remain healthy.

Report actual commands/results, changed files, a clearly identified local fictional example (not sent), sanitized before/after runtime checks, and any unavailable validation. Keep all work and temporary/cache paths inside this project root, including pytest --basetemp. Use a unique project-local test temp path and verify it before any cleanup. No global credential access.

## Reply and stopping condition

Publish the complete final report atomically through a project-local temporary file to the exact report path, with matching task ID/source, outcome, actual checks and remaining issues. Write material questions/blockers and stop dependent work if needed. After reporting, stop and await another separately approved task.
