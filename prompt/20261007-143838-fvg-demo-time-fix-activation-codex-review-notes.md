# Codex review observation during the approved activation task

Document type: INFORMATIONAL REVIEW NOTE - NOT A NEW TASK OR DISPATCH
Author: Codex
Parent approved task ID: 20261007-143838-fvg-demo-time-fix-activation
Authoritative source: `prompt/20261007-143838-fvg-demo-time-fix-activation.md`
Reply path remains: `report/20261007-143838-fvg-demo-time-fix-activation-report.md`

This note reviews the existing account-change/session-reset acceptance criterion. It does not authorize extra work, duplicate execution, arming, messages or additional live actions.

Current source observed at 14:45: MT5Feed.status detects server-name changes only. In a fake module, connect on account A, then change login to account B on the same server: feed.status remains ok/connected, so the scanner does not receive the unhealthy/reconnect transition required to open a new session watermark. The approved prompt explicitly requires account/broker or time-base changes to reset eligibility, including same-server changes.

Reproduction evidence (fake module only): `.tmp/fvg-demo-activation-codex-review/same-server-account-review.json`.

Please ensure this acceptance criterion is covered before the final report. A private server/account identity or fingerprint can detect the change without exposing logins in public status. Reconnect/new time base must cause the existing scanner session logic to set a new watermark. Preserve the feed's read-only role and existing account-bound opt-in behavior; this is not permission to arm or submit.
