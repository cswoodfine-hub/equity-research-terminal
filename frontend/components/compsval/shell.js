/**
 * shell.js: the frame of the Comps valuation view. Owner E.
 *
 * Contract: docs/design/comps-valuation.md. Per 11.1 this module owns the Streamlit protocol
 * shim, installTokens, installSharedCss, copyFontFaces, fitFrame and the --band-h / --main-h
 * observer (1.2), the storage wrapper (try/catch, core.migrateState), state and dispatch over
 * core.reduce, the layout with its breakpoints and height modes (1.3, 1.6), the header band
 * (1.5: context bar with its collapse steps, the scope line with its overflow menu), the
 * company selector, the command palette, the shortcut help with the single-key toggle, the
 * keyboard (7.1 to 7.4),
 * the shared tooltip, menu, undo toast and live region, CSV and clipboard actions, and the
 * shell's share of the state catalogue (8).
 *
 * The table (table.js), the charts (charts.js) and the panels (panels.js) are mounted into
 * slots through `ctx` exactly as 11.1 defines it. They are imported dynamically: a module that
 * is missing, fails to parse or lacks an export renders the calculation-failure state of
 * section 8 in its slot, and the rest of the view keeps working.
 *
 * Cooperation rules for the mounts (all optional, all defensive here):
 * - A mount that consumes a key calls preventDefault(); the shell's handler skips such events,
 *   so a key is never run twice.
 * - ctx.layout and ctx.height are getters, always current. ctx also carries a few helpers
 *   beyond 11.1: focusCell, scrollToColumn, goToColumn, scrollToSection, closeMethod, flush,
 *   runCommand and isMac.
 * - ctx.tooltip.describe(anchor, content) registers the anchor's tooltip: it gets hover and
 *   keyboard-focus behaviour from the shared tooltip and an aria-describedby to a hidden copy.
 *
 * Revision 4 (docs/design/company-scorecard.md 1.4, 5.2, 6.2 to 6.4): two views behind a switch
 * in the context bar. Scorecard (the default) mounts the scorecard, Compare, the company panel
 * and the methodology drawer; Table mounts the scope line, the comparables table, the folded
 * position chart, the company panel, the peer drawer and the methodology drawer. The conclusion
 * banner, "Why?", the KPI strip, Drivers and risks and the focal context that fed it left with
 * build step 6, their code with them. The chart of the
 * Scorecard view arrives as an SVG string (`chart_svg`, with `chart_digest`) that Python drew;
 * ctx.chart hands it to scorecard.js, which shows it and binds its bubbles.
 */

import * as core from "./core.js";

// ---------------------------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------------------------

const NULL = core.NULL_GLYPH;
// The module also loads without a DOM (node tests of the pure helpers below): nothing is
// built, imported or posted there.
const HAS_DOM = typeof window !== "undefined" && typeof document !== "undefined";
const IS_MAC = (() => {
  try { return /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent || ""); } catch (e) { return false; }
})();
const MIN_FRAME_H = 560;          // 1.2 floor
const FRAME_GAP = 12;             // 1.2: parent.innerHeight - frameTop - 12
const FALLBACK_H = 900;           // the height arg's default
const TIP_DELAY = 300;            // 7.5
const STEP_ROOM = 24;             // 1.5: reverse a collapse step when this much room is left
const BREAK = {ultrawide: 2200, wide: 1700, laptop: 1100};
// Collapse steps of 1.5 and the row each belongs to in the two-row narrow bar.
const STEP_ROW = {1: "id", 2: "id", 3: "ctl", 4: "ctl", 5: "id", 6: "ctl", 7: "ctl", 8: "ctl"};
const STEPS = [1, 2, 3, 4, 5, 6, 7, 8];
const SECTIONS = {
  charts: {label: "peer position", slot: "charts"},
  table: {label: "comparable companies", slot: "table"},
};
const CURRENCY_ITEMS = [["USD", "Standardised, USD"], ["EUR", "Standardised, EUR"], ["GBP", "Standardised, GBP"],
  ["CHF", "Standardised, CHF"], ["DKK", "Standardised, DKK"], ["REPORTED", "As reported, filing currency"]];
const RELOAD_TIP = "Reload the comps from the API. Refresh all in the top bar fetches new data from the sources.";
const KEYS_ON_TEXT = "Keyboard shortcuts, keys active";
const KEYS_OFF_TEXT = "Keyboard shortcuts, click the view to use keys";
const SINGLE_KEY_NOTE = "Turn off single keys if they clash with a screen reader or speech input.";
const SAVED_HERE = "Saved in this browser only.";

// Mounts (11.1, revised by 12.1): module, export, slot and the section name used in a failure
// state. The bridge leaves the Comps view; the Forecast tab draws it in bridge mode (12.5).
const FULL_MOUNTS = [
  {id: "scorecard", mod: "scorecard", fn: "mountScorecard", slot: "scorecard", section: "Company scorecard"},
  {id: "compare", mod: "scorecard", fn: "mountCompare", slot: "compare", section: "Compare"},
  {id: "charts", mod: "charts", fn: "mountCharts", slot: "charts", section: "Peer position"},
  {id: "table", mod: "table", fn: "mountTable", slot: "table", section: "Comparable companies table"},
  {id: "peers", mod: "panels", fn: "mountPeerPanel", slot: "peers", section: "Peer selection"},
  {id: "method", mod: "panels", fn: "mountMethod", slot: "method", section: "Methodology"},
  {id: "detail", mod: "panels", fn: "mountDetail", slot: "detail", section: "Side panel"},
];
const BRIDGE_MOUNTS = [
  {id: "bridgeInputs", mod: "panels", fn: "mountBridgeInputs", slot: "bridgeInputs", section: "Peer-multiple value inputs"},
  {id: "bridgeChart", mod: "charts", fn: "mountBridgeChart", slot: "bridgeChart", section: "Peer-multiple value chart"},
];
let MOUNTS = FULL_MOUNTS;
const MODULE_FILES = {table: "./table.js", charts: "./charts.js", panels: "./panels.js", scorecard: "./scorecard.js"};
/** Revision 4 (5.2): the slots each view shows. The Scorecard view mounts four, the Table view
 * six (its scope line is the shell's own row). */
export const VIEW_SLOTS = {
  scorecard: ["scorecard", "compare", "detail", "method"],
  table: ["scope", "table", "charts", "detail", "peers", "method"],
};
export function slotsFor(view) { return (VIEW_SLOTS[view] || VIEW_SLOTS.scorecard).slice(); }
/** Commands that act on the Table view: run from the Scorecard view, they open it first. */
const TABLE_COMMANDS = new Set(["metric.open", "columns.find", "peer.add", "export.csv", "export.tsv", "filters.reset",
  "layout.reset", "outliers.toggle", "cf.next", "density.next", "text.bigger", "text.smaller", "peers.save",
  "peers.restore", "peers.addAdjacent", "layout.save", "peers.edit", "primary.reset", "basis.next", "basis.prev",
  "currency.next", "earnings.toggle"]);

// ---------------------------------------------------------------------------------------------
// Streamlit protocol shim (UI report 1.3; the covnav and prodcards pattern)
// ---------------------------------------------------------------------------------------------

function post(type, extra) {
  try {
    window.parent.postMessage(Object.assign({isStreamlitMessage: true, type}, extra || {}), "*");
  } catch (e) { /* no parent: nothing to tell */ }
}
export const Streamlit = {
  componentReady() { post("streamlit:componentReady", {apiVersion: 1}); },
  setFrameHeight(height) { post("streamlit:setFrameHeight", {height}); },
  setComponentValue(value) { post("streamlit:setComponentValue", {value, dataType: "json"}); },
};

// ---------------------------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------------------------

/** Breakpoint of 1.3 from the frame's own innerWidth. */
export function layoutFor(width) {
  if (width >= BREAK.ultrawide) return "ultrawide";
  if (width >= BREAK.wide) return "wide";
  if (width >= BREAK.laptop) return "laptop";
  return "narrow";
}

/** Height mode of 1.3 with its hysteresis: short under 720 px or past 120 px of scroll; tall
 * again only at 720 px or more and under 40 px of scroll. */
export function heightModeFor(current, frameH, scrollTop) {
  if (frameH < core.SHORT_FRAME_PX || scrollTop > core.COLLAPSE_AT_PX) return "short";
  if (scrollTop < core.EXPAND_BELOW_PX) return "tall";
  return current || "tall";
}

/** Frame height of 1.2: viewport less the frame's resting top less 12, floored at 560. */
export function frameHeightFor(parentInnerH, frameTop, fallback) {
  const h = Number.isFinite(parentInnerH) && Number.isFinite(frameTop) ? parentInnerH - frameTop - FRAME_GAP : fallback;
  return Math.max(MIN_FRAME_H, Math.round(Number.isFinite(h) ? h : FALLBACK_H));
}

function stripStop(s) { return String(s == null ? "" : s).trim().replace(/\.+$/, ""); }
function errText(e) { return stripStop(e && e.message ? e.message : String(e)); }
function lcfirst(s) {
  if (!s) return s;
  if (/^[A-Z0-9&]{2,}(\b|\/)/.test(s) || /^[A-Z]\//.test(s)) return s;
  return s.charAt(0).toLowerCase() + s.slice(1);
}
function signed(n) { return n > 0 ? `+${n}` : n < 0 ? `\u2212${Math.abs(n)}` : "0"; }
function sigOf(...parts) {
  try { return JSON.stringify(parts, (k, v) => (k === "record" || k === "analysis" || k === "detail" ? undefined : v)); }
  catch (e) { return String(Math.random()); }
}
let UID = 0;
function uid(prefix) { UID += 1; return `${prefix}-${UID}`; }
function cssEsc(s) {
  const C = globalThis.CSS;
  return C && typeof C.escape === "function" ? C.escape(s) : String(s).replace(/["\\]/g, "\\$&");
}

// ---------------------------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------------------------

function append(el, kids) {
  for (const k of kids) {
    if (k === null || k === undefined || k === false) continue;
    if (Array.isArray(k)) append(el, k);
    else if (typeof k === "string" || typeof k === "number") el.appendChild(document.createTextNode(String(k)));
    else el.appendChild(k);
  }
}
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const k of Object.keys(attrs)) {
      const v = attrs[k];
      if (v === null || v === undefined || v === false) continue;
      if (k === "text") el.textContent = String(v);
      else if (k === "class") el.className = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k === "hidden" || k === "disabled") el[k] = !!v;
      else if (k === "value") el.value = String(v);
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, String(v));
    }
  }
  append(el, kids);
  return el;
}
/**
 * requestAnimationFrame with a timer behind it: a hidden tab or pane pauses animation frames,
 * and the view must still render, size its frame and move focus there.
 */
const frames = new Map();
let frameSeq = 0;
function nextFrame(fn) {
  const id = ++frameSeq;
  const run = () => {
    const f = frames.get(id);
    if (!f) return;
    frames.delete(id);
    cancelAnimationFrame(f.raf);
    clearTimeout(f.timer);
    fn();
  };
  frames.set(id, {raf: requestAnimationFrame(run), timer: setTimeout(run, 80)});
  return id;
}
function cancelFrame(id) {
  const f = frames.get(id);
  if (!f) return;
  frames.delete(id);
  cancelAnimationFrame(f.raf);
  clearTimeout(f.timer);
}
const SVGNS = "http://www.w3.org/2000/svg";
function svgIcon(kind) {
  const svg = document.createElementNS(SVGNS, "svg");
  svg.setAttribute("width", "14"); svg.setAttribute("height", "14"); svg.setAttribute("viewBox", "0 0 14 14");
  svg.setAttribute("aria-hidden", "true"); svg.setAttribute("focusable", "false");
  svg.setAttribute("class", "sh-icon");
  const path = document.createElementNS(SVGNS, "path");
  path.setAttribute("d", kind === "reload"
    ? "M11.5 7a4.5 4.5 0 1 1-1.4-3.26M11.5 1.8v2.4H9.1"
    : "M7 1.8v7M4.2 6.4 7 9.2l2.8-2.8M2.5 12.2h9");
  path.setAttribute("fill", "none"); path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "1.4"); path.setAttribute("stroke-linecap", "square");
  svg.appendChild(path);
  return svg;
}
function isVisible(el) { return !!(el && el.isConnected && (el.offsetWidth || el.offsetHeight || el.getClientRects().length)); }
const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
function focusables(root) { return Array.from(root.querySelectorAll(FOCUSABLE)).filter(isVisible); }
function focusEl(el) {
  if (!el || !el.isConnected) return false;
  try { el.focus({preventScroll: true}); } catch (e) { try { el.focus(); } catch (e2) { return false; } }
  return document.activeElement === el;
}
function isTextTarget(t) {
  if (!t || t.nodeType !== 1) return false;
  if (t.isContentEditable) return true;
  const tag = t.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (t.getAttribute("type") || "text").toLowerCase();
    return !["button", "checkbox", "radio", "submit", "reset", "range", "color", "file", "image"].includes(type);
  }
  return false;
}
/** A remembered element, or the one a re-render put in its place (same data-key or id):
 * focus returns to the control the analyst left, also when its bar was rebuilt meanwhile. */
function twinOf(el) {
  if (!el) return null;
  if (isVisible(el)) return el;
  const key = el.getAttribute ? el.getAttribute("data-key") : null;
  if (key) {
    const n = document.querySelector(`[data-key="${cssEsc(key)}"]`);
    if (n && isVisible(n)) return n;
  }
  if (el.id) {
    const n = document.getElementById(el.id);
    if (n && isVisible(n)) return n;
  }
  return null;
}
/** Rebuild an element's children, keeping focus on the element with the same data-key. */
function rebuild(el, build) {
  const ae = document.activeElement;
  let key = null;
  if (ae && ae !== document.body && el.contains(ae)) key = ae.getAttribute("data-key");
  el.textContent = "";
  build();
  if (key) {
    const n = el.querySelector(`[data-key="${cssEsc(key)}"]`);
    if (n && isVisible(n)) focusEl(n);
  }
}

// ---------------------------------------------------------------------------------------------
// Tokens, the shared stylesheet and fonts
// ---------------------------------------------------------------------------------------------

let tokensSig = "";
/** Set every token as a custom property on the document element (9.1). */
export function installTokens(tokens) {
  const tk = tokens && typeof tokens === "object" ? tokens : {};
  const s = JSON.stringify(tk);
  if (s === tokensSig) return;
  tokensSig = s;
  const root = document.documentElement;
  root.setAttribute("data-tokens", "1");   // shell.css keeps #app hidden until the palette is in
  for (const k of Object.keys(tk)) {
    const v = tk[k];
    if (typeof v === "string" || typeof v === "number") root.style.setProperty(`--${k}`, String(v));
  }
}
let sharedCssText = null;
/** Write research.css (the shared_css arg) into its <style> ahead of the linked sheets (9.8). */
export function installSharedCss(text) {
  if (typeof text !== "string" || text === sharedCssText) return;
  sharedCssText = text;
  let el = document.getElementById("research-css");
  if (!el) {
    el = document.createElement("style");
    el.id = "research-css";
    const first = document.head.querySelector('link[rel="stylesheet"]');
    document.head.insertBefore(el, first);
  }
  el.textContent = text;
}
let fontsCopied = false;
/** Copy the parent's @font-face rules (the fonts are inlined there by theme.css()). */
export function copyFontFaces() {
  if (fontsCopied) return;
  fontsCopied = true;
  try {
    if (window.parent === window) return;
    let faces = "";
    const sheets = window.parent.document.styleSheets;
    for (let i = 0; i < sheets.length; i++) {
      let rules;
      try { rules = sheets[i].cssRules; } catch (e) { continue; }   // an opaque sheet
      if (!rules) continue;
      for (let j = 0; j < rules.length; j++) {
        if (rules[j].type === 5 /* CSSRule.FONT_FACE_RULE */) faces += rules[j].cssText + "\n";
      }
    }
    if (faces) {
      let el = document.getElementById("font-faces");
      if (!el) { el = document.createElement("style"); el.id = "font-faces"; document.head.prepend(el); }
      el.textContent = faces;
    }
  } catch (e) { /* no parent access: the font stacks fall back to system faces */ }
}

// ---------------------------------------------------------------------------------------------
// Storage wrapper (0.1.7, 3.15): try/catch everywhere; the view works without storage
// ---------------------------------------------------------------------------------------------

const store = {
  ok: (() => {
    try {
      const k = core.STORAGE_KEY + ".probe";
      window.localStorage.setItem(k, "1");
      window.localStorage.removeItem(k);
      return true;
    } catch (e) { return false; }
  })(),
  readLocal(tickers) {
    try {
      const raw = window.localStorage.getItem(core.STORAGE_KEY);
      if (!raw) return null;
      return core.migrateState(JSON.parse(raw), tickers && tickers.length ? tickers : null);
    } catch (e) { return null; }
  },
  readSession() {
    try {
      const raw = window.sessionStorage.getItem(core.SESSION_KEY);
      const v = raw ? JSON.parse(raw) : null;
      return v && typeof v === "object" ? v : null;
    } catch (e) { return null; }
  },
  write(local, session) {
    try { window.localStorage.setItem(core.STORAGE_KEY, JSON.stringify(local)); } catch (e) { /* quota or blocked */ }
    try { window.sessionStorage.setItem(core.SESSION_KEY, JSON.stringify(session)); } catch (e) { /* blocked */ }
  },
};

// ---------------------------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------------------------

let args = null;               // last render args
let chart = {svg: "", digest: ""};   // revision 4: the company map Python drew
let mode = "full";             // "full" (Comps) or "bridge" (Forecast tab, 12.5)
let builtMode = null;          // the mode the skeleton was built for
let payload = null;
let lastDigest;
let lastArgsFocal;
let openEngine = "";
let state = null;
let view = null;
let viewDirty = true;
let viewVersion = 0;
let sessionRaw = null;
let scrollRestored = false;

let layout = layoutFor((HAS_DOM && window.innerWidth) || 1440);
let heightMode = "tall";
let arranged = null;
const ctxSteps = new Set();
let keyActive = false;

const mods = {table: null, charts: null, panels: null, scorecard: null};
const modErr = {};
let modsDone = false;
const modsReady = (HAS_DOM ? Promise.all(Object.keys(MODULE_FILES).map((k) =>
  import(MODULE_FILES[k]).then((m) => { mods[k] = m; }, (e) => { modErr[k] = e; console.error(`compsval ${k}.js`, e); })))
  : Promise.resolve()).then(() => { modsDone = true; });
let waitingForMods = false;

const mounted = {};            // mount id -> {api, root, failed, missing, failedAt}

// DOM
let app = null, ctxEl, scopeRow, mainEl, frameStateEl, analysisEl, footEl;
let bridgeLineEl = null, bridgeBodyEl = null, bridgeCloseEl = null;
let layer, tipEl, toastEl, liveEl, descHost;
const slots = {};
const sigs = {};
let scopeParts = null;

let rafId = 0, rendering = false, rerender = false;
const pending = {detailFocus: false, methodFocus: false, overlayFocus: null, restore: []};
let detailReturn = null, methodReturn = null, overlayReturn = null;

// ---------------------------------------------------------------------------------------------
// State, dispatch and the view
// ---------------------------------------------------------------------------------------------

function dispatch(action) {
  if (!state || !action || !action.type) return;
  const a = action.now === undefined ? {...action, now: Date.now()} : action;
  const prev = state;
  let next;
  try { next = core.reduce(state, a, payload); } catch (e) {
    console.error("compsval reduce", e);
    announce(`That action failed: ${errText(e)}.`);
    return;
  }
  if (!next || next === prev) return;
  state = next;
  viewDirty = true;
  viewVersion += 1;
  onStateChange(prev, next);
  persistSoon();
  scheduleRender();
}

function getView() {
  if (!payload || !state) return null;
  if (viewDirty || !view) {
    try { view = core.deriveView(payload, state, {mode}); } catch (e) {
      console.error("compsval deriveView", e);
      view = {schema: core.SCHEMA, error: core.stateMsg("calc_failed_section", {section: "The comparison", message: errText(e)}),
        focal: null, ctx: null, header: null, primary: null, scope: null, table: null,
        dotplot: null, bridge: null, peers: null, method: null, detail: null,
        states: [], lineage: null, undo: null, sectionErrors: {}, mode, footer: null, bridgeLine: null};
    }
    viewDirty = false;
  }
  return view;
}

function onStateChange(prev, next) {
  const pu = prev.ui || {}, nu = next.ui || {};
  if (nu.undo && nu.undo !== pu.undo) showToast(`${stripStop(nu.undo.label)}.`, {undo: true});
  else if (!nu.undo && pu.undo && toastKind === "undo") hideToast();
  if (!pu.detail && nu.detail) {
    if (!detailReturn) detailReturn = activeOutside(slots.detail);
    pending.detailFocus = true;
  }
  if (pu.detail && !nu.detail) { pending.restore.push({box: slots.detail, el: detailReturn}); detailReturn = null; }
  if (!pu.method && nu.method) {
    if (!methodReturn) methodReturn = activeOutside(slots.method);
    pending.methodFocus = true;
  }
  if (pu.method && !nu.method) { pending.restore.push({box: slots.method, el: methodReturn}); methodReturn = null; }
  if (pu.overlay && !nu.overlay && overlayReturn) { pending.restore.push({box: null, el: overlayReturn}); overlayReturn = null; }
  if (prev.singleKeys !== next.singleKeys) sigs.ctx = null;
}
function activeOutside(box) {
  const ae = document.activeElement;
  if (!ae || ae === document.body || (box && box.contains(ae))) return null;
  return ae;
}

let persistTimer = 0;
function persistSoon() {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(persistNow, 200);
}
let lastWrote = null;
function persistNow() {
  clearTimeout(persistTimer);
  if (!state) return;
  if (mode === "bridge") {
    // Never the whole state: a bridge left open must not put back a peer set that Comps has
    // since changed (12.5).
    try {
      const merged = core.mergeBridge(window.localStorage.getItem(core.STORAGE_KEY), state.focal, (state.bridge || {})[state.focal]);
      lastWrote = JSON.stringify(merged);
      window.localStorage.setItem(core.STORAGE_KEY, lastWrote);
    } catch (e) { /* storage is a convenience */ }
    return;
  }
  try {
    const p = core.persistable(state);
    let table = null;
    const t = api("table");
    if (t && typeof t.getViewport === "function") {
      try { const vp = t.getViewport(); if (vp) table = {scrollTop: Math.round(vp.scrollTop || 0), scrollLeft: Math.round(vp.scrollLeft || 0)}; } catch (e) { table = null; }
    }
    lastWrote = JSON.stringify(p.local);
    store.write(p.local, {...p.session, scroll: {main: mainEl ? Math.round(mainEl.scrollTop) : 0}, table});
  } catch (e) { /* storage is a convenience */ }
}

function initState(a) {
  const companies = Array.isArray(payload.companies) ? payload.companies : [];
  const tickers = companies.map((c) => c.ticker);
  const local = store.readLocal(tickers);
  sessionRaw = store.readSession();
  try {
    state = core.defaultState(payload, {focal: a.focal, engine: a.engine, live: a.live !== false}, local, sessionRaw);
  } catch (e) {
    console.error("compsval defaultState", e);
    state = core.defaultState(payload, {focal: a.focal, engine: a.engine, live: a.live !== false}, null, null);
  }
  viewDirty = true;
}

function focalRecord() {
  return payload && Array.isArray(payload.companies) ? payload.companies.find((c) => c.ticker === (state && state.focal)) : null;
}
function engineLabels() {
  const u = payload && payload.universe;
  return {pharma: "Big pharma", biotech: "Biotech", cellgene: "Cell and gene", ...((u && u.engine_labels) || {})};
}

// ---------------------------------------------------------------------------------------------
// The render message
// ---------------------------------------------------------------------------------------------

function onRenderArgs(a) {
  args = a || {};
  installTokens(args.tokens);
  installSharedCss(args.shared_css);
  copyFontFaces();
  bindParentResize();
  mode = args.mode === "bridge" ? "bridge" : "full";
  MOUNTS = mode === "bridge" ? BRIDGE_MOUNTS : FULL_MOUNTS;
  if (!app || builtMode !== mode) buildSkeleton();
  if (mode === "full" && typeof args.chart_svg === "string") {
    const d = args.chart_digest == null ? String(args.chart_svg.length) : String(args.chart_digest);
    if (d !== chart.digest) chart = {svg: args.chart_svg, digest: d};
  }
  if (!modsDone) {
    renderLoading();
    if (!waitingForMods) {
      waitingForMods = true;
      modsReady.then(() => { waitingForMods = false; onRenderArgs(args); });
    }
    nextFrame(fitFrame);
    return;
  }
  const digest = args.digest == null ? null : String(args.digest);
  if (!payload || digest !== lastDigest || (digest === null && args.payload !== payload)) {
    payload = args.payload && typeof args.payload === "object" ? args.payload : {};
    lastDigest = digest;
    viewDirty = true;
    viewVersion += 1;
    if (!state) { initState(args); lastArgsFocal = args.focal; }
  }
  if (state) {
    // A new focal from Python (the top bar's company) applies; a re-sent render with the same
    // focal never undoes a focal change made here that Python has not applied yet (7.5).
    if (args.focal && args.focal !== lastArgsFocal) {
      lastArgsFocal = args.focal;
      if (args.focal !== state.focal) dispatch({type: "SET_FOCAL", ticker: args.focal});
    }
    const rec = focalRecord();
    openEngine = args.engine || (rec && rec.engine) || state.engine || "";
    const live = args.live !== false;
    if (state.live !== live) { state = {...state, live}; viewDirty = true; viewVersion += 1; }
  }
  scheduleRender();
  nextFrame(fitFrame);
}

if (HAS_DOM) {
  window.addEventListener("message", (e) => {
    const d = e.data;
    if (!d || d.type !== "streamlit:render") return;
    if (e.source && e.source !== window.parent && e.source !== window) return;
    onRenderArgs(d.args || {});
  });
}

// ---------------------------------------------------------------------------------------------
// Frame sizing (1.2)
// ---------------------------------------------------------------------------------------------

let lastFrameH = 0;
/** Fit the frame to the visible viewport; the frame scrolls inside itself. */
export function fitFrame() {
  if (mode === "bridge") { fitBridge(); return; }
  if (!window.innerWidth) return;                         // a hidden tab: wait for a resize
  const fallback = Number(args && args.height) || FALLBACK_H;
  let hgt = fallback;
  try {
    const fe = window.frameElement;
    if (fe && window.parent && window.parent !== window) {
      const rect = fe.getBoundingClientRect();
      if (!rect.width) return;                             // not laid out yet
      const main = window.parent.document.querySelector('[data-testid="stMain"]');
      hgt = frameHeightFor(window.parent.innerHeight, rect.top + (main ? main.scrollTop : 0), fallback);
    } else {
      hgt = frameHeightFor(NaN, NaN, fallback);
    }
  } catch (e) { hgt = frameHeightFor(NaN, NaN, fallback); }
  if (Math.abs(hgt - lastFrameH) < 2) return;
  lastFrameH = hgt;
  Streamlit.setFrameHeight(hgt);
}
let parentResize = null;
function bindParentResize() {
  if (parentResize) return;
  try {
    const pw = window.parent;
    if (!pw || pw === window) return;
    parentResize = () => nextFrame(fitFrame);
    pw.addEventListener("resize", parentResize);
    window.addEventListener("pagehide", () => {
      try { pw.removeEventListener("resize", parentResize); } catch (e) { /* gone */ }
      persistNow();
    }, {once: true});
  } catch (e) { parentResize = () => {}; }
}

// --band-h and --main-h (1.2), published on #app and written only when they change.
let lastBandH = -1, lastMainH = -1;
function measureBand() {
  if (!app || !mainEl) return;
  const bandH = Math.max(0, Math.round(mainEl.getBoundingClientRect().top - app.getBoundingClientRect().top));
  const mainH = Math.round(mainEl.clientHeight);
  if (bandH !== lastBandH) { lastBandH = bandH; app.style.setProperty("--band-h", `${bandH}px`); }
  if (mainH !== lastMainH) { lastMainH = mainH; app.style.setProperty("--main-h", `${mainH}px`); }
}

function updateHeightMode() {
  if (!app) return;
  // Narrow runs the banner and the KPI strip as short mode (1.6).
  const next = layout === "narrow" ? "short" : heightModeFor(heightMode, window.innerHeight, mainEl ? mainEl.scrollTop : 0);
  if (next === heightMode) return;
  heightMode = next;
  app.setAttribute("data-height", heightMode);
  fitCtx();
  fitScope();
  measureBand();
  positionAnchored();
}

// ---------------------------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------------------------

function buildSkeleton() {
  app = document.getElementById("app");
  if (!app) { app = h("div", {id: "app"}); document.body.appendChild(app); }
  // A rebuild for the other mode starts clean: the mounts of the old skeleton go with it.
  for (const id of Object.keys(mounted)) {
    const r = mounted[id];
    if (r && r.api && typeof r.api.destroy === "function") { try { r.api.destroy(); } catch (e) { /* ignore */ } }
    delete mounted[id];
  }
  for (const k of Object.keys(sigs)) delete sigs[k];
  for (const k of Object.keys(slots)) delete slots[k];
  app.textContent = "";
  builtMode = mode;
  app.setAttribute("data-mode", mode);
  document.documentElement.setAttribute("data-mode", mode);
  app.setAttribute("data-layout", layout);
  app.setAttribute("data-height", heightMode);

  layer = h("div", {class: "sh-layer"});
  tipEl = h("div", {class: "u-tip sh-tip", role: "tooltip", id: "sh-tip", hidden: true});
  toastEl = h("div", {class: "u-toast sh-toast", role: "status", hidden: true});
  liveEl = h("div", {class: "u-live", "aria-live": "polite", role: "status"});
  descHost = h("div", {class: "sh-descs", hidden: true});
  layer.append(tipEl, toastEl, liveEl, descHost);
  frameStateEl = h("div", {class: "sh-frame-state", hidden: true});

  if (mode === "bridge") {
    // 12.5: one context line, the inputs and the chart, one closing line. Nothing else.
    bridgeLineEl = h("p", {class: "sh-bridge-line"});
    slots.bridgeInputs = h("div", {class: "sh-slot sh-bridge-inputs"});
    slots.bridgeChart = h("div", {class: "sh-slot sh-bridge-chart"});
    bridgeBodyEl = h("div", {class: "sh-bridge-body"}, slots.bridgeInputs, slots.bridgeChart);
    bridgeCloseEl = h("p", {class: "sh-bridge-close"});
    app.append(bridgeLineEl, frameStateEl, bridgeBodyEl, bridgeCloseEl, layer);
    wireTips();
    wireBridge();
    return;
  }

  ctxEl = h("div", {class: "sh-ctx", role: "group", "aria-label": "Company, peer set and basis"});
  scopeRow = h("div", {class: "sh-scope-row"});
  mainEl = h("main", {id: "main", class: "sh-main", "aria-label": "Comparable companies"});

  // #main (revision 4): the Scorecard view's chart and ranked table with Compare laid over them,
  // or the Table view's folded chart strip, the table and the one-line footer.
  analysisEl = h("div", {class: "sh-stack"});
  slots.scorecard = h("section", {class: "sh-slot sh-scorecard", id: "sh-sec-scorecard", tabindex: "-1", role: "region", "aria-label": "Company scorecard"});
  slots.compare = h("div", {class: "sh-slot sh-compare"});
  slots.charts = h("div", {class: "sh-slot sh-charts", id: "sh-sec-charts", tabindex: "-1", role: "region", "aria-label": "Peer position"});
  slots.table = h("div", {class: "sh-slot sh-table", id: "sh-sec-table", tabindex: "-1"});
  footEl = h("div", {class: "sh-foot"});
  analysisEl.append(slots.scorecard, slots.compare, slots.charts, slots.table, footEl);
  mainEl.append(frameStateEl, analysisEl);

  // Right-side surfaces, one open at a time: the company panel, the peer drawer, methodology.
  slots.detail = h("aside", {class: "sh-slot sh-detail", "aria-label": "Company details", hidden: true});
  slots.peers = h("div", {class: "sh-slot sh-peers", hidden: true});
  slots.method = h("div", {class: "sh-slot sh-method", hidden: true});

  app.append(ctxEl, scopeRow, mainEl, slots.detail, slots.peers, slots.method, layer);

  wireTips();
  wireGlobal();
}

// ---------------------------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------------------------

function scheduleRender() {
  if (rendering) { rerender = true; return; }
  if (!rafId) rafId = nextFrame(render);
}
/** Render now: used when a command must act on the updated DOM (focus a cell after SHOW_COLUMN). */
function flush() {
  if (rafId) { cancelFrame(rafId); rafId = 0; }
  render();
}

function applyAppAttrs() {
  app.setAttribute("data-layout", layout);
  app.setAttribute("data-height", heightMode);
  if (state) {
    const ts = core.TEXT_SIZES.includes(state.textSize) ? state.textSize : 13;
    app.setAttribute("data-density", state.density || "default");
    app.setAttribute("data-text-size", String(ts));
    app.style.setProperty("--ts", String(ts / 13));
    app.toggleAttribute("data-detail", !!(state.ui && state.ui.detail));
    app.toggleAttribute("data-peers", !!(state.ui && state.ui.peers));
    app.setAttribute("data-view", currentView());
    app.toggleAttribute("data-compare", !!(state.ui && state.ui.compareOpen));
    app.setAttribute("data-single-keys", state.singleKeys === false ? "off" : "on");
  }
}

function render() {
  rafId = 0;
  if (rendering) { rerender = true; return; }
  rendering = true;
  try {
    if (!app || builtMode !== mode) buildSkeleton();
    applyAppAttrs();
    if (mode === "bridge") { renderBridge(); return; }
    if (!payload || !state || !modsDone) { renderLoading(); return; }
    const v = getView();
    const err = v ? v.error : null;
    // Revision 4: the scope line is the Table view's.
    scopeRow.hidden = !!err || currentView() !== "table";
    renderCtx(v);
    if (!err && currentView() === "table") renderScope(v);
    renderMain(v);
    renderSelector(v);
    renderPalette(v);
    renderHelp(v);
    postRender();
  } catch (e) {
    console.error("compsval shell", e);
    showFatal(e);
  } finally {
    rendering = false;
    if (rerender) { rerender = false; scheduleRender(); }
  }
}

function postRender() {
  fitCtx();
  fitScope();
  measureBand();
  updateHeightMode();
  positionAnchored();
  if (tipState.anchor && !tipState.anchor.isConnected) hideTip();
  gcDescs();
  if (!scrollRestored && sessionRaw && sessionRaw.scroll && Number.isFinite(sessionRaw.scroll.main)) {
    scrollRestored = true;
    mainEl.scrollTop = sessionRaw.scroll.main;
  } else scrollRestored = true;
  if (pending.detailFocus && state.ui.detail && !slots.detail.hidden) {
    pending.detailFocus = false;
    nextFrame(() => { if (!slots.detail.contains(document.activeElement)) focusFirstIn(slots.detail); });
  }
  if (pending.methodFocus && state.ui.method && !slots.method.hidden) {
    pending.methodFocus = false;
    nextFrame(() => { if (!slots.method.contains(document.activeElement)) focusFirstIn(slots.method); });
  }
  if (pending.restore.length) {
    const list = pending.restore.splice(0);
    nextFrame(() => {
      for (const r of list) {
        const ae = document.activeElement;
        const lost = !ae || ae === document.body || !isVisible(ae) || (r.box && r.box.contains(ae) && r.box.hidden);
        const back = lost ? twinOf(r.el) : null;
        if (back) { focusEl(back); break; }
      }
    });
  }
  nextFrame(fitFrame);
}

function focusFirstIn(root) {
  const pref = root.querySelector("[data-autofocus]") || root.querySelector("h1[tabindex], h2[tabindex], h3[tabindex]");
  if (pref && focusEl(pref)) return;
  const f = focusables(root)[0];
  if (f && focusEl(f)) return;
  root.setAttribute("tabindex", "-1");
  focusEl(root);
}

function showFatal(e) {
  try {
    frameStateEl.hidden = false;
    if (analysisEl) analysisEl.hidden = true;
    if (bridgeBodyEl && mode === "bridge") bridgeBodyEl.hidden = true;
    frameStateEl.textContent = "";
    frameStateEl.append(stateBlock(core.stateMsg("calc_failed_section", {section: "The view", message: errText(e)})));
  } catch (e2) { /* nothing more to do */ }
}

// ----- loading (section 8: before the first render message, and while modules load) -----

function renderLoading() {
  if (!app) return;
  if (mode === "bridge") { renderBridge(); return; }
  const T = (args && args.focal) || "";
  const msg = core.stateMsg("loading", {T: T || "the focal company"});
  if (sigs.loading !== T) {
    sigs.loading = T;
    sigs.ctx = null;
    ctxEl.textContent = "";
    ctxEl.append(h("div", {class: "sh-ctx-id"},
      T ? h("span", {class: "sh-company is-static"}, h("span", {class: "u-ticker", text: T})) : null),
    h("div", {class: "sh-ctx-ctl"}));
  }
  scopeRow.hidden = true;
  analysisEl.hidden = true;
  frameStateEl.hidden = false;
  frameStateEl.setAttribute("aria-busy", "true");
  frameStateEl.textContent = "";
  const skel = h("div", {class: "sh-skel", "aria-hidden": "true"});
  for (let i = 0; i < 10; i++) skel.append(h("span", {class: "u-skeleton"}));
  frameStateEl.append(stateBlock(msg), skel);
}

// ---------------------------------------------------------------------------------------------
// Tooltips (7.5): one shared element, delegated hover and focus
// ---------------------------------------------------------------------------------------------

const tipState = {anchor: null, byFocus: false, hover: null, showTimer: 0, hideTimer: 0, pressed: null, pressedKey: null};
function tipContent(c) {
  const v = typeof c === "function" ? c() : c;
  if (!v) return null;
  if (typeof v === "string") return {body: v};
  return v;
}
function tipText(c) {
  const v = tipContent(c);
  if (!v) return "";
  return [v.title, v.body].concat(v.lines || []).filter(Boolean).join(" ");
}
/** Register a tooltip on an element of the shell: hover and focus behaviour, plus an
 * aria-describedby to a hidden copy in `host` (or the shared host). */
function tip(el, content, host) {
  if (!el) return el;
  if (!host) { describe(el, content); return el; }   // shared host, collected once the anchor goes
  el.__shTip = content;
  const text = tipText(content);
  if (text) {
    const id = uid("sh-d");
    host.appendChild(h("span", {id, text}));
    const prev = el.getAttribute("aria-describedby");
    el.setAttribute("aria-describedby", prev ? `${prev} ${id}` : id);
  }
  return el;
}
function showTip(anchor, content, byFocus = false) {
  const c = tipContent(content);
  if (!anchor || !c || !(c.title || c.body || (c.lines && c.lines.length))) return;
  clearTimeout(tipState.showTimer);
  clearTimeout(tipState.hideTimer);
  tipEl.textContent = "";
  if (c.title) tipEl.append(h("p", {class: "u-tip-title", text: c.title}));
  if (c.body) tipEl.append(h("p", {class: "u-tip-body", text: c.body}));
  if (c.lines && c.lines.length) tipEl.append(h("ul", {class: "u-tip-lines"}, c.lines.filter(Boolean).map((l) => h("li", {text: l}))));
  tipEl.hidden = false;
  tipState.anchor = anchor;
  tipState.byFocus = byFocus;
  placeNear(tipEl, anchor, {gap: 6});
}
function hideTip() {
  clearTimeout(tipState.showTimer);
  clearTimeout(tipState.hideTimer);
  if (tipEl) tipEl.hidden = true;
  tipState.anchor = null;
  tipState.byFocus = false;
}
function scheduleHideTip() {
  clearTimeout(tipState.hideTimer);
  tipState.hideTimer = setTimeout(hideTip, TIP_DELAY);
}
function tipAnchorOf(t) {
  let n = t;
  while (n && n !== document.documentElement) {
    if (n.__shTip) return n;
    n = n.parentElement || (n.parentNode && n.parentNode.host) || null;
  }
  return null;
}
/** Place a fixed element below its anchor (above when there is no room), inside the frame. */
function placeNear(el, anchor, opts = {}) {
  const gap = opts.gap ?? 4;
  const r = anchor.getBoundingClientRect();
  const W = window.innerWidth, H = window.innerHeight;
  const w = el.offsetWidth, hh = el.offsetHeight;
  let top = r.bottom + gap;
  if (top + hh > H - 8 && r.top - gap - hh >= 8) top = r.top - gap - hh;
  let left = opts.alignRight ? r.right - w : r.left;
  left = Math.min(left, W - w - 8);
  el.style.top = `${Math.round(Math.max(8, top))}px`;
  el.style.left = `${Math.round(Math.max(8, left))}px`;
}
function describe(anchor, content) {
  if (!anchor) return;
  if (content !== undefined) anchor.__shTip = content;
  const text = tipText(anchor.__shTip);
  let span = anchor.__shDesc;
  if (!span || !span.isConnected) {
    if (!text) return;
    span = h("span", {id: uid("sh-d")});
    span.__anchor = anchor;
    descHost.appendChild(span);
    anchor.__shDesc = span;
  }
  span.textContent = text;
  const ids = (anchor.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
  if (!ids.includes(span.id)) anchor.setAttribute("aria-describedby", ids.concat([span.id]).join(" "));
}
function gcDescs() {
  if (!descHost) return;
  for (const s of Array.from(descHost.children)) if (s.__anchor && !s.__anchor.isConnected) s.remove();
}

// ---------------------------------------------------------------------------------------------
// Shared menu (11.1: items {id, label, shortcut, disabled, reason, checked, onSelect})
// ---------------------------------------------------------------------------------------------

let menuState = null;
function openMenu(anchor, items, opts = {}) {
  closeMenu(false);
  hideTip();
  if (!anchor || !Array.isArray(items)) return;
  const label = opts.label || (anchor.getAttribute && (anchor.getAttribute("aria-label") || (anchor.textContent || "").trim())) || "Menu";
  const el = h("div", {class: "u-menu sh-menu", role: "menu", "aria-label": label.replace(/\s*▾$/, "")});
  const buttons = [];
  for (const it of items) {
    if (!it) continue;
    if (it.kind === "sep") { el.append(h("div", {class: "u-menu-sep", role: "separator"})); continue; }
    if (it.kind === "head") { el.append(h("div", {class: "u-menu-head", role: "presentation", text: it.label})); continue; }
    if (it.kind === "note") { el.append(h("div", {class: "u-menu-note", role: "presentation", text: it.label})); continue; }
    const hasCheck = typeof it.checked === "boolean";
    const key = it.shortcut ? core.keyLabel(it.shortcut, IS_MAC) : "";
    const b = h("button", {type: "button", class: "u-menu-item", role: hasCheck ? "menuitemradio" : "menuitem", tabindex: "-1",
      "aria-disabled": it.disabled ? "true" : null, "aria-checked": hasCheck ? String(!!it.checked) : null},
    h("span", {class: "u-menu-check", "aria-hidden": "true", text: it.checked ? "✓" : ""}),
    h("span", {class: "u-menu-label", text: it.label}),
    key ? h("span", {class: "u-menu-key"}, h("kbd", {class: "u-kbd", text: key})) : null);
    if (it.disabled && it.reason) tip(b, it.reason);
    b.addEventListener("click", (e) => { e.preventDefault(); activateMenuItem(it); });
    b.addEventListener("mouseenter", () => focusEl(b));
    buttons.push(b);
    el.append(b);
  }
  layer.append(el);
  if (anchor.hasAttribute && anchor.hasAttribute("aria-haspopup")) anchor.setAttribute("aria-expanded", "true");
  menuState = {el, anchor, buttons, items: items.filter((i) => i && !i.kind)};
  el.addEventListener("keydown", menuKeys);
  placeNear(el, anchor, {gap: 2, alignRight: !!opts.alignRight});
  const start = buttons.findIndex((b) => b.getAttribute("aria-checked") === "true" && b.getAttribute("aria-disabled") !== "true");
  const first = start >= 0 ? start : buttons.findIndex((b) => b.getAttribute("aria-disabled") !== "true");
  focusEl(buttons[first >= 0 ? first : 0]);
}
function activateMenuItem(it) {
  if (!it || it.disabled) return;
  closeMenu(true);
  if (typeof it.onSelect === "function") {
    try { it.onSelect(); } catch (e) { console.error("compsval menu", e); announce(`That action failed: ${errText(e)}.`); }
  }
}
function closeMenu(restore) {
  if (!menuState) return;
  const {el, anchor} = menuState;
  menuState = null;
  el.remove();
  if (anchor && anchor.isConnected && anchor.hasAttribute && anchor.hasAttribute("aria-haspopup")) anchor.setAttribute("aria-expanded", "false");
  if (restore && anchor) focusEl(twinOf(anchor));
  hideTip();
}
function toggleMenu(anchor, itemsFn, opts) {
  if (menuState && menuState.anchor === anchor) { closeMenu(true); return; }
  openMenu(anchor, itemsFn(), opts);
}
function menuKeys(e) {
  if (!menuState) return;
  const {buttons, items} = menuState;
  const i = buttons.indexOf(document.activeElement);
  const move = (j) => { e.preventDefault(); focusEl(buttons[(j + buttons.length) % buttons.length]); };
  switch (e.key) {
    case "ArrowDown": move(i + 1); break;
    case "ArrowUp": move(i < 0 ? buttons.length - 1 : i - 1); break;
    case "Home": move(0); break;
    case "End": move(buttons.length - 1); break;
    case "Enter": case " ":
      e.preventDefault();
      if (i >= 0) activateMenuItem(items[i]);
      break;
    case "Escape": e.preventDefault(); closeMenu(true); break;
    case "Tab": e.preventDefault(); closeMenu(true); break;
    default:
      if (e.key && e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) {
        const ch = e.key.toLowerCase();
        for (let k = 1; k <= buttons.length; k++) {
          const j = (Math.max(i, 0) + k) % buttons.length;
          if ((items[j].label || "").toLowerCase().startsWith(ch)) { move(j); break; }
        }
        e.preventDefault();
      }
  }
  e.stopPropagation();
}

// ---------------------------------------------------------------------------------------------
// Toast (7.5) and live region
// ---------------------------------------------------------------------------------------------

let toastTimer = 0, toastKind = null;
function showToast(text, opts = {}) {
  if (!toastEl) return;
  clearTimeout(toastTimer);
  toastEl.textContent = "";
  toastEl.append(h("span", {class: "sh-toast-text", text}));
  if (opts.undo) {
    const b = h("button", {type: "button", class: "u-btn sh-toast-undo"}, "Undo",
      h("kbd", {class: "u-kbd", text: core.keyLabel("mod+z", IS_MAC)}));
    b.addEventListener("click", doUndo);
    toastEl.append(b);
  }
  toastKind = opts.undo ? "undo" : "info";
  toastEl.hidden = false;
  startToastTimer();
}
function startToastTimer() {
  clearTimeout(toastTimer);
  toastTimer = setTimeout(expireToast, core.UNDO_MS);
}
function expireToast() {
  const wasUndo = toastKind === "undo";
  hideToast();
  if (wasUndo && state && state.ui.undo) dispatch({type: "EXPIRE_UNDO", now: Date.now()});
}
function hideToast() {
  clearTimeout(toastTimer);
  if (toastEl) { toastEl.hidden = true; toastEl.textContent = ""; }
  toastKind = null;
}
function doUndo() {
  if (!state || !state.ui.undo) return;
  const label = stripStop(state.ui.undo.label);
  hideToast();
  dispatch({type: "UNDO"});
  announce(`Undone: ${lcfirst(label)}.`);
}

let liveTimer = 0;
function announce(text) {
  if (!liveEl || !text) return;
  clearTimeout(liveTimer);
  liveEl.textContent = "";
  liveTimer = setTimeout(() => { liveEl.textContent = String(text); }, 40);
}

// ---------------------------------------------------------------------------------------------
// Blocks
// ---------------------------------------------------------------------------------------------

function stateBlock(msg, extraClass = "") {
  if (!msg) return null;
  const tone = msg.severity === "red" ? " red" : msg.severity === "amber" ? " amber" : "";
  const kids = [h("p", {class: "u-state-title", text: msg.title || ""}), h("p", {class: "u-state-detail", text: msg.detail || ""})];
  if (msg.action && msg.action.command) {
    kids.push(h("button", {type: "button", class: "u-btn u-state-action", onclick: () => runCommand(msg.action.command)}, msg.action.label));
  }
  return h("div", {class: `u-state${tone}${extraClass ? " " + extraClass : ""}`, role: msg.severity === "red" ? "alert" : null}, kids);
}
function sectionFailBlock(sectionId, fallbackName) {
  const m = (view && view.sectionErrors && view.sectionErrors[sectionId]) ||
    core.stateMsg("calc_failed_section", {section: fallbackName, message: "no result"});
  return stateBlock(m, "sh-fail");
}
function chipEl(c, opts = {}) {
  const tone = c.tone && c.tone !== "neutral" ? ` ${c.tone}` : "";
  const el = h(opts.tag || "span", {class: `u-chip${tone}${opts.class ? " " + opts.class : ""}`,
    tabindex: opts.focusable ? "0" : null, "data-key": opts.key || null},
  h("span", {class: "u-chip-label", text: c.text}));
  return el;
}
function hintOf(id) {
  const c = core.COMMAND_BY_ID[id];
  const k = c && state ? core.commandHint(state, c, IS_MAC) : "";
  return k ? ` (${k})` : "";
}

// ---------------------------------------------------------------------------------------------
// Context bar (1.5)
// ---------------------------------------------------------------------------------------------

function renderCtx(v) {
  const H = v && v.header, C = v && v.ctx;
  const S = v && v.scorecard;
  const scoreView = currentView() === "scorecard";
  const sig = sigOf("ctx", H, C, state.basis, state.currency, state.earnings, state.activeSet,
    state.singleKeys, v && v.error, store.ok, (payload.companies || []).length, currentView(),
    S && [S.state, S.contextText, S.compareLabel, S.compareEnabled, S.compareTip], !!state.ui.compareOpen);
  if (sig === sigs.ctx) return;
  sigs.ctx = sig;
  sigs.loading = null;
  rebuild(ctxEl, () => {
    const descs = h("div", {class: "sh-descs", hidden: true});
    const idg = h("div", {class: "sh-ctx-id"});
    const ctl = h("div", {class: "sh-ctx-ctl"});
    ctxEl.append(idg, ctl, descs);
    const T = (H && H.ticker) || state.focal || "";

    // Company selector (never hidden).
    const name = (H && H.name) || (v && v.focal && v.focal.name) || T;
    const company = h("button", {type: "button", class: "sh-company", "data-key": "company", "aria-haspopup": "listbox",
      "aria-expanded": String(state.ui.overlay === "selector"), "aria-label": `Company ${T}, ${name}. Change company`},
    h("span", {class: "u-ticker", text: T}), h("span", {class: "sh-caret", "aria-hidden": "true", text: "▾"}));
    company.addEventListener("click", () => {
      if (state.ui.overlay === "selector") closeOverlay(true); else openOverlay("selector");
    });
    tip(company, () => ({title: name, body: H && ctxSteps.has(1) ? H.listingText : null,
      lines: [`Change company${hintOf("company.open")}`]}), descs);
    idg.append(company);

    if (!H) {
      if (!(v && v.error)) {
        const m = (v && v.sectionErrors && v.sectionErrors.header) ||
          core.stateMsg("calc_failed_section", {section: "Context bar", message: "no result"});
        const fc = h("span", {class: "u-chip sh-failchip", tabindex: "0", "data-key": "ctx-fail"},
          h("span", {class: "sh-warn-mark", "aria-hidden": "true", text: "✕"}), h("span", {class: "u-chip-label", text: m.title}));
        tip(fc, {title: m.title, body: m.detail}, descs);
        idg.append(fc);
      }
      ctl.append(helpButton(descs));
      return;
    }

    const nameEl = h("span", {class: "sh-name", text: H.name});
    tip(nameEl, H.name);
    idg.append(nameEl);
    // Revision 4 (1.4): the Scorecard view's bar is the company, its cohort and the actions on
    // the scorecard; listing, reporting and the valuation type chip belong to the Table view.
    for (const c of [H.subsectorChip, H.stageChip, scoreView ? null : H.typeChip]) {
      if (!c) continue;
      const el = chipEl(c, {class: `sh-idchip sh-chip-${c.id}`});
      if (c.tooltip) { el.append(h("span", {class: "u-sr", text: `. ${c.tooltip}`})); tip(el, {title: c.text, body: c.tooltip}); }
      idg.append(el);
    }
    if (!scoreView) {
      idg.append(h("span", {class: "sh-listing", text: H.listingText}));
      const rep = h("span", {class: "sh-reporting"},
        h("span", {class: "sh-full", text: H.reportingText}), h("span", {class: "sh-short", text: H.reportingShort}));
      if (H.reportingTooltip) tip(rep, {title: H.reportingText, body: H.reportingTooltip});
      idg.append(rep);
    }
    if (H.liveChip) {
      const lc = chipEl(H.liveChip, {class: "sh-live", focusable: true, key: "live"});
      tip(lc, {title: H.liveChip.text, body: H.liveChip.tooltip}, descs);
      idg.append(lc);
    }
    if (scoreView && S && S.state === "ok" && S.contextText) idg.append(h("span", {class: "sh-cohort", text: S.contextText}));

    // The view switch (1.4): Scorecard opens first; Table is the comparables table.
    const viewSeg = h("div", {class: "u-seg sh-view-seg", role: "group", "aria-label": "View"});
    for (const id of core.VIEWS) {
      const label = core.SCORECARD_COPY.views[id];
      const b = h("button", {type: "button", "data-key": `view-${id}`, "aria-pressed": String(currentView() === id), text: label});
      b.addEventListener("click", () => setView(id));
      tip(b, id === "table" ? "The comparable companies table, with its peer set, periods and basis." : "The cohort on one chart, with the ranked table beside it.", descs);
      viewSeg.append(b);
    }

    if (scoreView) {
      ctl.append(viewSeg);
      // Compare (4.2): enabled from two ticks; the open company is ticked when the view opens.
      const enabled = !!(S && S.state === "ok" && S.compareEnabled);
      const cmp = h("button", {type: "button", class: `u-btn sh-compare-btn${state.ui.compareOpen ? " is-set" : ""}`, "data-key": "compare",
        "aria-pressed": String(!!state.ui.compareOpen), "aria-disabled": enabled ? null : "true",
        text: S ? S.compareLabel : core.SCORECARD_COPY.compare.replace("{k}", "0")});
      cmp.addEventListener("click", () => {
        if (state.ui.compareOpen) { closeCompare(); return; }
        if (!enabled) { announce(`${core.SCORECARD_COPY.compareTip}.`); return; }
        openCompare();
      });
      tip(cmp, () => (enabled ? (state.ui.compareOpen ? "Close Compare" : "The ticked companies side by side") : core.SCORECARD_COPY.compareTip), descs);
      ctl.append(cmp);
    }

    // Peer set (never hidden; step 8 gives the short form).
    const ps = h("button", {type: "button", class: "u-btn sh-peerset", "data-key": "peerset", "aria-haspopup": "menu",
      "aria-expanded": "false", "aria-label": `Peer set: ${H.peerSet.full}. Change the peer set`},
    h("span", {class: "sh-peerset-k", text: "Peers:"}),
    h("span", {class: "sh-full", text: H.peerSet.full}), h("span", {class: "sh-short", text: H.peerSet.short}),
    h("span", {class: "sh-caret", "aria-hidden": "true", text: "▾"}));
    ps.addEventListener("click", () => toggleMenu(ps, peerSetItems, {label: "Peer set"}));
    tip(ps, {title: `Peers: ${H.peerSet.full}`, body: "The companies the statistics compare against. Saved sets live in this browser only."}, descs);
    if (!scoreView) ctl.append(ps);

    // Period: segmented, or "NTM ▾" at step 7.
    const seg = h("div", {class: "u-seg sh-period-seg", role: "group", "aria-label": "Period basis"});
    for (const b of core.BASES) {
      const btn = h("button", {type: "button", "data-key": `basis-${b}`, "aria-pressed": String(state.basis === b), text: b});
      btn.addEventListener("click", () => setBasis(b));
      tip(btn, {title: b, body: C && C.basisTooltips ? C.basisTooltips[b] : null}, descs);
      seg.append(btn);
    }
    if (!scoreView) ctl.append(seg);
    const pbtn = h("button", {type: "button", class: "u-btn sh-period-btn", "data-key": "basis-menu", "aria-haspopup": "menu",
      "aria-expanded": "false", "aria-label": `Period basis ${state.basis}. Change the period`},
    h("span", {text: state.basis}), h("span", {class: "sh-caret", "aria-hidden": "true", text: "▾"}));
    pbtn.addEventListener("click", () => toggleMenu(pbtn, () => core.BASES.map((b) => ({id: b, label: C && C.basisTooltips ? `${b}: ${C.basisTooltips[b]}` : b,
      checked: state.basis === b, onSelect: () => setBasis(b)})), {label: "Period basis"}));
    tip(pbtn, {title: `Period ${state.basis}`, body: C && C.basisTooltips ? C.basisTooltips[state.basis] : null,
      lines: [`Next period${hintOf("basis.next")}`]}, descs);
    if (!scoreView) ctl.append(pbtn);

    // Basis (12.6): currency, data state and earnings in one menu; the chip names what is not default.
    const B = H.basis || {text: "Basis", nonDefault: false, tooltip: C ? C.basisText : null};
    const basisBtn = h("button", {type: "button", class: `u-btn sh-basis${B.nonDefault ? " is-set" : ""}`, "data-key": "basis", "aria-haspopup": "menu",
      "aria-expanded": "false", "aria-label": `${B.text}. Change currency, data state or earnings basis`},
    h("span", {class: "sh-basis-text", text: B.text}), h("span", {class: "sh-caret", "aria-hidden": "true", text: "▾"}));
    basisBtn.addEventListener("click", () => toggleMenu(basisBtn, () => {
      const items = [{kind: "head", label: "Currency and data state"}];
      for (const [id, label] of CURRENCY_ITEMS) items.push({id, label, checked: state.currency === id, onSelect: () => setCurrency(id)});
      items.push({kind: "sep"}, {kind: "head", label: "Earnings"},
        {id: "reported", label: "GAAP/IFRS", checked: state.earnings !== "adjusted", onSelect: () => setEarnings("reported")},
        {id: "adjusted", label: "Ex amort. and IPR&D", checked: state.earnings === "adjusted", onSelect: () => setEarnings("adjusted")});
      if (B.nonDefault) items.push({kind: "sep"}, {id: "reset", label: "Reset to USD and GAAP/IFRS", onSelect: () => { setCurrency("USD"); setEarnings("reported"); }});
      return items;
    }, {label: "Basis"}));
    tip(basisBtn, {title: B.text, body: B.tooltip, lines: [`Next currency${hintOf("currency.next")}`, `Switch earnings${hintOf("earnings.toggle")}`]}, descs);
    if (!scoreView) ctl.append(basisBtn, viewSeg);

    // Data as of.
    const flag = H.dataAsOf.tone === "flag";
    const asof = h("button", {type: "button", class: `u-chip sh-asof${flag ? " flag" : ""}`, "data-key": "asof",
      "aria-label": `${H.dataAsOf.text}${flag ? ", with a data warning" : ""}`},
    flag ? h("span", {class: "sh-asof-mark", "aria-hidden": "true", text: "!"}) : null,
    h("span", {class: "sh-full", text: H.dataAsOf.text}), h("span", {class: "sh-short", text: H.dataAsOf.short}));
    const asofTip = {title: H.dataAsOf.text, lines: H.dataAsOf.lines};
    asof.addEventListener("click", () => {
      if (tipState.anchor === asof) hideTip(); else showTip(asof, asofTip, true);
    });
    tip(asof, asofTip, descs);
    ctl.append(asof);

    // Reload and export, or the "⋯" menu at step 6.
    const reload = h("button", {type: "button", class: "u-btn icon sh-reload", "data-key": "reload", "aria-label": "Reload the comps"}, svgIcon("reload"));
    reload.addEventListener("click", doReload);
    tip(reload, RELOAD_TIP, descs);
    const exp = h("button", {type: "button", class: "u-btn icon sh-export", "data-key": "export", "aria-label": "Export",
      "aria-haspopup": "menu", "aria-expanded": "false"}, svgIcon("export"));
    exp.addEventListener("click", () => toggleMenu(exp, exportItems, {label: "Export", alignRight: true}));
    tip(exp, "Export this view as CSV, or copy it as TSV.", descs);
    const more = h("button", {type: "button", class: "u-btn icon sh-more", "data-key": "more", "aria-label": "Reload and export",
      "aria-haspopup": "menu", "aria-expanded": "false", text: "⋯"});
    more.addEventListener("click", () => toggleMenu(more, () => [{id: "reload", label: "Reload the comps", onSelect: doReload}, {kind: "sep"}]
      .concat(exportItems()), {label: "Reload and export", alignRight: true}));
    if (scoreView) ctl.append(reload);
    else ctl.append(reload, exp, more);

    ctl.append(helpButton(descs));
  });
  updateKeyState();
}

function helpButton(descs) {
  const b = h("button", {type: "button", class: `u-btn icon sh-help-btn${keyActive ? " is-keys" : ""}`, "data-key": "help",
    "aria-label": keyActive ? KEYS_ON_TEXT : KEYS_OFF_TEXT, "aria-haspopup": "dialog"},
  h("span", {"aria-hidden": "true", text: "?"}), h("span", {class: "sh-keydot", "aria-hidden": "true"}));
  b.addEventListener("click", () => { if (state && state.ui.overlay === "help") closeOverlay(true); else openOverlay("help"); });
  tip(b, () => ({body: keyActive ? KEYS_ON_TEXT : KEYS_OFF_TEXT, lines: [`Shortcut help${hintOf("help.open")}`]}), descs);
  return b;
}

function updateKeyState() {
  let active = false;
  try { active = document.hasFocus(); } catch (e) { active = false; }
  keyActive = active;
  const b = ctxEl && ctxEl.querySelector('[data-key="help"]');
  if (b) {
    b.classList.toggle("is-keys", active);
    b.setAttribute("aria-label", active ? KEYS_ON_TEXT : KEYS_OFF_TEXT);
  }
}

function peerSetItems() {
  const info = core.peerSetTickers(payload, state);
  const saved = Object.keys(state.savedSets || {});
  const items = [{kind: "head", label: "Peer set"},
    {id: "system", label: `System set, ${info.def ? info.def.tickers.length : 0} peers`,
      checked: state.activeSet === "system" && !info.edited, onSelect: () => { dispatch({type: "RESTORE_SYSTEM"}); announce("System peers restored."); }}];
  for (const name of saved) {
    const s = state.savedSets[name];
    items.push({id: `saved:${name}`, label: `'${name}', ${s.tickers.length}`, checked: state.activeSet === `saved:${name}` && !info.edited,
      onSelect: () => { dispatch({type: "LOAD_SET", name}); announce(`Loaded peer set '${name}'.`); }});
  }
  if (info.edited) {
    items.push({id: "custom", label: `Custom (edited), ${info.tickers.length}`, checked: true, disabled: true,
      reason: "Your edits to the set. Save it to keep it under a name."});
  }
  items.push({kind: "sep"},
    {id: "save", label: "Save current set", onSelect: () => runCommand("peers.save")},
    {id: "edit", label: "Edit peers", onSelect: () => openPeers()},
    {kind: "note", label: store.ok ? SAVED_HERE : core.STATE_COPY.storage_unavailable.detail});
  return items;
}
function exportItems() {
  return [
    {id: "csv", label: "CSV of this view", shortcut: shortcutOf("export.csv"), onSelect: () => runCommand("export.csv")},
    {id: "tsv", label: "Copy as TSV", shortcut: shortcutOf("export.tsv"), onSelect: () => runCommand("export.tsv")},
  ];
}
function shortcutOf(id) {
  const c = core.COMMAND_BY_ID[id];
  if (!c || !c.key) return null;
  if (c.singleKey && state && state.singleKeys === false) return null;
  return c.key;
}

// Collapse steps (1.5): apply 1 to 8 while the bar overflows; reverse the most recent step when
// the bar has room for it plus 24 px. In narrow the steps run per row.
function applySteps() {
  for (const n of STEPS) ctxEl.classList.toggle(`sh-c${n}`, ctxSteps.has(n));
}
function ctxOver(row) {
  const cs = getComputedStyle(ctxEl);
  const avail = ctxEl.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
  const idg = ctxEl.querySelector(".sh-ctx-id"), ctl = ctxEl.querySelector(".sh-ctx-ctl");
  if (!idg || !ctl) return -Infinity;
  const wi = idg.getBoundingClientRect().width, wc = ctl.getBoundingClientRect().width;
  if (row === "id") return wi - avail;
  if (row === "ctl") return wc - avail;
  const gap = parseFloat(cs.columnGap) || 8;
  return wi + gap + wc - avail;
}
function fitCtx() {
  if (!ctxEl || !state || ctxEl.offsetParent === null) return;
  const rows = layout === "narrow" ? ["id", "ctl"] : ["all"];
  applySteps();
  for (const row of rows) {
    const steps = STEPS.filter((n) => row === "all" || STEP_ROW[n] === row);
    let guard = 0;
    while (ctxOver(row) > 0 && guard++ < 10) {
      const nxt = steps.find((n) => !ctxSteps.has(n));
      if (nxt === undefined) break;
      ctxSteps.add(nxt);
      applySteps();
    }
    guard = 0;
    while (guard++ < 10) {
      const applied = steps.filter((n) => ctxSteps.has(n));
      if (!applied.length) break;
      const last = applied[applied.length - 1];
      ctxSteps.delete(last);
      applySteps();
      if (ctxOver(row) + STEP_ROOM > 0) { ctxSteps.add(last); applySteps(); break; }
    }
  }
}

function setBasis(b) {
  if (state.basis === b) return;
  dispatch({type: "SET_BASIS", basis: b});
  announceAfter(() => `Period ${state.basis}.`);
}
function setCurrency(c) {
  if (state.currency === c) return;
  dispatch({type: "SET_CURRENCY", currency: c});
  announceAfter(() => `${getView() && getView().ctx ? getView().ctx.currencyLabel : c}.`);
}
function setEarnings(id) {
  if (state.earnings === id) return;
  dispatch({type: "SET_EARNINGS", earnings: id});
  announceAfter(() => `Earnings ${id === "adjusted" ? "ex amortisation and IPR&D" : "GAAP/IFRS"}.`);
}
/** Announce a change once the view has it. */
function announceAfter(fn) {
  announce(fn());
}

// ---------------------------------------------------------------------------------------------
// Scope line (1.5)
// ---------------------------------------------------------------------------------------------

function renderScope(v) {
  const S = v.scope;
  const sig = sigOf("scope", S, (state.filters || []).length, state.singleKeys, v.sectionErrors && v.sectionErrors.scope);
  if (sig === sigs.scope) return;
  sigs.scope = sig;
  rebuild(scopeRow, () => {
    const descs = h("div", {class: "sh-descs", hidden: true});
    const line = h("div", {class: "sh-scope", role: "group", "aria-label": "What shapes the statistics"});
    scopeRow.append(line, descs);
    scopeParts = null;
    if (!S) { line.append(sectionFailBlock("scope", "Scope line")); return; }
    // 1. Counts.
    const counts = h("button", {type: "button", class: "u-btn link sh-counts", "data-key": "scope-counts", text: S.counts.text});
    counts.addEventListener("click", () => openPeers());
    tip(counts, "Open peer selection.", descs);
    line.append(counts);
    const items = S.items || [];
    // 2. Exclusions.
    const collapsibles = [];
    const ex = items.filter((i) => i.kind === "exclusion");
    if (ex.length) {
      // One chip per ticker up to three; more than three, or a line too narrow, give one
      // chip with a menu.
      const chips = [];
      if (ex.length <= 3) {
        chips.push(h("span", {class: "sh-scope-label", text: "Excluded:"}));
        for (const i of ex) chips.push(removableChip(i, `Include ${i.text} in statistics again`, descs));
        line.append(...chips);
      }
      const b = h("button", {type: "button", class: "u-chip sh-scope-menu", "data-key": "scope-ex", "aria-haspopup": "menu", "aria-expanded": "false",
        text: `Excluded: ${ex.length} ▾`, hidden: ex.length <= 3});
      b.addEventListener("click", () => toggleMenu(b, () => ex.map((i) => ({id: i.id, label: `Include ${i.text} again`, onSelect: () => runScopeItem(i)})),
        {label: "Excluded peers"}));
      tip(b, {title: `Excluded: ${ex.map((i) => i.text).join(", ")}`, body: ex[0].tooltip}, descs);
      line.append(b);
      if (chips.length) collapsibles.push({els: chips, btn: b});
    }
    // 3. Filters.
    const fl = items.filter((i) => i.kind === "filter");
    if (fl.length) {
      const chips = [];
      if (fl.length <= 3) {
        for (const i of fl) chips.push(removableChip(i, `Remove the filter ${i.text}`, descs));
        line.append(...chips);
      }
      const b = h("button", {type: "button", class: "u-chip sh-scope-menu", "data-key": "scope-fl", "aria-haspopup": "menu", "aria-expanded": "false",
        text: `Filters: ${fl.length} ▾`, hidden: fl.length <= 3});
      b.addEventListener("click", () => toggleMenu(b, () => fl.map((i) => ({id: i.id, label: `Remove ${i.text}`, onSelect: () => runScopeItem(i)})),
        {label: "Filters"}));
      tip(b, {title: `Filters: ${fl.length}`, body: fl[0].tooltip}, descs);
      line.append(b);
      if (chips.length) collapsibles.push({els: chips, btn: b});
    }
    // 4 to 6: statistics group, outliers, warnings. These may move into the "+n" menu.
    const movEls = [];
    for (const i of items.filter((x) => x.kind === "group" || x.kind === "outliers" || x.kind === "warning")) {
      const el = i.removable ? removableChip(i, i.kind === "group" ? "Statistics over all peers" : "Include outliers in statistics", descs)
        : warningChip(i, descs);
      movEls.push({item: i, el});
      line.append(el);
    }
    const more = h("button", {type: "button", class: "u-chip sh-scope-more", "data-key": "scope-more", "aria-haspopup": "menu",
      "aria-expanded": "false", hidden: true});
    line.append(more);
    // 7. Fixed actions.
    const edit = h("button", {type: "button", class: "u-btn sh-scope-btn", "data-key": "scope-edit", text: "Edit peers"});
    edit.addEventListener("click", () => openPeers());
    const nf = (state.filters || []).length;
    const reset = h("button", {type: "button", class: "u-btn sh-scope-btn", "data-key": "scope-reset", "aria-disabled": nf ? null : "true",
      text: "Reset filters"});
    reset.addEventListener("click", () => { if ((state.filters || []).length) runCommand("filters.reset"); });
    tip(reset, nf ? `Clear every filter${hintOf("filters.reset")}. Undo stays available for five seconds.` : "No filter is set.", descs);
    line.append(h("div", {class: "sh-scope-fixed"}, edit, reset));
    scopeParts = {line, movEls, more, collapsibles};
  });
}
function removableChip(item, removeLabel, descs) {
  const x = h("button", {type: "button", class: "u-chip-x", "data-key": `x-${item.id}`, "aria-label": removeLabel, text: "✕"});
  x.addEventListener("click", () => runScopeItem(item));
  const chip = h("span", {class: `u-chip sh-scope-chip sh-scope-${item.kind}`}, h("span", {class: "u-chip-label", text: item.text}), x);
  tip(chip, {title: item.text, body: item.tooltip});
  tip(x, {title: item.text, body: item.tooltip}, descs);
  return chip;
}
function warningChip(item, descs) {
  const el = h("span", {class: "u-chip flag sh-scope-warn", tabindex: "0", "data-key": `w-${item.id}`},
    h("span", {class: "sh-warn-mark", "aria-hidden": "true", text: "!"}), h("span", {class: "u-chip-label", text: item.text}));
  tip(el, {title: item.text, body: item.tooltip}, descs);
  return el;
}
function runScopeItem(item) {
  if (!item || !item.action) return;
  dispatch(item.action);
  const said = item.kind === "exclusion" ? `${item.text} is back in the statistics.`
    : item.kind === "filter" ? `Removed the filter ${item.text}.`
      : item.kind === "group" ? "Statistics over all peers."
        : item.kind === "outliers" ? "Statistics include outliers." : "";
  if (said) announceAfter(() => said);
}
function fitScope() {
  if (!scopeParts || !scopeParts.line.isConnected || scopeRow.hidden) return;
  const {line, movEls, more, collapsibles} = scopeParts;
  for (const m of movEls) m.el.hidden = false;
  for (const c of collapsibles) { for (const el of c.els) el.hidden = false; c.btn.hidden = true; }
  more.hidden = true;
  const moved = [];
  for (let i = movEls.length - 1; i >= 0 && line.scrollWidth > line.clientWidth + 1; i--) {
    movEls[i].el.hidden = true;
    moved.unshift(movEls[i]);
    more.hidden = false;
    more.textContent = `+${moved.length} ▾`;
  }
  // Still too narrow: the filter chips, then the exclusion chips, fold into their menus.
  for (let i = collapsibles.length - 1; i >= 0 && line.scrollWidth > line.clientWidth + 1; i--) {
    for (const el of collapsibles[i].els) el.hidden = true;
    collapsibles[i].btn.hidden = false;
  }
  if (moved.length) {
    more.setAttribute("aria-label", `${moved.length} more ${moved.length === 1 ? "item" : "items"} that shape the statistics`);
    more.onclick = () => toggleMenu(more, () => moved.map((m) => (m.item.removable
      ? {id: m.item.id, label: `Remove: ${m.item.text}`, onSelect: () => runScopeItem(m.item)}
      : {id: m.item.id, label: m.item.text, onSelect: () => showTip(more, {title: m.item.text, body: m.item.tooltip}, true)})),
    {label: "More scope items"});
  }
}

// ---------------------------------------------------------------------------------------------
// #main: layout, slots and mounts
// ---------------------------------------------------------------------------------------------

function renderMain(v) {
  const err = v ? v.error : null;
  frameStateEl.removeAttribute("aria-busy");
  frameStateEl.hidden = !err;
  analysisEl.hidden = !!err;
  if (err) {
    const sig = sigOf("err", err);
    if (sigs.frameErr !== sig) {
      sigs.frameErr = sig;
      frameStateEl.textContent = "";
      frameStateEl.append(stateBlock(err));
    }
    return;
  }
  sigs.frameErr = null;
  sigs.loading = null;
  frameStateEl.textContent = "";
  const shown = new Set(slotsFor(currentView()));
  slots.detail.hidden = !state.ui.detail;
  slots.peers.hidden = !state.ui.peers || !shown.has("peers");
  slots.method.hidden = !state.ui.method;
  for (const id of ["scorecard", "compare", "charts", "table"]) slots[id].hidden = !shown.has(id);
  slots.compare.hidden = !shown.has("compare") || !(state.ui && state.ui.compareOpen);
  footEl.hidden = currentView() !== "table";
  if (!footEl.hidden) renderFooter(v);
  ensureMounts();
  updateMounts(v);
}

/** The open view of revision 4: "scorecard" (default) or "table"; the bridge has neither. */
function currentView() {
  const v = state && state.ui ? state.ui.view : null;
  return core.VIEWS.includes(v) ? v : "scorecard";
}
/** The mounts the open view shows (5.2). The bridge mounts its own two. */
function viewMounts() {
  if (mode === "bridge") return MOUNTS;
  const want = new Set(slotsFor(currentView()));
  return MOUNTS.filter((m) => want.has(m.slot));
}
function setView(value) {
  if (!state || !core.VIEWS.includes(value) || currentView() === value) return;
  dispatch({type: "SET_VIEW", value});
  announce(value === "table" ? "Table view: the comparable companies." : "Scorecard view: the cohort on one chart.");
}
/** Open the Table view at once, for a command that acts on the table or its charts. */
function ensureTableView() {
  if (mode === "bridge" || !state || currentView() === "table") return;
  dispatch({type: "SET_VIEW", value: "table"});
  flush();
}
/** Tick or untick a company for Compare; a fourth is refused and said so (8.1). */
function toggleCompare(ticker) {
  if (!state || !ticker) return false;
  const cur = (state.ui && state.ui.compare) || [];
  if (!cur.includes(ticker) && cur.length >= core.COMPARE_MAX) {
    const t = core.SCORECARD_COPY.compareFull;
    announce(t);
    showToast(t);
    return false;
  }
  dispatch({type: "TOGGLE_COMPARE", ticker});
  const now = (state.ui && state.ui.compare) || [];
  announce(`${ticker} ${now.includes(ticker) ? "ticked" : "unticked"} for Compare, ${now.length} of ${core.COMPARE_MAX}.`);
  return true;
}
function openCompare() {
  if (!state) return;
  if (((state.ui && state.ui.compare) || []).length < 2) { announce(core.SCORECARD_COPY.compareTip + "."); return; }
  dispatch({type: "OPEN_COMPARE"});
}
function closeCompare() {
  if (!state || !(state.ui && state.ui.compareOpen)) return;
  dispatch({type: "CLOSE_COMPARE"});
  flush();
}

/** The one-line footer (12.6): what the figures rest on, and the way into sources and method. */
function renderFooter(v) {
  const F = v && v.footer;
  const sig = sigOf("foot", F);
  if (sig === sigs.foot) return;
  sigs.foot = sig;
  rebuild(footEl, () => {
    if (!F) return;
    const flag = F.tone === "flag";
    footEl.classList.toggle("flag", flag);
    const b = h("button", {type: "button", class: "u-btn link sh-foot-btn", "data-key": "foot-sources", text: F.buttonLabel || "Sources and method"});
    b.addEventListener("click", () => openMethod(F.anchor || "sources"));
    footEl.append(flag ? h("span", {class: "u-marker amber", "aria-hidden": "true", text: "!"}) : null,
      h("span", {class: "sh-foot-text", text: F.text || ""}), b);
    tip(footEl.querySelector(".sh-foot-text"), F.text || "");
  });
}

// ---------------------------------------------------------------------------------------------
// Bridge-only mode (12.5): the Forecast tab's "Value implied by peer multiples"
// ---------------------------------------------------------------------------------------------

function renderBridge() {
  if (!app || !bridgeLineEl) return;
  if (!payload || !state || !modsDone) {
    bridgeBodyEl.hidden = true;
    bridgeLineEl.textContent = "";
    frameStateEl.hidden = false;
    frameStateEl.setAttribute("aria-busy", "true");
    if (sigs.bridgeLoading !== 1) {
      sigs.bridgeLoading = 1;
      frameStateEl.textContent = "";
      frameStateEl.append(stateBlock(core.stateMsg("loading", {T: (args && args.focal) || "the focal company"})));
    }
    fitBridge();
    return;
  }
  sigs.bridgeLoading = 0;
  frameStateEl.removeAttribute("aria-busy");
  const v = getView();
  const err = v ? v.error : null;
  frameStateEl.hidden = !err;
  bridgeBodyEl.hidden = !!err;
  if (err) {
    frameStateEl.textContent = "";
    frameStateEl.append(stateBlock(err));
    bridgeLineEl.textContent = "";
  } else {
    const L = v.bridgeLine || {};
    if (bridgeLineEl.textContent !== (L.text || "")) bridgeLineEl.textContent = L.text || "";
    const sig = sigOf("bclose", L.linkLabel, L.storageLine);
    if (sig !== sigs.bclose) {
      sigs.bclose = sig;
      bridgeCloseEl.textContent = "";
      const b = h("button", {type: "button", class: "u-btn sh-bridge-back", "data-key": "bridge-back", text: L.linkLabel || "Change peers or metric in Comps"});
      b.addEventListener("click", () => clickParentTab("Comps"));
      bridgeCloseEl.append(b, h("span", {class: "u-meta", text: L.storageLine || "Peer set and inputs are saved in this browser only."}));
    }
    ensureMounts();
    updateMounts(v);
  }
  nextFrame(fitBridge);
}

let lastBridgeH = 0;
/** The bridge is a block in the Forecast tab's flow: the frame is as tall as its content. */
function fitBridge() {
  if (!app || !window.innerWidth) return;
  const hgt = Math.max(200, Math.ceil(app.getBoundingClientRect().height) + 4);
  if (Math.abs(hgt - lastBridgeH) < 2) return;
  lastBridgeH = hgt;
  Streamlit.setFrameHeight(hgt);
}
let bridgeWired = false;
function wireBridge() {
  if (typeof ResizeObserver === "function") { const ro = new ResizeObserver(() => fitBridge()); ro.observe(app); }
  if (bridgeWired) return;
  bridgeWired = true;
  document.addEventListener("keydown", onKeyDown);
  window.addEventListener("pagehide", persistNow);
  window.addEventListener("resize", () => { if (mode === "bridge") nextFrame(() => { scheduleRender(); fitBridge(); }); });
  wireStorageSync();
}
/** Both frames share one storage key (12.5): adopt what the other frame stored. */
let storageWired = false;
function wireStorageSync() {
  if (storageWired) return;
  storageWired = true;
  const adopt = () => {
    if (!state || !payload) return;
    let local = null, session = null;
    try {
      const raw = window.localStorage.getItem(core.STORAGE_KEY);
      if (raw && raw !== lastWrote) local = JSON.parse(raw);
    } catch (e) { local = null; }
    try { session = store.readSession(); } catch (e) { session = null; }
    if (local || session) dispatch({type: "ADOPT_PERSISTED", local, session});
  };
  window.addEventListener("storage", (e) => {
    if (e.key !== core.STORAGE_KEY && e.key !== core.SESSION_KEY) return;
    if (e.key === core.STORAGE_KEY && e.newValue === lastWrote) return;
    adopt();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) adopt(); });
}

function api(id) {
  const r = mounted[id];
  return r && !r.failed ? r.api : null;
}
function ensureMounts() {
  // A view's mounts leave with it (revision 4), so a hidden table never lays itself out at
  // zero width; the slot is emptied and the mount rebuilt when its view opens again.
  if (mode === "full") {
    const keep = new Set(viewMounts().map((m) => m.id));
    for (const m of MOUNTS) {
      if (keep.has(m.id) || !mounted[m.id]) continue;
      const r = mounted[m.id];
      if (r.api && typeof r.api.destroy === "function") { try { r.api.destroy(); } catch (e) { /* ignore */ } }
      delete mounted[m.id];
      if (slots[m.slot]) { slots[m.slot].textContent = ""; slots[m.slot].classList.remove("sh-slot-failed"); }
    }
  }
  for (const m of viewMounts()) {
    const r = mounted[m.id];
    if (r && !r.failed) continue;
    if (r && r.missing) continue;                         // a missing module will not appear before a reload
    if (r && r.failed && r.failedAt === viewVersion) continue;   // retry only after the view changes
    mountOne(m);
  }
}
function mountOne(m) {
  const slot = slots[m.slot];
  if (!slot) return;
  const prev = mounted[m.id];
  if (prev && prev.api && typeof prev.api.destroy === "function") { try { prev.api.destroy(); } catch (e) { /* ignore */ } }
  slot.textContent = "";
  const mod = mods[m.mod];
  const fn = mod ? mod[m.fn] : null;
  if (typeof fn !== "function") {
    const why = !mod ? `${m.mod}.js did not load` : `${m.mod}.js has no ${m.fn} export`;
    failSlot(m, why, true);
    return;
  }
  const root = h("div", {class: `sh-mount sh-mount-${m.id}`});
  slot.classList.remove("sh-slot-failed");
  slot.append(root);
  try {
    const a = fn(root, ctx);
    mounted[m.id] = {api: a || {}, root, failed: false};
  } catch (e) {
    console.error(`compsval ${m.fn}`, e);
    failSlot(m, errText(e) || `${m.fn} threw`, false);
  }
}
function failSlot(m, message, missing) {
  const slot = slots[m.slot];
  slot.textContent = "";
  slot.classList.add("sh-slot-failed");
  const msg = core.stateMsg("calc_failed_section", {section: m.section, message: stripStop(message)});
  slot.append(stateBlock(msg, "sh-fail"));
  mounted[m.id] = {api: null, root: null, failed: true, missing: !!missing, failedAt: viewVersion};
}
function updateMounts(v) {
  for (const m of viewMounts()) {
    const r = mounted[m.id];
    if (!r || r.failed || !r.api || typeof r.api.update !== "function") continue;
    try { r.api.update(v); } catch (e) {
      console.error(`compsval ${m.id}.update`, e);
      try { if (typeof r.api.destroy === "function") r.api.destroy(); } catch (e2) { /* ignore */ }
      failSlot(m, errText(e) || "its update threw", false);
    }
  }
}

// ---------------------------------------------------------------------------------------------
// Navigation helpers: sections, columns, charts, detail and methodology
// ---------------------------------------------------------------------------------------------

function revealInMain(el, pad = 8) {
  if (!el || !mainEl) return;
  const mr = mainEl.getBoundingClientRect(), r = el.getBoundingClientRect();
  if (r.top < mr.top || r.top > mr.bottom - 60) { mainEl.scrollTop += r.top - mr.top - pad; updateHeightMode(); }
}
function scrollToSection(id, focus = true) {
  if (id === "peers") { openPeers(); return; }
  if (id === "notes" || id === "sources") { openMethod("sources"); return; }
  if (SECTIONS[id]) ensureTableView();
  const meta = SECTIONS[id];
  const sec = meta ? slots[meta.slot] : null;
  if (!sec || !mainEl) return;
  const mr = mainEl.getBoundingClientRect(), r = sec.getBoundingClientRect();
  mainEl.scrollTop += r.top - mr.top - 8;
  updateHeightMode();
  if (focus) focusEl(sec);
  announce(`Showing ${meta.label}.`);
}
function tableFocus(ticker, colId) {
  const t = api("table");
  if (t && typeof t.focusCell === "function") {
    try { t.focusCell(ticker, colId); return true; } catch (e) { console.error("compsval focusCell", e); }
  }
  dispatch({type: "FOCUS_CELL", row: ticker, col: colId});
  return false;
}
function goToColumn(colId, ticker, said) {
  ensureTableView();
  const v = getView();
  if (!v || !colId) return;
  const T = ticker || state.focal;
  const col = core.COLUMN_BY_ID[colId];
  const label = col ? lcfirst(col.label) : colId;
  const inTable = !!(v.table && (v.table.columns || []).some((c) => c.id === colId));
  if (!inTable) dispatch({type: "SHOW_COLUMN", colId});
  flush();
  revealInMain(slots.table);
  const t = api("table");
  if (t && typeof t.scrollToColumn === "function") { try { t.scrollToColumn(colId); } catch (e) { /* the focus still lands */ } }
  tableFocus(T, colId);
  announce(inTable ? (said || `Showing ${label}.`) : `Added ${label} to a custom column set.`);
}
function revealCharts() {
  ensureTableView();
  // The strip is the chart area at every width (12.1).
  const l = layout === "narrow" ? "narrow" : layout;
  dispatch({type: "SET_CHART_STRIP", layout: l, value: "open"});
  flush();
  revealInMain(slots.charts);
}
function openPeers(opts = {}) {
  if (mode === "bridge" || !state) return;
  ensureTableView();
  dispatch({type: "OPEN_PEERS", search: !!opts.search});
}
function closePeers() {
  if (!state || !state.ui.peers) return;
  dispatch({type: "CLOSE_PEERS"});
}
function openDetail(ticker) {
  if (!ticker) return;
  if (!state.ui.detail) detailReturn = activeOutside(slots.detail);
  dispatch({type: "OPEN_DETAIL", ticker});
}
function closeDetail() {
  if (!state.ui.detail) return;
  const ret = detailReturn;
  const T = state.ui.detail;
  dispatch({type: "CLOSE_DETAIL"});
  // Focus goes back before the panel leaves the page, and without scrolling: a panel that
  // found focus on the body would fetch it back itself and scroll its target into view,
  // and the table must keep its place when the panel closes (11.2).
  focusEl(twinOf(ret));
  flush();
  pending.restore = pending.restore.filter((r) => r.box !== slots.detail);
  const ae = document.activeElement;
  if (!ae || ae === document.body || !isVisible(ae)) {
    const back = twinOf(ret);
    if (back) focusEl(back);
    else if (state.ui.focus && state.ui.focus.row) tableFocus(state.ui.focus.row, state.ui.focus.col);
    else if (T) tableFocus(T, "ticker");
  }
  detailReturn = null;
}
function openMethod(anchor) {
  if (!state.ui.method) methodReturn = activeOutside(slots.method);
  dispatch({type: "OPEN_METHOD", anchor: anchor || null});
  if (state.ui.method) pending.methodFocus = true;
}
function closeMethod() {
  if (!state.ui.method) return;
  const ret = methodReturn;
  dispatch({type: "CLOSE_METHOD"});
  focusEl(twinOf(ret));                                   // before the drawer leaves, as in closeDetail
  flush();
  pending.restore = pending.restore.filter((r) => r.box !== slots.method);
  const ae = document.activeElement;
  if (!ae || ae === document.body || !isVisible(ae)) focusEl(twinOf(ret));
  methodReturn = null;
}

// ---------------------------------------------------------------------------------------------
// Overlays: selector, palette, help (state.ui.overlay)
// ---------------------------------------------------------------------------------------------

let paletteInit = null;
function openOverlay(kind, init) {
  if (!state) return;
  closeMenu(false);
  hideTip();
  if (state.ui.overlay === kind) return;
  if (!state.ui.overlay) {
    const ae = document.activeElement;
    overlayReturn = ae && ae !== document.body && !(layer && layer.contains(ae)) ? ae : null;
  }
  if (kind === "palette") paletteInit = init || {query: "", mode: null};
  pending.overlayFocus = kind;
  dispatch({type: "OPEN_OVERLAY", overlay: kind});
  // Open now, not on the next frame: whatever is typed straight after the shortcut lands in
  // the overlay's input ("C, then type to filter", 7.2).
  flush();
}
function closeOverlay(restore = true) {
  if (!state || !state.ui.overlay) return;
  const ret = overlayReturn;
  overlayReturn = null;
  dispatch({type: "CLOSE_OVERLAY"});
  flush();
  pending.restore = pending.restore.filter((r) => r.el !== ret);
  const back = restore ? twinOf(ret) : null;
  if (back) focusEl(back);
}
function modalOpen() {
  const o = state && state.ui.overlay;
  return o === "palette" || o === "help" || o === "selector";
}
function trapTab(e, root) {
  if (e.key !== "Tab") return;
  const f = focusables(root);
  if (!f.length) { e.preventDefault(); return; }
  const i = f.indexOf(document.activeElement);
  if (e.shiftKey && (i <= 0)) { e.preventDefault(); focusEl(f[f.length - 1]); }
  else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); focusEl(f[0]); }
}

// ----- company selector (1.5) -----

let selEl = null, selInput = null, selList = null, selQuery = "", selIdx = 0, selOpts = [];
function renderSelector(v) {
  const open = state.ui.overlay === "selector";
  const cb = ctxEl.querySelector('[data-key="company"]');
  if (cb) cb.setAttribute("aria-expanded", String(open));
  if (!open) {
    if (selEl) { selEl.remove(); selEl = null; }
    return;
  }
  if (!selEl) buildSelector();
  positionSelector();
  if (pending.overlayFocus === "selector") { pending.overlayFocus = null; focusEl(selInput); }
}
function buildSelector() {
  selQuery = "";
  const n = (payload.companies || []).length;
  selEl = h("div", {class: "sh-sel", role: "dialog", "aria-label": "Change the focal company"});
  selInput = h("input", {class: "u-input sh-sel-input", type: "text", role: "combobox", "aria-expanded": "true",
    "aria-controls": "sh-sel-list", "aria-autocomplete": "list", "aria-label": "Search companies",
    placeholder: `Search ${n} companies by ticker or name`, autocomplete: "off", spellcheck: "false"});
  selList = h("div", {class: "sh-sel-list", id: "sh-sel-list", role: "listbox", "aria-label": "Companies"});
  selEl.append(selInput, selList, h("p", {class: "sh-sel-foot", text: "Enter makes the company focal. Esc closes."}));
  layer.append(selEl);
  selInput.addEventListener("input", () => { selQuery = selInput.value; selIdx = 0; fillSelector(); });
  selInput.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); e.stopPropagation();
      if (!selOpts.length) return;
      selIdx = (selIdx + (e.key === "ArrowDown" ? 1 : -1) + selOpts.length) % selOpts.length;
      markSelector();
    } else if (e.key === "PageDown" || e.key === "PageUp") {
      e.preventDefault(); e.stopPropagation();
      selIdx = Math.max(0, Math.min(selOpts.length - 1, selIdx + (e.key === "PageDown" ? 10 : -10)));
      markSelector();
    } else if (e.key === "Enter") {
      e.preventDefault(); e.stopPropagation();
      if (selOpts[selIdx]) pickCompany(selOpts[selIdx].ticker);
    } else if (e.key === "Escape") {
      e.preventDefault(); e.stopPropagation();
      closeOverlay(true);
    } else if (e.key === "Tab") {
      closeOverlay(false);
    }
  });
  fillSelector();
  const cur = selOpts.findIndex((o) => o.ticker === state.focal);
  selIdx = cur >= 0 ? cur : 0;
  markSelector();
}
function fillSelector() {
  const labels = engineLabels();
  const q = selQuery.trim().toLowerCase();
  const all = (payload.companies || []).map((c) => {
    let rank = 0;
    if (q) {
      const t = String(c.ticker || "").toLowerCase(), n = String(c.name || "").toLowerCase();
      if (t.startsWith(q)) rank = 1;
      else if (t.includes(q)) rank = 2;
      else if (n.startsWith(q) || n.includes(` ${q}`)) rank = 3;
      else if (n.includes(q)) rank = 4;
      else return null;
    }
    return {c, rank};
  }).filter(Boolean);
  const sortFn = (a, b) => (a.rank - b.rank) || String(a.c.ticker).localeCompare(String(b.c.ticker));
  const inEng = all.filter((x) => x.c.engine === openEngine).sort(sortFn);
  const other = all.filter((x) => x.c.engine !== openEngine).sort(sortFn);
  selList.textContent = "";
  selOpts = [];
  const group = (title, list) => {
    if (!list.length) return;
    const hid = uid("sh-selg");
    const g = h("div", {role: "group", "aria-labelledby": hid, class: "sh-sel-group"}, h("div", {class: "sh-sel-head", id: hid, role: "presentation", text: title}));
    for (const {c} of list) {
      const clinical = c.stage === "clinical";
      const opt = h("div", {role: "option", class: "sh-sel-opt", id: `sh-sel-o-${c.ticker}`, "aria-selected": "false",
        "data-ticker": c.ticker, "aria-current": c.ticker === state.focal ? "true" : null},
      h("span", {class: "sh-sel-check", "aria-hidden": "true", text: c.ticker === state.focal ? "✓" : ""}),
      h("span", {class: "u-ticker sh-sel-ticker", text: c.ticker}),
      h("span", {class: "sh-sel-name", text: c.name || ""}),
      h("span", {class: `u-chip${clinical ? " clinical" : ""} sh-sel-stage`, text: clinical ? "Clinical" : "Commercial"}));
      opt.addEventListener("mousedown", (e) => e.preventDefault());
      opt.addEventListener("click", () => pickCompany(c.ticker));
      selOpts.push({ticker: c.ticker, el: opt});
      g.append(opt);
    }
    selList.append(g);
  };
  group(`In ${labels[openEngine] || openEngine || "this subsector"}`, inEng);
  group(openEngine ? "Other subsectors" : "All companies", other);
  if (!selOpts.length) selList.append(h("p", {class: "sh-sel-empty", text: `No company matches “${selQuery.trim()}”.`}));
  markSelector();
}
function markSelector() {
  selOpts.forEach((o, i) => {
    const on = i === selIdx;
    o.el.setAttribute("aria-selected", String(on));
    o.el.classList.toggle("is-active", on);
  });
  const a = selOpts[selIdx];
  if (a) {
    selInput.setAttribute("aria-activedescendant", a.el.id);
    const lr = selList.getBoundingClientRect(), r = a.el.getBoundingClientRect();
    if (r.top < lr.top) selList.scrollTop += r.top - lr.top - 24;
    else if (r.bottom > lr.bottom) selList.scrollTop += r.bottom - lr.bottom;
  } else selInput.removeAttribute("aria-activedescendant");
}
function positionSelector() {
  if (!selEl) return;
  const b = ctxEl.querySelector('[data-key="company"]');
  const W = window.innerWidth;
  selEl.style.width = `${Math.min(420, W - 32)}px`;
  if (b && isVisible(b)) placeNear(selEl, b, {gap: 4}); else { selEl.style.top = "8px"; selEl.style.left = "16px"; }
  const top = parseFloat(selEl.style.top) || 0;
  selList.style.maxHeight = `${Math.max(160, Math.min(420, window.innerHeight - top - 90))}px`;
}
function pickCompany(ticker) {
  closeOverlay(true);
  setFocal(ticker);
}
function setFocal(ticker) {
  if (!ticker || !state) return;
  if (ticker === state.focal) { announce(`${ticker} is already the focal company.`); return; }
  dispatch({type: "SET_FOCAL", ticker});
  if (state.focal !== ticker) { announce(`${ticker} is not in the universe.`); return; }
  send({action: "focus", ticker});
  announceAfter(() => `Focal company ${ticker}.`);
}

// ----- command palette (7.3) -----

let palEl = null, palScrim = null, palInput = null, palList = null, palFoot = null, palIdx = 0, palItems = [], palMode = null;
function openPalette(query = "", mode = null) {
  if (state.ui.overlay === "palette") {
    if (!query && !mode && !palMode) { focusEl(palInput); return; }
    palMode = mode;
    if (palInput) { palInput.value = query; configurePalette(); fillPalette(); focusEl(palInput); }
    return;
  }
  openOverlay("palette", {query, mode});
}
function renderPalette(v) {
  const open = state.ui.overlay === "palette";
  if (!open) {
    if (palEl) { palEl.remove(); palScrim.remove(); palEl = null; palScrim = null; }
    return;
  }
  if (!palEl) buildPalette();
  if (pending.overlayFocus === "palette") { pending.overlayFocus = null; focusEl(palInput); }
}
function buildPalette() {
  const init = paletteInit || {query: "", mode: null};
  paletteInit = null;
  palMode = init.mode || null;
  palScrim = h("div", {class: "sh-scrim"});
  palScrim.addEventListener("mousedown", (e) => { e.preventDefault(); closeOverlay(true); });
  palEl = h("div", {class: "sh-pal", role: "dialog", "aria-modal": "true", "aria-label": "Command palette"});
  palInput = h("input", {class: "u-input sh-pal-input", type: "text", role: "combobox", "aria-expanded": "true",
    "aria-controls": "sh-pal-list", "aria-autocomplete": "list", autocomplete: "off", spellcheck: "false", value: init.query || ""});
  palList = h("ul", {class: "sh-pal-list", id: "sh-pal-list", role: "listbox", "aria-label": "Commands"});
  palFoot = h("p", {class: "sh-pal-foot"});
  palEl.append(palInput, palList, palFoot);
  layer.append(palScrim, palEl);
  palInput.addEventListener("input", () => { palIdx = 0; fillPalette(); });
  palInput.addEventListener("keydown", paletteKeys);
  palEl.addEventListener("keydown", (e) => trapTab(e, palEl));
  configurePalette();
  fillPalette();
}
function configurePalette() {
  if (palMode) {
    const what = palMode.kind === "layout" ? "layout" : "peer set";
    palInput.setAttribute("aria-label", `Name for this ${what}`);
    palInput.setAttribute("placeholder", `Name for this ${what}`);
    palInput.removeAttribute("aria-activedescendant");
    palList.hidden = true;
    palFoot.textContent = `Enter saves the ${what}. ${store.ok ? SAVED_HERE : core.STATE_COPY.storage_unavailable.detail}`;
  } else {
    palInput.setAttribute("aria-label", "Search commands, columns, companies and sections");
    palInput.setAttribute("placeholder", "Search commands, columns, companies and sections");
    palList.hidden = false;
    palFoot.textContent = `Up and down move, Enter runs, Esc closes.${state.singleKeys === false ? " Single-key shortcuts are off." : ""}`;
  }
}
function paletteEntries() {
  const base = core.COMMANDS.filter((c) => c.when !== "grid" && !["palette.open", "overlay.close", "singlekeys.toggle"].includes(c.id)
    && !(c.id === "undo" && !state.ui.undo));
  let extras = [];
  try { extras = core.paletteExtras(getView(), state).filter((x) => x.id !== "export:csv"); } catch (e) { extras = []; }
  return core.matchCommands(palInput.value || "", base, extras);
}
function fillPalette() {
  if (palMode) return;
  palItems = paletteEntries();
  palList.textContent = "";
  if (!palItems.length) {
    palList.append(h("li", {class: "sh-pal-empty", role: "presentation", text: "No command matches."}));
    palInput.removeAttribute("aria-activedescendant");
    return;
  }
  palIdx = Math.max(0, Math.min(palIdx, palItems.length - 1));
  const shown = palItems.slice(0, 300);
  shown.forEach((it, i) => {
    const hint = it.keys ? core.commandHint(state, it, IS_MAC) : "";
    const li = h("li", {role: "option", class: "sh-pal-item", id: `sh-pal-o-${i}`, "aria-selected": String(i === palIdx)},
      h("span", {class: "sh-pal-label", text: it.label}),
      h("span", {class: "sh-pal-group", text: it.group || ""}),
      hint ? h("kbd", {class: "u-kbd sh-pal-key", text: hint}) : h("span", {class: "sh-pal-key"}));
    li.addEventListener("mousedown", (e) => e.preventDefault());
    li.addEventListener("click", () => runPaletteEntry(it));
    li.addEventListener("mousemove", () => { if (palIdx !== i) { palIdx = i; markPalette(); } });
    palList.append(li);
  });
  markPalette();
}
function markPalette() {
  const items = palList.querySelectorAll(".sh-pal-item");
  items.forEach((li, i) => {
    li.setAttribute("aria-selected", String(i === palIdx));
    li.classList.toggle("is-active", i === palIdx);
  });
  const a = items[palIdx];
  if (a) {
    palInput.setAttribute("aria-activedescendant", a.id);
    const lr = palList.getBoundingClientRect(), r = a.getBoundingClientRect();
    if (r.top < lr.top) palList.scrollTop += r.top - lr.top;
    else if (r.bottom > lr.bottom) palList.scrollTop += r.bottom - lr.bottom;
  }
}
function paletteKeys(e) {
  if (palMode) {
    if (e.key === "Enter") {
      e.preventDefault(); e.stopPropagation();
      const name = palInput.value.trim();
      if (!name) { announce("Type a name first."); return; }
      const kind = palMode.kind;
      closeOverlay(true);
      if (kind === "layout") {
        const replaced = !!(state.layouts || {})[name];
        dispatch({type: "SAVE_LAYOUT", name});
        showToast(`${replaced ? "Replaced" : "Saved"} layout '${name}'. ${store.ok ? SAVED_HERE : core.STATE_COPY.storage_unavailable.detail}`);
      } else {
        const replaced = !!(state.savedSets || {})[name];
        dispatch({type: "SAVE_SET", name});
        showToast(`${replaced ? "Replaced" : "Saved"} peer set '${name}'. ${store.ok ? SAVED_HERE : core.STATE_COPY.storage_unavailable.detail}`);
      }
    } else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeOverlay(true); }
    return;
  }
  const n = palList.querySelectorAll(".sh-pal-item").length;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault(); e.stopPropagation();
    if (!n) return;
    palIdx = (palIdx + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
    markPalette();
  } else if (e.key === "PageDown" || e.key === "PageUp") {
    e.preventDefault(); e.stopPropagation();
    palIdx = Math.max(0, Math.min(n - 1, palIdx + (e.key === "PageDown" ? 12 : -12)));
    markPalette();
  } else if (e.key === "Enter") {
    e.preventDefault(); e.stopPropagation();
    if (palItems[palIdx]) runPaletteEntry(palItems[palIdx]);
  } else if (e.key === "Escape") {
    e.preventDefault(); e.stopPropagation();
    closeOverlay(true);
  }
}
function runPaletteEntry(it) {
  if (!it) return;
  if (it.keys) {
    if (it.id === "peers.save" || it.id === "layout.save") { openPalette("", {kind: it.id === "layout.save" ? "layout" : "set"}); return; }
    closeOverlay(true);
    runCommand(it.id);
    return;
  }
  closeOverlay(true);
  if (it.command === "focus") { setFocal(it.ticker); return; }
  if (it.command) { runCommand(it.command, it); return; }
  const a = it.action;
  if (it.target && it.target.kind === "section") { scrollToSection(it.target.id); return; }
  if (!a) return;
  switch (a.type) {
    case "SHOW_COLUMN": goToColumn(a.colId); return;
    case "OPEN_DETAIL": openDetail(a.ticker); return;
    case "SET_BASIS": setBasis(a.basis); return;
    case "SET_CURRENCY": setCurrency(a.currency); return;
    case "ADD_PEER": dispatch(a); announceAfter(() => `Added ${a.ticker} to the peers.`); return;
    case "REMOVE_PEER": dispatch(a); announceAfter(() => `Removed ${a.ticker} from the peers.`); return;
    case "LOAD_SET": dispatch(a); announceAfter(() => `Loaded peer set '${a.name}'.`); return;
    case "LOAD_LAYOUT": dispatch(a); announce(`Loaded layout '${a.name}'.`); return;
    case "SET_SINGLE_KEYS": dispatch(a); announce(`Single-key shortcuts ${a.on ? "on" : "off"}.`); return;
    default: dispatch(a); announce(`${it.label}: done.`);
  }
}

// ----- shortcut help (7.2) -----

let helpEl = null, helpScrim = null;
function renderHelp(v) {
  const open = state.ui.overlay === "help";
  if (!open) {
    if (helpEl) { helpEl.remove(); helpScrim.remove(); helpEl = null; helpScrim = null; sigs.help = null; }
    return;
  }
  if (!helpEl) {
    helpScrim = h("div", {class: "sh-scrim"});
    helpScrim.addEventListener("mousedown", (e) => { e.preventDefault(); closeOverlay(true); });
    helpEl = h("div", {class: "sh-help", role: "dialog", "aria-modal": "true", "aria-labelledby": "sh-help-title"});
    helpEl.addEventListener("keydown", (e) => trapTab(e, helpEl));
    layer.append(helpScrim, helpEl);
  }
  const sig = sigOf("help", state.singleKeys);
  if (sig !== sigs.help) {
    sigs.help = sig;
    rebuild(helpEl, buildHelp);
  }
  if (pending.overlayFocus === "help") {
    pending.overlayFocus = null;
    focusEl(helpEl.querySelector('[data-key="singlekeys"]'));
  }
}
function buildHelp() {
  const on = state.singleKeys !== false;
  helpEl.append(h("div", {class: "sh-help-head"},
    h("h2", {class: "u-section-title", id: "sh-help-title", text: "Keyboard shortcuts"}),
    h("button", {type: "button", class: "u-btn icon", "data-key": "help-close", "aria-label": "Close keyboard shortcuts", text: "✕",
      onclick: () => closeOverlay(true)})));
  const sw = h("button", {type: "button", role: "switch", class: "sh-switch", "data-key": "singlekeys", "aria-checked": String(on)},
    h("span", {class: "sh-switch-track", "aria-hidden": "true"}, h("span", {class: "sh-switch-thumb"})),
    h("span", {class: "sh-switch-label", text: "Single-key shortcuts"}),
    h("span", {class: "sh-switch-state", "aria-hidden": "true", text: on ? "On" : "Off"}));
  sw.addEventListener("click", () => {
    dispatch({type: "SET_SINGLE_KEYS", on: !(state.singleKeys !== false)});
    announce(`Single-key shortcuts ${state.singleKeys !== false ? "on" : "off"}.`);
  });
  const box = h("div", {class: "sh-help-toggle"}, sw, h("p", {class: "sh-help-note", text: SINGLE_KEY_NOTE}));
  if (!on) box.append(stateBlock(core.stateMsg("single_keys_off", {})));
  helpEl.append(box);
  helpEl.append(h("p", {class: "sh-help-note", text: "Keys work while the view has focus: click the view or tab into it first. Streamlit's own keys do not reach it then."}));
  const groups = [];
  for (const c of core.COMMANDS) {
    if (!c.keys || !c.keys.length) continue;
    let g = groups.find((x) => x.name === c.group);
    if (!g) { g = {name: c.group, cmds: []}; groups.push(g); }
    g.cmds.push(c);
  }
  const grid = h("div", {class: "sh-help-grid"});
  for (const g of groups) {
    const dl = h("dl", {class: "sh-help-list"});
    for (const c of g.cmds) {
      const off = c.singleKey && !on;
      dl.append(h("div", {class: `sh-help-row${off ? " is-off" : ""}`},
        h("dt", {}, c.keys.map((k, i) => [i ? h("span", {class: "sh-help-or", text: " or "}) : null, h("kbd", {class: "u-kbd", text: core.keyLabel(k, IS_MAC)})]),
          c.when === "grid" ? h("span", {class: "sh-help-scope", text: " in the table"}) : null),
        h("dd", {text: `${c.label}${off ? " (off)" : ""}`})));
    }
    grid.append(h("section", {class: "sh-help-group"}, h("h3", {class: "sh-help-gtitle", text: g.name === "Grid" ? "Table grid" : g.name}), dl));
  }
  helpEl.append(grid);
  helpEl.append(h("p", {class: "sh-help-note", text: "The palette also runs: go to any column or section, add, remove or open a company, make it focal, load or save peer sets and layouts and show the methodology."}));
}

function positionAnchored() {
  if (tipState.anchor && !tipEl.hidden && tipState.anchor.isConnected) placeNear(tipEl, tipState.anchor, {gap: 6});
  if (selEl) positionSelector();
  if (menuState && menuState.anchor && menuState.anchor.isConnected) placeNear(menuState.el, menuState.anchor, {gap: 2});
}

// ---------------------------------------------------------------------------------------------
// Commands (7.2, 3.14)
// ---------------------------------------------------------------------------------------------

function runCommand(id, opts = {}) {
  if (!state) return;
  if (TABLE_COMMANDS.has(id) || /^preset\.\d$/.test(id)) ensureTableView();
  const m = /^preset\.(\d)$/.exec(id);
  if (m) {
    const p = core.PRESETS[Number(m[1]) - 1];
    if (p) { dispatch({type: "SET_PRESET", preset: p.id}); announce(`Columns: ${p.label}.`); }
    return;
  }
  if (id.startsWith("grid.") || ["peer.exclude", "peer.remove", "detail.open", "row.expand", "sort.focused"].includes(id)) {
    gridCommand(id);
    return;
  }
  switch (id) {
    case "palette.open": openPalette(); break;
    case "help.open": if (state.ui.overlay === "help") closeOverlay(true); else openOverlay("help"); break;
    case "company.open": openOverlay("selector"); break;
    case "basis.next": dispatch({type: "CYCLE_BASIS", dir: 1}); announceAfter(() => `Period ${state.basis}.`); break;
    case "basis.prev": dispatch({type: "CYCLE_BASIS", dir: -1}); announceAfter(() => `Period ${state.basis}.`); break;
    case "currency.next": dispatch({type: "CYCLE_CURRENCY", dir: 1}); announceAfter(() => `${getView() && getView().ctx ? getView().ctx.currencyLabel : state.currency}.`); break;
    case "earnings.toggle": dispatch({type: "TOGGLE_EARNINGS"});
      announceAfter(() => `Earnings ${state.earnings === "adjusted" ? "ex amortisation and IPR&D" : "GAAP/IFRS"}.`); break;
    case "metric.open": focusMetricSwitcher(); break;
    case "columns.find": openColumnFinder(); break;
    case "peer.add": openPeerPicker(); break;
    case "export.csv": exportCSV(); break;
    case "export.tsv": copyTSV(); break;
    case "filters.reset": {
      const n = (state.filters || []).length;
      if (!n) { announce("No filter is set."); break; }
      dispatch({type: "CLEAR_FILTERS"});
      break;
    }
    case "layout.reset": {
      const before = state;
      dispatch({type: "RESET_LAYOUT"});
      if (state === before) announce("Columns, widths and sort are already the preset's.");
      break;
    }
    case "outliers.toggle": dispatch({type: "TOGGLE_OUTLIERS"});
      announceAfter(() => (state.outliers === "exclude" ? "Statistics without outliers." : "Statistics with outliers.")); break;
    case "cf.next": dispatch({type: "CYCLE_CF_MODE", dir: 1}); announce(`Conditional format: ${lcfirst(core.CF_MODE_LABEL[state.cfMode] || state.cfMode)}.`); break;
    case "density.next": dispatch({type: "CYCLE_DENSITY"}); announce(`Row density: ${state.density}.`); break;
    case "text.bigger": dispatch({type: "SET_TEXT_SIZE", delta: 1}); announce(`Text size ${state.textSize}.`); break;
    case "text.smaller": dispatch({type: "SET_TEXT_SIZE", delta: -1}); announce(`Text size ${state.textSize}.`); break;
    case "undo": if (state.ui.undo) doUndo(); else announce("Nothing to undo."); break;
    case "overlay.close": escChain(null); break;
    case "peers.save": openPalette("", {kind: "set"}); break;
    case "peers.restore": {
      const before = state;
      dispatch({type: "RESTORE_SYSTEM"});
      if (state === before) announce("The system peers are already in use.");
      break;
    }
    case "peers.addAdjacent": {
      const before = state;
      dispatch({type: "ADD_POOL_C"});
      announceAfter(() => (state === before ? "No adjacent-subsector company is left to add." : "Added adjacent-subsector peers."));
      break;
    }
    case "layout.save": openPalette("", {kind: "layout"}); break;
    case "peers.edit": openPeers(); break;
    case "sources.open": openMethod("sources"); break;
    case "primary.reset": dispatch({type: "SET_PRIMARY", colId: null}); announceAfter(() => "Primary metric reset."); break;
    case "method.open": openMethod(opts.anchor || null); break;
    case "singlekeys.toggle": dispatch({type: "SET_SINGLE_KEYS", on: state.singleKeys === false});
      announce(`Single-key shortcuts ${state.singleKeys !== false ? "on" : "off"}.`); break;
    case "reload": doReload(); break;
    case "focus": setFocal(opts.ticker); break;
    case "view.scorecard": setView("scorecard"); break;
    case "view.table": setView("table"); break;
    case "compare.open": openCompare(); break;
    default: break;
  }
}

function focusMetricSwitcher() {
  revealCharts();
  const c = api("charts");
  if (!c) { announce("The peer position chart is not available."); return; }
  if (typeof c.focusSwitcher === "function") c.focusSwitcher();
  else if (typeof c.focusDotPlot === "function") c.focusDotPlot();
}
function openColumnFinder() {
  const t = api("table");
  if (t && typeof t.openColumnFinder === "function") { t.openColumnFinder(); return; }
  if (t) { revealInMain(slots.table); openOverlay("columnfinder"); return; }
  openPalette("Go to column ");
}
function openPeerPicker() {
  openPeers({search: true});
  announce("Search all companies to add a peer.");
}

function focusedCell() {
  const f = state.ui.focus;
  if (f && f.row) return f;
  const ae = document.activeElement;
  const g = ae && ae.closest ? ae.closest('[role="grid"]') : null;
  const id = g ? g.getAttribute("aria-activedescendant") : null;
  const mm = id ? /^c-(.+)-([a-z0-9_]+)$/.exec(id) : null;
  return mm ? {row: mm[1], col: mm[2]} : null;
}
function gridCommand(id) {
  const f = focusedCell();
  if (!f) return;
  const v = getView();
  switch (id) {
    case "peer.exclude":
      if (f.row === state.focal) { announce("The focal company is never in the statistics."); return; }
      dispatch({type: "TOGGLE_EXCLUDE", ticker: f.row});
      announceAfter(() => `${f.row} ${(state.excluded || []).includes(f.row) ? "excluded from" : "included in"} the statistics.`);
      return;
    case "peer.remove":
      if (f.row === state.focal) { announce("The focal company cannot be removed."); return; }
      dispatch({type: "REMOVE_PEER", ticker: f.row});
      return;
    case "detail.open": openDetail(f.row); return;
    case "row.expand": if (f.row !== state.focal) dispatch({type: "TOGGLE_ROW_EXPANDED", ticker: f.row}); return;
    case "sort.focused": if (f.col) { dispatch({type: "SORT", colId: f.col}); announce(state.sort ? `Sorted by ${f.col}, ${state.sort.dir === "asc" ? "ascending" : "descending"}.` : "Sort cleared."); } return;
    default: break;
  }
  if (!v || !v.table) return;
  const rows = (v.table.rows || []).map((r) => r.ticker);
  const cols = (v.table.columns || []).map((c) => c.id);
  if (!rows.length || !cols.length) return;
  let ri = Math.max(0, rows.indexOf(f.row));
  let ci = cols.indexOf(f.col);
  if (ci < 0) ci = Math.max(0, cols.indexOf("ticker"));
  switch (id) {
    case "grid.up": ri -= 1; break;
    case "grid.down": ri += 1; break;
    case "grid.left": ci -= 1; break;
    case "grid.right": ci += 1; break;
    case "grid.rowStart": ci = 0; break;
    case "grid.rowEnd": ci = cols.length - 1; break;
    case "grid.pageUp": ri -= 10; break;
    case "grid.pageDown": ri += 10; break;
    default: return;
  }
  ri = Math.max(0, Math.min(rows.length - 1, ri));
  ci = Math.max(0, Math.min(cols.length - 1, ci));
  tableFocus(rows[ri], cols[ci]);
}

// Esc (7.2): close the top-most of palette, help, menu, "Why?", selector, methodology drawer,
// side panel; else clear cell focus. A visible tooltip is dismissed first (7.5).
function escChain(e) {
  const t = e ? e.target : null;
  if (tipState.anchor && !tipEl.hidden) { hideTip(); return true; }
  if (menuState) { closeMenu(true); return true; }
  if (state.ui.overlay) { closeOverlay(true); return true; }
  if (state.ui.method) { closeMethod(); return true; }
  if (state.ui.peers) { closePeers(); return true; }
  if (state.ui.detail) { closeDetail(); return true; }
  if (state.ui.compareOpen) { closeCompare(); return true; }
  if (t && isTextTarget(t)) { t.blur(); return true; }
  if (state.ui.focus) { dispatch({type: "FOCUS_CELL", row: null}); return true; }
  return false;
}

function onKeyDown(e) {
  if (!state || !payload || e.defaultPrevented || e.isComposing) return;
  if (mode === "bridge") {
    // No palette, help or single keys on the Forecast tab: Esc closes a tooltip or a menu.
    if (e.key === "Escape") { if (tipState.anchor && !tipEl.hidden) { hideTip(); e.preventDefault(); } else if (menuState) { closeMenu(true); e.preventDefault(); } }
    return;
  }
  const key = core.normKey(e, IS_MAC);
  const t = e.target;
  if (key === "esc") { if (escChain(e)) e.preventDefault(); return; }
  if (key === "mod+k") { e.preventDefault(); openPalette(); return; }
  if (isTextTarget(t)) return;
  if (modalOpen()) {
    if (key === "?" && state.ui.overlay === "help") { e.preventDefault(); closeOverlay(true); }
    return;
  }
  const zone = t && t.closest ? (t.closest('[role="grid"]') ? "grid" : t.closest(".ch-plot") ? "chart" : "") : "";
  const id = core.handleKey(state, key, zone);
  if (!id) return;
  e.preventDefault();
  runCommand(id, {zone});
}

// ---------------------------------------------------------------------------------------------
// Export and clipboard
// ---------------------------------------------------------------------------------------------

function exportCSV() {
  const v = getView();
  let text = "", name = "comps.csv";
  try { text = core.toCSV(v); name = core.csvFilename(v); } catch (e) { announce(`Export failed: ${errText(e)}.`); return; }
  if (!text) { showToast("Nothing to export: the table did not compute."); return; }
  try {
    const blob = new Blob([text], {type: "text/csv;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const a = h("a", {href: url, download: name, class: "u-sr"});
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
    showToast(`Exported ${name}.`);
  } catch (e) {
    showToast(`Export failed: ${errText(e)}.`);
  }
}
function copyTSV() {
  const v = getView();
  let text = "";
  try { text = core.toTSV(v); } catch (e) { text = ""; }
  if (!text) { showToast("Nothing to copy: the table did not compute."); return; }
  copyText(text, "the table as TSV");
}
async function copyText(text, what) {
  let ok = false;
  const back = document.activeElement;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) { await navigator.clipboard.writeText(text); ok = true; }
  } catch (e) { ok = false; }
  if (!ok) {
    try {
      const ta = h("textarea", {class: "u-sr", "aria-hidden": "true", tabindex: "-1"});
      ta.value = text;
      document.body.append(ta);
      ta.select();
      ok = document.execCommand("copy");
      ta.remove();
    } catch (e) { ok = false; }
    focusEl(twinOf(back));
  }
  showToast(ok ? `Copied ${what}.` : `Could not copy ${what}: the browser blocked the clipboard.`);
}

// ---------------------------------------------------------------------------------------------
// Python round trips (7.5)
// ---------------------------------------------------------------------------------------------

let lastNonce = 0;
function send(value) {
  const v = Object.assign({}, value || {});
  if (v.nonce == null) { lastNonce = Math.max(Date.now(), lastNonce + 1); v.nonce = lastNonce; }
  Streamlit.setComponentValue(v);
}
function doReload() {
  send({action: "reload"});
  showToast("Reloading the comps from the API.");
}
/** Click the parent's Streamlit tab with this label (as covnav does). */
function clickParentTab(label) {
  try {
    const tabs = window.parent.document.querySelectorAll('button[data-baseweb="tab"]');
    for (const tb of tabs) {
      if ((tb.textContent || "").trim() === label) { tb.click(); return true; }
    }
  } catch (e) { /* no parent access */ }
  return false;
}

// ---------------------------------------------------------------------------------------------
// ctx (11.1)
// ---------------------------------------------------------------------------------------------

const ctx = {
  dispatch,
  getState: () => state,
  getView,
  openDetail,
  closeDetail,
  openMethod,
  closeMethod,
  openPeers,
  closePeers,
  announce,
  tooltip: {
    show: (anchor, content) => showTip(anchor, content, false),
    hide: hideTip,
    describe,
  },
  menu: {open: (anchor, items, opts) => openMenu(anchor, items, opts), close: () => closeMenu(false)},
  toast: (label, opts) => showToast(label, opts || {}),
  send,
  clickParentTab,
  focusCell: (ticker, colId) => tableFocus(ticker, colId),
  scrollToColumn: (colId) => { const t = api("table"); if (t && typeof t.scrollToColumn === "function") t.scrollToColumn(colId); },
  goToColumn: (colId, ticker) => goToColumn(colId, ticker),
  scrollToSection: (id, focus) => scrollToSection(id, focus !== false),
  runCommand: (id, opts) => runCommand(id, opts || {}),
  setFocal,
  setView,
  toggleCompare,
  openCompare,
  closeCompare,
  flush,
  isMac: IS_MAC,
};
Object.defineProperty(ctx, "storageOk", {get: () => store.ok, enumerable: true});
// The table's scroll offsets from the session, so a page reload keeps its position.
Object.defineProperty(ctx, "initialViewport", {get: () => (sessionRaw && sessionRaw.table) || null, enumerable: true});
Object.defineProperty(ctx, "layout", {get: () => layout, enumerable: true});
Object.defineProperty(ctx, "mode", {get: () => mode, enumerable: true});
Object.defineProperty(ctx, "height", {get: () => heightMode, enumerable: true});
// Revision 4: the company map Python drew, {svg, digest}; scorecard.js swaps it on a new digest.
Object.defineProperty(ctx, "chart", {get: () => chart, enumerable: true});

// ---------------------------------------------------------------------------------------------
// Global listeners
// ---------------------------------------------------------------------------------------------

let tipsWired = false;
/** The shared tooltip and the outside-click rules: wired once, in either mode. */
function wireTips() {
  if (tipsWired) return;
  tipsWired = true;
  // Tooltips: delegated hover (300 ms) and immediate keyboard focus.
  document.addEventListener("mouseover", (e) => {
    if (tipEl.contains(e.target)) { clearTimeout(tipState.hideTimer); return; }
    const a = tipAnchorOf(e.target);
    if (a === tipState.hover) return;
    tipState.hover = a;
    clearTimeout(tipState.showTimer);
    // A control that was just pressed keeps quiet until the pointer leaves it, also when a
    // re-render replaced its element (same data-key).
    if (a && tipState.pressed) {
      const key = a.getAttribute ? a.getAttribute("data-key") : null;
      if (a === tipState.pressed || (key && key === tipState.pressedKey)) return;
    }
    tipState.pressed = null;
    tipState.pressedKey = null;
    if (a) {
      if (tipState.anchor === a) { clearTimeout(tipState.hideTimer); return; }
      tipState.showTimer = setTimeout(() => {
        if (tipState.hover !== a || !a.isConnected) return;
        if (a.getAttribute && a.getAttribute("aria-expanded") === "true") return;   // its menu or popover is open
        showTip(a, a.__shTip, false);
      }, TIP_DELAY);
    } else if (tipState.anchor && !tipState.byFocus) {
      scheduleHideTip();
    }
  });
  document.documentElement.addEventListener("mouseleave", () => {
    tipState.hover = null;
    clearTimeout(tipState.showTimer);
    if (tipState.anchor && !tipState.byFocus) scheduleHideTip();
  });
  document.addEventListener("focusin", (e) => {
    const t = e.target;
    if (t && t.__shTip) {
      let visible = true;
      try { visible = t.matches(":focus-visible"); } catch (err) { visible = true; }
      if (visible) showTip(t, t.__shTip, true);
    } else if (tipState.anchor && tipState.byFocus && !tipEl.contains(t)) hideTip();
  });
  document.addEventListener("focusout", (e) => {
    if (tipState.anchor === e.target && !(e.relatedTarget && tipEl.contains(e.relatedTarget))) hideTip();
  });

  // Clicks outside close the menu, the "Why?" popover and the selector.
  document.addEventListener("pointerdown", (e) => {
    const t = e.target;
    clearTimeout(tipState.showTimer);
    const pa = tipAnchorOf(t);
    tipState.pressed = pa;
    tipState.pressedKey = pa && pa.getAttribute ? pa.getAttribute("data-key") : null;
    if (tipEl && !tipEl.contains(t) && tipState.anchor && !tipState.anchor.contains(t)) hideTip();
    else if (tipEl && tipState.anchor && pa === tipState.anchor && !tipState.byFocus) hideTip();
    if (menuState && !menuState.el.contains(t) && !(menuState.anchor && menuState.anchor.contains(t))) closeMenu(false);
    if (state && state.ui.overlay === "selector" && selEl && !selEl.contains(t)) {
      const b = ctxEl ? ctxEl.querySelector('[data-key="company"]') : null;
      if (!(b && b.contains(t))) closeOverlay(false);
    }
  }, true);
}

let wired = false;
let resizeRaf = 0, scrollRaf = 0, scrollSaveTimer = 0;
function wireGlobal() {
  if (wired) return;
  wired = true;
  document.addEventListener("keydown", onKeyDown);
  window.addEventListener("resize", () => { if (!resizeRaf) resizeRaf = nextFrame(onResize); });
  window.addEventListener("focus", updateKeyState);
  window.addEventListener("blur", updateKeyState);
  document.addEventListener("focusin", updateKeyState);

  // The toast pauses while it is hovered or focused.
  toastEl.addEventListener("mouseenter", () => clearTimeout(toastTimer));
  toastEl.addEventListener("mouseleave", () => { if (!toastEl.hidden && !toastEl.contains(document.activeElement)) startToastTimer(); });
  toastEl.addEventListener("focusin", () => clearTimeout(toastTimer));
  toastEl.addEventListener("focusout", (e) => { if (!toastEl.hidden && !toastEl.contains(e.relatedTarget)) startToastTimer(); });

  // #main scroll: height mode, scroll memory, tooltips follow nothing that moves.
  mainEl.addEventListener("scroll", () => {
    if (tipState.anchor && mainEl.contains(tipState.anchor)) hideTip();
    if (!scrollRaf) scrollRaf = nextFrame(() => { scrollRaf = 0; updateHeightMode(); });
    clearTimeout(scrollSaveTimer);
    scrollSaveTimer = setTimeout(persistNow, 400);
  }, {passive: true});

  // A wheel over the pinned band scrolls #main: the band never scrolls itself, so the lower
  // sections stay in reach wherever the pointer rests.
  for (const el of [ctxEl, scopeRow]) {
    el.addEventListener("wheel", (e) => {
      if (e.ctrlKey || !e.deltaY) return;
      const unit = e.deltaMode === 1 ? 18 : e.deltaMode === 2 ? mainEl.clientHeight : 1;
      mainEl.scrollTop += e.deltaY * unit;
    }, {passive: true});
  }

  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => { measureBand(); });
    for (const el of [ctxEl, scopeRow, mainEl]) ro.observe(el);
    const ctxRo = new ResizeObserver(() => { fitCtx(); fitScope(); });
    ctxRo.observe(ctxEl);
  }
  try {
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => { sigs.ctx = null; fitCtx(); fitScope(); measureBand(); fitFrame(); });
    }
  } catch (e) { /* no font loading API */ }
  window.addEventListener("pagehide", persistNow);
  wireStorageSync();
}

function onResize() {
  resizeRaf = 0;
  if (!window.innerWidth) return;                          // a hidden tab: keep the last layout
  const l = layoutFor(window.innerWidth);
  if (l !== layout) {
    layout = l;
    app.setAttribute("data-layout", layout);
    if (state && payload) scheduleRender();
  } else {
    fitCtx();
    fitScope();
    measureBand();
    updateHeightMode();
    positionAnchored();
  }
  fitFrame();
}

// ---------------------------------------------------------------------------------------------
// Start: the loading state, then tell Streamlit the frame is ready
// ---------------------------------------------------------------------------------------------

if (HAS_DOM) {
  // The skeleton is built on the first render message: it names the mode (12.5), and the
  // tokens arrive with it, so nothing could paint before it anyway.
  Streamlit.componentReady();
}
