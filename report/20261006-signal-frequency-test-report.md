# Signal frequency test results

User authorization: On 2026-10-06, the user selected "Test changes for more signals". These are isolated exploratory tests only.

Status: completed. No live strategy, application source, database, scanner controls or Telegram settings changed. No messages or orders sent.

## Result

Lower RR thresholds produced more historical alerts. Both alternatives had negative simulated results in the later period. Extending the confirmation window alone produced no signals.

| Profile | Earlier-period signals | Later-period signals | Total signals | Later-period simulated result |
|---|---:|---:|---:|---:|
| Current rules | 0 | 0 | 0 | +0.0000R |
| Minimum RR 1.0 | 1 | 1 | 2 | -1.0100R |
| Minimum RR 0.5 | 10 | 4 | 14 | -0.7662R |
| Two-hour confirmation window | 0 | 0 | 0 | +0.0000R |

The RR 1.0 profile produced one TP in the earlier period and one SL in the later period. The RR 0.5 profile produced eight TP, one SL and one timed expiry in the earlier period; the later period had two TP and two SL. Lower RR means a winning target pays less relative to the stop risk. More signals do not by themselves show better results.

R means the simulated result divided by initial stop risk, with assumed slippage accounted for. These are price-hit simulations, not broker executions.

## Method and verification

Period: {'start': '2026-08-06T07:00:00Z', 'end': '2026-10-05T06:55:00Z', 'm5_bars': 11560, 'h1_bars': 963}. This is the same roughly 60-day broker history used in the earlier review, ending 2026-10-05 06:55 UTC.

Only existing GET /api/market/bars candle reads were used. No separate MT5 connection or replay POST was made. Pure app.replay.replay ran with an in-memory store and temporary StrategyConfig copies. Spread assumption: 0.20 price units; slippage assumption: 0.05. Each alternative changed only one setting.

The baseline reproduced the prior diagnostic exactly for candidate and rejection-reason counts in both periods. The live configuration file retained version CRT-SMC-v1@193949a6.

## Limits

The 70/30 chronological split is retained for comparison, but this sample was already inspected. The later period is therefore not an untouched validation set. Small signal counts and OHLC assumptions do not establish profitability or future signal frequency. No variant was selected or applied to live operation.

Script: .tmp/compare_signal_frequency.py
Detailed results: .tmp/signal-frequency-comparison-20261006.json
