# Codex review of the three-bug repair

Task reviewed: 20261002-132805-gold-three-bug-fixes
Source report: report/20261002-132805-gold-three-bug-fixes-report.md
Review date: 2026-10-02
Outcome: two replay defects repaired; startup/recovery repair still has a same-scan reconnect gap.

## Independently checked

- Full suite: 80 passed, one third-party Starlette TestClient deprecation warning. Temporary test directory under .tmp.
- Replay code now advances exits through the replay clock, clips tick reads to period.end, and preserves overlap protection until observed exits. Existing/new tests cover bounded exits and entry, missing ticks, overlap, BUY Bid and SELL Ask exit sides.
- MT5 replay now performs lazy tick reads inside try/finally and closes the feed afterward. Mocked lifecycle tests pass.
- Engine checks confirm_close against the in-memory session eligibility watermark before creating a signal; startup/restart and multi-scan unhealthy recovery regressions pass.
- Local health endpoint reports PID 27448, demo mode, scanner running. State has no scanner error and Telegram configured false/enabled false.

## Remaining finding: successful reconnect within the same scan

app/scanner.py:_ensure_connected sees an unhealthy feed status, calls feed.connect(), and returns the recovered healthy status. _scan marks _unhealthy only when that returned status is unhealthy, so a reconnect that succeeds immediately loses the unhealthy transition. The old session watermark can still authorize a missed confirmation less than 30 seconds old.

Independent mock-only reproduction using tests.test_scanner.make/run:
1. Run the demo scanner from 05:30 through 06:09:30, establishing the old watermark and a pending candidate.
2. Advance its fictional clock to 2030-01-07T06:10:05, five seconds after confirmation.
3. Set the mock feed mode to mt5; status returns disconnected; connect restores the demo feed's healthy status immediately. No real MT5 API is invoked.
4. scan_once followed by mocked delivery.process_due.

Result: watermark_reset=false, signals_created=1, mock_telegram_calls=1. No real Telegram message was sent.

Required correction: preserve the unhealthy/reconnection transition before connect returns, so the first healthy recovered scan opens a fresh watermark even when reconnect succeeds within that scan. Add a regression for this exact case and a control showing a truly new post-recovery confirmation is still eligible. Preserve existing positions and deduplication. Review is not final acceptance of all three bugs.

The separate remaining live SELL OHLC limitation continues: outcomes may be estimated from Bid bars plus entry spread; real MT5 and Telegram remain unverified. No application code changed during this review.