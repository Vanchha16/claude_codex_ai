# Codex review: FVG dashboard risk and timeframe fixes

Author: Codex
Task ID: 20261007-135946-fvg-dashboard-risk-labels
Source prompt: `prompt/20261007-135946-fvg-dashboard-risk-labels.md`
Claude report: `report/20261007-135946-fvg-dashboard-risk-labels-report.md`
Reviewed: 2026-10-07T14:11:39

## Outcome

The two approved defects are resolved and this task is accepted. USC risk is converted to USD correctly while retaining original cent units. FVG uses the M15/M5 caption and readiness; CRT and FastSweep retain their existing correct behavior. Scope is presentation and tests only; no backend Python file has a modification time during this task.

## Independent checks

- `npm.cmd test` in `frontend/`: 36 tests passed (28 existing plus 8 new), zero failures/skipped.
- `node --check app/static/app.js` and `node --check app/static/fvg-display.js`: passed.
- Executed the actual `renderFvgBaskets` from final app.js in a DOM stub with the actual helper. Verified USC 333.33 -> $3.33 USD (333.33 USC), USD 3.33 -> $3.33 USD, missing currency -> clearly labeled account units, and EUR -> explicit no USD conversion. No false $333.33 USD appeared.
- Executed the actual last-closed branch from `refreshState` with FVG warm-up state: M15/M5 caption and 12/50 M15 (warm-up), with no H1 caption.
- Evidence: `.tmp/fvg-codex-review/dashboard-fixes-final-verification.json`.
- Inspected Claude's actual desktop System/Overview and 390 px leg-column screenshots in `.tmp/ui-mock/screens/`. Correct converted amounts and M15 readiness are visible. Narrow leg text wraps inside the table, whose container scrolls horizontally.
- Checked built/template script order: fvg-display.js is loaded before app.js.
- Confirmed active selection remains FastSweep rr2, configured setup risk remains 10 USD and `.tmp/gold-signals/fvg_execution_optin.json` is absent.
- Claude also reports a successful asset build, six API tests and a mock browser check. Codex did not repeat those operations or run the full backend suite for this presentation-only change. The parent build's independent 233-test backend pass remains the prior result.
- No live-server restart, activation, arming, actual broker requests or Telegram sends by Codex.

## Final source hashes

{
  "app/static/app.js": "8afaab1afc8baecd84a77688e6586050134efa671df237bf5bb1a462b25fee5b",
  "app/static/fvg-display.js": "db5fd2394c75b39bf29427bbb4e34325b2cb1e97bd021ad39940beae7584db92",
  "frontend/tests/fvg-display.test.mjs": "a6a4d0d66b5f149dfe433dc0d04e6878ecda1501e413723c19b0dda8457f20d2"
}

## Remaining pre-existing wording

Claude identified an older sidebar paragraph in `frontend/src/index.template.html:102`, copied to `app/static/index.html:102`, saying "No orders are ever sent." The main footer and API already distinguish alert-only CRT/FastSweep from opt-in FVG order capability. The sidebar sentence becomes inaccurate if FVG is activated and armed. This was outside the approved two-defect follow-up scope and remains unchanged. It is a presentation correction, not an order-sizing or execution defect.

A one-paragraph wording follow-up is drafted at `prompt/drafts/20261007-141139-fvg-sidebar-execution-copy.md`, not dispatched. No further implementation is authorized merely by completion of the current task.
