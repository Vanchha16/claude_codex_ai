"use strict";
// VC Signal market chart: TradingView Lightweight Charts (Apache-2.0, https://www.tradingview.com/) fed by
// VC Signal's own /api/market/bars (the local MT5 terminal, or the fictional demo fixture). Display only:
// chart timeframes, the forming candle, EMAs and tick volume never reach the H1/M5 strategy engine.
(function (root) {
  const LWC = root.LightweightCharts;
  const TF_LABEL = { M1: "1m", M5: "5m", M15: "15m", H1: "1h", H4: "4h", D1: "1d" };
  const TF_SECONDS = { M1: 60, M5: 300, M15: 900, H1: 3600, H4: 14400, D1: 86400 };

  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function ema(bars, period) {
    const out = []; const k = 2 / (period + 1); let prev = null;
    for (let i = 0; i < bars.length; i++) {
      const c = bars[i].close;
      if (i + 1 < period) continue;
      if (prev === null) { let s = 0; for (let j = i + 1 - period; j <= i; j++) s += bars[j].close; prev = s / period; }
      else prev = c * k + prev * (1 - k);
      out.push({ time: bars[i].time, value: prev });
    }
    return out;
  }

  // ---------------------------------------------------------------- price-zone overlay (FVG / IFVG / OB / BB)
  // A Lightweight Charts series primitive: semi-transparent rectangles on the candle pane, drawn below the candles,
  // attached to the real price/time scales. It never handles input, so pan/zoom/touch are untouched.
  // Colour = zone TYPE (FVG cyan, IFVG purple, OB amber, BB rose; theme tokens --zone-*); border style is a second type
  // cue; direction is the badge arrow (\u25B2 bullish, \u25BC bearish). Boxes sit below the candles; badges above them.
  const ZONE_STYLE = {
    FVG: { fill: 0.07, line: 0.55, width: 1, dash: [] },
    IFVG: { fill: 0.06, line: 0.6, width: 1, dash: [5, 3] },
    OB: { fill: 0.09, line: 0.65, width: 1.5, dash: [] },
    BB: { fill: 0.06, line: 0.65, width: 1.5, dash: [2, 3] },
  };
  function rgba(hex, a) {
    const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec((hex || "").trim()); // the CSS minifier may shorten #rrggbb
    if (!m) return `rgba(128,128,128,${a})`;
    const h = m[1].length === 3 ? m[1].replace(/./g, (c) => c + c) : m[1];
    const n = parseInt(h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }
  class ZonePrimitive {
    constructor() {
      this.zones = [];
      this.lastTime = null; // newest drawn candle: active zones extend to it
      this.visible = { FVG: false, IFVG: false, OB: false, BB: false };
      this.colors = { FVG: "#38bdf8", IFVG: "#a78bfa", OB: "#fbbf24", BB: "#fb7185", badgeText: "#0b0e14" };
      this._chart = null; this._series = null; this._request = null;
      this._boxes = { draw: (target) => this._paint(target, false) };
      this._badges = { draw: (target) => this._paint(target, true) };
      this._views = [{ zOrder: () => "bottom", renderer: () => this._boxes }, { zOrder: () => "normal", renderer: () => this._badges }];
    }
    attached(p) { this._chart = p.chart; this._series = p.series; this._request = p.requestUpdate; }
    detached() { this._chart = null; this._series = null; this._request = null; }
    updateAllViews() {}
    paneViews() { return this._views; }
    _update() { if (this._request) this._request(); }
    setZones(zones, lastTime) { this.zones = zones; this.lastTime = lastTime; this._update(); }
    setLastTime(t) { if (t !== this.lastTime) { this.lastTime = t; this._update(); } }
    setVisible(type, on) { this.visible[type] = !!on; this._update(); }
    setColors(c) { this.colors = c; this._update(); }

    /** On-screen rectangles of the visible zones, at their real price/time coordinates (never moved). */
    _geometry(width) {
      const ts = this._chart.timeScale(), series = this._series;
      const a = ts.logicalToCoordinate(0), b = ts.logicalToCoordinate(1);
      const half = a !== null && b !== null ? Math.abs(b - a) / 2 : 3;
      const xLast = this.lastTime === null ? null : ts.timeToCoordinate(this.lastTime);
      const xRight = xLast === null ? width : Math.min(width, xLast + half);
      const out = [];
      for (const z of this.zones) {
        if (!this.visible[z.type]) continue;
        const xs = ts.timeToCoordinate(z.active);
        if (xs === null) continue;
        let x2 = xRight;
        if (z.end !== null) { const xe = ts.timeToCoordinate(z.end); if (xe === null) continue; x2 = xe + half; }
        const x1 = xs - half;
        if (x2 < 0 || x1 > width || x2 <= x1) continue;
        const yt = series.priceToCoordinate(z.top), yb = series.priceToCoordinate(z.bottom);
        if (yt === null || yb === null) continue;
        out.push({ z, x1, x2, y: Math.min(yt, yb), h: Math.max(1, Math.abs(yb - yt)) });
      }
      return out;
    }

    _paint(target, badges) {
      if (!this._chart || !this._series || !this.zones.length) return;
      target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
        const geo = this._geometry(mediaSize.width);
        if (!geo.length) return;
        ctx.save();
        if (!badges) {
          // ended first, then active oldest -> newest, so the newest active box is on top
          geo.sort((p, q) => (p.z.end === null) - (q.z.end === null) || (p.z.end ?? p.z.active) - (q.z.end ?? q.z.active));
          for (const g of geo) {
            const st = ZONE_STYLE[g.z.type], col = this.colors[g.z.type], fade = g.z.end === null ? 1 : 0.4;
            ctx.fillStyle = rgba(col, st.fill * fade);
            ctx.fillRect(g.x1, g.y, g.x2 - g.x1, g.h);
            ctx.strokeStyle = rgba(col, st.line * fade);
            ctx.lineWidth = st.width;
            ctx.setLineDash(st.dash);
            ctx.strokeRect(g.x1 + 0.5, g.y + 0.5, Math.max(0, g.x2 - g.x1 - 1), Math.max(0, g.h - 1));
          }
        } else {
          // badge priority: newest active first, then newest ended; an overlapping badge is skipped, never moved elsewhere
          geo.sort((p, q) => (q.z.end === null) - (p.z.end === null) ||
            (q.z.end === null ? q.z.active - p.z.active : q.z.end - p.z.end));
          ctx.font = "600 10px 'Inter Tight', system-ui, sans-serif";
          ctx.textBaseline = "middle";
          const placed = [];
          for (const g of geo) {
            const text = `${g.z.dir === "bull" ? "\u25B2" : "\u25BC"} ${g.z.type}`;
            const w = Math.ceil(ctx.measureText(text).width) + 8, h = 14;
            const bx = Math.max(g.x1, 0) + 3, by = g.h >= h + 4 ? g.y + 2 : g.y - h - 1;
            if (g.z.end !== null && bx + w > g.x2) continue; // ended box too narrow to label
            if (by < 0 || by + h > mediaSize.height) continue;
            if (placed.some((r) => bx < r.x + r.w + 3 && r.x < bx + w + 3 && by < r.y + r.h + 2 && r.y < by + h + 2)) continue;
            placed.push({ x: bx, y: by, w, h });
            const col = this.colors[g.z.type], alpha = g.z.end === null ? 0.9 : 0.55;
            ctx.fillStyle = rgba(col, alpha);
            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(bx, by, w, h, 4); else ctx.rect(bx, by, w, h);
            ctx.fill();
            ctx.fillStyle = this.colors.badgeText;
            ctx.globalAlpha = g.z.end === null ? 1 : 0.8;
            ctx.fillText(text, bx + 4, by + h / 2 + 0.5);
            ctx.globalAlpha = 1;
          }
        }
        ctx.restore();
      });
    }
  }

  class MarketChart {
    constructor(container, opts) {
      this.el = container;
      this.api = opts.api;                 // (path) => Promise<json>
      this.onStatus = opts.onStatus || (() => {});
      this.onReadout = opts.onReadout || (() => {});
      this.tz = () => (opts.timezone ? opts.timezone() : "UTC");
      this.tf = "M5";
      this.mode = "live";                  // "live" | "setup"
      this.closed = [];                    // closed bars (ascending, unique)
      this.forming = null;
      this.seq = 0;                        // request generation: stale responses are dropped
      this.loadingOlder = false;
      this.noMoreHistory = false;
      this.lines = [];
      this.indicators = { ema20: false, ema50: false, volume: false, fvg: false, ifvg: false, ob: false, bb: false };
      this.onZones = opts.onZones || (() => {});
      this.zoneKey = null; this.zoneResult = null; this.zoneShown = [];
      this.zoneDisplay = root.VCZones ? root.VCZones.normalizeDisplay(null) : { perType: 3, history: false };
      this.hasVolume = false;
      this.digits = 2; this.tick = 0.01;
      this._create();
    }

    _colors() {
      return { bg: css("--chart-bg") || "#ffffff", text: css("--chart-text"), grid: css("--chart-grid"), up: css("--chart-up"),
        down: css("--chart-down"), forming: css("--chart-forming") || "rgba(152,162,179,0.55)", ema20: css("--chart-level"),
        ema50: css("--chart-sweep"), vol: css("--chart-volume") || "rgba(152,162,179,0.35)",
        zones: { FVG: css("--zone-fvg") || "#38bdf8", IFVG: css("--zone-ifvg") || "#a78bfa", OB: css("--zone-ob") || "#fbbf24",
          BB: css("--zone-bb") || "#fb7185", badgeText: css("--zone-badge-text") || "#0b0e14" } };
    }

    _create() {
      const c = this._colors();
      this.chart = LWC.createChart(this.el, {
        autoSize: true,
        layout: { background: { type: "solid", color: c.bg }, textColor: c.text, fontFamily: "'Inter Tight', system-ui, sans-serif", attributionLogo: true },
        grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
        rightPriceScale: { borderColor: c.grid },
        timeScale: { borderColor: c.grid, timeVisible: true, secondsVisible: false, rightOffset: 6,
          tickMarkFormatter: (t) => root.VCTime.axis(t, this.tz(), TF_SECONDS[this.tf] >= 86400) },
        crosshair: { mode: LWC.CrosshairMode.Normal },
        localization: { timeFormatter: (t) => root.VCTime.format(t, this.tz(), false) },
        kineticScroll: { touch: true, mouse: false },
      });
      this.candles = this.chart.addSeries(LWC.CandlestickSeries, { upColor: c.up, downColor: c.down, wickUpColor: c.up,
        wickDownColor: c.down, borderVisible: false });
      this.volume = this.chart.addSeries(LWC.HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" },
        color: c.vol, visible: false, lastValueVisible: false, priceLineVisible: false });
      this.chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      this.ema20 = this.chart.addSeries(LWC.LineSeries, { color: c.ema20, lineWidth: 1, visible: false, priceLineVisible: false,
        lastValueVisible: false, crosshairMarkerVisible: false, title: "EMA20" });
      this.ema50 = this.chart.addSeries(LWC.LineSeries, { color: c.ema50, lineWidth: 1, visible: false, priceLineVisible: false,
        lastValueVisible: false, crosshairMarkerVisible: false, title: "EMA50" });
      this.markers = LWC.createSeriesMarkers(this.candles, []);
      if (root.VCZones) {
        this.zonePrim = new ZonePrimitive();
        this.zonePrim.setColors(c.zones);
        this.candles.attachPrimitive(this.zonePrim);
      }
      this._onCrosshair = (p) => this._readout(p);
      this._onRange = (r) => { if (r && r.from < 8 && !this.loadingOlder && !this.noMoreHistory && this.mode === "live") this.loadOlder(); };
      this.chart.subscribeCrosshairMove(this._onCrosshair);
      this.chart.timeScale().subscribeVisibleLogicalRangeChange(this._onRange);
    }

    dispose() {
      if (!this.chart) return;
      this.chart.unsubscribeCrosshairMove(this._onCrosshair);
      this.chart.timeScale().unsubscribeVisibleLogicalRangeChange(this._onRange);
      if (this.zonePrim) { this.candles.detachPrimitive(this.zonePrim); this.zonePrim = null; }
      this.chart.remove();
      this.chart = null;
    }

    applyTheme() {
      const c = this._colors();
      this.chart.applyOptions({ layout: { background: { type: "solid", color: c.bg }, textColor: c.text },
        grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
        rightPriceScale: { borderColor: c.grid }, timeScale: { borderColor: c.grid } });
      this.candles.applyOptions({ upColor: c.up, downColor: c.down, wickUpColor: c.up, wickDownColor: c.down });
      this.volume.applyOptions({ color: c.vol });
      this.ema20.applyOptions({ color: c.ema20 }); this.ema50.applyOptions({ color: c.ema50 });
      if (this.zonePrim) this.zonePrim.setColors(c.zones);
      this._render(false);
    }

    _priceFormat(data) {
      if (data.digits !== undefined) { this.digits = data.digits; this.tick = data.tick_size || Math.pow(10, -data.digits); }
      this.candles.applyOptions({ priceFormat: { type: "price", precision: this.digits, minMove: this.tick } });
    }

    _candle(b) {
      const d = { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close };
      if (b.forming) { const c = this._colors(); Object.assign(d, { color: c.forming, wickColor: c.forming, borderColor: c.forming }); }
      return d;
    }

    _render(keepView) {
      const range = keepView ? this.chart.timeScale().getVisibleLogicalRange() : null;
      const all = this.forming ? this.closed.concat([this.forming]) : this.closed;
      this.candles.setData(all.map((b) => this._candle(b)));
      this.seriesLast = all.length ? all[all.length - 1].time : -Infinity;  // newest time currently drawn
      this.hasVolume = this.closed.some((b) => typeof b.volume === "number");
      this.volume.setData(this.hasVolume ? all.filter((b) => typeof b.volume === "number").map((b) => ({ time: b.time, value: b.volume })) : []);
      this.volume.applyOptions({ visible: this.indicators.volume && this.hasVolume });
      this.ema20.setData(this.indicators.ema20 ? ema(this.closed, 20) : []);  // closed bars only
      this.ema50.setData(this.indicators.ema50 ? ema(this.closed, 50) : []);
      this.ema20.applyOptions({ visible: this.indicators.ema20 }); this.ema50.applyOptions({ visible: this.indicators.ema50 });
      if (range) this.chart.timeScale().setVisibleLogicalRange(range);
      this._updateZones();
    }

    /** Detect zones from CLOSED bars only; cached until the closed data (or tick/timeframe) actually changes. */
    _updateZones() {
      if (!this.zonePrim) return;
      const cl = this.closed, last = cl[cl.length - 1];
      const key = cl.length ? [this.tf, this.tick, cl.length, cl[0].time, last.time, last.open, last.high, last.low, last.close].join("|") : "empty";
      if (key !== this.zoneKey) {
        this.zoneKey = key;
        this.zoneResult = cl.length ? root.VCZones.detect(cl, { tick: this.tick, step: TF_SECONDS[this.tf] })
          : { zones: [], stats: { bars: 0 } };
        this._selectZones();
      }
      this.zonePrim.setLastTime(Number.isFinite(this.seriesLast) ? this.seriesLast : null);
      this._emitZones();
    }

    /** Render-only selection from the cached detection result (no re-detection). */
    _selectZones() {
      const r = this.zoneResult || { zones: [] };
      this.zoneShown = root.VCZones.selectForDisplay(r.zones, this.zoneDisplay.perType, { history: this.zoneDisplay.history });
      this.zonePrim.setZones(this.zoneShown, this.zonePrim.lastTime);
    }

    /** Display options: {perType: 3|5|10, history: bool}. Viewport, timeframe, selection and detection are untouched. */
    setZoneDisplay(opts) {
      this.zoneDisplay = root.VCZones ? root.VCZones.normalizeDisplay(opts) : this.zoneDisplay;
      if (!this.zonePrim) return;
      this._selectZones();
      this._emitZones();
    }

    _emitZones() {
      const r = this.zoneResult || { zones: [], stats: { bars: 0 } };
      const shown = {};
      for (const t of ["FVG", "IFVG", "OB", "BB"]) {
        const mine = this.zoneShown.filter((z) => z.type === t);
        shown[t] = { active: mine.filter((z) => z.end === null).length, ended: mine.filter((z) => z.end !== null).length };
      }
      this.onZones({ counts: root.VCZones ? root.VCZones.counts(r.zones) : null, shown, bars: r.stats.bars, tf: this.tf,
        display: { ...this.zoneDisplay },
        visible: { FVG: this.indicators.fvg, IFVG: this.indicators.ifvg, OB: this.indicators.ob, BB: this.indicators.bb } });
    }

    setIndicator(name, on) {
      this.indicators[name] = on;
      const zoneType = { fvg: "FVG", ifvg: "IFVG", ob: "OB", bb: "BB" }[name];
      if (zoneType) { if (this.zonePrim) this.zonePrim.setVisible(zoneType, on); this._emitZones(); return; } // no data reset
      this._render(true);
    }

    _status(kind, text) { this.onStatus({ kind, text, tf: this.tf, mode: this.mode, forming: !!this.forming, hasVolume: this.hasVolume }); }

    async load(tf) {
      if (tf) this.tf = tf;
      const my = ++this.seq; const tfAtRequest = this.tf;
      this.mode = "live"; this.noMoreHistory = false;
      this._clearOverlays();
      this._status("loading", `Loading ${TF_LABEL[this.tf]} candles…`);
      let data;
      try { data = await this.api(`/api/market/bars?tf=${tfAtRequest}&count=400`); }
      catch (e) { if (my === this.seq) { this.closed = []; this.forming = null; this._render(false); this._status("error", `Chart data unavailable: ${e.message}`); } return; }
      if (my !== this.seq || tfAtRequest !== this.tf) return; // a newer selection won
      this._priceFormat(data);
      this.closed = data.bars || []; this.forming = data.forming || null;
      this._render(false);
      this.chart.timeScale().scrollToRealTime();
      if (!data.available) this._status("unavailable", data.reason || "No history for this timeframe.");
      else this._status("ok", this._liveText(data));
      this.lastData = data;
    }

    _liveText(data) {
      const src = data.source === "demo" ? "DEMO fixture (fictional)" : "MT5 terminal";
      return `${data.symbol || "?"} · ${TF_LABEL[this.tf]} · ${src} · ${this.closed.length} closed candles` +
        (this.forming ? " · last candle FORMING (display only; analysis uses closed candles)" : "");
    }

    async poll() {
      if (this.mode !== "live" || !this.chart) return;
      const my = this.seq; const tfAtRequest = this.tf;
      let data;
      try { data = await this.api(`/api/market/bars?tf=${tfAtRequest}&count=3`); } catch (e) { this._status("error", `Update failed: ${e.message}`); return; }
      if (my !== this.seq || tfAtRequest !== this.tf || this.mode !== "live") return;
      if (!data.available) { this._status("unavailable", data.reason || "No data"); return; }
      if (!this.closed.length) { this.load(); return; }
      let changed = false;
      for (const b of data.bars) {
        const last = this.closed[this.closed.length - 1];
        if (b.time > last.time) { this.closed.push(b); changed = true; }
        else if (b.time === last.time) { this.closed[this.closed.length - 1] = b; changed = true; }
      }
      const f = data.forming;
      if (f && f.time > this.closed[this.closed.length - 1].time) { this.forming = f; changed = true; }
      else if (this.forming && (!f || f.time <= this.closed[this.closed.length - 1].time)) { this.forming = null; changed = true; }
      if (!changed) return;
      // incremental update keeps the user's zoom/pan; LWC follows the live edge only if the user is at it.
      // series.update() may only touch the newest bar or append; anything else (e.g. the forming candle closing and a
      // new one starting) falls back to a full, view-preserving redraw.
      const tail = data.bars.filter((b) => b.time >= this.seriesLast).concat(this.forming ? [this.forming] : []);
      const removedForming = this.seriesLast > this.closed[this.closed.length - 1].time && !this.forming;
      const needFull = this.indicators.ema20 || this.indicators.ema50 || this.indicators.volume || removedForming ||
        data.bars.some((b) => b.time < this.seriesLast && b.time >= this.closed[Math.max(0, this.closed.length - 3)].time);
      if (needFull) this._render(true);
      else {
        for (const b of tail.sort((x, y) => x.time - y.time)) {
          if (b.time < this.seriesLast) { this._render(true); break; }
          this.candles.update(this._candle(b));
          this.seriesLast = b.time;
        }
        this._updateZones(); // a closed bar may have been added or revised
      }
      this._status("ok", this._liveText(data));
    }

    async loadOlder() {
      if (!this.closed.length) return;
      this.loadingOlder = true;
      const my = this.seq; const tfAtRequest = this.tf;
      const before = new Date(this.closed[0].time * 1000).toISOString();
      try {
        const data = await this.api(`/api/market/bars?tf=${tfAtRequest}&count=300&before=${encodeURIComponent(before)}`);
        if (my !== this.seq || tfAtRequest !== this.tf || this.mode !== "live") return;
        const older = (data.bars || []).filter((b) => b.time < this.closed[0].time);
        if (!older.length) { this.noMoreHistory = true; this._status("ok", `${this._liveText(data)} · no older history returned`); return; }
        const range = this.chart.timeScale().getVisibleLogicalRange();
        this.closed = older.concat(this.closed);
        this._render(false);
        if (range) this.chart.timeScale().setVisibleLogicalRange({ from: range.from + older.length, to: range.to + older.length });
      } catch (e) { this._status("error", `Older history unavailable: ${e.message}`); }
      finally { this.loadingOlder = false; }
    }

    _clearOverlays() {
      for (const l of this.lines) this.candles.removePriceLine(l);
      this.lines = [];
      this.markers.setMarkers([]);
      this.selection = null;
    }

    _line(price, color, title, style) {
      if (price === null || price === undefined) return;
      this.lines.push(this.candles.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }));
    }

    /** Show a selected backend setup/signal on M5 candles; overlay values come straight from the backend record. */
    async showSetup(rec) {
      const my = ++this.seq;
      this.mode = "setup"; this.tf = "M5";
      this._clearOverlays();
      this._status("loading", "Loading setup candles…");
      let data;
      try { data = await this.api(`/api/market/bars?tf=M5&count=600&before=${encodeURIComponent(rec.window.end)}`); }
      catch (e) { if (my === this.seq) this._status("error", `Setup chart unavailable: ${e.message}`); return; }
      if (my !== this.seq) return;
      this._priceFormat(data);
      this.closed = data.bars || []; this.forming = null;
      this._render(false);
      const c = rec.candidate, s = rec.signal, col = this._colors(), LS = LWC.LineStyle;
      this._line(c.a_high, css("--chart-range-edge"), "A high", LS.Solid);
      this._line(c.a_low, css("--chart-range-edge"), "A low", LS.Solid);
      this._line(c.direction === "BUY" ? c.b_low : c.b_high, css("--chart-sweep"), "sweep", LS.Dotted);
      this._line(c.level, css("--chart-level"), "level", LS.Dashed);
      if (s) { this._line(s.entry, css("--chart-entry"), "entry", LS.Solid); this._line(s.sl, css("--chart-sl"), "SL", LS.Solid); this._line(s.tp, css("--chart-tp"), "TP", LS.Solid); }
      const t = (iso) => Math.floor(Date.parse(iso) / 1000);
      const marks = [];
      const times = new Set(this.closed.map((b) => b.time));
      const bOpen = t(c.b_open), bLast = t(c.b_close) - 300;
      if (times.has(bOpen)) marks.push({ time: bOpen, position: "aboveBar", color: col.text, shape: "square", text: "B" });
      if (times.has(bLast)) marks.push({ time: bLast, position: "aboveBar", color: col.text, shape: "circle", text: "B close" });
      if (c.confirm_close) {
        const ct = t(c.confirm_close) - 300; // confirmation bar OPEN time
        if (times.has(ct)) marks.push({ time: ct, position: c.direction === "BUY" ? "belowBar" : "aboveBar",
          color: c.direction === "BUY" ? col.up : col.down, shape: c.direction === "BUY" ? "arrowUp" : "arrowDown",
          text: `${c.direction}${s ? " " + s.id.split("-").slice(-1)[0] : ""}` });
      }
      marks.sort((a, b) => a.time - b.time);
      this.markers.setMarkers(marks);
      this.selection = rec;
      const from = t(c.a_open) - 3600, to = t(rec.window.end);
      try { this.chart.timeScale().setVisibleRange({ from, to }); } catch (e) { this.chart.timeScale().fitContent(); }
      this._status("setup", `${c.direction} setup · A ${root.VCTime.format(c.a_open, this.tz(), false)} · ${c.status}` +
        (s ? ` · ${s.id}` : "") + (rec.mode === "demo" ? " · FICTIONAL DEMO PRICES" : "") + " · press “Live” to return");
    }

    returnLive() { return this.load(this.tf); }

    resetView() {
      this.chart.priceScale("right").applyOptions({ autoScale: true });
      if (this.mode === "setup" && this.selection) {
        const t = (iso) => Math.floor(Date.parse(iso) / 1000);
        this.chart.timeScale().setVisibleRange({ from: t(this.selection.candidate.a_open) - 3600, to: t(this.selection.window.end) });
      } else { this.chart.timeScale().fitContent(); this.chart.timeScale().scrollToRealTime(); }
    }

    _readout(p) {
      let bar = null;
      if (p && p.time !== undefined) {
        const d = p.seriesData.get(this.candles);
        if (d) bar = { time: p.time, open: d.open, high: d.high, low: d.low, close: d.close,
          forming: !!(this.forming && this.forming.time === p.time),
          volume: (this.closed.find((b) => b.time === p.time) || this.forming || {}).volume };
      }
      if (!bar) { const l = this.forming || this.closed[this.closed.length - 1]; if (l) bar = l; }
      this.onReadout(bar, this.digits);
    }
  }

  root.VCMarketChart = { MarketChart, TF_LABEL, ema, ZonePrimitive };
})(window);
