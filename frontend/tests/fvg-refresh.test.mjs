// node --test frontend/tests : FVG Engines record-refresh feedback (review 20261008-163422 #3) and the Guide's explicit
// missing-record selection (#2). The real scripts run in a VM with a fake document and a CONTROLLED fetch.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(path.join(here, "../../app/static/fvg-engines.js"), "utf8");
const require = createRequire(import.meta.url);
const Guide = require("../../app/static/fvg-guide.js");

/** Loads fvg-engines.js with a fetch whose every call returns a promise the test settles explicitly. */
function harness() {
  const busy = { on: false };
  const nodes = {
    "engines-section": { setAttribute: (k) => { if (k === "aria-busy") busy.on = true; }, removeAttribute: (k) => { if (k === "aria-busy") busy.on = false; } },
    "en-records-note": { textContent: "" },
  };
  const pending = [];
  const fetch = () => new Promise((resolve, reject) => pending.push({
    ok: (data) => resolve({ ok: true, status: 200, json: async () => data }),
    fail: (msg) => reject(new Error(msg)),
  }));
  const root = { document: { readyState: "loading", addEventListener() {}, getElementById: (id) => nodes[id] || null } };
  vm.runInNewContext(SRC, { self: root, fetch, Date, Promise, Error, Set, Object, JSON, Math, Number, String, Array });
  const tick = () => new Promise((r) => setTimeout(r, 0));
  return { E: root.VCEngines, note: () => nodes["en-records-note"].textContent, busy, pending, tick };
}

test("a failed first load shows a lasting failure and does not imply any records exist", async () => {
  const h = harness();
  const p = h.E.refreshFvg(true);
  assert.equal(h.busy.on, true);
  h.pending[0].fail("offline probe");
  await p;
  assert.match(h.note(), /^Records refresh failed .* \(offline probe\)\. No records have been loaded yet\.$/);
  assert.equal(h.busy.on, false);
});

test("failure after success keeps the failure and the last successful time; recovery clears it", async () => {
  const h = harness();
  let p = h.E.refreshFvg(true); h.pending[0].ok({ baskets: [], setups: [] }); await p;
  assert.match(h.note(), /^Records updated /);
  const okAt = h.note().replace("Records updated ", "").replace(/\.$/, "");
  p = h.E.refreshFvg(true); h.pending[1].fail("HTTP 503"); await p;
  assert.match(h.note(), /^Records refresh failed .* \(HTTP 503\)\. Showing records from /);
  assert.ok(h.note().endsWith(`Showing records from ${okAt}.`));
  p = h.E.refreshFvg(true); h.pending[2].ok({ baskets: [], setups: [] }); await p;
  assert.match(h.note(), /^Records updated /);
  assert.equal(h.busy.on, false);
});

test("overlapping requests: superseded successes and failures change nothing", async () => {
  const h = harness();
  const a = h.E.refreshFvg(true);
  const b = h.E.refreshFvg(true);       // supersedes a
  h.pending[1].ok({ baskets: [], setups: [] });
  await b;
  const afterB = h.note();
  assert.match(afterB, /^Records updated /);
  assert.equal(h.busy.on, false);
  h.pending[0].fail("late failure of the superseded request");
  await a; await h.tick();
  assert.equal(h.note(), afterB);       // the superseded failure did not overwrite current evidence
  const c = h.E.refreshFvg(true);
  const d = h.E.refreshFvg(true);       // supersedes c
  h.pending[3].fail("current failure");
  await d;
  const afterD = h.note();
  assert.match(afterD, /current failure/);
  h.pending[2].ok({ baskets: [], setups: [] });
  await c; await h.tick();
  assert.equal(h.note(), afterD);       // a superseded success does not hide the current failure
  assert.equal(h.busy.on, false);
});

test("Guide: an explicit missing key stays requested (no substitute); choosing a real record recovers", () => {
  const missing = Guide.selectionState({ missing_key: "K-old", selected: null, records: [{ key: "K-new" }] }, "K-old");
  assert.deepEqual(missing, { mode: "missing", key: "K-old" });
  const again = Guide.selectionState({ missing_key: "K-old", selected: null }, missing.key); // next refresh, same request
  assert.deepEqual(again, { mode: "missing", key: "K-old" });
  const recovered = Guide.selectionState({ selected: { record: { key: "K-m15" } } }, "K-m15");
  assert.deepEqual(recovered, { mode: "selected", key: "K-m15" });
  assert.deepEqual(Guide.selectionState({ selected: null, records: [] }, null), { mode: "none", key: null });
});
