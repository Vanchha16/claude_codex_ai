// node --test frontend/tests : stored stop provenance line (task 20261009-103608); display only, stored values only.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const D = require("../../app/static/fvg-display.js");
const p = (v) => Number(v).toFixed(2);

test("a moved spread-aware stop names its base stop, tick count and measured spread", () => {
  const s = D.stopNote({ policy: "spread_aware", base_sl: 4172.66, sl: 4172.64, spread: 0.49, moved_ticks: 2 }, p);
  assert.match(s, /moved 2 ticks outward from 4172\.66/);
  assert.match(s, /spread \(0\.49\) \+ 1 tick/);
  assert.match(D.stopNote({ policy: "spread_aware", base_sl: 1, spread: 0.3, moved_ticks: 1 }, p), /moved 1 tick outward/);
});

test("no move, a recorded note, fixed policy and missing data", () => {
  assert.equal(D.stopNote({ policy: "spread_aware", base_sl: 1, sl: 1, spread: 0.2, moved_ticks: 0 }, p),
    "Spread-aware stop: no move needed at spread 0.20.");
  assert.equal(D.stopNote({ policy: "spread_aware", moved_ticks: 0, spread: null, note: "spread 0.60 above the 0.50 maximum: not adjusted" }),
    "Stop: spread 0.60 above the 0.50 maximum: not adjusted.");
  assert.equal(D.stopNote({ policy: "fixed", base_sl: 1, sl: 1, spread: null, moved_ticks: 0 }), null);
  assert.equal(D.stopNote(null), null);
  assert.equal(D.stopNote(undefined), null);
  assert.equal(D.stopNote({ moved_ticks: 3 }), null); // never claims a move without the stored base stop and spread
});

const G = require("../../app/static/fvg-guide.js");

test("Guide rules: the dual stop rule comes from the server's per-engine scope text", () => {
  const cfg = { sl_buffer_ticks: 2 };
  const same = "spread-aware: 2 ticks beyond the far edge, moved further outward by whole ticks when needed";
  assert.equal(G.stopRule(cfg, { stop_policy: { M15: same, M5: same } }), `common stop for both engines: ${same}`);
  assert.equal(G.stopRule(cfg, { stop_policy: { M15: "fixed: 2 ticks beyond the far edge", M5: same } }),
    `common stop: M15 fixed: 2 ticks beyond the far edge; M5 ${same}`);
  assert.equal(G.stopRule(cfg, {}), "common stop 2 ticks beyond the far edge"); // older server without the scope
});
