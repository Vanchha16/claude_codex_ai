"use strict";
// FVG Engines view: the M15 and M5 dual-mode engines side by side, each with its own fixed-timeframe chart, readiness,
// latest decision evidence, basket/legs and recent records. READ-ONLY: it only GETs /api/state (via app.js's
// "vc:state" event), /api/fvg and /api/market/bars. It never arms, submits, cancels, changes settings or runs a replay;
// live execution controls stay in System. Everything shown comes from stored records: nothing is invented to fill gaps.
(function (root, factory) {
  const api = factory(root);
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.VCEngines = api;
})(typeof self !== "undefined" ? self : this, function (root) {
  const ENGINES = ["M15", "M5"];
  const TF_SECONDS = { M15: 900, M5: 300 };
  const QUALIFY = ["history_not_ending_at_c", "trend_warmup", "trend_flat", "trend_against", "atr_warmup", "gap_too_small",
    "weak_displacement"];
  // the order in which the dual engine decides after qualification (app/fvg_dual.py _decide)
  const DECIDE = ["c_before_session_watermark", "c_close_in_future", "decision_too_old", "levels_invalid",
    "no_quote_for_eligibility_check", "stop_within_spread", "limit_on_wrong_side_of_market", "engine_basket_open",
    "cooldown", "daily_cap", "concurrent_risk_cap", "duplicate_basket"];
  const REASON = {
    history_not_ending_at_c: "the candle history did not end exactly at candle C",
    trend_warmup: "not enough contiguous candles of this timeframe yet for EMA20/EMA50 (50 needed after any break)",
    trend_flat: "EMA20 equals EMA50: no trend direction", trend_against: "the gap points against the EMA20/EMA50 trend",
    atr_warmup: "not enough candles for ATR14", gap_too_small: "the gap is smaller than max(2 ticks, 0.10 x ATR14)",
    weak_displacement: "candle B's body is smaller than 1.0 x ATR14",
    c_before_session_watermark: "candle C closed before this live session started (history: never ordered)",
    c_close_in_future: "candle C's close was in the future at decision time",
    decision_too_old: "candle C was more than 30 seconds old at the decision (never ordered late)",
    levels_invalid: "the zone is too narrow for three distinct limit prices",
    no_quote_for_eligibility_check: "no live quote was available for the spread/placement check",
    stop_within_spread: "a stop would sit inside the spread (needs spread + 1 tick)",
    limit_on_wrong_side_of_market: "a limit price was already on the wrong side of the market",
    engine_basket_open: "this engine already had an open or unresolved basket (one per engine)",
    cooldown: "less than 30 minutes since this engine's previous accepted basket",
    daily_cap: "4 baskets were already accepted today across both engines",
    concurrent_risk_cap: "the open baskets' planned risk would exceed one budget per engine",
    duplicate_basket: "a basket for this gap already existed",
  };
  const CHECKS = [
    ["Candles", ["history_not_ending_at_c"], "Three adjacent closed candles of this timeframe ending at C"],
    ["Trend warm-up", ["trend_warmup"], "At least 50 contiguous candles of this timeframe"],
    ["Trend direction", ["trend_flat", "trend_against"], "EMA20 vs EMA50 agrees with the gap direction"],
    ["ATR14", ["atr_warmup"], "ATR14 available through candle B"],
    ["Gap size", ["gap_too_small"], "Gap at least max(2 ticks, 0.10 x ATR14)"],
    ["Displacement", ["weak_displacement"], "Candle B body at least 1.0 x ATR14"],
    ["Timing", ["c_before_session_watermark", "c_close_in_future", "decision_too_old"], "C closed in this session and was at most 30 s old"],
    ["Levels and market", ["levels_invalid", "no_quote_for_eligibility_check", "stop_within_spread", "limit_on_wrong_side_of_market"],
      "Three distinct prices; stops outside the spread; limits on the resting side"],
    ["Capacity", ["engine_basket_open", "cooldown", "daily_cap", "concurrent_risk_cap", "duplicate_basket"],
      "Engine slot free, cooldown over, daily total and concurrent risk within limits"],
  ];
  const FILLED = new Set(["filled_open", "partially_filled", "filled", "closed_tp", "closed_sl", "closed_other"]);
  const ACCEPTED = new Set(["pending", "cancelled", "expired", ...FILLED]);
  const UNRESOLVED = new Set(["unknown", "sending", "prepared"]);
  const NOT_ACCEPTED = new Set(["rejected", "not_sent"]);
  const LEG_TEXT = { pending: "pending limit (waiting)", filled_open: "filled - position open", partially_filled: "partly filled",
    filled: "filled", closed_tp: "closed at TP", closed_sl: "closed at SL", closed_other: "closed (other)",
    cancelled: "cancelled", expired: "expired unfilled", unknown: "UNKNOWN - being reconciled, never resent",
    sending: "sending - outcome unknown", prepared: "prepared, not sent", rejected: "refused by the broker", not_sent: "not sent" };

  const reasonKey = (r) => String(r || "").split(" ", 1)[0].split(":", 1)[0];
  const SHORT = { trend_warmup: "trend warm-up", trend_against: "against trend", trend_flat: "flat trend", atr_warmup: "ATR warm-up",
    gap_too_small: "gap too small", weak_displacement: "weak candle B", decision_too_old: "too old (>30 s)",
    c_before_session_watermark: "before session start", stop_within_spread: "stop inside spread",
    limit_on_wrong_side_of_market: "limit on wrong side", engine_basket_open: "engine busy", cooldown: "cooldown",
    daily_cap: "daily cap reached", concurrent_risk_cap: "risk cap", levels_invalid: "zone too narrow",
    no_quote_for_eligibility_check: "no quote", history_not_ending_at_c: "history gap", duplicate_basket: "duplicate" };
  const short = (r) => (r ? SHORT[reasonKey(r)] || reasonKey(r).replace(/_/g, " ") : null);
  const explain = (r) => (r ? (REASON[reasonKey(r)] ? `${REASON[reasonKey(r)]}${reasonKey(r) !== r ? ` (${r})` : ""}` : r) : null);

  /** "symbol|a_open|version" -> parts (the stored setup key). */
  function parseKey(key) {
    const parts = String(key || "").split("|");
    if (parts.length < 3) return { symbol: null, a_open: null, version: null };
    return { symbol: parts[0], a_open: parts.slice(1, -1).join("|"), version: parts[parts.length - 1] };
  }

  /** Dual records of ONE engine only: engine field AND an engine version; legacy v1 never qualifies. */
  function recordsFor(engine, setups, limit = 12) {
    return (setups || []).filter((s) => s.engine === engine &&
      String(parseKey(s.key).version || "").startsWith(`FVG-Immediate-${engine}-`))
      .sort((a, b) => String(b.c_close).localeCompare(String(a.c_close))).slice(0, limit);
  }

  /** Baskets in this engine's slot: its own baskets, plus legacy v1 baskets (no engine) for the M15 slot. */
  function basketsFor(engine, baskets) {
    return (baskets || []).filter((b) => (b.engine ? b.engine === engine : engine === "M15"));
  }

  function legCounts(basket) {
    const legs = ((basket || {}).execution || {}).legs || [];
    const c = { total: legs.length, accepted: 0, filled: 0, unresolved: 0, notAccepted: 0 };
    for (const l of legs) {
      if (ACCEPTED.has(l.state)) c.accepted += 1;
      if (FILLED.has(l.state)) c.filled += 1;
      if (NOT_ACCEPTED.has(l.state)) c.notAccepted += 1;
      else if (UNRESOLVED.has(l.state) || !ACCEPTED.has(l.state)) c.unresolved += 1;
    }
    return c;
  }

  /** Broker-side state of the engine's slot (kept separate from the analysis state). */
  function brokerState(slot, basket) {
    if (!slot) return { label: "Slot free", tone: "light" };
    const ex = (basket || {}).execution || {};
    if (!basket) return { label: `Slot occupied (${slot.status})`, tone: "warning" };
    if (basket.status === "alert_only" || ex.state === "not_submitted") return { label: "Alert only (no orders)", tone: "light" };
    const c = legCounts(basket);
    if (!c.total) return { label: "Outcome unresolved", tone: "warning" };
    if (c.unresolved) return { label: "Outcome unresolved", tone: "warning" };
    if (c.filled) return { label: "Filled exposure", tone: "info" };
    // only legs pending NOW are resting limits (cancelled/expired ones were accepted earlier but are gone)
    const pending = (((basket || {}).execution || {}).legs || []).filter((l) => l.state === "pending").length;
    if (pending) {
      return { label: pending === c.total ? "Pending limits" : pending === c.accepted ? `Pending limits (${pending} of ${c.total} accepted)`
        : `Pending limits (${pending} of ${c.total} still pending)`, tone: "info" };
    }
    if (c.accepted) return { label: "No resting limit (cancelled/expired)", tone: "light" };
    return { label: "No limit accepted", tone: "error" };
  }

  /** Analysis-side state of one engine from readiness + the latest evaluation (never a signal by itself). */
  function analysisState(eng, feedOk) {
    if (!feedOk) return { label: "Unavailable (feed offline)", tone: "error" };
    const r = (eng || {}).readiness;
    if (!r) return { label: "No readiness yet", tone: "light" };
    if (!r.ready) return { label: "Warming up", tone: "warning" };
    const ev = eng.last_evaluation, ls = eng.last_setup;
    if (ev && ev.gap && ls && ls.c_close === ev.c_close && ls.status === "rejected") return { label: "FVG rejected", tone: "error" };
    if (ev && ev.gap && ls && ls.c_close === ev.c_close && ls.status === "accepted") return { label: "FVG accepted", tone: "success" };
    return { label: "Watching for FVG", tone: "info" };
  }

  /** The one-sentence next action from real evidence. fmtT formats ISO times. */
  function nextAction(engine, eng, ctx) {
    const fmt = ctx.fmtT || ((x) => x);
    if (!ctx.feedOk) return "Feed offline.";
    const r = (eng || {}).readiness;
    if (!r) return "Waiting for closed candles.";
    const slot = eng.slot;
    if (slot) return `Basket ${slot.basket}${slot.legacy ? " (legacy v1)" : ""} open · no new ${engine} basket until it resolves.`;
    if (!r.ready) return `Warming up: ${r.run}/${r.required} ${engine} candles${r.ready_eta ? ` · ready ~${fmt(r.ready_eta)} if no gap` : ""}.`;
    if (eng.cooldown_until) return `Cooldown until ${fmt(eng.cooldown_until)}.`;
    const ev = eng.last_evaluation;
    if (!ev) return `Ready · waiting for the next ${engine} close.`;
    if (!ev.gap) return `Ready · no FVG on the last ${engine} close.`;
    const why = ev.reason || ((eng.last_setup || {}).c_close === ev.c_close ? eng.last_setup.reason : null);
    return why ? `Last ${ev.gap.direction} gap rejected: ${short(why)}.` : `Last ${ev.gap.direction} gap qualified.`;
  }

  /** Per-check evidence for one stored record: only what the stored first failure proves. */
  function ruleChecks(rec) {
    const st = (rec || {}).status, key = reasonKey((rec || {}).reason);
    const out = [];
    let failedAt = -1;
    if (st === "rejected") failedAt = CHECKS.findIndex(([, keys]) => keys.includes(key));
    for (let i = 0; i < CHECKS.length; i++) {
      const [name, , text] = CHECKS[i];
      let state;
      if (st === "accepted") state = "passed";
      else if (st === "rejected" && failedAt === -1) state = "unavailable"; // reason not recognised: claim nothing
      else if (st === "rejected") state = i < failedAt ? "passed" : i === failedAt ? "failed" : "not_evaluated";
      else if (st === "qualified") state = i < 6 ? "passed" : "not_evaluated";
      else state = "unavailable";
      out.push({ name, state, detail: state === "failed" ? explain(rec.reason) : text });
    }
    return out;
  }

  /** Keep the user's selection if it still exists; otherwise the default. */
  function keepSelection(prevKey, records, defaultKey) {
    if (prevKey && records.some((r) => r.key === prevKey)) return prevKey;
    return defaultKey || (records[0] ? records[0].key : null);
  }

  /** Request generations: a response is applied only if no newer request of the same kind was started. */
  function latest() {
    let n = 0;
    return { next: () => ++n, current: (x) => x === n };
  }

  /** Leg rows from the stored basket and its execution journal (no journal -> not sized / not submitted). */
  function legRows(basket) {
    const ex = (basket || {}).execution || {};
    const planned = ex.legs || [];
    return ((basket || {}).legs || []).map((l, i) => {
      const p = planned[i] || null;
      return { n: l.n, pct: l.pct, entry: l.entry, sl: l.sl != null ? l.sl : basket.sl, tp: l.tp,
        volume: p && p.volume != null ? p.volume : null, plannedLoss: p ? p.planned_loss : null,
        state: p ? p.state : null, stateText: p ? (LEG_TEXT[p.state] || p.state) : (ex.state === "not_submitted" ? "not submitted (alert only)" : "not sized / not submitted"),
        details: p ? { ticket: p.ticket, filled_volume: p.filled_volume, pending_volume: p.pending_volume,
          retcode: p.retcode, cancel: p.cancel, note: p.note, comment: p.comment } : null };
    });
  }

  /** Compact trend label from readiness. */
  function trendText(r) {
    if (!r) return "—";
    if (!r.ready || !r.trend) return r.ready ? "Trend n/a" : "Trend warming up";
    return r.trend.startsWith("up") ? "Trend up · BUY only" : r.trend.startsWith("down") ? "Trend down · SELL only" : "Trend flat";
  }

  const pure = { ENGINES, parseKey, recordsFor, basketsFor, legCounts, brokerState, analysisState, nextAction, ruleChecks,
    keepSelection, latest, legRows, explain, short, trendText };
  if (!root || !root.document) return pure;

  // ------------------------------------------------------------------ browser
  const doc = root.document;
  const $ = (id) => doc.getElementById(id);
  const el = (tag, text, cls) => { const e = doc.createElement(tag); if (text != null) e.textContent = String(text); if (cls) e.className = cls; return e; };
  const S = { state: null, stateAt: null, failedAt: null, fvg: null, fvgAt: null, sel: {}, panels: {}, charts: {}, sig: {},
    fvgReq: latest(), loadingFvg: false, lastFvgFetch: 0 };
  const tz = () => ((S.state || {}).setup || {}).display_timezone || (S.state && S.state.display_timezone) || "UTC";
  const fmtT = (s) => (s && root.VCTime ? root.VCTime.format(s, tz()) : (s || "—"));
  const digits = () => (S.state && S.state.symbol && Number.isInteger(S.state.symbol.digits) ? S.state.symbol.digits : null);
  const fmtP = (v) => (v === null || v === undefined ? "—" : digits() === null ? String(v) : Number(v).toFixed(digits()));
  const CHIP = { success: "vc-chip-success", info: "vc-chip-info", warning: "vc-chip-warning", error: "vc-chip-error", light: "vc-chip-light" };
  const chip = (node, look) => { node.textContent = look.label; node.className = `vc-chip ${CHIP[look.tone] || CHIP.light}`; };
  const visible = () => root.VCNav && root.VCNav.current() === "engines";
  // the ACTIVE strategy decides whether the dual engines are selected; their summary only exists once the scanner has
  // built them (first healthy scan), so "selected but not running" is told apart from "not selected"
  const dualActive = () => !!(S.state && S.state.active_strategy && S.state.active_strategy.mode === "dual");
  const feedOk = () => !!(S.state && S.state.feed && S.state.feed.ok);

  async function getJSON(path) {
    const r = await fetch(path);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || d.error || `HTTP ${r.status}`);
    return d;
  }

  // ---------------------------------------------------------------- panels (built once; later updates are in place)
  function buildPanels() {
    const tpl = $("en-panel-tpl"), grid = $("en-panels");
    if (!tpl || !grid || S.panels.M15) return;
    for (const e of ENGINES) {
      const node = tpl.content.firstElementChild.cloneNode(true);
      node.id = `engine-${e}`;
      node.dataset.engine = e;
      const q = (role) => node.querySelector(`[data-role="${role}"]`);
      q("title").textContent = `${e} engine · ${e} candles`;
      q("chart").setAttribute("aria-label", `${e} candlestick chart (${e} only)`);
      q("reset").addEventListener("click", () => { const c = S.charts[e]; if (c) c.resetView(); });
      q("explain").addEventListener("click", () => {
        const key = S.sel[e];
        if (!key || !root.VCGuide || !root.VCNav) return;
        root.VCGuide.openRecord(key);
        root.VCNav.go("guide");
      });
      grid.append(node);
      S.panels[e] = { node, q };
    }
  }

  function setText(node, text) { if (node && node.textContent !== text) node.textContent = text; }

  function renderHeader() {
    const s = S.state;
    if (!s) return;
    const q = s.quote, sc = s.scanner || {};
    const src = "LIVE MT5";
    const stale = S.failedAt ? ` · REFRESH FAILED ${fmtT(S.failedAt)} · data from ${fmtT(S.stateAt)}` : "";
    setText($("en-header"), `${s.configured_symbol || (s.symbol || {}).name || "?"} · ${src} · ${feedOk() ? "feed ok" : "FEED OFFLINE"} · `
      + `${sc.error ? "SCANNER ERROR" : !sc.running ? "SCANNER STOPPED" : sc.paused ? "PAUSED" : "scanning"} · ${q && q.fresh ? "quotes fresh" : "QUOTES NOT FRESH"} · `
      + `${fmtT(sc.last_scan)}${stale}`);
    const f = s.fvg || {}, d = f.dual;
    const inactive = $("en-inactive");
    if (!d) {
      inactive.hidden = false;
      inactive.textContent = dualActive() ? `Engines not running: ${feedOk() ? "waiting for the first scan" : "feed offline"}.`
        : f.strategy_active ? "Dual engines inactive: legacy v1 FVG is the active strategy."
        : "Dual engines inactive: FVG is not the active strategy.";
    } else inactive.hidden = true;
    const auto = f.auto_execution === "ON";
    setText($("en-sum-auto"), auto ? `ON · ${f.armed_by === "you" ? "your arming" : f.armed_by === "default (demo account)" ? "demo-account default" : f.armed_by || "?"}` : `OFF · ${f.reason || "not armed"}`);
    setText($("en-sum-risk"), f.risk_usd != null ? `$${Number(f.risk_usd).toFixed(0)} per basket · max $${Number(f.max_concurrent_risk_usd || 2 * f.risk_usd).toFixed(0)}` : "not configured");
    $("en-sum-risk").title = "Planned stop-loss risk (nominal; fees, gaps and slippage can exceed it)";
    const busy = d ? ENGINES.filter((e) => (d.engines[e] || {}).slot).length : 0;
    setText($("en-sum-slots"), d ? `${busy}/2 occupied` : "—");
    setText($("en-sum-day"), d ? `${d.daily.accepted}/${d.daily.cap} baskets (both engines)` : "—");
    setText($("en-sum-cool"), d && d.scopes ? d.scopes.cooldown : "—");
  }

  function renderReadiness(p, e, eng) {
    const r = (eng || {}).readiness;
    const bar = p.q("bar"), pct = r ? Math.min(100, Math.round((100 * r.run) / Math.max(1, r.required))) : 0;
    bar.style.width = `${pct}%`;
    p.q("progress").setAttribute("aria-valuenow", String(r ? Math.min(r.run, r.required) : 0));
    p.q("progress").setAttribute("aria-valuemax", String(r ? r.required : 50));
    setText(p.q("run"), r ? (r.ready ? `${r.run} · ready` : `${r.run}/${r.required}`) : "—");
    p.q("run").title = r ? `${r.run} contiguous closed ${e} candles; ${r.required} needed` : "";
    setText(p.q("trend"), trendText(r));
    setText(p.q("atr"), r && r.atr14 != null ? String(r.atr14) : "—");
    setText(p.q("last"), r ? fmtT(r.last_close) : "—");
    setText(p.q("next-close"), r ? fmtT(r.next_close) : "—");
    setText(p.q("eta"), r && !r.ready && r.ready_eta ? `~${fmtT(r.ready_eta)} (if no data gap)` : r && r.ready ? "complete" : "—");
  }

  function selectedRecord(e) {
    const recs = recordsFor(e, (S.fvg || {}).setups);
    return { recs, rec: recs.find((r) => r.key === S.sel[e]) || null };
  }

  function renderDecision(p, e) {
    const { recs, rec } = selectedRecord(e);
    const box = p.q("decision");
    box.replaceChildren();
    const hist = rec && recs[0] && rec.key !== recs[0].key;
    setText(p.q("decision-kind"), !rec ? "" : hist ? "(historical selection)" : "(latest)");
    setText(p.q("zone"), !rec ? (S.fvg ? `No ${e} FVG recorded yet.` : "Loading…")
      : `${hist ? "Selected (historical)" : "Latest FVG"}: ${rec.direction} ${fmtP(rec.bottom)}–${fmtP(rec.top)} · ${rec.status}${rec.reason ? ` · ${short(rec.reason)}` : ""}`);
    if (!rec) {
      box.append(el("dd", S.fvg ? "No record." : "Loading…", "vc-muted col-span-2"));
      p.q("check-list").replaceChildren(el("li", "No stored record: no check is claimed.", "vc-muted"));
      return;
    }
    const k = parseKey(rec.key);
    const rows = [["Direction", rec.direction], ["Zone", `${fmtP(rec.bottom)} – ${fmtP(rec.top)}`], ["A opened", fmtT(k.a_open)],
      ["C closed", fmtT(rec.c_close)], ["Status", rec.status], ["Reason", explain(rec.reason) || (rec.status === "accepted" ? `accepted: basket ${rec.basket}` : "—")]];
    for (const [a, b] of rows) box.append(el("dt", a, "vc-muted"), el("dd", b, "break-words"));
    const list = p.q("check-list");
    list.replaceChildren();
    const look = { passed: "✓ passed", failed: "✗ failed", not_evaluated: "· not evaluated (stops at the first failure)", unavailable: "? not recorded" };
    for (const c of ruleChecks(rec)) {
      const li = el("li", null, `vc-rc vc-rc-${c.state}`);
      li.append(el("span", c.name, "font-semibold"), el("span", ` — ${look[c.state]}`), el("span", ` · ${c.detail}`, "vc-muted"));
      list.append(li);
    }
  }

  function renderBasket(p, e, eng) {
    const all = basketsFor(e, (S.fvg || {}).baskets);
    const slot = (eng || {}).slot;
    const open = slot ? all.find((b) => b.id === slot.basket) : null;
    const { rec } = selectedRecord(e);
    // the SELECTED record's own basket first (a historical pick shows its real levels), else the open slot basket
    const shown = (rec && rec.basket ? all.find((b) => b.id === rec.basket) : null) || open || null;
    chip(p.q("broker"), brokerState(slot, open));
    const legsBox = p.q("legs");
    const sig = JSON.stringify(shown ? [shown.id, shown.status, legRows(shown)] : null) + (digits() ?? "");
    setText(p.q("slot"), !S.fvg ? "Loading…" : slot ? `Slot: ${slot.basket} · ${slot.status}${slot.legacy ? " · legacy v1" : ""}`
      : `Slot free${eng && eng.cooldown_until ? ` · cooldown until ${fmtT(eng.cooldown_until)}` : ""}`);
    if (S.sig[`legs-${e}`] === sig) return; // unchanged: keep expanded legs and focus as they are
    S.sig[`legs-${e}`] = sig;
    const openLegs = new Set([...legsBox.querySelectorAll("details[open]")].map((d) => d.dataset.leg));
    legsBox.replaceChildren();
    if (!shown) return; // "Slot free" already says it: no basket, nothing sized or sent
    const ex = shown.execution || {};
    const c = legCounts(shown);
    const head = el("p", `${shown.id}${shown === open ? "" : " (selected, not the current slot)"} · ${c.total ? `${c.accepted}/${c.total} accepted · ${c.filled} filled${c.unresolved ? ` · ${c.unresolved} unresolved` : ""}` : shown.status}`, "text-[13px] font-semibold");
    head.title = `placed ${fmtT(shown.placed_at)} · pending orders expire ${fmtT(shown.pending_expires)}`;
    legsBox.append(head, el("p", `expires ${fmtT(shown.pending_expires)}`, "vc-faint text-[12px] mb-1"));
    for (const l of legRows(shown)) {
      const d = el("details", null, "vc-leg");
      d.dataset.leg = String(l.n);
      if (openLegs.has(String(l.n))) d.open = true;
      const risk = l.plannedLoss != null && root.VCFvgDisplay ? root.VCFvgDisplay.legRisk(l.plannedLoss, ex.account_currency) : null;
      const sum = el("summary", null, "vc-leg-summary");
      sum.append(el("span", `L${l.n} ${l.pct}%`, "font-semibold"), el("span", `entry ${fmtP(l.entry)} · SL ${fmtP(l.sl)} · TP ${fmtP(l.tp)}`, "vc-num"),
        el("span", l.volume != null ? `${l.volume} lot${risk ? ` · planned loss ${risk}` : ""}` : "not sized", "vc-num"), el("span", l.stateText, "vc-leg-state"));
      d.append(sum);
      const det = el("dl", null, "vc-leg-details");
      const dd = l.details || {};
      const rows = l.details ? [["Ticket", dd.ticket ?? "—"], ["Filled volume", dd.filled_volume ?? "—"], ["Pending volume", dd.pending_volume ?? "—"],
        ["Broker retcode", dd.retcode ?? "—"], ["Cancel", dd.cancel ?? "—"], ["Comment", dd.comment ?? "—"], ["Note", dd.note ?? "—"]]
        : [["Journal", "no execution journal row for this leg (nothing was sent)"]];
      for (const [a, b] of rows) det.append(el("dt", a, "vc-muted"), el("dd", b, "vc-num break-words"));
      d.append(det);
      legsBox.append(d);
    }
  }

  function renderHistory(p, e) {
    const { recs } = selectedRecord(e);
    const ul = p.q("history");
    const sig = JSON.stringify(recs.map((r) => [r.key, r.status, r.reason])) + "|" + S.sel[e] + "|" + !!S.fvg + "|" + (digits() ?? "");
    p.q("explain").disabled = !S.sel[e];
    p.q("explain").title = S.sel[e] ? "" : "No recorded setup for this engine yet";
    if (S.sig[`hist-${e}`] === sig) return;
    S.sig[`hist-${e}`] = sig;
    const focusedKey = ul.contains(doc.activeElement) ? doc.activeElement.dataset.key : null;
    ul.replaceChildren();
    if (!recs.length) { ul.append(el("li", S.fvg ? "No records for this engine yet." : "Loading…", "vc-muted text-[13px]")); return; }
    recs.forEach((r, i) => {
      const li = el("li");
      const b = el("button", null, `vc-rec${r.key === S.sel[e] ? " vc-rec-selected" : ""}`);
      b.type = "button";
      b.dataset.key = r.key;
      b.setAttribute("aria-pressed", String(r.key === S.sel[e]));
      b.append(el("span", fmtT(r.c_close), "vc-num"), el("span", `${r.direction} ${fmtP(r.bottom)}–${fmtP(r.top)}`, "vc-num"),
        el("span", r.status + (r.basket ? ` · ${r.basket}` : ""), r.status === "accepted" ? "vc-rec-ok" : "vc-muted"),
        el("span", i === 0 ? "latest" : "historical", "vc-rec-tag"));
      b.addEventListener("click", () => select(e, r.key));
      li.append(b);
      ul.append(li);
      if (focusedKey === r.key) b.focus();
    });
  }

  // ---------------------------------------------------------------- charts (one per engine, own timeframe)
  function ensureChart(e) {
    if (S.charts[e] || !root.VCMarketChart || !root.LightweightCharts) return S.charts[e] || null;
    const p = S.panels[e];
    const ch = new root.VCMarketChart.MarketChart(p.q("chart"), {
      api: getJSON, timezone: tz,
      onStatus: (st) => setText(p.q("chart-status"), st.kind === "ok" ? "" : st.kind === "loading" ? "Loading…" : st.text),
      onReadout: (bar, dg) => setText(p.q("readout"), bar ? `${e} ${fmtT(new Date(bar.time * 1000).toISOString())} · ${bar.forming ? "FORMING (not used by the engine)" : "closed"} · O ${Number(bar.open).toFixed(dg)} H ${Number(bar.high).toFixed(dg)} L ${Number(bar.low).toFixed(dg)} C ${Number(bar.close).toFixed(dg)}` : `${e}: no candle`),
    });
    S.charts[e] = ch;
    ch.load(e).then(() => overlay(e));
    return ch;
  }

  /** Stored strategy evidence on the engine's own chart: zone bounds, A/B/C, and stored basket levels only. */
  function overlay(e) {
    const ch = S.charts[e];
    if (!ch || !ch.chart || ch.mode !== "live") return;
    const { rec } = selectedRecord(e);
    const basket = rec && rec.basket ? basketsFor(e, (S.fvg || {}).baskets).find((b) => b.id === rec.basket) : null;
    const sig = JSON.stringify([rec && rec.key, basket && basket.id, ch.closed.length && ch.closed[0].time]);
    if (S.sig[`ov-${e}`] === sig) return;
    S.sig[`ov-${e}`] = sig;
    for (const l of ch.lines) ch.candles.removePriceLine(l);
    ch.lines = [];
    ch.markers.setMarkers([]);
    if (!rec) return;
    const css = (n) => getComputedStyle(doc.documentElement).getPropertyValue(n).trim();
    const LS = root.LightweightCharts.LineStyle;
    ch._line(rec.top, css("--zone-fvg"), "FVG top", LS.Dashed);
    ch._line(rec.bottom, css("--zone-fvg"), "FVG bottom", LS.Dashed);
    if (basket) {
      ch._line(basket.sl, css("--chart-sl"), "SL", LS.Solid);
      for (const l of basket.legs || []) {
        ch._line(l.entry, css("--chart-entry"), `L${l.n}`, LS.Dotted);
        ch._line(l.tp, css("--chart-tp"), `TP${l.n}`, LS.Dotted);
      }
    }
    const a = Math.floor(Date.parse(parseKey(rec.key).a_open) / 1000);
    const times = new Set(ch.closed.map((b) => b.time));
    const marks = ["A", "B", "C"].map((t, i) => ({ time: a + i * TF_SECONDS[e], position: "aboveBar", color: css("--chart-text"), shape: "square", text: t }))
      .filter((m) => times.has(m.time));
    ch.markers.setMarkers(marks);
    S.panels[e].q("chart").title = marks.length === 3 ? "" : "A/B/C are outside the loaded candles";
  }

  function select(e, key) {
    S.sel[e] = key;
    renderPanel(e);
  }

  function renderPanel(e) {
    const p = S.panels[e];
    if (!p) return;
    const d = ((S.state || {}).fvg || {}).dual;
    const eng = d ? d.engines[e] : null;
    chip(p.q("analysis"), d ? analysisState(eng, feedOk()) : dualActive() ? { label: feedOk() ? "Starting" : "Unavailable (feed offline)", tone: feedOk() ? "light" : "error" }
      : { label: "Inactive", tone: "light" });
    setText(p.q("next"), d ? nextAction(e, eng, { feedOk: feedOk(), fmtT }) : dualActive() ? (feedOk() ? "Waiting for the first scan." : "Feed offline.")
      : "The dual engines are not the active strategy.");
    renderReadiness(p, e, eng);
    const recs = recordsFor(e, (S.fvg || {}).setups);
    const slotBasket = eng && eng.slot ? basketsFor(e, (S.fvg || {}).baskets).find((b) => b.id === eng.slot.basket) : null;
    S.sel[e] = keepSelection(S.sel[e], recs, slotBasket && slotBasket.setup_key);
    renderDecision(p, e);
    renderBasket(p, e, eng);
    renderHistory(p, e);
    overlay(e);
  }

  function renderOverview() {
    const box = $("ov-engines");
    if (!box) return;
    const d = ((S.state || {}).fvg || {}).dual;
    box.hidden = !d;
    if (!d) return;
    for (const e of ENGINES) {
      const eng = d.engines[e];
      setText($(`ov-eng-${e}-state`), `${analysisState(eng, feedOk()).label} · ${brokerState(eng.slot, null).label}`);
      setText($(`ov-eng-${e}-next`), nextAction(e, eng, { feedOk: feedOk(), fmtT }));
    }
    setText($("ov-engines-day"), `${d.daily.accepted}/${d.daily.cap} baskets today (both engines)`);
  }

  /** The records note: a failure stays visible until a later CURRENT request succeeds; it keeps the last successful
   * data time apart from the failed refresh time and never implies records exist when none were ever loaded. */
  function recordsNote() {
    if (S.fvgErr) {
      return `Records refresh failed ${fmtT(S.fvgErrAt)} (${S.fvgErr}). `
        + (S.fvgAt ? `Showing records from ${fmtT(S.fvgAt)}.` : "No records have been loaded yet.");
    }
    return S.fvgAt ? `Records updated ${fmtT(S.fvgAt)}.` : "";
  }

  async function refreshFvg(force) {
    if (S.loadingFvg && !force) return;
    if (!force && Date.now() - S.lastFvgFetch < 8000) return;
    const my = S.fvgReq.next();
    S.loadingFvg = true;
    S.lastFvgFetch = Date.now();
    $("engines-section").setAttribute("aria-busy", "true");
    try {
      const data = await getJSON("/api/fvg?limit=200");
      if (!S.fvgReq.current(my)) return; // superseded: changes nothing
      S.fvg = data;
      S.fvgAt = new Date().toISOString();
      S.fvgErr = null; S.fvgErrAt = null; // recovered
      for (const e of ENGINES) renderPanel(e);
    } catch (err) {
      if (!S.fvgReq.current(my)) return; // a superseded failure changes nothing either
      S.fvgErr = err.message || String(err);
      S.fvgErrAt = new Date().toISOString();
    } finally {
      if (S.fvgReq.current(my)) {
        S.loadingFvg = false;
        $("engines-section").removeAttribute("aria-busy");
        setText($("en-records-note"), recordsNote());
      }
    }
  }

  function onState(ev) {
    S.state = ev.detail;
    S.stateAt = new Date().toISOString();
    S.failedAt = null;
    renderOverview();
    if (!visible()) return;
    renderHeader();
    for (const e of ENGINES) renderPanel(e);
    refreshFvg(false);
    for (const e of ENGINES) { const c = ensureChart(e); if (c && c.closed.length) c.poll().then(() => overlay(e)); }
  }

  function onStateError() {
    S.failedAt = new Date().toISOString();
    if (visible()) renderHeader();
  }

  /** Overview / System shortcuts: open the view and bring one engine panel into focus. */
  function focusEngine(e) {
    if (root.VCNav) root.VCNav.go("engines");
    const n = $(`engine-${e}`);
    if (n) {
      const smooth = !(root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches);
      n.scrollIntoView({ block: "start", behavior: smooth ? "smooth" : "auto" });
      n.focus({ preventScroll: true });
    }
  }

  function init() {
    if (!$("engines-section")) return;
    buildPanels();
    for (const e of ENGINES) {
      const b = $(`ov-eng-${e}`);
      if (b) b.addEventListener("click", () => focusEngine(e));
    }
    root.addEventListener("vc:state", onState);
    root.addEventListener("vc:state-error", onStateError);
    root.addEventListener("themechange", () => { for (const c of Object.values(S.charts)) c.applyTheme(); for (const e of ENGINES) S.sig[`ov-${e}`] = null; });
    if (root.VCNav) root.VCNav.onChange((k) => {
      if (k !== "engines") return;
      renderHeader();
      for (const e of ENGINES) { renderPanel(e); ensureChart(e); }
      refreshFvg(true);
    });
  }
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", init); else init();

  return { ...pure, focusEngine, refreshFvg };
});
