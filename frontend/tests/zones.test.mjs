// node --test frontend/tests : FVG / IFVG / OB / BB detection in app/static/smc-zones.js (fictional fixture bars only).
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const Z = require("../../app/static/smc-zones.js");

const STEP = 300;
const T0 = 1_900_000_200; // multiple of 300
/** Build contiguous bars from [open, high, low, close] tuples. */
const mk = (rows, start = T0) => rows.map(([o, h, l, c], i) => ({ time: start + i * STEP, open: o, high: h, low: l, close: c }));
const run = (bars, tick = 0.01) => Z.detect(bars, { tick, step: STEP }).zones;
const of = (zones, type, dir) => zones.filter((z) => z.type === type && (!dir || z.dir === dir));

// ------------------------------------------------------------------ FVG
test("bullish FVG needs a gap of at least one tick (equality / sub-tick is not a gap)", () => {
  const base = [[99, 100, 98, 99.5], [99.5, 101.5, 99.4, 101.4]];
  const one = run(mk([...base, [101.4, 102, 100.01, 101.9]]));
  assert.equal(of(one, "FVG", "bull").length, 1);
  const z = of(one, "FVG", "bull")[0];
  assert.deepEqual([z.bottom, z.top, z.origin, z.active, z.end], [100, 100.01, T0, T0 + 2 * STEP, null]);
  assert.equal(z.available, T0 + 3 * STEP); // usable once the 3rd bar has closed
  assert.equal(of(run(mk([...base, [101.4, 102, 100.0, 101.9]])), "FVG").length, 0); // touching: no gap
  assert.equal(of(run(mk([...base, [101.4, 102, 100.005, 101.9]])), "FVG").length, 0); // half a tick: no gap
});

test("bearish FVG mirrors the bullish rule", () => {
  const zones = run(mk([[101, 102, 100, 100.5], [100.5, 100.6, 98.5, 98.6], [98.6, 99.99, 98, 98.2]]));
  const z = of(zones, "FVG", "bear")[0];
  assert.deepEqual([z.bottom, z.top], [99.99, 100]);
  assert.equal(of(run(mk([[101, 102, 100, 100.5], [100.5, 100.6, 98.5, 98.6], [98.6, 100, 98, 98.2]])), "FVG").length, 0);
});

test("tick precision survives floating point (3-digit symbol, gap of exactly 0.001)", () => {
  const zones = run(mk([[4141.1, 4141.208, 4140.9, 4141.0], [4141.0, 4142.0, 4140.95, 4141.9], [4141.9, 4142.5, 4141.209, 4142.4]]), 0.001);
  assert.equal(of(zones, "FVG", "bull").length, 1);
  const none = run(mk([[4141.1, 4141.208, 4140.9, 4141.0], [4141.0, 4142.0, 4140.95, 4141.9], [4141.9, 4142.5, 4141.2085, 4142.4]]), 0.001);
  assert.equal(of(none, "FVG").length, 0);
});

// ------------------------------------------------------------------ IFVG
const bullFvg = [[99, 100, 98, 99.5], [99.5, 101.5, 99.4, 101.4], [101.4, 102, 101, 101.9]]; // FVG [100, 101]

test("bullish FVG flips to a bearish IFVG only on a close strictly below its bottom", () => {
  const wick = run(mk([...bullFvg, [101.9, 102, 99, 100.5]]));          // wick through, close inside
  assert.equal(of(wick, "IFVG").length, 0);
  const atEdge = run(mk([...bullFvg, [101.9, 102, 99.5, 100]]));        // close exactly at the bottom
  assert.equal(of(atEdge, "IFVG").length, 0);
  const flip = run(mk([...bullFvg, [101.9, 102, 99.5, 99.99]]));
  const fvg = of(flip, "FVG", "bull")[0], ifvg = of(flip, "IFVG", "bear")[0];
  assert.equal(fvg.end, T0 + 3 * STEP);
  assert.equal(fvg.endReason, "inverted");
  assert.deepEqual([ifvg.bottom, ifvg.top, ifvg.origin, ifvg.parent], [100, 101, fvg.origin, fvg.id]);
  assert.equal(ifvg.active, T0 + 3 * STEP); // activates at the flip, not at the original formation
  assert.equal(ifvg.end, null);
});

test("IFVG ends on a close strictly beyond its far edge and never flips again", () => {
  const rows = [...bullFvg, [101.9, 102, 99.5, 99.99], [99.99, 101, 99.8, 101], [101, 101.6, 100.8, 101.5], [101.5, 101.6, 98, 98.5]];
  const zones = run(mk(rows));
  const ifvg = of(zones, "IFVG", "bear")[0];
  assert.equal(ifvg.end, T0 + 5 * STEP); // close 101 == top does not end it; 101.5 does
  assert.equal(ifvg.endReason, "invalidated");
  assert.equal(of(zones, "IFVG").length, 1); // no flip chain
});

// ------------------------------------------------------------------ OB / BB
// Pivot high 105 at index 2 (confirmed when index 4 closes); index 5 is the last bearish candle; index 6 breaks.
const obRows = [
  [100, 101, 99, 100.5], [100.5, 103, 100, 102.5], [102.5, 105, 102, 103], [103, 104, 101.5, 102], [102, 103, 100.5, 101],
  [101, 101.5, 100.2, 100.4], [100.4, 105.8, 100.3, 105.5],
];

test("bullish OB: close strictly above a confirmed pivot high; source = last bearish candle", () => {
  const zones = run(mk(obRows));
  const ob = of(zones, "OB", "bull");
  assert.equal(ob.length, 1);
  assert.deepEqual([ob[0].bottom, ob[0].top], [100.2, 101.5]);          // full range of index 5
  assert.deepEqual([ob[0].origin, ob[0].active, ob[0].pivot], [T0 + 5 * STEP, T0 + 6 * STEP, T0 + 2 * STEP]);
  const equalClose = obRows.slice(0, 6).concat([[100.4, 105.5, 100.3, 105]]); // close == pivot: no break
  assert.equal(of(run(mk(equalClose)), "OB").length, 0);
});

test("a pivot is consumed once: a second break does not create another OB", () => {
  const rows = obRows.concat([[105.5, 105.6, 103, 103.5], [103.5, 104, 102.8, 103], [103, 106, 102.9, 105.7]]); // above the consumed pivot (105), below the newer one (105.8)
  assert.equal(of(run(mk(rows)), "OB").length, 1);
});

test("no opposite-colour candle between pivot and break: no OB", () => {
  const rows = [[100, 101, 99, 100.5], [100.5, 103, 100, 102.5], [102.5, 105, 102, 103], [102, 104, 101.5, 103.5],
    [101, 103, 100.5, 102.8], [102.8, 104.9, 102.7, 104.8], [104.8, 106, 104.7, 105.9]];
  // index 2 (bearish? 102.5->103 is bullish) .. index 5 are all bullish; nothing bearish from the pivot on
  assert.equal(of(run(mk(rows)), "OB").length, 0);
});

test("bearish OB mirrors it (close strictly below a confirmed pivot low; last bullish candle)", () => {
  const mirror = obRows.map(([o, h, l, c]) => [200 - o, 200 - l, 200 - h, 200 - c]);
  const ob = of(run(mk(mirror)), "OB", "bear");
  assert.equal(ob.length, 1);
  assert.deepEqual([ob[0].bottom, ob[0].top], [98.5, 99.8]);
});

test("bullish OB closed strictly below its low becomes a bearish BB; the BB ends above its high", () => {
  const rows = obRows.concat([[105.5, 105.6, 100.1, 100.2], [100.2, 100.5, 99, 100.1], [100.1, 101.5, 100, 101.5], [101.5, 102, 101, 101.6]]);
  const zones = run(mk(rows));
  const ob = of(zones, "OB", "bull")[0], bb = of(zones, "BB", "bear")[0];
  assert.equal(ob.end, T0 + 8 * STEP);                   // 100.2 == low: no break; 100.1 < 100.2: break
  assert.equal(ob.endReason, "broken");
  assert.deepEqual([bb.bottom, bb.top, bb.origin, bb.parent, bb.active], [100.2, 101.5, ob.origin, ob.id, T0 + 8 * STEP]);
  assert.equal(bb.end, T0 + 10 * STEP);                  // 101.5 == top does not end it; 101.6 does
  assert.equal(of(zones, "BB").length, 1);
});

// ------------------------------------------------------------------ data hygiene
test("no pattern across a missing candle; invalid / out-of-order / forming bars are skipped", () => {
  const gap = mk(bullFvg);
  gap[2] = { ...gap[2], time: gap[2].time + STEP }; // one candle missing before the 3rd bar
  assert.equal(of(run(gap), "FVG").length, 0);
  const bad = mk(bullFvg);
  bad[1] = { ...bad[1], high: NaN };
  assert.equal(run(bad).length, 0);
  const dup = mk(bullFvg);
  const res = Z.detect([dup[0], dup[1], dup[1], dup[2]], { tick: 0.01, step: STEP });
  assert.equal(res.stats.invalid, 1);
  const forming = mk(bullFvg).map((b, i) => (i === 2 ? { ...b, forming: true } : b));
  assert.equal(run(forming).length, 0);
  assert.deepEqual(Z.detect([], { tick: 0.01, step: STEP }).zones, []);
  assert.deepEqual(Z.detect(null, { tick: 0.01 }).zones, []);
});

// ------------------------------------------------------------------ no lookahead, determinism, display cap
function walk(n, seed) {
  let s = seed, price = 2400;
  const rnd = () => ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648);
  const rows = [];
  for (let i = 0; i < n; i++) {
    const o = price, c = Math.round((o + (rnd() - 0.5) * 6) * 100) / 100;
    const h = Math.round((Math.max(o, c) + rnd() * 2) * 100) / 100, l = Math.round((Math.min(o, c) - rnd() * 2) * 100) / 100;
    rows.push([o, h, l, c]); price = c;
  }
  return mk(rows);
}

test("prefix property: nothing activates before its closed data exists, and history never rewrites", () => {
  const bars = walk(400, 7);
  const full = run(bars);
  for (const t of ["FVG", "IFVG", "OB", "BB"]) assert.ok(of(full, t).length > 0, `fixture exercises ${t}`);
  for (let k = 1; k <= bars.length; k += 7) {
    const last = bars[k - 1].time;
    const pre = run(bars.slice(0, k));
    for (const z of pre) assert.ok(z.active <= last && z.origin <= z.active);
    const byId = new Map(pre.map((z) => [z.id, z]));
    for (const z of full.filter((x) => x.active <= last)) {
      const p = byId.get(z.id);
      assert.ok(p, `zone ${z.id} known at the prefix`);
      assert.deepEqual([p.top, p.bottom, p.origin, p.parent], [z.top, z.bottom, z.origin, z.parent]);
      if (z.end !== null && z.end <= last) assert.equal(p.end, z.end);
      if (z.end === null || z.end > last) assert.equal(p.end, null);
    }
  }
});

test("deterministic, unique ids, and display cap keeps active zones first", () => {
  const bars = walk(600, 11);
  const a = run(bars), b = run(bars.map((x) => ({ ...x })));
  assert.deepEqual(a, b);
  assert.equal(new Set(a.map((z) => z.id)).size, a.length);
  const shown = Z.selectForDisplay(a, 10);
  for (const t of Z.TYPES) {
    const mine = shown.filter((z) => z.type === t);
    assert.ok(mine.length <= 10);
    const firstEnded = mine.findIndex((z) => z.end !== null);
    if (firstEnded >= 0) assert.ok(mine.slice(firstEnded).every((z) => z.end !== null));
  }
  const c = Z.counts(a);
  assert.equal(c.IFVG.total, of(a, "IFVG").length);
});

// ------------------------------------------------------------------ display selection (render-only)
test("display: newest active zones only by default-style options, never more than the cap", () => {
  const zones = run(walk(600, 11));
  for (const cap of [3, 5, 10]) {
    const shown = Z.selectForDisplay(zones, cap, { history: false });
    for (const t of Z.TYPES) {
      const mine = shown.filter((z) => z.type === t);
      const active = of(zones, t).filter((z) => z.end === null).sort((a, b) => b.active - a.active);
      assert.ok(mine.length <= cap && mine.every((z) => z.end === null));
      assert.deepEqual(mine.map((z) => z.id), active.slice(0, cap).map((z) => z.id)); // the most recent active ones
    }
  }
});

test("display: History fills the cap with the newest ended zones after the active ones", () => {
  const zones = run(walk(600, 11));
  const shown = Z.selectForDisplay(zones, 5, { history: true });
  for (const t of Z.TYPES) {
    const mine = shown.filter((z) => z.type === t);
    const act = of(zones, t).filter((z) => z.end === null).length;
    assert.equal(mine.length, Math.min(5, of(zones, t).length));
    assert.equal(mine.filter((z) => z.end === null).length, Math.min(5, act));
    const ended = mine.filter((z) => z.end !== null).map((z) => z.end);
    assert.deepEqual(ended, [...ended].sort((a, b) => b - a));
  }
});

test("display: selection never alters detection; legacy defaults (10, history) unchanged", () => {
  const bars = walk(600, 11);
  const before = JSON.stringify(run(bars));
  const zones = run(bars);
  Z.selectForDisplay(zones, 3, { history: false });
  Z.selectForDisplay(zones, 10, { history: true });
  assert.equal(JSON.stringify(zones), before);
  assert.deepEqual(Z.selectForDisplay(zones), Z.selectForDisplay(zones, 10, { history: true }));
});

test("display preference is bounded: 3/5/10 and a boolean history, else defaults (3, off)", () => {
  assert.deepEqual(Z.normalizeDisplay(null), { perType: 3, history: false });
  assert.deepEqual(Z.normalizeDisplay({ perType: 5, history: true }), { perType: 5, history: true });
  assert.deepEqual(Z.normalizeDisplay({ perType: 7, history: "yes" }), { perType: 3, history: false });
  assert.deepEqual(Z.normalizeDisplay({ perType: "10", history: 1 }), { perType: 3, history: false });
  assert.deepEqual(Z.normalizeDisplay("garbage"), { perType: 3, history: false });
});
