// node --test frontend/tests : separate M15 / M5 signal lists (stored provenance, truthful status, journal-only sizing).
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const S = require("../../app/static/fvg-signals.js");

const V = (e) => `FVG-Immediate-${e}-v2-RR2@f4b7f7a5`;
const b = (id, engine, version, execution, extra = {}) => ({ id, engine, version, direction: "BUY", sl: 1, status: "orders_pending",
  legs: [{ n: 1, pct: 1, entry: 3, tp: 7 }, { n: 2, pct: 50, entry: 2.5, tp: 6 }, { n: 3, pct: 80, entry: 2.2, tp: 5 }], execution, ...extra });
const ex = (...states) => ({ state: "submitted", legs: states.map((s) => ({ state: s, volume: 0.02, planned_loss: 3.3 })) });

test("lists are partitioned by STORED engine + version; anything else is legacy, never a dual signal", () => {
  const p = S.partition([b("a", "M15", V("M15")), b("b", "M5", V("M5")), b("c", undefined, "FVG-Trend-M15-M5-v1-RR2@8a49bace"),
    b("d", "M5", V("M15")), b("e", "H1", V("H1"))]);
  assert.deepEqual(p.M15.map((x) => x.id), ["a"]);
  assert.deepEqual(p.M5.map((x) => x.id), ["b"]);
  assert.deepEqual(p.legacy.map((x) => x.id), ["c", "d", "e"]);
});

test("status comes from the journal: planned/alert-only, pending, partial, unknown, filled, refused", () => {
  assert.equal(S.signalStatus(b("x", "M5", V("M5"), { state: "not_submitted" }, { status: "alert_only" })).label, "Alert only · no orders");
  assert.equal(S.signalStatus(b("x", "M5", V("M5"), ex("pending", "pending", "pending"))).label, "3 pending limits");
  assert.equal(S.signalStatus(b("x", "M5", V("M5"), ex("pending", "rejected", "not_sent"))).label, "Partial · 1/3 accepted · 1 pending limit");
  assert.equal(S.signalStatus(b("x", "M5", V("M5"), ex("pending", "unknown", "not_sent"))).label, "Unresolved · 1/3 accepted · 1 pending limit");
  assert.equal(S.signalStatus(b("x", "M5", V("M5"), ex("filled_open", "pending", "pending"))).label, "Open 1/3 · 2 pending limits");
  assert.equal(S.signalStatus(b("x", "M5", V("M5"), ex("rejected", "not_sent", "not_sent"))).label, "Refused · no order");
  assert.equal(S.signalStatus(b("x", "M5", V("M5"), null, { status: "planned" })).label, "Outcome unresolved");
});

test("lots and planned loss only from the journal; planned levels from the basket", () => {
  const rows = S.legRows(b("x", "M15", V("M15"), ex("pending")));
  assert.equal(rows[0].volume, 0.02);
  assert.equal(rows[1].volume, null);
  assert.equal(rows[1].state, "not sized");
  assert.equal(rows[2].sl, 1);
  assert.equal(S.legRows(b("y", "M15", V("M15"), { state: "not_submitted" }))[0].state, "not submitted");
});

test("each list keeps its own selection across refreshes", () => {
  const list = [{ id: "n" }, { id: "o" }];
  assert.equal(S.keepSelection("o", list), "o");
  assert.equal(S.keepSelection("gone", list), "n");
  assert.equal(S.keepSelection(null, []), null);
});

test("only legs pending NOW count as pending limits; terminal outcomes are named (review 20261008-163422 #1)", () => {
  const st = (...states) => S.signalStatus(b("x", "M15", V("M15"), ex(...states)));
  assert.deepEqual(st("cancelled", "cancelled", "cancelled"), { label: "Cancelled · no fill", tone: "light" });
  assert.deepEqual(st("expired", "expired", "expired"), { label: "Expired · no fill", tone: "light" });
  assert.equal(st("cancelled", "expired", "expired").label, "Cancelled/expired · no fill");
  assert.equal(st("pending", "cancelled", "expired").label, "1 pending limit · 1 cancelled · 1 expired");
  assert.equal(st("closed_tp", "expired", "expired").label, "Closed 1/3 · 2 expired");          // no open exposure claimed
  assert.equal(st("closed_tp", "closed_sl", "closed_other").label, "Closed 3/3");
  assert.equal(st("closed_tp", "rejected", "not_sent").label, "Partial · 1/3 accepted · Closed 1/3");
  assert.equal(st("pending", "rejected", "not_sent").tone, "warning");
  assert.equal(st("filled_open", "cancelled", "expired").label, "Open 1/3 · 1 cancelled · 1 expired");
  assert.equal(st("partially_filled", "pending", "pending").label, "Open 1/3 · 2 pending limits");
  assert.equal(st("sending", "not_sent", "not_sent").label, "Unresolved · 0/3 accepted");
  for (const states of [["cancelled", "cancelled", "cancelled"], ["expired", "expired", "expired"], ["pending", "cancelled", "expired"]]) {
    const t = S.legTally(states.map((state) => ({ state })));
    assert.equal(t.pending, states.filter((x) => x === "pending").length);
    assert.ok(!/3 pending/.test(st(...states).label));
  }
});
