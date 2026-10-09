"use strict";
// FVG signals, one list PER ENGINE (task 20261008-161842): "M15 Signals" and "M5 Signals" are separate panels, each with
// its latest signal, its own bounded history, filter, selection and Telegram message. READ-ONLY: GET /api/fvg?engine=...
// only. A basket's planned levels come from the stored basket; lots, planned loss and leg states only from its
// execution journal. Records are partitioned by their STORED engine + engine version; anything else is legacy.
(function (root, factory) {
  const api = factory(root);
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.VCSignals = api;
})(typeof self !== "undefined" ? self : this, function (root) {
  const ENGINES = ["M15", "M5"];
  const FILLED = new Set(["filled_open", "partially_filled", "filled", "closed_tp", "closed_sl", "closed_other"]);
  const ACCEPTED = new Set(["pending", "cancelled", "expired", ...FILLED]);
  const REFUSED = new Set(["rejected", "not_sent"]);
  const LEG_TEXT = { pending: "pending limit", filled_open: "filled · open", partially_filled: "partly filled", filled: "filled",
    closed_tp: "closed at TP", closed_sl: "closed at SL", closed_other: "closed", cancelled: "cancelled", expired: "expired unfilled",
    unknown: "UNKNOWN · reconciling", sending: "sending · unknown", prepared: "prepared · not sent", rejected: "refused",
    not_sent: "not sent" };

  /** Which list a stored basket belongs to: its engine only when engine AND engine version agree. */
  function slotOf(b) {
    const e = (b || {}).engine, v = String((b || {}).version || "");
    return (e === "M15" || e === "M5") && v.startsWith(`FVG-Immediate-${e}-`) ? e : "legacy";
  }

  function partition(baskets) {
    const out = { M15: [], M5: [], legacy: [] };
    for (const b of baskets || []) out[slotOf(b)].push(b);
    return out;
  }

  // CURRENT leg evidence: only "pending" is a resting limit now; cancelled/expired/closed legs are history.
  const OPEN = new Set(["filled_open", "partially_filled", "filled"]);
  const CLOSED = new Set(["closed_tp", "closed_sl", "closed_other"]);

  function legTally(legs) {
    const c = { pending: 0, open: 0, closed: 0, cancelled: 0, expired: 0, refused: 0, unresolved: 0 };
    for (const l of legs) {
      const st = l.state;
      if (st === "pending") c.pending += 1;
      else if (OPEN.has(st)) c.open += 1;
      else if (CLOSED.has(st)) c.closed += 1;
      else if (st === "cancelled") c.cancelled += 1;
      else if (st === "expired") c.expired += 1;
      else if (REFUSED.has(st)) c.refused += 1;
      else c.unresolved += 1; // unknown / sending / prepared / anything unrecognised: never assumed resolved
    }
    return c;
  }

  /** Signal status from the execution journal only: planned/alert-only is never shown as accepted orders, and only
   * legs that are pending NOW count as pending limits. */
  function signalStatus(b) {
    const ex = (b || {}).execution || {};
    const legs = ex.legs || [];
    if (!legs.length) {
      if (ex.state === "not_submitted" || b.status === "alert_only" || b.status === "expired_unsubmitted")
        return { label: "Alert only · no orders", tone: "light" };
      if (b.status === "planned" || ["submitting", "needs_reconciliation"].includes(ex.state)) return { label: "Outcome unresolved", tone: "warning" };
      return { label: b.status || "not submitted", tone: "light" };
    }
    const n = legs.length, c = legTally(legs);
    const accepted = n - c.refused - c.unresolved;
    const limits = (k) => `${k} pending limit${k === 1 ? "" : "s"}`;
    if (c.unresolved) return { label: `Unresolved · ${accepted}/${n} accepted${c.pending ? ` · ${limits(c.pending)}` : ""}`, tone: "warning" };
    if (c.pending === n) return { label: limits(n), tone: "info" };
    if (c.refused === n) return { label: "Refused · no order", tone: "error" };
    if (c.cancelled + c.expired === n) {
      return { label: `${c.cancelled && c.expired ? "Cancelled/expired" : c.cancelled ? "Cancelled" : "Expired"} · no fill`, tone: "light" };
    }
    const parts = [];
    if (c.refused) parts.push(`Partial · ${accepted}/${n} accepted`);
    if (c.open) parts.push(`Open ${c.open}/${n}`);
    if (c.pending) parts.push(limits(c.pending));
    if (c.closed) parts.push(`Closed ${c.closed}/${n}`);
    if (c.cancelled) parts.push(`${c.cancelled} cancelled`);
    if (c.expired) parts.push(`${c.expired} expired`);
    const tone = c.open || c.pending ? (c.refused ? "warning" : "info") : c.refused ? "warning" : "light";
    return { label: parts.join(" · "), tone };
  }

  function legRows(b) {
    const ex = (b || {}).execution || {};
    const planned = ex.legs || [];
    return ((b || {}).legs || []).map((l, i) => {
      const p = planned[i] || null;
      return { n: l.n, pct: l.pct, entry: l.entry, sl: l.sl != null ? l.sl : b.sl, tp: l.tp, rr: l.rr,
        volume: p && p.volume != null ? p.volume : null, plannedLoss: p ? p.planned_loss : null,
        state: p ? (LEG_TEXT[p.state] || p.state) : (ex.state === "not_submitted" ? "not submitted" : "not sized") };
    });
  }

  function keepSelection(prev, list) {
    return prev && list.some((b) => b.id === prev) ? prev : (list[0] ? list[0].id : null);
  }

  const pure = { ENGINES, slotOf, partition, signalStatus, legTally, legRows, keepSelection };
  if (!root || !root.document) return pure;

  // ------------------------------------------------------------------ browser
  const doc = root.document;
  const $ = (id) => doc.getElementById(id);
  const el = (tag, text, cls) => { const e = doc.createElement(tag); if (text != null) e.textContent = String(text); if (cls) e.className = cls; return e; };
  const S = { lists: { M15: null, M5: null, legacy: null }, at: {}, err: {}, sel: {}, side: {}, gen: {}, busy: {}, sig: {}, state: null, preview: {} };
  const tz = () => ((S.state || {}).setup || {}).display_timezone || "UTC";
  const fmtT = (s) => (s && root.VCTime ? root.VCTime.format(s, tz()) : (s || "—"));
  const digits = () => (S.state && S.state.symbol && Number.isInteger(S.state.symbol.digits) ? S.state.symbol.digits : null);
  const fmtP = (v) => (v == null ? "—" : digits() === null ? String(v) : Number(v).toFixed(digits()));
  const CHIP = { success: "vc-chip-success", info: "vc-chip-info", warning: "vc-chip-warning", error: "vc-chip-error", light: "vc-chip-light" };
  const visible = () => root.VCNav && root.VCNav.current() === "signals";
  const dualActive = () => !!(S.state && S.state.active_strategy && S.state.active_strategy.mode === "dual");

  async function getJSON(path) {
    const r = await fetch(path);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || d.error || `HTTP ${r.status}`);
    return d;
  }

  async function load(key) {
    if (S.busy[key]) return;
    const my = (S.gen[key] = (S.gen[key] || 0) + 1);
    S.busy[key] = true;
    const panel = $(`sig-${key}`);
    if (panel) panel.setAttribute("aria-busy", "true");
    try {
      const d = await getJSON(`/api/fvg?engine=${key}&limit=${key === "legacy" ? 20 : 30}`);
      if (my !== S.gen[key]) return; // a newer request for THIS engine won
      S.lists[key] = d.baskets || [];
      S.at[key] = new Date().toISOString();
      S.err[key] = null;
    } catch (e) {
      if (my === S.gen[key]) S.err[key] = e.message;
    } finally {
      if (my === S.gen[key]) { S.busy[key] = false; if (panel) panel.removeAttribute("aria-busy"); render(key); }
    }
  }

  function chip(text, tone) { return el("span", text, `vc-chip ${CHIP[tone] || CHIP.light}`); }

  function detail(key, b) {
    const box = el("div", null, "vc-sig-detail");
    const st = signalStatus(b);
    const head = el("div", null, "flex flex-wrap items-center gap-2");
    head.append(el("span", b.direction, b.direction === "BUY" ? "vc-buy font-semibold" : "vc-sell font-semibold"),
      el("span", fmtT(b.placed_at), "vc-num text-[13px]"), chip(st.label, st.tone));
    if (b.delivery) head.append(chip(`Telegram ${b.delivery.status}`, b.delivery.status === "sent" ? "success" : b.delivery.status === "failed" ? "error" : "light"));
    box.append(head, el("p", `Zone ${fmtP(b.bottom)} – ${fmtP(b.top)} · SL ${fmtP(b.sl)} · ${b.id}`, "vc-muted vc-num mt-1 text-[12px]"));
    const ex = b.execution || {};
    const t = el("table", null, "vc-table vc-sig-legs mt-2");
    const hr = el("tr");
    for (const h of ["Leg", "Entry", "SL", "TP", "RR", "Lots", "Planned loss", "State"]) hr.append(el("th", h));
    const th = el("thead"); th.append(hr);
    const tb = el("tbody");
    for (const l of legRows(b)) {
      const risk = l.plannedLoss != null && root.VCFvgDisplay ? root.VCFvgDisplay.legRisk(l.plannedLoss, ex.account_currency) : null;
      const tr = el("tr");
      tr.append(el("td", `L${l.n} ${l.pct}%`), el("td", fmtP(l.entry), "vc-num"), el("td", fmtP(l.sl), "vc-num"), el("td", fmtP(l.tp), "vc-num"),
        el("td", l.rr != null ? Number(l.rr).toFixed(2) : "—", "vc-num"), el("td", l.volume != null ? l.volume : "—", "vc-num"),
        el("td", risk || "—", "vc-num"), el("td", l.state));
      tb.append(tr);
    }
    t.append(th, tb);
    const wrap = el("div", null, "vc-table-wrap"); wrap.append(t);
    box.append(wrap);
    const acts = el("div", null, "mt-2 flex flex-wrap gap-2");
    const msgBtn = el("button", S.preview[key] === b.id ? "Hide message" : "Telegram message", "vc-btn h-8 px-3 text-[12px]");
    msgBtn.type = "button";
    msgBtn.setAttribute("aria-expanded", String(S.preview[key] === b.id));
    msgBtn.addEventListener("click", () => { S.preview[key] = S.preview[key] === b.id ? null : b.id; S.sig[key] = null; render(key); });
    const guide = el("button", "Explain in FVG Guide", "vc-btn h-8 px-3 text-[12px]");
    guide.type = "button";
    guide.disabled = !b.setup_key;
    guide.addEventListener("click", () => { if (root.VCGuide && root.VCNav) { root.VCGuide.openRecord(b.setup_key); root.VCNav.go("guide"); } });
    acts.append(msgBtn, guide);
    if (key !== "legacy") {
      const eng = el("button", `${key} engine panel`, "vc-btn h-8 px-3 text-[12px]");
      eng.type = "button";
      eng.addEventListener("click", () => { if (root.VCEngines) root.VCEngines.focusEngine(key); });
      acts.append(eng);
    }
    box.append(acts);
    if (S.preview[key] === b.id) {
      const m = b.message || { source: "preview", text: b.preview || "" };
      box.append(el("p", m.source === "queued" ? "Exact queued Telegram text (this basket only)" : "Preview only: not queued (Telegram off or not sent)", "vc-faint mt-2 text-[12px]"),
        el("pre", m.text, "vc-inset vc-scroll mt-1 overflow-x-auto p-3 font-mono text-[12px] whitespace-pre-wrap"));
    }
    return box;
  }

  function render(key) {
    const panel = $(`sig-${key}`);
    if (!panel) return;
    const listAll = S.lists[key];
    const side = S.side[key] || "";
    const list = (listAll || []).filter((b) => !side || b.direction === side);
    S.sel[key] = keepSelection(S.sel[key], list);
    const count = panel.querySelector('[data-role="count"]');
    if (count) count.textContent = listAll ? `${list.length}${side ? ` ${side}` : ""} shown` : "";
    const note = panel.querySelector('[data-role="note"]');
    const feedOk = !!(S.state && S.state.feed && S.state.feed.ok);
    if (note) note.textContent = S.err[key] ? `Refresh failed (${S.err[key]})${S.at[key] ? ` · showing ${fmtT(S.at[key])}` : ""}`
      : !feedOk && S.state ? "Feed offline · stored signals only" : "";
    const sig = JSON.stringify([listAll && listAll.map((b) => [b.id, b.status, (b.execution || {}).state, ((b.execution || {}).legs || []).map((l) => l.state), (b.delivery || {}).status]),
      side, S.sel[key], S.preview[key], digits(), tz()]);
    if (S.sig[key] === sig) return; // nothing changed: keep focus and scroll
    S.sig[key] = sig;
    const focused = panel.contains(doc.activeElement) ? doc.activeElement.dataset.id || doc.activeElement.textContent : null;
    const body = panel.querySelector('[data-role="body"]');
    body.replaceChildren();
    if (!listAll) { body.append(el("p", "Loading…", "vc-muted text-[13px]")); return; }
    if (!list.length) { body.append(el("p", key === "legacy" ? "None." : `No ${key} signals${side ? ` (${side})` : ""} yet.`, "vc-muted text-[13px]")); return; }
    const selected = list.find((b) => b.id === S.sel[key]) || list[0];
    body.append(el("p", selected === list[0] ? "Latest" : "Selected (historical)", "vc-label mb-1"), detail(key, selected));
    const ul = el("ul", null, "mt-3 grid gap-1");
    for (const b of list.slice(0, 20)) {
      const li = el("li");
      const btn = el("button", null, `vc-rec${b.id === selected.id ? " vc-rec-selected" : ""}`);
      btn.type = "button";
      btn.dataset.id = b.id;
      btn.setAttribute("aria-pressed", String(b.id === selected.id));
      btn.append(el("span", fmtT(b.placed_at), "vc-num"), el("span", `${b.direction} ${fmtP(b.bottom)}–${fmtP(b.top)}`, "vc-num"),
        el("span", signalStatus(b).label, "vc-muted"), el("span", b.id === list[0].id ? "latest" : "history", "vc-rec-tag"));
      btn.addEventListener("click", () => { S.sel[key] = b.id; S.sig[key] = null; render(key); });
      li.append(btn);
      ul.append(li);
    }
    body.append(el("p", "History", "vc-label mt-3"), ul);
    if (focused) {
      const again = [...panel.querySelectorAll("button")].find((x) => (x.dataset.id || x.textContent) === focused);
      if (again) again.focus();
    }
  }

  function refreshAll(force) {
    for (const k of ["M15", "M5", "legacy"]) {
      if (force || !S.at[k] || Date.now() - Date.parse(S.at[k]) > 8000) load(k);
    }
  }

  function onState(ev) {
    S.state = ev.detail;
    const box = $("fvg-signals");
    if (!box) return;
    const on = dualActive();
    box.hidden = !on;
    const other = $("other-signals");
    if (other && on && !other.dataset.collapsedOnce) { other.open = false; other.dataset.collapsedOnce = "1"; }
    if (!on || !visible()) return;
    refreshAll(false);
    for (const k of ["M15", "M5", "legacy"]) render(k);
  }

  function init() {
    if (!$("fvg-signals")) return;
    for (const k of ["M15", "M5"]) {
      const f = $(`sig-${k}-side`);
      if (f) f.addEventListener("change", () => { S.side[k] = f.value; S.sig[k] = null; render(k); });
    }
    const leg = $("sig-legacy-wrap");
    if (leg) leg.addEventListener("toggle", () => { if (leg.open) render("legacy"); });
    root.addEventListener("vc:state", onState);
    if (root.VCNav) root.VCNav.onChange((k) => { if (k === "signals" && dualActive()) refreshAll(true); });
  }
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", init); else init();

  return { ...pure, refreshAll };
});
