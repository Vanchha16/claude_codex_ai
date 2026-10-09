# Codex review: M5 stop policy activation

Task ID: 20261009-105101-activate-m5-spread-aware-stop
Source prompt: `prompt/20261009-105101-activate-m5-spread-aware-stop.md`
Claude report: `report/20261009-105101-activate-m5-spread-aware-stop-report.md`
Reviewed: 2026-10-09

The matching activation report was received. Claude reports exactly one controlled launcher restart, PID 33344 to 13004, successful startup and unchanged configuration/consent hashes. No implementation changes or manual test orders/messages were reported.

Independent read-only `/api/state` confirms:

- Dual strategy and both engine versions end in **@a2d893f0**.
- M5 scope describes the spread-aware common stop; M15 scope describes the fixed two-tick stop.
- Live MT5 is connected to **MetaQuotes-Demo**, demo account, symbol **XAUUSD**.
- Automatic execution **ON** via the existing demo-account default; planned risk **$10 per basket**.
- Scanner running, unpaused, no error; quote fresh.
- Fresh session watermark **2026-10-09T03:56:01.199700Z**, after the old screenshot gaps.

Configuration hash preservation and absence of open baskets at restart were reported by Claude, not independently reconstructed from the previous process. Successful startup does not demonstrate a real new-policy basket or broker acceptance; no such live example was available in the completed report. The screenshot gaps remain historical. New qualifying closes after the watermark are eligible under the new policy and all remaining checks.

No blocking activation issue found. The reviewed fix is now loaded in the live app. Explicit new-version consent was not added or migrated; execution follows the already enabled demo-account default. Codex performed read-only state verification and wrote this review only, without restarting the runtime or sending broker/Telegram requests.
