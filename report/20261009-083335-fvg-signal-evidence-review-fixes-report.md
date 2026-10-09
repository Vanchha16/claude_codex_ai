# Claude report: FVG signal status, exact Guide links and record-refresh feedback

Task ID: 20261009-083335-fvg-signal-evidence-review-fixes
Source prompt: `prompt/20261009-083335-fvg-signal-evidence-review-fixes.md`
Review addressed: `report/20261008-163422-separate-signals-code-review.md` (findings 1–3, P2)
Status: completed
Reported at: 2026-10-09 ~01:50Z

## Outcome

All three review findings are fixed.

1. **Truthful signal status** (`app/static/fvg-signals.js`):
   - `signalStatus` now counts journal legs by their CURRENT state (`legTally`: pending, open, closed, cancelled, expired, refused, unresolved). Only legs that are `pending` now count as pending limits. Historical acceptance appears only in the partial/unresolved labels ("Partial · 1/3 accepted · …", "Unresolved · n/3 accepted · …").
   - Examples:
     - all cancelled: "Cancelled · no fill";
     - all expired: "Expired · no fill";
     - a mix: "Cancelled/expired · no fill";
     - pending + cancelled + expired: "1 pending limit · 1 cancelled · 1 expired";
     - closed TP + expired: "Closed 1/3 · 2 expired" (no open exposure implied);
     - filled_open + 2 pending: "Open 1/3 · 2 pending limits".
   - All three pending still gives "3 pending limits", and all refused still gives "Refused · no order".
   - Sizing and per-leg rows are unchanged and come from the journal only.
   - The FVG Engines broker chip had the same flaw, so I fixed it too: it now counts only current pending legs ("Pending limits (1 of 3 still pending)", or "No resting limit (cancelled/expired)").
2. **Exact Guide lookup** (`app/web.py`, `app/fvg_live.py`, `app/static/fvg-guide.js`):
   - `/api/fvg/guide?key=` resolves the key directly with `FvgStore.get_setup`, independent of the 30-record selector window. The selected setup is added to `records` once, only if absent.
   - The basket is resolved by the stored relationship with the new read-only `FvgStore.basket_for_setup(setup_key)`, a parameterized `json_extract(payload,'$.setup_key') = ?` query. This replaces the 500-basket scan, with no global limit increase.
   - An unknown explicit key returns `selected: null`, `missing_key`, a clear message and the real `records`; it never substitutes another setup. Requests without a key keep the same default selection as before.
   - Frontend: the new pure `selectionState(data, requestedKey)`. On a missing key the Guide hides the stale selected evidence, keeps the requested key through refreshes (so it doesn't drift to another record), shows "Requested setup not found: <key> …", and recovers when you pick a real record.
3. **Persistent refresh feedback** (`app/static/fvg-engines.js`):
   - `refreshFvg` writes the success note only after a successful response for the current request.
   - A failure persists until recovery, with separate failed-refresh and last-successful times: "Records refresh failed <t> (<error>). Showing records from <last ok>." On a failed first load it says "… No records have been loaded yet."
   - Superseded successes and failures change nothing: no evidence, status, timestamps or busy state. The busy state clears only for the current request. State and market polls never write this note.

## Files changed

Nothing is committed or pushed; other existing uncommitted work is untouched.

- `app/fvg_live.py`: new read-only `FvgStore.basket_for_setup`.
- `app/web.py`: `/api/fvg/guide` exact-key resolution, `missing_key`, and the direct basket relationship (also used for the default selection).
- `app/static/fvg-signals.js`: `legTally` and the new `signalStatus`.
- `app/static/fvg-engines.js`: the broker chip's current-pending count; `refreshFvg` and `recordsNote`.
- `app/static/fvg-guide.js`: `selectionState` and missing-key rendering, plus exports.
- Generated `app/static/index.html` and `app/static/dist/app.css` (normal build; no template changes).
- `frontend/package.json` (new test file added).
- Tests:
  - new `tests/test_fvg_guide_exact.py` and `frontend/tests/fvg-refresh.test.mjs`;
  - extended `frontend/tests/fvg-signals.test.mjs`. Three existing expectations were updated to the corrected wording: "Partial · 1/3 accepted · 1 pending limit", "Unresolved · 1/3 accepted · 1 pending limit", and "Open 1/3 · 2 pending limits" (previously "Filled 1/3");
  - extended `frontend/tests/fvg-engines.test.mjs`.

## Validation performed

- **Frontend:** `npm.cmd test` gives **62 passed**. New coverage:
  - status regressions: all cancelled, all expired, cancelled/expired, pending/cancelled/expired, closed/expired, all closed, closed/refused, partial acceptance, open/cancelled/expired, partially filled, sending/unresolved, and actual pending counts via `legTally`;
  - the broker chip's current-pending count;
  - `refreshFvg` running the REAL script in a VM with controlled, settle-on-demand fetch promises: failed first load, success then failure (failure kept with the last successful time), recovery, and two overlapping pairs settling out of order (a superseded failure doesn't overwrite a current success; a superseded success doesn't hide a current failure), plus busy cleanup;
  - Guide `selectionState`: a missing key stays requested across refreshes, and choosing a real record recovers.
- **Build and syntax:** `npm.cmd run build` succeeds, and `node --check` passes on all `app/static/*.js`.
- **Backend:**
  - `tests/test_fvg_guide_exact.py`: **2 passed**. It covers an old M15 setup displaced by 31 newer M5 setups, whose basket is displaced by 510 newer baskets, resolved with the exact key, engine M15 and the exact basket id, and listed in the selector exactly once. No-key default selection is unchanged. An unknown key is reported missing both on an empty store and on a populated one. Storage counts are unchanged, so the GETs are read-only.
  - **Full suite:** fresh in-project basetemps, 6 runs. **364 passed** in runs 3, 4 and 5, which is 362 before plus the 2 new tests.
  - **Intermittent failure, recurred:** runs 1 and 6 failed 2 tests. Run 6 named both: `tests/test_mt5_time.py::test_verified_server_offset_normalises_quotes_bars_and_ranges_exactly_once[2]` and `[3]`. Run 1 named `[2]` (the second name was not captured). This is the pre-existing intermittent MT5-time test reported in earlier tasks; that file is unchanged by this task and unrelated to it. Run 2's output was not captured.
- **Audit reproductions re-run** (Codex's scripts assert that the OLD defects exist):
  - `node .tmp/separate-signals-code-audit/probe-ui.cjs` now fails its first assertion: actual "Cancelled · no fill", expected the old "3 pending limits".
  - `python .tmp/separate-signals-code-audit/probe-guide.py` now fails at `assert actual != requested`: the requested M15 key is returned exactly.
  - Both outcomes mean the fixes hold. probe-guide wrote into its own existing isolated audit store (`.tmp/separate-signals-code-audit/state`).
- **Restart:** one controlled launcher restart (PID 33344).
  - MT5 is now connected (MetaQuotes-Demo, XAUUSD, dual `…@f4b7f7a5`), with the scanner running and no error.
  - Automatic execution is ON via the demo-account default; risk $10; Telegram ON; 0 baskets.
  - Config hashes are unchanged and the log shows no errors.
  - A live `/api/fvg/guide?key=XAUUSD|nope|x` returns `missing_key` with `selected: null`.
- **Browser, isolated mock:** port 8017, test fixture feed, temp store, no Telegram token, fictional records; now stopped. Screenshots are in `.tmp/fix-083335/screens/`.
  - Signals: M15 "Cancelled · no fill"; M5 "1 pending limit · 1 cancelled · 1 expired"; M5 history "Expired · no fill" (`01`).
  - The old M15 record's **Explain in FVG Guide** opened exactly that M15 record (31 newer M5 setups present).
  - `openRecord` with a missing key showed "Requested setup not found", hid the evidence, and kept the requested key through a refresh. Choosing a real record recovered (`02`).
  - Engines: a forced `/api/fvg` failure showed "Records refresh failed … Showing records from <last ok>". It persisted for 4 s while state polls kept updating the header, recovered to "Records updated …", and left `aria-busy` cleared.
  - The Chrome extension disconnected once mid-check; I reloaded and re-ran the checks cleanly.

## Checks not performed

- A real broker basket with cancelled/expired legs: none exists live. These were shown only with fictional mock data.
- Mobile and light-theme views of the changed labels: the layout is unchanged, so I didn't re-screenshot. A screen reader was not used.

## Questions, missing requirements, or blockers

None for this task.

- The intermittent `test_mt5_time` failure ([2] and [3]) continues to recur and could get its own investigation task.
- The explicit dual-version consent remains the separate open item.

## Suggested next step

Codex reviews the new status wording and the Guide's `missing_key` contract.
