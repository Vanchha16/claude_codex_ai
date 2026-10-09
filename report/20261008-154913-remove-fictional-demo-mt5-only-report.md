# Claude report: remove fictional demo features; VC Signal is MT5-only

Task ID: 20261008-154913-remove-fictional-demo-mt5-only
Source prompt: `prompt/20261008-154913-remove-fictional-demo-mt5-only.md`
Status: completed
Reported at: 2026-10-08 ~09:15Z

## Outcome

The app's fictional demo mode is gone from production. That covers the fixture feed, the simulated clock and demo speed, demo startup and store selection, the demo switch and restart, the demo replay source, and the fictional Guide lessons, together with their API and player. VC Signal now runs **only on the real MT5 terminal**.

An explicit `demo` value now fails clearly and has no side effects:
- from the environment or `config/local_settings.json`, it raises `ConfigError` with an "MT5-only" message and the file is not rewritten;
- the dashboard setup save returns 400 and writes nothing;
- `Workstation.start("demo")` raises before stopping anything;
- the replay API returns 400, and the replay CLI rejects it as an invalid choice.

The connected **MetaQuotes-Demo broker account is retained unchanged**. Its account type, server name, demo-account execution default, explicit-consent rules for real and contest accounts, risk, Telegram, journals and stores are all untouched. The FVG Engines page, the Guide's real-record view (exact engine links; truthful pending, filled, unknown and partial states), the interaction polish and the clean layout are preserved.

## Files removed, relocated or retired

These moves into `tests/` used PowerShell `Move-Item` with checks that each target is inside the project and not a link:
- `app/data/demo.py` → `tests/fixture_feed.py`. It is now the test-only `FixtureFeed` (presented as an MT5-type feed with no MT5 module, so it can't trade), plus `OfflineFeed` and `load_fixture`.
- `app/demo_fixture.py` → `tests/fixture_gen.py` (`python -m tests.fixture_gen`).
- `app/scenarios.py` → `tests/scenarios.py`.
- `data/demo/xauusd_demo_m5.json` → `tests/data/xauusd_fixture_m5.json`. Its content is unchanged; its internal `demo_*` keys and `DEMO-XAUUSD` symbol are now test-only data.
- The empty `data/demo/` and `data/` folders were removed. This was a literal-path, non-recursive removal, done only after confirming they were empty.

Production code no longer imports any of these, and a test enforces that.

**Retired contracts:**
- `GOLD_DEMO_SPEED` and `Settings.demo_speed` are removed; an old value in `.env` is ignored.
- `DEMO_FIXTURE` is removed.
- `data_mode` defaults to `mt5`, and `demo` is refused.
- `POST /api/mode` (the demo/MT5 switch), `POST /api/demo/restart` and `GET /api/fvg/guide/lessons` are removed. The app has no OpenAPI schema (`openapi_url=None`).
- The `demo` key is gone from `/api/state`.
- The replay API accepts `source` = `mt5` (run and results) or `csv` (results), and defaults to `mt5`.
- `python -m app.replay --source` accepts `mt5` or `csv` and defaults to `mt5`; `load_fixture` was removed from production.
- `Delivery(..., source=)` is now a required keyword. The app always passes `mt5`; tests pass a non-MT5 label, which never touches the live opt-in.

## Other changed files

- **Backend:**
  - `app/config.py` (MT5-only plus the `DEMO_REMOVED` message);
  - `app/web.py`: MT5-only start and store selection, routes removed, state and replay changes, and the default feed factory now resolved at call time so tests can safely replace it;
  - `app/scanner.py`: the simulated-clock loop is removed, and the scheduler is MT5 only;
  - `app/replay.py`;
  - `app/fvg_guide.py`: the lesson generators and unused imports are removed, and real record views are kept;
  - `app/engine.py` and `app/fastsweep_live.py`: the `DEMO-` signal-ID prefix branch is removed;
  - `app/delivery.py`, `app/outcomes.py`, `app/models.py`, `app/data/__init__.py`, `app/data/base.py` (comments, labels and the default);
  - `.env.example`, `README.md`, and the `gold.cmd` usage line.
- **Frontend**, plus the generated `index.html` and `dist/app.css`:
  - `index.template.html`: removed the "Restart demo" and "Switch to demo/MT5" header buttons, the System data-source select, the Replay source select (now an "MT5 history" chip), the Guide learning tab, player and fictional ladder, and the fictional captions and footer text;
  - `app.js`: demo branches, handlers and loading-wrapper entries removed; delivery confirmation is now live-only; Replay controls are MT5-only;
  - `fvg-guide.js`: the lesson player is removed; rules come from `/api/fvg/guide`, and `clampFrame` is kept for its existing test;
  - `fvg-engines.js`: the demo source label is removed; an offline state now reads "Engines not running: feed offline" instead of wrongly saying "legacy v1 active", a bug found during the visual checks; the broker default is labelled "demo-account default";
  - `market-chart.js`: demo labels removed.
- **Tests:**
  - new `tests/conftest.py`, an autouse safety net: the app's default feed factory becomes an offline fake in every test, so no test can reach a real terminal;
  - new `tests/test_mt5_only.py` (5 tests);
  - migrated tests use `FixtureFeed` / `fixture_factory` explicitly, and the API signal test drives the fixture clock and `scan_once` itself;
  - `test_api.py` asserts that the routes are gone, and that a `demo` setup, replay or lesson request changes nothing (it now uses a temp settings file);
  - `test_live_market.py` keeps its no-fallback and disconnected assertions;
  - lesson-only tests were deleted: 5 in `test_fvg_guide.py` and 1 in `test_fvg_dual.py`. Their endpoint checks now assert 404. The underlying rules (equal close, invalidation precedence, third-candle confirmation, success paths) remain covered by the engine and Guide record tests.

## Legitimate remaining "demo" references (kept on purpose)

- **Broker metadata:**
  - `app/data/mt5.py` `_ACCOUNT_TYPES` (`0: "demo"`);
  - `app/web.py` `_fvg_armed`, `_fvg_default_on_demo`, `account_type`, and the `"default (demo account)"` label;
  - `config/fvg_execution.json` `default_on_for_demo_accounts`;
  - the MetaQuotes-Demo server name (in `app/mt5_time.py` docs and the README time-offset notes);
  - the engines summary's "demo-account default" and the Guide rule text "demo-ACCOUNT default".
- **Rejection messages:** `DEMO_REMOVED` in `app/config.py` and `app/web.py`, plus the replay 400 text.
- **Test-only:** fixture keys and symbol, the `ExecutionPolicy(source="demo")` negative test, and the test names in `tests/test_mt5_only.py`.
- **Historical:** previous prompts and reports (immutable), and the dormant `.tmp/gold-signals/demo.sqlite` (left untouched and unused, as instructed).

## Validation performed

- **Backend:** with a fresh in-project basetemp (`.tmp/pytest-nodemo-final`), **359 passed**. That is 360 before, minus 6 lesson-only tests, plus 5 new MT5-only tests. Before the final fixes, the first run surfaced 21 failures, all from tests that relied on the demo default or on `Delivery`'s default source; they were fixed by explicit fakes and sources, not by weakening assertions. No intermittent failures recurred in these runs.
- **New focused tests** (`tests/test_mt5_only.py`):
  - MT5 defaults;
  - `demo` rejected from env and from a saved file, with the file left byte-identical;
  - the setup save and `start("demo")` refused with no stop, no write and no outbox;
  - the replay CLI has no demo source;
  - production never imports test fixtures, the demo files are gone, and the UI has no demo controls.
  - Broker demo-account and real/contest consent policy stays covered by the existing `test_fvg_review_fixes.py` tests, which pass.
- **Frontend:** `npm.cmd test` gives **52 passed**, `npm.cmd run build` succeeds, and `node --check` passes on all of `app/static/*.js`.
- **Residual search:** production `app/`, `frontend/src`, `*.cmd` and `.env.example` contain only the references classified above.
- **Restart:** one controlled `app.launcher restart`, which succeeded with no permission denial. New PID 19940; fresh session watermark 2026-10-08T09:09:28Z; no log errors since start.
- **Before/after runtime** (`.tmp/demo-removal/before-runtime.json`, `after-runtime.json`):

  | | Before | After |
  |---|---|---|
  | Mode | mt5 | mt5, with `data_label` "MetaTrader 5 terminal data (read-only)" and no `demo` key |
  | Account / symbol / version | MetaQuotes-Demo (demo), XAUUSD, dual `…@f4b7f7a5` | unchanged |
  | Feed / scanner | ok, running | ok, running, quotes fresh |
  | Automatic execution | ON, armed_by "default (demo account)", armed_at null, $10 | unchanged |
  | Telegram | ON | ON |
  | Baskets / today / setups | 0 / 0 of 4 / 14 | 0 / 0 of 4 / 14 |
  | Engines | — | M15 44/50 warming up, M5 133 ready (natural advance) |

  The six `config/*.json` SHA-256 prefixes are identical before and after, including `local_settings.json`, `fvg_execution.json` and `fvg_risk.json`.
- **Live HTTP checks:**
  - `/api/fvg/guide/lessons` returns 404;
  - `/api/replay?source=demo` returns 400;
  - the removed POST routes return 403 without a token (any POST does), and 404/405 with a token, per the tests.
- **Visual:** screenshots in `.tmp/demo-removal/screens/`.
  - **Live app** (dark, desktop, real MT5): Overview (`01`), Guide showing a real M5 record with no learning tab (`02`), and Replay with an "MT5 history" chip and the existing real replay evidence (`03`).
  - **Text scan of all eight views:** the only "demo" text is the broker account type and its demo-account default.
  - **Console:** no errors after a clean reload.
  - **Isolated offline mock:** port 8015, test-only `OfflineFeed`, temp state and settings, no Telegram token; now stopped. Overview "Disconnected", Engines and Guide at 390 px, light and dark, no page overflow, with an MT5 banner, empty charts and "No FVG setups have been recorded yet." (`04`). The Engines offline wording was fixed and re-checked (`05`).
  - These mock screenshots are visual-only, not live-trading interaction.

## Checks not performed

- Visual coverage was the screenshot set above. The Chart, Signals, Setups and System views were checked by DOM text scan on desktop, with no separate screenshots.
- A real `prefers-reduced-motion` setting and a physical touch device were not exercised. The CSS from the previous task is unchanged.
- Starting with a saved `data_mode: "demo"` on the real workstation was not tried. The user's file says `mt5`, and this path is covered by tests only.

## Questions, missing requirements, or blockers

None for this task. The explicit dual-version consent remains the separate open item; it was not touched.

## Suggested next step

Codex reviews the retired contracts and the test migration (`tests/conftest.py`, `tests/fixture_feed.py`, `tests/test_mt5_only.py`).
