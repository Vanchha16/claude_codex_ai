# Code review: separate M5/M15 signals and linked evidence

Reviewed task: 20261008-161842-separate-m5-m15-signals
Source prompt: `prompt/20261008-161842-separate-m5-m15-signals.md`
Claude report: `report/20261008-161842-separate-m5-m15-signals-report.md`
Review date: 2026-10-08
Scope: latest signal separation UI/API/delivery and linked Guide/engine-view behavior. This is a review artifact, not an approved implementation task.

## Findings

### 1. [P2] Cancelled/expired orders are reported as pending

Location: `app/static/fvg-signals.js:51`, with the acceptance-state set at line 13.

`ACCEPTED` deliberately includes cancelled and expired orders as evidence of historical acceptance, but `signalStatus` uses the accepted count as a current pending count. Three cancelled legs or three expired legs yield “3 pending limits”; pending/cancelled/expired also yields “3 pending limits” with only one current pending order. This affects both the prominent signal badge and history labels. A user reviewing closed exposure receives an incorrect broker status.

Reproduced by running `node .tmp/separate-signals-code-audit/probe-ui.cjs`. The three terminal-state cases print actual pending counts 0, 0 and 1, while all display three pending limits.

Correction: track actual `pending` separately from historical acceptance and filled/terminal/unresolved evidence. Derive the headline from current journal states. Regression cases should include fully cancelled, fully expired, mixed pending/terminal and partial acceptance, as well as filled/closed/unresolved states.

### 2. [P2] Exact Guide links silently select a different engine's record

Location: `app/web.py:828` (bounded history read at line 823 and silent fallback at lines 829–830).

The requested Guide key is searched only in the latest 30 global setup records by default. A Signals panel now exposes independently filtered engine histories, so an older M15 basket can remain selectable while many newer M5 setups push its setup outside that global window. Explain in FVG Guide then returns a different newest setup, including an M5 record, rather than the requested M15 evidence. An invalid explicit key also silently selects another record. The frontend records that substitute key, making the mismatch persist on subsequent refreshes.

Reproduced using an isolated OfflineFeed and fresh local store in `python .tmp/separate-signals-code-audit/probe-guide.py`: seeded one older M15 setup plus 31 newer M5 setups; an explicit request for `audit-0` (M15 version) returned `audit-31` (M5 version), HTTP 200. A nonexistent explicit key also returned `audit-31`.

Correction: resolve an explicit key directly from storage independently of the bounded selector history, include the selected record in the response/selector, and report an explicit missing-key result rather than substituting. Resolve the associated basket directly as well; it currently uses a separate global 500-basket window. Keep normal default selection for requests with no key. Regression coverage should include an older requested engine record, an unknown key and an older associated basket.

### 3. [P2] Engine-record refresh errors are immediately overwritten

Location: `app/static/fvg-engines.js:495` (error assignment at line 491).

After `/api/fvg` fails, the catch writes an honest failure message, but the unconditional assignment after finally immediately replaces it with “Records updated <old timestamp>” or an empty string on the first failure. When state/market requests still succeed but the records endpoint fails, the engine charts can display old basket/decision evidence with no surviving record-refresh error.

Reproduced with the unmodified script in a small Node VM and a rejecting fetch: after `VCEngines.refreshFvg(true)`, `en-records-note` is empty even though fetch rejected with “offline probe”. Included in `probe-ui.cjs`.

Correction: write a success note only after a successful current-generation response, retain the failure until recovery and distinguish last successful data time from the failed refresh time. Test first-load failure, failure after success, recovery and superseded responses.

## Verification and limits

- Existing frontend signal tests: 4 passed.
- Existing backend signal/Guide tests: 17 passed using fresh `.tmp/pytest-codex-separate-signals-audit-20261008`.
- Both additional reproduction scripts passed their assertions that the defects currently occur.
- No application files changed; no live account, trading, consent, Telegram or runtime restart actions performed. Probes used an isolated offline store and fake browser/fetch objects.
- This deeper review supersedes the earlier proportionate delivery review's “no blocking issue found” conclusion for the presentation/link paths above. Tests of separate message IDs and contents still pass; no cross-engine Telegram concatenation defect was found in the reviewed delivery path.
- Full strategy/executor logic and an interactive browser session were not audited here. Any implementation follow-up needs its own approved task under the established agent-to-agent workflow.
