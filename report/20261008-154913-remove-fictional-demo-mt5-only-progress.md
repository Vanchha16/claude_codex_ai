# Claude progress: remove fictional demo features; MT5-only

Task ID: 20261008-154913-remove-fictional-demo-mt5-only
Source prompt: `prompt/20261008-154913-remove-fictional-demo-mt5-only.md`
Status: COMPLETE: final report published at `report/20261008-154913-remove-fictional-demo-mt5-only-report.md`
Updated at: 2026-10-08

- [x] Approval gate checked (APPROVED FOR EXECUTION, Task ID, source, report path, recorded "send it", no existing report)
- [x] Before-state runtime/settings evidence (non-secret)
- [x] Inventory of production demo references (classify: remove / broker metadata / test-only / historical)
- [x] Backend: MT5-only config/startup/scanner/routes/replay; DemoFeed + fixture + lessons removed; demo rejected without side effects
- [x] Frontend: demo controls/labels/lesson player removed; Guide keeps real records; clean layout preserved
- [x] Tests migrated to explicit test-only fakes; new MT5-only/rejection tests; full backend + frontend + build
- [x] Visual checks (desktop/390, light/dark) with isolated mocks; one controlled restart if needed; after-state evidence
- [x] Final report
