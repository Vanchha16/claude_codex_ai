"use strict";
// VC Signal dashboard behaviour (vanilla JS). Layout/theme/drawer state is handled by Alpine.js; styling uses the vc-* classes in frontend/src/input.css.
// The market chart lives in market-chart.js (TradingView Lightweight Charts); times are formatted by timefmt.js.
const TOKEN = document.querySelector('meta[name="session-token"]').content;
const $ = (id) => document.getElementById(id);
let STATE = null;
let selected = null; // {signal_id} | {candidate_id}
let selectedRec = null; // {signal?, candidate?}: last-known records for the detail card
let detailTab = "summary";
let LISTS = { signals: [], candidates: [] };
let CHART = null;
let setupDirty = false;

// Chart indicator preference (versioned, allowlisted booleans only; storage may be blocked).
const IND_KEY = "vcIndicators.v1";
const IND_DEFAULTS = { ema20: false, ema50: false, volume: false, fvg: true, ifvg: true, ob: true, bb: true };
function loadIndicators() {
  const out = { ...IND_DEFAULTS };
  try {
    const raw = JSON.parse(localStorage.getItem(IND_KEY) || "null");
    if (raw && typeof raw === "object") for (const k of Object.keys(IND_DEFAULTS)) if (typeof raw[k] === "boolean") out[k] = raw[k];
  } catch (e) { /* unreadable or blocked: defaults */ }
  return out;
}
function saveIndicators(p) { try { localStorage.setItem(IND_KEY, JSON.stringify(p)); } catch (e) { /* blocked: session only */ } }
// Zone display preference (render-only): {perType: 3|5|10, history: bool}; bounded by VCZones.normalizeDisplay.
const ZONE_DISPLAY_KEY = "vcZoneDisplay.v1";
function loadZoneDisplay() {
  let raw = null;
  try { raw = JSON.parse(localStorage.getItem(ZONE_DISPLAY_KEY) || "null"); } catch (e) { /* unreadable or blocked */ }
  return window.VCZones ? VCZones.normalizeDisplay(raw) : { perType: 3, history: false };
}
function saveZoneDisplay(d) { try { localStorage.setItem(ZONE_DISPLAY_KEY, JSON.stringify(d)); } catch (e) { /* blocked: session only */ } }
const ZONE_TYPES = ["FVG", "IFVG", "OB", "BB"];
function renderZoneCounts(z) {
  const box = $("zone-counts");
  box.title = "";
  if (!z || !z.counts) { box.textContent = "Zones: unavailable"; return; }
  if (!z.bars) { box.textContent = "Zones: no candle data"; return; }
  const total = ZONE_TYPES.reduce((n, t) => n + z.counts[t].total, 0);
  if (!total) { box.textContent = `Zones: none in the ${z.bars} loaded candles`; return; }
  // "shown/active": what is drawn vs what is currently active; ended zones only appear with History on
  box.textContent = "Shown / active: " + ZONE_TYPES.map((t) => {
    if (!z.visible[t]) return `${t} off`;
    const s = z.shown[t];
    return `${t} ${s.active}/${z.counts[t].active}${s.ended ? ` +${s.ended} ended` : ""}`;
  }).join(" \u00b7 ");
  box.title = ZONE_TYPES.map((t) => `${t}: ${z.visible[t] ? `${z.shown[t].active} active${z.shown[t].ended ? ` + ${z.shown[t].ended} ended` : ""} drawn`
    : "hidden"}; ${z.counts[t].active} active, ${z.counts[t].total} detected`).join("\n") +
    `\nFrom ${z.bars} closed candles. Drawing the newest ${z.display.perType} per type${z.display.history ? ", including ended zones" : " (active only)"}.`;
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (init.method !== "GET") {
    init.headers["X-Session-Token"] = TOKEN;
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body || {});
  }
  const r = await fetch(path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || data.error || `HTTP ${r.status}`);
  return data;
}

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined && text !== null) e.textContent = String(text);
  if (cls) e.className = cls;
  return e;
}
const tz = () => (STATE && STATE.setup && STATE.setup.display_timezone) || "UTC";
const fmtT = (s) => (s ? VCTime.format(s, tz()) : "—");
const fmtP = (v, d) => (v === null || v === undefined ? "—" : Number(v).toFixed(d));
const digits = () => (STATE && STATE.symbol ? STATE.symbol.digits : 2);

// Status chip variants (vc-chip-* in input.css)
const BADGE = { success: "vc-chip-success", error: "vc-chip-error", warning: "vc-chip-warning", info: "vc-chip-info",
  brand: "vc-chip-brand", light: "vc-chip-light" };
const TONE = {
  tp: "success", sent: "success", confirmed: "success", running: "success", fresh: "success",
  sl: "error", failed: "error", invalidated: "error", error: "error", stale: "error",
  unknown: "warning", ambiguous: "warning", pending: "info", active: "info", expired: "light", rejected: "light",
  paused: "warning", demo: "brand", mt5: "success",
};
const LABEL = { unknown: "UNKNOWN (not resent)", ambiguous: "AMBIGUOUS (excluded from win rate)" };
function badge(text, tone) {
  return el("span", LABEL[text] || text, `vc-chip ${BADGE[tone || TONE[text] || "light"]}`);
}
function setBadge(node, text, tone) {
  node.textContent = text;
  node.className = `vc-chip ${BADGE[tone] || BADGE.light}`;
}
function banner(msg) {
  const b = $("banner");
  b.hidden = !msg;
  b.textContent = msg || "";
}
function alertBanner(e) { banner(e.message || String(e)); }
function dotChip(node, text, tone) {
  node.className = `vc-chip ${BADGE[tone] || BADGE.light}`;
  node.replaceChildren(el("span", null, "vc-dot"), document.createTextNode(text));
}

// ------------------------------------------------------------------ state
async function refreshState() {
  try {
    STATE = await api("/api/state");
  } catch (e) {
    banner(`The dashboard cannot reach the local server: ${e.message}`);
    $("scanner-state").textContent = "unreachable";
    return;
  }
  const s = STATE;
  if (s.owner_error) { banner(s.owner_error); $("scanner-state").textContent = "not owner"; return; }
  setBadge($("mode-badge"), s.mode === "demo" ? "DEMO · fictional data" : "LIVE · MT5 data", s.mode);
  $("data-label").textContent = s.data_label;
  const act = s.active_strategy || {};
  const tfs = s.timeframes || {};
  $("page-strategy").textContent = `${tfs.range || "?"} / ${tfs.confirmation || "?"} · ${act.label || "?"}`;
  $("strategy-kicker").textContent = `Strategy state (${act.label || "?"})`;
  const fsOpt = $("replay-strategy").querySelector('option[value="fastsweep"]');
  if (fsOpt) fsOpt.textContent = act.kind === "fastsweep" ? `FastSweep (active: ${act.label})` : "FastSweep (research, 1:2)";
  const crtOpt = $("replay-strategy").querySelector('option[value="crt"]');
  if (crtOpt) crtOpt.textContent = act.kind === "crt" ? "CRT-SMC-v1 (active)" : "CRT-SMC-v1 (legacy, not active)";
  $("page-source").textContent = s.mode === "demo" ? "Demo fixture (fictional prices)" : "Live MT5 data (read-only)";
  $("btn-mode").textContent = s.mode === "demo" ? "Switch to live MT5…" : "Switch to demo…";
  $("btn-demo-restart").hidden = s.mode !== "demo";
  $("tz-label").textContent = tz() === "local" ? "this browser's time zone" : tz();

  const sym = s.symbol;
  const symName = sym ? sym.name : (s.configured_symbol || "no symbol selected");
  $("symbol").textContent = sym ? `${sym.name} (tick ${sym.tick_size}, ${sym.digits} digits, ${sym.source})` :
    (s.configured_symbol ? `${s.configured_symbol} (not loaded)` : "not selected (choose the exact symbol in Setup)");
  $("ov-symbol").textContent = sym ? `· ${sym.name}` : "";
  $("page-symbol").textContent = symName;
  $("chart-symbol").textContent = `· ${symName} · ${s.mode === "demo" ? "DEMO (fictional)" : "LIVE MT5"}`;
  const q = s.quote;
  $("quote").textContent = q ? `${fmtP(q.bid, digits())} / ${fmtP(q.ask, digits())}` : "—";
  $("spread").textContent = q ? `${fmtP(q.spread, digits())} (max ${s.strategy.max_spread_price})` : "—";
  if (q) setBadge($("quote-age"), `${q.age_seconds}s · ${q.fresh ? "fresh" : "NOT FRESH"}`, q.fresh ? "success" : "error");
  else setBadge($("quote-age"), "no quote", "light");
  $("quote-time").textContent = q ? fmtT(q.time) : "—";
  $("provider").textContent = s.provider || "—";
  const acct = s.account || {};
  $("broker").textContent = acct.server ? `${acct.company || "?"} · ${acct.server} (${acct.account_type || "?"} account)` :
    (s.mode === "demo" ? "— (demo fixture)" : "not connected");
  $("feed").textContent = s.feed ? s.feed.message : "—";
  const lc = (s.scanner && s.scanner.last_closed) || {};
  const ready = (s.strategy_state || {}).readiness;
  const closed = VCFvgDisplay.lastClosed((s.active_strategy || {}).kind, lc, ready, fmtT);
  $("last-closed-label").textContent = closed.label;
  $("last-closed").textContent = closed.value;

  const sc = s.scanner;
  $("scanner-state").textContent = sc.error ? "error" : !sc.running ? "stopped" : sc.paused ? "Paused" : "Running";
  $("scanner-state").title = sc.error || (sc.paused ? "No new candidates or alerts; outcome tracking continues" : "");
  $("btn-pause").textContent = sc.paused ? "Resume" : "Pause";
  $("last-scan").textContent = `${fmtT(sc.last_scan)}${s.demo ? " (simulated clock)" : ""}`;
  $("live-start").textContent = fmtT(sc.session_watermark || sc.live_start);
  $("issues").textContent = sc.data_issues && sc.data_issues.length ? sc.data_issues.join("; ") : (sc.error ? sc.error : "ok");
  const ss = s.strategy_state || {};
  $("strategy-state").textContent = ss.state || "—";
  $("strategy-detail").textContent = ss.detail || "";
  const feedOk = s.feed && s.feed.ok;
  if (sc.error) dotChip($("strategy-chip"), "Scanner error", "error");
  else if (!sc.running) dotChip($("strategy-chip"), "Stopped", "error");
  else if (sc.paused) dotChip($("strategy-chip"), "Paused", "warning");
  else if (!feedOk) dotChip($("strategy-chip"), "Feed offline", "error");
  else if (!q || !q.fresh) dotChip($("strategy-chip"), "Quotes not fresh", "warning");
  else dotChip($("strategy-chip"), s.mode === "demo" ? "Scanning · demo" : "Scanning · live", "success");

  renderTelegram(s.telegram || {}, s.setup || {});
  renderSetup(s.setup || {}, s);

  let warn = null;
  if (s.feed && !s.feed.ok) warn = s.feed.message;
  else if (q && !q.fresh) warn = q.note;
  else if (s.demo && s.demo.finished) warn = "Demo fixture finished. Press “Restart demo” to replay it.";
  else if (sc.error) warn = `Scanner error: ${sc.error}`;
  banner(warn);

  $("cfg-version").textContent = s.strategy.version;
  const dl = $("config");
  dl.replaceChildren();
  for (const [k, v] of Object.entries(s.strategy)) {
    if (k === "version") continue;
    dl.append(el("dt", k, "vc-muted"), el("dd", v, "vc-num break-words"));
  }
  $("btn-replay").disabled = s.replay_running;
  renderFvg(s.fvg || {}, act);
}

// ------------------------------------------------------------------ FVG automatic execution (default OFF)
const money = (v) => (v === null || v === undefined ? "—" : `$${Number(v).toFixed(2)}`);
let fvgBasketsAt = 0;
function renderFvg(f, act) {
  const on = f.auto_execution === "ON";
  dotChip($("fvg-auto"), on ? "Auto execution ON" : "Auto execution OFF", on ? "warning" : "light");
  $("fvg-strategy").textContent = f.strategy_active ? `active (${act.label || "FVG"})` : "inactive build (not the active strategy)";
  $("fvg-reason").textContent = on ? `armed ${fmtT(f.armed_at)}` : (f.reason || "OFF");
  $("fvg-budget").textContent = f.risk_configured ? `${money(f.risk_usd)} total planned SL risk per setup` : "not configured";
  $("fvg-share").textContent = f.risk_configured ? `${money(f.risk_usd / 3)} per leg before lot rounding` : "—";
  $("fvg-pct").textContent = f.risk_pct_of_equity !== null && f.risk_pct_of_equity !== undefined
    ? `${f.risk_pct_of_equity}% of equity (${money(f.equity_usd)}, account ${f.account_currency})` : "— (needs live MT5 account)";
  const canArm = !!(f.strategy_active && f.risk_configured && !on && STATE && STATE.mode === "mt5");
  $("btn-fvg-arm").disabled = !(canArm && $("fvg-confirm").checked);
  $("fvg-confirm").disabled = !canArm;
  $("btn-fvg-disarm").disabled = !on;
  $("fvg-baskets-wrap").classList.toggle("hidden", !f.strategy_active);
  if (f.strategy_active && Date.now() - fvgBasketsAt > 10000) {
    fvgBasketsAt = Date.now();
    api("/api/fvg?limit=20").then((r) => renderFvgBaskets(r.baskets || [])).catch(() => {});
  }
}

function renderFvgBaskets(baskets) {
  const body = $("fvg-baskets");
  body.replaceChildren();
  if (!baskets.length) {
    const tr = el("tr"); const td = el("td", "No baskets yet.", "vc-faint"); td.colSpan = 7; tr.append(td); body.append(tr);
    return;
  }
  const d = digits();
  for (const b of baskets) {
    const ex = b.execution || {};
    const planned = (ex.legs || []);
    const legs = (b.legs || []).map((l, i) => {
      const p = planned[i] || {};
      const lots = p.volume !== undefined ? `${p.volume} lot` : "not sized";
      const risk = VCFvgDisplay.legRisk(p.planned_loss, ex.account_currency);  // account units -> USD only when known
      const loss = risk ? ` · planned loss ${risk}` : "";
      return `${l.pct}%: ${fmtP(l.entry, d)} · TP ${fmtP(l.tp, d)} · ${lots}${loss}${p.state ? ` (${p.state})` : ""}`;
    }).join("\n");
    const tr = el("tr");
    const legCell = el("td", legs, "vc-num whitespace-pre-line");
    tr.append(el("td", fmtT(b.placed_at), "vc-num"), el("td", b.direction), el("td", `${fmtP(b.bottom, d)}–${fmtP(b.top, d)}`, "vc-num"),
      legCell, el("td", fmtP(b.sl, d), "vc-num"), el("td", b.status),
      el("td", `${ex.state || "—"}${ex.reason ? ` (${ex.reason})` : ""}`, "break-words"));
    body.append(tr);
  }
}

async function setFvgExecution(enabled) {
  $("fvg-msg").textContent = "";
  try {
    const r = await api("/api/fvg/execution", { method: "POST", body: { enabled, confirm: enabled ? $("fvg-confirm").checked : false } });
    $("fvg-msg").textContent = enabled ? "Automatic execution is ON for this binding." : "Automatic execution is OFF. Accepted orders keep their broker SL/TP.";
    $("fvg-confirm").checked = false;
    renderFvg(r, (STATE && STATE.active_strategy) || {});
  } catch (e) {
    $("fvg-msg").textContent = e.message;
  }
}

function renderTelegram(tg, setup) {
  $("tg-status").textContent = tg.state || "—";
  const v = tg.verified;
  $("tg-bot").textContent = setup.telegram_token === "configured"
    ? (v && v.bot ? `@${v.bot.username} (verified ${fmtT(v.checked_at)})` : `token configured (${(setup.origins || {}).telegram_bot_token || "server-side"}); not verified`)
    : "no bot token (add GOLD_TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN to .venv/.env)";
  $("tg-dest").textContent = setup.telegram_chat_id
    ? (v && v.chat ? `${v.chat.title || v.chat.id} (${v.chat.type})` : `${setup.telegram_chat_id}${v && v.chat_error ? ` — ${v.chat_error}` : " (not verified)"}`)
    : "missing: enter the destination chat ID in Setup";
  $("tg-delivery").textContent = tg.enabled ? (tg.persisted ? "ON (saved live opt-in)" : "ON (this session)") : "OFF";
  $("tg-enabled").checked = !!tg.enabled;
  $("tg-enabled").disabled = !tg.configured;
  $("btn-tg-test").disabled = !tg.configured;
  $("btn-tg-verify").disabled = !(setup.telegram_token === "configured" && setup.telegram_chat_id);
  $("tg-note").textContent = tg.note || "";
  $("sum-delivery").textContent = tg.configured ? `delivery ${tg.enabled ? "ON" : "OFF"}${tg.mode === "mt5" ? " · live" : " · demo"}`
    : `missing: ${(tg.missing || []).join(", ") || "setup"}`;
}

function renderSetup(setup, s) {
  const locked = new Set(setup.locked_by_environment || []);
  const fields = { "setup-source": "data_mode", "setup-symbol": "symbol", "setup-terminal": "mt5_terminal_path",
    "setup-chat": "telegram_test_chat_id", "setup-tz": "display_timezone" };
  for (const [id, key] of Object.entries(fields)) {
    $(id).disabled = locked.has(key);
    $(id).title = locked.has(key) ? "Set by the process environment" : "";
  }
  $("setup-token").textContent = setup.telegram_token === "configured"
    ? `configured from ${(setup.origins || {}).telegram_bot_token || "server-side configuration"} (value hidden)` : "missing";
  const acct = setup.account || {};
  $("setup-account").textContent = acct.server ? `MT5: ${acct.company || ""} · ${acct.server} · ${acct.account_type || ""}` : "";
  if (setupDirty) return; // don't overwrite what the user is editing
  $("setup-source").value = setup.data_mode || s.mode;
  $("setup-terminal").value = setup.mt5_terminal_path || "";
  $("setup-chat").value = setup.telegram_chat_id || "";
  $("setup-tz").value = setup.display_timezone || "UTC";
  fillSymbols(setup.candidates, setup.symbol);
}

function fillSymbols(candidates, current) {
  const sel = $("setup-symbol");
  const names = new Map();
  for (const c of candidates || []) names.set(c.name, `${c.name} — ${c.description || ""} (${c.digits} digits, tick ${c.tick_size})`);
  if (current && !names.has(current)) names.set(current, `${current} (current)`);
  const prev = sel.value || current || "";
  sel.replaceChildren(el("option", names.size ? "— choose the exact symbol —" : "— connect MT5 and press Find —"));
  sel.firstChild.value = "";
  for (const [name, label] of names) { const o = el("option", label); o.value = name; sel.append(o); }
  sel.value = names.has(prev) ? prev : "";
}

// ------------------------------------------------------------------ tables
function td(content, extra) {
  const cell = el("td", null, `whitespace-nowrap ${extra || ""}`);
  if (content instanceof Node) cell.append(content); else cell.textContent = content === null || content === undefined ? "—" : String(content);
  return cell;
}
function messageRow(table, cols, text, tone) {
  const tbody = $(table).querySelector("tbody");
  const tr = document.createElement("tr");
  tr.className = "vc-row-message";
  const cell = td(text, tone === "error" ? "vc-tone-error" : "");
  cell.colSpan = cols;
  tr.append(cell);
  tbody.replaceChildren(tr);
}
function selectable(tr, sel, label, rec) {
  tr.tabIndex = 0;
  tr.setAttribute("aria-label", label);
  tr.className = "vc-row-click";
  const pick = () => {
    selected = sel; selectedRec = rec; detailTab = rec.signal ? "signal" : "setup";
    renderDetail(); showSelected(true); refreshTables();
  };
  tr.addEventListener("click", pick);
  tr.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(); } });
}
const isSel = (sel) => selected && Object.entries(sel).every(([k, v]) => selected[k] === v);

async function refreshTables() {
  if (!STATE || STATE.owner_error) return;
  const sigQ = new URLSearchParams();
  if ($("f-sig-dir").value) sigQ.set("direction", $("f-sig-dir").value);
  if ($("f-sig-out").value) sigQ.set("outcome", $("f-sig-out").value);
  const candQ = new URLSearchParams();
  if ($("f-cand-status").value) candQ.set("status", $("f-cand-status").value);
  let sigs, all, cands, events, outbox;
  try {
    [sigs, all, cands, events, outbox] = await Promise.all([
      api(`/api/signals?${sigQ}`), api("/api/signals?limit=1000"), api(`/api/candidates?${candQ}`),
      api("/api/events?limit=80"), api("/api/outbox")]);
  } catch (e) {
    messageRow("signals", 11, `Could not load signals: ${e.message}`, "error");
    messageRow("candidates", 7, `Could not load setups: ${e.message}`, "error");
    return;
  }
  const outboxBySignal = {};
  for (const o of outbox) if (o.signal_id) outboxBySignal[o.signal_id] = o;
  renderSummary(all, outbox);

  const d = digits();
  const sb = $("signals").querySelector("tbody");
  if (!sigs.length) messageRow("signals", 11, all.length ? "No signals match the filters." : "No confirmed signals yet. No eligible setup is a valid result.");
  else {
    sb.replaceChildren();
    for (const s of sigs) {
      const tr = document.createElement("tr");
      selectable(tr, { signal_id: s.id }, `Chart signal ${s.id}`, { signal: s });
      if (isSel({ signal_id: s.id })) { tr.classList.add("vc-row-selected"); tr.setAttribute("aria-selected", "true"); }
      const ob = outboxBySignal[s.id];
      const del = ob ? badge(ob.status) : badge(STATE.telegram && STATE.telegram.enabled ? "not queued" : "dashboard only", "light");
      if (ob && ob.last_error) del.title = ob.last_error;
      const prev = el("button", "View", "vc-btn h-7 px-2.5 text-[12px]");
      prev.type = "button";
      prev.setAttribute("aria-label", `Preview Telegram message for ${s.id}`);
      prev.onclick = (ev) => { ev.stopPropagation(); showPreview(s.id); };
      const outcome = badge(s.outcome_status);
      if (s.measurement_gaps) outcome.title = `${s.measurement_gaps} tick-history gap(s) recorded`;
      tr.append(td(s.id, "font-medium"),
        td(s.direction, s.direction === "BUY" ? "vc-buy" : "vc-sell"),
        td(fmtP(s.entry, d), "vc-num"), td(fmtP(s.sl, d), "vc-num"), td(fmtP(s.tp, d), "vc-num"), td(s.reward_risk, "vc-num"), td(fmtT(s.confirm_close), "vc-num"),
        td(outcome), td(s.outcome_r === null ? "—" : s.outcome_r), td(del), td(prev));
      tr.title = s.outcome_note || s.explanation;
      sb.append(tr);
    }
  }

  const cb = $("candidates").querySelector("tbody");
  if (!cands.length) messageRow("candidates", 7, $("f-cand-status").value ? "No setups in this state." : "No setups recorded yet.");
  else {
    cb.replaceChildren();
    for (const c of cands) {
      const tr = document.createElement("tr");
      if (c.direction && c.level !== null) {
        selectable(tr, { candidate_id: c.id }, `Chart ${c.direction} setup with A candle ${fmtT(c.a_open)}`, { candidate: c });
        if (isSel({ candidate_id: c.id })) { tr.classList.add("vc-row-selected"); tr.setAttribute("aria-selected", "true"); }
      }
      const sweep = c.direction === "BUY" ? c.b_low : c.direction === "SELL" ? c.b_high : null;
      tr.append(td(fmtT(c.a_open) + (c.warmup ? " (warm-up)" : ""), "vc-num"),
        td(c.direction || "—", c.direction === "BUY" ? "vc-buy" : c.direction === "SELL" ? "vc-sell" : "vc-muted"),
        td(`${fmtP(c.a_low, d)} – ${fmtP(c.a_high, d)}`, "vc-num"), td(sweep === null ? "—" : fmtP(sweep, d), "vc-num"),
        td(c.level === null ? "—" : fmtP(c.level, d), "vc-num"), td(badge(c.status)), td(c.reason || "", "vc-muted"));
      cb.append(tr);
    }
  }

  const ul = $("events");
  ul.replaceChildren();
  if (!events.length) ul.append(el("li", "No events yet.", "vc-muted py-1.5"));
  for (const e of events) {
    const tone = e.level === "error" ? "text-[var(--vc-danger)]" : e.level === "warning" ? "text-[var(--vc-warning)]" : "";
    const li = el("li", null, `flex gap-3 border-b border-[var(--vc-border)] py-2 last:border-b-0 ${tone}`);
    li.append(el("span", fmtT(e.at), "vc-faint vc-num shrink-0"), el("span", `${e.kind}: ${e.message}`, "min-w-0 break-words"));
    ul.append(li);
  }

  LISTS = { signals: all, candidates: cands };
  if (selectedRec && selectedRec.signal) selectedRec.signal = all.find((x) => x.id === selectedRec.signal.id) || selectedRec.signal;
  if (selectedRec && selectedRec.candidate) selectedRec.candidate = cands.find((x) => x.id === selectedRec.candidate.id) || selectedRec.candidate;
  renderDetail();
}

function renderSummary(all, outbox) {
  const count = (k) => all.filter((s) => s.outcome_status === k).length;
  $("sum-signals").textContent = `Signals: ${all.length} total · ${count("active")} active`;
  $("sum-outcomes").textContent = `TP ${count("tp")} · SL ${count("sl")} · expired ${count("expired")} · ambiguous ${count("ambiguous")} (simulated)`;
  const by = (k) => outbox.filter((o) => o.status === k).length;
  if (outbox.length) $("sum-delivery").textContent += ` · sent ${by("sent")} · failed ${by("failed")} · UNKNOWN ${by("unknown")}`;
}

// ------------------------------------------------------------------ detail card + evidence
// Everything shown here is read from VC Signal's own records (state, signals, setups). Nothing is generated or scored.
function kv(rows) {
  const dl = el("dl", null, "grid grid-cols-[max-content_minmax(0,1fr)] gap-x-5 gap-y-2 text-[13px]");
  for (const [k, v, cls] of rows) {
    const dd = el("dd", null, `break-words ${cls || ""}`);
    if (v instanceof Node) dd.append(v); else dd.textContent = v === null || v === undefined || v === "" ? "—" : String(v);
    dl.append(el("dt", k, "vc-muted"), dd);
  }
  return dl;
}
function detailHint(text) { return el("p", text, "vc-muted"); }
const sideNode = (dir) => el("span", dir || "—", dir === "BUY" ? "vc-buy" : dir === "SELL" ? "vc-sell" : "vc-muted");
function linkedCandidate(sig) { return sig && LISTS.candidates.find((c) => c.key === sig.candidate_key) || null; }
function currentRecords() {
  const sig = selectedRec && selectedRec.signal || null;
  const cand = selectedRec && selectedRec.candidate || (sig ? linkedCandidate(sig) : null);
  return { sig, cand };
}
function setupRows(c, d) {
  const sweep = c.direction === "BUY" ? c.b_low : c.direction === "SELL" ? c.b_high : null;
  return [["Side", sideNode(c.direction)], ["State", badge(c.status)], ["Reason", c.reason],
    ["Strategy", `${c.strategy || "CRT-SMC-v1"} (${c.config_version})`, "vc-faint"],
    [`A candle (${c.range_tf || "H1"})`, fmtT(c.a_open) + (c.warmup ? " (warm-up)" : ""), "vc-num"],
    ["A range", `${fmtP(c.a_low, d)} – ${fmtP(c.a_high, d)}`, "vc-num"],
    ["B candle closed", fmtT(c.b_close), "vc-num"], ["B sweep extreme", sweep === null ? "—" : fmtP(sweep, d), "vc-num"],
    ["Structure level (M5)", c.level === null ? "—" : fmtP(c.level, d), "vc-num"],
    ["Pivot", c.pivot_time ? `${fmtT(c.pivot_time)} (usable ${fmtT(c.pivot_available)})` : "—", "vc-num"],
    ["Confirm deadline", fmtT(c.deadline), "vc-num"], ["Confirmed at", fmtT(c.confirm_close), "vc-num"],
    ["Config", c.config_version, "vc-faint"]];
}
function signalRows(s, d) {
  return [["Signal", s.id, "font-medium"], ["Side", sideNode(s.direction)], ["Entry", fmtP(s.entry, d), "vc-num"],
    ["Stop loss", fmtP(s.sl, d), "vc-num"], ["Take profit", fmtP(s.tp, d), "vc-num"], ["Reward : risk", s.reward_risk, "vc-num"],
    ["Bid / Ask at signal", `${fmtP(s.bid, d)} / ${fmtP(s.ask, d)} (spread ${fmtP(s.spread, d)})`, "vc-num"],
    ["Confirmed M5 close", fmtT(s.confirm_close), "vc-num"], ["Valid until", fmtT(s.valid_until), "vc-num"],
    ["Outcome (simulated)", badge(s.outcome_status)],
    ["Outcome price / time", s.outcome_time ? `${fmtP(s.outcome_price, d)} at ${fmtT(s.outcome_time)}` : "—", "vc-num"],
    ["R", s.outcome_r === null ? "—" : s.outcome_r, "vc-num"],
    ["Duration", s.duration_minutes === null ? "—" : `${s.duration_minutes} min`, "vc-num"],
    ["Note", s.outcome_note || ""], ["Config", s.config_version, "vc-faint"]];
}
function renderDetail() {
  const body = $("detail-body");
  if (!body) return;
  for (const b of $("detail-tabs").children) b.setAttribute("aria-selected", String(b.dataset.tab === detailTab));
  const d = digits();
  const { sig, cand } = currentRecords();
  const scope = $("detail-scope");
  if (sig) setBadge(scope, `Signal ${sig.id}`, "brand");
  else if (cand) setBadge(scope, `Setup #${cand.id}`, "brand");
  else setBadge(scope, "Live market", "light");

  const s = STATE || {};
  const ss = s.strategy_state || {};
  const live = ss.candidate || null; // the pending setup the scanner is waiting on, if any
  let content;
  if (detailTab === "summary") {
    if (sig) {
      content = el("div");
      content.append(el("p", `${sig.direction} ${sig.symbol || ""} · entry ${fmtP(sig.entry, d)}, SL ${fmtP(sig.sl, d)}, TP ${fmtP(sig.tp, d)} (R:R ${sig.reward_risk}).`, "font-medium"));
      if (sig.explanation) content.append(el("p", sig.explanation, "vc-muted mt-2"));
      const o = el("p", null, "mt-3 flex flex-wrap items-center gap-2");
      o.append(el("span", "Simulated outcome", "vc-muted text-[13px]"), badge(sig.outcome_status));
      if (sig.outcome_r !== null) o.append(el("span", `${sig.outcome_r} R`, "vc-num text-[13px]"));
      content.append(o);
    } else if (cand) {
      content = el("div");
      content.append(el("p", `${cand.direction || "Non-directional"} setup · A candle ${fmtT(cand.a_open)}`, "font-medium"));
      const o = el("p", null, "mt-2 flex flex-wrap items-center gap-2");
      o.append(badge(cand.status));
      if (cand.reason) o.append(el("span", cand.reason, "vc-muted text-[13px]"));
      content.append(o);
    } else {
      content = el("div");
      content.append(el("p", ss.state || "—", "font-medium capitalize"), el("p", ss.detail || "", "vc-muted mt-1"));
      const q = s.quote;
      content.append(el("div", null, "mt-3"));
      content.lastChild.append(kv([
        ["Bid / Ask", q ? `${fmtP(q.bid, d)} / ${fmtP(q.ask, d)}` : "—", "vc-num"],
        ["Spread", q ? `${fmtP(q.spread, d)} (max ${(s.strategy || {}).max_spread_price ?? "—"})` : "—", "vc-num"],
        ["Feed", s.feed ? s.feed.message : "—"]]));
      content.append(el("p", "Select a signal or setup row to inspect its record.", "vc-faint mt-3 text-[12px]"));
    }
  } else if (detailTab === "setup") {
    if (cand) content = kv(setupRows(cand, d));
    else if (live) content = kv([["Live pending setup", sideNode(live.direction)], ["A range", `${fmtP(live.a_low, d)} – ${fmtP(live.a_high, d)}`, "vc-num"],
      ["Sweep extreme", fmtP(live.sweep_extreme, d), "vc-num"], ["Frozen level", fmtP(live.level, d), "vc-num"],
      ["B candle closed", fmtT(live.b_close), "vc-num"], ["Confirm deadline", fmtT(live.deadline), "vc-num"]]);
    else content = detailHint(sig ? "This signal's setup is not in the current Setups list (check the state filter)." : "No setup selected and none pending. Select a row in Setups.");
  } else {
    content = sig ? kv(signalRows(sig, d)) : detailHint(cand ? "This setup has no signal selected. Select a row in Signals." : "No signal selected. Select a row in Signals.");
  }
  body.replaceChildren(content);
  renderEvidence(sig, cand, live, d);
}
function evidenceGroup(title, color, items) {
  const g = el("div", null, "vc-evidence-group");
  g.style.setProperty("--evidence", color);
  g.append(el("p", title, "vc-evidence-head"));
  const ul = el("ul");
  for (const it of items) if (it) ul.append(el("li", it));
  g.append(ul);
  return g;
}
function renderEvidence(sig, cand, live, d) {
  const box = $("evidence");
  const s = STATE || {};
  const groups = [];
  const c = cand || (!sig && live ? { direction: live.direction, a_low: live.a_low, a_high: live.a_high, level: live.level,
    deadline: live.deadline, b_close: live.b_close, sweep: live.sweep_extreme, status: "pending" } : null);
  if (c) {
    const sweep = c.sweep ?? (c.direction === "BUY" ? c.b_low : c.direction === "SELL" ? c.b_high : null);
    groups.push(evidenceGroup(`Range · ${c.range_tf || (STATE && STATE.timeframes ? STATE.timeframes.range : "H1")}`, "var(--vc-info)", [
      `A range ${fmtP(c.a_low, d)} – ${fmtP(c.a_high, d)}`,
      sweep !== null && sweep !== undefined ? `B swept ${c.direction === "BUY" ? "below the low" : "above the high"} to ${fmtP(sweep, d)}` : "No sweep recorded",
      c.b_close ? `B closed ${fmtT(c.b_close)}` : null]));
    groups.push(evidenceGroup(c.strategy === "FastSweep" ? "Confirmation · M5 (break of B)" : "Structure · M5", "var(--vc-primary)", [
      c.level !== null && c.level !== undefined ? `Level ${fmtP(c.level, d)}` : "No structure level",
      c.confirm_close ? `Confirmed by M5 close ${fmtT(c.confirm_close)}` : c.deadline ? `Confirmation deadline ${fmtT(c.deadline)}` : null,
      `State: ${c.status}${c.reason ? ` — ${c.reason}` : ""}`]));
  }
  if (sig) {
    groups.push(evidenceGroup("Risk", "var(--vc-warning)", [
      `Entry ${fmtP(sig.entry, d)} · SL ${fmtP(sig.sl, d)} · TP ${fmtP(sig.tp, d)}`,
      `Reward : risk ${sig.reward_risk}`, `Spread at signal ${fmtP(sig.spread, d)}`]));
    const tone = sig.outcome_status === "tp" ? "var(--vc-success)" : sig.outcome_status === "sl" ? "var(--vc-danger)" : "var(--vc-muted)";
    groups.push(evidenceGroup("Outcome · simulated", tone, [
      `Status ${LABEL[sig.outcome_status] || sig.outcome_status}${sig.outcome_r !== null ? ` · ${sig.outcome_r} R` : ""}`,
      sig.outcome_note || null, sig.measurement_gaps ? `${sig.measurement_gaps} tick-history gap(s) recorded` : null]));
  }
  if (!sig && !cand) {
    const sc = s.scanner || {};
    const q = s.quote;
    groups.push(evidenceGroup("Data checks", s.feed && s.feed.ok ? "var(--vc-success)" : "var(--vc-danger)", [
      s.feed ? `Feed: ${s.feed.message}` : "Feed: —",
      q ? `Quote ${q.fresh ? "fresh" : "NOT fresh"} (${q.age_seconds}s old)` : "No quote",
      sc.data_issues && sc.data_issues.length ? `Issues: ${sc.data_issues.join("; ")}` : "No data issues reported"]));
    groups.push(evidenceGroup("Session", "var(--vc-info)", [
      `Eligible since ${fmtT(sc.session_watermark || sc.live_start)}`,
      (() => { const c = VCFvgDisplay.lastClosed((s.active_strategy || {}).kind, sc.last_closed, (s.strategy_state || {}).readiness, fmtT);
        return `${c.label}: ${c.value}`; })(),
      sc.paused ? "Scanner paused: no new setups or alerts" : null]));
  }
  if (!groups.length) { box.replaceChildren(detailHint("No evidence for this selection.")); return; }
  box.replaceChildren(...groups);
}
for (const b of $("detail-tabs").children) b.onclick = () => { detailTab = b.dataset.tab; renderDetail(); };

async function showPreview(id) {
  const wrap = $("msg-preview-wrap"), p = $("msg-preview");
  try {
    const r = await api(`/api/signals/${encodeURIComponent(id)}/message`);
    p.textContent = `${r.text}\n\n— ${r.note}`;
  } catch (e) { p.textContent = `Could not load the message: ${e.message}`; }
  wrap.hidden = false;
  wrap.scrollIntoView({ block: "nearest", behavior: "smooth" });
}
$("btn-close-preview").onclick = () => { $("msg-preview-wrap").hidden = true; };

// ------------------------------------------------------------------ chart
function initChart() {
  if (!window.LightweightCharts || !window.VCMarketChart) {
    $("chart-status").textContent = "Chart library failed to load.";
    return;
  }
  CHART = new VCMarketChart.MarketChart($("lw-chart"), {
    api, timezone: tz,
    onStatus: (st) => {
      $("chart-status").textContent = st.text;
      $("chart-status").className = `mt-0.5 text-[12px] ${st.kind === "error" || st.kind === "unavailable" ? "text-[var(--vc-danger)]" : "vc-muted"}`;
      styleTfButtons(st.tf);
      $("ind-volume").disabled = !st.hasVolume;
      $("ind-volume").parentElement.title = st.hasVolume ? "" : "No tick volume from this source";
      $("btn-chart-live").textContent = st.mode === "setup" ? "Back to live" : "Live";
    },
    onZones: renderZoneCounts,
    onReadout: (b, d) => {
      $("ohlc-readout").textContent = b ? `${VCTime.format(b.time, tz(), false)}  O ${fmtP(b.open, d)}  H ${fmtP(b.high, d)}  L ${fmtP(b.low, d)}  C ${fmtP(b.close, d)}` +
        (typeof b.volume === "number" ? `  tick vol ${b.volume}` : "") + (b.forming ? "  (forming candle)" : "") : "—";
    },
  });
  const group = $("tf-buttons");
  for (const [tf, label] of Object.entries(VCMarketChart.TF_LABEL)) {
    const b = el("button", label);
    b.type = "button"; b.dataset.tf = tf; b.setAttribute("aria-pressed", "false");
    b.onclick = () => { selected = null; selectedRec = null; renderDetail(); CHART.load(tf); };
    group.append(b);
  }
  styleTfButtons("M5");
  const prefs = loadIndicators();
  for (const name of Object.keys(IND_DEFAULTS)) {
    $(`ind-${name}`).checked = prefs[name];
    CHART.setIndicator(name, prefs[name]);
    $(`ind-${name}`).onchange = (ev) => { prefs[name] = ev.target.checked; saveIndicators(prefs); CHART.setIndicator(name, ev.target.checked); };
  }
  const zoneDisplay = loadZoneDisplay();
  $("zone-cap").value = String(zoneDisplay.perType);
  $("zone-history").checked = zoneDisplay.history;
  CHART.setZoneDisplay(zoneDisplay);
  const onZoneDisplay = () => {
    const d = window.VCZones ? VCZones.normalizeDisplay({ perType: Number($("zone-cap").value), history: $("zone-history").checked })
      : zoneDisplay;
    saveZoneDisplay(d);
    CHART.setZoneDisplay(d);
  };
  $("zone-cap").onchange = onZoneDisplay;
  $("zone-history").onchange = onZoneDisplay;
  $("btn-chart-reset").onclick = () => CHART.resetView();
  $("btn-chart-live").onclick = () => { selected = null; selectedRec = null; renderDetail(); CHART.returnLive(); refreshTables(); };
  $("btn-chart-full").onclick = toggleExpand;
  document.addEventListener("fullscreenchange", () => {
    const on = document.fullscreenElement === $("chart-card");
    $("btn-chart-full").textContent = on ? "Exit full screen" : "Expand";
    $("btn-chart-full").setAttribute("aria-pressed", String(on));
  });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && $("chart-card").classList.contains("chart-expanded")) toggleExpand(); });
  window.addEventListener("themechange", () => CHART.applyTheme());
  CHART.load("M5");
}
function styleTfButtons(active) {
  for (const b of $("tf-buttons").children) {
    const on = b.dataset.tf === active;
    b.setAttribute("aria-pressed", String(on)); // styled by .vc-seg > button[aria-pressed]
  }
}
async function toggleExpand() {
  const card = $("chart-card");
  if (document.fullscreenElement) { await document.exitFullscreen(); return; }
  if (card.classList.contains("chart-expanded")) {
    card.classList.remove("chart-expanded");
    $("btn-chart-full").textContent = "Expand"; $("btn-chart-full").setAttribute("aria-pressed", "false");
    return;
  }
  if (card.requestFullscreen) {
    try { await card.requestFullscreen(); return; } catch (e) { /* fall back to an in-page expanded panel */ }
  }
  card.classList.add("chart-expanded");
  $("btn-chart-full").textContent = "Close expanded chart"; $("btn-chart-full").setAttribute("aria-pressed", "true");
}
async function showSelected(open) {
  if (!selected || !CHART) return;
  if (open) VCNav.go("chart"); // switch to the Chart view first, then draw the record's overlays there
  const q = selected.signal_id ? `signal_id=${encodeURIComponent(selected.signal_id)}` : `candidate_id=${selected.candidate_id}`;
  try {
    const rec = await api(`/api/chart?${q}`);
    await CHART.showSetup(rec);
  } catch (e) { $("chart-status").textContent = `Chart unavailable: ${e.message}`; }
}

// ------------------------------------------------------------------ replay
async function refreshReplay() {
  const box = $("replay");
  const source = $("replay-source").value;
  const strategy = $("replay-strategy").value;
  let r;
  try { r = await api(`/api/replay?source=${source}&strategy=${strategy}`); } catch (e) {
    box.replaceChildren(el("p", `Could not load the replay summary: ${e.message}`, "text-[var(--vc-danger)]"));
    return;
  }
  const frag = document.createDocumentFragment();
  if (STATE && STATE.replay_error) frag.append(el("p", `Last replay failed: ${STATE.replay_error}`, "mb-2 text-[var(--vc-danger)]"));
  if (!r.available) { frag.append(el("p", r.hint, "vc-muted")); box.replaceChildren(frag); return; }
  const res = r.result;
  if (strategy === "fastsweep") { renderFastSweepReplay(res, frag); box.replaceChildren(frag); return; }
  frag.append(el("p", `CRT-SMC-v1 replay (${res.config_version || "legacy"}) — shown for reference; it is not the FastSweep strategy`, "vc-faint text-[12px]"));
  frag.append(el("p", `${res.data_label}`, "font-medium"));
  frag.append(el("p", `Period ${fmtT(res.period.start)} → ${fmtT(res.period.end)} · ${res.period.m5_bars} M5 / ${res.period.h1_bars} H1 bars · holdout from ${fmtT(res.split_at)}`, "vc-muted vc-num mt-1 text-[12px]"));
  frag.append(el("p", `Costs: ${res.costs}`, "vc-faint mt-1 text-[12px]"));
  const grid = el("div", null, "mt-4 grid grid-cols-1 gap-4 md:grid-cols-2");
  for (const [name, seg] of Object.entries(res.segments)) {
    const card = el("div", null, "vc-inset p-4");
    const head = el("div", null, "mb-3 flex items-center justify-between gap-2");
    head.append(el("h3", name === "holdout" ? "Held-out validation (last 30%)" : "Development", "vc-card-title"),
      badge(name === "holdout" ? "holdout" : "in-sample", name === "holdout" ? "brand" : "light"));
    card.append(head);
    const dl = el("dl", null, "grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[12px]");
    const rows = [["Setups", `${seg.candidates} (${Object.entries(seg.candidates_by_status).map(([k, v]) => `${k} ${v}`).join(", ") || "none"})`],
      ["Signals", seg.signals], ["Outcomes", Object.entries(seg.outcomes).map(([k, v]) => `${k} ${v}`).join(", ") || "none"],
      ["Win rate", seg.win_rate === null ? "n/a" : `${(seg.win_rate * 100).toFixed(1)}%`], ["Denominator", seg.win_rate_denominator],
      ["Mean R", seg.mean_r ?? "n/a"], ["Max drawdown (R)", seg.max_drawdown_r]];
    for (const [k, v] of rows) dl.append(el("dt", k, "vc-muted"), el("dd", v, "vc-num break-words"));
    card.append(dl); grid.append(card);
  }
  frag.append(grid);
  const ul = el("ul", null, "vc-muted mt-4 list-disc space-y-1 pl-5 text-[12px]");
  for (const l of res.limitations) ul.append(el("li", l));
  frag.append(ul);
  box.replaceChildren(frag);
}

function renderFastSweepReplay(res, frag) {
  const f = (res.frequency || {}).covered_dates_ge_12h || {};
  frag.append(el("p", `${res.strategy} — OHLC simulation (no tick replay); never touches live records`, "vc-faint text-[12px]"));
  frag.append(el("p", res.data_label || `${res.period.m5_bars} M5 bars`, "font-medium"));
  frag.append(el("p", `Period ${fmtT(res.period.start)} → ${fmtT(res.period.end)} · ${res.period.m5_bars} M5 / ${res.period.m15_bars} M15 bars · later segment from ${fmtT(res.split_at)}`, "vc-muted vc-num mt-1 text-[12px]"));
  frag.append(el("p", `Costs: spread ${res.costs.spread}, slippage ${res.costs.slippage} (price units)`, "vc-faint mt-1 text-[12px]"));
  frag.append(el("p", f.dates ? `Signals per covered Bangkok date (>= 12 h data, ${f.dates} dates): mean ${f.mean}, median ${f.median}; 3–4 signals on ${f.pct_3_to_4}% of dates (a cap of 4, not a quota)` : "No covered dates", "mt-2 text-[13px]"));
  const grid = el("div", null, "mt-4 grid grid-cols-1 gap-4 md:grid-cols-3");
  for (const [name, seg] of Object.entries(res.segments)) {
    const card = el("div", null, "vc-inset p-4");
    card.append(el("h3", name === "later" ? "Later 30% (comparison)" : name === "earlier" ? "Earlier 70%" : "Whole period", "vc-card-title mb-3"));
    const dl = el("dl", null, "grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[12px]");
    const rows = [["Setups", seg.candidates], ["Confirmations", seg.confirmations], ["Signals", seg.signals],
      ["Outcomes", Object.entries(seg.outcomes).map(([k, v]) => `${k} ${v}`).join(", ") || "none"],
      ["Win rate TP/(TP+SL)", seg.win_rate_tp_over_tp_sl === null ? "n/a" : `${(seg.win_rate_tp_over_tp_sl * 100).toFixed(1)}%`],
      ["Total R", seg.total_r], ["Mean R", seg.mean_r ?? "n/a"], ["Max drawdown (R)", seg.max_drawdown_r]];
    for (const [k, v] of rows) dl.append(el("dt", k, "vc-muted"), el("dd", v, "vc-num break-words"));
    card.append(dl); grid.append(card);
  }
  frag.append(grid);
  frag.append(el("p", "Simulated price hits, not broker fills or evidence of future profitability.", "vc-muted mt-4 text-[12px]"));
}

// ------------------------------------------------------------------ tools
async function refreshTools() {
  try {
    const t = await api("/api/tools");
    if (t.task_panel) { $("tool-taskpanel").href = t.task_panel; $("tool-taskpanel-item").hidden = false; }
  } catch (e) { /* optional link only */ }
}

// ------------------------------------------------------------------ actions
$("btn-pause").onclick = async () => {
  try { await api(`/api/scanner/${STATE.scanner.paused ? "resume" : "pause"}`, { method: "POST" }); refreshState(); }
  catch (e) { alertBanner(e); }
};
$("btn-demo-restart").onclick = async () => {
  try { await api("/api/demo/restart", { method: "POST" }); selected = null; selectedRec = null; refreshState(); refreshTables(); if (CHART) CHART.load(); } catch (e) { alertBanner(e); }
};
$("btn-mode").onclick = async () => {
  const target = STATE.mode === "demo" ? "mt5" : "demo";
  const msg = target === "mt5"
    ? "Switch to LIVE MT5? VC Signal will read live data (read-only) from your running, logged-in MetaTrader 5 terminal. No trades are placed. The choice is saved and survives restarts."
    : "Switch to DEMO (fictional data)? The choice is saved and survives restarts.";
  if (!window.confirm(msg)) return;
  try { await api("/api/mode", { method: "POST", body: { mode: target, confirm: true } }); selected = null; selectedRec = null; setupDirty = false; await refreshState(); refreshTables(); if (CHART) CHART.load(); }
  catch (e) { alertBanner(e); }
};
$("tg-enabled").onchange = async (ev) => {
  const want = ev.target.checked;
  const live = STATE && STATE.mode === "mt5";
  if (want && !window.confirm(live
    ? "Enable LIVE delivery? New confirmed LIVE MARKET SIGNALs for this symbol will be sent to the configured Telegram chat. The opt-in is saved for this source, symbol, bot and destination until you disable it."
    : "Enable delivery? New DEMO TEST SIGNALs (fictional prices) will be sent to the configured Telegram chat for this session.")) {
    ev.target.checked = false; return;
  }
  try { await api("/api/telegram/enabled", { method: "POST", body: { enabled: want } }); refreshState(); }
  catch (e) { ev.target.checked = !want; alertBanner(e); }
};
$("fvg-confirm").onchange = () => renderFvg((STATE && STATE.fvg) || {}, (STATE && STATE.active_strategy) || {});
$("btn-fvg-arm").onclick = () => setFvgExecution(true);
$("btn-fvg-disarm").onclick = () => setFvgExecution(false);
$("btn-tg-test").onclick = async () => {
  if (!window.confirm("Send one labeled TEST MESSAGE to the configured Telegram chat now?")) return;
  try { const r = await api("/api/telegram/test", { method: "POST" }); banner(r.note); } catch (e) { alertBanner(e); }
};
$("btn-tg-verify").onclick = async () => {
  $("btn-tg-verify").disabled = true;
  try {
    const r = await api("/api/telegram/verify", { method: "POST" });
    $("tg-note").textContent = r.bot_ok && r.chat_ok ? "Bot and destination verified (read-only getMe/getChat; nothing was sent)."
      : `Verification problem: ${r.bot_error || r.chat_error || "unknown"}`;
    refreshState();
  } catch (e) { $("tg-note").textContent = e.message; }
  finally { $("btn-tg-verify").disabled = false; }
};
$("btn-replay").onclick = async () => {
  const source = $("replay-source").value;
  const days = Number($("replay-days").value || 60);
  try {
    const strategy = $("replay-strategy").value;
    await api("/api/replay/run", { method: "POST", body: { source, days, strategy, use_ticks: strategy === "crt" && $("replay-ticks").checked } });
    $("btn-replay").disabled = true;
    setTimeout(refreshReplay, 2000);
  } catch (e) { alertBanner(e); }
};
$("replay-source").onchange = () => {
  const mt5 = $("replay-source").value === "mt5";
  const fs = $("replay-strategy").value === "fastsweep";
  $("replay-days").disabled = !mt5; $("replay-ticks").disabled = !mt5 || fs;  // FastSweep replay is OHLC only
  refreshReplay();
};
$("replay-strategy").onchange = () => {
  if ($("replay-strategy").value === "fastsweep") $("replay-source").value = "mt5";  // FastSweep replay needs MT5 history
  $("replay-source").onchange();
};
for (const id of ["setup-source", "setup-symbol", "setup-terminal", "setup-chat", "setup-tz"]) $(id).addEventListener("input", () => { setupDirty = true; });
$("btn-discover").onclick = async () => {
  $("setup-msg").textContent = "Looking for gold symbols in your MT5 terminal…";
  try {
    const r = await api("/api/mt5/discover");
    fillSymbols(r.candidates, $("setup-symbol").value || (STATE.setup || {}).symbol);
    setupDirty = true;
    $("setup-msg").textContent = r.candidates.length
      ? `${r.candidates.length} candidate(s) found${r.account && r.account.server ? ` on ${r.account.server}` : ""}. Choose the exact contract you trade; VC Signal never guesses.`
      : "No gold-like symbols found in this terminal.";
  } catch (e) { $("setup-msg").textContent = e.message; }
};
$("setup-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const body = {};
  const map = { data_mode: "setup-source", symbol: "setup-symbol", mt5_terminal_path: "setup-terminal",
    telegram_test_chat_id: "setup-chat", display_timezone: "setup-tz" };
  for (const [key, id] of Object.entries(map)) if (!$(id).disabled) body[key] = $(id).value.trim();
  const cur = STATE.setup || {};
  const restarts = body.data_mode !== (cur.data_mode || STATE.mode) || (body.symbol || "") !== (cur.symbol || "") ||
    (body.mt5_terminal_path || "") !== (cur.mt5_terminal_path || "");
  if (restarts && !window.confirm("Save and start a new scanner session with this source/symbol? Earlier confirmations are not replayed; history is kept per symbol.")) return;
  $("btn-setup-save").disabled = true;
  try {
    const r = await api("/api/setup", { method: "POST", body });
    setupDirty = false;
    $("setup-msg").textContent = `Saved: ${r.action}.`;
    selected = null; selectedRec = null;
    await refreshState(); refreshTables(); refreshReplay();
    if (restarts && CHART) CHART.load();
  } catch (e) { $("setup-msg").textContent = e.message; }
  finally { $("btn-setup-save").disabled = false; }
};
for (const id of ["f-sig-dir", "f-sig-out", "f-cand-status"]) $(id).onchange = refreshTables;

messageRow("signals", 11, "Loading signals…");
messageRow("candidates", 7, "Loading setups…");
async function loop() {
  await refreshState();
  await refreshTables();
  if (CHART) CHART.poll();
}
refreshState().then(async () => { // the selected view is already shown by nav.js; nothing here moves it
  initChart();
  $("replay-source").onchange();
  refreshTools();
  await Promise.allSettled([refreshTables(), refreshReplay()]);
});
setInterval(loop, 3000);
setInterval(refreshReplay, 15000);
