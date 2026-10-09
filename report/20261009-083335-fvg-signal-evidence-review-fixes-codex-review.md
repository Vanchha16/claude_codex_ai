# Codex review: FVG signal evidence fixes

Task ID: 20261009-083335-fvg-signal-evidence-review-fixes
Source prompt: `prompt/20261009-083335-fvg-signal-evidence-review-fixes.md`
Claude report: `report/20261009-083335-fvg-signal-evidence-review-fixes-report.md`
Reviewed: 2026-10-09

The matching completed report was received. The three reproduced findings from the preceding review are addressed in the reviewed paths:

- Signals counts actual pending legs separately from cancelled, expired, open and closed journal states. The status regressions cover terminal and mixed states and preserve unresolved evidence. The related Engines pending-order chip also counts only currently pending legs.
- Guide resolves an explicit setup with `get_setup` and retrieves its basket with a parameterized stored-relationship query. An older requested setup is added to the bounded selector once; an unknown key returns an explicit missing result without choosing another record. The frontend retains the missing identity and hides the previous evidence.
- Engine record-refresh feedback retains failure and last successful data time, clears on successful recovery, and ignores superseded success/failure responses. Only the current request clears busy state.

Independent verification:

- Frontend suite: **62 passed**, zero failures. Includes controlled asynchronous fetch regressions exercising the actual Engines script, signal terminal-state cases and Guide selection-state cases.
- `tests/test_fvg_guide_exact.py`, `tests/test_fvg_guide.py`, `tests/test_fvg_signals.py`: **19 passed** using fresh `.tmp/pytest-codex-20261009-fvg-evidence-review`. The exact-link regression displaces the old M15 setup with 31 M5 setups and its basket with 510 newer baskets; it checks exact setup/engine/basket identity, selector membership, missing-key results and unchanged no-key behavior.
- Read the changed status, API/storage lookup, Guide selection/rendering and refresh-generation logic.
- Viewed saved `01-MOCK-signals-cancelled-expired-mixed.jpg`: separate M15 cancelled and M5 mixed-pending panels, plus expired history, visibly match the corrected wording. This is inspection of Claude's isolated mock artifact, not an independent interactive browser check.

No blocking issue found in these checks for the three reviewed findings. The full backend suite, build, live health/settings and controlled restart were not independently rerun or verified. Claude reports three full-suite runs with **364 passed**, and intermittent failures in two MT5-time parameter cases in other runs; full-suite stability remains unresolved. The test file was unchanged by this task, but the reported pre-existing attribution was not independently investigated. Mobile/light-theme checks were not performed by Claude for these changes.

No application code, live orders, Telegram messages, consent, risk settings, runtime or account state was changed by Codex. The separate explicit dual-version consent item remains outside this task.
