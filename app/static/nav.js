"use strict";
// Dashboard view router: each sidebar item opens its own main view; exactly one of the six views is shown at a time.
// One state source (this module) drives the visible view, the Alpine `selected` value (sidebar styling), the URL hash
// and the remembered view. Priority on load: recognised URL hash > remembered view (localStorage, if readable) > Overview.
// Browser Back/Forward move between views through real history entries. There is no scroll-driven selection.
(function (root) {
  const SECTIONS = { overview: "overview", chart: "chart-section", signals: "signals-section", setups: "setups-section",
    replay: "replay-section", system: "system-section" };
  const KEY = "vcSection";
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const byAnchor = {};
  for (const [k, id] of Object.entries(SECTIONS)) byAnchor[id] = k;

  function keyFromHash(hash) {
    let h = "";
    try { h = decodeURIComponent((hash || "").replace(/^#/, "")); } catch (e) { return null; }
    return own(byAnchor, h) ? byAnchor[h] : null;
  }
  const fromHash = () => keyFromHash(root.location.hash);
  function stored() {
    try { const v = root.localStorage.getItem(KEY); return v && own(SECTIONS, v) ? v : null; } catch (e) { return null; }
  }
  function store(k) {
    try { root.localStorage.setItem(KEY, k); } catch (e) { /* storage blocked: the URL hash still carries the view */ }
  }
  const initialView = fromHash() || stored() || "overview";
  let current = null;
  const listeners = [];

  /** Show exactly one view (hidden views leave layout, tab order and the accessibility tree). */
  function apply(k) {
    document.documentElement.dataset.view = k;
    for (const [key, id] of Object.entries(SECTIONS)) {
      const el = document.getElementById(id);
      if (el) el.hidden = key !== k;
    }
    const sc = document.getElementById("content");
    if (sc) sc.scrollTop = 0; // every view starts at its own top
  }
  function syncAlpine(k) {
    const data = root.Alpine && root.Alpine.$data ? root.Alpine.$data(document.body) : null;
    if (data && data.selected !== k) data.selected = k; // the Alpine $watch calls go() again, which is then a no-op
  }
  function setUrl(k, push) {
    const want = "#" + SECTIONS[k];
    if (root.location.hash === want) return;
    try {
      if (push) root.history.pushState({ vcView: k }, "", want);
      else root.history.replaceState({ vcView: k }, "", want);
    } catch (e) { /* ignore: view still switches */ }
  }

  /**
   * Switch to view k. opts.history: "push" (default, user navigation), "replace" (initial/normalise) or "none"
   * (Back/Forward or a manual hash change, where the URL is already right).
   */
  function go(k, opts) {
    if (!own(SECTIONS, k)) return false;
    const mode = (opts && opts.history) || "push";
    if (mode !== "none") setUrl(k, mode === "push");
    if (k === current) { syncAlpine(k); return true; }
    current = k;
    apply(k);
    store(k);
    syncAlpine(k);
    for (const fn of listeners) { try { fn(k); } catch (e) { /* a listener must not break navigation */ } }
    return true;
  }
  function fromLocation() { go(fromHash() || "overview", { history: "none" }); }

  function init() {
    go(initialView, { history: "replace" });
    root.addEventListener("popstate", fromLocation);
    root.addEventListener("hashchange", fromLocation);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();

  root.VCNav = {
    SECTIONS, initial: () => initialView, current: () => current || initialView, go, keyFromHash, fromHash, stored,
    onChange: (fn) => listeners.push(fn),
    // compatibility shims for older callers
    remember: (k) => go(k), setSelected: (k) => go(k),
  };
})(window);
