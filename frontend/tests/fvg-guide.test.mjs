// node --test frontend/tests : FVG Guide pure helpers (step labels, lesson frame bounds, chart reveal without future bars).
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const G = require("../../app/static/fvg-guide.js");

const bar = (t, o, h, l, c, tf = "M5") => ({ t, o, h, l, c, tf, closed: true });

test("every step state has a text label and a non-colour mark", () => {
  for (const s of ["done", "waiting", "failed", "skipped", "unavailable"]) {
    const look = G.stepLook(s);
    assert.ok(look.text && look.mark && look.tone);
  }
  assert.equal(G.stepLook("bogus").text, "Not reached");
});

test("lesson frame index is clamped to the available frames", () => {
  assert.equal(G.clampFrame(-3, 5), 0);
  assert.equal(G.clampFrame(9, 5), 4);
  assert.equal(G.clampFrame(2, 5), 2);
});

test("the chart only draws the revealed M5 candles (no future candles)", () => {
  const m15 = [bar(0, 1, 2, 0.5, 1.5, "M15"), bar(900, 1.5, 3, 1.4, 2.9, "M15"), bar(1800, 2.9, 3.2, 2.2, 3.1, "M15")];
  const m5 = [bar(2700, 3, 3.1, 2.4, 2.5), bar(3000, 2.5, 3.3, 2.4, 3.2), bar(3300, 3.2, 3.4, 3.1, 3.3)];
  const spec = { m15, m5, revealed: 1, zone: { bottom: 2.0, top: 2.2 } };
  const L = G.layoutChart(spec, 800, 300);
  assert.equal(L.candles.length, 4);
  assert.ok(L.candles.every((c) => c.t <= 2700));
  assert.equal(G.layoutChart({ ...spec, revealed: null }, 800, 300).candles.length, 6);
  assert.equal(G.layoutChart({ m15: [], m5: [], revealed: 0 }, 800, 300).empty, true);
});

test("price scale is inverted (higher price higher on screen) and keeps the zone inside the plot", () => {
  const L = G.layoutChart({ m15: [bar(0, 1, 2, 0.5, 1.5, "M15")], m5: [], revealed: null, zone: { bottom: 3, top: 4 } }, 800, 300);
  assert.ok(L.y(4) < L.y(3));
  assert.ok(L.y(4) >= L.pad.t && L.y(0.5) <= 300 - L.pad.b);
});

test("right-margin price labels are spread apart and stay inside the plot", () => {
  const out = G.spreadLabels([{ y: 100, text: "a" }, { y: 101, text: "b" }, { y: 102, text: "c" }, { y: 295, text: "d" }, { y: 296, text: "e" }], 12, 14, 300);
  const at = out.map((o) => o.at);
  for (let i = 1; i < at.length; i++) assert.ok(at[i] - at[i - 1] >= 12 - 1e-9);
  assert.ok(at[0] >= 14 && at[at.length - 1] <= 300);
  assert.deepEqual(out.map((o) => o.y), [100, 101, 102, 295, 296]); // true price positions kept for leader lines
});

test("every step state, including partly done, has a label", () => {
  assert.equal(G.stepLook("partial").text, "Partly done");
});

test("formation candles of the M5 engine are drawn with M5 width, and every zone is inside the price range", () => {
  const abc = [bar(0, 1, 2, 0.5, 1.5, "M5"), bar(300, 1.5, 3, 1.4, 2.9, "M5"), bar(600, 2.9, 3.2, 2.2, 3.1, "M5")];
  const L = G.layoutChart({ m15: abc, m5: [], revealed: null, zones: [{ bottom: 5, top: 6 }, { bottom: -1, top: 0 }] }, 800, 300);
  const widths = L.candles.map((c) => c.w);
  const m15w = G.layoutChart({ m15: [bar(0, 1, 2, 0.5, 1.5, "M15")], m5: [], revealed: null }, 800, 300).candles[0].w;
  assert.ok(widths.every((w) => Math.abs(w - widths[0]) < 1e-9));
  assert.ok(L.y(6) >= L.pad.t && L.y(-1) <= 300 - L.pad.b);
  assert.ok(m15w > 0);
});
