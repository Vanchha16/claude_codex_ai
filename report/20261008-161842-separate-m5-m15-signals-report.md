# Claude report: separate M5 and M15 signals on the website and Telegram

Task ID: 20261008-161842-separate-m5-m15-signals
Source prompt: `prompt/20261008-161842-separate-m5-m15-signals.md`
Status: completed
Reported at: 2026-10-08 ~09:30Z

## Outcome

**Website.** In dual mode, Signals opens with two separate panels, **M15 Signals** and **M5 Signals**: M15 left and M5 right on desktop (matching the FVG Engines page), stacked at 390 px. Each panel has:
- its own side filter, latest signal, selection and bounded history (20 rows from a 30-record fetch);
- truthful empty, offline and refresh-failed notes.

The latest or selected signal shows:
- side, time and zone;
- a status from the execution journal only: "Alert only · no orders", "3 pending limits", "Partial · 1/3 accepted", "Unresolved · n/3 accepted", "Filled n/3" or "Refused · no order";
- the basket's Telegram status;
- its three planned legs (entry, SL, TP, RR), with lots, planned loss (USD/USC helper) and leg state from the journal only ("not sized" / "not submitted" when there is no journal);
- **Telegram message**: that basket only. It shows the exact queued text, or a preview labelled "not queued";
- **Explain in FVG Guide**, which opens the exact setup;
- **M15/M5 engine panel**, which focuses that engine on the FVG Engines page.

There is no combined feed, merged total or composite card.

Baskets whose stored provenance doesn't match a dual engine (no engine, or engine/version mismatch) appear only in a closed "Legacy / unclassified FVG baskets" disclosure. The CRT/FastSweep signal table is unchanged inside its own disclosure, "CRT / FastSweep signals (simulated outcomes · not broker fills)", which is collapsed once in dual mode.

**System.** The combined FVG basket table was replaced by separate **M15 baskets**, **M5 baskets** and (when present) **Legacy / unclassified baskets** lists. Each has "Open … Signals →", and each is fetched with its own engine filter. The account risk and day-cap summaries are unchanged.

**Telegram.** This was verified rather than rebuilt. Each accepted basket was already queued once via `Delivery.on_fvg_basket`, with the outbox `UNIQUE(signal_id, kind)` key giving per-basket-ID deduplication. The only change is the header line of dual messages, now e.g. `M5 FVG · XAUUSD · SELL · 3 planned limit entries`. The old header said "3 pending limits", which the alert can't know at queue time. Below the header come that basket's three existing entry blocks with unchanged spacing and precision. Simultaneous M15 and M5 baskets produce two independent messages. Consent, expiry, retry, UNKNOWN behaviour and the destination are unchanged. Historical queued or sent messages were not rewritten, and nothing was resent.

## Files changed

Nothing is committed or pushed.

- `app/web.py`: `GET /api/fvg` gains an optional `engine=M15|M5|legacy` filter.
  - It partitions by STORED engine plus engine version, before the limit, so one engine can't crowd out the other.
  - An invalid value returns 400; the unfiltered contract is unchanged.
  - Each basket gains `delivery` (`status`, `attempts`, `updated_at`, `valid_until`; no error text or secrets) and `message` (`{source: "queued", text}` from its own outbox row, else `{source: "preview", text}`).
- `app/store.py`: `outbox_for(ids, kind)`, a read-only lookup of each basket's own outbox row.
- `app/delivery.py`: the dual header now reads engine · symbol · side · "3 planned limit entries".
- `app/static/fvg-signals.js` (new): pure `slotOf`, `partition`, `signalStatus`, `legRows` and `keepSelection`; per-engine GET polling only while Signals is open; per-engine request generations so stale responses are ignored; refresh-failed notes; and in-place rendering that preserves selection, filter, focus and an open message.
- `app/static/app.js`: System per-engine basket lists via three engine-filtered GETs.
- `frontend/src/index.template.html`, plus the generated `app/static/index.html`: the Signals panels, the legacy and CRT/FastSweep disclosures, the System list container, and the script tag.
- `frontend/src/input.css`, plus the generated `app/static/dist/app.css`: signal detail and leg styles, a busy state, and the `@source` for the new script.
- `frontend/package.json` and the new `frontend/tests/fvg-signals.test.mjs`.
- New `tests/test_fvg_signals.py`.

## Message examples (isolated fictional data, from `tests/test_fvg_signals.py` and the mock)

```
M15 FVG · XAUUSD · BUY · 3 planned limit entries


1️⃣ First entry

📍 Entry: 4101.19
...
```

```
M5 FVG · XAUUSD · SELL · 3 planned limit entries


1️⃣ First entry

📍 Entry: 4120.01

🎯 TP: 4115.00

🛑 SL: 4121.22

⚖️ RR: 2.00
... (second and third entry blocks of the same basket only)
```

## Validation performed

- **Backend:**
  - `tests/test_fvg_signals.py` gives **3 passed**:
    - simultaneous M15 BUY and M5 SELL baskets give exactly two `fvg_basket` outbox rows; reprocessing adds none;
    - each text has its own header, exactly three entries and its own levels, never the other basket's; it never says "pending limits" or "accepted";
    - the live dual engines end to end (test fixture with fake delivery client) give two rows and two separate sends, with no extra rows after repeated polls;
    - API: the engine filter applies before the limit (M15 not starved by five newer M5 baskets), mismatched provenance goes to legacy, each basket's own queued vs preview message and delivery state are correct, an invalid engine returns 400, the unfiltered response is unchanged, and the GETs don't mutate stores.
  - **Full suite:** fresh basetemp `.tmp/pytest-sig-full`, **362 passed**. That is 359 before plus 3 new.
- **Frontend:** `npm.cmd test` gives **56 passed**; the 4 new tests cover provenance partition, journal-only status for every state, journal-only sizing and selection preservation. `npm.cmd run build` succeeds, and `node --check` passes on all `app/static/*.js`.
- **Restart:** one controlled launcher restart to load the backend changes (PID 45000), with no log errors.
  - Preserved: MetaQuotes-Demo (demo account), XAUUSD, dual version `…@f4b7f7a5`; automatic execution ON via the demo-account default with `armed_at` null; $10; Telegram ON; 0/4 today.
  - Fresh watermark 09:26:29Z, and all `config/*.json` hashes unchanged.
- **Live Signals, read-only:** "No M15 signals yet." and "No M5 signals yet.", because there are no real dual baskets yet. The other-strategy section is collapsed (`04`).
- **Isolated mock:** port 8016, test fixture feed, temp state, no Telegram token, FICTIONAL seeded baskets; now stopped. Screenshots are in `.tmp/signals-mock/screens/`, and the files whose names start with `MOCK` are mock screenshots, not live interaction.
  - Separate panels: M15 "Unresolved · 1/3 accepted" with an UNKNOWN leg; M5 "Filled 1/3" with "Telegram pending" and its exact queued text (`01`).
  - Filtering and selecting in M5 left M15 byte-identical; the M5 historical selection survived a poll; the legacy basket shows only in the legacy list.
  - System per-engine lists (`02`). Their "alert_only" status next to "submitted" execution is an artifact of my hand-seeded mock rows.
  - 390 px light (M15) and dark (M5): stacked, no page overflow, the legs table scrolls inside its frame (`03`).
  - No console errors.

## Checks not performed

- A real dual basket and its real Telegram message: none has occurred yet live, and no test messages or orders were sent, by instruction.
- A screen reader, and real reduced-motion or touch devices. The existing interaction and reduced-motion CSS applies to the new controls (native buttons and selects).

## Questions, missing requirements, or blockers

None for this task. The explicit dual-version consent remains the separate open item.

## Suggested next step

Codex reviews the `engine` filter contract, `outbox_for`, and the header wording "3 planned limit entries".
