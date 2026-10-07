# Correct the sidebar's outdated execution statement

Task ID: 20261007-141139-fvg-sidebar-execution-copy
Delivery status: DRAFT - DO NOT EXECUTE
User authorization: pending
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261007-141139-fvg-sidebar-execution-copy.md`
Report path: `report/20261007-141139-fvg-sidebar-execution-copy-report.md`

## Goal and context

The FVG build and the two dashboard fixes are complete. Claude found one pre-existing sidebar paragraph still saying "Alerts and simulated outcomes only. No orders are ever sent." That becomes inaccurate under explicitly armed FVG automatic execution, although the main footer and API are already correct.

## Scope and implementation

Change only this sidebar paragraph in `frontend/src/index.template.html` (currently line 102), then regenerate `app/static/index.html` through the normal asset build. Use this concrete wording, with minor punctuation/spacing adjustments allowed:

"CRT and FastSweep: alerts only. FVG can send real pending orders when automatic execution is ON (default OFF). Research baseline; not proven profitable."

Do not modify strategy logic, sizing, risk, broker requests, arming controls, active selection, credentials, live settings, history or delivery. Do not restart the live server, activate or arm FVG, initialize MT5, send broker requests or Telegram messages. FastSweep rr2 stays active, FVG inactive and execution OFF.

## Acceptance and validation

The sidebar must truthfully distinguish alert-only CRT/FastSweep from opt-in FVG automatic orders and preserve the research-baseline qualification. The built page must contain the corrected text. Run the applicable normal asset build and inspect the template and generated output. This is a one-paragraph copy edit: do not add mirror tests, rerun trading replays or broaden the task.

Keep all artifacts inside the project root. Verify resolved workspace paths before any recursive deletion/move.

## Reply and stopping condition

Codex is planner/reviewer; Claude is implementer. Do not execute this draft before separate approval and atomic publication. On approval, acknowledge in `report/20261007-141139-fvg-sidebar-execution-copy-progress.md`, make the copy correction and publish a matching complete report atomically at `report/20261007-141139-fvg-sidebar-execution-copy-report.md`. Report actual checks and confirm no live actions and unchanged inactive/OFF status. Stop after reporting and wait for the next separately approved task.
