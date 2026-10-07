# Codex review: MT5 timestamp finding

Author: Codex
Source finding: `report/20261007-142425-mt5-server-time-offset-finding.md`
Document type: REVIEW OF INFORMATIONAL FINDING - no implementation dispatch
Reviewed: 2026-10-07T14:28:42
User request: "check report from claude"

## Conclusion

The approximately three-hour future-timestamp problem is confirmed independently in the running dashboard. Claude's proposed configuration-only workaround is incomplete for FVG automatic execution. The automatic offset proposal also needs a reliable way to distinguish clock offset from a stale tick before implementation.

No code/config changes, activation, arming, backend restart, real MT5 initialization, broker requests or Telegram sends were performed by Codex. The HTTP check read only the existing local app's status; the reproduction uses a fake broker exclusively.

## Independent evidence

Read-only `GET http://127.0.0.1:8000/api/state`, observed at 2026-10-07T07:26:13.6503274Z:

- Account server: MetaQuotes-Demo, demo; symbol XAUUSD.
- Active strategy: FastSweep.
- Quote timestamp: 2026-10-07T10:26:11.586000Z.
- Last scan: 2026-10-07T07:26:12.356873Z.
- Quote age: -10799.2 seconds; fresh=false.
- Note: quote timestamp is in the future (clock skew or invalid data); nothing actionable.
- No legacy offset was reported.

The separate current-UTC tool returned 2026-10-07 07:27:12 UTC, consistent with the host clock used for the scan. The status corroborates the mismatch; it does not by itself establish that every MetaQuotes-Demo epoch uses the same broker-time convention or prove historical/DST rules.

## Corrections to Claude's proposal

1. **Cause is an inference.** Official MetaTrader5 Python documentation specifies UTC for returned tick/bar times and UTC range arguments: [copy_rates_range](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py), [copy_ticks_range](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py). The observed feed conflicts with that documented expectation. A broker-specific encoding/terminal issue is plausible, but should be verified rather than assumed universally.
2. **Setting +3 only fixes the feed path if that offset is confirmed.** `MT5Feed._utc` subtracts the configured offset and `_req` reverses it. `MT5FvgExecutor._context` instead computes age directly from raw `symbol_info_tick.time_msc` and has no feed offset input. With a fake +3-hour tick and feed offset +3, the feed quote is corrected to UTC while the executor still raises `invalid or stale MT5 quote`. Reproduction: `.tmp/mt5-time-codex-review/feed-executor-offset-reproduction.json`. Zero order requests were made.
3. **Learning offset from one tick and the local clock can make stale data look fresh.** Tick age and clock offset are confounded in that subtraction. Rounding to 15 minutes does not resolve it. 'Recent relative to the terminal's own last tick' is not independent evidence if it is the same stale tick. Do not weaken the future/stale guards or force every latest tick to now.
4. **Account/broker switching matters.** A verified correction should be explicit and tied to its validated server/account context. Changing broker or offset must reset session eligibility so old corrected history does not trigger new signals/orders. Retain fail-closed behavior when time semantics are uncertain.

## Recommended next task, not dispatched

First verify the broker/terminal time convention using read-only observations of advancing tick timestamps, known UTC and recent M5 chart/rate times, with no activation or order submission. Then define one tested UTC conversion contract used consistently by feed and FVG quote checks; verify range/history and pending-expiry semantics explicitly. Use fake-broker regressions for standard UTC, verified +3/+2, stale/weekend ticks, account changes and future timestamps. An explicit verified server-bound offset is preferable to unvalidated automatic guessing. Keep the $10 budget, strategy rules and default-OFF execution unchanged.

The user's current request is report review, not approval to implement or change environment settings. No new prompt has been dispatched. Any implementation task should be drafted for review in the selected agent-to-agent workflow.

## Activation rejection reported by Claude

Claude reports its earlier strategy-selection command was rejected by the Claude Code permission classifier as "Production Deploy". This is Claude's recorded rejection; Codex did not reproduce or bypass it. Current config still selects FastSweep rr2, and `.tmp/gold-signals/fvg_execution_optin.json` remains absent. The running backend has the old legacy trading-status wording, consistent with no restart.
