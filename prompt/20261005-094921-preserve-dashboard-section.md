# Keep the current dashboard section after refresh

Task ID: 20261005-094921-preserve-dashboard-section
Delivery status: APPROVED FOR EXECUTION
User authorization: On 2026-10-05 the user explicitly instructed "tell claude when refresh don't back to overwrite", authorizing this specific refresh/Overview task to be sent to Claude.
Project root: E:\VideCode\vc_trade
Source prompt: `prompt/20261005-094921-preserve-dashboard-section.md`
Report path: `report/20261005-094921-preserve-dashboard-section-report.md`

## Goal and context

User instruction: "tell claude when refresh don't back to overwrite". Codex interprets "overwrite" as the existing Overview section and has stated this interpretation to the user: a browser refresh should keep the current dashboard section instead of jumping back to Overview.

The dashboard is a single scrolling page with an Alpine sidebar. frontend/src/index.template.html initializes selected to overview on every load. Sidebar links already use anchors: #overview, #chart-section, #signals-section, #setups-section, #replay-section, #system-section. Scroll occurs inside the app layout, so restoring only the highlighted sidebar may not restore the visible section.

The prior MT5 task is completed and reported. Current live state is MT5/XAUUSDc, scanner resumed, Telegram external delivery explicitly enabled by the user. Preserve that runtime state.

## Scope and relevant files

frontend/src/index.template.html is the page source; app/static/index.html is generated. app/static/app.js and a small local UI helper if needed; frontend/copy-assets.mjs only if required to include a helper. Keep this to refresh/navigation persistence; no redesign, strategy/backend/configuration changes, or chart-settings persistence expansion.

## Implementation plan

1. Read existing instructions and relevant navigation, scrolling and initialization code.
2. Restore a recognized current section on reload. Prefer the existing recognized URL anchor; if no recognized anchor is present, use a safely read browser-local remembered section. Default to Overview for a fresh visit with no valid remembered selection. Allowlist existing section identifiers and handle inaccessible browser storage without breaking the page.
3. Keep selected sidebar styling, aria-current and actual visible section aligned. Remember selection when navigating using sidebar, logo or Open market chart. Account for application-driven navigation to the chart if relevant.
4. Restore the intended section after layout initialization; subsequent periodic data polling must not scroll back to Overview. Keep existing anchors/deep links and normal browser navigation functional.
5. Rebuild using existing project-local frontend dependencies and build scripts. Edit the template and regenerate served HTML rather than only patching generated HTML.
6. Verify refresh behavior on desktop and mobile if available. Do not restart the working backend unless necessary; do not toggle scanner/Telegram or send test messages during this UI task.

## Acceptance criteria

- Navigate to Chart, Signals, Setups, Replay or System, refresh, and remain at that section with its sidebar item active.
- A recognized direct anchor opens the intended section and wins over a conflicting stored selection.
- A fresh browser state opens Overview. Invalid anchors/stored values and denied storage do not crash the UI.
- Periodic API refresh does not reset the selected section or scroll location.
- Existing mobile navigation and normal chart/dashboard functions still work.
- Live MT5, scanner and Telegram settings remain unchanged; no external messages are sent by validation actions.

## Validation

Run the existing frontend build and relevant existing frontend tests/syntax checks. For this small UI fix, prioritize actual browser checks of reload and section selection. If no browser is available, report that limitation and checks actually performed; do not claim visual or interaction tests passed. Keep caches, temporary artifacts and screenshots inside this project. No global installations. Verify targets before recursive file operations; never follow paths outside the project.

## Reply and stopping condition

Acknowledge receipt in report/20261005-094921-preserve-dashboard-section-progress.md. Claude implements; Codex plans and reviews. Write material questions/blockers to the exact final report path and stop dependent work.

Final report must include task ID, source prompt, outcome, changed files, actual validation and remaining issues. Publish it completely via a project-local temporary file and atomic rename where supported. Stop after reporting and await another separately authorized task.
