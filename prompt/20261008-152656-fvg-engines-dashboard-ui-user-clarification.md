# User clarification: clean dashboard, minimal visible text

Document type: USER CLARIFICATION FOR THE ACTIVE APPROVED TASK — not a new task or a request to repeat completed work.
Applies to task: 20261008-152656-fvg-engines-dashboard-ui
Source of implementation authorization: `prompt/20261008-152656-fvg-engines-dashboard-ui.md`
Existing progress path: `report/20261008-152656-fvg-engines-dashboard-ui-progress.md`
Existing final report path: `report/20261008-152656-fvg-engines-dashboard-ui-report.md`
User authorization: On 2026-10-08, while this task was acknowledged and implementing, the user explicitly instructed: "don't add many text on website let implement and clean it". Apply this clarification within the same active UI task. No additional send-it is required for this direct user steering.

## Apply throughout the dashboard

Keep the website clean and visually led. Favor charts, concise status chips, compact numbers and meaningful controls. Remove redundant introductory paragraphs, repeated descriptions, duplicate legends and prose explaining obvious controls from normal dashboard views. Do not surface implementation details, internal version/hash names or lengthy technical reasons in the main UI; retain them in appropriate expanded technical details where useful.

The FVG Engines page should open with a compact context/status header and two clear M15/M5 cards. Each card's default visible content should prioritize its chart, short status, readiness count/progress, concise trend/ATR, relevant zone or no-FVG label, and compact basket/leg state. Use at most one short next-action/rejection sentence when it materially explains why no order exists. Keep detailed timestamps, qualification checks, per-leg sizing explanation and history compact or expandable, without concealing their availability.

Move longer strategy/rule explanations into FVG Guide or clearly labelled Details/Rules disclosures, CLOSED BY DEFAULT. Keep complete learning/rule material available on demand rather than deleting it. Prefer a single concise label/link to repeated explanation paragraphs.

Hover, click and motion should help users discover real details. Tooltips are short; necessary information is available through focus/tap/expanded details as well. Do not make essential information hover-only. Keep native labels, accessibility names, clear empty/error/stale states and the existing explicit execution-control consent semantics intact.

Retain the agreed two engine charts, real data, own-timeframe status, truthful pending-versus-filled/unknown counts, risk labels ($10 per basket/up to $20 planned total when these are actual configured values), and useful interactions. A clean default must not hide an execution/account/disconnection error or pretend a ready engine has a signal. No trading/risk/consent changes are authorized by this clarification.

Do not stop implementation to request approval for this styling/content adjustment, create another implementation task, or self-dispatch follow-ups. Continue the current task, acknowledge this clarification in its existing progress/final report, and include desktop/mobile evidence of the uncluttered default views with details still reachable.
Published at: 2026-10-08T08:46:19.2932874Z
