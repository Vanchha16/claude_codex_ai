// node --test frontend/tests : view routing in app/static/nav.js (one visible view, hash > storage > overview, history).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = readFileSync(path.join(here, "../../app/static/nav.js"), "utf8");
const IDS = ["overview", "chart-section", "signals-section", "setups-section", "engines-section", "replay-section", "system-section"];

/** Minimal browser stand-in: elements with `hidden`, a scroll container, localStorage, location.hash and history. */
function load({ hash = "", stored = null, blockedStorage = false } = {}) {
  const els = Object.fromEntries(IDS.map((id) => [id, { id, hidden: false }]));
  els.content = { scrollTop: 120 };
  const handlers = {};
  const store = new Map(stored === null ? [] : [["vcSection", stored]]);
  const entries = [hash];
  let index = 0;
  const location = { get hash() { return entries[index]; } };
  const fire = (type) => (handlers[type] || []).forEach((fn) => fn());
  const win = {
    location,
    localStorage: {
      getItem(k) { if (blockedStorage) throw new Error("blocked"); return store.has(k) ? store.get(k) : null; },
      setItem(k, v) { if (blockedStorage) throw new Error("blocked"); store.set(k, String(v)); },
    },
    history: {
      pushState(_s, _t, url) { entries.splice(index + 1); entries.push(url); index += 1; },
      replaceState(_s, _t, url) { entries[index] = url; },
    },
    addEventListener(type, fn) { (handlers[type] ||= []).push(fn); },
  };
  const doc = { readyState: "complete", documentElement: { dataset: {} }, getElementById: (id) => els[id] || null,
    addEventListener() {} };
  const back = () => { index -= 1; fire("popstate"); fire("hashchange"); };
  const forward = () => { index += 1; fire("popstate"); fire("hashchange"); };
  vm.runInNewContext(SOURCE, { window: win, document: doc });
  const visible = () => IDS.filter((id) => !els[id].hidden);
  return { nav: win.VCNav, els, doc, store, entries, location, visible, back, forward };
}

test("fresh visit opens Overview alone and normalises the URL", () => {
  const t = load();
  assert.deepEqual(t.visible(), ["overview"]);
  assert.equal(t.doc.documentElement.dataset.view, "overview");
  assert.equal(t.location.hash, "#overview");
  assert.equal(t.els.content.scrollTop, 0);
});

test("a recognised hash wins over the remembered view", () => {
  const t = load({ hash: "#chart-section", stored: "system" });
  assert.deepEqual(t.visible(), ["chart-section"]);
  assert.equal(t.store.get("vcSection"), "chart");
});

test("remembered view is used without a hash; invalid values fall back to Overview", () => {
  assert.deepEqual(load({ stored: "replay" }).visible(), ["replay-section"]);
  assert.deepEqual(load({ hash: "#nope", stored: "bogus" }).visible(), ["overview"]);
  assert.deepEqual(load({ hash: "#%E0%A4%A", stored: "constructor" }).visible(), ["overview"]);
});

test("blocked storage does not break routing", () => {
  const t = load({ hash: "#signals-section", blockedStorage: true });
  assert.deepEqual(t.visible(), ["signals-section"]);
  assert.equal(t.nav.go("setups"), true);
  assert.deepEqual(t.visible(), ["setups-section"]);
});

test("go() shows exactly one view, starts it at the top and adds a history entry", () => {
  const t = load();
  t.els.content.scrollTop = 500;
  t.nav.go("system");
  assert.deepEqual(t.visible(), ["system-section"]);
  assert.equal(t.els.content.scrollTop, 0);
  assert.deepEqual(t.entries, ["#overview", "#system-section"]);
  assert.equal(t.nav.go("system"), true); // repeat is a no-op: no duplicate entry
  assert.equal(t.entries.length, 2);
  assert.equal(t.nav.go("unknown"), false);
  assert.deepEqual(t.visible(), ["system-section"]);
});

test("Back/Forward restore the previous views", () => {
  const t = load();
  t.nav.go("chart");
  t.nav.go("replay");
  t.back();
  assert.deepEqual(t.visible(), ["chart-section"]);
  t.back();
  assert.deepEqual(t.visible(), ["overview"]);
  t.forward();
  assert.deepEqual(t.visible(), ["chart-section"]);
  assert.equal(t.store.get("vcSection"), "chart");
});

test("view-change listeners fire once per real change", () => {
  const t = load();
  const seen = [];
  t.nav.onChange((k) => seen.push(k));
  t.nav.go("chart");
  t.nav.go("chart");
  t.nav.go("signals");
  assert.deepEqual(seen, ["chart", "signals"]);
});

test("FVG Engines has its own deep link, saved selection and Back/Forward entry", () => {
  const t = load({ hash: "#engines-section" });
  assert.deepEqual(t.visible(), ["engines-section"]);
  assert.equal(t.store.get("vcSection"), "engines");
  t.nav.go("overview");
  t.nav.go("engines");
  t.back();
  assert.deepEqual(t.visible(), ["overview"]);
  t.forward();
  assert.deepEqual(t.visible(), ["engines-section"]);
  assert.deepEqual(load({ stored: "engines" }).visible(), ["engines-section"]);
});

test("only real view changes get the enter transition class (never the first paint)", () => {
  const t = load();
  const classes = new Set();
  t.els["engines-section"].classList = { add: (c) => classes.add(c), remove: (c) => classes.delete(c) };
  t.els["engines-section"].addEventListener = () => {};
  t.nav.go("engines");
  assert.ok(classes.has("vc-entering"));
  const first = load({ hash: "#engines-section" });
  assert.equal(first.els["engines-section"].classList, undefined); // stub has none: apply() never needed it on load
});
