// node --test frontend/tests : FVG planned-risk currency display and the active strategy's last-closed caption
// (app/static/fvg-display.js, the functions app.js calls). Synthetic values only.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const D = require("../../app/static/fvg-display.js");
const APP = readFileSync(new URL("../../app/static/app.js", import.meta.url), "utf8");
const fmtT = (s) => (s ? `T(${s})` : "—");

test("USD account: planned loss is shown as USD unchanged", () => {
  assert.equal(D.legRisk(3.33, "USD"), "$3.33 USD");
  assert.equal(D.legRisk(3.3, "usd"), "$3.30 USD");
});

test("USC cent account: 333.33 cents is about $3.33 USD, never $333.33", () => {
  const text = D.legRisk(333.33, "USC");
  assert.equal(text, "$3.33 USD (333.33 USC)");
  assert.ok(!text.includes("$333.33"));
});

test("unknown or unsupported currency is never converted or labelled USD", () => {
  for (const ccy of [undefined, null, "", "  "]) {
    const text = D.legRisk(333.33, ccy);
    assert.equal(text, "333.33 account units (currency unknown, not converted)");
    assert.ok(!text.includes("$") && !text.includes("USD"));
  }
  const eur = D.legRisk(12.5, "EUR");
  assert.equal(eur, "12.50 EUR (no USD conversion)");
  assert.ok(!eur.includes("$"));
});

test("missing or invalid amounts render nothing (no NaN, no fabricated zero)", () => {
  for (const v of [undefined, null, NaN, Infinity, "3.33"]) assert.equal(D.legRisk(v, "USD"), null);
});

test("actual lot-rounded leg losses are shown as given, not forced to one third of the budget", () => {
  assert.equal(D.legRisk(3.1, "USD"), "$3.10 USD");
  assert.equal(D.legRisk(298.0, "USC"), "$2.98 USD (298.00 USC)");
});

test("FVG last-closed caption uses M5 + M15 readiness (warm-up and ready)", () => {
  const lc = { M5: "m5", H1: "h1" };
  const warm = D.lastClosed("fvg", lc, { m15_run: 12, required: 50, ready: false }, fmtT);
  assert.deepEqual(warm, { label: "Last closed M5 · M15 trend", value: "M5 T(m5) · 12/50 M15 (warm-up)" });
  const ready = D.lastClosed("fvg", lc, { m15_run: 64, required: 50, ready: true }, fmtT);
  assert.equal(ready.value, "M5 T(m5) · 64/50 M15 (ready)");
  assert.ok(!ready.label.includes("H1") && !ready.value.includes("H1"));
  assert.equal(D.lastClosed("fvg", lc, null, fmtT).value, "M5 T(m5) · —");
  assert.equal(D.lastClosed("fvg", undefined, {}, fmtT).value, "M5 — · —");
});

test("FastSweep keeps M5 · M15 and CRT keeps H1 / M5", () => {
  const lc = { M5: "m5", H1: "h1" };
  assert.deepEqual(D.lastClosed("fastsweep", lc, { m15_run: 50, required: 50, ready: true }, fmtT),
    { label: "Last closed M5 · M15 trend", value: "M5 T(m5) · 50/50 M15 (ready)" });
  assert.deepEqual(D.lastClosed("crt", lc, null, fmtT), { label: "Last closed H1 / M5", value: "H1 T(h1) · M5 T(m5)" });
  assert.equal(D.lastClosed(undefined, lc, null, fmtT).label, "Last closed H1 / M5");
});

test("app.js routes both display paths through these helpers", () => {
  assert.equal((APP.match(/VCFvgDisplay\.lastClosed\(/g) || []).length, 2); // status card and evidence panel
  assert.match(APP, /VCFvgDisplay\.legRisk\(p\.planned_loss, ex\.account_currency\)/);
  assert.ok(!/money\(p\.planned_loss\)/.test(APP), "raw account units must not go to the USD formatter");
  assert.ok(!APP.includes("Last closed H1"), "timeframe captions live in fvg-display.js only");
});
