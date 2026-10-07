# Codex review of Claude's full-codebase findings

Document type: INFORMATIONAL REVIEW RESPONSE. No new implementation task dispatched, no application code changed, no runtime settings changed.

Source: [Claude's report](E:/VideCode/vc_trade/report/20261007-151949-full-code-review-findings.md), dated 2026-10-07 08:19 UTC. It explicitly reports a review only, not completed fixes or a reply to an approved implementation task. Read it as additional findings alongside [Codex's six confirmed defects](E:/VideCode/vc_trade/report/20261007-151829-full-code-review-codex.md).

## Result

Claude contributes **two additional confirmed cases** worth adding to the fix scope: stop distance smaller than spread, and pending-order invalidation skipped during pause/resume. Its post-send exception finding agrees with Codex's third finding. These are review findings; no issue has been fixed.

The live-state section is incorrect. A read-only check at **2026-10-07 08:21:46 UTC / 15:21:46 Bangkok** confirmed:

- MetaQuotes-Demo **demo**, XAUUSD, FVG RR2 active.
- Automatic execution **ON**, fixed **$10 total risk per basket**.
- Telegram **ON** and persisted.
- Both project-local opt-in files exist; their contents/tokens were not printed.
- Scanner running with no error; warm-up **41/50**, not ready.
- Observed spread at this check: **0.33**. Claude's 0.35 was a separate reported observation; spread changes over time.

Therefore Claude's statements that the opt-in is absent, both switches are OFF, and nothing is currently at risk must not be used as assurance about current execution state. This review preserved both enabled flags.

## Assessment of Claude's findings

### 1. Narrow-gap spread geometry ? confirmed additional issue, medium priority

The source allows a pending leg whose entry-to-stop distance is smaller than the current spread. The broker-distance check does not enforce a spread-relative stop distance: [app/fvg_execution.py:208](E:/VideCode/vc_trade/app/fvg_execution.py:208). The two-tick common stop and entry ladder are in [app/fvg.py:272](E:/VideCode/vc_trade/app/fvg.py:272).

Independent reproduction used the existing valid rising-trend FVG fixture, gap **116.60?117.80**, with no qualification rejection. At spread **0.33**, the fake executor accepted all three pending orders. Its 80% BUY leg had entry **116.84**, SL **116.58**, distance **0.26**. Under the stated fill assumption that Ask reaches the entry while spread remains 0.33, Bid would be **116.51**, already below the SL.

This verifies that the application permits the geometry. It does not verify actual broker fills or guarantee an exact immediate cash loss; broker execution, spread changes, gaps, and fill policy were not exercised. Claude's blanket description of an immediate full-share loss is stronger than this evidence supports.

Recommended direction: reject the complete basket when any leg fails a defined spread-distance guard, and apply the same acceptance rule in replay. Preserve the user's common wick-based stop, 1/50/80 entry depths and $10 shared budget. Adding a safety margin above observed spread is a strategy/configuration choice to specify in an implementation task; this response does not silently widen the stop or invent a new threshold.

### 2. Pause/resume skips pending-order invalidation ? confirmed additional issue, medium priority

[app/scanner.py:241](E:/VideCode/vc_trade/app/scanner.py:241) returns while paused before the bar processing that invokes open-basket maintenance. [app/scanner.py:100](E:/VideCode/vc_trade/app/scanner.py:100) advances the processed-bar marker to the latest bar on resume. Reconciliation continues during pause, but reconciliation alone does not apply the strategy's far-edge-close cancellation rule.

Independent reproduction used the actual scanner, FVG engine and executor with an isolated fake feed/broker. A BUY basket had a still-pending 80% remainder. A paused-period M5 candle closed at **116.59**, below the far edge **116.60**. The scanner sent zero cancellation requests during pause, skipped that candle on resume, and sent zero after the next inside-zone candle. As a control, managing the skipped far-edge candle directly produced one removal of the owned remainder.

Recommended direction: continue management of already-submitted baskets over trustworthy newly closed bars while new candidates/confirmations remain paused. Resume must account for skipped maintenance bars before advancing the entry-eligibility watermark. Keep account ownership checks and the rule that cancellation removes only pending remainders. Add a regression for a far-edge breach during pause followed by a return inside the zone before resume.

### 3. Post-journal exception ? agrees with existing confirmed high-priority finding

This is the same durable-journal/post-send misclassification identified and reproduced as finding 3 in the Codex report. Retain **high priority**: an accepted order can leave the application's lifecycle permanently even though the broker retains SL/TP and symbol exposure prevents another basket. Recovery should adopt the durable journal without any blind resend.

### 4. Other-account baskets and repeated errors ? valid maintenance concern; suggested remedy needs care

Source inspection supports repeated reconciliation failures after switching to a different account. Do not simply drop a basket from lifecycle tracking. First fix the server-plus-login consent/journal boundary from Codex finding 1, then distinguish the current account's capacity from retained journals for other accounts, show account-unavailable state clearly, and rate-limit repeated events. Original orders must be recoverable when the account returns. This concern does not negate the confirmed same-login/different-server identity collision.

### 5. Rejected/alert-only baskets consume cap and cooldown ? policy observation

The counters are based on accepted baskets, including plans without successful execution. Existing replay follows the same broad accepted-basket policy. This is a policy choice, not a newly confirmed implementation defect. Changing the cap to count fills or successful sends would change semantics and needs a deliberate requirement.

### 6. Second pre-send check uses scan-start time ? source-supported availability concern

A tick captured more than five seconds after the scan-start time can look too far in the future to [app/fvg_execution.py:195](E:/VideCode/vc_trade/app/fvg_execution.py:195), causing rejection even when it is fresh at actual send time. The suggested fresh current clock at the final execution boundary is sensible. No timed broker-delay reproduction was run in this review, so this remains source inspection rather than an independently reproduced slow-broker case.

### 7. Placement checks differ between live and replay ? source-supported modeling limitation

Live rejects the complete basket when a pending limit violates placement/broker distance constraints at confirmation. Replay constructs levels without this live preflight check: [app/fvg_replay.py:150](E:/VideCode/vc_trade/app/fvg_replay.py:150). Align executable placement assumptions when updating replay. Claude's saved-baseline count of zero affected baskets out of 16 was not independently rerun here, and should not be treated as proof that future cases are impossible.

### Informational claims

Telegram messages are plans queued before broker submission; they do not prove successful placement. This is current behavior under the four-field alert specification, not a fix completed by this review. The exact predicted DST switch date and replay sensitivity statistics in Claude's report were not independently verified in this response; any broker clock-offset change needs observed verification rather than relying on an assumed date.

## Claims requiring qualification

Claude's general statement that historical confirmations cannot alert or submit is too broad. Codex already reproduced the delayed-healthy-scan case: a confirmation three hours old, but after the existing session watermark, was submitted. The watermark handles startup/restart/recovery boundaries; it does not supply a final confirmation-age or decision-time expiry check.

Claude's opt-in-isolation assurance also needs the server identity qualification. A login-only hash binds incompletely even though the feed detects server/account changes correctly.

The five Codex findings not shared with Claude's post-send finding remain unresolved: server identity binding, delayed historical confirmation, partial-fill cancellation race, invalid constituent aggregation, and legacy outcome expiry. No absence from Claude's lighter review overturns their existing reproductions.

## Evidence and next work

- [Sanitized runtime snapshot](E:/VideCode/vc_trade/.tmp/claude-review-20261007/runtime-sanitized.json).
- [Independent fake-broker/feed script](E:/VideCode/vc_trade/.tmp/claude-review-20261007/reproduce-claude-findings.py) and [results](E:/VideCode/vc_trade/.tmp/claude-review-20261007/additional-findings-reproduction.json).
- [Source unchanged check](E:/VideCode/vc_trade/.tmp/claude-review-20261007/source-unchanged-check.json): 90 inventoried source files, zero changes.

No full test-suite rerun was needed for unchanged application code. The earlier **336 passing existing tests** remain the last completed suite result; the two new checks are reviewer reproductions, not newly added regression tests. No terminal was initialized, no real orders were placed or canceled, and no Telegram message was sent by these reproductions.

Recommended combined scope: fix the three high-priority Codex execution defects first, then the cancellation race, paused-basket maintenance, spread-distance eligibility, candle validation and legacy expiry. Claude is waiting for a separately approved implementation task; none was published by this review response.
