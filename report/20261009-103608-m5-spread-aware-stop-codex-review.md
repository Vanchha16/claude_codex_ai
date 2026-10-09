# Codex review: M5 stop policy implementation

Task ID: 20261009-103608-m5-spread-aware-stop
Source prompt: `prompt/20261009-103608-m5-spread-aware-stop.md`
Claude report: `report/20261009-103608-m5-spread-aware-stop-report.md`
Reviewed: 2026-10-09

The matching implementation report was received. The reviewed change addresses the screenshot's specific spread-room rejection: qualifying dual M5 gaps retain their entries and use the base common stop or the minimum outward tick adjustment needed for the measured spread plus one tick. Targets and sizing use that selected stop. M15 and legacy stop policies remain fixed.

Independent verification:

- `tests/test_fvg_spread_stop.py`, `tests/test_fvg_execution.py`, `tests/test_fvg_dual.py`, `tests/test_fvg_guide.py`, `tests/test_fvg_signals.py`: **103 passed**, fresh `.tmp/pytest-codex-20261009-m5-spread-review`.
- Frontend suite: **64 passed**, zero failures.
- Reviewed the stop calculation, engine-to-executor levels handoff, validation against recomputed broker-precision entries/targets, account-currency sizing, journal provenance, Guide actual/preview behavior and new regression cases.
- Exact example regression confirms SL **4172.64**, entries **4174.99 / 4173.85 / 4173.14**, TPs **4179.69 / 4176.27 / 4174.14**. The fake 100-unit contract produces lots **0.01 / 0.02 / 0.06** with total nominal planned loss **7.77**, within the 10-unit budget. These volumes are fictional test values, not live account sizing.
- Regression checks include SELL symmetry, unchanged M15/fixed behavior, missing/stale/invalid quotes, minimum-lot refusal, exact stored/message/journal/request levels, no resubmission and a spread widening before the first send that refuses the already chosen plan.
- Live read-only `/api/state`: running strategy still **@f4b7f7a5**, automatic execution **ON**, risk **$10**, scanner running without an error. No activation occurred.

No blocking issue found for the implemented stop-policy change in these checks. Claude reports **393 passed** in one full backend run and successful frontend build; those were not independently repeated. No browser visual QA of the new plain-text provenance lines was performed. Existing account/freshness guards during individual sends were retained; the new spread-widening regression exercises the recheck before the first send, not changing spread between later legs.

Version decision: keeping the existing whole-dual-config digest is acceptable for this task. Both engine version strings become **@a2d893f0** even though M15 behavior is unchanged; shared strategy provenance should reflect the changed dual configuration. Per-engine digest redesign is unnecessary here. Historical records/consent must remain intact.

Maximum-spread clarification from code inspection: above 0.50, M5 does not adjust its stop and the executor still rejects excessive spread. The report's statement that every such basket is refused by the engine's spread-room check is too broad: a sufficiently wide base stop can pass that check and yield a planned alert before execution refusal. This follows the existing signal-before-executor flow; it does not bypass the executor's spread ceiling.

Activation is a separate pending step. New code uses **@a2d893f0**; explicit old-version consent does not match that version. The current demo-account default may keep execution ON after restart without consent migration. A controlled restart must preserve settings, reconcile existing exposure and establish a fresh watermark; old screenshot gaps must not be traded retroactively.

Codex changed only handoff/review documents and ran isolated checks plus a read-only live state request. No broker requests, Telegram messages, consent/risk/configuration changes or runtime restart were made.
