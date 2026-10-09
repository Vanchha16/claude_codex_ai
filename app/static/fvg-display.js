"use strict";
// Display-only formatting for the dashboard (no network, no state): FVG per-leg planned risk in the account currency
// converted to USD where the conversion is known, and the "last closed" caption for the active strategy's timeframes.
// Conversions mirror app/fvg_orders.py ACCOUNT_UNITS_PER_USD (USD x1, USC cent account x100); anything else is shown
// in its own units and never labelled as USD.
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.VCFvgDisplay = api;
})(typeof self !== "undefined" ? self : this, function () {
  const UNITS_PER_USD = { USD: 1, USC: 100 };

  const isNum = (v) => typeof v === "number" && Number.isFinite(v);
  const usd = (v) => `$${v.toFixed(2)} USD`;

  /** Planned SL loss of one leg (account-currency units from the execution payload) as display text, or null if absent. */
  function legRisk(amount, currency) {
    if (!isNum(amount)) return null;
    const ccy = typeof currency === "string" ? currency.trim().toUpperCase() : "";
    const units = UNITS_PER_USD[ccy];
    if (units === 1) return usd(amount);
    if (units) return `${usd(amount / units)} (${amount.toFixed(2)} ${ccy})`;
    if (ccy) return `${amount.toFixed(2)} ${ccy} (no USD conversion)`;
    return `${amount.toFixed(2)} account units (currency unknown, not converted)`;
  }

  /** Caption + value for the last closed bars of the ACTIVE strategy. CRT: H1/M5. FastSweep and FVG: M5 + M15 trend. */
  function lastClosed(kind, lastClosedBars, readiness, fmtT) {
    const lc = lastClosedBars || {};
    if (kind === "fastsweep" || kind === "fvg") {
      const r = readiness;
      const trend = r && isNum(r.m15_run) && isNum(r.required)
        ? `${r.m15_run}/${r.required} M15 ${r.ready ? "(ready)" : "(warm-up)"}` : "—";
      return { label: "Last closed M5 · M15 trend", value: `M5 ${fmtT(lc.M5)} · ${trend}` };
    }
    return { label: "Last closed H1 / M5", value: `H1 ${fmtT(lc.H1)} · M5 ${fmtT(lc.M5)}` };
  }

  /** One line explaining a stored stop's provenance (task 20261009-103608), or null when there is nothing to say.
   * Only STORED values are shown: a moved stop names its base stop and the measured spread it was moved for. */
  function stopNote(stop, fmtP) {
    if (!stop || typeof stop !== "object") return null;
    const p = fmtP || ((v) => String(v));
    const n = stop.moved_ticks;
    if (isNum(n) && n > 0 && isNum(stop.base_sl) && isNum(stop.spread)) {
      return `Spread-aware stop: moved ${n} tick${n === 1 ? "" : "s"} outward from ${p(stop.base_sl)} so every leg is at `
        + `least the spread (${stop.spread.toFixed(2)}) + 1 tick from the SL; targets recalculated at 1:2.`;
    }
    if (typeof stop.note === "string" && stop.note) return `Stop: ${stop.note}.`;
    if (stop.policy === "spread_aware" && isNum(stop.spread)) {
      return `Spread-aware stop: no move needed at spread ${stop.spread.toFixed(2)}.`;
    }
    return null;
  }

  return { legRisk, lastClosed, stopNote, UNITS_PER_USD };
});
