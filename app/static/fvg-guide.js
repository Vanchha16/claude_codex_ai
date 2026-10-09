"use strict";
// FVG Guide view: explains, from real records, how an FVG setup moves from the M15 gap to an M5 confirmation, the three
// pending limits and later fills, from real stored MT5 records only (no fictional lessons or sample data).
// Read-only: it only GETs /api/fvg/guide. It never arms, submits, cancels, injects signals,
// changes stored records or sends messages.
(function (root, factory) {
  const api = factory(root);
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.VCGuide = api;
})(typeof self !== "undefined" ? self : this, function (root) {
  const STEP_LOOK = {
    done: { text: "Completed", tone: "success", mark: "✓" },
    partial: { text: "Partly done", tone: "warning", mark: "◐" },
    waiting: { text: "Waiting", tone: "info", mark: "…" },
    failed: { text: "Failed / expired", tone: "error", mark: "✗" },
    skipped: { text: "Not used", tone: "warning", mark: "–" },
    unavailable: { text: "Not reached", tone: "light", mark: "·" },
  };
  const stepLook = (state) => STEP_LOOK[state] || STEP_LOOK.unavailable;
  const clampFrame = (i, n) => Math.max(0, Math.min(n - 1, i | 0));
  const M5S = 300, M15S = 900;

  /**
   * Pure chart geometry (testable without a DOM). spec: {m15, m5, revealed (count of m5 shown, or null = all), zone,
   * level, levelAt (epoch s), lines: [{price, label, kind}]}. Returns candles with pixel geometry and the price/time scale.
   */
  function layoutChart(spec, width, height) {
    const pad = { l: 8, r: 118, t: 14, b: 26 };
    const m5 = spec.revealed == null ? spec.m5 : spec.m5.slice(0, spec.revealed);
    const bars = [...(spec.m15 || []).map((b) => ({ ...b, span: b.tf === "M5" ? M5S : M15S })), ...m5.map((b) => ({ ...b, span: M5S }))];
    if (!bars.length) return { candles: [], empty: true };
    const t0 = Math.min(...bars.map((b) => b.t));
    const visibleEnd = Math.max(...bars.map((b) => b.t + b.span));
    const t1 = Math.max(visibleEnd + 2 * M5S, t0 + 6 * M15S);
    const prices = bars.flatMap((b) => [b.h, b.l]);
    if (spec.zone) prices.push(spec.zone.bottom, spec.zone.top);
    for (const z of spec.zones || []) prices.push(z.bottom, z.top);
    if (spec.level != null) prices.push(spec.level);
    for (const ln of spec.lines || []) prices.push(ln.price);
    let lo = Math.min(...prices), hi = Math.max(...prices);
    const padP = (hi - lo || 1) * 0.06;
    lo -= padP; hi += padP;
    const x = (t) => pad.l + ((t - t0) / (t1 - t0)) * (width - pad.l - pad.r);
    const y = (p) => pad.t + ((hi - p) / (hi - lo)) * (height - pad.t - pad.b);
    const candles = bars.map((b) => {
      const x0 = x(b.t), x1 = x(b.t + b.span), w = Math.max(2, (x1 - x0) * 0.68);
      return { ...b, cx: (x0 + x1) / 2, w, yH: y(b.h), yL: y(b.l), yO: y(b.o), yC: y(b.c), up: b.c >= b.o };
    });
    return { candles, x, y, t0, t1, lo, hi, width, height, pad, right: width - pad.r };
  }

  /**
   * Right-margin price labels never overlap: sorted by their price's y, pushed apart to at least `gap` px and kept inside
   * [top, bottom]. Each keeps its true `y` (for a short leader line) and gets a display position `at`.
   */
  function spreadLabels(items, gap, top, bottom) {
    const out = items.map((it) => ({ ...it })).sort((a, b) => a.y - b.y);
    for (let i = 0; i < out.length; i++) out[i].at = Math.max(out[i].y, i ? out[i - 1].at + gap : top);
    const over = out.length ? out[out.length - 1].at - bottom : 0;
    if (over > 0) {
      out[out.length - 1].at = bottom;
      for (let i = out.length - 2; i >= 0; i--) out[i].at = Math.min(out[i].at, out[i + 1].at - gap);
    }
    return out;
  }

  /**
   * What the live Guide shows for a response: the selected record, an explicit "requested record not found" (the
   * requested key is KEPT so refreshes keep asking for it; nothing else is shown in its place), or nothing.
   */
  function selectionState(data, requestedKey) {
    if (data && data.missing_key) return { mode: "missing", key: data.missing_key };
    if (data && data.selected && data.selected.record) return { mode: "selected", key: data.selected.record.key };
    return { mode: "none", key: requestedKey || null };
  }

  if (!root || !root.document) return { stepLook, clampFrame, layoutChart, spreadLabels, selectionState, stopRule };

  // ------------------------------------------------------------------ browser
  const doc = root.document;
  const $ = (id) => doc.getElementById(id);
  const SVG = "http://www.w3.org/2000/svg";
  const G = { data: null, key: null, loading: false };
  const tz = () => (G.data && G.data.display_timezone) || "UTC";
  const fmtT = (s) => (s && root.VCTime ? root.VCTime.format(s, tz()) : (s || "—"));
  const fmtP = (v) => (v === null || v === undefined ? "—" : Number(v).toFixed(2));
  // server texts carry ISO-8601 UTC instants; show them in the dashboard's display time zone
  const ISO_RE = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g;
  const humanise = (text) => String(text || "").replace(ISO_RE, (m) => fmtT(m));
  const el = (tag, text, cls) => { const e = doc.createElement(tag); if (text != null) e.textContent = String(text); if (cls) e.className = cls; return e; };
  const sv = (tag, attrs, text) => {
    const e = doc.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, String(v));
    if (text != null) e.textContent = String(text);
    return e;
  };
  const reduceMotion = () => root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;

  async function getJSON(path) {
    const r = await fetch(path);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || data.error || `HTTP ${r.status}`);
    return data;
  }

  function renderSteps(list, steps) {
    list.replaceChildren();
    for (const s of steps || []) {
      const look = stepLook(s.state);
      const li = el("li", null, `vc-gstep vc-gstep-${s.state}`);
      const head = el("div", null, "flex flex-wrap items-center gap-2");
      head.append(el("span", look.mark, "vc-gstep-mark"), el("span", s.title, "font-semibold"),
        el("span", look.text, `vc-chip vc-chip-${look.tone}`));
      li.append(head, el("p", humanise(s.detail), "vc-muted mt-1 text-[13px]"));
      list.append(li);
    }
  }

  function renderLadder(box, levels, opts) {
    box.replaceChildren();
    if (!levels || levels.error) { box.append(el("p", levels && levels.error ? `Levels unavailable: ${levels.error}` : "No levels.", "vc-muted")); return; }
    const source = levels.source === "basket" ? "Actual basket levels" : "PREVIEW levels (not orders)";
    box.append(el("p", `${source} · common SL ${fmtP(levels.sl)} · each leg its own 1:2 target`, "vc-label mb-2"));
    const stopText = levels.source === "basket" && root.VCFvgDisplay ? root.VCFvgDisplay.stopNote(levels.stop, fmtP) : null;
    if (stopText) box.append(el("p", stopText, "vc-muted mb-2 text-[13px]"));
    if (levels.note) box.append(el("p", levels.note, "vc-muted mb-2 text-[13px]"));
    const table = el("table", null, "vc-table");
    const head = el("tr");
    for (const h of ["Leg", "Depth", "Entry (limit)", "Stop loss", "Take profit", "RR", "Lots", "Planned loss", "State"]) head.append(el("th", h));
    const thead = el("thead"); thead.append(head);
    const tbody = el("tbody");
    for (const l of levels.legs || []) {
      const tr = el("tr");
      const risk = l.planned_loss != null && root.VCFvgDisplay ? root.VCFvgDisplay.legRisk(l.planned_loss, levels.account_currency) : null;
      const state = opts.legState ? opts.legState(l) : (l.state || (levels.source === "basket" ? "—" : "not submitted"));
      tr.append(el("td", `L${l.n}`), el("td", `${l.pct}%`), el("td", fmtP(l.entry), "vc-num"), el("td", fmtP(l.sl != null ? l.sl : levels.sl), "vc-num"),
        el("td", fmtP(l.tp), "vc-num"), el("td", l.rr != null ? Number(l.rr).toFixed(2) : "2.00", "vc-num"),
        el("td", l.volume != null ? `${l.volume} lot` : "not sized", "vc-num"), el("td", risk || "—", "vc-num"), el("td", state));
      tbody.append(tr);
    }
    table.append(thead, tbody);
    const wrap = el("div", null, "vc-table-wrap"); wrap.append(table);
    box.append(wrap);
  }

  /** Annotated SVG chart: M15 A/B/C, zone, retest, frozen level, numbered confirmation candles, entries/SL/TP. */
  function renderChart(holder, spec) {
    holder.replaceChildren();
    const W = 860, H = 340;
    const L = layoutChart(spec, W, H);
    if (L.empty) { holder.append(el("p", spec.emptyText || "No candles available for this setup.", "vc-muted p-4")); return; }
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": spec.aria || "FVG setup chart", class: "vc-gchart" });
    const right = L.right;
    const zones = spec.zones || (spec.zone && spec.zoneFrom != null ? [{ ...spec.zone, from: spec.zoneFrom, label: "zone" }] : []);
    const labels = [];
    for (const z of zones) {
      const zx = L.x(z.from);
      svg.append(sv("rect", { x: zx, y: L.y(z.top), width: Math.max(1, right - zx), height: Math.max(1, L.y(z.bottom) - L.y(z.top)), class: `vc-gzone${z.kind ? ` vc-gzone-${z.kind}` : ""}` }));
      labels.push({ y: L.y(z.top), text: `${z.label} top ${fmtP(z.top)}`, cls: "vc-glabel" });
      labels.push({ y: L.y(z.bottom), text: `${z.label} bottom ${fmtP(z.bottom)}`, cls: "vc-glabel" });
    }
    for (const ln of spec.lines || []) {
      const lx = ln.from != null ? L.x(ln.from) : L.pad.l;
      svg.append(sv("line", { x1: lx, x2: right, y1: L.y(ln.price), y2: L.y(ln.price), class: `vc-gline vc-gline-${ln.kind}` }));
      labels.push({ y: L.y(ln.price), text: `${ln.label} ${fmtP(ln.price)}`, cls: `vc-glabel vc-glabel-${ln.kind}` });
    }
    for (const lb of spreadLabels(labels, 12, L.pad.t, H - L.pad.b)) {
      if (Math.abs(lb.at - lb.y) > 0.5) svg.append(sv("line", { x1: right, x2: right + 3, y1: lb.y, y2: lb.at, class: "vc-gleader" }));
      svg.append(sv("text", { x: right + 4, y: lb.at + 4, class: lb.cls }, lb.text));
    }
    for (const c of L.candles) {
      const g = sv("g", { class: `vc-gcandle ${c.up ? "vc-gup" : "vc-gdown"}${c.closed === false ? " vc-gforming" : ""}`, tabindex: 0 });
      g.append(sv("title", {}, `${c.tf} ${fmtT(new Date(c.t * 1000).toISOString())}${c.closed === false ? " (forming)" : ""}  O ${fmtP(c.o)}  H ${fmtP(c.h)}  L ${fmtP(c.l)}  C ${fmtP(c.c)}`));
      g.append(sv("line", { x1: c.cx, x2: c.cx, y1: c.yH, y2: c.yL, class: "vc-gwick" }));
      g.append(sv("rect", { x: c.cx - c.w / 2, y: Math.min(c.yO, c.yC), width: c.w, height: Math.max(1, Math.abs(c.yO - c.yC)), class: "vc-gbody" }));
      const tag = spec.tags && spec.tags[`${c.tf}:${c.t}`];
      if (tag) {
        const above = !spec.tagsBelow;
        svg.append(g);
        const ty = above ? c.yH - 6 : c.yL + 14;
        svg.append(sv("text", { x: c.cx, y: ty, "text-anchor": "middle", class: `vc-gtag vc-gtag-${tag.kind || "info"}` }, tag.text));
        continue;
      }
      svg.append(g);
    }
    const ticks = 6;
    for (let i = 0; i <= ticks; i++) {
      const t = L.t0 + ((L.t1 - L.t0) * i) / ticks;
      const anchor = i === 0 ? "start" : i === ticks ? "end" : "middle"; // edge labels stay inside the plot
      svg.append(sv("text", { x: L.x(t), y: H - 8, "text-anchor": anchor, class: "vc-glabel" }, root.VCTime ? root.VCTime.axis(t, tz()) : ""));
    }
    holder.append(svg);
  }

  function chartSpecFromRecord(sel, extra) {
    const rec = sel.record;
    const tags = {};
    for (const b of sel.m15 || []) tags[`M15:${b.t}`] = { text: b.role, kind: "abc" };
    for (const w of sel.window || []) {
      if (w.missing) continue;
      if (w.role === "retest") tags[`M5:${w.t}`] = { text: "R (retest)", kind: "retest" };
      else tags[`M5:${w.t}`] = { text: `${w.n}${w.beyond ? " ✓" : w.closed === false ? " …" : " ✗"}`, kind: w.beyond ? "ok" : "no" };
    }
    const lines = [];
    const retestT = rec.retest_close ? Date.parse(rec.retest_close) / 1000 - M5S : null;
    if (rec.level != null) lines.push({ price: rec.level, label: "confirm level", kind: "level", from: retestT });
    const lv = sel.levels;
    const confirmT = rec.confirm_close ? Date.parse(rec.confirm_close) / 1000 : null;
    if (lv && !lv.error && (extra.showLevels || lv.source === "basket")) {
      lines.push({ price: lv.sl, label: "SL", kind: "sl", from: confirmT });
      for (const l of lv.legs || []) {
        lines.push({ price: l.entry, label: `L${l.n} ${l.pct}%`, kind: "entry", from: confirmT });
        lines.push({ price: l.tp, label: `TP${l.n}`, kind: "tp", from: confirmT });
      }
    }
    return { m15: sel.m15 || [], m5: sel.m5 || [], revealed: extra.revealed == null ? null : extra.revealed,
      zone: { bottom: rec.bottom, top: rec.top }, zoneFrom: Date.parse(rec.c_close) / 1000, level: rec.level, lines, tags,
      tagsBelow: rec.direction === "SELL", aria: extra.aria, emptyText: extra.emptyText };
  }

  // ------------------------------------------------------------------ live / recorded
  /** One confirmation-window line; a forming or missing candle is never introduced as a closed one. */
  function windowText(w, rec) {
    const name = w.role === "retest" ? "Retest" : `Chance ${w.n}`;
    const closeAt = fmtT(new Date((w.t + M5S) * 1000).toISOString());
    if (w.missing) return `${name} · M5 ${fmtT(new Date(w.t * 1000).toISOString())} candle → ${w.verdict}`;
    if (w.closed === false) return `${name} · M5 forming, closes ${closeAt} · price now ${fmtP(w.c)} vs level ${fmtP(rec.level)} → ${w.verdict}`;
    return `${name} · M5 closed ${closeAt} · close ${fmtP(w.c)} vs level ${fmtP(rec.level)} → ${w.verdict}`;
  }

  function renderLive() {
    const d = G.data;
    if (!d) return;
    const rt = $("g-runtime");
    const st = d.status || {};
    const dual = st.dual;
    rt.textContent = `LIVE MT5 · FVG ${d.fvg_active ? (d.strategy_mode === "dual" ? "dual engines (M15 + M5)" : "active (legacy v1)") : "inactive"}${dual ? ` · baskets today ${dual.daily.accepted}/${dual.daily.cap} (total)` : ""} · feed ${d.feed_ok ? "connected" : "OFFLINE"} · quotes ${d.quote_fresh ? "fresh" : "NOT fresh"}${d.scanner_paused ? " · scanner PAUSED" : ""} · automatic execution ${st.auto_execution || "OFF"} · risk ${st.risk_usd != null ? `$${Number(st.risk_usd).toFixed(2)}` : "not set"} per ${d.strategy_mode === "dual" ? "basket (one per engine)" : "setup"} · updated ${fmtT(d.now)}`;
    const sel = $("g-record");
    const prev = G.key;
    sel.replaceChildren();
    for (const r of d.records || []) {
      const o = el("option", `${fmtT(r.c_close)} · ${r.engine ? `${r.engine} engine` : "legacy v1"} · ${r.direction} ${fmtP(r.bottom)}–${fmtP(r.top)} · ${r.status}${r.current_version ? "" : " · other rule version"}`);
      o.value = r.key; sel.append(o);
    }
    const msg = $("g-message");
    msg.textContent = d.message || "";
    msg.hidden = !d.message;
    const body = $("g-live-body");
    const pick = selectionState(d, G.key);
    G.key = pick.key;
    if (pick.mode === "missing") {
      msg.hidden = false;
      msg.textContent = `Requested setup not found: ${pick.key}. ${d.message || ""} Choose another record above.`;
      const o = el("option", "Requested setup not found");
      o.value = pick.key; o.disabled = true; sel.prepend(o); sel.value = pick.key;
    }
    if (pick.mode !== "selected") { body.hidden = true; return; }
    body.hidden = false;
    const s = d.selected, rec = s.record;
    sel.value = prev && (d.records || []).some((r) => r.key === prev) ? prev : rec.key;
    const active = rec.status === "pending" || rec.status === "retested";
    const chip = $("g-status");
    chip.textContent = active ? `LIVE · ${rec.status}` : `HISTORICAL · ${rec.status}`;
    chip.className = `vc-chip ${active ? "vc-chip-info" : rec.status === "confirmed" ? "vc-chip-success" : "vc-chip-light"}`;
    $("g-reason").textContent = rec.reason_text ? `Reason: ${rec.reason_text}` : "";
    $("g-version").textContent = [rec.rule_label ? `Rules: ${rec.rule_label}` : "",
      rec.current_version ? "" : "Recorded under another rule version; shown as stored."].filter(Boolean).join(" · ");
    $("g-next").textContent = humanise(s.next);
    renderSteps($("g-steps"), s.steps);
    const dl = $("g-deadlines"); dl.replaceChildren();
    for (const x of s.deadlines || []) dl.append(el("li", `${x.label}: ${fmtT(x.at)}`));
    const ct = $("g-chart-title");
    if (ct) ct.textContent = `Candles (${rec.engine || "M15"} A/B/C of the gap, then closed M5 candles)`;
    renderChart($("g-chart"), chartSpecFromRecord(s, { aria: `${rec.direction} FVG ${rec.bottom} to ${rec.top}`,
      emptyText: s.data_note || "Candles unavailable.", showLevels: false }));
    const wt = $("g-window"); wt.replaceChildren();
    if (rec.rule_set === "dual") wt.append(el("li", `The ${rec.engine} engine decides when candle C closes: there is no retest or confirmation window. A qualified gap places three limits at once; they fill only if price later comes back to them.`, "vc-muted"));
    else if (!(s.window || []).length) wt.append(el("li", rec.retest_close ? "Candles for the confirmation window are unavailable." : "No retest yet, so no confirmation window.", "vc-muted"));
    for (const w of s.window || []) wt.append(el("li", windowText(w, rec)));
    renderLadder($("g-ladder"), s.levels, {});
    renderRisk($("g-risk"), st, s.levels);
  }

  function renderRisk(box, st, levels) {
    box.replaceChildren();
    const risk = st && st.risk_usd != null ? Number(st.risk_usd) : null;
    const p = [
      risk != null ? `Total planned stop-loss risk per setup: $${risk.toFixed(2)}, split into three equal shares of $${(risk / 3).toFixed(2)} before lot rounding.` :
        "Risk per setup is not available right now, so no amount is shown. Whatever amount is saved is split into three equal shares before lot rounding.",
      "Each leg's lots = its share ÷ the broker's loss per lot from that entry to the common stop, rounded DOWN to the lot step. A deeper entry is closer to the stop, so it gets MORE lots; a wider stop distance gets fewer.",
      "If any leg cannot fit the minimum lot inside its share, the whole basket is rejected (no redistribution). Actual rounded losses can be lower than the share; fees, gaps and slippage can make a real loss larger.",
      levels && levels.source === "basket" ? "Lots and planned losses above come from the actual execution journal." :
          "No basket exists for this setup, so nothing was sized or submitted.",
    ];
    for (const t of p) box.append(el("p", t, "vc-muted text-[13px]"));
  }

  async function refreshLive() {
    if (G.loading) return;
    G.loading = true;
    try {
      G.data = await getJSON(`/api/fvg/guide${G.key ? `?key=${encodeURIComponent(G.key)}` : ""}`);
      renderLive();
      renderRules(G.data.config, G.data.scopes, G.data.strategy_mode);
    } catch (e) {
      const msg = $("g-message"); msg.hidden = false; msg.textContent = `Guide data unavailable: ${e.message}`;
    } finally { G.loading = false; }
  }

  // ------------------------------------------------------------------ rule reference
  /** The dual engines' common-stop rule from the server's own per-engine scope text (task 20261009-110034). */
  function stopRule(cfg, scopes) {
    const sp = (scopes && scopes.stop_policy) || {};
    if (sp.M15 && sp.M15 === sp.M5) return `common stop for both engines: ${sp.M15}`;
    if (sp.M15 || sp.M5) return `common stop: M15 ${sp.M15 || "?"}; M5 ${sp.M5 || "?"}`;
    return `common stop ${cfg.sl_buffer_ticks} ticks beyond the far edge`;
  }

  function renderRules(cfg, scopes, mode) {
    const box = $("g-rules-body");
    if (!cfg || !box) return;
    box.replaceChildren();
    const dual = scopes ? [
      ["Two engines (dual mode)", "An M15 engine and an M5 engine run side by side. Each uses only its OWN closed candles (M15: complete M15 candles; M5: closed M5 candles) for the gap, the trend warm-up and ATR. Neither needs the other's direction, readiness or approval."],
      ["Gap and qualification", `Three adjacent CLOSED candles A, B, C of that engine's timeframe; BUY gap A.high..C.low, SELL gap C.high..A.low. EMA${cfg.ema_fast}/EMA${cfg.ema_slow} trend on at least ${cfg.trend_min_candles} contiguous candles of that timeframe, gap at least max(${cfg.min_gap_ticks} ticks, ${cfg.gap_atr} × ATR${cfg.atr_period}), candle B's body at least ${cfg.displacement_atr} × ATR.`],
      ["Entry event", `Qualification IS the entry decision: no retest and no confirmation. Candle C must close after the current session started and be at most ${scopes.decision_max_age_seconds} s old when the order is decided and sent; old gaps from catch-up or reconnects are recorded, never ordered.`],
      ["Orders", `Three limits at ${cfg.entry_depths.join("% / ")}% depth of that engine's zone, ${stopRule(cfg, scopes)}, each 1:${cfg.reward_risk}. They wait for price to come back; a limit is not a market fill.`],
      ["Capacity", `${scopes.open_baskets} open basket; cooldown ${scopes.cooldown}; ${scopes.daily_cap}; ${scopes.risk}; ${scopes.tie_order}.`],
      ["Invalidation", "A later CLOSED candle of the basket's own timeframe beyond the far edge removes that basket's pending remainder (M15 baskets: M15 closes only; M5 baskets: M5 closes). Filled positions keep their stop and target."],
    ] : [];
    const legacyPrefix = scopes ? "Legacy v1 · " : "";
    const rows = [
      ["Gap (M15)", `Three adjacent CLOSED M15 candles A, B, C. BUY gap = A's high to C's low (C's low above A's high); SELL gap = C's high to A's low. It exists from C's close.`],
      ["Trend", `EMA${cfg.ema_fast} vs EMA${cfg.ema_slow} on the contiguous closed M15 run ending at C, which needs at least ${cfg.trend_min_candles} candles after any market/data break. EMA${cfg.ema_fast} above allows BUY, below allows SELL, equal allows neither.`],
      ["Size and displacement", `Gap at least max(${cfg.min_gap_ticks} ticks, ${cfg.gap_atr} × ATR${cfg.atr_period}); candle B's body at least ${cfg.displacement_atr} × ATR${cfg.atr_period} (ATR measured through B).`],
      ["Retest (M5)", "The FIRST later closed M5 candle that trades into the zone. Its high (BUY) or low (SELL) is frozen as the confirmation level. The retest candle can never confirm itself."],
      ["Confirmation (M5)", `A DIFFERENT one of the next ${cfg.confirm_bars} contiguous closed M5 candles must CLOSE strictly above the level (BUY) or below it (SELL). A wick is not enough and an equal close is not beyond. After ${cfg.confirm_bars} candles without it, the setup expires.`],
      ["Invalidation", "Any closed M5 candle beyond the far edge (BUY close below the bottom, SELL close above the top) invalidates, and wins over a same-candle confirmation. A missing or invalid M5 candle also ends the setup."],
      ["Lifetimes", `Setup: ${cfg.setup_minutes} min from candle C. Confirmation window: ${cfg.confirm_bars} M5 candles after the retest. Pending orders: ${cfg.pending_expiry_minutes} min from placement.`],
      ["Signal blockers", `Confirmation must close after the current session started, be at most ${cfg.max_confirmation_age_seconds} s old at the decision and before the setup deadline; one open basket at a time, ${cfg.cooldown_minutes} min cooldown, at most ${cfg.max_baskets_per_day} baskets per Bangkok day; every stop at least spread + ${cfg.stop_spread_margin_ticks} tick from its entry and every limit on the resting side of the market.`],
      ["Entries", `Three limits at ${cfg.entry_depths.join("% / ")}% depth into the zone, one common stop ${cfg.sl_buffer_ticks} ticks beyond the far edge, each with its own 1:${cfg.reward_risk} target. Confirmation places them; a fill needs a LATER return of price to each limit.`],
      ["Execution (separate)", "Only when automatic execution is ON for this exact account (the demo-ACCOUNT default of your broker account, or your explicit arming): account/server binding, risk sizing, broker preflight, fresh quote and spread checks, then sends. Unknown results are reconciled, never resent."],
    ];
    const dl = el("dl", null, "grid gap-x-4 gap-y-2 text-[13px] sm:grid-cols-[max-content_1fr]");
    for (const [k, v] of dual) dl.append(el("dt", k, "font-semibold"), el("dd", v, "vc-muted"));
    if (scopes) dl.append(el("dt", "Legacy v1 rules", "font-semibold mt-2"), el("dd", "Kept for rollback and for explaining older records (M15 gap, then M5 retest and confirmation):", "vc-muted mt-2"));
    for (const [k, v] of rows) dl.append(el("dt", legacyPrefix + k, "font-semibold"), el("dd", v, "vc-muted"));
    box.append(dl, el("p", `Rule parameters ${cfg.version}${mode === "dual" ? " · active mode: dual engines" : ""}`, "vc-faint mt-2 text-[12px]"));
  }

  // ------------------------------------------------------------------ wiring
  const visible = () => root.VCNav && root.VCNav.current() === "guide";

  function init() {
    if (!$("guide-section")) return;
    $("g-record").addEventListener("change", (e) => { G.key = e.target.value; refreshLive(); });
    root.addEventListener("themechange", () => { if (visible()) renderLive(); });
    if (root.VCNav) root.VCNav.onChange((k) => { if (k === "guide") refreshLive(); });
    if (visible()) refreshLive();
    root.setInterval(() => { if (visible()) refreshLive(); }, 10000);
  }
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", init); else init();

  return { stepLook, clampFrame, layoutChart, spreadLabels, selectionState, refreshLive,
    openRecord: (key) => { G.key = key; refreshLive(); } };
});
