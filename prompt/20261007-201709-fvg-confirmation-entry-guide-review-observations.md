# Codex review observations for the active FVG Guide task

Document type: REVIEW OBSERVATIONS ONLY — not another implementation task or independent execution authorization.
Applies to existing approved task: 20261007-201709-fvg-confirmation-entry-guide
Source of implementation authorization remains: `prompt/20261007-201709-fvg-confirmation-entry-guide.md`
Existing final report remains: `report/20261007-201709-fvg-confirmation-entry-guide-report.md`

These are preliminary findings from the in-progress display code, within the existing task's requirement for truthful partial/unknown states and missing-data handling. No strategy, risk, execution or consent changes are requested or authorized. This note does not authorize re-executing any completed task.

1. **Unknown fill evidence is currently asserted as no fill.** The fake probe in `.tmp/fvg-guide-codex-review/preliminary-edge-probes.json` calls `steps` with a confirmed record and execution `needs_reconciliation`, legs `unknown, not_sent, not_sent`. The pending stage correctly says outcome uncertain, but the fills stage is failed and says `No leg filled: 1 unknown, 2 not_sent`. An unknown leg can have filled. The expected presentation is unresolved/being reconciled, not proof of no fill. The same principle applies to sending/submitting evidence. Known accepted/filled legs must remain visible alongside uncertainty.

2. **Partial submission is marked as completion of "Three pending limits".** `steps` groups `partial` with `submitted` and gives this stage `done`, with `Broker accepted the pending limits (state partial)`. An example with only one accepted pending leg and two not_sent has not completed three accepted limits. The guide should clearly show the accepted count and remaining refused/not_sent/unknown states; do not imply all three were accepted merely because the aggregate state is partial.

3. **Missing configuration/metadata needs honest labels.** `renderRisk` currently falls back to a $10 total for live records if risk is unconfigured. The guide API also fabricates 0.01 tick/point and two digits if feed metadata fails, and then emits exact-looking previews. A clearly fictional lesson can use declared fictional inputs. A live/historical preview should disclose unknown inputs or be unavailable rather than infer real sizing/precision. Older-version records must not present a recomputed current-config preview as stored historic evidence.

The actual motivating expired record and deterministic success lessons remain the main scope. These observations are informational review feedback for that approved implementation, not a new handoff. Acknowledge any addressed observations in the existing final report.

## Resume review evidence (2026-10-08)

The user asked Codex to continue and confirmed Claude is already working on the existing approved task. This section remains review feedback within that same task, not a new implementation task or a request to re-execute completed work.

Fresh deterministic probes are saved at `.tmp/fvg-guide-codex-review/resume-probes.py` and `resume-probes.json`. They still reproduce observations 1 and 2: both `unknown` and `sending` legs lead to a false "No leg filled" statement; one pending, one rejected and one not_sent leg completes "Three pending limits". Preserve known accepted/filled evidence while explicitly reporting unresolved legs.

4. **The confirmation diagram contradicts missing-bar invalidation.** The probe supplies a retest closing 12:05Z, omits the expected 12:05Z M5 bar, and supplies a later bar opening 12:10Z whose close crosses the threshold. The recorded setup is correctly `invalidated / m5_continuity_lost`, but `window_candles` compresses the later candle into `window-1` and says "closed beyond the level - confirms" with `beyond: true`. Slot numbering must follow actual expected M5 timestamps and the stored lifecycle evidence. Bars after a missing/invalid bar, setup deadline, invalidation, or an earlier confirmation must not be represented as additional valid confirmations. A close comparison can remain visible if clearly labelled as such rather than a passed confirmation. The existing task explicitly requires contiguous candles and honest unavailable history.

5. **Partial M15 history can mislabel A/B/C.** `record_view` currently enumerates whatever aggregates are available and assigns `ABC[i]`. If A is unavailable but B/C remain, B is labelled A and C is labelled B. Assign each role from its expected timestamp (`a_open`, `a_open + M15`, `a_open + 2*M15`) and disclose missing formation candles.

6. **A forming candle is still introduced as closed in the confirmation list.** `renderLive` prefixes every window item with "M5 closed", even when `closed` is false and its verdict says forming. Use a forming label and expected close time in that case.

Independent checks saved from 2026-10-07: 323 backend tests and 40 frontend tests passed (`independent-test-summary.json`); these are not evidence that the above edge cases work. Extend focused behavioral coverage where appropriate under the existing acceptance criteria.

Read-only runtime at 2026-10-08 01:08Z is saved in `.tmp/fvg-guide-codex-review/resume-runtime.json`: FVG RR2/XAUUSD active, scanner running, MT5 terminal not running/account unavailable, effective automatic execution OFF for that reason, saved risk $10, Telegram enabled, one historical expired setup. Codex changed no live settings or trading state. Preserve saved preferences and report disconnected effective status honestly; do not initialize/login/switch MT5 for this guide task.

Codex's current UI tool inventory has no enabled browsers or native apps, and opening the in-app browser returned "Browser is not available: iab". No desktop/mobile screenshot or visual approval is claimed by Codex. Complete available visual verification from Claude's supported environment and document actual limitations in the existing final report.
