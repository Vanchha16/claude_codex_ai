# Codex review: FVG confirmation-to-entry Guide

Task ID: 20261007-201709-fvg-confirmation-entry-guide
Source prompt: `prompt/20261007-201709-fvg-confirmation-entry-guide.md`
Matching Claude report: `report/20261007-201709-fvg-confirmation-entry-guide-report.md`
Reviewed: 2026-10-08

The matching final implementation report has been received. All six previously recorded presentation findings are addressed according to the report; focused checks independently confirm the substantive evidence-state, missing-history and version-preview fixes.

Independent checks on the reported final code:

- `pytest tests/test_fvg_guide.py --basetemp=.tmp/pytest-codex-guide-final-20261008-1500`: 19 passed. One existing Starlette/httpx deprecation warning.
- `npm.cmd test` in `frontend`: 42 passed.
- `.tmp/fvg-guide-codex-review/resume-probes.py`: unknown/sending legs remain unresolved instead of no-fill; one accepted limit is partial; a known fill remains visible beside uncertainty; a missing M5 slot ends the window; missing A leaves B/C correctly labelled; an older rule version has no recomputed preview.

Claude reports two successful full-suite runs of 333 tests after one intermittent MT5-time failure. Codex did not rerun the full suite in this final focused review and has not independently diagnosed that intermittent failure. It is recorded rather than attributed to this change.

Claude documents desktop/mobile screenshots, light/dark checks and navigation, plus specific unavailable checks. Codex's current UI inventory has no enabled browser/native surface, so no independent interactive visual verification is claimed here. No live settings, broker orders, Telegram messages or application implementation files were changed by Codex during this review.

The user has now specified a separate dual-engine strategy: independent M15/M5 qualification, immediate pending limits, and $10 per basket with two concurrent baskets allowed. That new task is a separate draft, not authorization to reinterpret this completed Guide task or its legacy strategy.
