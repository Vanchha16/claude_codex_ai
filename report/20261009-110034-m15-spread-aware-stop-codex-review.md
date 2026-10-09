# Codex review: M15 spread-aware stop

Task ID: 20261009-110034-m15-spread-aware-stop
Source prompt: `prompt/20261009-110034-m15-spread-aware-stop.md`
Claude report: `report/20261009-110034-m15-spread-aware-stop-report.md`
Reviewed: 2026-10-09

The matching implementation report was received. Both dual engines now default to the existing spread-aware stop policy in code, with expected strategy/engine versions **@dc9ff475**. M5 numerical behavior is preserved; M15 now uses the same shared level-plan calculation and executor interface. Legacy fixed-stop behavior remains available.

Independent checks:

- Stop-policy, dual, execution, Guide, Guide-exact, signal and FVG/sizing regressions: **130 passed**, fresh `.tmp/pytest-codex-20261009-m15-spread-review`.
- Frontend suite: **65 passed**, zero failures.
- Reviewed the per-engine default/scopes change, strategy description, Guide stop-rule rendering and M15 BUY/SELL/no-adjustment/fixed-policy tests. M15 fake-executor coverage verifies stored basket, message, Guide, journal and broker-request level agreement, planned loss within the budget and no repeat submission for the same close.
- Read-only live state still shows **@a2d893f0**, M15 fixed stop and M5 spread-aware stop, execution ON, $10 planned risk, connected feed and healthy running scanner. The M15 implementation is not activated yet.

No blocking issue found in these focused checks. Claude's one full backend run had **398 passed, 2 failed** in the previously recurring MT5-time parameter cases at `tests/test_mt5_time.py:95`. The proposed clock-dependent fixture cause remains a hypothesis; Codex did not investigate it or rerun the full suite. This task did not change time/feed code. Claude reports a successful frontend build; no browser visual QA of the updated rule text was performed.

Activation requires one separately approved controlled restart to load **@dc9ff475**, preserving source/account/symbol/risk/delivery and existing demo-account execution default. No old consent/records should be migrated, and old gaps must remain historical. Both engine version labels change under the existing whole-config digest; M5 behavior remains as previously reviewed.

Codex ran isolated tests and read-only live verification and wrote handoff/review documents. No application code, runtime, consent, broker orders or Telegram state was changed by Codex.
