"use strict";
// Display-only price zones for the chart: FVG, IFVG, Order Block (OB) and Breaker Block (BB).
// A pure, deterministic function of ordered CLOSED OHLC bars and the symbol tick size; it never feeds the CRT-SMC-v1
// strategy, signals or Telegram. These are project conventions (documented in README "Chart zones"), not a vendor copy.
//
// Conventions (all comparisons on closed candles; wicks never flip or end a zone):
// - Contiguity: a bar continues the current segment only if its time is exactly previous + timeframe step. Any larger
//   gap (market break, weekend or missing data), an invalid bar or an out-of-order bar starts a new segment. Patterns
//   (FVG triples, pivots, OB breaks) form only inside one segment; zones that already exist keep being managed by later
//   closes.
// - FVG: bars i-2, i-1, i. Bullish if low[i] - high[i-2] >= 1 tick, zone [high[i-2], low[i]]; bearish if
//   low[i-2] - high[i] >= 1 tick, zone [high[i], low[i-2]]. Activates on bar i.
// - IFVG: a bullish FVG becomes a bearish IFVG on a later close strictly below its bottom; a bearish FVG becomes a
//   bullish IFVG on a close strictly above its top. The FVG ends there; the IFVG keeps its bounds/origin and activates
//   on that bar. A bearish IFVG ends on a close strictly above its top; a bullish IFVG on a close strictly below its
//   bottom. No further flips.
// - Pivots: a high (low) strictly above (below) the two bars on each side; usable only after the 2nd right-hand bar
//   closes. Only the most recently confirmed pivot high/low is eligible, and each pivot is consumed at most once.
// - OB: a bullish break is a close strictly above the eligible pivot high; the OB is the full range of the last
//   bearish candle (close < open) before the break bar, searched back at most 20 bars and not before the pivot.
//   Bearish mirrors it (close strictly below the pivot low; last bullish candle). No opposite candle: no OB (the
//   pivot is still consumed). The OB activates on the break bar.
// - BB: a bullish OB closed strictly below its low becomes a bearish BB; a bearish OB closed strictly above its high
//   becomes a bullish BB (same bounds/origin, activates on that bar). A bearish BB ends on a close strictly above its
//   top; a bullish BB on a close strictly below its bottom.
// - Order per bar: manage already-active zones first, then create new ones, so a zone cannot end on its own bar.
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.VCZones = api;
})(typeof self !== "undefined" ? self : this, function () {
  const TYPES = ["FVG", "IFVG", "OB", "BB"];
  const NAMES = { FVG: "Fair Value Gap", IFVG: "Inverse Fair Value Gap", OB: "Order Block", BB: "Breaker Block" };
  const SOURCE_LOOKBACK = 20;

  const finite = (v) => typeof v === "number" && Number.isFinite(v);
  function validBar(b) {
    return !!b && Number.isInteger(b.time) && finite(b.open) && finite(b.high) && finite(b.low) && finite(b.close) &&
      b.high >= b.low && b.high >= Math.max(b.open, b.close) && b.low <= Math.min(b.open, b.close);
  }
  function inferStep(bars) {
    let step = Infinity;
    for (let i = 1; i < bars.length; i++) {
      const d = bars[i] && bars[i - 1] ? bars[i].time - bars[i - 1].time : NaN;
      if (d > 0 && d < step) step = d;
    }
    return Number.isFinite(step) ? step : 0;
  }
  const zoneId = (type, dir, origin, active) => `${type}-${dir}-${origin}-${active}`;

  /**
   * @param bars closed bars {time (s), open, high, low, close}, ascending and unique (forming candles excluded)
   * @param opts {tick: symbol tick size, step: timeframe seconds (inferred if omitted)}
   * @returns {zones, stats} every zone ever detected (ended ones keep `end`), in creation order
   */
  function detect(bars, opts) {
    const o = opts || {};
    const tick = o.tick > 0 ? o.tick : 0.01;
    const eps = tick * 1e-6;
    const step = o.step > 0 ? o.step : inferStep(bars || []);
    const zones = [];
    let active = [];
    const stats = { bars: 0, invalid: 0, segments: 0 };
    let seq = [];           // valid contiguous bars of the current segment
    let lastTime = -Infinity;
    let pivotHigh = null, pivotLow = null;

    const newSegment = () => { seq = []; pivotHigh = null; pivotLow = null; };
    const create = (type, dir, top, bottom, origin, at, extra) => {
      const z = Object.assign({ id: zoneId(type, dir, origin, at), type, dir, top, bottom, origin, active: at,
        available: at + step, end: null, endReason: null, parent: null }, extra || {});
      zones.push(z);
      return z;
    };

    for (const b of bars || []) {
      if (b && b.forming) { stats.forming = (stats.forming || 0) + 1; continue; } // never let a forming candle decide
      if (!validBar(b) || b.time <= lastTime) { stats.invalid++; newSegment(); continue; }
      if (!seq.length || b.time - seq[seq.length - 1].time !== step) { newSegment(); stats.segments++; }
      lastTime = b.time;
      seq.push(b);
      stats.bars++;
      const n = seq.length, t = b.time, c = b.close;

      // 1) manage zones that were active before this bar
      const keep = [], born = [];
      for (const z of active) {
        const beyond = z.dir === "bull" ? c < z.bottom - eps : c > z.top + eps;
        if (!beyond) { keep.push(z); continue; }
        z.end = t;
        if (z.type === "FVG" || z.type === "OB") {
          z.endReason = z.type === "FVG" ? "inverted" : "broken";
          const flipType = z.type === "FVG" ? "IFVG" : "BB";
          const dir = z.dir === "bull" ? "bear" : "bull";
          born.push(create(flipType, dir, z.top, z.bottom, z.origin, t, { parent: z.id, source: z.source || null }));
        } else {
          z.endReason = "invalidated";
        }
      }
      active = keep.concat(born);

      // 2) structure breaks against pivots confirmed on earlier bars -> order blocks
      if (pivotHigh && !pivotHigh.consumed && c > pivotHigh.price + eps) {
        pivotHigh.consumed = true;
        const src = findSource(seq, n - 1, pivotHigh.idx, "bear");
        if (src) active.push(create("OB", "bull", src.high, src.low, src.time, t, { source: src.time, pivot: pivotHigh.time }));
      }
      if (pivotLow && !pivotLow.consumed && c < pivotLow.price - eps) {
        pivotLow.consumed = true;
        const src = findSource(seq, n - 1, pivotLow.idx, "bull");
        if (src) active.push(create("OB", "bear", src.high, src.low, src.time, t, { source: src.time, pivot: pivotLow.time }));
      }

      // 3) fair value gaps completed by this bar
      if (n >= 3) {
        const a = seq[n - 3];
        if (b.low - a.high >= tick - eps) active.push(create("FVG", "bull", b.low, a.high, a.time, t));
        else if (a.low - b.high >= tick - eps) active.push(create("FVG", "bear", a.low, b.high, a.time, t));
      }

      // 4) pivots confirmed by this bar (centre two bars back); eligible from the next bar on
      if (n >= 5) {
        const j = n - 3, p = seq[j];
        const around = [seq[j - 2], seq[j - 1], seq[j + 1], seq[j + 2]];
        if (around.every((x) => p.high > x.high)) pivotHigh = { price: p.high, idx: j, time: p.time, consumed: false };
        if (around.every((x) => p.low < x.low)) pivotLow = { price: p.low, idx: j, time: p.time, consumed: false };
      }
    }
    return { zones, stats: Object.assign(stats, { step, tick }) };
  }

  // Last candle of the wanted colour before the break bar (index k), at most SOURCE_LOOKBACK bars back, not before the pivot.
  function findSource(seq, k, pivotIdx, colour) {
    for (let i = k - 1; i >= Math.max(pivotIdx, k - SOURCE_LOOKBACK); i--) {
      const x = seq[i];
      if (colour === "bear" ? x.close < x.open : x.close > x.open) return x;
    }
    return null;
  }

  /**
   * Display selection only (detection is untouched). Per type: active zones first (newest activation), then - only when
   * `history` is on - the most recently ended ones, never more than `perType`. Defaults keep the original behaviour
   * (10 per type, history included) for callers that pass no options.
   */
  function selectForDisplay(zones, perType, opts) {
    const cap = perType || 10;
    const history = !opts || opts.history !== false;
    const out = [];
    for (const type of TYPES) {
      const of = zones.filter((z) => z.type === type);
      const act = of.filter((z) => z.end === null).sort((a, b) => b.active - a.active);
      const ended = history ? of.filter((z) => z.end !== null).sort((a, b) => b.end - a.end) : [];
      out.push(...act.concat(ended).slice(0, cap));
    }
    return out;
  }

  const DISPLAY_CAPS = [3, 5, 10];
  const DISPLAY_DEFAULTS = { perType: 3, history: false };
  /** Bounded display preference: unknown or invalid values fall back to the defaults. */
  function normalizeDisplay(raw) {
    const r = raw && typeof raw === "object" ? raw : {};
    return { perType: DISPLAY_CAPS.includes(r.perType) ? r.perType : DISPLAY_DEFAULTS.perType,
      history: typeof r.history === "boolean" ? r.history : DISPLAY_DEFAULTS.history };
  }

  function counts(zones) {
    const out = {};
    for (const type of TYPES) {
      const of = zones.filter((z) => z.type === type);
      out[type] = { active: of.filter((z) => z.end === null).length, total: of.length };
    }
    return out;
  }

  return { detect, selectForDisplay, normalizeDisplay, DISPLAY_CAPS, DISPLAY_DEFAULTS, counts, validBar, TYPES, NAMES, SOURCE_LOOKBACK };
});
