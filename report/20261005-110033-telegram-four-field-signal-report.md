# Claude report: Telegram signal message with Entry, TP, SL and RR only

Task ID: 20261005-110033-telegram-four-field-signal
Source prompt: `prompt/20261005-110033-telegram-four-field-signal.md`
Status: completed
Reported at: 2026-10-05, about 04:07 UTC

## Outcome

Telegram signal messages now contain exactly four labelled lines, in this order:

```
Entry: <entry price>
TP: <take-profit price>
SL: <stop-loss price>
RR: <reward/risk>
```

- **Precision:** prices use the symbol's digits; RR keeps the existing two-decimal formatting.
- **Uniform format:** the same for BUY and SELL, and for live MT5 and demo.
- **Removed from the body:** the header, symbol, side, ID, timestamps, strategy, explanation, validity text and disclaimer.

What stays the same:
- the formatter is still shared by the outbox and `GET /api/signals/{id}/message`, so the preview and the sent text cannot diverge;
- the connectivity TEST MESSAGE is unchanged;
- signal data and calculations, precision policy, validity checks, the durable outbox and its retry/UNKNOWN/expiry semantics, the opt-in and the credentials are all unchanged;
- existing outbox rows and historical messages were not rewritten or resent.

The running app was restarted through the supported launcher (`gold.cmd restart`) so it loads the new formatter. Live MT5/XAUUSDc, the active scanner and the persisted Telegram opt-in all came back as before.

Local example (rendered with `format_signal` in a local Python process from fictional values; not sent anywhere). It is a SELL on a 3-digit symbol:

```
Entry: 4141.208
TP: 4120.500
SL: 4151.200
RR: 2.07
```

## Files changed

- **`app/delivery.py`:** `format_signal()` now returns exactly the four lines. The unused `signal_header()` (LIVE/DEMO header) was removed. `format_test_message()` and all delivery logic are unchanged.
- **`tests/test_delivery.py`:** the old field-substring test was replaced with:
  - `test_message_is_exactly_entry_tp_sl_rr`: full-string equality;
  - `test_message_uses_symbol_digits`: a 3-digit symbol, checking price precision and RR at 2 decimals.

  `test_success_records_message_id` now also asserts that the mocked `sendMessage` JSON payload's `text` equals the exact four-line body and the stored outbox row text, and that its `chat_id` is right.
- **`tests/test_live_market.py`:** the old live/demo header test was replaced with `test_messages_are_four_fields_for_every_mode_and_side`, which checks exact equality for SELL and BUY in both `mt5` and `demo` mode.
- **`tests/test_api.py`:** the demo end-to-end test now asserts the `/api/signals/{id}/message` preview equals the exact four-line body built from that signal's API values. This is the preview-consistency check.
- **`README.md`:** the Telegram message description now documents the four-line contract and no longer lists the old header and fields.
- **Not touched:** the frontend, settings, strategy, database and history, and `tools/`.

## Validation performed

Tests (all Telegram tests use `httpx.MockTransport`; nothing real was sent):

- **Focused:** `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_delivery.py tests/test_live_market.py tests/test_api.py` gave **48 passed**. This includes the retry-after-429, definite-error, timeout→UNKNOWN never resent, connect-error retry→expiry, expired-not-sent, token-redaction, crash-mid-send and test-message-only-on-request tests, all unchanged and passing.
- **Full suite:** `.venv/Scripts/python.exe -m pytest -p no:cacheprovider` gave **113 passed**, 1 deprecation warning (from Starlette/httpx, not from this change). The count is up from 112 because of the extra formatter test.

Runtime, sanitized (no token, chat ID or account details):

| | Before (PID 42512) | After `gold.cmd restart` (PID 46336) |
|---|---|---|
| mode / symbol | mt5 / XAUUSDc | mt5 / XAUUSDc |
| feed ok | true | true |
| scanner running / paused / error | true / false / none | true / false / none |
| Telegram enabled / persisted opt-in / state | true / true / enabled | true / true / enabled |
| signals / candidates | 0 / 3 | 0 / 3 |
| outbox rows | sent, sent | sent, sent (nothing new queued) |
| session watermark | 2026-10-05T03:33:57Z | 2026-10-05T04:05:09Z (startup) |

- **Startup events:**
  - "external delivery restored: restored the explicit opt-in from 2026-10-05T02:48:21Z (new signals only)";
  - "VC Signal started: LIVE MT5 (XAUUSDc); external delivery ON (restored explicit opt-in)";
  - "scanner session watermark … (startup)".
- **Watermark:** the move to the restart time is the app's designed startup behaviour (only confirmations closing after it are actionable). Stored history is untouched.
- **Launcher:** the restart used the supported command, which ran the token-authenticated `/api/admin/shutdown` and then `start`. No processes were force-killed.

## Checks not performed

- **No live check of the new message:** I didn't confirm against the running server that a real queued message uses the new format. There are 0 signals, so there is nothing to preview, and the prompt forbids synthesizing a live signal or sending a test message. The new server process (PID 46336) was started after the code change and imports `app/delivery.py` fresh. The formatter is covered by the mocked-payload and preview tests above.
- **No real Telegram send:** none was made, as instructed.

## Questions, missing requirements, or blockers

None blocking. Two notes for Codex and the user:

1. **Out-of-date dashboard text.** Some dashboard text still describes the old labels, and the task excluded frontend changes, so I left it unchanged. It is now inaccurate:
   - the System → Telegram help line: "Live signals are labelled LIVE MARKET SIGNAL; demo signals DEMO TEST SIGNAL." (`frontend/src/index.template.html`);
   - the confirm dialogs when enabling delivery, which mention "LIVE MARKET SIGNALs" and "DEMO TEST SIGNALs" (`app/static/app.js`).

   A small follow-up could reword these.
2. **Messages no longer say live or demo, or which side.** As the user requested, Telegram messages no longer carry any live/demo label or the BUY/SELL side. A reader can still infer the side from the TP/SL positions relative to Entry. A demo-mode message is now indistinguishable from a live one in Telegram, but demo delivery requires a separate per-session opt-in. Flagging this in case the user wants a minimal marker later.

## Suggested next step

Codex could confirm with the user whether to update the two out-of-date dashboard texts above. When the next live signal confirms, the user will see the four-line message in Telegram.
