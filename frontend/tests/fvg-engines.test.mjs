// node --test frontend/tests : FVG Engines view logic (independent M15/M5 evidence, honest states, selection, stale guard).
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const E = require("../../app/static/fvg-engines.js");

const V15 = "FVG-Immediate-M15-v2-RR2@f4b7f7a5", V5 = "FVG-Immediate-M5-v2-RR2@f4b7f7a5", V1 = "FVG-Trend-M15-M5-v1-RR2@8a49bace";
const rec = (engine, version, c, status, extra = {}) => ({ key: `XAUUSD|2026-10-08T0${c}:00:00+00:00|${version}`, engine,
  direction: "SELL", bottom: 4000, top: 4001, c_close: `2026-10-08T0${c}:15:00Z`, status, reason: null, ...extra });
const fmtT = (s) => `T(${s})`;

test("each engine sees only its own dual records; legacy v1 records never count as a dual FVG", () => {
  const setups = [rec("M15", V15, 1, "rejected"), rec("M5", V5, 2, "accepted"), rec(null, V1, 3, "expired"),
    rec("M5", V1, 4, "rejected") /* wrong version for the engine */];
  assert.deepEqual(E.recordsFor("M15", setups).map((r) => r.engine), ["M15"]);
  assert.deepEqual(E.recordsFor("M5", setups).map((r) => r.status), ["accepted"]);
  const baskets = [{ id: "FVG15-a", engine: "M15" }, { id: "FVG5-b", engine: "M5" }, { id: "FVG-legacy" }];
  assert.deepEqual(E.basketsFor("M15", baskets).map((b) => b.id), ["FVG15-a", "FVG-legacy"]); // legacy occupies M15
  assert.deepEqual(E.basketsFor("M5", baskets).map((b) => b.id), ["FVG5-b"]);
});

test("warm-up, ready without a gap, rejected and offline states are told apart (ready is not a signal)", () => {
  const warm = { readiness: { ready: false, run: 41, required: 50, ready_eta: "2026-10-08T10:30:00Z", next_close: "x" } };
  assert.equal(E.analysisState(warm, true).label, "Warming up");
  assert.equal(E.nextAction("M15", warm, { feedOk: true, fmtT }), "Warming up: 41/50 M15 candles · ready ~T(2026-10-08T10:30:00Z) if no gap.");
  const ready = { readiness: { ready: true, run: 125, required: 50, next_close: "2026-10-08T08:30:00Z" },
    last_evaluation: { c_close: "2026-10-08T08:25:00Z", gap: null } };
  assert.equal(E.analysisState(ready, true).label, "Watching for FVG");
  assert.equal(E.nextAction("M5", ready, { feedOk: true, fmtT }), "Ready · no FVG on the last M5 close.");
  const rejected = { readiness: { ready: true, run: 125, required: 50 },
    last_evaluation: { c_close: "c", gap: { direction: "BUY" }, reason: "trend_against" },
    last_setup: { c_close: "c", status: "rejected", reason: "trend_against" } };
  assert.equal(E.analysisState(rejected, true).label, "FVG rejected");
  assert.equal(E.nextAction("M5", rejected, { feedOk: true, fmtT }), "Last BUY gap rejected: against trend.");
  assert.equal(E.analysisState(ready, false).label, "Unavailable (feed offline)");
  assert.equal(E.nextAction("M5", ready, { feedOk: false, fmtT }), "Feed offline.");
  assert.equal(E.trendText({ ready: false, run: 3, required: 50 }), "Trend warming up");
  assert.equal(E.trendText({ ready: true, trend: "down (SELL gaps allowed)" }), "Trend down · SELL only");
  assert.match(E.nextAction("M15", { readiness: { ready: true }, slot: { basket: "FVG15-x", status: "partial" } }, { feedOk: true, fmtT }), /^Basket FVG15-x open/);
});

test("broker state: pending, partial, unknown, filled and alert-only are distinct and never 'no fill' when unresolved", () => {
  const b = (state, legs, extra = {}) => ({ id: "FVG5-x", status: "orders_pending", ...extra,
    execution: { state, legs: legs.map((s) => ({ state: s })) } });
  const slot = { basket: "FVG5-x", status: "orders_pending" };
  assert.equal(E.brokerState(null, null).label, "Slot free");
  assert.equal(E.brokerState(slot, b("submitted", ["pending", "pending", "pending"])).label, "Pending limits");
  assert.equal(E.brokerState(slot, b("partial", ["pending", "rejected", "not_sent"])).label, "Pending limits (1 of 3 accepted)");
  assert.equal(E.brokerState(slot, b("needs_reconciliation", ["pending", "unknown", "not_sent"])).label, "Outcome unresolved");
  assert.equal(E.brokerState(slot, b("submitting", ["sending", "not_sent", "not_sent"])).label, "Outcome unresolved");
  assert.equal(E.brokerState(slot, b("submitted", ["filled_open", "pending", "pending"])).label, "Filled exposure");
  assert.equal(E.brokerState(slot, b("not_submitted", [], { status: "alert_only" })).label, "Alert only (no orders)");
  const c = E.legCounts(b("needs_reconciliation", ["filled_open", "unknown", "not_sent"]));
  assert.deepEqual([c.accepted, c.filled, c.unresolved, c.notAccepted], [1, 1, 1, 1]);
});

test("leg rows come from the stored basket + journal; no journal means not sized / not submitted", () => {
  const basket = { sl: 4002, legs: [{ n: 1, pct: 1, entry: 4000.01, tp: 3996 }, { n: 2, pct: 50, entry: 4000.5, tp: 3997 }],
    execution: { state: "submitted", legs: [{ volume: 0.02, planned_loss: 3.3, state: "pending", ticket: 9 }] } };
  const rows = E.legRows(basket);
  assert.equal(rows[0].volume, 0.02);
  assert.equal(rows[0].details.ticket, 9);
  assert.equal(rows[1].volume, null);
  assert.equal(rows[1].stateText, "not sized / not submitted");
  assert.equal(rows[1].sl, 4002);
});

test("rule checks claim only what the stored first failure proves", () => {
  const states = (r) => E.ruleChecks(r).map((c) => c.state);
  const trend = states({ status: "rejected", reason: "trend_against" });
  assert.deepEqual(trend.slice(0, 4), ["passed", "passed", "failed", "not_evaluated"]);
  assert.ok(trend.slice(3).every((s) => s === "not_evaluated"));
  const cap = states({ status: "rejected", reason: "daily_cap" });
  assert.deepEqual(cap, ["passed", "passed", "passed", "passed", "passed", "passed", "passed", "passed", "failed"]);
  assert.ok(states({ status: "accepted" }).every((s) => s === "passed"));
  assert.ok(states({ status: "rejected", reason: "something_new" }).every((s) => s === "unavailable"));
  assert.ok(states(null).every((s) => s === "unavailable"));
});

test("selection survives refreshes; a vanished record falls back to the default; stale responses are ignored", () => {
  const recs = [{ key: "a" }, { key: "b" }];
  assert.equal(E.keepSelection("b", recs, "a"), "b");
  assert.equal(E.keepSelection("gone", recs, null), "a");
  assert.equal(E.keepSelection(null, [], null), null);
  const g = E.latest();
  const first = g.next(), second = g.next();
  assert.equal(g.current(first), false);
  assert.equal(g.current(second), true);
});

test("the setup key gives A's open time and the engine version", () => {
  const k = E.parseKey(`XAUUSD|2026-10-08T07:45:00+00:00|${V5}`);
  assert.equal(k.a_open, "2026-10-08T07:45:00+00:00");
  assert.equal(k.version, V5);
});

test("broker chip counts only legs pending NOW (cancelled/expired are no longer resting) (review 20261008-163422 #1)", () => {
  const b = (legs) => ({ id: "FVG5-x", status: "orders_pending", execution: { state: "submitted", legs: legs.map((s) => ({ state: s })) } });
  const slot = { basket: "FVG5-x", status: "orders_pending" };
  assert.equal(E.brokerState(slot, b(["pending", "cancelled", "expired"])).label, "Pending limits (1 of 3 still pending)");
  assert.equal(E.brokerState(slot, b(["cancelled", "cancelled", "expired"])).label, "No resting limit (cancelled/expired)");
  assert.equal(E.brokerState(slot, b(["pending", "pending", "pending"])).label, "Pending limits");
});
