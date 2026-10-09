# Codex review: activation of spread-aware stops on both engines

Task ID: 20261009-110728-activate-m15-spread-aware-stop
Source prompt: `prompt/20261009-110728-activate-m15-spread-aware-stop.md`
Claude report: `report/20261009-110728-activate-m15-spread-aware-stop-report.md`
Reviewed: 2026-10-09

The matching complete activation report was received. Claude reports one successful launcher restart from PID 13004 to 20836 and unchanged source/account/symbol/configuration/consent hashes, without code changes or test orders/messages.

Independent read-only verification confirms:

- Active dual strategy and both engine versions are **@dc9ff475**.
- Both M15 and M5 scopes describe the spread-aware stop: base two ticks beyond the far zone edge, moved further outward only as needed for spread plus one tick.
- Live MT5 connected, **MetaQuotes-Demo** demo account, **XAUUSD**; quote fresh.
- Scanner running, unpaused and without errors; fresh session watermark **2026-10-09T06:36:25.695823Z**.
- Automatic execution **ON** through the demo-account default; planned risk **$10 per basket**; Telegram enabled.
- Owner file reports PID **20836**, matching Claude's new process.
- Shared daily basket counter is **3/4** on 2026-10-09 Bangkok date. This is not three broker-accepted order batches: read-only M5 history shows two preflight-refused baskets and one closed basket. The existing counter includes those refused reservations; that rule was not changed in this task.

Additional independently observed history: M5 basket `FVG5-0ce92ed6135eb330`, created at 04:30Z under the previous **@a2d893f0**, stored a stop moved two ticks from 4180.10 to 4180.08; all three journal legs are now `closed_sl`. This is a live broker outcome with the already activated M5 policy, not an outcome produced by this activation or evidence of a profitable trade. The other two recorded M5 baskets have no submitted legs and were refused because entry 1 could not fit the minimum lot within its equal risk share.

No new-policy M15 broker outcome was available in Claude's activation report. Healthy activation confirms loaded code/settings, not future order acceptance. Existing gaps remain historical; new qualifying closes after the startup watermark are eligible subject to remaining rules and the daily cap.

No blocking activation issue found. Both requested stop-policy changes are now live. Configuration hash preservation was reported by Claude, not independently reconstructed from the previous process. Codex only read live state/history/owner metadata and wrote this review; no broker, Telegram, consent or runtime changes were performed by Codex.
