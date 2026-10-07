# Codex review: FastSweep strategy research

Task ID: 20261006-144723-fast-sweep-strategy
Source prompt: prompt/20261006-144723-fast-sweep-strategy.md
Claude report: report/20261006-144723-fast-sweep-strategy-report.md
Status: reviewed; historical results accepted as exploratory evidence, objective not achieved; no live activation

## Independently verified

- Matched the actual completed report to the approved task and source.
- Ran tests/test_fastsweep.py: all 18 tests passed.
- Independently replayed both baseline profiles from the cached real broker candles. Segments, every signal, daily tables and frequency statistics matched saved results exactly.
- Independently recomputed reward/risk geometry for every emitted research signal: at least the profile ratio after outward rounding.
- Config, original CRT strategy/engine/replay, scanner, config loader and API files retained their pre-task SHA-256 hashes.
- Read live API after completion: current CRT profile remains minimum RR 1.5, not FastSweep; healthy live MT5 feed/scanner, Telegram remains enabled, zero live signals.
- Claude reports 131 backend and 28 frontend tests passed. Codex independently reran the 18 new tests, not the whole suite.

## Result

The 1:1 profile generated 102 research signals; 1:2 generated 101. Both averaged 2.317 signals over each of 41 dates with at least 12 hours of valid M5 data. Both had 3-4 signals on 19/41 covered dates (46.3%); five of the covered dates had zero signals. Full-period simulated totals were -19.3372R and -17.7181R. Both later-period results and cost-stress results were negative. This meets neither a reliable 3-4 daily target nor an evidenced positive result. The live system was not changed to manufacture alerts.

## Implementation limitations found during review

1. The daily-table builder creates dates through the last bar OPEN date, while candidates are assigned using B CLOSE dates. A valid series ending exactly at Bangkok midnight can create a candidate on the next date and raise KeyError. Independently reproduced with two complete M15 candles ending at 2030-01-08 00:00 Bangkok. This does not affect the evaluated sample ending at 13:55 Bangkok, but needs a fix and boundary test before general use.
2. The build_levels helper checks quote age but does not enforce a maximum elapsed time from confirmation to entry. A fresh quote ten minutes after confirmation is accepted directly. The current OHLC replay only enters at the exact confirmation timestamp, so reported historical results are unaffected. Add the confirmation-age and future-quote checks before any live adapter.
3. EMA readiness deliberately resets across every M15 gap, including the routine daily break. Requiring 50 contiguous candles removes roughly 12.5 hours after each break and rejected 682 of 1,313 valid range patterns. Changing that behavior is a new strategy experiment, not a silent fix to these predeclared results.

No fixes or new implementation tasks were dispatched during this review. These findings must accompany any future development or live-activation proposal.

## Report precision

The report refers to dispatch as 14:47 Bangkok, which was the draft task timestamp. Actual publication was 2026-10-06 07:53:42 UTC (14:53:42 Bangkok). The documented dashboard test-message/toggle events still predate publication. They were not actions by this task.

The later sample was already inspected; it is comparison data, not untouched validation. These are simulated OHLC price hits with assumed costs, not broker executions or a claim of profitability. The old live configuration remains unchanged. Any next experiment or activation needs a separately reviewed task under the established workflow.
