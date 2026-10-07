# TailAdmin admin dashboard and remaining reconnect correction

Task ID: 20261002-133945-tailadmin-dashboard
Delivery status: APPROVED FOR EXECUTION
User authorization: Browser-button approval. The user clicked "Send to Claude" in the local task panel for task 20261002-133945-tailadmin-dashboard at 2026-10-02T06:43:45.047Z, approving the reviewed draft prompt/drafts/20261002-133945-tailadmin-dashboard.md with SHA-256 7c25462d689c1ce9a47e5de333cecec389dcd192b8824a9951665d478c32a319.
Project root: E:\VideCode\vc_trade
Source prompt: prompt/20261002-133945-tailadmin-dashboard.md
Report path: `report/20261002-133945-tailadmin-dashboard-report.md`
Progress path: `report/20261002-133945-tailadmin-dashboard-progress.md`

## Goal and context

The user requests TailAdmin as the admin dashboard for the Gold Signal Workstation. Integrate the actual official free TailAdmin HTML edition with the existing FastAPI/HTML/JavaScript app. Retain all working signal-system features. First close the small remaining reconnection gap found in Codex review of the previous repair; this preserves the user's requirement to fix the three bugs first.

Read report/20261002-132805-gold-three-bug-fixes-report.md and report/20261002-133945-gold-fixes-codex-review.md. Codex independently ran 80 tests successfully and checked demo health. The two replay fixes are present; same-scan reconnect still fails the independent mock reproduction below.

## Prerequisite: complete the reconnect repair

In app/scanner.py:_ensure_connected, a disconnected status followed by a successful feed.connect() returns healthy before _scan marks _unhealthy. The existing watermark is reused. With a pending first fictional BUY, run tests.test_scanner.make/run to 06:09:30, advance the fixture clock to 2030-01-07T06:10:05, set the mock feed mode to mt5, make status return disconnected once and connect restore healthy immediately, then scan_once/process_due. Codex observed watermark_reset=false, signals_created=1 and mock_telegram_calls=1. No real MT5 or Telegram was used.

Preserve the unhealthy transition before reconnecting so the recovered healthy scan opens a new eligibility watermark, including reconnect that succeeds within that same scan. Historical confirmations must create no actionable signal, active entry, outbox or send. Add a regression for this reproduction and a control for a genuinely new post-recovery confirmation. Preserve tracking of existing positions, deduplication, pause/resume and all accepted strategy defaults.

## TailAdmin source and integration

Official HTML guide: https://tailadmin.com/docs/installation/html
Official free repository: https://github.com/TailAdmin/tailadmin-free-tailwind-dashboard-template
License: https://github.com/TailAdmin/tailadmin-free-tailwind-dashboard-template/blob/main/LICENSE

The HTML edition uses Tailwind CSS and Alpine.js and is appropriate to the existing frontend. Use real template components/assets rather than a lookalike branded as TailAdmin. Use the free edition and retain its MIT copyright/license notice with copied code. Record the upstream commit/version and adapted components in project documentation. Download/vendor only inside this project; keep dependencies and caches local, pin them in a lockfile if introducing a build. Use only components needed for this application. Follow existing repo instructions. If external download/build is denied, report the exact blocker without weakening permissions or silently substituting a different template.

Serve the finished assets locally through the current FastAPI app at http://127.0.0.1:8000/. A separate frontend development server should not be needed for normal gold.cmd start. Retain a reproducible project-local build command if necessary. Do not require CDN fonts/scripts/styles for normal dashboard use. Do not migrate to React/Next or rewrite the backend solely for this UI task.

Relevant files: app/static/index.html, app/static/styles.css, app/static/app.js, app/web.py where required for asset paths, frontend source/build configuration if needed, README.md, local third-party notices, and the scanner regression mentioned above.

## Dashboard behavior and design

- TailAdmin sidebar, top bar, cards, tables, forms and status styling, adapted to a focused gold signal workstation. Use clear typography, consistent spacing, restrained colors, and responsive behavior. Include light/dark theme switching and persist the choice locally.
- Sidebar sections: Overview, Signals, Setups, Replay, System. Real section navigation/anchors or small views are acceptable; all links must lead to useful functioning sections. Include a link to the existing task panel as a separate tool if useful, without rebuilding it.
- Keep demo/fictional versus MT5/live data clearly visible, with symbol, H1/M5 timeframes, quote age, spread, feed health and scanner state. Summary values must come from actual backend data; do not retain template sample revenue, profits, customers or invented performance numbers.
- Preserve Pause/Resume, Restart demo and mode switching behavior, including existing confirmations. Preserve external-delivery toggle and labeled test-message control, existing disabled/not-configured behavior, and explicit action requirements. No automatic external messaging.
- Preserve selectable chart with A range, B sweep extreme, frozen structure level, entry, SL and TP; keep chart resizing/labels legible in sidebar layouts and on small screens.
- Preserve Signals table: side, entry, SL, TP, R:R, UTC confirmation, simulated outcome, R and delivery status. Preserve direction/outcome filters, setup selection and full Telegram message preview.
- Preserve Setups lifecycle/status filter and reasons; replay development/holdout summary and run-demo-replay action; strategy configuration display and version; event log.
- Keep UNKNOWN delivery states, ambiguous outcomes and simulation limitations clearly labeled. Retain research/demo labels and the no-order-execution behavior. Use useful loading, empty and error states.
- Responsive desktop sidebar with working mobile drawer; usable at about 1440px and 390px widths. No page-wide overflow; wide tables may scroll in their containers. Keyboard-accessible navigation/controls with visible focus, sensible contrast and labels.
- Adapt app.js selectors/handlers as required; do not leave duplicate element IDs or obsolete bindings. Preserve existing session-token protections and API contracts.

## Scope boundaries

Other than the explicitly described reconnect fix, this is a UI integration. Do not add broker trade execution, MetaApi support, AI calls, credential setup, user accounts or public deployment. Do not read, copy, print or migrate .venv/.env secrets; credentials remain outside frontend assets and reports. Do not modify the separate task panel, unrelated projects, global configuration or security settings. Keep external delivery off for validation; use demo/mocks only.

## Acceptance and validation

1. The remaining same-scan reconnect regression passes and genuine post-recovery signals still work.
2. Actual official free TailAdmin components are integrated and attributed; provenance/build instructions are recorded.
3. All listed dashboard controls/data/chart/filters work through existing APIs. No decorative dead controls or fabricated metrics remain.
4. Desktop/mobile and light/dark layouts render legibly, with no broken assets or JavaScript errors.
5. The app runs through the normal launcher with locally built assets; demo healthy, Telegram disabled, no real messages or broker calls.

Run the full Python suite plus the new reconnect regression, using project-local unique temporary directories and no shared temp collisions. Run any required frontend production build and syntax/type checks applicable to the chosen stack. Browser-smoke-check navigation, theme, mobile drawer, filters, chart selection/resize, message preview, pause/resume, demo restart and demo replay. Verify disconnected/not-configured/empty states using mocks or offline data. Do not send a real test message or switch to a real MT5 terminal for this task. Browser screenshots may be saved inside .tmp for review; report any unavailable visual checks honestly. Avoid snapshot/unit tests that merely mirror decorative markup.

Restart the local demo if necessary to serve the implementation and report its actual URL/PID. Verify health and Telegram delivery off. Keep the task panel available. All dependencies, caches, test databases, artifacts and work must stay inside the project. Before recursive delete/move verify resolved targets stay within the intended directory and do not follow links outside it.

## Reply and stopping condition

Claude implements; Codex reviews. After approval acknowledge this exact task in its progress path. If material requirements or permissions block work, write the blocker/questions at the exact report path and stop dependent work.

Publish a complete final report via a project-local temporary file and rename, including task ID, source prompt, outcome, changed files, reconnect regression evidence, TailAdmin version/provenance/license, build/run instructions, actual tests/browser checks, local server state, screenshots if available and remaining limitations. Stop after reporting and wait for the next separately approved task.