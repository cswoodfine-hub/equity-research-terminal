/**
 * charts.js: the SVG charts of the Comps valuation view. Owner D.
 *
 * Contract: docs/design/comps-valuation.md section 5 (5.1 dot plot, 5.3 bridge chart, 5.4 side
 * panel minis). The valuation-against-growth scatter (5.2) and KPI 5's position strip left with
 * revision 4 (company-scorecard.md 5.2). Exports of 11.1:
 *
 *   mountCharts(root, ctx) -> {update(view), focusDotPlot(), focusPoint(ticker), destroy()}
 *                              (plus focusSwitcher() for the `m` key)
 *   mountBridgeChart(root, ctx) -> {update(view), destroy()}
 *   sparkline, barMini, lineMini, phaseBars -> SVGElement
 *
 * Every chart reads its geometry from `view` (core.deriveView), uses tokens only (classes in
 * charts.css, no colour literal here), carries a <title> and a <desc> with the view's
 * description, and is one tab stop with arrow-key point navigation. The pure geometry helpers
 * (scales, ticks, domains, label and point collision, the waterfall) are exported for the node
 * tests in frontend/tests/compsval/charts.test.js; they touch no DOM.
 */

import {
  COLUMN_BY_ID, NULL_GLYPH, fmtCell, fmtNumber, fmtDate, metricLabel,
} from "./core.js";

// ---------------------------------------------------------------------------------------------
// Constants (5.1 to 5.4)
// ---------------------------------------------------------------------------------------------

export const DOT = {laneH: 56, laneLabelW: 112, axisH: 24, headerH: 28, pad: 12, top: 6, targetH: 22,
  peerR: 4, focalR: 7, stackGap: 8, stackRows: [0, -6, 6]};
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
// mountCharts: the dot plot (5.1) in a folding strip (1.3)
// ---------------------------------------------------------------------------------------------

export function mountCharts(root, ctx) {
  const doc = root.ownerDocument;
  root.classList.add("ch-root");
  let view = null;
  let lastSig = null;
  let lastWidth = 0;
  const ui = {dotActive: null, dotLane: 0};
  const els = {dotPlot: null, switcher: null, tabs: []};
  let destroyed = false;

  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => {
    const w = root.clientWidth;
    if (Math.abs(w - lastWidth) >= 1 && view) { lastWidth = w; render(true); }
  }) : null;
  if (ro) ro.observe(root);

  function render(force = false) {
    if (destroyed || !view) return;
    const layout = layoutOf(ctx, root);
    const st = stateOf(ctx) || {};
    // Revision 4 (company-scorecard.md 5.2): the strip is the Position chart alone, folded until
    // opened.
    const stripState = ((st.chartStrip || {})[layout]) || "collapsed";
    const signature = sig(layout, stripState, root.clientWidth, view.dotplot, view.primary,
      view.sectionErrors && view.sectionErrors.dotplot, ui);
    if (!force && signature === lastSig) return;
    lastSig = signature;
    lastWidth = root.clientWidth;
    rebuildKeepingFocus(root, () => {
      root.textContent = "";
      root.setAttribute("data-layout", layout);
      buildStrip(layout, stripState);
    });
  }

  // ----- strip, every width -----
  function buildStrip(layout, stripState) {
    const collapsed = stripState === "collapsed";
    const head = h("div", {class: "ch-strip-head"});
    root.appendChild(head);
    const list = h("div", {class: "ch-tabs", role: "tablist", "aria-label": "Charts"});
    head.appendChild(list);
    const panelId = uid("chp");
    const tab = h("button", {type: "button", role: "tab", class: "ch-tab", id: `${panelId}-t0`, "data-key": "tab-position",
      "aria-selected": "true", "aria-controls": panelId, tabindex: "0", text: "Position"});
    list.appendChild(tab);
    els.tabs = [tab];
    if (!collapsed) dotHeaderItems(head, true);
    const spacer = h("span", {class: "ch-spacer"});
    head.appendChild(spacer);
    const col = h("button", {type: "button", class: "u-btn icon ch-collapse", "data-key": "collapse",
      "aria-expanded": String(!collapsed), "aria-controls": panelId,
      "aria-label": collapsed ? "Expand charts" : "Collapse charts", text: collapsed ? "⌄" : "⌃"});
    col.addEventListener("click", () => dispatch(ctx, {type: "SET_CHART_STRIP", layout, value: collapsed ? "open" : "collapsed"}));
    head.appendChild(col);
    const panel = h("div", {class: "ch-strip-panel", role: "tabpanel", id: panelId,
      "aria-labelledby": `${panelId}-t0`, hidden: collapsed});
    root.appendChild(panel);
    if (collapsed) return;
    const card = h("div", {class: "ch-card ch-dot ch-in-strip"});
    panel.appendChild(card);
    fillDot(card);
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

  function ensureStripOpen() {
    const layout = layoutOf(ctx, root);
    const st = stateOf(ctx) || {};
    if (((st.chartStrip || {})[layout] || "collapsed") === "collapsed") dispatch(ctx, {type: "SET_CHART_STRIP", layout, value: "open"});
    render(true);
  }
  function focusLater(getEl) {
    const go = () => { const el = getEl(); if (el) { el.focus(); el.scrollIntoView && el.scrollIntoView({block: "nearest"}); } };
    go();
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(go);
  }

  return {
    update(v) { view = v; render(false); },
    focusDotPlot() { ensureStripOpen(); focusLater(() => root.querySelector('[data-key="dot-plot"]')); },
    focusSwitcher() {
      ensureStripOpen();
      focusLater(() => root.querySelector('.ch-switch [aria-pressed="true"]') || root.querySelector('[data-key="switcher"]')
        || root.querySelector(".ch-switch button"));
    },
    focusPoint(ticker) {
      const dp = view && view.dotplot;
      const inDot = dp && (dp.lanes || []).some((l) => (l.points || []).some((p) => p.ticker === ticker));
      if (!inDot) return;
      const li = Math.max(0, (dp.lanes || []).findIndex((l) => (l.points || []).some((p) => p.ticker === ticker)));
      ui.dotActive = ticker; ui.dotLane = li;
      ensureStripOpen();
      focusLater(() => root.querySelector('[data-key="dot-plot"]'));
      const pt = dp.lanes[li].points.find((p) => p.ticker === ticker);
      if (pt) announce(ctx, pt.announce);
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
