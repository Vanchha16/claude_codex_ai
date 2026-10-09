# Codex review: MT5-only demo removal

Task ID: 20261008-154913-remove-fictional-demo-mt5-only
Source prompt: `prompt/20261008-154913-remove-fictional-demo-mt5-only.md`
Claude report: `report/20261008-154913-remove-fictional-demo-mt5-only-report.md`
Reviewed: 2026-10-08 approximately 16:16 Asia/Bangkok

Read the matching COMPLETE report. Claude reports 359 backend tests and 52 frontend tests passed, successful build/syntax checks, one successful controlled restart and no task blockers.

Independent checks:

- Frontend `npm.cmd test`: 52 passed, zero failures.
- Selected backend suites passed with exit code 0: `test_mt5_only.py`, `test_api.py`, `test_fvg_guide.py`, `test_fvg_review_fixes.py`, `test_regressions_watermark.py`, `test_regressions_reconnect.py`, using fresh `.tmp/pytest-codex-mt5-only-review-20261008`. This was focused validation, not an independent rerun of all 359 tests.
- Read test feed injection/safety fixture and MT5-only acceptance tests; reviewed production config, startup and route removal changes. Search for retired fixture imports/config/endpoints/UI controls in production/templates/docs returned no matches in the searched patterns.
- Live GET: `/api/state` is MT5, has no demo key, feed and scanner healthy, XAUUSD and dual strategy unchanged, Telegram enabled. Execution ON via existing broker demo-account policy, armed_at null, $10 basket / $20 maximum planned concurrent risk. M15 warming up 45/50, M5 ready at review time; these counts advance naturally.
- Live GET: removed `/api/fvg/guide/lessons` returns 404; `/api/replay?source=demo` returns 400; actual-record `/api/fvg/guide` returns 200. No mutating requests sent.
- Compared nine preservation fields in Claude's before/after artifacts: account server/type, symbol, strategy version, automatic execution, consent source/time, risk and Telegram all unchanged. Also observed current live state as above. Did not independently reproduce the claimed historical database/config hash checks.
- Viewed saved `02-live-guide-real-record-no-lessons.jpg`: Guide retains actual historical M5 setup evidence, no fictional lesson tabs or demo header controls. Artifact inspection only; no independent interactive browser session.

No blocking issue found in this proportionate review. Test-only fictional fixtures, genuine broker account metadata/policy and historical records are retained as authorized. The existing explicit dual-version consent remains a separate open item; this task neither supplies nor changes it. The account's genuine MetaQuotes-Demo name/type is correctly retained.
