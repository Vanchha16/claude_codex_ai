# Fix FVG signal status, exact Guide links and record-refresh feedback

Task ID: 20261009-083335-fvg-signal-evidence-review-fixes
Delivery status: DRAFT — DO NOT EXECUTE
User authorization: pending
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261009-083335-fvg-signal-evidence-review-fixes.md`
Report path: `report/20261009-083335-fvg-signal-evidence-review-fixes-report.md`
Progress path: `report/20261009-083335-fvg-signal-evidence-review-fixes-progress.md`

## Goal and context

Resolve the three reproduced P2 findings in `report/20261008-163422-separate-signals-code-review.md`. The completed separate-signals task requires truthful broker statuses, links to each signal's exact evidence and visible refresh failures. Preserve independent M15 and M5 signals, histories and messages.

Read the review, its existing reproductions in `.tmp/separate-signals-code-audit/`, and the preceding separate-signals prompt/report before implementation. Claude implements; Codex plans and reviews. This draft does not authorize execution.

## Scope and relevant files

Expected scope: `app/static/fvg-signals.js`, `app/web.py`, the FVG store implementation, `app/static/fvg-guide.js` as needed for missing-record behavior, `app/static/fvg-engines.js`, and their frontend/backend regression tests. Follow existing asset generation if HTML/CSS changes are needed. Avoid unrelated cleanup of the existing uncommitted work.

## Implementation plan

1. **Truthful signal status.** In `signalStatus`, distinguish actual pending legs from historical acceptance, fills, closed legs, cancelled/expired legs and unresolved outcomes. Cancelled and expired orders must never contribute to a pending-order count. Derive the headline from current journal evidence; retain concise partial-acceptance and unresolved labels where appropriate. All-cancelled and all-expired baskets must visibly identify their terminal outcome, and mixed states must not claim more pending limits than actually remain. Closed filled legs must not imply currently open exposure. Keep journal-only sizing and per-leg evidence intact.

2. **Exact Guide lookup.** An explicit `/api/fvg/guide?key=...` must resolve that setup directly from storage, independently of the bounded recent selector list, even if other-engine records have displaced it. Include the selected setup in `records` without duplication so its selector label remains available. Resolve its associated basket directly by stored relationship rather than scanning only the most recent 500 baskets; use the existing store lookup where possible, or add a narrowly scoped parameterized read-only lookup. Do not solve this by increasing global fetch limits. An explicit nonexistent key must return a clear missing-record result and never substitute another setup. Keep ordinary default selection only for requests without an explicit key. Update the Guide frontend as needed so a missing explicit key clears stale selected evidence, retains the requested identity and displays an understandable message through refreshes. Preserve legacy and dual record rendering and compatibility for valid/default requests.

3. **Persistent refresh feedback.** In `refreshFvg`, write the success note only after a successful response for the current request generation. A failed first load must show a lasting failure without implying previous records exist. Failure after success must retain the failure and the last successful data timestamp; state/market refreshes must not conceal it. Clear the failure upon successful recovery. Superseded successes/failures must not modify current evidence, status, timestamps or busy state.

## Acceptance criteria and validation

- Add signal-status regressions for all cancelled, all expired, pending/cancelled/expired, terminal/refused mixtures, partial acceptance, filled/open versus closed and unresolved states. Assert actual pending counts and meaningful terminal wording, not merely historical acceptance.
- Add Guide API regressions for an old M15 setup displaced by more than 30 newer M5 setups, its associated basket displaced by more than 500 newer baskets, an unknown explicit key with a populated store, an unknown explicit key with an empty store, and unchanged no-key selection. Assert exact selected key/engine/basket identity, selector membership and read-only storage behavior.
- Add frontend coverage that exercises `refreshFvg` with controlled asynchronous fetch responses: first-load failure, success followed by failure, successful recovery, and overlapping requests resolving/rejecting out of order. Verify the rendered note, successful timestamp and busy cleanup. Cover missing explicit Guide selection and recovery without switching engine records.
- Re-run the relevant audit reproductions with expectations updated for corrected behavior, if useful; record which were actually run.
- Run the frontend suite and build, JS syntax checks, focused backend Guide/signals tests, and the full backend suite if backend code changes. Use a fresh project-local pytest basetemp, isolated test feeds/stores and fake delivery clients.
- Inspect browser behavior with isolated fixtures where available: cancelled/expired signal badges and history, an old M15 signal's exact Guide link, missing-key feedback, and engine records failure/recovery while other data continues updating. Report unavailable interactive checks honestly.

Keep files, caches and artifacts inside this project. Do not inject mock evidence into the live store, send Telegram messages, submit/cancel broker orders, change strategy/account/consent/risk configuration, reset data, install global tools, commit or push. Preserve existing natural automatic execution/delivery under its current authorization. Validation must use isolated stores and fake clients. Do not start a second live scanner. If approved backend changes require one controlled restart, follow the established launcher and reconciliation/fresh-watermark procedure, preserve all settings and report read-only health evidence.

## Reply and stopping condition

Acknowledge the approved task in the exact progress path. If a material requirement is missing, report the question and stop dependent work. Publish the complete report atomically through a project-local temporary file, with this task ID and source, changed files, actual validation, unavailable checks and remaining limitations. Do not claim historical audit results as new checks. After reporting, stop and wait for the next separately approved task.
