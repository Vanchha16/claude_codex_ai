# Send a current valid signal to Telegram

Task ID: 20261005-112052-send-current-telegram-signal
Delivery status: APPROVED FOR EXECUTION
User authorization: On 2026-10-05 the user explicitly instructed "ask claude to send signal to telegram". This authorizes dispatch and sending a genuine current valid signal once via the existing configured delivery path.
Project root: E:\VideCode\vc_trade
Source prompt: `prompt/20261005-112052-send-current-telegram-signal.md`
Report path: `report/20261005-112052-send-current-telegram-signal-report.md`

## Goal and context

User instruction: "ask claude to send signal to telegram". The user authorizes delivery of a genuine current confirmed signal to the already-configured Telegram destination. Signal message body must retain the newly implemented Entry, TP, SL, RR only format.

At dispatch, read-only state check shows MT5/XAUUSDc connected with fresh quotes, scanner active, Telegram enabled, and zero signal records. Recheck current state; do not claim a signal has been sent without actual delivery evidence.

## Scope and actions

This is an operational check/send request, not an application redesign or strategy change. Read existing project instructions and write a progress receipt to report/20261005-112052-send-current-telegram-signal-progress.md.

1. Inspect current state, signal records, recent candidates/events and sanitized outbox through existing supported project interfaces.
2. If a genuine confirmed signal is current, valid, eligible for delivery and not already sent/ambiguous, let the existing enabled delivery path send it once. Use its normal validity, opt-in, deduplication, retry and outbox checks. Check for a confirmed sent status and Telegram message ID. Do not bypass the delivery lifecycle by directly calling the bot API or altering SQLite.
3. If there is no valid confirmed signal, check the scanner's current status and give a concise factual reason (if observable) why none is ready. A short observation window up to 60 seconds is sufficient. Leave automatic scanning/delivery active and report that no signal was sent. Do not wait indefinitely for a market setup.
4. Keep the configured destination, Telegram opt-in, MT5 symbol/source, settings, strategy, session watermark, history and existing scanner state. No restart or code edits are required for this request.

Do not invent prices, synthesize a live signal, send a demo/example/connectivity message, replay an expired historical signal, resend a sent message or an UNKNOWN/ambiguous delivery, loosen strategy rules, force-confirm a candidate, run a replay, expose credentials, or edit global state. A separate explicit instruction is needed for a test/demo message.

## Acceptance and validation

- If delivered, report the real signal ID, four-line body, outbox sent status and Telegram message ID, without destination identifiers or credentials.
- If no eligible signal exists, explicitly report no signal sent, the current scanner/feed/Telegram state and any observed waiting condition. That is a valid completed check, not a fabricated successful send.
- No duplicate or unrelated external messages.

## Reply and stopping condition

Claude performs the approved operational request; Codex coordinates and reviews. Write the exact final report with matching task ID/source, actions performed, delivery evidence or no-signal outcome, and blockers. Publish the complete report atomically through a project-local temporary file. Stop after reporting and await another separately approved task. Do not execute drafts or invent a follow-up task.
