/**
 * charts.js: the SVG charts of the Comps valuation view. Owner D.
 *
 * Contract: docs/design/comps-valuation.md section 5 (5.1 dot plot, 5.2 scatter, 5.3 bridge
 * chart, 5.4 side panel minis) and KPI 5's position strip (1.5). Exports of 11.1:
 *
 *   mountCharts(root, ctx) -> {update(view), focusDotPlot(), focusScatter(), focusPoint(ticker),
 *                              destroy()}   (plus focusSwitcher() for the `m` key)
 *   mountBridgeChart(root, ctx) -> {update(view), destroy()}
 *   positionStrip(strip, opts) -> SVGElement
 *   sparkline, barMini, lineMini, phaseBars -> SVGElement
 *
 * Every chart reads its geometry from `view` (core.deriveView), uses tokens only (classes in
 * charts.css, no colour literal here), carries a <title> and a <desc> with the view's
 * description, and is one tab stop with arrow-key point navigation. The pure geometry helpers
 * (scales, ticks, domains, label and point collision, the waterfall) are exported for the node
 * tests in frontend/tests/compsval/charts.test.js; they touch no DOM.
 */

import {
  COLUMN_BY_ID, NULL_GLYPH, NEAR_TREND_BAND, fmtCell, fmtNumber, fmtDate, metricLabel,
} from "./core.js";

// ---------------------------------------------------------------------------------------------
// Constants (5.1 to 5.4)
// ---------------------------------------------------------------------------------------------

export const DOT = {laneH: 56, laneLabelW: 112, axisH: 24, headerH: 28, pad: 12, top: 6, targetH: 22,
  peerR: 4, focalR: 7, stackGap: 8, stackRows: [0, -6, 6]};
export const SCATTER = {height: 320, laptop: 236, narrow: 220, padL: 44, padB: 28, padT: 10, padR: 18,
  minR: 4, spanR: 14};
export const STRIP = {width: 120, height: 20};
const LABEL_PX = 10.5;
const FOCAL_LABEL_PX = 12;
const TICK_PX = 11;
const INLINE_METRICS = 5;
const MORE = "More ▾";
const GLYPH = {lo: "◂", hi: "▸", up: "▴", down: "▾"};

function isNum(v) { return typeof v === "number" && Number.isFinite(v); }
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

// ---------------------------------------------------------------------------------------------
// Pure geometry: scales, ticks, domains
// ---------------------------------------------------------------------------------------------

/** Linear map of `domain` onto `range`, with `invert`. A zero-width domain maps to the middle. */
export function linearScale(domain, range) {
  const [d0, d1] = domain, [r0, r1] = range;
  const flat = !(d1 !== d0);
  const k = flat ? 0 : (r1 - r0) / (d1 - d0);
  const f = (v) => (flat ? (r0 + r1) / 2 : r0 + (v - d0) * k);
  f.invert = (p) => (k === 0 ? d0 : d0 + (p - r0) / k);
  f.domain = [d0, d1];
  f.range = [r0, r1];
  f.kind = "linear";
  return f;
}

/** Log10 map; falls back to linear when either end is not positive. */
export function logScale(domain, range) {
  const [d0, d1] = domain;
  if (!(d0 > 0) || !(d1 > 0)) return linearScale(domain, range);
  const L = linearScale([Math.log10(d0), Math.log10(d1)], range);
  const f = (v) => (v > 0 ? L(Math.log10(v)) : range[0]);
  f.invert = (p) => 10 ** L.invert(p);
  f.domain = [d0, d1];
  f.range = range.slice();
  f.kind = "log";
  return f;
}

export function makeScale(kind, domain, range) {
  return kind === "log" ? logScale(domain, range) : linearScale(domain, range);
}

/** A 1, 2, 2.5 or 5 times a power of ten near span / count. */
export function niceStep(span, count = 5) {
  if (!(span > 0) || !Number.isFinite(span)) return 1;
  const raw = span / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const m = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
  return m * mag;
}

/** Decimals needed to write `v` exactly, up to 6. */
export function decimalsOf(v) {
  if (!isNum(v)) return 0;
  const a = Math.abs(v);
  for (let d = 0; d <= 6; d++) {
    const s = a * 10 ** d;
    if (Math.abs(s - Math.round(s)) < 1e-6 * Math.max(1, s)) return d;
  }
  return 6;
}

/** Nice ticks inside [lo, hi] (both ends included when they fall on a step). */
export function niceTicks(lo, hi, count = 5) {
  if (!isNum(lo) || !isNum(hi)) return [];
  if (lo > hi) [lo, hi] = [hi, lo];
  if (lo === hi) return [lo];
  const step = niceStep(hi - lo, count);
  const d = decimalsOf(step);
  const start = Math.ceil(lo / step - 1e-9);
  const out = [];
  for (let i = start; i * step <= hi + step * 1e-9; i++) out.push(Number((i * step).toFixed(Math.min(12, d + 2))));
  return out;
}

/** Log ticks: powers of ten inside [lo, hi]; with fewer than two, the 1, 2, 5 sequence. */
export function logTicks(lo, hi) {
  if (!(lo > 0) || !(hi > 0)) return [];
  if (lo > hi) [lo, hi] = [hi, lo];
  const inside = (v) => v >= lo * (1 - 1e-9) && v <= hi * (1 + 1e-9);
  const e0 = Math.floor(Math.log10(lo)), e1 = Math.ceil(Math.log10(hi));
  const pow = [];
  for (let e = e0; e <= e1; e++) { const v = Number((10 ** e).toPrecision(12)); if (inside(v)) pow.push(v); }
  if (pow.length >= 2) return pow;
  const f = [];
  for (let e = e0; e <= e1; e++) for (const m of [1, 2, 5]) { const v = Number((m * 10 ** e).toPrecision(12)); if (inside(v)) f.push(v); }
  return f.length >= 2 ? f : niceTicks(lo, hi, 3).filter((v) => v > 0);
}

export function ticksFor(scale, count = 5) {
  const [a, b] = scale.domain;
  return scale.kind === "log" ? logTicks(a, b) : niceTicks(a, b, count);
}

/** Min to max of the finite values, padded by `pad` of the span (in log space when `log`). */
export function paddedDomain(values, pad = 0.08, log = false) {
  const v = (values || []).filter((x) => isNum(x) && (!log || x > 0));
  if (!v.length) return null;
  let lo = Math.min(...v), hi = Math.max(...v);
  if (log) {
    const a = Math.log10(lo), b = Math.log10(hi);
    const span = b - a || 1;
    return [10 ** (a - pad * span), 10 ** (b + pad * span)];
  }
  let span = hi - lo;
  if (span === 0) span = Math.abs(hi) || 1;
  return [lo - pad * span, hi + pad * span];
}

// ---------------------------------------------------------------------------------------------
// Pure formatting of chart values (header units: × and % are written, money and counts are not)
// ---------------------------------------------------------------------------------------------

function unitSuffix(colId) {
  const c = COLUMN_BY_ID[colId];
  const f = c ? c.fmt : "";
  if (f === "mult1" || f === "mult2") return "×";
  if (f === "pct1" || f === "pct0") return "%";
  return "";
}
function displayFactor(colId) {
  const c = COLUMN_BY_ID[colId];
  const f = c ? c.fmt : "";
  if (f === "pct1" || f === "pct0") return 100;
  if (f === "money1") return 1 / 1000;
  return 1;
}

/** A chart value in the column's format with its × or % suffix: "15.3×", "8.6%", "260.0". */
export function fmtValue(colId, v) {
  if (!isNum(v)) return NULL_GLYPH;
  const c = COLUMN_BY_ID[colId];
  if (!c) return fmtNumber(v, 2);
  return fmtCell({status: "ok", v}, c) + unitSuffix(colId);
}

/** Tick label formatter: decimals from the tick step (per value on a log axis). */
export function tickFormatter(colId, ticks = [], kind = "linear") {
  const k = displayFactor(colId);
  const suffix = unitSuffix(colId);
  const step = ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) * k : 0;
  const stepDec = Math.min(4, decimalsOf(step));
  return (v) => {
    if (!isNum(v)) return NULL_GLYPH;
    const x = v * k;
    const d = kind === "log" ? Math.min(4, decimalsOf(Number(x.toPrecision(6)))) : stepDec;
    return fmtNumber(x, d) + suffix;
  };
}

/** Rough text width in px for label collision: Plex Mono advances about 0.6 em. */
export function textWidth(text, px = LABEL_PX, mono = true) {
  return String(text || "").length * px * (mono ? 0.6 : 0.54);
}

// ---------------------------------------------------------------------------------------------
// Pure collision helpers
// ---------------------------------------------------------------------------------------------

/**
 * `stackPoints(xs, {gap, rows, pin})`: vertical offsets so points closer than `gap` px sit in
 * different rows (5.1: within 8 px, up to three rows, ±6 px). Pinned indices take row 0 first.
 * Returns one offset per input, in input order; a non-finite x gets 0.
 */
export function stackPoints(xs, opts = {}) {
  const gap = opts.gap ?? DOT.stackGap;
  const rows = opts.rows ?? DOT.stackRows;
  const pin = new Set(opts.pin || []);
  const placed = rows.map(() => []);
  const out = xs.map(() => 0);
  const idx = xs.map((x, i) => i).filter((i) => isNum(xs[i]));
  const order = idx.filter((i) => pin.has(i)).concat(idx.filter((i) => !pin.has(i)).sort((a, b) => xs[a] - xs[b] || a - b));
  for (const i of order) {
    const x = xs[i];
    let r = pin.has(i) ? 0 : placed.findIndex((list) => list.every((px) => Math.abs(px - x) >= gap));
    if (r < 0) {
      let best = -1;
      r = 0;
      placed.forEach((list, k) => {
        const d = Math.min(...list.map((px) => Math.abs(px - x)));
        if (d > best) { best = d; r = k; }
      });
    }
    placed[r].push(x);
    out[i] = rows[r];
  }
  return out;
}

/**
 * `placeLabels(items, {gap, rows, min, max})`: one-dimensional label rows. Items in priority
 * order, each `{x, w, anchor: "start" | "middle" | "end", required}`. A label goes in the first
 * row where it keeps `gap` px from every label already there; it is clamped inside [min, max].
 * A label with no free row is dropped unless `required` (then it takes row 0).
 * Returns `{row, x0, x1, dropped}` per item.
 */
export function placeLabels(items, opts = {}) {
  const gap = opts.gap ?? 4;
  const nRows = opts.rows ?? 2;
  const lo = opts.min ?? -Infinity, hi = opts.max ?? Infinity;
  const rows = Array.from({length: nRows}, () => []);
  return items.map((it) => {
    const w = it.w;
    let x0 = it.anchor === "end" ? it.x - w : it.anchor === "middle" ? it.x - w / 2 : it.x;
    x0 = Math.max(lo, Math.min(hi - w, x0));
    const x1 = x0 + w;
    let r = rows.findIndex((list) => list.every(([a, b]) => x1 + gap <= a || x0 >= b + gap));
    if (r < 0) {
      if (!it.required) return {row: -1, x0, x1, dropped: true};
      r = 0;
    }
    rows[r].push([x0, x1]);
    return {row: r, x0, x1, dropped: false};
  });
}

export function boxesOverlap(a, b, gap = 0) {
  return !(a.x1 + gap <= b.x0 || b.x1 + gap <= a.x0 || a.y1 + gap <= b.y0 || b.y1 + gap <= a.y0);
}

/** True when `box` comes within `gap` px of the edge of the circle `{x, y, r}`. */
export function boxNearPoint(box, pt, gap = 8) {
  const dx = Math.max(box.x0 - pt.x, 0, pt.x - box.x1);
  const dy = Math.max(box.y0 - pt.y, 0, pt.y - box.y1);
  return Math.hypot(dx, dy) - (pt.r || 0) < gap;
}

/**
 * `pickLabelSlot(pt, w, h, placed, bounds, force)`: a label box beside a mark of radius r:
 * top right, top left, bottom right, bottom left, the first inside `bounds` and clear of every
 * box in `placed`. `force` returns the first slot clamped inside the bounds when none is clear.
 * Returns `{x, y, anchor, box}` (x, y the text anchor and baseline) or null.
 */
export function pickLabelSlot(pt, w, h, placed, bounds, force = false) {
  const r = pt.r || 0, d = 3;
  const cands = [
    {dx: r + d, top: true, anchor: "start"}, {dx: -(r + d), top: true, anchor: "end"},
    {dx: r + d, top: false, anchor: "start"}, {dx: -(r + d), top: false, anchor: "end"},
  ];
  const mk = (c) => {
    const x = pt.x + c.dx;
    const y = c.top ? pt.y - r - 2 : pt.y + r + h;
    const x0 = c.anchor === "end" ? x - w : x;
    return {x, y, anchor: c.anchor, box: {x0, x1: x0 + w, y0: y - h + 2, y1: y + 2}};
  };
  for (const c of cands) {
    const s = mk(c);
    const b = s.box;
    if (b.x0 < bounds.x0 || b.x1 > bounds.x1 || b.y0 < bounds.y0 || b.y1 > bounds.y1) continue;
    if ((placed || []).some((p) => boxesOverlap(p, b, 1))) continue;
    return s;
  }
  if (!force) return null;
  const s = mk(cands[0]);
  const shiftX = Math.min(0, bounds.x1 - s.box.x1) + Math.max(0, bounds.x0 - s.box.x0);
  const shiftY = Math.max(0, bounds.y0 - s.box.y0) + Math.min(0, bounds.y1 - s.box.y1);
  return {x: s.x + shiftX, y: s.y + shiftY, anchor: s.anchor,
    box: {x0: s.box.x0 + shiftX, x1: s.box.x1 + shiftX, y0: s.box.y0 + shiftY, y1: s.box.y1 + shiftY}};
}

// ---------------------------------------------------------------------------------------------
// Pure chart geometry
// ---------------------------------------------------------------------------------------------

/** Dot plot frame: plot x range, lane centres, axis y and SVG height for `width` px. */
export function dotGeometry(dp, width) {
  const lanes = (dp && dp.lanes) || [];
  const n = Math.max(1, lanes.length);
  const multi = lanes.length > 1;
  const labelW = multi ? DOT.laneLabelW : 0;
  const x0 = labelW + 16;
  const x1 = Math.max(x0 + 40, width - 16);
  const domain = dp && dp.domain ? dp.domain : [0, 1];
  const scale = makeScale(dp && dp.scale === "log" ? "log" : "linear", domain, [x0, x1]);
  const laneTop = (i) => DOT.top + i * DOT.laneH;
  const laneY = (i) => laneTop(i) + 34;
  const axisY = DOT.top + n * DOT.laneH;
  const height = axisY + DOT.axisH + (dp && dp.target ? DOT.targetH : 0);
  return {labelW, x0, x1, scale, laneTop, laneY, axisY, height, multi, width};
}

/** Scatter frame: plot box and the two scales. */
export function scatterGeometry(sc, width, height) {
  const x0 = SCATTER.padL, x1 = Math.max(SCATTER.padL + 40, width - SCATTER.padR);
  const y0 = SCATTER.padT, y1 = Math.max(SCATTER.padT + 40, height - SCATTER.padB);
  const dx = sc && sc.domain && sc.domain.x ? sc.domain.x : [0, 1];
  const dy = sc && sc.domain && sc.domain.y ? sc.domain.y : [0, 1];
  const sx = linearScale(dx, [x0, x1]);
  const sy = makeScale(sc && sc.logY ? "log" : "linear", dy, [y1, y0]);
  return {x0, x1, y0, y1, sx, sy, width, height};
}

/** Samples of the OLS trend between xa and xb: [{x, y}]. */
export function trendSamples(trend, xa, xb, n = 24) {
  if (!trend || !isNum(xa) || !isNum(xb)) return [];
  const out = [];
  for (let i = 0; i <= n; i++) {
    const x = xa + ((xb - xa) * i) / n;
    out.push({x, y: trend.intercept + trend.slope * x});
  }
  return out;
}

/** The ±NEAR_TREND_BAND band around the trend, as upper and lower sample lists (y > 0 only). */
export function trendBand(trend, xa, xb, n = 24, band = NEAR_TREND_BAND) {
  const s = trendSamples(trend, xa, xb, n).filter((p) => p.y > 0);
  return {upper: s.map((p) => ({x: p.x, y: p.y * (1 + band)})), lower: s.map((p) => ({x: p.x, y: p.y * (1 - band)}))};
}

/** Labels either side of the median-x line (5.2), by the x column's direction. */
export function medianSideLabels(xCol, xShort) {
  const dir = (COLUMN_BY_ID[xCol] || {}).dir || "n";
  const xs = String(xShort || "");
  if (dir === "+") return {left: `${xs} worse than median`, right: "better than median"};
  if (dir === "-") return {left: `${xs} better than median`, right: "worse than median"};
  return {left: `${xs} below median`, right: "above median"};
}

/**
 * Horizontal waterfall of the bridge (5.3): implied EV from 0, net debt as a floating step,
 * other claims when on, then the equity total from 0. Values in display currency millions.
 */
export function waterfallRows(b) {
  if (!b || !isNum(b.EVi) || !isNum(b.ND)) return [];
  const rows = [{id: "ev", label: "Implied EV", x0: 0, x1: b.EVi, kind: "total", value: b.EVi}];
  let run = b.EVi;
  rows.push({id: "net_debt", label: b.ND >= 0 ? "Less net debt" : "Plus net cash", x0: run, x1: run - b.ND, kind: "step", value: -b.ND});
  run -= b.ND;
  if (isNum(b.OC)) {
    rows.push({id: "other_claims", label: "Other claims", x0: run, x1: run + b.OC, kind: "step", value: b.OC});
    run += b.OC;
  }
  const eq = isNum(b.Eq) ? b.Eq : run;
  rows.push({id: "equity", label: "Implied equity", x0: 0, x1: eq, kind: "total", value: eq});
  return rows;
}

/** Per-share strip markers of the bridge: the values that set its domain. */
export function bridgeStripValues(b) {
  if (!b) return [];
  const v = [];
  if (b.range) v.push(b.range[0], b.range[1]);
  if (isNum(b.price)) v.push(b.price);
  if (isNum(b.V)) v.push(b.V);
  if (b.streetTarget && isNum(b.streetTarget.value)) v.push(b.streetTarget.value);
  if (b.modelFairValue && isNum(b.modelFairValue.value)) v.push(b.modelFairValue.value);
  return v.filter(isNum);
}

/** Position strip x positions (KPI 5): band, median tick and focal marker for `width` px. */
export function stripGeometry(strip, width = STRIP.width) {
  if (!strip || !strip.domain) return null;
  const pad = 6;
  const sc = makeScale(strip.scale === "log" ? "log" : "linear", strip.domain, [pad, width - pad]);
  const at = (v) => (isNum(v) ? clamp(sc(v), pad, width - pad) : null);
  const clampedSide = strip.clamped || (isNum(strip.focal) && sc(strip.focal) < pad ? "lo"
    : isNum(strip.focal) && sc(strip.focal) > width - pad ? "hi" : null);
  return {p25: at(strip.p25), p75: at(strip.p75), median: at(strip.median), focal: at(strip.focal),
    clamped: clampedSide, x0: pad, x1: width - pad};
}

// ---------------------------------------------------------------------------------------------
// DOM helpers (shared with panels.js)
// ---------------------------------------------------------------------------------------------

const SVGNS = "http://www.w3.org/2000/svg";
let UID = 0;
export function uid(prefix = "ch") { UID += 1; return `${prefix}-${UID}`; }

function setAttrs(el, attrs) {
  if (!attrs) return;
  for (const k of Object.keys(attrs)) {
    const v = attrs[k];
    if (v === null || v === undefined || v === false) continue;
    if (k === "text") el.textContent = String(v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "value" && "value" in el && el.tagName !== "BUTTON") el.value = String(v);
    else if (k === "checked" || k === "selected" || k === "disabled" || k === "hidden") { el[k] = !!v; if (v === true && k !== "checked" && k !== "selected") el.setAttribute(k, ""); }
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
}
function appendKids(el, kids) {
  for (const k of kids) {
    if (k === null || k === undefined || k === false) continue;
    if (Array.isArray(k)) appendKids(el, k);
    else if (typeof k === "string" || typeof k === "number") el.appendChild(el.ownerDocument.createTextNode(String(k)));
    else el.appendChild(k);
  }
}
/** HTML element builder: h("button", {class, onclick}, "Label"). */
export function h(tag, attrs, ...kids) {
  const el = globalThis.document.createElement(tag);
  setAttrs(el, attrs);
  appendKids(el, kids);
  return el;
}
/** SVG element builder. */
export function s(tag, attrs, ...kids) {
  const el = globalThis.document.createElementNS(SVGNS, tag);
  setAttrs(el, attrs);
  appendKids(el, kids);
  return el;
}
function r1(v) { return Math.round(v * 10) / 10; }

function normTip(c) {
  const v = typeof c === "function" ? c() : c;
  if (!v) return null;
  if (typeof v === "string") return {body: v};
  return v;
}
export function tipText(c) {
  const v = normTip(c);
  if (!v) return "";
  return [v.title, v.body].concat(v.lines || []).filter(Boolean).join(" ");
}

/**
 * `bindTip(ctx, el, content, descHost)`: the shared tooltip (7.5) on hover after 300 ms and at
 * once on keyboard focus, through ctx.tooltip. `descHost` (a hidden element of the mount)
 * receives a copy of the text for aria-describedby, so screen readers reach it without hover.
 * Without ctx.tooltip the text goes in a title attribute.
 */
export function bindTip(ctx, el, content, descHost) {
  el.__tip = content;
  const text = tipText(content);
  if (descHost && text) {
    const id = uid("tip");
    descHost.appendChild(h("span", {id, text}));
    const prev = el.getAttribute("aria-describedby");
    el.setAttribute("aria-describedby", prev ? `${prev} ${id}` : id);
  }
  const T = ctx && ctx.tooltip;
  if (!T || typeof T.show !== "function") {
    if (text) el.setAttribute("title", text);
    return el;
  }
  if (el.__tipBound) return el;
  el.__tipBound = true;
  let timer = null;
  const show = () => { clearTimeout(timer); const c = normTip(el.__tip); if (c) T.show(el, c); };
  const hide = () => { clearTimeout(timer); if (typeof T.hide === "function") T.hide(); };
  el.addEventListener("mouseenter", () => { clearTimeout(timer); timer = setTimeout(show, 300); });
  el.addEventListener("mouseleave", hide);
  el.addEventListener("focus", show);
  el.addEventListener("blur", hide);
  return el;
}

/** Hover-only tooltip for a chart mark (the plot itself is the keyboard stop): 300 ms delay. */
export function hoverTip(ctx, el, textFn) {
  const T = ctx && ctx.tooltip;
  if (!T || typeof T.show !== "function") { el.appendChild(s("title", {}, textFn())); return; }
  let timer = null;
  el.addEventListener("mouseenter", () => { clearTimeout(timer); timer = setTimeout(() => T.show(el, {body: textFn()}), 300); });
  el.addEventListener("mouseleave", () => { clearTimeout(timer); if (typeof T.hide === "function") T.hide(); });
}

/** A `.u-state` block from a StateMsg (section 8). */
export function stateBlock(msg, onAction) {
  if (!msg) return null;
  const tone = msg.severity === "red" ? " red" : msg.severity === "amber" ? " amber" : "";
  const kids = [h("p", {class: "u-state-title", text: msg.title || ""}), h("p", {class: "u-state-detail", text: msg.detail || ""})];
  if (msg.action && onAction) {
    kids.push(h("button", {type: "button", class: "u-btn u-state-action", onclick: () => onAction(msg.action)}, msg.action.label));
  }
  return h("div", {class: `u-state${tone}`, role: msg.severity === "red" ? "alert" : null}, kids);
}

/** Chip element: tones neutral, active, flag, down, up, clinical, analyst. */
export function chip(text, tone = "neutral", attrs = {}) {
  const cls = `u-chip${tone && tone !== "neutral" ? " " + tone : ""}${attrs.class ? " " + attrs.class : ""}`;
  return h(attrs.tag || "span", {...attrs, tag: null, class: cls}, h("span", {class: "u-chip-label", text}));
}

function layoutOf(ctx, root) {
  const l = ctx ? (typeof ctx.layout === "function" ? ctx.layout() : ctx.layout) : null;
  if (l) return l;
  const app = root && root.ownerDocument ? root.ownerDocument.getElementById("app") : null;
  return (app && app.getAttribute("data-layout")) || "wide";
}
function stateOf(ctx) {
  try { return ctx && typeof ctx.getState === "function" ? ctx.getState() : null; } catch (e) { return null; }
}
function dispatch(ctx, action) { if (ctx && typeof ctx.dispatch === "function") ctx.dispatch(action); }
function announce(ctx, text) { if (ctx && typeof ctx.announce === "function" && text) ctx.announce(text); }
function openDetail(ctx, ticker) {
  if (ctx && typeof ctx.openDetail === "function") ctx.openDetail(ticker);
  else dispatch(ctx, {type: "OPEN_DETAIL", ticker});
}
export function lcfirst(s) {
  if (!s) return s;
  if (/^[A-Z0-9&]{2,}(\b|\/)/.test(s) || /^[A-Z]\//.test(s)) return s;
  return s.charAt(0).toLowerCase() + s.slice(1);
}

/**
 * Go to a column of the table (6.1, 5.1 "Not plotted" link): add it through SHOW_COLUMN when the
 * preset lacks it, then focus the focal company's cell in it and announce where focus went.
 */
export function goToColumn(ctx, view, colId) {
  if (!colId || !view) return;
  const c = COLUMN_BY_ID[colId];
  const label = c ? lcfirst(c.label) : colId;
  const inTable = !!(view.table && (view.table.columns || []).some((cv) => cv.id === colId));
  if (!inTable) dispatch(ctx, {type: "SHOW_COLUMN", colId});
  const T = view.focal ? view.focal.ticker : null;
  const table = ctx && ctx.table;
  const focus = () => {
    if (ctx && typeof ctx.focusCell === "function") ctx.focusCell(T, colId);
    else if (table && typeof table.focusCell === "function") {
      if (typeof table.scrollToColumn === "function") table.scrollToColumn(colId);
      table.focusCell(T, colId);
    } else dispatch(ctx, {type: "FOCUS_CELL", row: T, col: colId});
  };
  // A column added by SHOW_COLUMN exists only after the table re-renders.
  if (!inTable && typeof requestAnimationFrame === "function") requestAnimationFrame(focus);
  else focus();
  announce(ctx, inTable ? `Showing ${label}` : `Added ${label} to a custom column set.`);
}

/**
 * Keep focus, typed values and scroll positions across a rebuild of `root`. Elements carry
 * `data-key`; an input the analyst was typing in (data-dirty) keeps its text.
 */
export function rebuildKeepingFocus(root, build) {
  const doc = root.ownerDocument;
  const ae = doc.activeElement;
  let key = null, val = null, dirty = false, selStart = null, selEnd = null;
  if (ae && ae !== doc.body && root.contains(ae)) {
    key = ae.getAttribute("data-key");
    if ("value" in ae && ae.tagName !== "BUTTON") {
      val = ae.value;
      dirty = ae.getAttribute("data-dirty") === "1";
      try { selStart = ae.selectionStart; selEnd = ae.selectionEnd; } catch (e) { /* not a text input */ }
    }
  }
  const scrolls = [];
  for (const el of root.querySelectorAll("[data-scroll-key]")) {
    if (el.scrollTop || el.scrollLeft) scrolls.push([el.getAttribute("data-scroll-key"), el.scrollTop, el.scrollLeft]);
  }
  build();
  for (const [k, top, left] of scrolls) {
    const el = root.querySelector(`[data-scroll-key="${cssEsc(k)}"]`);
    if (el) { el.scrollTop = top; el.scrollLeft = left; }
  }
  if (key) {
    const el = root.querySelector(`[data-key="${cssEsc(key)}"]`);
    if (el) {
      if (dirty && val !== null && el.value !== val) { el.value = val; el.setAttribute("data-dirty", "1"); }
      try { el.focus({preventScroll: true}); } catch (e) { el.focus(); }
      if (selStart !== null) { try { el.setSelectionRange(selStart, selEnd); } catch (e) { /* ignore */ } }
    }
  }
}
function cssEsc(s) {
  const C = globalThis.CSS;
  return C && typeof C.escape === "function" ? C.escape(s) : String(s).replace(/["\\]/g, "\\$&");
}

/** Signature of a view slice, for skipping rebuilds when nothing it shows has changed. */
export function sig(...parts) {
  try { return JSON.stringify(parts, (k, v) => (k === "record" || k === "analysis" ? undefined : v)); } catch (e) { return String(Math.random()); }
}

// ---------------------------------------------------------------------------------------------
// Mark builders
// ---------------------------------------------------------------------------------------------

/** Shape path of equal area to a circle of radius r: circle, square or triangle. */
export function shapePath(shape, x, y, r) {
  if (shape === "square") {
    const a = r * Math.sqrt(Math.PI) / 2;
    return `M${r1(x - a)},${r1(y - a)}h${r1(2 * a)}v${r1(2 * a)}h${r1(-2 * a)}Z`;
  }
  if (shape === "triangle") {
    const side = r * Math.sqrt(4 * Math.PI / Math.sqrt(3));
    const ht = side * Math.sqrt(3) / 2;
    return `M${r1(x)},${r1(y - (2 * ht) / 3)}L${r1(x + side / 2)},${r1(y + ht / 3)}L${r1(x - side / 2)},${r1(y + ht / 3)}Z`;
  }
  return `M${r1(x - r)},${r1(y)}a${r1(r)},${r1(r)} 0 1,0 ${r1(2 * r)},0a${r1(r)},${r1(r)} 0 1,0 ${r1(-2 * r)},0Z`;
}
function diamondPath(x, y, d) {
  return `M${r1(x)},${r1(y - d)}L${r1(x + d)},${r1(y)}L${r1(x)},${r1(y + d)}L${r1(x - d)},${r1(y)}Z`;
}
function label(x, y, text, cls = "ch-lbl", anchor = "start", extra = {}) {
  return s("text", {x: r1(x), y: r1(y), class: cls, "text-anchor": anchor, ...extra}, text);
}
function svgRoot(width, height, titleText, descText, cls) {
  const tid = uid("cht"), did = uid("chd");
  const svg = s("svg", {class: `ch-svg ${cls || ""}`.trim(), width: Math.round(width), height: Math.round(height),
    viewBox: `0 0 ${Math.round(width)} ${Math.round(height)}`, role: "img", "aria-labelledby": `${tid} ${did}`,
    focusable: "false"});
  svg.appendChild(s("title", {id: tid}, titleText || ""));
  svg.appendChild(s("desc", {id: did}, descText || ""));
  svg.__descId = did;
  return svg;
}

// ---------------------------------------------------------------------------------------------
// mountCharts: dot plot (5.1) and scatter (5.2), rail or two-tab strip by layout (1.3)
// ---------------------------------------------------------------------------------------------

export function mountCharts(root, ctx) {
  const doc = root.ownerDocument;
  root.classList.add("ch-root");
  let view = null;
  let lastSig = null;
  let lastWidth = 0;
  const ui = {dotActive: null, dotLane: 0, scActive: null, scHover: null};
  const els = {dotPlot: null, scPlot: null, switcher: null, tabs: []};
  let destroyed = false;

  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => {
    const w = root.clientWidth;
    if (Math.abs(w - lastWidth) >= 1 && view) { lastWidth = w; render(true); }
  }) : null;
  if (ro) ro.observe(root);

  // Revision 3 (12.1): the two-tab strip is the chart area at every width; the rail is gone.
  function stripMode() { return true; }

  function render(force = false) {
    if (destroyed || !view) return;
    const layout = layoutOf(ctx, root);
    const st = stateOf(ctx) || {};
    const tabKey = layout === "narrow" ? "narrowTab" : "laptopTab";
    const tab = (st.ui && st.ui[tabKey]) || "position";
    const stripState = ((st.chartStrip || {})[layout]) || "open";
    const signature = sig(layout, tab, stripState, root.clientWidth, view.dotplot, view.scatter, view.primary,
      view.sectionErrors && [view.sectionErrors.dotplot, view.sectionErrors.scatter], ui);
    if (!force && signature === lastSig) return;
    lastSig = signature;
    lastWidth = root.clientWidth;
    rebuildKeepingFocus(root, () => {
      root.textContent = "";
      root.setAttribute("data-layout", layout);
      if (stripMode(layout)) buildStrip(layout, tab, stripState);
      else buildRail();
    });
  }

  // ----- rail (wide, ultrawide) -----
  function buildRail() {
    const dotCard = h("section", {class: "ch-card ch-dot", "aria-label": "Peer position"});
    root.appendChild(dotCard);
    const head = h("div", {class: "ch-head"}, h("h3", {class: "ch-title", text: "Peer position"}));
    dotCard.appendChild(head);
    dotHeaderItems(head, false);
    fillDot(dotCard);
    const scCard = h("section", {class: "ch-card ch-sc", "aria-label": "Valuation against fundamentals"});
    root.appendChild(scCard);
    scCard.appendChild(h("div", {class: "ch-head"}, h("h3", {class: "ch-title", text: "Valuation against fundamentals"})));
    fillScatter(scCard, SCATTER.height);
  }

  // ----- strip (laptop, narrow) -----
  function buildStrip(layout, tab, stripState) {
    const collapsed = stripState === "collapsed";
    const head = h("div", {class: "ch-strip-head"});
    root.appendChild(head);
    const list = h("div", {class: "ch-tabs", role: "tablist", "aria-label": "Charts"});
    head.appendChild(list);
    const panelId = uid("chp");
    const tabs = [{id: "position", label: "Position"}, {id: "scatter", label: "Valuation and growth"}];
    els.tabs = tabs.map((t, i) => {
      const sel = t.id === tab;
      const b = h("button", {type: "button", role: "tab", class: "ch-tab", id: `${panelId}-t${i}`, "data-key": `tab-${t.id}`,
        "aria-selected": String(sel), "aria-controls": panelId, tabindex: sel ? "0" : "-1", text: t.label});
      b.addEventListener("click", () => setTab(layout, t.id));
      b.addEventListener("keydown", (e) => {
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault(); e.stopPropagation();
          const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
          setTab(layout, next.id);
          requestAnimationFrame(() => { const nb = root.querySelector(`[data-key="tab-${next.id}"]`); if (nb) nb.focus(); });
        }
      });
      list.appendChild(b);
      return b;
    });
    if (tab === "position" && !collapsed) dotHeaderItems(head, true);
    const spacer = h("span", {class: "ch-spacer"});
    head.appendChild(spacer);
    const col = h("button", {type: "button", class: "u-btn icon ch-collapse", "data-key": "collapse",
      "aria-expanded": String(!collapsed), "aria-controls": panelId,
      "aria-label": collapsed ? "Expand charts" : "Collapse charts", text: collapsed ? "⌄" : "⌃"});
    col.addEventListener("click", () => dispatch(ctx, {type: "SET_CHART_STRIP", layout, value: collapsed ? "open" : "collapsed"}));
    head.appendChild(col);
    const panel = h("div", {class: "ch-strip-panel", role: "tabpanel", id: panelId,
      "aria-labelledby": `${panelId}-t${tab === "position" ? 0 : 1}`, hidden: collapsed});
    root.appendChild(panel);
    if (collapsed) return;
    if (tab === "position") {
      const card = h("div", {class: "ch-card ch-dot ch-in-strip"});
      panel.appendChild(card);
      fillDot(card);
    } else {
      const card = h("div", {class: "ch-card ch-sc ch-in-strip"});
      panel.appendChild(card);
      fillScatter(card, layout === "narrow" ? SCATTER.narrow : layout === "laptop" ? 260 : SCATTER.height);
    }
  }

  function setTab(layout, id) {
    dispatch(ctx, {type: layout === "narrow" ? "SET_NARROW_TAB" : "SET_LAPTOP_TAB", tab: id});
    render(true);
  }

  // ----- dot plot header: switcher, tag, lane chip, "Use as primary" -----
  function dotHeaderItems(head, compact) {
    const dp = view.dotplot;
    const P = view.primary;
    if (!dp || !P) return;
    const cands = P.candidates || [];
    const cur = dp.colId;
    const descHost = hiddenHost(head);
    if (compact) {
      const curC = cands.find((c) => c.colId === cur);
      const btn = h("button", {type: "button", class: "u-btn ch-switch-menu", "data-key": "switcher",
        "aria-haspopup": "menu", "aria-label": `Metric: ${dp.label || (curC && curC.label) || ""}. Change metric`},
        `${dp.label || (curC ? curC.label : "Metric")} ▾`);
      btn.addEventListener("click", () => openMetricMenu(btn, cands, cur));
      head.appendChild(btn);
      els.switcher = btn;
    } else {
      const seg = h("div", {class: "u-seg ch-switch", role: "group", "aria-label": "Plotted metric"});
      head.appendChild(seg);
      const inline = cands.slice(0, INLINE_METRICS);
      const rest = cands.slice(INLINE_METRICS);
      let firstPressed = null;
      for (const c of inline) {
        const pressed = c.colId === cur;
        const b = h("button", {type: "button", "data-key": `metric-${c.colId}`, "aria-pressed": String(pressed),
          "aria-disabled": c.enabled ? null : "true", class: c.enabled ? "" : "ch-dim", text: c.label});
        b.addEventListener("click", () => chooseMetric(c));
        if (!c.enabled) bindTip(ctx, b, c.reason || "No value for this metric.", descHost);
        else if (c.positionOnly) bindTip(ctx, b, "Position only: no premium or discount is stated on this metric.", descHost);
        seg.appendChild(b);
        if (pressed) firstPressed = b;
      }
      const restCur = rest.find((c) => c.colId === cur);
      const more = h("button", {type: "button", "data-key": "metric-more", "aria-haspopup": "menu",
        "aria-pressed": String(!!restCur), text: restCur ? `${restCur.label} ▾` : MORE});
      more.addEventListener("click", () => openMetricMenu(more, rest, cur));
      seg.appendChild(more);
      els.switcher = firstPressed || seg.querySelector("button");
    }
    if (dp.tag === "Primary") head.appendChild(chip("Primary", "active"));
    else if (dp.tag === "Position only") head.appendChild(chip("Position only", "neutral"));
    const lanes = dp.lanes || [];
    if (dp.unit && dp.unit !== "×" && dp.unit !== "%") head.appendChild(h("span", {class: "u-meta ch-unit", text: dp.unit}));
    if (lanes.length > 1) head.appendChild(chip(`${lanes.length} cohorts`));
    else if (lanes.length === 1) head.appendChild(chip(`${lanes[0].n} peer ${lanes[0].n === 1 ? "value" : "values"}`));
    if (dp.useAsPrimary) {
      const b = h("button", {type: "button", class: "u-btn ch-use", "data-key": "use-primary", text: "Use as primary"});
      b.addEventListener("click", () => { dispatch(ctx, {type: "SET_PRIMARY", colId: cur}); announce(ctx, `${dp.label} is now the primary metric.`); });
      head.appendChild(b);
    }
    if (dp.useAsPrimary || P.override) {
      const m = h("button", {type: "button", class: "u-btn icon ch-primary-menu", "data-key": "primary-menu",
        "aria-haspopup": "menu", "aria-label": "Primary metric options", text: "▾"});
      m.addEventListener("click", () => {
        const items = [];
        if (dp.useAsPrimary) items.push({id: "use", label: "Use as primary", onSelect: () => dispatch(ctx, {type: "SET_PRIMARY", colId: cur})});
        items.push({id: "reset", label: "Reset primary", disabled: !P.override,
          reason: P.override ? null : "The primary metric is the default already.",
          onSelect: () => { dispatch(ctx, {type: "SET_PRIMARY", colId: null}); announce(ctx, "Primary metric reset to the default."); }});
        openMenu(m, items);
      });
      head.appendChild(m);
    }
  }

  function chooseMetric(c) {
    if (!c.enabled) { announce(ctx, c.reason || "No value for this metric."); return; }
    const P = view.primary;
    dispatch(ctx, {type: "SET_DOT_METRIC", colId: P && c.colId === P.colId ? null : c.colId});
    announce(ctx, `Peer position on ${c.label}`);
  }

  function openMetricMenu(anchor, list, cur) {
    const items = list.map((c) => ({id: c.colId, label: c.positionOnly ? `${c.label}, position only` : c.label,
      checked: c.colId === cur, disabled: !c.enabled, reason: c.enabled ? null : c.reason,
      onSelect: () => chooseMetric(c)}));
    openMenu(anchor, items);
  }

  function openMenu(anchor, items) {
    if (ctx && ctx.menu && typeof ctx.menu.open === "function") ctx.menu.open(anchor, items);
    else {
      const first = items.find((i) => !i.disabled);
      if (first && first.onSelect) first.onSelect();
    }
  }

  // ----- dot plot body -----
  function fillDot(card) {
    const dp = view.dotplot;
    if (!dp) {
      const err = view.sectionErrors && view.sectionErrors.dotplot;
      card.appendChild(stateBlock(err || {severity: "red", title: "This section could not be computed", detail: "Peer position failed."}));
      return;
    }
    if (dp.subtitle) card.appendChild(h("p", {class: "ch-sub"}, h("span", {class: "u-marker amber", "aria-hidden": "true", text: "!"}), dp.subtitle));
    if (dp.disabledState || !dp.domain) {
      card.appendChild(stateBlock(dp.disabledState || {severity: "info", title: "No peer position", detail: dp.disabledReason || ""},
        (a) => runAction(a)));
      return;
    }
    const wrap = h("div", {class: "ch-plot ch-dot-plot", tabindex: "0", role: "group", "data-key": "dot-plot",
      "aria-roledescription": "dot plot"});
    card.appendChild(wrap);
    els.dotPlot = wrap;
    const width = Math.max(240, wrap.clientWidth || card.clientWidth - 2 * DOT.pad || root.clientWidth - 26 || 480);
    const {svg, nav} = drawDot(dp, width);
    wrap.setAttribute("aria-labelledby", svg.__descId);
    wrap.appendChild(svg);
    wrap.__nav = nav;
    wrap.addEventListener("keydown", (e) => dotKey(e, wrap));
    wrap.addEventListener("blur", () => { if (ctx && ctx.tooltip && ctx.tooltip.hide) ctx.tooltip.hide(); });
    if (dp.notPlottedText) {
      const b = h("button", {type: "button", class: "u-btn link ch-notplotted", "data-key": "notplotted", text: dp.notPlottedText});
      b.addEventListener("click", () => goToColumn(ctx, view, dp.colId));
      card.appendChild(b);
    }
  }

  function drawDot(dp, width) {
    const g = dotGeometry(dp, width);
    const svg = svgRoot(width, g.height, `Peer position: ${dp.label}`, dp.description, "ch-dot-svg");
    const nav = [];
    const lanes = dp.lanes || [];
    const fmt = (v) => fmtValue(dp.colId, v);
    // Axis and ticks.
    const ticks = ticksFor(g.scale, Math.max(3, Math.round((g.x1 - g.x0) / 90)));
    const tf = tickFormatter(dp.colId, ticks, g.scale.kind);
    const axis = s("g", {class: "ch-axis"});
    axis.appendChild(s("line", {x1: g.x0, x2: g.x1, y1: g.axisY, y2: g.axisY, class: "ch-axis-line"}));
    const tickItems = ticks.map((t) => ({x: g.scale(t), w: textWidth(tf(t), TICK_PX), anchor: "middle"}));
    const tp = placeLabels(tickItems, {rows: 1, gap: 6, min: 0, max: width});
    ticks.forEach((t, i) => {
      const x = g.scale(t);
      axis.appendChild(s("line", {x1: r1(x), x2: r1(x), y1: g.axisY, y2: g.axisY + 4, class: "ch-tick"}));
      if (!tp[i].dropped) axis.appendChild(label((tp[i].x0 + tp[i].x1) / 2, g.axisY + 15, tf(t), "ch-tick-lbl", "middle"));
    });
    svg.appendChild(axis);
    // Lanes.
    lanes.forEach((lane, li) => {
      const cy = g.laneY(li);
      const lg = s("g", {class: "ch-lane"});
      if (g.multi) {
        const txt = lane.label.length > 17 ? lane.label.slice(0, 16) + "…" : lane.label;
        const t = label(0, cy + 4, txt, "ch-lane-lbl", "start");
        t.appendChild(s("title", {}, `${lane.label}, n ${lane.n}`));
        lg.appendChild(t);
        if (li > 0) lg.appendChild(s("line", {x1: 0, x2: width, y1: g.laneTop(li), y2: g.laneTop(li), class: "ch-lane-sep"}));
      }
      if (isNum(lane.p25) && isNum(lane.p75)) {
        const a = g.scale(lane.p25), b = g.scale(lane.p75);
        lg.appendChild(s("rect", {x: r1(Math.min(a, b)), y: r1(cy - 9), width: r1(Math.max(1, Math.abs(b - a))), height: 18, class: "ch-iqr"}));
      }
      const labels = [];
      const pts = (lane.points || []).slice();
      const focalIdx = pts.findIndex((p) => p.isFocal);
      const xs = pts.map((p) => g.scale(p.x));
      const off = stackPoints(xs, {pin: focalIdx >= 0 ? [focalIdx] : []});
      if (isNum(lane.median)) {
        const mx = g.scale(lane.median);
        lg.appendChild(s("line", {x1: r1(mx), x2: r1(mx), y1: r1(cy - 13), y2: r1(cy + 13), class: "ch-median"}));
        labels.push({key: "median", x: mx, w: textWidth(`Median ${fmt(lane.median)}`), anchor: "middle",
          text: `Median ${fmt(lane.median)}`, cls: "ch-lbl ch-lbl-median", pri: 1});
      }
      // Marks: peers first, then the focal on top.
      const order = pts.map((p, i) => i).sort((a, b) => (pts[a].isFocal ? 1 : 0) - (pts[b].isFocal ? 1 : 0));
      const laneNav = [];
      for (const i of order) {
        const p = pts[i];
        const x = xs[i], y = cy + (p.isFocal ? 0 : off[i]);
        const r = p.isFocal ? DOT.focalR : DOT.peerR;
        const cls = p.isFocal ? "ch-pt ch-pt-focal" : p.excluded ? "ch-pt ch-pt-excl" : "ch-pt";
        const mark = s("circle", {cx: r1(x), cy: r1(y), r, class: cls, "data-ticker": p.ticker});
        mark.addEventListener("click", () => openDetail(ctx, p.ticker));
        hoverTip(ctx, mark, () => p.hover);
        lg.appendChild(mark);
        if (p.clamped) {
          const gx = p.clamped === "lo" ? x - r - 5 : x + r + 5;
          lg.appendChild(label(gx, y + 4, p.clamped === "lo" ? GLYPH.lo : GLYPH.hi, "ch-lbl ch-glyph", p.clamped === "lo" ? "end" : "start"));
        }
        const active = ui.dotActive === p.ticker && ui.dotLane === li;
        if (active) lg.appendChild(s("circle", {cx: r1(x), cy: r1(y), r: r + 3, class: "ch-ring"}));
        if (p.isFocal) {
          // Ticker above the marker (12 px 700) with the value beside it, clear of the median tick.
          const val = fmt(p.v);
          labels.push({key: "focal", x, w: textWidth(p.ticker, FOCAL_LABEL_PX) + textWidth(` ${val}`, 11), anchor: "middle",
            text: p.ticker, value: val, cls: "ch-lbl-focal", pri: 0, required: true});
        } else if (p.label || active) {
          const txt = p.label || p.ticker;
          const anchor = p.clamped === "hi" ? "end" : p.clamped === "lo" ? "start" : "middle";
          labels.push({key: p.ticker, x: p.clamped === "hi" ? g.x1 + 12 : p.clamped === "lo" ? g.x0 - 12 : x,
            w: textWidth(txt), anchor, text: txt, cls: "ch-lbl", pri: active ? 0.5 : 2, required: active});
        }
        laneNav.push({ticker: p.ticker, x, y, announce: p.announce, hover: p.hover, lane: li});
      }
      labels.sort((a, b) => a.pri - b.pri);
      const placed = placeLabels(labels, {rows: 2, gap: 4, min: g.multi ? g.labelW : 0, max: width});
      labels.forEach((l, i) => {
        const pl = placed[i];
        if (pl.dropped) return;
        const y = cy - 15 - pl.row * 12;
        const t = label(pl.x0, y, l.text, l.cls, "start");
        if (l.value) t.appendChild(s("tspan", {class: "ch-lbl-value", dx: 4}, l.value));
        lg.appendChild(t);
      });
      laneNav.sort((a, b) => a.x - b.x || a.ticker.localeCompare(b.ticker));
      nav.push(laneNav);
      svg.appendChild(lg);
    });
    // Analyst target range, below the axis.
    if (dp.target && isNum(dp.target.lo) && isNum(dp.target.hi)) {
      const y = g.axisY + DOT.axisH + 4;
      let a = g.scale(Math.min(dp.target.lo, dp.target.hi)), b = g.scale(Math.max(dp.target.lo, dp.target.hi));
      a = clamp(a, g.x0, g.x1); b = clamp(b, g.x0, g.x1);
      if (b - a < 6) { a -= 3; b += 3; }
      svg.appendChild(s("path", {d: `M${r1(a)},${y - 5}V${y}H${r1(b)}V${y - 5}`, class: "ch-target"}));
      const txt = "Target range (analyst)";
      const lx = clamp(a, 0, width - textWidth(txt));
      svg.appendChild(label(lx, y + 13, txt, "ch-lbl ch-lbl-target", "start"));
    }
    return {svg, nav};
  }

  function dotKey(e, wrap) {
    const nav = wrap.__nav || [];
    if (!nav.length) return;
    let li = clamp(ui.dotLane || 0, 0, nav.length - 1);
    let lane = nav[li];
    let idx = lane.findIndex((p) => p.ticker === ui.dotActive);
    const k = e.key;
    let handled = true;
    if (k === "ArrowRight") idx = idx < 0 ? 0 : Math.min(lane.length - 1, idx + 1);
    else if (k === "ArrowLeft") idx = idx < 0 ? lane.length - 1 : Math.max(0, idx - 1);
    else if (k === "Home") idx = 0;
    else if (k === "End") idx = lane.length - 1;
    else if ((k === "ArrowDown" || k === "ArrowUp") && nav.length > 1) {
      const t = ui.dotActive;
      li = clamp(li + (k === "ArrowDown" ? 1 : -1), 0, nav.length - 1);
      lane = nav[li];
      idx = Math.max(0, lane.findIndex((p) => p.ticker === t));
    } else if (k === "Enter" && idx >= 0) { openDetail(ctx, lane[idx].ticker); }
    else handled = false;
    if (!handled) return;
    e.preventDefault();
    e.stopPropagation();
    if (k === "Enter") return;
    const p = lane[idx];
    if (!p) return;
    ui.dotActive = p.ticker;
    ui.dotLane = li;
    announce(ctx, p.announce);
    render(true);
  }

  // ----- scatter -----
  function fillScatter(card, height) {
    const sc = view.scatter;
    if (!sc) {
      const err = view.sectionErrors && view.sectionErrors.scatter;
      card.appendChild(stateBlock(err || {severity: "red", title: "This section could not be computed", detail: "Valuation against fundamentals failed."}));
      return;
    }
    card.appendChild(scatterControls(sc));
    if (sc.disabledState || !sc.domain || !sc.domain.x || !sc.domain.y) {
      card.appendChild(stateBlock(sc.disabledState || {severity: "info", title: "No valuation against growth chart", detail: sc.disabledReason || ""},
        (a) => runAction(a)));
      return;
    }
    const wrap = h("div", {class: "ch-plot ch-sc-plot", tabindex: "0", role: "group", "data-key": "sc-plot",
      "aria-roledescription": "scatter plot"});
    card.appendChild(wrap);
    els.scPlot = wrap;
    const width = Math.max(260, wrap.clientWidth || card.clientWidth - 2 * DOT.pad || root.clientWidth - 26 || 520);
    const {svg, nav} = drawScatter(sc, width, height);
    wrap.setAttribute("aria-labelledby", svg.__descId);
    wrap.appendChild(svg);
    wrap.__nav = nav;
    wrap.addEventListener("keydown", (e) => scKey(e, wrap));
    wrap.addEventListener("blur", () => { if (ctx && ctx.tooltip && ctx.tooltip.hide) ctx.tooltip.hide(); });
    const interp = h("p", {class: "ch-sc-interp"}, sc.interpretation || "");
    if (sc.region) interp.appendChild(chip(sc.region.label, "neutral", {class: "ch-region"}));
    card.appendChild(interp);
    card.appendChild(scatterLegend(sc));
  }

  function scatterControls(sc) {
    const bar = h("div", {class: "ch-sc-controls"});
    const sel = (key, labelText, options, value, onChange) => {
      const id = uid("chs");
      const el = h("select", {class: "u-input ch-select", id, "data-key": key},
        options.map((o) => h("option", {value: o.id, selected: o.id === value, text: o.label})));
      el.addEventListener("change", () => onChange(el.value));
      return h("label", {class: "ch-field", for: id}, h("span", {class: "u-label", text: labelText}), el);
    };
    bar.appendChild(sel("sc-x", "X", sc.xOptions || [], sc.x, (v) => dispatch(ctx, {type: "SET_SCATTER", x: v})));
    bar.appendChild(sel("sc-y", "Y", sc.yOptions || [], sc.y, (v) => dispatch(ctx, {type: "SET_SCATTER", y: v})));
    bar.appendChild(sel("sc-size", "Size", [{id: "market_cap", label: "Market cap"}, {id: "ev", label: "EV"}, {id: "none", label: "None"}],
      sc.size || "market_cap", (v) => dispatch(ctx, {type: "SET_SCATTER", size: v})));
    const colourLbl = uid("chl");
    const colour = h("div", {class: "u-seg ch-colour", role: "group", "aria-labelledby": colourLbl});
    for (const o of [{id: "none", label: "None"}, {id: "stage", label: "Stage"}]) {
      const b = h("button", {type: "button", "data-key": `sc-colour-${o.id}`, "aria-pressed": String((sc.colorBy || "none") === o.id), text: o.label});
      b.addEventListener("click", () => dispatch(ctx, {type: "SET_SCATTER", colorBy: o.id}));
      colour.appendChild(b);
    }
    bar.appendChild(h("span", {class: "ch-colour-group"}, h("span", {class: "u-label", id: colourLbl, text: "Colour"}), colour));
    const trend = h("button", {type: "button", class: "u-btn", "data-key": "sc-trend", "aria-pressed": String(sc.trendOn !== false), text: "Trend line"});
    trend.addEventListener("click", () => dispatch(ctx, {type: "SET_SCATTER", trend: !(sc.trendOn !== false)}));
    bar.appendChild(trend);
    if (sc.logYOffered) {
      const lg = h("button", {type: "button", class: "u-btn", "data-key": "sc-log", "aria-pressed": String(!!sc.logY), text: "Log scale"});
      lg.addEventListener("click", () => dispatch(ctx, {type: "SET_SCATTER", logY: !sc.logY}));
      bar.appendChild(lg);
    }
    return bar;
  }

  function drawScatter(sc, width, height) {
    const g = scatterGeometry(sc, width, height);
    const svg = svgRoot(width, height, `${sc.yLabel || ""} against ${sc.xLabel || ""}`, sc.description, "ch-sc-svg");
    const clipId = uid("chclip");
    const defs = s("defs", {}, s("clipPath", {id: clipId}, s("rect", {x: g.x0, y: g.y0, width: r1(g.x1 - g.x0), height: r1(g.y1 - g.y0)})));
    svg.appendChild(defs);
    const plotBounds = {x0: g.x0, x1: g.x1, y0: g.y0, y1: g.y1};
    // Grid and axes.
    const yt = ticksFor(g.sy, Math.max(3, Math.round((g.y1 - g.y0) / 56)));
    const xt = ticksFor(g.sx, Math.max(3, Math.round((g.x1 - g.x0) / 90)));
    const yf = tickFormatter(sc.y, yt, g.sy.kind), xf = tickFormatter(sc.x, xt, "linear");
    const grid = s("g", {class: "ch-grid"});
    for (const t of yt) {
      const y = g.sy(t);
      grid.appendChild(s("line", {x1: g.x0, x2: g.x1, y1: r1(y), y2: r1(y), class: "ch-grid-line"}));
      grid.appendChild(label(g.x0 - 6, y + 4, yf(t), "ch-tick-lbl", "end"));
    }
    grid.appendChild(s("line", {x1: g.x0, x2: g.x1, y1: g.y1, y2: g.y1, class: "ch-axis-line"}));
    const xItems = xt.map((t) => ({x: g.sx(t), w: textWidth(xf(t), TICK_PX), anchor: "middle"}));
    const xp = placeLabels(xItems, {rows: 1, gap: 8, min: g.x0 - 20, max: width});
    xt.forEach((t, i) => {
      const x = g.sx(t);
      grid.appendChild(s("line", {x1: r1(x), x2: r1(x), y1: g.y1, y2: g.y1 + 4, class: "ch-tick"}));
      if (!xp[i].dropped) grid.appendChild(label(x, g.y1 + 14, xf(t), "ch-tick-lbl", "middle"));
    });
    svg.appendChild(grid);
    const plot = s("g", {"clip-path": `url(#${clipId})`});
    svg.appendChild(plot);
    // Median x line and its side labels.
    if (isNum(sc.medianX)) {
      const mx = g.sx(sc.medianX);
      if (mx >= g.x0 && mx <= g.x1) {
        plot.appendChild(s("line", {x1: r1(mx), x2: r1(mx), y1: g.y0, y2: g.y1, class: "ch-median-x"}));
        const side = medianSideLabels(sc.x, lcfirst(sc.xLabel || ""));
        const ly = g.y1 + 25;
        const lw = textWidth(side.left, 10), rw = textWidth(side.right, 10);
        if (mx - 6 - lw >= 0) svg.appendChild(label(mx - 6, ly, side.left, "ch-lbl ch-side", "end"));
        if (mx + 6 + rw <= width) svg.appendChild(label(mx + 6, ly, side.right, "ch-lbl ch-side", "start"));
      }
    }
    // Trend and near-trend band.
    const fitPts = (sc.points || []).filter((p) => !p.isFocal && p.inStats);
    const showTrend = sc.trendOn !== false && sc.trend;
    const placedBoxes = [];
    if (showTrend && fitPts.length) {
      const xa = Math.min(...fitPts.map((p) => p.px)), xb = Math.max(...fitPts.map((p) => p.px));
      const band = trendBand(sc.trend, xa, xb);
      if (band.upper.length > 1) {
        const pts = band.upper.concat(band.lower.slice().reverse()).map((p) => `${r1(g.sx(p.x))},${r1(g.sy(p.y))}`);
        plot.appendChild(s("polygon", {points: pts.join(" "), class: "ch-band"}));
        const end = band.upper[band.upper.length - 1];
        const ex = g.sx(end.x), ey = g.sy(end.y);
        const txt = "Near trend";
        const lx = Math.min(ex, g.x1 - 2);
        const box = {x0: lx - textWidth(txt), x1: lx, y0: ey - 12, y1: ey};
        if (box.y0 >= g.y0 && box.x0 >= g.x0) { plot.appendChild(label(lx, ey - 3, txt, "ch-lbl ch-band-lbl", "end")); placedBoxes.push(box); }
      }
      const line = trendSamples(sc.trend, xa, xb).filter((p) => g.sy.kind !== "log" || p.y > 0)
        .map((p) => `${r1(g.sx(p.x))},${r1(g.sy(p.y))}`);
      if (line.length > 1) plot.appendChild(s("polyline", {points: line.join(" "), class: "ch-trend"}));
      const tl = `Peer trend, R² ${fmtNumber(sc.trend.r2, 2)}, n ${sc.trend.n}`;
      svg.appendChild(label(g.x0 + 4, g.y0 + 11, tl, "ch-lbl ch-trend-lbl", "start"));
      placedBoxes.push({x0: g.x0 + 4, x1: g.x0 + 4 + textWidth(tl), y0: g.y0, y1: g.y0 + 14});
    }
    // Points.
    const pts = (sc.points || []).map((p) => ({...p, sxp: g.sx(p.px), syp: g.sy(p.py)}));
    const colourStage = sc.colorBy === "stage";
    const order = pts.map((p, i) => i).sort((a, b) => {
      const pa = pts[a], pb = pts[b];
      if (pa.isFocal !== pb.isFocal) return pa.isFocal ? 1 : -1;
      return (pb.r || 0) - (pa.r || 0);
    });
    const marks = s("g", {class: "ch-marks"});
    svg.appendChild(marks);
    for (const i of order) {
      const p = pts[i];
      const cls = ["ch-mk"];
      if (p.isFocal) cls.push("ch-mk-focal");
      else if (p.excluded) cls.push("ch-mk-excl");
      else if (p.hollow) cls.push("ch-mk-hollow");
      if (colourStage && p.stage === "clinical" && !p.isFocal) cls.push("ch-mk-clinical");
      const mark = s("path", {d: shapePath(p.shape, p.sxp, p.syp, p.r), class: cls.join(" "), "data-ticker": p.ticker});
      mark.addEventListener("click", () => openDetail(ctx, p.ticker));
      hoverTip(ctx, mark, () => p.announce);
      mark.addEventListener("mouseenter", () => {
        if (!p.showLabel && ui.scHover !== p.ticker) { ui.scHover = p.ticker; showHoverLabel(marks, p, g); }
      });
      mark.addEventListener("mouseleave", () => {
        ui.scHover = null;
        const old = marks.querySelector(".ch-hover-lbl");
        if (old) old.remove();
      });
      marks.appendChild(mark);
      if (p.isFocal) marks.appendChild(s("path", {d: shapePath(p.shape, p.sxp, p.syp, p.r + 3), class: "ch-mk-ring"}));
      if (ui.scActive === p.ticker) marks.appendChild(s("path", {d: shapePath(p.shape, p.sxp, p.syp, p.r + (p.isFocal ? 6 : 3)), class: "ch-ring"}));
      const glyphs = [];
      if (p.clampedX) glyphs.push({t: p.clampedX === "lo" ? GLYPH.lo : GLYPH.hi, dx: p.clampedX === "lo" ? -(p.r + 7) : p.r + 7, dy: 4});
      if (p.clampedY) glyphs.push({t: p.clampedY === "lo" ? GLYPH.down : GLYPH.up, dx: 0, dy: p.clampedY === "lo" ? p.r + 11 : -(p.r + 3)});
      for (const gl of glyphs) marks.appendChild(label(p.sxp + gl.dx, p.syp + gl.dy, gl.t, "ch-lbl ch-glyph", "middle"));
    }
    // Labels: focal first, then clamped and the five largest, then the active point.
    const labelled = pts.filter((p) => p.showLabel || ui.scActive === p.ticker)
      .sort((a, b) => (b.isFocal - a.isFocal) || ((ui.scActive === b.ticker) - (ui.scActive === a.ticker)) || (b.r - a.r));
    for (const p of labelled) {
      const isF = p.isFocal;
      const txt = (p.clampedX || p.clampedY) && !isF ? `${p.ticker} ${p.yText}` : p.ticker;
      const px = isF ? FOCAL_LABEL_PX : LABEL_PX;
      const slot = pickLabelSlot({x: p.sxp, y: p.syp, r: p.r + (isF ? 3 : 0)}, textWidth(txt, px), px + 2, placedBoxes,
        {x0: 0, x1: width, y0: 0, y1: g.y1}, isF || ui.scActive === p.ticker);
      if (!slot) continue;
      placedBoxes.push(slot.box);
      marks.appendChild(label(slot.x, slot.y, txt, isF ? "ch-lbl-focal" : "ch-lbl", slot.anchor));
    }
    // Region labels, only where they sit clear of every point and inside the plot.
    if (showTrend && sc.reference === "trend") {
      for (const reg of sc.regions || []) {
        const x = g.sx(reg.x), y = g.sy(reg.y);
        const w = textWidth(reg.label, LABEL_PX);
        const box = {x0: x - w / 2, x1: x + w / 2, y0: y - 10, y1: y + 2};
        if (box.x0 < g.x0 || box.x1 > g.x1 || box.y0 < g.y0 || box.y1 > g.y1) continue;
        if (pts.some((p) => boxNearPoint(box, {x: p.sxp, y: p.syp, r: p.r}, 8))) continue;
        if (placedBoxes.some((b) => boxesOverlap(b, box, 2))) continue;
        placedBoxes.push(box);
        plot.appendChild(label(x, y, reg.label, "ch-lbl ch-region-lbl", "middle"));
      }
    }
    const nav = pts.slice().sort((a, b) => a.px - b.px || a.py - b.py || a.ticker.localeCompare(b.ticker))
      .map((p) => ({ticker: p.ticker, announce: p.announce}));
    return {svg, nav};
  }

  function showHoverLabel(marks, p, g) {
    const old = marks.querySelector(".ch-hover-lbl");
    if (old) old.remove();
    const slot = pickLabelSlot({x: p.sxp, y: p.syp, r: p.r}, textWidth(p.ticker), LABEL_PX + 2, [],
      {x0: 0, x1: g.width, y0: 0, y1: g.y1}, true);
    if (slot) marks.appendChild(label(slot.x, slot.y, p.ticker, "ch-lbl ch-hover-lbl", slot.anchor));
  }

  function scKey(e, wrap) {
    const nav = wrap.__nav || [];
    if (!nav.length) return;
    let idx = nav.findIndex((p) => p.ticker === ui.scActive);
    const k = e.key;
    if (k === "Escape") {
      if (ui.scActive) { e.preventDefault(); e.stopPropagation(); ui.scActive = null; render(true); }
      else wrap.blur();
      return;
    }
    if (k === "ArrowRight") idx = idx < 0 ? 0 : Math.min(nav.length - 1, idx + 1);
    else if (k === "ArrowLeft") idx = idx < 0 ? nav.length - 1 : Math.max(0, idx - 1);
    else if (k === "Home") idx = 0;
    else if (k === "End") idx = nav.length - 1;
    else if (k === "Enter" && idx >= 0) { e.preventDefault(); e.stopPropagation(); openDetail(ctx, nav[idx].ticker); return; }
    else return;
    e.preventDefault();
    e.stopPropagation();
    ui.scActive = nav[idx].ticker;
    announce(ctx, nav[idx].announce);
    render(true);
  }

  function scatterLegend(sc) {
    const T = view.focal ? view.focal.ticker : "";
    // Texts from core (sc.legend, in this order) when it sends them; the spec's words otherwise.
    const words = Array.isArray(sc.legend) && sc.legend.length === 6 ? sc.legend
      : ["Circle: big pharma", "Square: biotech", "Triangle: cell and gene", "Hollow = clinical", `Ring = ${T}`, "Dashed = excluded"];
    const items = [
      {shape: "circle", cls: "ch-mk", text: words[0]},
      {shape: "square", cls: "ch-mk", text: words[1]},
      {shape: "triangle", cls: "ch-mk", text: words[2]},
      {shape: "circle", cls: `ch-mk ch-mk-hollow${sc.colorBy === "stage" ? " ch-mk-clinical" : ""}`, text: words[3]},
      {shape: "circle", cls: "ch-mk ch-mk-focal", ring: true, text: words[4]},
      {shape: "circle", cls: "ch-mk ch-mk-excl", text: words[5]},
    ];
    const ul = h("ul", {class: "ch-legend", "aria-label": "Legend"});
    for (const it of items) {
      const icon = s("svg", {width: 14, height: 14, viewBox: "0 0 14 14", "aria-hidden": "true", focusable: "false", class: "ch-legend-icon"},
        s("path", {d: shapePath(it.shape, 7, 7, 4.2), class: it.cls}));
      if (it.ring) icon.appendChild(s("path", {d: shapePath("circle", 7, 7, 6.2), class: "ch-mk-ring"}));
      ul.appendChild(h("li", {}, icon, h("span", {text: it.text})));
    }
    return ul;
  }

  function runAction(a) {
    if (!a) return;
    if (a.command === "peers.restore") dispatch(ctx, {type: "RESTORE_SYSTEM", now: Date.now()});
    else if (a.command === "peers.addAdjacent") dispatch(ctx, {type: "ADD_POOL_C"});
    else if (a.type) dispatch(ctx, a);
  }

  function hiddenHost(parent) {
    const host = h("div", {hidden: true, class: "ch-desc"});
    parent.appendChild(host);
    return host;
  }

  function ensureStripOpen(tab) {
    const layout = layoutOf(ctx, root);
    if (!stripMode(layout)) return;
    const st = stateOf(ctx) || {};
    const key = layout === "narrow" ? "narrowTab" : "laptopTab";
    if (((st.chartStrip || {})[layout]) === "collapsed") dispatch(ctx, {type: "SET_CHART_STRIP", layout, value: "open"});
    if ((st.ui && st.ui[key]) !== tab) dispatch(ctx, {type: layout === "narrow" ? "SET_NARROW_TAB" : "SET_LAPTOP_TAB", tab});
    render(true);
  }
  function focusLater(getEl) {
    const go = () => { const el = getEl(); if (el) { el.focus(); el.scrollIntoView && el.scrollIntoView({block: "nearest"}); } };
    go();
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(go);
  }

  return {
    update(v) { view = v; render(false); },
    focusDotPlot() { ensureStripOpen("position"); focusLater(() => root.querySelector('[data-key="dot-plot"]')); },
    focusSwitcher() {
      ensureStripOpen("position");
      focusLater(() => root.querySelector('.ch-switch [aria-pressed="true"]') || root.querySelector('[data-key="switcher"]')
        || root.querySelector(".ch-switch button"));
    },
    focusScatter() { ensureStripOpen("scatter"); focusLater(() => root.querySelector('[data-key="sc-plot"]')); },
    focusPoint(ticker) {
      const dp = view && view.dotplot;
      const inDot = dp && (dp.lanes || []).some((l) => (l.points || []).some((p) => p.ticker === ticker));
      if (inDot) {
        const li = Math.max(0, (dp.lanes || []).findIndex((l) => (l.points || []).some((p) => p.ticker === ticker)));
        ui.dotActive = ticker; ui.dotLane = li;
        ensureStripOpen("position");
        focusLater(() => root.querySelector('[data-key="dot-plot"]'));
        const pt = dp.lanes[li].points.find((p) => p.ticker === ticker);
        if (pt) announce(ctx, pt.announce);
      } else {
        ui.scActive = ticker;
        ensureStripOpen("scatter");
        focusLater(() => root.querySelector('[data-key="sc-plot"]'));
      }
    },
    destroy() { destroyed = true; if (ro) ro.disconnect(); root.textContent = ""; root.classList.remove("ch-root"); },
  };
}

// ---------------------------------------------------------------------------------------------
// mountBridgeChart (5.3): waterfall for EV multiples, then the per-share strip
// ---------------------------------------------------------------------------------------------

export function mountBridgeChart(root, ctx) {
  root.classList.add("ch-br");
  let view = null, lastSig = null, lastWidth = 0, destroyed = false;
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => {
    const w = root.clientWidth;
    if (Math.abs(w - lastWidth) >= 1 && view) { lastWidth = w; render(true); }
  }) : null;
  if (ro) ro.observe(root);

  function render(force) {
    if (destroyed || !view) return;
    const b = view.bridge;
    const signature = sig(root.clientWidth, b, view.sectionErrors && view.sectionErrors.bridge);
    if (!force && signature === lastSig) return;
    lastSig = signature;
    lastWidth = root.clientWidth;
    root.textContent = "";
    if (!b) {
      root.appendChild(stateBlock((view.sectionErrors && view.sectionErrors.bridge) ||
        {severity: "red", title: "This section could not be computed", detail: "Valuation bridge failed."}));
      return;
    }
    if (!b.enabled) {
      root.appendChild(stateBlock({severity: "info", title: "No bridge", detail: b.reason || ""}));
      return;
    }
    const width = Math.max(280, root.clientWidth || 520);
    root.appendChild(h("p", {class: "u-sr", text: b.description || ""}));
    if (b.isEV) root.appendChild(drawWaterfall(b, width));
    root.appendChild(drawPerShare(b, width));
    if (b.negativeEquity) root.appendChild(h("p", {class: "ch-br-note"}, h("span", {class: "u-marker amber", "aria-hidden": "true", text: "!"}), b.reason || ""));
  }

  function drawWaterfall(b, width) {
    const rows = waterfallRows(b);
    const rowH = 22, gap = 6, labelW = 128, top = 6, axisH = 26;
    const height = top + rows.length * (rowH + gap) + axisH;
    const vals = rows.flatMap((r) => [r.x0, r.x1]);
    const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    const span = hi - lo || 1;
    const x0 = labelW, x1 = width - 56;
    const sc = linearScale([lo - span * 0.02, hi + span * 0.04], [x0, x1]);
    const cur = b.currency || "USD";
    const svg = svgRoot(width, height, "Valuation bridge: enterprise value to equity", b.description, "ch-br-svg");
    const fmtBn = (v, signed) => fmtNumber(v / 1000, 1, {signed});
    const ticks = niceTicks(sc.domain[0], sc.domain[1], Math.max(3, Math.round((x1 - x0) / 90)));
    const tf = tickFormatter("ev", ticks);
    const axisY = top + rows.length * (rowH + gap);
    svg.appendChild(s("line", {x1: x0, x2: x1, y1: axisY, y2: axisY, class: "ch-axis-line"}));
    for (const t of ticks) {
      const x = sc(t);
      svg.appendChild(s("line", {x1: r1(x), x2: r1(x), y1: top, y2: axisY, class: "ch-grid-line"}));
      svg.appendChild(label(x, axisY + 14, tf(t), "ch-tick-lbl", "middle"));
    }
    svg.appendChild(label(0, axisY + 14, `${cur} bn`, "ch-tick-lbl", "start"));
    if (lo < 0) svg.appendChild(s("line", {x1: r1(sc(0)), x2: r1(sc(0)), y1: top, y2: axisY, class: "ch-zero"}));
    rows.forEach((r, i) => {
      const y = top + i * (rowH + gap);
      const a = sc(Math.min(r.x0, r.x1)), c = sc(Math.max(r.x0, r.x1));
      svg.appendChild(label(0, y + rowH / 2 + 4, r.label, "ch-br-lbl", "start"));
      svg.appendChild(s("rect", {x: r1(a), y, width: r1(Math.max(1, c - a)), height: rowH, class: r.kind === "total" ? "ch-br-total" : "ch-br-step"}));
      const text = r.kind === "step" ? fmtBn(r.value, true) : fmtBn(r.value, false);
      const endX = r.x1 >= r.x0 ? c : a;
      const right = r.x1 >= r.x0;
      svg.appendChild(label(right ? endX + 4 : endX - 4, y + rowH / 2 + 4, text, "ch-lbl ch-br-val", right ? "start" : "end"));
      if (i < rows.length - 1) {
        const nx = sc(r.x1);
        svg.appendChild(s("line", {x1: r1(nx), x2: r1(nx), y1: y + rowH, y2: y + rowH + gap, class: "ch-br-conn"}));
      }
    });
    return h("div", {class: "ch-br-block"}, svg);
  }

  function drawPerShare(b, width) {
    const values = bridgeStripValues(b);
    const dom = paddedDomain(values, 0.08) || [0, 1];
    const x0 = 40, x1 = width - 16;
    const sc = linearScale(dom, [x0, x1]);
    const height = 90, my = 56, axisY = 70;
    const title = "Implied value per share against price";
    const svg = svgRoot(width, height, title, b.description, "ch-br-strip");
    const ticks = niceTicks(dom[0], dom[1], Math.max(3, Math.round((x1 - x0) / 90)));
    const tf = tickFormatter("price", ticks);
    svg.appendChild(s("line", {x1: x0, x2: x1, y1: axisY, y2: axisY, class: "ch-axis-line"}));
    for (const t of ticks) {
      const x = sc(t);
      svg.appendChild(s("line", {x1: r1(x), x2: r1(x), y1: axisY, y2: axisY + 4, class: "ch-tick"}));
      svg.appendChild(label(x, axisY + 15, tf(t), "ch-tick-lbl", "middle"));
    }
    svg.appendChild(label(0, axisY + 15, "USD", "ch-tick-lbl", "start"));
    const labels = [];
    if (b.range) {
      const a = sc(b.range[0]), c = sc(b.range[1]);
      svg.appendChild(s("rect", {x: r1(a), y: my - 7, width: r1(Math.max(2, c - a)), height: 14, class: "ch-br-iqr"}));
      labels.push({x: a, w: textWidth("Interquartile range"), anchor: "start", text: "Interquartile range", pri: 4});
    }
    if (isNum(b.price)) {
      const x = sc(b.price);
      svg.appendChild(s("line", {x1: r1(x), x2: r1(x), y1: my - 12, y2: my + 12, class: "ch-price"}));
      labels.push({x, w: textWidth(`Price ${fmtNumber(b.price, 2)}`), anchor: "middle", text: `Price ${fmtNumber(b.price, 2)}`, pri: 1, required: true});
    }
    if (b.streetTarget && isNum(b.streetTarget.value)) {
      const x = sc(b.streetTarget.value);
      svg.appendChild(s("line", {x1: r1(x), x2: r1(x), y1: my - 7, y2: my + 7, class: "ch-street"}));
      labels.push({x, w: textWidth(`Street ${fmtNumber(b.streetTarget.value, 2)}`), anchor: "middle", text: `Street ${fmtNumber(b.streetTarget.value, 2)}`, pri: 2});
    }
    if (b.modelFairValue && isNum(b.modelFairValue.value)) {
      const x = sc(b.modelFairValue.value);
      svg.appendChild(s("path", {d: diamondPath(x, my, 5), class: "ch-model"}));
      labels.push({x, w: textWidth(`Model ${fmtNumber(b.modelFairValue.value, 2)}`), anchor: "middle", text: `Model ${fmtNumber(b.modelFairValue.value, 2)}`, pri: 3});
    }
    if (isNum(b.V)) {
      const x = sc(b.V);
      svg.appendChild(s("path", {d: diamondPath(x, my, 6), class: "ch-implied"}));
      labels.push({x, w: textWidth(`Implied ${fmtNumber(b.V, 2)}`, 11), anchor: "middle", text: `Implied ${fmtNumber(b.V, 2)}`, pri: 0, required: true, cls: "ch-lbl-implied"});
    }
    labels.sort((a, c) => a.pri - c.pri);
    const placed = placeLabels(labels, {rows: 3, gap: 6, min: 0, max: width});
    labels.forEach((l, i) => {
      const p = placed[i];
      if (p.dropped) return;
      svg.appendChild(label(p.x0, my - 16 - p.row * 12, l.text, l.cls || "ch-lbl", "start"));
    });
    return h("div", {class: "ch-br-block"}, svg);
  }

  return {
    update(v) { view = v; render(false); },
    destroy() { destroyed = true; if (ro) ro.disconnect(); root.textContent = ""; root.classList.remove("ch-br"); },
  };
}

// ---------------------------------------------------------------------------------------------
// positionStrip (KPI 5): 120 x 20, IQR band, median tick, focal diamond
// ---------------------------------------------------------------------------------------------

/**
 * `positionStrip(strip, opts)` -> SVGElement. `strip` is a View PositionStrip
 * ({domain, scale, p25, median, p75, focal, clamped, description}); opts {width, height}.
 * Returns an empty labelled SVG when the strip is null, so the KPI cell keeps its layout.
 */
export function positionStrip(strip, opts = {}) {
  const width = opts.width || STRIP.width, height = opts.height || STRIP.height;
  const desc = strip && strip.description ? strip.description : "No position on this metric.";
  const svg = s("svg", {class: "ch-strip", width, height, viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": desc, focusable: "false"});
  svg.appendChild(s("title", {}, desc));
  const g = stripGeometry(strip, width);
  if (!g) return svg;
  const cy = height / 2;
  svg.appendChild(s("line", {x1: g.x0, x2: g.x1, y1: cy, y2: cy, class: "ch-strip-base"}));
  if (isNum(g.p25) && isNum(g.p75)) {
    svg.appendChild(s("rect", {x: r1(Math.min(g.p25, g.p75)), y: cy - 4, width: r1(Math.max(1, Math.abs(g.p75 - g.p25))), height: 8, class: "ch-strip-iqr"}));
  }
  if (isNum(g.median)) svg.appendChild(s("line", {x1: r1(g.median), x2: r1(g.median), y1: cy - 6, y2: cy + 6, class: "ch-strip-median"}));
  if (isNum(g.focal)) {
    if (g.clamped) {
      const x = g.clamped === "lo" ? 1 : width - 1;
      svg.appendChild(s("text", {x, y: cy + 4, class: "ch-strip-edge", "text-anchor": g.clamped === "lo" ? "start" : "end"},
        g.clamped === "lo" ? GLYPH.lo : GLYPH.hi));
    } else {
      svg.appendChild(s("path", {d: diamondPath(g.focal, cy, 3.5), class: "ch-strip-focal"}));
    }
  }
  return svg;
}

// ---------------------------------------------------------------------------------------------
// Side panel minis (5.4)
// ---------------------------------------------------------------------------------------------

function miniSvg(width, height, labelText, cls) {
  const svg = s("svg", {class: `ch-mini ${cls}`, width, height, viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": labelText || "", focusable: "false"});
  if (labelText) svg.appendChild(s("title", {}, labelText));
  return svg;
}

/** `sparkline(values, {width, height, label})`: 1 px text line, a dot on the last point. */
export function sparkline(values, opts = {}) {
  const width = opts.width || 160, height = opts.height || 36;
  const svg = miniSvg(width, height, opts.label || "", "ch-spark");
  const v = (values || []).map((x) => (isNum(x) ? x : null));
  const fin = v.filter(isNum);
  if (fin.length < 2) return svg;
  const sx = linearScale([0, v.length - 1], [2, width - 4]);
  const lo = Math.min(...fin), hi = Math.max(...fin);
  const sy = linearScale(lo === hi ? [lo - 1, hi + 1] : [lo, hi], [height - 3, 3]);
  let d = "", pen = false;
  v.forEach((y, i) => {
    if (!isNum(y)) { pen = false; return; }
    d += `${pen ? "L" : "M"}${r1(sx(i))},${r1(sy(y))}`;
    pen = true;
  });
  svg.appendChild(s("path", {d, class: "ch-spark-line"}));
  let li = v.length - 1;
  while (li >= 0 && !isNum(v[li])) li--;
  if (li >= 0) svg.appendChild(s("circle", {cx: r1(sx(li)), cy: r1(sy(v[li])), r: 2, class: "ch-spark-dot"}));
  return svg;
}

let PATTERN_N = 0;
/**
 * `barMini(series, {width, height, derivedIndex, label, labels})`: vertical bars from a zero
 * baseline. `series` holds numbers (null draws no bar) or `{value, label}`; bars whose index is in
 * `derivedIndex` are hatched. Bar labels print under the bars when given.
 */
export function barMini(series, opts = {}) {
  const width = opts.width || 200, height = opts.height || 64;
  const svg = miniSvg(width, height, opts.label || "", "ch-bars");
  const items = (series || []).map((x) => (x && typeof x === "object" ? x : {value: x}));
  const vals = items.map((x) => (isNum(x.value) ? x.value : null));
  const fin = vals.filter(isNum);
  if (!fin.length) return svg;
  const lbls = opts.labels || items.map((x) => x.label || "");
  const hasLbl = lbls.some(Boolean);
  const bottom = height - (hasLbl ? 14 : 2);
  const lo = Math.min(0, ...fin), hi = Math.max(0, ...fin);
  const sy = linearScale([lo, hi === lo ? lo + 1 : hi], [bottom, 4]);
  const n = items.length;
  const slot = (width - 4) / Math.max(1, n);
  const bw = Math.max(2, slot * 0.66);
  const derived = new Set(opts.derivedIndex || []);
  let patId = null;
  if (derived.size) {
    PATTERN_N += 1;
    patId = `ch-hatch-${PATTERN_N}`;
    svg.appendChild(s("defs", {}, s("pattern", {id: patId, width: 4, height: 4, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)"},
      s("rect", {x: 0, y: 0, width: 4, height: 4, class: "ch-hatch-bg"}), s("line", {x1: 0, y1: 0, x2: 0, y2: 4, class: "ch-hatch-line"}))));
  }
  const y0 = sy(0);
  items.forEach((it, i) => {
    const v = vals[i];
    const cx = 2 + slot * i + slot / 2;
    if (isNum(v)) {
      const y = sy(v);
      const rect = s("rect", {x: r1(cx - bw / 2), y: r1(Math.min(y, y0)), width: r1(bw), height: r1(Math.max(1, Math.abs(y0 - y))),
        class: derived.has(i) ? "ch-bar ch-bar-derived" : v < 0 ? "ch-bar ch-bar-neg" : "ch-bar"});
      if (derived.has(i) && patId) rect.style.fill = `url(#${patId})`;
      if (it.title) rect.appendChild(s("title", {}, it.title));
      svg.appendChild(rect);
    }
    if (hasLbl && lbls[i]) svg.appendChild(s("text", {x: r1(cx), y: height - 3, class: "ch-mini-lbl", "text-anchor": "middle"}, lbls[i]));
  });
  svg.appendChild(s("line", {x1: 2, x2: width - 2, y1: r1(y0), y2: r1(y0), class: "ch-mini-zero"}));
  return svg;
}

/**
 * `lineMini(series, labels, opts)`: small multi-line chart. `series` is
 * `[{name, values, tone: "peer" | "focal"}]`: peer in text colour, focal active and dashed.
 * `labels` are the x labels (first and last are printed). opts {width, height, label, format}.
 */
export function lineMini(series, labels, opts = {}) {
  const width = opts.width || 260, height = opts.height || 90;
  const svg = miniSvg(width, height, opts.label || "", "ch-lines");
  const all = (series || []).flatMap((x) => (x.values || []).filter(isNum));
  const n = Math.max(0, ...(series || []).map((x) => (x.values || []).length));
  if (!all.length || n < 2) return svg;
  const left = 36, bottom = height - 14;
  const sx = linearScale([0, n - 1], [left, width - 8]);
  const lo = Math.min(0, ...all), hi = Math.max(...all);
  const sy = linearScale(lo === hi ? [lo - 1, hi + 1] : [lo, hi], [bottom, 6]);
  const fmt = opts.format || ((v) => fmtNumber(v * 100, 0) + "%");
  const ticks = niceTicks(sy.domain[0], sy.domain[1], 3);
  for (const t of ticks) {
    svg.appendChild(s("line", {x1: left, x2: width - 8, y1: r1(sy(t)), y2: r1(sy(t)), class: t === 0 ? "ch-mini-zero" : "ch-grid-line"}));
    svg.appendChild(s("text", {x: left - 4, y: r1(sy(t)) + 3, class: "ch-mini-lbl", "text-anchor": "end"}, fmt(t)));
  }
  (labels || []).forEach((l, i) => {
    if (i === 0 || i === (labels.length - 1)) svg.appendChild(s("text", {x: r1(sx(i)), y: height - 2, class: "ch-mini-lbl", "text-anchor": i === 0 ? "start" : "end"}, l));
  });
  for (const ser of series || []) {
    let d = "", pen = false;
    (ser.values || []).forEach((v, i) => {
      if (!isNum(v)) { pen = false; return; }
      d += `${pen ? "L" : "M"}${r1(sx(i))},${r1(sy(v))}`;
      pen = true;
    });
    const focal = ser.tone === "focal" || ser.tone === "active";
    const path = s("path", {d, class: focal ? "ch-line ch-line-focal" : "ch-line"});
    path.appendChild(s("title", {}, ser.name || ""));
    svg.appendChild(path);
  }
  return svg;
}

const PHASE_ORDER = ["Preclinical", "Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Filed", "Phase 4", "Marketed"];
const PHASE_CLASS = {"Preclinical": "ch-ph-pre", "Phase 1": "ch-ph-1", "Phase 1/2": "ch-ph-1", "Phase 2": "ch-ph-2",
  "Phase 2/3": "ch-ph-2", "Phase 3": "ch-ph-3", "Filed": "ch-ph-3", "Phase 4": "ch-ph-approved", "Marketed": "ch-ph-approved"};

/**
 * `phaseBars(compounds, opts)`: horizontal bars of compounds by phase, from the phase ramp
 * tokens (preclinical to phase 3, approved for Phase 4 or marketed; never the filed step, which is
 * the flag colour). Labels and counts always shown. `compounds` is `{phase: count}`.
 */
export function phaseBars(compounds, opts = {}) {
  const entries = PHASE_ORDER.filter((p) => compounds && isNum(compounds[p])).map((p) => [p, compounds[p]])
    .concat(Object.entries(compounds || {}).filter(([p, v]) => !PHASE_ORDER.includes(p) && isNum(v)));
  const rowH = 16;
  const width = opts.width || 260, height = opts.height || Math.max(rowH, entries.length * rowH + 2);
  const total = entries.reduce((a, [, v]) => a + v, 0);
  const svg = miniSvg(width, height, opts.label || `Compounds by phase: ${entries.map(([p, v]) => `${p} ${v}`).join(", ")}`, "ch-phase");
  if (!entries.length) return svg;
  const labelW = 70, countW = 30;
  const max = Math.max(1, ...entries.map(([, v]) => v));
  const sx = linearScale([0, max], [labelW, width - countW]);
  entries.forEach(([p, v], i) => {
    const y = i * rowH + 1;
    svg.appendChild(s("text", {x: 0, y: y + 11, class: "ch-mini-lbl ch-phase-lbl"}, p));
    svg.appendChild(s("rect", {x: labelW, y: y + 3, width: r1(Math.max(v > 0 ? 1 : 0, sx(v) - labelW)), height: rowH - 6, class: `ch-ph ${PHASE_CLASS[p] || "ch-ph-pre"}`}));
    svg.appendChild(s("text", {x: r1(sx(v) + 4), y: y + 11, class: "ch-mini-lbl"}, String(v)));
  });
  void total;
  return svg;
}

// Re-exported for panels.js so both modules format dates the same way.
export {fmtDate, metricLabel};
