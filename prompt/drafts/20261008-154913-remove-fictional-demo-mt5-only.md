# Remove fictional demo features; make VC Signal MT5-only

Task ID: 20261008-154913-remove-fictional-demo-mt5-only
Delivery status: DRAFT — DO NOT EXECUTE
User authorization: pending — requires this task's own “send it”
Project root: E:\VideCode\vc_trade
Source prompt after approval: `prompt/20261008-154913-remove-fictional-demo-mt5-only.md`
Report path: `report/20261008-154913-remove-fictional-demo-mt5-only-report.md`
Progress path: `report/20261008-154913-remove-fictional-demo-mt5-only-progress.md`

## Goal and agreed scope

User: “one more task remove everything about demo i don't want demo”. Asked to distinguish fictional app mode from the connected broker account; user selected: “Remove the app’s fictional demo mode/data and make it MT5-only; keep the connected account”. Remove the product's fictional demo functionality and bundled sample data completely, rather than just hiding buttons. Continue the user's clean, minimal-text design.

The previous UI task `20261008-152656-fvg-engines-dashboard-ui` has published its COMPLETE report. Read that report and its clean-text clarification first; preserve the two engine panels, charts, interaction polish and useful disclosures. Only this task may be active after approval.

Current runtime is actual MT5 data from XAUUSD on MetaQuotes-Demo. This broker account is explicitly retained. Its account type and server name are genuine metadata, not the fictional demo feed. Preserve its execution policy and actual consent state. Do not turn real/contest accounts automatically ON, hide account type, rename the server or pretend that “MT5-only” means a funded account. The explicit dual-version consent remains an existing open item and is outside this cleanup.

## Exact removal and preservation boundaries

Remove from production:

- Fictional `DemoFeed`, simulated-clock/speed/restart branches and demo-specific scanner scheduling, startup/store selection and public state.
- The bundled `data/demo/xauusd_demo_m5.json`, production generator `app/demo_fixture.py`, production `app/data/demo.py`, and their production imports/constants. Test-only data/helpers may be relocated into `tests/` if needed for meaningful isolated regression coverage; production must not load or import them.
- Demo source choices and handlers in header, System setup, Replay UI/API/CLI; remove `/api/demo/restart` and demo-switch capability. Retain normal pause/resume and MT5 setup/reconnect behavior.
- Fictional Guide lessons, learning tab/player, lesson API and production lesson generators. Retain FVG Guide explanations of actual stored live/historical MT5 setups and baskets, with exact engine links and truthful pending/filled/unknown/partial states.
- Demo-specific product labels, banners, footer text, speed settings, sample instructions and documented demo commands. Preserve concise errors, accessibility and meaningful risk/account information.

Preserve:

- Actual connected MT5 account, exact symbol, terminal selection, UTC verification and server metadata; credentials and Telegram configuration.
- Strategy rules/versions, both engine state machines, order preflight/execution/reconciliation, $10 per basket/$20 planned concurrent risk, cooldown/caps/expiry and automatic execution policy/opt-in files.
- Existing MT5 stores, broker journals, orders, positions, historic user records, delivery logs and replay evidence. Do not wipe/reset a database or cancel exposure for this cleanup. Leave dormant old demo runtime stores/history untouched, inaccessible to the product; do not recursively purge `.tmp`, prompt/report history or unrelated files.
- Replay of actual MT5 history and the existing user-supplied CSV CLI path, with honest simulated outcome labels. Replay is offline analysis, not order execution. Do not replace demo with another packaged sample or invented market feed.
- Developer-only mocks/synthetic test fixtures necessary to test failures, watermarking and order handling safely. They are not a product demo feature. Never connect tests to the real MT5 account or Telegram.

## Relevant files and implementation plan

Inspect all production references before removal: `app/config.py`, `app/web.py`, `app/scanner.py`, `app/launcher.py`, `app/data/__init__.py`, `app/data/demo.py`, `app/demo_fixture.py`, `app/replay.py`, `app/fvg_guide.py`, `app/static/app.js`, `app/static/fvg-guide.js`, `app/static/fvg-engines.js`, `frontend/src/index.template.html`, `frontend/src/input.css`, `.env.example`, `README.md`, related launch scripts and tests. Update generated `app/static/index.html` / `app/static/dist/app.css` through the normal frontend build.

1. Capture nonsecret runtime/settings preservation evidence before editing. Inspect the latest files; do not overwrite previous tasks' uncommitted changes.
2. Make MT5 the sole runtime source and default. Remove demo-speed config parsing and fixture constants. Explicit requests/config for unsupported `demo` should fail clearly, rather than execute fictional data, silently fall back or mutate user configuration. A disconnected terminal must expose unavailable/empty market data with a concise error. Blank symbol remains unavailable until the user selects the exact broker symbol; never guess it.
3. Remove demo startup/routes, feed code and scanner scheduling. Adapt backend APIs/config to the MT5-only contract while keeping real MT5 behavior intact. Remove product-only fixture loading/generation. Keep CSV parsing and empirical historical replay behavior. Default replay source to MT5; reject old demo replay requests. Retired routes should have no mutating behavior and be absent from OpenAPI.
4. Remove fictional Guide lessons/API/player but retain live and historical evidence rendering, chart helpers actually used by it, exact record selection, Guide deep links from both engines and useful rule details. Repair stale learning-tab state/deep links so the Guide opens actual records or an honest empty state.
5. Clean every affected UI: remove Restart demo, Switch to demo, simulated-clock UI, source toggles/selectors, fictional lesson controls, fictional source badges and help text. Keep short MT5 status, real account metadata, setup controls and offline feedback. Update listeners, loading-button wrappers, null checks, source branches and navigation so there are no missing-element errors, dangling controls or broken saved views. Preserve hover/focus/pressed/loading feedback, motion, touch and reduced-motion behavior. Do not misrepresent existing broker-account execution defaults as explicit arming; any shorter label must explain its actual source in accessible Details/tooltips.
6. Migrate tests that depended on production DemoFeed/default Settings to explicit test-only injected fake feeds and isolated stores. Preserve meaningful assertions for disconnects, freshness/watermarks, duplicate prevention, risk, unknown/partial legs and source/account policy. Avoid weakening tests just to remove imports; delete only assertions exclusive to intentionally removed product functionality, replace with removal/MT5-only assertions.
7. Update current usage/docs/environment examples to MT5-only. Do not blanket replace the word “demo”: genuine broker account names/types, tests of account policy and immutable historical handoffs remain accurate. No new dependency, global install, commit or push needed.

## Acceptance criteria

- Normal startup and UI operate only on real MT5 data; no bundled fictional feed, sample fallback, simulated live clock or demo-speed setting remains in production.
- No fictional demo source or learning lesson can be selected, restarted, replayed or fetched via UI/API/CLI. Unsupported source values fail with no side effects. Guide remains useful for actual MT5 records, including when none exist.
- Overview, both engine panels, Chart, Signals, Setups, Guide, Replay and System load cleanly; inspect paths contain no fictional sample data and maintain concise layout. Real account identity/type remains truthful.
- Disconnected/no-symbol/no-record cases are empty/unavailable; never fabricated signals, prices or orders.
- Trading strategy, risk, consent/account policy, Telegram and existing broker exposure/history remain intact. Test fixtures are isolated from production entry points.
- Report lists exact files removed/relocated, retired API/config contracts and legitimate remaining “demo” references with their purpose.

## Validation and runtime application

- Run full backend suite in a fresh project-local pytest basetemp and full frontend tests/build, plus JS syntax checks. This spans backend/config/fixtures, so frontend-only checks are insufficient.
- Add focused tests for MT5 defaults, invalid demo config/source rejection, removed routes/lesson API, no disconnected fallback, real Guide data and preservation of broker demo-account execution policy and real-account consent requirements. Assert rejection causes no execution/settings/delivery mutations.
- Verify desktop and 390px light/dark layouts, navigation and console, both engines and Guide/Replay/System; use isolated injected mocks for offline/empty states, not the live broker. Save screenshots locally and clearly distinguish screenshots from live interaction validation.
- Search production code/templates/docs/launchers for residual fictional demo imports, endpoints and UI controls. Classify genuine broker metadata/test-only/historical matches instead of deleting blindly.
- Apply backend changes through the established local launcher if necessary: one controlled restart, no second concurrent scanner. Preserve existing exposure/reconciliation, use a fresh healthy-session watermark and never submit historical catch-up orders. Do not send test orders, cancel broker orders, switch/login accounts, toggle automatic execution or Telegram, or retry any denied consent action by another tool. Report a denied restart honestly if it occurs.
- Record before/after nonsecret runtime preservation and service health. Natural market evaluations may advance during the work; explain that rather than asserting identical counters.

Keep artifacts and caches inside this project. Before any removal/move, verify the resolved absolute targets stay within the named production/test locations, including symlink targets. Use native PowerShell file operations end to end; no blanket recursive demo/text-match deletion.

## Reply and stopping condition

Claude implements; Codex plans/reviews. Acknowledge in the exact progress file. If a material missing requirement or permission block prevents completion, report the action and stated reason; do not invent authorization. Publish the complete final report atomically with this task ID/source, outcome, files changed/removed, actual tests, unavailable checks and remaining issues. After reporting, stop and wait for the next separately approved task.
