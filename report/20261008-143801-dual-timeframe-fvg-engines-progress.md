# Claude progress: independent M15 and M5 FVG order engines

Task ID: 20261008-143801-dual-timeframe-fvg-engines
Source prompt: `prompt/20261008-143801-dual-timeframe-fvg-engines.md`
Status: COMPLETE: final report published at `report/20261008-143801-dual-timeframe-fvg-engines-report.md` (dual consent still to be recorded by the user)
Updated at: 2026-10-08

- [x] Approval gate checked (APPROVED FOR EXECUTION, Task ID, source, report path, recorded "send it", no existing report)
- [x] Read rule/live/replay/orders/execution/scanner/strategy/web sources and the Guide report
- [x] Timeframe-aware pure rules + dual engine (app/fvg_dual.py); legacy v1 preserved and selectable
- [x] Shared admission: one slot per engine, 30 min cooldown per engine, 4/day total (M15 before M5), $10 per basket
- [x] Executor: only the other engine's own open basket may coexist; FVG15/FVG5 broker comments
- [x] Replay, API, dashboard engines table, Guide dual path + lessons (legacy labelled)
- [x] Tests: backend 360 passed (fresh basetemp), frontend 43 passed, build + syntax OK
- [x] Visual verification on an isolated dual DEMO instance (stopped); screenshots in .tmp/fvg-dual-screens
- [x] Activation: the user ran the select + restart commands; dual mode active (ON via demo default; explicit dual consent pending)
      restarts and records the new consent was DENIED by Claude Code's permission (auto-mode) classifier on
      2026-10-08. Not retried or worked around. Waiting for the user to allow it or to run it themselves.
- [x] Final report
