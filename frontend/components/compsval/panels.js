/**
 * panels.js: the panels of the Comps valuation view. Owner D.
 *
 * Contract: docs/design/comps-valuation.md section 6 (6.1 drivers and risks, 6.2 peer selection,
 * 6.3 notes and data sources and the methodology drawer, 6.4 detail side panel) and the bridge
 * inputs table of 5.3. Exports of 11.1, each `(root, ctx) -> {update(view), destroy()}`:
 *
 *   mountBridgeInputs   .pn-br      valuation bridge inputs (analyst inputs distinct from sourced)
 *   mountObservations   .pn-obs     drivers and risks, each linked to its column
 *   mountPeerPanel      .pn-peers   relevance grid, candidates, saved sets, subgroups, cohorts
 *   mountNotesSources   .pn-notes   sources and timestamps, analyst notes, storage notice
 *   mountMethod         .pn-method  methodology drawer (renders only while state.ui.method is set)
 *   mountDetail         .pn-detail  company side panel (renders only while state.ui.detail is set)
 *
 * Every mount renders its own section title. It reads only `view` (core.deriveView) plus
 * `ctx.getState()` for the few settings the view does not echo (the chosen cohorts), and changes
 * state only through `ctx.dispatch`. A rebuild keeps focus, typed text and scroll positions
 * (charts.rebuildKeepingFocus). No colour literal here: classes in panels.css.
 */

import {
  h, chip, stateBlock, bindTip, uid, rebuildKeepingFocus, sig, goToColumn, lcfirst,
  sparkline, barMini, lineMini, phaseBars,
} from "./charts.js";
import {
  BRIDGEABLE, COLUMN_BY_ID, NA_TEXT, NULL_GLYPH, STATE_COPY, STORAGE_LINE, RELEVANCE_COMPONENTS,
  UNDO_MS, MAX_ABS_GROWTH, MIN_MARGIN, fmtNumber, fmtDate, fmtDateShort, fmtTime, fmtMoneyProse, metricLabel, ordinal,
  paletteExtras,
} from "./core.js";

// ---------------------------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------------------------

const UP = "▲", DOWN = "▼";
const SAVED_HERE = "Saved in this browser only.";
const COMPONENT_ORDER = ["subsector", "model", "scale", "geography", "growth", "profitability"];
const COMPONENT_LABEL = Object.fromEntries(RELEVANCE_COMPONENTS.map((c) => [c.id, c.label]));
const SOURCE_NAMES = {prices: "Prices", consensus_nasdaq: "Nasdaq consensus", financials: "Financials", fx: "FX",
  approvals: "Approvals", ndc_marketing: "NDC marketing", paragraph_iv: "Paragraph IV", press_ir: "Press releases",
  press_page: "Press page", filings: "Filings", labels: "Labels", trials: "Trials", catalysts: "Catalysts"};

function isNum(v) { return typeof v === "number" && Number.isFinite(v); }
function dispatch(ctx, action) { if (ctx && typeof ctx.dispatch === "function") ctx.dispatch(action); }
function announce(ctx, text) { if (ctx && typeof ctx.announce === "function" && text) ctx.announce(text); }
function stateOf(ctx) {
  try { return ctx && typeof ctx.getState === "function" ? ctx.getState() || {} : {}; } catch (e) { return {}; }
}
function storageOk(ctx) {
  if (!ctx) return true;
  const v = typeof ctx.storageOk === "function" ? ctx.storageOk() : ctx.storageOk;
  return v !== false;
}
function nowMs() { return Date.now(); }
function sourceName(id) { return SOURCE_NAMES[id] || String(id || "").replace(/_/g, " "); }
function fx(view) { return {usd_per_unit: (view && view.lineage && view.lineage.rates) || {}}; }
function signedPct(v, d = 1) { return isNum(v) ? `${fmtNumber(v * 100, d, {signed: true})}%` : NULL_GLYPH; }
function arrowPct(v, d = 1) {
  if (!isNum(v)) return NULL_GLYPH;
  const g = v > 0 ? UP : v < 0 ? DOWN : "";
  return `${g ? g + " " : ""}${fmtNumber(v * 100, d, {signed: true})}%`;
}
function dateTime(ts) {
  if (!ts) return NULL_GLYPH;
  const t = fmtTime(ts);
  return t === NULL_GLYPH ? fmtDate(ts) : `${fmtDate(ts)}, ${t} UTC`;
}
function shortStamp(ts) {
  if (!ts) return NULL_GLYPH;
  const t = fmtTime(ts);
  return t === NULL_GLYPH ? fmtDateShort(ts) : `${fmtDateShort(ts)}, ${t}`;
}
function labelCtx(view) {
  const a = view && view.analysis && view.analysis.ctx;
  return a ? {fy0Label: a.fy0Label, fy1Label: a.fy1Label, fy2Label: a.fy2Label} : (view ? view.ctx : {});
}
function hiddenHost(parent) {
  const host = h("div", {hidden: true, class: "pn-desc"});
  parent.appendChild(host);
  return host;
}
function sectionHead(title, id, ...extras) {
  return h("div", {class: "pn-head"}, h("h2", {class: "u-section-title pn-title", id, text: title}), ...extras);
}
function sub(title, ...kids) {
  return h("section", {class: "pn-sub"}, h("h3", {class: "pn-sub-title", text: title}), ...kids);
}
function btn(text, attrs = {}, onClick = null) {
  const b = h("button", {type: "button", class: `u-btn${attrs.cls ? " " + attrs.cls : ""}`, ...attrs, cls: null, text});
  if (onClick) b.addEventListener("click", onClick);
  return b;
}
function linkBtn(text, attrs = {}, onClick = null) { return btn(text, {...attrs, cls: `link${attrs.cls ? " " + attrs.cls : ""}`}, onClick); }
function sectionError(view, id, name) {
  const e = view && view.sectionErrors && view.sectionErrors[id];
  return stateBlock(e || {severity: "red", title: "This section could not be computed",
    detail: `${name} failed. The rest of the view is unaffected.`});
}
function makeFocal(ctx, ticker) {
  if (!ticker) return;
  if (ctx && typeof ctx.setFocal === "function") { ctx.setFocal(ticker); return; }
  dispatch(ctx, {type: "SET_FOCAL", ticker});
  if (ctx && typeof ctx.send === "function") ctx.send({action: "focus", ticker, nonce: nowMs()});
}
function openDetail(ctx, ticker) {
  if (ctx && typeof ctx.openDetail === "function") ctx.openDetail(ticker);
  else dispatch(ctx, {type: "OPEN_DETAIL", ticker});
}
function openMethod(ctx, anchor) {
  if (ctx && typeof ctx.openMethod === "function") ctx.openMethod(anchor);
  else dispatch(ctx, {type: "OPEN_METHOD", anchor});
}
function storageNote(ctx) {
  if (storageOk(ctx)) return h("p", {class: "u-meta pn-saved", text: SAVED_HERE});
  const c = STATE_COPY.storage_unavailable;
  return h("p", {class: "u-meta pn-saved pn-saved-off"}, h("span", {class: "u-marker amber", "aria-hidden": "true", text: "!"}), c.detail);
}
function isTyping(el) {
  if (!el || !el.tagName) return false;
  const t = el.tagName.toLowerCase();
  return t === "input" || t === "textarea" || t === "select" || el.isContentEditable;
}

/**
 * Parse an analyst number: commas and spaces dropped, a true minus or an en dash read as minus,
 * a trailing ×, x or % ignored. Empty gives null; anything else unreadable gives NaN.
 */
export function parseNumberInput(text) {
  if (text === null || text === undefined) return null;
  const t = String(text).trim().replace(/[\s,]/g, "").replace(/[−–]/g, "-").replace(/[×x%]$/i, "");
  if (t === "") return null;
  if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(t)) return NaN;
  return Number(t);
}

/** Plain text for an input's value: fixed decimals, no separators, a hyphen minus. */
export function inputText(v, decimals = 2) {
  if (!isNum(v)) return "";
  return Number(v.toFixed(decimals)).toString();
}

/**
 * A number input that commits on Enter or blur and restores on Escape. `onCommit(v)` receives a
 * number or null (emptied: back to the sourced value).
 */
function numInput(ctx, {key, value, decimals = 2, label, analyst = false, onCommit, width = 96, placeholder = ""}) {
  const el = h("input", {type: "text", inputmode: "decimal", autocomplete: "off", spellcheck: "false",
    class: `u-input num pn-num${analyst ? " analyst" : ""}`, "data-key": key, "aria-label": label,
    value: inputText(value, decimals), placeholder, style: {width: `${width}px`}});
  const orig = el.value;
  let done = false;
  const commit = () => {
    if (done) return;
    if (el.value === orig) { el.removeAttribute("data-dirty"); return; }
    const v = parseNumberInput(el.value);
    if (Number.isNaN(v)) {
      announce(ctx, "Enter a number.");
      el.value = orig;
      el.removeAttribute("data-dirty");
      return;
    }
    done = true;
    el.removeAttribute("data-dirty");
    onCommit(v);
  };
  el.addEventListener("input", () => el.setAttribute("data-dirty", "1"));
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); commit(); }
    else if (e.key === "Escape") {
      if (el.value !== orig) { e.preventDefault(); e.stopPropagation(); el.value = orig; el.removeAttribute("data-dirty"); }
    }
  });
  // On blur the commit waits a tick: a rebuild during the focus change would drop the focus
  // that is moving to the next control. Enter commits at once; focus stays on this input.
  const later = () => setTimeout(commit, 0);
  el.addEventListener("change", later);
  el.addEventListener("blur", later);
  return el;
}

/** A labelled select; `options` [{id, label, disabled, title}]. */
function selectEl(key, label, options, value, onChange, cls = "") {
  const el = h("select", {class: `u-input pn-select ${cls}`.trim(), "data-key": key, "aria-label": label},
    options.map((o) => h("option", {value: o.id, selected: o.id === value, disabled: !!o.disabled, title: o.title || null, text: o.label})));
  el.addEventListener("change", () => onChange(el.value));
  return el;
}

/** Source chip of a bridge step (5.3, 4.2 provenance words). Analyst inputs carry "Analyst". */
function sourceChip(ctx, source, sourceText, descHost) {
  if (source === "analyst") {
    const c = chip("Analyst", "analyst", {class: "pn-src"});
    bindTip(ctx, c, {title: "Analyst input", body: "Entered by you, not sourced. Reset restores the sourced or calculated value."}, descHost);
    return c;
  }
  if (source === "sourced") {
    const c = chip("Sourced", "neutral", {class: "pn-src", tabindex: "0"});
    bindTip(ctx, c, {title: "Sourced", body: sourceText || "From the filings and feeds on file."}, descHost);
    return c;
  }
  if (source === "model") return chip("Model output", "neutral", {class: "pn-src"});
  const c = chip("Calculated", "neutral", {class: "pn-src"});
  if (sourceText && sourceText !== "Calculated") bindTip(ctx, c, sourceText, descHost);
  return c;
}

/**
 * createMount: the shared update loop. `spec.sig(view, local)` decides whether a rebuild is due;
 * `spec.build(root, view, local, api)` draws; `spec.after(root, view, local, api)` runs after
 * every rebuild (focus moves). `local` is mount-private UI state kept across rebuilds.
 */
function createMount(root, ctx, cls, spec) {
  for (const c of cls.split(" ")) root.classList.add(c);
  let view = null, lastSig = null, destroyed = false, bump = 0;
  const local = spec.local ? spec.local() : {};
  const api = {
    rerender() { bump += 1; render(true); },
    get view() { return view; },
  };
  function render(force) {
    if (destroyed || !view) return;
    let s;
    try { s = sig(spec.sig(view, local), bump, storageOk(ctx)); } catch (e) { s = String(Math.random()); }
    if (!force && s === lastSig) return;
    lastSig = s;
    rebuildKeepingFocus(root, () => {
      root.textContent = "";
      try { spec.build(root, view, local, api); } catch (e) {
        root.textContent = "";
        root.appendChild(stateBlock({severity: "red", title: "This section could not be computed",
          detail: `${spec.name || "This panel"} failed: ${e && e.message ? e.message : e}. The rest of the view is unaffected.`}));
      }
    });
    if (spec.after) spec.after(root, view, local, api);
  }
  return {
    update(v) { view = v; render(false); },
    destroy() {
      destroyed = true;
      if (spec.destroy) spec.destroy(root, local);
      root.textContent = "";
      for (const c of cls.split(" ")) root.classList.remove(c);
    },
    _api: api,
  };
}

// ---------------------------------------------------------------------------------------------
// 5.3 Valuation bridge inputs (mountBridgeInputs)
// ---------------------------------------------------------------------------------------------

const STAT_OPTIONS = [
  {id: "median", label: "Median"}, {id: "mean", label: "Mean"}, {id: "p25", label: "25th percentile"},
  {id: "p75", label: "75th percentile"}, {id: "pct", label: "Percentile"},
];

/** Options of the valuation metric select: every bridgeable column on each basis it supports. */
export function bridgeMetricOptions(lctx = {}) {
  const out = [];
  for (const colId of BRIDGEABLE) {
    const c = COLUMN_BY_ID[colId];
    if (!c) continue;
    const bases = c.bases && c.bases[0] !== "-" ? c.bases : ["-"];
    for (const b of bases) out.push({id: `${colId}|${b === "-" ? "" : b}`, colId, basis: b === "-" ? null : b,
      label: metricLabel(colId, b === "-" ? "NTM" : b, lctx)});
  }
  return out;
}

export function mountBridgeInputs(root, ctx) {
  return createMount(root, ctx, "pn-br", {
    name: "Valuation bridge",
    sig: (v) => [v.bridge, v.focal && v.focal.ticker, v.ctx && v.ctx.currency, v.sectionErrors && v.sectionErrors.bridge,
      v.primary && v.primary.candidates],
    build: (root, view) => buildBridgeInputs(root, view, ctx),
  });
}

function buildBridgeInputs(root, view, ctx) {
  const b = view.bridge;
  const T = view.focal ? view.focal.ticker : "";
  const titleId = uid("pnbr");
  const reset = btn("Reset to sourced", {"data-key": "br-reset", cls: "pn-br-reset"}, () => {
    dispatch(ctx, {type: "RESET_BRIDGE"});
    announce(ctx, "Bridge inputs reset to sourced and calculated values.");
  });
  // RESET_BRIDGE clears the focal company's stored inputs; with none stored there is nothing to reset.
  const stored = (stateOf(ctx).bridge || {})[T];
  const edited = !!(stored && Object.keys(stored).length) || !!(b && b.analyst && Object.values(b.analyst).some(Boolean));
  if (!edited) {
    reset.setAttribute("aria-disabled", "true");
    bindTip(ctx, reset, "Every input is sourced or calculated already.");
  }
  const bridgeMode = !!ctx && (typeof ctx.mode === "function" ? ctx.mode() : ctx.mode) === "bridge";
  if (bridgeMode) root.appendChild(h("div", {class: "pn-head pn-br-head", id: titleId}, reset));
  else root.appendChild(sectionHead("Valuation bridge", titleId, reset));
  const descHost = hiddenHost(root);
  if (!b) { root.appendChild(sectionError(view, "bridge", "Valuation bridge")); return; }
  root.appendChild(h("p", {class: "u-meta pn-br-key"},
    "Sourced figures come from filings and feeds; calculated figures from the peer set; analyst inputs are yours, marked ",
    h("span", {class: "pn-analyst-sample", text: "Analyst"}), " with a dashed underline. ", SAVED_HERE));

  const lctx = labelCtx(view);
  const table = h("table", {class: "pn-br-table", "aria-labelledby": titleId});
  table.appendChild(h("caption", {class: "u-sr", text: `Valuation bridge inputs for ${T}`}));
  table.appendChild(h("thead", {}, h("tr", {},
    h("th", {scope: "col", class: "pn-br-lbl", text: "Input"}),
    h("th", {scope: "col", class: "pn-br-val", text: "Value"}),
    h("th", {scope: "col", class: "pn-br-src", text: "Source"}))));
  const tbody = h("tbody");
  table.appendChild(tbody);
  const row = (id, label, valueKids, srcKids, extra = {}) => {
    const tr = h("tr", {class: `pn-br-row pn-br-${id}${extra.cls ? " " + extra.cls : ""}`, "data-step": id},
      h("th", {scope: "row", class: "pn-br-lbl"}, label),
      h("td", {class: "pn-br-val"}, valueKids),
      h("td", {class: "pn-br-src"}, srcKids));
    tbody.appendChild(tr);
    return tr;
  };
  const inputs = b.inputs || {};
  const patch = (p, say) => { dispatch(ctx, {type: "SET_BRIDGE", patch: p}); if (say) announce(ctx, say); };
  const resetLink = (key, p, what) => linkBtn("Reset", {"data-key": key, cls: "pn-reset", "aria-label": `Reset ${what}`},
    () => patch(p, `${what} reset.`));

  // 1. Valuation metric.
  const opts = bridgeMetricOptions(lctx);
  const curId = `${b.colId || ""}|${b.basis && b.basis !== "-" ? b.basis : ""}`;
  const cands = new Map(((view.primary && view.primary.candidates) || []).map((c) => [c.colId, c]));
  for (const o of opts) {
    const c = cands.get(o.colId);
    if (c && !c.enabled && c.reason) o.title = c.reason;
  }
  if (!opts.some((o) => o.id === curId) && b.colId) opts.unshift({id: curId, label: b.metricLabel || b.colId});
  const metricSel = selectEl("br-metric", "Valuation metric", opts, curId, (val) => {
    const [colId, basis] = val.split("|");
    patch({colId, basis: basis || null, multipleOverride: null, metricOverride: null},
      `Bridge on ${(opts.find((o) => o.id === val) || {}).label || colId}.`);
  });
  row("metric", "Valuation metric", metricSel, sourceChip(ctx, "calculated", null, descHost));

  const steps = Object.fromEntries((b.steps || []).map((s) => [s.id, s]));
  if (!b.enabled && !(b.steps || []).length) {
    root.appendChild(table);
    // The reason itself is the chart's state block (5.3); here, the way out.
    root.appendChild(h("p", {class: "pn-empty pn-br-none"}, h("span", {class: "u-sr", text: `No bridge: ${b.reason || ""} `}),
      "No bridge on this metric. Choose another valuation metric above."));
    return;
  }

  // 2. Peer statistic.
  const st = steps.stat;
  if (st) {
    const kids = [selectEl("br-stat", "Peer statistic", STAT_OPTIONS, inputs.stat || "median", (v) => patch({stat: v},
      `Peer statistic: ${(STAT_OPTIONS.find((o) => o.id === v) || {}).label || v}.`))];
    if ((inputs.stat || "median") === "pct") {
      kids.push(numInput(ctx, {key: "br-pct", value: isNum(inputs.pct) ? inputs.pct : 50, decimals: 0, label: "Percentile, 0 to 100",
        analyst: true, width: 56, onCommit: (v) => {
          const p = v === null ? 50 : Math.max(0, Math.min(100, Math.round(v)));
          patch({pct: p}, `${ordinal(p)} percentile of peers.`);
        }}));
    }
    kids.push(h("span", {class: "u-meta pn-br-of", text: st.sourceText || ""}));
    row("stat", "Peer statistic", kids, sourceChip(ctx, st.source, null, descHost));
  }

  // 3. Applied multiple (or yield).
  const m = steps.multiple;
  if (m) {
    const isYield = b.colId === "fcf_yield";
    const shown = isNum(m.value) ? (isYield ? m.value * 100 : m.value) : null;
    const analyst = m.source === "analyst";
    const el = numInput(ctx, {key: "br-multiple", value: shown, decimals: 2, label: `Applied multiple${isYield ? ", percent" : ", times"}`,
      analyst, onCommit: (v) => patch({multipleOverride: v === null ? null : (isYield ? v / 100 : v)},
        v === null ? "Applied multiple back to the peer statistic." : "Applied multiple set by you.")});
    row("multiple", "Applied multiple", [el, h("span", {class: "pn-unit", text: isYield ? "%" : "×"})],
      [sourceChip(ctx, m.source, m.sourceText, descHost), analyst ? resetLink("br-multiple-reset", {multipleOverride: null}, "Applied multiple") : null],
      {cls: analyst ? "is-analyst" : ""});
  }

  // 4. Operating metric.
  const op = steps.operating;
  if (op) {
    const perShare = !!b.perShareX;
    const analyst = op.source === "analyst";
    const el = numInput(ctx, {key: "br-operating", value: op.value, decimals: perShare ? 2 : 0, label: op.label, analyst,
      width: perShare ? 96 : 112, onCommit: (v) => patch({metricOverride: v}, v === null ? `${op.label} back to the sourced figure.` : `${op.label} set by you.`)});
    row("operating", op.label, [el, h("span", {class: "pn-unit", text: op.unit || ""})],
      [sourceChip(ctx, op.source, op.sourceText, descHost), analyst ? resetLink("br-operating-reset", {metricOverride: null}, "Operating metric") : null],
      {cls: analyst ? "is-analyst" : ""});
  }

  // 5 to 7. Enterprise value route.
  if (steps.ev) {
    row("ev", "Implied enterprise value", valueText(steps.ev), sourceChip(ctx, "calculated", null, descHost));
  }
  const nd = steps.net_debt;
  if (nd) {
    const analyst = nd.source === "analyst";
    const el = numInput(ctx, {key: "br-netdebt", value: nd.value, decimals: 0, label: "Net debt, negative for net cash", analyst, width: 112,
      onCommit: (v) => patch({netDebtOverride: v}, v === null ? "Net debt back to the balance sheet figure." : "Net debt set by you.")});
    row("net_debt", "Less net debt", [el, h("span", {class: "pn-unit", text: nd.unit || ""})],
      [sourceChip(ctx, nd.source, nd.sourceText, descHost), analyst ? resetLink("br-netdebt-reset", {netDebtOverride: null}, "Net debt") : null],
      {cls: analyst ? "is-analyst" : ""});
  }
  const oc = steps.other_claims;
  if (oc) {
    const info = b.otherClaims || {};
    const on = !!info.on;
    const sw = h("button", {type: "button", role: "switch", class: "u-btn pn-switch", "data-key": "br-oc",
      "aria-checked": String(on), "aria-label": "Apply other claims", disabled: !info.available, text: on ? "On" : "Off"});
    sw.addEventListener("click", () => {
      if (!info.available) return;
      patch({otherClaimsOn: !on}, on ? "Other claims off." : "Other claims applied.");
    });
    const lines = (info.lines || []).map((l) => `${l.label}: ${fmtNumber(l.value, 0, {signed: true})} ${b.currency || "USD"} m${l.as_of ? `, ${fmtDate(l.as_of)}` : ""}`);
    bindTip(ctx, sw, info.available ? {title: "Filed claims outside cash and debt", body: info.text, lines} : (info.reason || NA_TEXT.none_on_file), descHost);
    const kids = [sw];
    let src;
    if (on) {
      const analyst = oc.source === "analyst";
      kids.push(numInput(ctx, {key: "br-oc-total", value: oc.value, decimals: 0, label: "Other claims total, positive adds to equity", analyst, width: 96,
        onCommit: (v) => patch({otherClaimsOverride: v}, v === null ? "Other claims back to the filed total." : "Other claims set by you.")}));
      kids.push(h("span", {class: "pn-unit", text: oc.unit || ""}));
      src = [sourceChip(ctx, oc.source, oc.sourceText, descHost), analyst ? resetLink("br-oc-reset", {otherClaimsOverride: null}, "Other claims") : null];
    } else {
      src = info.available ? sourceChip(ctx, "sourced", oc.sourceText, descHost) : h("span", {class: "u-meta", text: NULL_GLYPH});
    }
    kids.push(h("p", {class: "pn-br-note", text: info.available ? (on ? "On: the filed claims below cash and debt are applied to equity." : info.text) : (info.reason || NA_TEXT.none_on_file)}));
    row("other_claims", "Other claims", kids, src, {cls: on && oc.source === "analyst" ? "is-analyst" : ""});
  }

  // 8. Implied equity value.
  if (steps.equity) row("equity", "Implied equity value", valueText(steps.equity), sourceChip(ctx, "calculated", null, descHost));

  // 9. Shares.
  const sh = steps.shares;
  if (sh) {
    const src = inputs.sharesSource || "market_cap";
    const options = (b.sharesOptions || []).map((o) => ({id: o.id, label: o.label,
      title: isNum(o.value) ? `${fmtNumber(o.value, 1)} m shares` : null}));
    const kids = [selectEl("br-shares", "Share count", options, src, (v) => patch({sharesSource: v}, `Shares: ${(options.find((o) => o.id === v) || {}).label || v}.`), "pn-shares-sel")];
    const analyst = sh.source === "analyst";
    if (src === "analyst") {
      kids.push(numInput(ctx, {key: "br-shares-n", value: inputs.sharesOverride, decimals: 1, label: "Share count, millions of US-listed shares",
        analyst: true, width: 96, placeholder: "millions", onCommit: (v) => patch({sharesOverride: v}, v === null ? "Share count cleared." : "Share count set by you.")}));
      kids.push(h("span", {class: "pn-unit", text: "m"}));
    } else {
      kids.push(h("span", {class: "u-num pn-br-num", text: `${sh.text} m`}));
    }
    row("shares", "Shares", kids, sourceChip(ctx, sh.source, sh.sourceText, descHost), {cls: analyst ? "is-analyst" : ""});
  }

  // 10 to 12. Result, price, upside.
  const ps = steps.per_share;
  if (ps) {
    const kids = [h("span", {class: "u-num pn-br-result", text: ps.text}), h("span", {class: "pn-unit", text: "USD"})];
    if (b.negativeEquity) kids.push(h("p", {class: "pn-br-note pn-br-warn"}, h("span", {class: "u-marker amber", "aria-hidden": "true", text: "!"}),
      STATE_COPY.negative_equity.detail));
    row("per_share", "Implied value per share", kids, sourceChip(ctx, "calculated", null, descHost), {cls: "pn-br-resultrow"});
  }
  const pr = steps.price;
  if (pr) row("price", "Current price", valueText(pr), sourceChip(ctx, "sourced", pr.sourceText, descHost));
  const upside = steps.upside;
  if (upside) row("upside", "Upside or downside", h("span", {class: "u-num pn-br-num pn-br-upside", text: upside.text}),
    sourceChip(ctx, "calculated", null, descHost));
  root.appendChild(h("div", {class: "pn-br-scroll", "data-scroll-key": "br-table"}, table));

  // Below the table: range, street target, model value.
  const foot = h("ul", {class: "pn-br-foot"});
  if (b.range) {
    foot.appendChild(h("li", {}, h("span", {class: "pn-foot-lbl", text: "Interquartile range: "}),
      h("span", {class: "u-num", text: `${fmtNumber(b.range[0], 2)} to ${fmtNumber(b.range[1], 2)} per share`}),
      b.rangeUpside ? h("span", {class: "u-meta", text: ` (${signedPct(b.rangeUpside[0])} to ${signedPct(b.rangeUpside[1])})`}) : null,
      " ", sourceChip(ctx, "calculated", null, descHost)));
  }
  if (b.streetTarget) {
    const t = b.streetTarget;
    foot.appendChild(h("li", {}, h("span", {class: "pn-foot-lbl", text: "Street target, 12M: "}),
      h("span", {class: "u-num", text: `${fmtNumber(t.value, 2)} (${arrowPct(t.upside)})`}), " ",
      sourceChip(ctx, "sourced", `Nasdaq consensus${t.analysts ? `, ${t.analysts} analysts` : ""}${t.as_of ? `, ${fmtDate(t.as_of)}` : ""}.`, descHost)));
  } else {
    foot.appendChild(h("li", {}, h("span", {class: "pn-foot-lbl", text: "Street target, 12M: "}), h("span", {class: "u-null", text: NULL_GLYPH}),
      h("span", {class: "u-meta", text: " No consensus price target on file."})));
  }
  if (b.modelFairValue) {
    const mv = b.modelFairValue;
    foot.appendChild(h("li", {}, h("span", {class: "pn-foot-lbl", text: "Model fair value: "}),
      h("span", {class: "u-num", text: `${fmtNumber(mv.value, 2)}${mv.rating ? ` (${mv.rating})` : ""}`}),
      h("span", {class: "u-meta", text: `, model output${isNum(mv.upside) ? `, ${signedPct(mv.upside)} against price` : ""}`}),
      h("span", {class: "u-marker", "aria-hidden": "true", text: "M"})));
  }
  root.appendChild(foot);
  root.appendChild(h("p", {class: "u-sr", text: b.description || ""}));
}

/** History values with the table's n.m. rules applied: growth beyond MAX_ABS_GROWTH and margins
 * below MIN_MARGIN become null (not plotted), never clamped. */
export function historyValues(values, key) {
  return (values || []).map((v) => {
    if (!isNum(v)) return null;
    if (key === "net_margin") return v < MIN_MARGIN ? null : v;
    return Math.abs(v) > MAX_ABS_GROWTH ? null : v;
  });
}

function valueText(step) {
  if (!step) return h("span", {class: "u-null", text: NULL_GLYPH});
  const unit = step.unit && step.unit !== "%" ? step.unit : "";
  return [h("span", {class: `u-num pn-br-num${isNum(step.value) ? "" : " u-null"}`, text: step.text}), unit ? h("span", {class: "pn-unit", text: unit}) : null];
}

// ---------------------------------------------------------------------------------------------
// 6.1 Drivers and risks (mountObservations)
// ---------------------------------------------------------------------------------------------

const OBS_VISIBLE = 5;
const INSIGHT_VISIBLE = 5;

/** Follow an insight link: a table column, a tab of the page, or one indication's landscape. */
function followLink(ctx, view, link) {
  if (!link) return;
  if (ctx && typeof ctx.openLink === "function") { ctx.openLink(link); return; }
  if (link.kind === "column") { goToColumn(ctx, ctx && typeof ctx.getView === "function" ? ctx.getView() || view : view, link.colId); return; }
  if (link.kind === "tab" && ctx && typeof ctx.clickParentTab === "function") { ctx.clickParentTab(link.tab); return; }
  if (link.kind === "indication" && ctx && typeof ctx.send === "function") {
    ctx.send({action: "indication", indication_id: link.indicationId, ticker: view.focal ? view.focal.ticker : null});
  }
}
function insightChips(list) {
  return (list || []).map((c) => {
    const el = chip(c.text, c.tone || "neutral", {class: `pn-obs-chip pn-obs-chip-${c.id}`});
    if (c.tooltip) el.__tipText = c.tooltip;
    return el;
  });
}

export function mountObservations(root, ctx) {
  return createMount(root, ctx, "pn-obs", {
    name: "Drivers and risks",
    local: () => ({more: {premium: false, discount: false, catalysts: false, competition: false}}),
    sig: (v, local) => [v.insight, v.focal && v.focal.ticker, v.sectionErrors && v.sectionErrors.insight, local.more,
      v.table && (v.table.columns || []).map((c) => c.id)],
    build: (root, view, local, api) => buildObservations(root, view, ctx, local, api),
  });
}

function buildObservations(root, view, ctx, local, api) {
  const titleId = uid("pnobs");
  root.appendChild(sectionHead("Drivers and risks", titleId, chip("Observations, not conclusions", "neutral", {class: "pn-obs-tag"})));
  const I = view.insight;
  if (!I) { root.appendChild(sectionError(view, "insight", "Drivers and risks")); return; }
  const descHost = hiddenHost(root);
  const T = view.focal ? view.focal.ticker : "the focal company";

  // Row 1: what the comparison supports on each side.
  const sides = h("div", {class: "pn-obs-sides"});
  root.appendChild(sides);
  const side = (id, title, glyph, tone, items) => {
    const listId = uid("pnobsl");
    const box = h("section", {class: `pn-obs-side pn-obs-${id}`, "aria-labelledby": listId},
      h("h3", {class: "pn-sub-title", id: listId}, h("span", {class: `u-dir ${tone} pn-obs-glyph`, "aria-hidden": "true", text: glyph}), title));
    sides.appendChild(box);
    if (!items.length) {
      box.appendChild(h("p", {class: "pn-empty", text: "No observation passes the tests."}));
      return;
    }
    // Metric items fold after five; an item drawn from a catalyst or a pool always shows.
    const metric = items.filter((it) => it.kind === "metric"), other = items.filter((it) => it.kind !== "metric");
    const shown = (local.more[id] ? metric : metric.slice(0, OBS_VISIBLE)).concat(other);
    const ul = h("ul", {class: "pn-obs-list"});
    box.appendChild(ul);
    for (const it of shown) {
      const link = h("button", {type: "button", class: "u-chip pn-obs-link", "data-key": `obs-${it.id}`},
        h("span", {class: "u-chip-label", text: it.linkLabel}), h("span", {"aria-hidden": "true", text: "→"}));
      link.setAttribute("aria-label", `${it.linkLabel}: open`);
      link.addEventListener("click", () => followLink(ctx, view, it.link));
      const where = it.link && it.link.kind === "column" ? `Show ${lcfirst(it.linkLabel)} in the table, at ${T}'s cell.`
        : it.link && it.link.kind === "tab" ? `Open the ${it.link.tab} tab.`
          : it.link && it.link.kind === "indication" ? `Open Comps, Indications on ${lcfirst(it.link.name || "this indication")}.` : "";
      if (where) bindTip(ctx, link, where, descHost);
      const chips = h("div", {class: "pn-obs-chips"}, link);
      for (const c of insightChips(it.chips)) { chips.appendChild(c); if (c.__tipText) bindTip(ctx, c, c.__tipText, descHost); }
      ul.appendChild(h("li", {class: `pn-obs-item pn-obs-kind-${it.kind}`, "data-severity": it.severity || "info"},
        h("span", {class: `u-dir ${tone} pn-obs-glyph`, "aria-hidden": "true", text: glyph}),
        h("div", {class: "pn-obs-body"}, h("p", {class: "pn-obs-text"},
          h("span", {class: "u-sr", text: id === "premium" ? "Premium driver: " : "Discount driver: "}), it.text), chips)));
    }
    if (metric.length > OBS_VISIBLE) {
      const n = metric.length - OBS_VISIBLE;
      box.appendChild(linkBtn(local.more[id] ? "Show fewer" : `Show ${n} more`, {"data-key": `obs-more-${id}`, "aria-expanded": String(!!local.more[id])}, () => {
        local.more[id] = !local.more[id];
        api.rerender();
      }));
    }
  };
  const V = I.valuation || {premium: [], discount: [], notAssessed: []};
  side("premium", "Potential premium drivers", UP, "up", V.premium || []);
  side("discount", "Potential discount drivers", DOWN, "down", V.discount || []);

  // Row 2: the evidence for the company itself, catalysts and competition.
  const evidence = h("div", {class: "pn-obs-evidence"});
  root.appendChild(evidence);
  if (I.state === "pending" || I.state === "error") {
    const msg = I.message || {severity: I.state === "error" ? "amber" : "info",
      title: I.state === "error" ? "Catalysts and competition did not load" : `Loading catalysts and competition for ${T}`,
      detail: I.state === "error" ? "Reload with the reload button." : "They arrive with the page once the company changes."};
    const block = stateBlock(msg);
    block.classList.add("pn-obs-pending");
    if (I.state === "pending") block.setAttribute("aria-busy", "true");
    evidence.classList.add("is-state");
    evidence.appendChild(block);
  } else {
    evidence.appendChild(buildCatalysts(I.catalysts, view, ctx, local, api, descHost));
    evidence.appendChild(buildCompetition(I.competition, view, ctx, local, api, descHost));
  }

  const na = (V.notAssessed || []);
  if (na.length) {
    root.appendChild(h("div", {class: "pn-obs-na"}, h("h3", {class: "u-sr", text: "Not assessed"}),
      h("ul", {}, na.map((t) => h("li", {text: t})))));
  }
}

/** The heading row of an evidence group: title, count, an info button with the note, its link. */
function groupHead(G, id, view, ctx, descHost) {
  const titleId = uid(`pn${id}`);
  const head = h("div", {class: "pn-ev-head"},
    h("h3", {class: "pn-sub-title pn-ev-title", id: titleId, text: G.title}),
    G.countText ? h("span", {class: "u-meta pn-ev-count", text: G.countText}) : null);
  if (G.note) {
    const info = h("button", {type: "button", class: "u-btn icon pn-ev-info", "data-key": `${id}-info`, "aria-label": `About ${lcfirst(G.title)}`, text: "i"});
    bindTip(ctx, info, {title: G.title, body: G.note}, descHost);
    head.appendChild(info);
  }
  if (G.link && G.linkLabel) {
    const open = h("button", {type: "button", class: "u-btn link pn-ev-open", "data-key": `${id}-open`},
      h("span", {text: G.linkLabel}), h("span", {"aria-hidden": "true", text: " →"}));
    open.addEventListener("click", () => followLink(ctx, view, G.link));
    head.appendChild(open);
  }
  return {head, titleId};
}
function groupState(G) {
  const msg = G.empty || {severity: "info", title: G.title, detail: "Nothing to show."};
  const block = stateBlock(msg);
  block.classList.add("pn-ev-state");
  return block;
}
function moreRow(id, total, local, api) {
  if (total <= INSIGHT_VISIBLE) return null;
  const open = !!local.more[id];
  return linkBtn(open ? "Show fewer" : `Show ${total - INSIGHT_VISIBLE} more`, {"data-key": `${id}-more`, "aria-expanded": String(open), cls: "pn-ev-more"}, () => {
    local.more[id] = !open;
    api.rerender();
  });
}

function buildCatalysts(G, view, ctx, local, api, descHost) {
  const C = G || {state: "empty", title: "Catalysts ahead", rows: []};
  const {head, titleId} = groupHead(C, "cat", view, ctx, descHost);
  const box = h("section", {class: "pn-ev pn-obs-catalysts", "aria-labelledby": titleId}, head);
  if (C.state !== "ok" || !(C.rows || []).length) { box.appendChild(groupState(C)); return box; }
  const rows = local.more.catalysts ? C.rows : C.rows.slice(0, INSIGHT_VISIBLE);
  const list = h("ul", {class: "pn-ev-rows pn-cat-rows"});
  box.appendChild(list);
  for (const r of rows) {
    const date = h("span", {class: "pn-cat-date u-num"}, r.dateShort, r.estimated ? h("span", {class: "pn-cat-est", text: " est."}) : null);
    const label = h("span", {class: "pn-cat-label"},
      h("span", {class: "pn-cat-name", text: r.label}),
      r.indicationText ? h("span", {class: "pn-cat-ind", text: ` · ${r.indicationText}`}) : null,
      r.moreText ? h("span", {class: "pn-cat-more", text: ` · ${r.moreText}`}) : null);
    const model = r.modelText
      ? h("span", {class: "pn-cat-model u-num"}, r.modelText, h("span", {class: "u-marker pn-m", "aria-hidden": "true", text: "M"}))
      : h("span", {class: "pn-cat-model u-null", text: NULL_GLYPH});
    const open = h("button", {type: "button", class: "pn-ev-row pn-cat-row", "data-key": r.id}, date, label, model);
    open.setAttribute("aria-label", `${r.label}, ${r.dateText}${r.indicationText ? `, ${r.indicationText}` : ""}. ${r.modelText ? `${r.modelText}, model output.` : r.naText || "No modelled value."} Two-sided. Open the Catalysts tab`);
    open.addEventListener("click", () => followLink(ctx, view, r.link));
    bindTip(ctx, open, {title: r.label, lines: (r.tooltip || []).concat(r.modelText ? ["Two-sided: the outcome can raise or lower the value."] : [r.naText].filter(Boolean))});
    const li = h("li", {class: "pn-ev-li"}, open);
    if (r.sourceUrl) {
      const src = h("a", {class: "u-btn icon pn-cat-src", href: r.sourceUrl, target: "_blank", rel: "noopener noreferrer",
        "data-key": `${r.id}-src`, "aria-label": `Source for ${r.label}, opens in a new tab`, text: "↗"});
      li.appendChild(src);
    }
    list.appendChild(li);
  }
  const more = moreRow("catalysts", C.rows.length, local, api);
  if (more) box.appendChild(more);
  return box;
}

function buildCompetition(G, view, ctx, local, api, descHost) {
  const C = G || {state: "empty", title: "Competition by indication", rows: []};
  const {head, titleId} = groupHead(C, "comp", view, ctx, descHost);
  const box = h("section", {class: "pn-ev pn-obs-competition", "aria-labelledby": titleId}, head);
  if (C.state !== "ok" || !(C.rows || []).length) { box.appendChild(groupState(C)); return box; }
  if (C.lead) box.appendChild(h("p", {class: "u-meta pn-ev-lead", text: C.lead}));
  const cols = C.columns || ["Indication", "Value, $ a share · of price", "Own / rivals", "Pool claimed → supplied", "Share"];
  box.appendChild(h("div", {class: "pn-comp-grid pn-comp-cols", "aria-hidden": "true"}, cols.map((c, i) => h("span", {class: i ? "num" : "", text: c}))));
  const rows = local.more.competition ? C.rows : C.rows.slice(0, INSIGHT_VISIBLE);
  const list = h("ul", {class: "pn-ev-rows pn-comp-rows"});
  box.appendChild(list);
  const cellOr = (text, na, cls) => (text
    ? h("span", {class: `${cls} u-num num`, text})
    : h("span", {class: `${cls} u-null num`, text: NULL_GLYPH}));
  for (const r of rows) {
    const sideGlyphs = r.side === "both" ? [UP, DOWN] : r.side === "premium" ? [UP] : r.side === "discount" ? [DOWN] : [];
    const name = h("span", {class: "pn-comp-name"},
      sideGlyphs.map((g) => h("span", {class: `u-dir ${g === UP ? "up" : "down"} pn-comp-side`, "aria-hidden": "true", text: g})),
      h("span", {class: "pn-comp-text", text: r.name}));
    const rv = r.rivals || {n: 0};
    const total = Math.max(1, rv.n || 0);
    const seg = (n, cls) => (n ? h("i", {class: `pn-comp-seg ${cls}`, style: `flex-grow:${n}`}) : null);
    const counts = h("span", {class: "pn-comp-counts num"},
      h("span", {class: "u-num", text: `${(r.own && r.own.n) || 0} / ${rv.n || 0}`}),
      h("span", {class: "pn-comp-bar", "aria-hidden": "true", "data-total": String(total)},
        seg(rv.marketed, "marketed"), seg(rv.phase3, "p3"), seg(rv.phase2, "p2"), seg(rv.other, "other")));
    const open = h("button", {type: "button", class: "pn-ev-row pn-comp-grid pn-comp-row", "data-key": r.id},
      name, cellOr(r.valueText, r.valueNa, "pn-comp-value"), counts, cellOr(r.poolText, r.poolNa, "pn-comp-pool"), cellOr(r.shareText, r.shareNa, "pn-comp-share"));
    const spoken = [r.name, r.valueText ? `modelled value ${r.valueText.replace(" · ", ", ")} of price` : r.valueNa, r.ownText, r.rivalsText,
      r.poolText ? `pool claimed then supplied ${r.poolText.replace(" → ", " then ")}` : r.poolNa,
      r.shareText ? `share ${r.shareText}` : null].filter(Boolean).join(". ");
    open.setAttribute("aria-label", `${spoken}. Open this indication's landscape`);
    open.addEventListener("click", () => followLink(ctx, view, r.link));
    const lines = [r.ownText, r.rivalsText].concat(r.poolNa && !r.poolText ? [r.poolNa] : []).concat(r.tooltip || []).filter(Boolean);
    bindTip(ctx, open, {title: r.name, lines});
    list.appendChild(h("li", {class: "pn-ev-li"}, open));
  }
  const more = moreRow("competition", C.rows.length, local, api);
  if (more) box.appendChild(more);
  return box;
}

// ---------------------------------------------------------------------------------------------
// 6.2 Peer selection (mountPeerPanel)
// ---------------------------------------------------------------------------------------------

const PEER_COLS = [
  {id: "sel", label: "Select", sr: true},
  {id: "stats", label: "In statistics"},
  {id: "ticker", label: "Ticker", sort: (r) => r.ticker},
  {id: "name", label: "Company", sort: (r) => r.name},
  {id: "relevance", label: "Relevance", sort: (r) => (r.relevance ? r.relevance.score : -1), num: true},
  ...COMPONENT_ORDER.map((k) => ({id: `c_${k}`, comp: k, label: COMPONENT_LABEL[k] || k, num: true,
    sort: (r) => (isNum(r.components && r.components[k]) ? r.components[k] : -1)})),
  {id: "source", label: "Source", sort: (r) => r.source || ""},
  {id: "pool", label: "Pool", sort: (r) => r.pool || "Z"},
  {id: "reason", label: "Reason"},
  {id: "note", label: "Note"},
  {id: "remove", label: "Remove", sr: true},
];

/** Sort peer rows by a PEER_COLS key: desc puts the largest first; missing values sink. */
export function sortPeerRows(rows, sort) {
  const list = (rows || []).slice();
  if (!sort || !sort.key) return list;
  const col = PEER_COLS.find((c) => c.id === sort.key);
  if (!col || !col.sort) return list;
  const dir = sort.dir === "asc" ? 1 : -1;
  return list.sort((a, b) => {
    const x = col.sort(a), y = col.sort(b);
    if (typeof x === "number" && typeof y === "number") return (x - y) * dir || a.ticker.localeCompare(b.ticker);
    return String(x).localeCompare(String(y)) * dir || a.ticker.localeCompare(b.ticker);
  });
}

export function mountPeerPanel(root, ctx) {
  // 12.6: a drawer on the right, drawn only while it is open. The table behind stays live, so
  // excluding a peer here shows in the statistics at once.
  let wasOpen = false;
  let opener = null;
  const m = createMount(root, ctx, "pn-peers-root", {
    name: "Peer selection",
    local: () => ({selected: new Set(), sort: null, active: {r: 1, c: 0}, query: "", saveName: "", subName: "",
      renaming: null, cohortsOpen: false}),
    sig: (v, local) => {
      const st = stateOf(ctx);
      return [v.peers, v.focal && v.focal.ticker, v.primary && [v.primary.colId, v.primary.label], v.sectionErrors && v.sectionErrors.peers,
        [...local.selected], local.sort, local.renaming, st.cohorts];
    },
    build: (root, view, local, api) => {
      if (!(view.peers && view.peers.open)) return;
      const titleId = uid("pnpeerd");
      const drawer = h("aside", {class: "u-drawer pn-peers-drawer", role: "dialog", "aria-modal": "false", "aria-labelledby": titleId});
      drawer.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); e.stopPropagation(); close(); }
      });
      const closeBtn = h("button", {type: "button", class: "u-btn icon pn-close", "data-key": "peers-close", "aria-label": "Close edit peers", text: "\u2715"});
      closeBtn.addEventListener("click", close);
      drawer.appendChild(h("div", {class: "pn-drawer-head"},
        h("h2", {class: "u-section-title pn-peers-title", id: titleId, tabindex: "-1", "data-key": "peers-title", text: view.peers.title || "Edit peers"}),
        closeBtn));
      const body = h("div", {class: "pn-peers pn-peers-body", "data-scroll-key": "peers-body"});
      drawer.appendChild(body);
      root.appendChild(drawer);
      buildPeers(body, view, ctx, local, api);
    },
    after: (root, view, local) => {
      const open = !!(view.peers && view.peers.open);
      const doc = root.ownerDocument;
      if (open) {
        applyRoving(root, local);
        if (!wasOpen) {
          opener = captureOpener(doc, root) || opener;
          const target = view.peers.search ? root.querySelector('[data-key="peer-search"]') : root.querySelector(".pn-peers-title");
          if (target) { try { target.focus({preventScroll: true}); } catch (e) { target.focus(); } }
        }
      } else if (wasOpen) {
        returnFocus(doc, opener);
        opener = null;
      }
      wasOpen = open;
    },
  });
  function close() {
    if (ctx && typeof ctx.closePeers === "function") ctx.closePeers();
    else dispatch(ctx, {type: "CLOSE_PEERS"});
  }
  m.focusSearch = () => {
    const el = root.querySelector('[data-key="peer-search"]');
    if (el) { el.focus(); if (el.scrollIntoView) el.scrollIntoView({block: "nearest"}); }
  };
  return m;
}

function buildPeers(root, view, ctx, local, api) {
  const P = view.peers;
  const T = view.focal ? view.focal.ticker : "";
  const titleId = uid("pnpeer");
  if (!P) {
    root.appendChild(sectionError(view, "peers", "Peer selection"));
    return;
  }
  const descHost = hiddenHost(root);
  const setChip = chip((P.setLabel && P.setLabel.full) || "", "neutral", {class: "pn-setchip"});
  root.appendChild(h("div", {class: "pn-head pn-peers-head", id: titleId},
    chip(`${P.n} ${P.n === 1 ? "peer" : "peers"}`, "neutral"), chip(`${P.k} in statistics`, "neutral"), setChip));
  // Prune the selection to rows still in the set.
  const inSet = new Set((P.rows || []).map((r) => r.ticker));
  for (const t of [...local.selected]) if (!inSet.has(t)) local.selected.delete(t);

  // 1. Warnings.
  const warn = [P.mixed, P.weak].filter(Boolean);
  if (warn.length) {
    root.appendChild(h("div", {class: "pn-warns"}, warn.map((w) => stateBlock(w, (a) => runStateAction(ctx, a)))));
  }

  // 2. Relevance grid.
  root.appendChild(peerGrid(view, ctx, local, api, descHost));

  // Bulk actions on the selection.
  const nSel = local.selected.size;
  const bulk = h("div", {class: "pn-bulk", role: "group", "aria-label": "Selected rows"},
    h("span", {class: "u-meta", text: nSel ? `${nSel} selected` : "Select rows to act on several peers"}));
  const exSel = btn("Exclude selected", {"data-key": "bulk-exclude", disabled: !nSel}, () => {
    const rows = (P.rows || []).filter((r) => local.selected.has(r.ticker) && r.included);
    for (const r of rows) dispatch(ctx, {type: "TOGGLE_EXCLUDE", ticker: r.ticker});
    announce(ctx, `Excluded ${rows.length} from statistics.`);
  });
  const inSel = btn("Include selected", {"data-key": "bulk-include", disabled: !nSel}, () => {
    const rows = (P.rows || []).filter((r) => local.selected.has(r.ticker) && !r.included);
    for (const r of rows) dispatch(ctx, {type: "TOGGLE_EXCLUDE", ticker: r.ticker});
    announce(ctx, `Included ${rows.length} in statistics.`);
  });
  bulk.append(exSel, inSel);
  root.appendChild(bulk);

  // 3. Candidates and search.
  root.appendChild(candidatesBlock(view, ctx, local, descHost));

  // 4 to 8 in a tool grid.
  const tools = h("div", {class: "pn-tools"});
  root.appendChild(tools);
  tools.appendChild(savedSetsBlock(view, ctx, local));
  tools.appendChild(subgroupsBlock(view, ctx, local, api, descHost));
  tools.appendChild(cohortsBlock(view, ctx, local, descHost));
  tools.appendChild(outliersBlock(view, ctx));
  void T;
}

function runStateAction(ctx, a) {
  if (!a) return;
  if (a.command === "peers.restore") dispatch(ctx, {type: "RESTORE_SYSTEM", now: nowMs()});
  else if (a.command === "peers.addAdjacent") dispatch(ctx, {type: "ADD_POOL_C"});
  else if (a.type) dispatch(ctx, a);
}

function levelBars(level) {
  const n = level === "high" ? 3 : level === "medium" ? 2 : level === "low" ? 1 : 0;
  return h("span", {class: "pn-bars", "aria-hidden": "true"}, [0, 1, 2].map((i) => h("span", {class: `pn-bar${i < n ? " on" : ""}`})));
}

function peerGrid(view, ctx, local, api, descHost) {
  const P = view.peers;
  const rows = sortPeerRows(P.rows || [], local.sort);
  const wrap = h("div", {class: "pn-grid-wrap", "data-scroll-key": "peer-grid"});
  const table = h("table", {class: "pn-grid", role: "grid", "aria-label": "Peers and their relevance", "aria-rowcount": String(rows.length + 1)});
  wrap.appendChild(table);
  table.appendChild(h("caption", {class: "u-sr", text: `Peers of ${view.focal ? view.focal.ticker : ""}: ${P.n} in the set, ${P.k} in statistics. Arrow keys move between cells; Space or Enter uses the control in a cell.`}));
  // Header.
  const thead = h("thead");
  const hr = h("tr", {role: "row"});
  thead.appendChild(hr);
  const allSel = rows.length > 0 && rows.every((r) => local.selected.has(r.ticker));
  PEER_COLS.forEach((c, ci) => {
    const th = h("th", {role: "columnheader", scope: "col", class: `pn-g-${c.id}${c.num ? " num" : ""}`, "data-r": "0", "data-c": String(ci),
      "data-key": `pg-h-${c.id}`, tabindex: "-1"});
    if (c.id === "sel") {
      const cb = h("input", {type: "checkbox", tabindex: "-1", "aria-label": "Select all visible peers", checked: allSel});
      cb.addEventListener("change", () => {
        if (cb.checked) rows.forEach((r) => local.selected.add(r.ticker)); else local.selected.clear();
        api.rerender();
      });
      th.appendChild(cb);
    } else if (c.sort) {
      const dir = local.sort && local.sort.key === c.id ? local.sort.dir : null;
      th.setAttribute("aria-sort", dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none");
      const b = h("button", {type: "button", tabindex: "-1", class: "pn-sort"}, c.label,
        h("span", {class: "pn-sort-dir", "aria-hidden": "true", text: dir === "asc" ? " ▴" : dir === "desc" ? " ▾" : ""}));
      b.addEventListener("click", () => {
        const cur = local.sort && local.sort.key === c.id ? local.sort.dir : null;
        local.sort = cur === null ? {key: c.id, dir: "desc"} : cur === "desc" ? {key: c.id, dir: "asc"} : null;
        announce(ctx, local.sort ? `Sorted by ${lcfirst(c.label)}, ${local.sort.dir === "desc" ? "descending" : "ascending"}.` : "Sort cleared.");
        api.rerender();
      });
      th.appendChild(b);
    } else {
      th.appendChild(c.sr ? h("span", {class: "u-sr", text: c.label}) : document.createTextNode(c.label));
    }
    hr.appendChild(th);
  });
  table.appendChild(thead);
  // Body.
  const tbody = h("tbody");
  table.appendChild(tbody);
  if (!rows.length) {
    tbody.appendChild(h("tr", {}, h("td", {colspan: String(PEER_COLS.length), class: "pn-empty"},
      stateBlock(STATE_COPY.no_peers ? {severity: "amber", title: STATE_COPY.no_peers.title, detail: STATE_COPY.no_peers.detail,
        action: STATE_COPY.no_peers.action} : null, (a) => runStateAction(ctx, a)))));
  }
  rows.forEach((r, ri) => {
    const tr = h("tr", {role: "row", class: `${r.included ? "" : "is-excluded"}${local.selected.has(r.ticker) ? " is-selected" : ""}`, "aria-selected": String(local.selected.has(r.ticker))});
    PEER_COLS.forEach((c, ci) => {
      const td = h("td", {role: "gridcell", class: `pn-g-${c.id}${c.num ? " num" : ""}`, "data-r": String(ri + 1), "data-c": String(ci),
        "data-key": `pg-${r.ticker}-${c.id}`, tabindex: "-1"});
      fillPeerCell(td, c, r, view, ctx, local, api, descHost);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.addEventListener("keydown", (e) => gridKey(e, table, local, ctx));
  table.addEventListener("focusin", (e) => {
    const cell = e.target.closest && e.target.closest("[data-r]");
    if (!cell || !table.contains(cell)) return;
    local.active = {r: Number(cell.getAttribute("data-r")), c: Number(cell.getAttribute("data-c"))};
    for (const el of table.querySelectorAll('[data-r][tabindex="0"]')) if (el !== cell) el.setAttribute("tabindex", "-1");
    cell.setAttribute("tabindex", "0");
  });
  return wrap;
}

function fillPeerCell(td, c, r, view, ctx, local, api, descHost) {
  switch (c.id) {
    case "sel": {
      const cb = h("input", {type: "checkbox", tabindex: "-1", "aria-label": `Select ${r.ticker}`, checked: local.selected.has(r.ticker)});
      cb.addEventListener("change", () => {
        if (cb.checked) local.selected.add(r.ticker); else local.selected.delete(r.ticker);
        api.rerender();
      });
      td.appendChild(cb);
      break;
    }
    case "stats": {
      const cb = h("input", {type: "checkbox", tabindex: "-1", "aria-label": `${r.ticker} in statistics`, checked: !!r.included});
      cb.addEventListener("change", () => {
        dispatch(ctx, {type: "TOGGLE_EXCLUDE", ticker: r.ticker});
        announce(ctx, r.included ? `${r.ticker} excluded from statistics. Still shown.` : `${r.ticker} included in statistics.`);
      });
      td.appendChild(cb);
      if (r.included && !r.inStats) {
        const m = h("span", {class: "u-marker", text: "g"});
        bindTip(ctx, m, "Included, but outside the statistics group in use.");
        td.appendChild(m);
      }
      break;
    }
    case "ticker": {
      const b = h("button", {type: "button", tabindex: "-1", class: "u-ticker pn-linkish", text: r.ticker, "aria-label": `Open ${r.ticker} details`});
      b.addEventListener("click", () => openDetail(ctx, r.ticker));
      td.appendChild(b);
      break;
    }
    case "name": td.appendChild(h("span", {class: "pn-ellipsis", title: r.name, text: r.name})); break;
    case "relevance": {
      const rel = r.relevance;
      td.appendChild(h("span", {class: "u-num", text: rel ? String(rel.score) : NULL_GLYPH}));
      td.appendChild(levelBars(rel && rel.level));
      const lines = COMPONENT_ORDER.map((k) => `${COMPONENT_LABEL[k]}: ${isNum(r.components && r.components[k]) ? r.components[k] + "%" : "not scored"}`);
      if (rel) bindTip(ctx, td, {title: `Relevance ${rel.score} of 100, ${rel.level}`, body: r.reason || "", lines});
      break;
    }
    case "source": td.textContent = r.source || NULL_GLYPH; break;
    case "pool": td.appendChild(h("span", {class: "u-num", text: r.pool || NULL_GLYPH})); break;
    case "reason": td.appendChild(h("span", {class: "pn-ellipsis pn-reason", title: r.reason || "", text: r.reason || NULL_GLYPH})); break;
    case "note": {
      const inp = h("input", {type: "text", tabindex: "-1", class: "u-input pn-note-input", "data-key": `pg-note-${r.ticker}`,
        "aria-label": `Note on including ${r.ticker}`, value: r.note || "", placeholder: "Why included"});
      let orig = r.note || "";
      const save = () => {
        if (inp.value === orig) return;
        orig = inp.value;
        inp.removeAttribute("data-dirty");
        dispatch(ctx, {type: "SET_PEER_NOTE", ticker: r.ticker, text: inp.value, now: nowMs()});
        announce(ctx, `Note on ${r.ticker} saved. ${storageOk(ctx) ? SAVED_HERE : STATE_COPY.storage_unavailable.detail}`);
      };
      inp.addEventListener("input", () => inp.setAttribute("data-dirty", "1"));
      inp.addEventListener("blur", () => setTimeout(save, 0));
      inp.__save = save;
      inp.__orig = () => orig;
      td.appendChild(inp);
      break;
    }
    case "remove": {
      const b = h("button", {type: "button", tabindex: "-1", class: "u-btn icon pn-remove", "aria-label": `Remove ${r.ticker} from peers`, text: "✕"});
      b.addEventListener("click", () => {
        dispatch(ctx, {type: "REMOVE_PEER", ticker: r.ticker, now: nowMs()});
        announce(ctx, `Removed ${r.ticker} from peers.`);
      });
      td.appendChild(b);
      break;
    }
    default: {
      if (c.comp) {
        const v = r.components ? r.components[c.comp] : null;
        td.appendChild(h("span", {class: isNum(v) ? "u-num" : "u-null", text: isNum(v) ? `${v}%` : NULL_GLYPH}));
        if (!isNum(v)) {
          const miss = (r.missing || []).find((x) => x.id === c.comp);
          bindTip(ctx, td, miss ? miss.text || `not scored: ${miss.reason}` : "Not scored: no data for one of the two companies.");
        }
      }
    }
  }
  void view; void descHost;
}

/** Roving focus: one tab stop in the grid, restored to the last active cell. */
function applyRoving(root, local) {
  const table = root.querySelector(".pn-grid");
  if (!table) return;
  const cells = table.querySelectorAll("[data-r]");
  let target = null;
  for (const el of cells) {
    if (Number(el.getAttribute("data-r")) === local.active.r && Number(el.getAttribute("data-c")) === local.active.c) target = el;
    if (el.getAttribute("tabindex") !== "-1" && document.activeElement !== el) el.setAttribute("tabindex", "-1");
  }
  if (!target) target = table.querySelector('[data-r="1"][data-c="2"]') || table.querySelector('[data-r="0"][data-c="2"]');
  if (target) target.setAttribute("tabindex", "0");
}

function gridKey(e, table, local, ctx) {
  const t = e.target;
  const inNote = t && t.classList && t.classList.contains("pn-note-input");
  const cellOf = (el) => (el && el.closest ? el.closest("[data-r]") : null);
  if (inNote) {
    if (e.key === "Enter" || e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === "Escape") { t.value = t.__orig ? t.__orig() : t.value; t.removeAttribute("data-dirty"); }
      // Focus the cell first: the input's blur saves, and the rebuild then restores focus to the cell.
      const cell = cellOf(t);
      if (cell) cell.focus();
      if (e.key === "Enter" && t.__save) t.__save();
    }
    return;
  }
  const cell = cellOf(t);
  if (!cell || !table.contains(cell)) return;
  const r = Number(cell.getAttribute("data-r")), c = Number(cell.getAttribute("data-c"));
  const maxR = table.querySelectorAll("tbody tr[role='row']").length;
  const maxC = PEER_COLS.length - 1;
  let nr = r, nc = c;
  switch (e.key) {
    case "ArrowUp": nr = Math.max(0, r - 1); break;
    case "ArrowDown": nr = Math.min(maxR, r + 1); break;
    case "ArrowLeft": nc = Math.max(0, c - 1); break;
    case "ArrowRight": nc = Math.min(maxC, c + 1); break;
    case "Home": nc = 0; if (e.ctrlKey || e.metaKey) nr = 0; break;
    case "End": nc = maxC; if (e.ctrlKey || e.metaKey) nr = maxR; break;
    case "PageUp": nr = Math.max(0, r - 10); break;
    case "PageDown": nr = Math.min(maxR, r + 10); break;
    case "Enter": case " ": {
      const ctl = cell.querySelector("input, button");
      if (!ctl) return;
      e.preventDefault();
      e.stopPropagation();
      if (ctl.tagName === "INPUT" && ctl.type === "text") { ctl.focus(); ctl.select(); }
      else ctl.click();
      return;
    }
    default: return;
  }
  e.preventDefault();
  e.stopPropagation();
  const next = table.querySelector(`[data-r="${nr}"][data-c="${nc}"]`);
  if (next) {
    local.active = {r: nr, c: nc};
    cell.setAttribute("tabindex", "-1");
    next.setAttribute("tabindex", "0");
    next.focus();
    if (next.scrollIntoView) next.scrollIntoView({block: "nearest", inline: "nearest"});
  }
  void ctx;
}

/** All companies that can be added, from core's palette entries (the view carries no raw list). */
function addableCompanies(view, ctx) {
  let extras = [];
  try { extras = paletteExtras(view, stateOf(ctx)) || []; } catch (e) { extras = []; }
  return extras.filter((x) => x && typeof x.id === "string" && x.id.startsWith("add:")).map((x) => {
    const ticker = x.id.slice(4);
    const name = String(x.label || "").replace(/^Add peer\s+/, "").slice(ticker.length).trim();
    return {ticker, name};
  });
}

/** Search over ticker and name: prefix on the ticker ranks first, then word starts in the name. */
export function searchCompanies(list, query, limit = 10) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return [];
  const scored = [];
  for (const c of list || []) {
    const t = String(c.ticker || "").toLowerCase(), n = String(c.name || "").toLowerCase();
    let s = 0;
    if (t === q) s = 5; else if (t.startsWith(q)) s = 4;
    else if (n.startsWith(q)) s = 3; else if (n.split(/[\s,.&-]+/).some((w) => w.startsWith(q))) s = 2;
    else if (t.includes(q) || n.includes(q)) s = 1;
    if (s) scored.push({c, s});
  }
  return scored.sort((a, b) => b.s - a.s || a.c.ticker.localeCompare(b.c.ticker)).slice(0, limit).map((x) => x.c);
}

function candidatesBlock(view, ctx, local, descHost) {
  const P = view.peers;
  const box = sub("Other companies by relevance");
  box.classList.add("pn-cands");
  // Search across the universe.
  const sid = uid("pnsearch");
  const results = h("ul", {class: "pn-search-results", "aria-live": "polite", id: `${sid}-r`});
  const input = h("input", {type: "search", id: sid, class: "u-input pn-search", "data-key": "peer-search", autocomplete: "off",
    placeholder: "Ticker or name", "aria-controls": `${sid}-r`, value: local.query || ""});
  const all = addableCompanies(view, ctx);
  const byT = new Map((P.candidates || []).map((c) => [c.ticker, c]));
  const drawResults = () => {
    results.textContent = "";
    const q = local.query || "";
    if (!q.trim()) return;
    const hits = searchCompanies(all, q, 10);
    if (!hits.length) { results.appendChild(h("li", {class: "pn-empty", text: `No company outside the set matches "${q.trim()}".`})); return; }
    for (const c of hits) {
      const cand = byT.get(c.ticker);
      results.appendChild(h("li", {class: "pn-cand"},
        h("span", {class: "u-ticker", text: c.ticker}), h("span", {class: "pn-ellipsis", text: c.name}),
        cand ? h("span", {class: "u-meta", text: `relevance ${cand.relevance ? cand.relevance.score : NULL_GLYPH}`}) : h("span"),
        addBtn(ctx, c.ticker, `search-add-${c.ticker}`)));
    }
  };
  input.addEventListener("input", () => { local.query = input.value; input.setAttribute("data-dirty", "1"); drawResults(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && input.value) { e.preventDefault(); e.stopPropagation(); input.value = ""; local.query = ""; drawResults(); }
    else if (e.key === "Enter") {
      const first = results.querySelector("button");
      if (first) { e.preventDefault(); first.click(); }
    }
  });
  box.appendChild(h("div", {class: "pn-search-row"},
    h("label", {class: "u-label", for: sid, text: "Add any of the 70 companies (A)"}), input));
  box.appendChild(results);
  drawResults();
  // Top 20 by relevance.
  const list = h("ul", {class: "pn-cand-list", "data-scroll-key": "peer-cands"});
  for (const c of P.candidates || []) {
    const li = h("li", {class: "pn-cand"},
      h("span", {class: "u-ticker", text: c.ticker}),
      h("span", {class: "pn-ellipsis", title: c.name, text: c.name}),
      h("span", {class: "u-meta pn-cand-sub", text: `${c.subsector}${c.stage === "clinical" ? ", clinical" : ""}`}),
      h("span", {class: "pn-cand-rel"}, h("span", {class: "u-num", text: c.relevance ? String(c.relevance.score) : NULL_GLYPH}), levelBars(c.relevance && c.relevance.level)),
      addBtn(ctx, c.ticker, `cand-add-${c.ticker}`));
    if (c.relevance) {
      const lines = COMPONENT_ORDER.map((k) => `${COMPONENT_LABEL[k]}: ${isNum(c.components && c.components[k]) ? c.components[k] + "%" : "not scored"}`);
      bindTip(ctx, li.querySelector(".pn-cand-rel"), {title: `Relevance ${c.relevance.score} of 100`, lines}, descHost);
      li.querySelector(".pn-cand-rel").setAttribute("tabindex", "0");
    }
    list.appendChild(li);
  }
  if (!(P.candidates || []).length) list.appendChild(h("li", {class: "pn-empty", text: "Every other company is in the set."}));
  box.appendChild(list);
  return box;
}

function addBtn(ctx, ticker, key) {
  return btn("Add", {"data-key": key, "aria-label": `Add ${ticker} to peers`, cls: "pn-add"}, () => {
    dispatch(ctx, {type: "ADD_PEER", ticker});
    announce(ctx, `Added ${ticker} to peers.`);
  });
}

function savedSetsBlock(view, ctx, local) {
  const P = view.peers;
  const box = sub("Saved peer sets");
  const ul = h("ul", {class: "pn-sets"});
  for (const s of P.savedSets || []) {
    ul.appendChild(h("li", {class: `pn-set${s.active ? " is-active" : ""}`},
      h("span", {class: "pn-set-name"}, s.active ? h("span", {class: "u-dir active", "aria-hidden": "true", text: "● "}) : null, `'${s.name}'`),
      h("span", {class: "u-meta", text: `${s.n} ${s.n === 1 ? "company" : "companies"}${s.createdText ? `, ${s.createdText}` : ""}${s.active ? ", in use" : ""}`}),
      btn("Load", {"data-key": `set-load-${s.name}`, "aria-label": `Load peer set '${s.name}'`, disabled: s.active && !isEdited(ctx)}, () => {
        dispatch(ctx, {type: "LOAD_SET", name: s.name});
        announce(ctx, `Loaded peer set '${s.name}'.`);
      }),
      btn("Delete", {"data-key": `set-del-${s.name}`, "aria-label": `Delete peer set '${s.name}'`}, () => {
        dispatch(ctx, {type: "DELETE_SET", name: s.name, now: nowMs()});
        announce(ctx, `Deleted peer set '${s.name}'. Undo with the toast or Cmd Z.`);
      })));
  }
  if (!(P.savedSets || []).length) ul.appendChild(h("li", {class: "pn-empty", text: "No saved sets yet."}));
  box.appendChild(ul);
  const nid = uid("pnset");
  const name = h("input", {type: "text", id: nid, class: "u-input pn-name", "data-key": "set-name", placeholder: "Name", value: local.saveName || "", maxlength: "40"});
  const save = btn("Save current set", {"data-key": "set-save", cls: "primary", disabled: !String(local.saveName || "").trim()}, () => {
    const n = String(name.value || "").trim();
    if (!n) return;
    dispatch(ctx, {type: "SAVE_SET", name: n, now: nowMs()});
    local.saveName = "";
    announce(ctx, `Saved the peer set as '${n}'. ${storageOk(ctx) ? SAVED_HERE : STATE_COPY.storage_unavailable.detail}`);
  });
  const exists = () => (P.savedSets || []).some((s) => s.name === String(name.value || "").trim());
  const hint = h("span", {class: "u-meta pn-name-hint", text: exists() ? "Replaces the saved set of the same name." : ""});
  name.addEventListener("input", () => {
    local.saveName = name.value;
    name.setAttribute("data-dirty", "1");
    save.disabled = !name.value.trim();
    hint.textContent = exists() ? "Replaces the saved set of the same name." : "";
  });
  name.addEventListener("keydown", (e) => { if (e.key === "Enter" && name.value.trim()) { e.preventDefault(); save.click(); } });
  box.appendChild(h("div", {class: "pn-inline-form"}, h("label", {class: "u-sr", for: nid, text: "Name of the peer set"}), name, save, hint));
  box.appendChild(storageNote(ctx));
  return box;
}

function isEdited(ctx) {
  const st = stateOf(ctx);
  const ed = st.peerEdits && st.focal ? st.peerEdits[st.focal] : null;
  return !!(ed && ((ed.added || []).length || (ed.removed || []).length));
}

function subgroupsBlock(view, ctx, local, api, descHost) {
  const P = view.peers;
  const box = sub("Subgroups");
  const inUse = P.statsGroup || "all";
  const ul = h("ul", {class: "pn-subgroups"});
  const allLi = h("li", {class: `pn-subgroup${inUse === "all" ? " is-active" : ""}`},
    h("span", {class: "pn-set-name", text: "All peers"}), h("span", {class: "u-meta", text: `${P.n} peers`}),
    btn(inUse === "all" ? "In use" : "Use for statistics", {"data-key": "sg-use-all", "aria-pressed": String(inUse === "all")}, () => {
      if (inUse !== "all") { dispatch(ctx, {type: "SET_STATS_GROUP", group: "all"}); announce(ctx, "Statistics over all peers."); }
    }));
  ul.appendChild(allLi);
  for (const g of P.subgroups || []) {
    const active = g.active || inUse === g.name;
    const nameEl = h("span", {class: "pn-set-name", tabindex: "0"}, g.name, g.system ? h("span", {class: "u-meta", text: " system"}) : null);
    bindTip(ctx, nameEl, g.tooltip || g.name, descHost);
    const li = h("li", {class: `pn-subgroup${active ? " is-active" : ""}`}, nameEl,
      h("span", {class: "u-meta", text: `${(g.tickers || []).length} peers${(g.leftOut || []).length ? `, ${g.leftOut.length} left out` : ""}`}));
    const use = btn(active ? "In use" : "Use for statistics", {"data-key": `sg-use-${g.name}`, "aria-pressed": String(active),
      disabled: !(g.tickers || []).length && !active}, () => {
      if (!active) { dispatch(ctx, {type: "SET_STATS_GROUP", group: g.name}); announce(ctx, `Statistics over the ${g.name} subgroup.`); }
    });
    if (!(g.tickers || []).length) bindTip(ctx, use, "No peer in the set belongs to this subgroup.");
    li.appendChild(use);
    if (!g.system) {
      if (local.renaming === g.name) {
        const inp = h("input", {type: "text", class: "u-input pn-name", "data-key": `sg-rename-${g.name}`, value: g.name, "aria-label": `New name for ${g.name}`, maxlength: "40"});
        const commit = () => {
          const n = inp.value.trim();
          local.renaming = null;
          if (n && n !== g.name) renameSubgroup(ctx, g, n, active);
          api.rerender();
        };
        inp.addEventListener("keydown", (e) => {
          if (e.key === "Enter") { e.preventDefault(); commit(); }
          else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); local.renaming = null; api.rerender(); }
        });
        li.appendChild(inp);
        li.appendChild(btn("Save", {"data-key": `sg-rename-save-${g.name}`}, commit));
      } else {
        li.appendChild(btn("Rename", {"data-key": `sg-rename-btn-${g.name}`, "aria-label": `Rename subgroup ${g.name}`}, () => { local.renaming = g.name; api.rerender(); }));
      }
      li.appendChild(btn("Delete", {"data-key": `sg-del-${g.name}`, "aria-label": `Delete subgroup ${g.name}`}, () => {
        dispatch(ctx, {type: "DELETE_SUBGROUP", name: g.name, now: nowMs()});
        announce(ctx, `Deleted subgroup '${g.name}'. Undo with the toast or Cmd Z.`);
      }));
    }
    ul.appendChild(li);
  }
  box.appendChild(ul);
  const nSel = local.selected.size;
  const nid = uid("pnsg");
  const name = h("input", {type: "text", id: nid, class: "u-input pn-name", "data-key": "sg-name", placeholder: "Subgroup name", value: local.subName || "", maxlength: "40"});
  const make = btn("Make subgroup from selected", {"data-key": "sg-make", disabled: nSel < 2 || !String(local.subName || "").trim()}, () => {
    const n = name.value.trim();
    if (!n || nSel < 2) return;
    dispatch(ctx, {type: "SET_SUBGROUP", name: n, tickers: [...local.selected]});
    local.subName = "";
    announce(ctx, `Subgroup '${n}' made from ${nSel} peers. ${storageOk(ctx) ? SAVED_HERE : ""}`);
  });
  if (nSel < 2) bindTip(ctx, make, "Select 2 or more peers in the table above first.", descHost);
  name.addEventListener("input", () => {
    local.subName = name.value;
    name.setAttribute("data-dirty", "1");
    make.disabled = nSel < 2 || !name.value.trim();
  });
  name.addEventListener("keydown", (e) => { if (e.key === "Enter" && !make.disabled) { e.preventDefault(); make.click(); } });
  box.appendChild(h("div", {class: "pn-inline-form"}, h("label", {class: "u-sr", for: nid, text: "Name of the new subgroup"}), name, make,
    h("span", {class: "u-meta", text: `${nSel} selected`})));
  return box;
}

function renameSubgroup(ctx, g, n, wasActive) {
  const t = nowMs();
  dispatch(ctx, {type: "SET_SUBGROUP", name: n, tickers: (g.tickers || []).slice()});
  dispatch(ctx, {type: "DELETE_SUBGROUP", name: g.name, now: t});
  // A rename is not a deletion: clear the undo record the delete step left behind.
  dispatch(ctx, {type: "EXPIRE_UNDO", now: t + UNDO_MS});
  if (wasActive) dispatch(ctx, {type: "SET_STATS_GROUP", group: n});
  announce(ctx, `Subgroup renamed to '${n}'.`);
}

function cohortsBlock(view, ctx, local, descHost) {
  const P = view.peers;
  const box = sub("Compare cohorts");
  const st = stateOf(ctx);
  const chosen = Array.isArray(st.cohorts) ? st.cohorts.slice() : (P.cohorts || []).map((c) => c.id);
  const fs = h("fieldset", {class: "pn-cohort-pick"}, h("legend", {class: "u-label", text: "Pick up to 3; the dot plot shows one lane each"}));
  for (const o of P.cohortOptions || []) {
    const id = uid("pnco");
    const on = chosen.includes(o.id);
    const cb = h("input", {type: "checkbox", id, "data-key": `co-${o.id}`, checked: on, disabled: !on && chosen.length >= 3});
    cb.addEventListener("change", () => {
      const next = cb.checked ? chosen.concat([o.id]).slice(0, 3) : chosen.filter((x) => x !== o.id);
      dispatch(ctx, {type: "SET_COHORTS", ids: next});
      announce(ctx, next.length ? `Comparing ${next.length} ${next.length === 1 ? "cohort" : "cohorts"}.` : "Cohort comparison off.");
    });
    const lab = h("label", {class: "pn-check", for: id}, cb, h("span", {text: o.label}));
    if (!on && chosen.length >= 3) bindTip(ctx, lab, "Three cohorts at most. Clear one first.", descHost);
    fs.appendChild(lab);
  }
  box.appendChild(fs);
  const T = view.focal ? view.focal.ticker : "";
  const metric = view.primary && view.primary.label ? view.primary.label : "the primary metric";
  if ((P.cohorts || []).length) {
    const t = h("table", {class: "pn-cohorts"},
      h("caption", {class: "u-meta", text: `On ${metric}, focal company excluded from every cohort.`}),
      h("thead", {}, h("tr", {}, ["Cohort", "n with a value", "Median", "Interquartile range", `${T} premium or discount`, `${T} percentile`]
        .map((x, i) => h("th", {scope: "col", class: i ? "num" : "", text: x})))));
    const tb = h("tbody");
    for (const c of P.cohorts) {
      const prem = h("td", {class: "num"}, h("span", {class: c.text && c.text.premium !== NULL_GLYPH ? "u-num" : "u-null", text: (c.text && c.text.premium) || NULL_GLYPH}));
      if (!isNum(c.premium)) bindTip(ctx, prem, c.n < 5 ? `Only ${c.n} values: no premium or discount is stated under 5.` : "No premium on this metric.");
      tb.appendChild(h("tr", {}, h("th", {scope: "row", text: c.label}), h("td", {class: "num u-num", text: String(c.n)}),
        h("td", {class: "num u-num", text: (c.text && c.text.median) || NULL_GLYPH}),
        h("td", {class: "num u-num", text: (c.text && c.text.iqr) || NULL_GLYPH}), prem,
        h("td", {class: "num u-num", text: c.text && c.text.pct !== NULL_GLYPH ? c.text.pct : NULL_GLYPH})));
    }
    t.appendChild(tb);
    box.appendChild(h("div", {class: "pn-scroll-x", "data-scroll-key": "cohorts"}, t));
  } else {
    box.appendChild(h("p", {class: "pn-empty", text: "No cohort chosen. The dot plot shows the peer set alone."}));
  }
  return box;
}

function outliersBlock(view, ctx) {
  const P = view.peers;
  const box = sub("Outliers and the system set");
  const name = uid("pnout");
  const fs = h("fieldset", {class: "pn-radios"}, h("legend", {class: "u-sr", text: "Outliers in statistics"}));
  for (const o of [{id: "include", label: "Statistics with outliers"}, {id: "exclude", label: "Statistics without outliers"}]) {
    const id = uid("pnor");
    const r = h("input", {type: "radio", name, id, value: o.id, "data-key": `out-${o.id}`, checked: (P.outliers || "include") === o.id});
    r.addEventListener("change", () => {
      if (r.checked) { dispatch(ctx, {type: "SET_OUTLIERS", mode: o.id}); announce(ctx, `${o.label}.`); }
    });
    fs.appendChild(h("label", {class: "pn-check", for: id}, r, h("span", {text: o.label})));
  }
  fs.appendChild(h("p", {class: "u-meta", text: "U switches between the two. Outliers sit beyond 1.5 interquartile ranges from the quartiles."}));
  box.appendChild(fs);
  const edited = isEdited(ctx) || P.activeSet !== "system";
  const restore = btn("Restore system peers", {"data-key": "restore-system", disabled: !edited}, () => {
    dispatch(ctx, {type: "RESTORE_SYSTEM", now: nowMs()});
    announce(ctx, "Restored system peers. Undo with the toast or Cmd Z.");
  });
  if (!edited) bindTip(ctx, restore, "The system set is in use, unedited.");
  box.appendChild(h("div", {class: "pn-inline-form"}, restore));
  return box;
}

// ---------------------------------------------------------------------------------------------
// 6.3 Notes and data sources (mountNotesSources)
// ---------------------------------------------------------------------------------------------

export function mountNotesSources(root, ctx) {
  return createMount(root, ctx, "pn-notes", {
    name: "Notes and data sources",
    sig: (v) => {
      const st = stateOf(ctx);
      return [v.lineage, v.focal && v.focal.ticker, st.notes, v.peers && (v.peers.rows || []).map((r) => r.ticker)];
    },
    build: (root, view) => buildNotes(root, view, ctx),
  });
}

function buildNotes(root, view, ctx, inDrawer = false) {
  const L = view.lineage || {};
  const F = L.focal || {};
  const T = view.focal ? view.focal.ticker : "";
  const titleId = uid("pnnotes");
  if (!inDrawer) {
    root.appendChild(sectionHead("Notes and data sources", titleId,
      btn("Open methodology", {"data-key": "open-method", cls: "pn-open-method"}, () => openMethod(ctx, "stats"))));
  }
  const descHost = hiddenHost(root);
  const dl = h("table", {class: "pn-sources"}, h("caption", {class: "u-sr", text: "Data sources and timestamps"}));
  const tb = h("tbody");
  dl.appendChild(tb);
  const add = (label, value, detail, flag = false) => tb.appendChild(h("tr", {class: flag ? "is-flag" : ""},
    h("th", {scope: "row", text: label}),
    h("td", {class: "pn-src-val"}, flag ? h("span", {class: "u-marker amber", "aria-hidden": "true", text: "!"}) : null, value),
    h("td", {class: "pn-src-detail"}, detail || "")));
  const old = isNum(L.priceTradingDaysOld) && L.priceTradingDaysOld >= 1;
  add("Prices", `Close ${fmtDate(L.priceDate)}`,
    `${T} fetched ${dateTime(F.quote_fetched_at)}${old ? `; ${L.priceTradingDaysOld} trading ${L.priceTradingDaysOld === 1 ? "day" : "days"} old` : ""}`, old);
  add("Consensus", `Last checked ${fmtDate(F.consensus_checked_at)}`,
    `Nasdaq consensus; the revision record starts on ${fmtDate(L.consensusStarts)}`);
  add("Financials", `Latest period ${fmtDate(F.fy_period_end)}`,
    `${F.financials_source ? `Source ${F.financials_source.replace(/_/g, " ")}` : "Source not recorded"}; balance sheet ${fmtDate(F.balance_sheet_as_of)}`);
  const rates = L.rates || {};
  const rateText = ["EUR", "GBP", "CHF", "DKK"].filter((c) => isNum(rates[c])).map((c) => `${c} ${fmtNumber(rates[c], 4)}`).join(", ");
  add("FX", `${L.fxSource || "ECB reference rates"}, ${fmtDate(L.fxDate)}`, rateText ? `USD per unit: ${rateText}` : "No rates on file");
  const run = L.run || null;
  if (run) {
    const failed = run.failed_sources || [];
    // Amber only where a failure touches this view: the focal company, a peer in the set, or
    // the whole universe. Failures elsewhere are listed in neutral text (amber discipline, 9.1).
    const mine = new Set([T].concat(((view.peers && view.peers.rows) || []).map((r) => r.ticker)));
    const touches = (f) => !f.ticker || mine.has(f.ticker);
    add("Refresh run", `Run ${run.id}, ${run.status}`, `Started ${dateTime(run.started_at)}, finished ${dateTime(run.finished_at)}`,
      failed.some(touches));
    if (failed.length) {
      const bySrc = {};
      for (const f of failed) (bySrc[f.source] = bySrc[f.source] || []).push(f);
      for (const [src, fs] of Object.entries(bySrc)) {
        const hit = fs.filter(touches), rest = fs.filter((f) => !touches(f));
        if (hit.length) add("", `${sourceName(src)} failed`, `For ${hit.map((f) => f.ticker || "every company").join(", ")}. Their figures are from the previous successful fetch.`, true);
        if (rest.length) add("", `${sourceName(src)} failed`, `For ${rest.map((f) => f.ticker).join(", ")}, outside this peer set.`);
      }
    }
    if ((run.other_failures || []).length) {
      add("", "Other sources", `Errors this view does not read: ${run.other_failures.map(sourceName).join(", ")}.`);
    }
  } else {
    add("Refresh run", NULL_GLYPH, "No refresh run on file");
  }
  add("Model values", L.complete === false ? "Not computed" : "Computed",
    L.complete === false ? NA_TEXT.model_not_computed : "Fair values and pipeline values from the forecast models, marked M wherever shown.");
  add("This view", `Built ${dateTime(L.generatedAt)}`, `${(L.universe && L.universe.n) || NULL_GLYPH} companies read from the book`);
  if ((L.errors || []).length) {
    for (const e of L.errors) add("", `${e.ticker} failed`, `Calculation failed for ${e.ticker}: ${e.message}. Other rows are unaffected.`, true);
  }
  root.appendChild(h("div", {class: "pn-scroll-x", "data-scroll-key": "sources"}, dl));

  // Analyst notes kept in this browser.
  const st = stateOf(ctx);
  const notes = Object.entries(st.notes || {}).filter(([, n]) => n && n.text);
  const box = sub("Analyst notes");
  if (notes.length) {
    const ul = h("ul", {class: "pn-note-list"});
    for (const [t, n] of notes.sort((a, b) => String(b[1].updated || "").localeCompare(String(a[1].updated || "")))) {
      const open = h("button", {type: "button", class: "u-btn link u-ticker", "data-key": `note-open-${t}`, "aria-label": `Open ${t} details and its note`, text: t});
      open.addEventListener("click", () => openDetail(ctx, t));
      const text = n.text.length > 160 ? `${n.text.slice(0, 157).replace(/\s+\S*$/, "")}…` : n.text;
      ul.appendChild(h("li", {}, open, h("span", {class: "pn-note-text", text}), h("span", {class: "u-meta", text: `Saved ${dateTime(n.updated)}`})));
    }
    box.appendChild(ul);
  } else {
    box.appendChild(h("p", {class: "pn-empty", text: "No analyst notes yet. Add one in a company's side panel."}));
  }
  root.appendChild(box);
  // Storage notice.
  if (storageOk(ctx)) root.appendChild(h("p", {class: "u-meta pn-storage", text: STORAGE_LINE}));
  else root.appendChild(stateBlock({severity: "amber", title: STATE_COPY.storage_unavailable.title, detail: STATE_COPY.storage_unavailable.detail}));
  void descHost;
}

/** The control that opened a drawer or panel: the element and its data-key, so focus can go
 * back to it after a rebuild replaced the element. */
function captureOpener(doc, root) {
  const ae = doc.activeElement;
  if (!ae || ae === doc.body || root.contains(ae)) return null;
  return {el: ae, key: ae.getAttribute ? ae.getAttribute("data-key") : null, id: ae.id || null};
}
/** Focus back to the opener when closing left focus nowhere (the closed panel held it). A shell
 * that restores focus itself (ctx.closeDetail, ctx.closeMethod) wins: focus is then not on body. */
function returnFocus(doc, opener) {
  if (!opener) return;
  const ae = doc.activeElement;
  if (ae && ae !== doc.body) return;
  let el = opener.el && doc.contains(opener.el) ? opener.el : null;
  if (!el && opener.key) el = doc.querySelector(`[data-key="${String(opener.key).replace(/["\\]/g, "\\$&")}"]`);
  if (!el && opener.id) el = doc.getElementById(opener.id);
  if (el) { try { el.focus({preventScroll: false}); } catch (e) { el.focus(); } }
}

// ---------------------------------------------------------------------------------------------
// 6.3 Methodology drawer (mountMethod)
// ---------------------------------------------------------------------------------------------

const METHOD_ALIASES = {statistics: "stats", "peer-statistics": "stats", notmeaningful: "nm", not_meaningful: "nm",
  "not-meaningful": "nm", definition: "definitions", defs: "definitions"};

/**
 * Where an anchor points in the drawer: a section id ("confidence"), an alias, or a column
 * ("pe", "def:pe", "definition:pe", "col:pe") whose definition row is the target.
 */
export function methodTarget(anchor, sectionIds = []) {
  if (!anchor) return {section: sectionIds[0] || "stats", colId: null};
  const a = String(anchor);
  const m = /^(?:def|definition|col|column):(.+)$/.exec(a);
  const col = m ? m[1] : a;
  if (COLUMN_BY_ID[col]) return {section: "definitions", colId: col};
  const id = METHOD_ALIASES[a] || a;
  return {section: sectionIds.includes(id) ? id : (sectionIds[0] || "stats"), colId: null};
}

export function mountMethod(root, ctx) {
  let opener = null;
  let lastAnchor = null;
  const m = createMount(root, ctx, "pn-method-root", {
    name: "Methodology",
    sig: (v) => [v.method, v.conclusion && v.conclusion.confidence, v.primary && v.primary.reasonText,
      v.method && v.method.open ? [v.lineage, stateOf(ctx).notes] : null],
    build: (root, view) => {
      const open = view.method && view.method.open;
      if (!open) return;
      buildMethod(root, view, ctx, () => close());
    },
    after: (root, view) => {
      const open = view.method && view.method.open;
      const doc = root.ownerDocument;
      if (!open) {
        if (lastAnchor !== null) {
          lastAnchor = null;
          returnFocus(doc, opener);
          opener = null;
        }
        return;
      }
      const drawer = root.querySelector(".pn-method");
      if (!drawer) return;
      if (lastAnchor === null) {
        opener = captureOpener(doc, root) || opener;
      }
      if (open !== lastAnchor) {
        lastAnchor = open;
        const ids = ["sources"].concat(((view.method && view.method.sections) || []).map((s) => s.id));
        const tgt = methodTarget(open, ids);
        const el = tgt.colId ? drawer.querySelector(`[data-def="${tgt.colId}"]`) : drawer.querySelector(`[data-sec="${tgt.section}"]`);
        const title = drawer.querySelector(".pn-method-title");
        const body = drawer.querySelector(".pn-method-body");
        if (el && body) {
          for (const x of drawer.querySelectorAll(".is-target")) x.classList.remove("is-target");
          el.classList.add("is-target");
          body.scrollTop = Math.max(0, el.offsetTop - body.offsetTop - 8);
        }
        const focusEl = tgt.colId && el ? el : title;
        if (focusEl) { try { focusEl.focus({preventScroll: true}); } catch (e) { focusEl.focus(); } }
      }
    },
  });
  function close() {
    if (ctx && typeof ctx.closeMethod === "function") ctx.closeMethod();
    else dispatch(ctx, {type: "CLOSE_METHOD"});
  }
  return m;
}

function buildMethod(root, view, ctx, close) {
  const M = view.method || {sections: []};
  const titleId = uid("pnmeth");
  const drawer = h("aside", {class: "u-drawer pn-method", role: "dialog", "aria-modal": "false", "aria-labelledby": titleId});
  drawer.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
  });
  const closeBtn = h("button", {type: "button", class: "u-btn icon pn-close", "data-key": "method-close", "aria-label": "Close methodology", text: "✕"});
  closeBtn.addEventListener("click", close);
  drawer.appendChild(h("div", {class: "pn-drawer-head"},
    h("h2", {class: "u-section-title pn-method-title", id: titleId, tabindex: "-1", "data-key": "method-title", text: "Methodology"}), closeBtn));
  const nav = h("nav", {class: "pn-method-nav", "aria-label": "Methodology sections"});
  const body = h("div", {class: "pn-method-body", "data-scroll-key": "method-body"});
  const sections = [{id: "sources", title: "Sources", body: []}].concat((M.sections || []).filter((x) => x.id !== "sources"));
  for (const s of sections) {
    const b = h("button", {type: "button", class: "u-chip pn-method-link", "data-key": `method-nav-${s.id}`, text: s.title});
    b.addEventListener("click", () => {
      const el = body.querySelector(`[data-sec="${s.id}"]`);
      if (el) { body.scrollTop = Math.max(0, el.offsetTop - body.offsetTop - 8); const t = el.querySelector("h3"); if (t) t.focus(); }
    });
    nav.appendChild(b);
    const sec = h("section", {class: "pn-method-sec", "data-sec": s.id, id: `pn-method-${s.id}`},
      h("h3", {class: "pn-sub-title", tabindex: "-1", text: s.title}));
    for (const p of s.body || []) if (p) sec.appendChild(h("p", {class: "pn-method-p", text: p}));
    if (s.id === "sources") { const box = h("div", {class: "pn-notes pn-method-sources"}); buildNotes(box, view, ctx, true); sec.appendChild(box); }
    if (s.id === "confidence") sec.appendChild(confidencePoints(view));
    if (s.id === "definitions") sec.appendChild(definitionsList(s.items || []));
    body.appendChild(sec);
  }
  drawer.appendChild(nav);
  drawer.appendChild(body);
  root.appendChild(drawer);
  void ctx;
}

function confidencePoints(view) {
  const c = view.conclusion && view.conclusion.confidence;
  if (!c || !(c.points || []).length) return h("p", {class: "u-meta", text: "No confidence is stated for this view's state."});
  const t = h("table", {class: "pn-points"}, h("caption", {class: "u-meta pn-points-cap",
    text: `This view: ${c.level ? `${c.level}, ` : ""}score ${isNum(c.score) ? fmtNumber(c.score, 0, {signed: true}) : NULL_GLYPH}`}));
  const tb = h("tbody");
  for (const p of c.points) tb.appendChild(h("tr", {}, h("td", {text: p.text}), h("td", {class: "num u-num", text: fmtNumber(p.points, 0, {signed: true})})));
  t.appendChild(tb);
  return t;
}

function definitionsList(items) {
  const wrap = h("div", {class: "pn-defs"});
  let group = null, dl = null;
  for (const it of items) {
    if (it.group !== group) {
      group = it.group;
      wrap.appendChild(h("h4", {class: "u-group-head pn-def-group", text: group || ""}));
      dl = h("dl", {class: "pn-def-list"});
      wrap.appendChild(dl);
    }
    dl.appendChild(h("div", {class: "pn-def", "data-def": it.colId, id: `pn-def-${it.colId}`, tabindex: "-1"},
      h("dt", {text: it.label}), h("dd", {text: it.text})));
  }
  return wrap;
}

// ---------------------------------------------------------------------------------------------
// 6.4 Detail side panel (mountDetail)
// ---------------------------------------------------------------------------------------------

export function mountDetail(root, ctx) {
  let opener = null;
  let lastTicker = null;
  const m = createMount(root, ctx, "pn-detail-root", {
    name: "Company details",
    local: () => ({overTime: "revenue_growth"}),
    sig: (v, local) => {
      const st = stateOf(ctx);
      const d = v.detail;
      return [d, d ? (st.notes || {})[d.ticker] : null, local.overTime, v.focal && v.focal.ticker, v.ctx && v.ctx.currency,
        v.table && (v.table.rows || []).map((r) => r.ticker)];
    },
    build: (root, view, local, api) => {
      const d = view.detail;
      root.toggleAttribute("data-open", !!d);
      if (!d) return;
      buildDetail(root, view, ctx, local, api, close);
    },
    after: (root, view) => {
      const d = view.detail;
      const doc = root.ownerDocument;
      if (!d) {
        if (lastTicker !== null) {
          lastTicker = null;
          returnFocus(doc, opener);
          opener = null;
        }
        return;
      }
      if (d.ticker !== lastTicker) {
        if (lastTicker === null) opener = captureOpener(doc, root);
        lastTicker = d.ticker;
        const title = root.querySelector(".pn-d-title");
        if (title) { try { title.focus({preventScroll: true}); } catch (e) { title.focus(); } }
        const body = root.querySelector(".pn-d-body");
        if (body) body.scrollTop = 0;
      }
    },
  });
  function close() {
    if (ctx && typeof ctx.closeDetail === "function") ctx.closeDetail();
    else dispatch(ctx, {type: "CLOSE_DETAIL"});
  }
  return m;
}

function buildDetail(root, view, ctx, local, api, close) {
  const d = view.detail;
  const R = d.record || {};
  const D = d.detail || null;
  const T = d.ticker;
  const F = d.focalTicker || (view.focal && view.focal.ticker) || "";
  const cur = d.currency || "USD";
  const FX = fx(view);
  const money = (usdM) => fmtMoneyProse(usdM, cur, FX);
  const titleId = uid("pndt");
  const panel = h("aside", {class: "pn-detail", role: "dialog", "aria-modal": "false", "aria-labelledby": titleId, "data-ticker": T});
  root.appendChild(panel);
  const descHost = hiddenHost(panel);
  panel.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); return; }
    if ((e.key === "ArrowUp" || e.key === "ArrowDown") && !isTyping(e.target) && !e.altKey && !e.metaKey && !e.ctrlKey) {
      const order = ((view.table && view.table.rows) || []).map((r) => r.ticker);
      const i = order.indexOf(T);
      if (i < 0 || !order.length) return;
      const j = e.key === "ArrowUp" ? i - 1 : i + 1;
      if (j < 0 || j >= order.length) { announce(ctx, e.key === "ArrowUp" ? "First row." : "Last row."); e.preventDefault(); return; }
      e.preventDefault();
      e.stopPropagation();
      openDetail(ctx, order[j]);
      announce(ctx, `Showing ${order[j]}.`);
    }
  });

  // 1. Header.
  const closeBtn = h("button", {type: "button", class: "u-btn icon pn-close", "data-key": "detail-close", "aria-label": `Close ${T} details`, text: "✕"});
  closeBtn.addEventListener("click", close);
  const head = h("header", {class: "pn-d-head"},
    h("div", {class: "pn-d-row1"},
      h("span", {class: "u-ticker pn-d-ticker", text: T}),
      h("h2", {class: "pn-d-title", id: titleId, tabindex: "-1", "data-key": "detail-title", text: d.name || T}),
      closeBtn));
  const chipsRow = h("div", {class: "pn-d-chips"});
  for (const c of d.chips || []) {
    const el = chip(c.text, c.tone || "neutral", {tabindex: c.tooltip ? "0" : null});
    if (c.tooltip) bindTip(ctx, el, c.tooltip, descHost);
    chipsRow.appendChild(el);
  }
  if (d.isFocal) chipsRow.appendChild(chip("Focal company", "active"));
  else if (d.relevance) {
    const rc = chip(`Relevance ${d.relevance.score} of 100`, "neutral", {tabindex: "0"});
    const lines = COMPONENT_ORDER.map((k) => {
      const v = d.relevance.components ? d.relevance.components[k] : null;
      return `${COMPONENT_LABEL[k]}: ${isNum(v) ? Math.round(v * 100) + "%" : "not scored"}`;
    });
    bindTip(ctx, rc, {title: `Relevance ${d.relevance.score} of 100, ${d.relevance.level}`, body: d.reason || "", lines}, descHost);
    chipsRow.appendChild(rc);
  }
  if (d.source) chipsRow.appendChild(chip(`Source: ${d.source === "saved" ? "saved set" : d.source}`, "neutral"));
  if (!d.isFocal && !d.inPeers) chipsRow.appendChild(chip("Not in the peer set", "neutral"));
  if (d.excluded) chipsRow.appendChild(chip("Excluded from statistics", "neutral"));
  head.appendChild(chipsRow);
  if (d.reason && !d.isFocal) head.appendChild(h("p", {class: "u-meta pn-d-reason", text: d.reason}));
  const acts = h("div", {class: "pn-d-actions", role: "group", "aria-label": `Actions on ${T}`});
  const A = d.actions || {};
  if (A.makeFocal) acts.appendChild(btn("Make focal", {"data-key": "d-focal", cls: "primary"}, () => { makeFocal(ctx, T); announce(ctx, `${T} is now the focal company.`); }));
  if (A.exclude) acts.appendChild(btn(A.excludeLabel || "Exclude from statistics", {"data-key": "d-exclude"}, () => {
    dispatch(ctx, {type: "TOGGLE_EXCLUDE", ticker: T});
    announce(ctx, d.excluded ? `${T} included in statistics.` : `${T} excluded from statistics. Still shown.`);
  }));
  if (!d.isFocal) acts.appendChild(btn(A.peerLabel || (d.inPeers ? "Remove from peers" : "Add to peers"), {"data-key": "d-peer"}, () => {
    if (d.inPeers) { dispatch(ctx, {type: "REMOVE_PEER", ticker: T, now: nowMs()}); announce(ctx, `Removed ${T} from peers.`); }
    else { dispatch(ctx, {type: "ADD_PEER", ticker: T}); announce(ctx, `Added ${T} to peers.`); }
  }));
  acts.appendChild(btn(A.openForecast || "Open in Forecast tab", {"data-key": "d-forecast"}, () => {
    if (T !== F) makeFocal(ctx, T);
    if (ctx && typeof ctx.clickParentTab === "function") ctx.clickParentTab("Forecast");
  }));
  head.appendChild(acts);
  panel.appendChild(head);

  const body = h("div", {class: "pn-d-body", "data-scroll-key": `detail-${T}`});
  panel.appendChild(body);
  const noRecord = (what) => h("p", {class: "pn-empty", text: `No ${what} in this payload for ${T}.`});

  // 2. Price.
  {
    const s = sub("Price");
    const closes = D && D.spark ? D.spark.closes : null;
    const width = Math.max(240, Math.min(420, (root.clientWidth || 440) - 40));
    if (closes && closes.length > 1) {
      s.appendChild(sparkline(closes, {width, height: 44, label: `${T} weekly closes over one year, ${signedPct(D.spark.change)}`}));
    } else {
      const sp = (R.market && R.market.spark_90d) || [];
      if (sp.length > 1) s.appendChild(sparkline(sp, {width, height: 44, label: `${T} daily closes over 90 days`}));
      else s.appendChild(h("p", {class: "pn-empty", text: NA_TEXT.no_prices}));
    }
    const mk = R.market || {};
    const rng = d.range52w;
    s.appendChild(h("p", {class: "pn-d-line"},
      h("span", {class: "u-num", text: isNum(d.price) ? `${fmtNumber(d.price, 2)} USD` : NULL_GLYPH}),
      h("span", {class: "u-meta", text: ` close ${fmtDate(mk.price_as_of)}`}),
      rng ? h("span", {class: "u-meta", text: ` · 52-week range ${fmtNumber(rng.low, 2)} to ${fmtNumber(rng.high, 2)}`}) : null));
    const rel = D && D.relative;
    if (rel) {
      const t = h("table", {class: "pn-mini-table"}, h("thead", {}, h("tr", {},
        h("th", {scope: "col", text: "Window"}), h("th", {scope: "col", class: "num", text: T}), h("th", {scope: "col", class: "num", text: "Against XLV"}))));
      const tb = h("tbody");
      for (const w of ["1m", "3m", "1y"]) {
        const x = rel[w];
        if (!x) continue;
        const covers = x.covers_window !== false;
        tb.appendChild(h("tr", {}, h("th", {scope: "row", text: w}),
          covers ? h("td", {class: "num u-num", text: arrowPct(x.company_pct)}) : h("td", {class: "num u-meta", colspan: "2", text: "listed for less than this window"}),
          covers ? h("td", {class: "num u-num", text: signedPct(x.relative_pct)}) : null));
      }
      t.appendChild(tb);
      s.appendChild(t);
    } else if (isNum(mk.ttm_change)) {
      s.appendChild(h("p", {class: "pn-d-line u-meta", text: `12 months: ${arrowPct(mk.ttm_change)}`}));
    }
    body.appendChild(s);
  }

  // 3. Against the focal company.
  if (!d.isFocal && (d.against || []).length) {
    const s = sub(`Against ${F}`);
    const t = h("table", {class: "pn-mini-table pn-against"}, h("caption", {class: "u-sr",
      text: `${T} against ${F}. An up triangle marks the better side where one side is better by the measure's direction.`}));
    t.appendChild(h("thead", {}, h("tr", {}, h("th", {scope: "col", text: "Measure"}), h("th", {scope: "col", class: "num", text: T}),
      h("th", {scope: "col", class: "num", text: F}))));
    const tb = h("tbody");
    for (const a of d.against) {
      const cell = (text, better, reason) => {
        const td = h("td", {class: "num"}, better ? h("span", {class: "pn-better", "aria-hidden": "true", text: `${UP} `}) : null,
          h("span", {class: text === NULL_GLYPH || text === "n.m." ? "u-null" : "u-num", text}),
          better ? h("span", {class: "u-sr", text: " (better)"}) : null);
        if (reason) bindTip(ctx, td, reason);
        return td;
      };
      tb.appendChild(h("tr", {}, h("th", {scope: "row", text: a.label}),
        cell(a.peer, a.better === "peer", a.peerReason), cell(a.focal, a.better === "focal", a.focalReason)));
    }
    t.appendChild(tb);
    s.appendChild(t);
    s.appendChild(h("p", {class: "u-meta", text: "Better is marked for revenue, revenue growth, net margin and late-stage trials (higher) and losing exclusivity (lower) only."}));
    body.appendChild(s);
  }

  // 4. Over time.
  {
    const s = sub("Over time");
    const ot = d.overTime || {labels: [], series: {}};
    const key = local.overTime === "net_margin" ? "net_margin" : "revenue_growth";
    const seg = h("div", {class: "u-seg pn-seg", role: "group", "aria-label": "Measure over time"});
    for (const o of [{id: "revenue_growth", label: "Revenue growth"}, {id: "net_margin", label: "Net margin"}]) {
      const b = h("button", {type: "button", "data-key": `ot-${o.id}`, "aria-pressed": String(key === o.id), text: o.label});
      b.addEventListener("click", () => { local.overTime = o.id; api.rerender(); });
      seg.appendChild(b);
    }
    s.appendChild(seg);
    const ser = (ot.series && ot.series[key]) || {peer: [], focal: []};
    // The table's n.m. rules hold here too: growth beyond 500 % and margins below -100 % are
    // not plotted (a small base would flatten every other year).
    const clean = (vals) => historyValues(vals, key);
    const series = [{name: T, values: clean(ser.peer), tone: "peer"}];
    if (!d.isFocal) series.push({name: F, values: clean(ser.focal), tone: "focal"});
    const dropped = series.reduce((n, x, i) => n + ((i ? ser.focal : ser.peer) || []).filter(isNum).length - x.values.filter(isNum).length, 0);
    const has = series.some((x) => (x.values || []).some(isNum));
    if (has) {
      const width = Math.max(240, Math.min(420, (root.clientWidth || 440) - 40));
      s.appendChild(lineMini(series, ot.labels || [], {width, height: 96,
        label: `${key === "net_margin" ? "Net margin" : "Revenue growth"}, ${(ot.labels || [])[0] || ""} to ${(ot.labels || []).slice(-1)[0] || ""}: ${T}${d.isFocal ? "" : ` against ${F}`}`}));
      s.appendChild(h("p", {class: "pn-legend"}, h("span", {class: "pn-key pn-key-peer", "aria-hidden": "true"}), T,
        d.isFocal ? null : [h("span", {class: "pn-key pn-key-focal", "aria-hidden": "true"}), F]));
      if (dropped) s.appendChild(h("p", {class: "u-meta", text: `${dropped} ${dropped === 1 ? "year is" : "years are"} not plotted: ${key === "net_margin"
        ? "a margin below −100% is not meaningful" : "growth beyond 500% is not meaningful"}.`}));
    } else s.appendChild(h("p", {class: "pn-empty", text: "No fiscal-year history on file."}));
    body.appendChild(s);
  }

  // 5. Earnings trend.
  {
    const s = sub("Earnings trend");
    const E = D && D.earnings;
    if (E && (E.fy || []).length) {
      const fy = E.fy.slice(-5);
      const width = Math.max(200, Math.min(420, (root.clientWidth || 440) - 40));
      const bn = (usdM) => (isNum(usdM) ? usdM / (cur === "USD" ? 1 : ((FX.usd_per_unit[cur]) || NaN)) / 1000 : null);
      s.appendChild(h("p", {class: "u-label", text: `Fiscal-year revenue and net income, ${cur} bn`}));
      s.appendChild(barMini(fy.map((r) => ({value: bn(r.revenue_usd_m), label: `FY${String(r.fy).slice(-2)}`,
        title: `FY${r.fy} revenue ${money(r.revenue_usd_m)}`})), {width, height: 56, label: `${T} revenue by fiscal year`}));
      s.appendChild(barMini(fy.map((r) => ({value: bn(r.net_income_usd_m), label: `FY${String(r.fy).slice(-2)}`,
        title: `FY${r.fy} net income ${money(r.net_income_usd_m)}`})), {width, height: 48, label: `${T} net income by fiscal year`}));
      const q = (E.quarters || []).slice(-8);
      if (q.length) {
        s.appendChild(h("p", {class: "u-label", text: `Quarterly revenue, ${cur} bn`}));
        s.appendChild(barMini(q.map((r) => ({value: bn(r.revenue_usd_m), label: r.label ? String(r.label).replace(/-\d\d$/, "") : "",
          title: `${r.label || fmtDate(r.period_end)} revenue ${money(r.revenue_usd_m)}${r.derived ? ". Q4 derived as the fiscal year less nine months" : ""}`})),
          {width, height: 56, derivedIndex: q.map((r, i) => (r.derived ? i : -1)).filter((i) => i >= 0), label: `${T} quarterly revenue`}));
        if (q.some((r) => r.derived)) s.appendChild(h("p", {class: "u-meta"}, h("span", {class: "pn-hatch-key", "aria-hidden": "true"}),
          "Hatched: Q4 derived as the fiscal year less nine months."));
      } else {
        s.appendChild(h("p", {class: "pn-empty", text: "No quarterly filings for this company; fiscal years only."}));
      }
      const t = h("table", {class: "pn-mini-table"}, h("caption", {class: "u-meta pn-cap", text: `EPS in ${E.unit || "the filing currency"} per ordinary share, as filed`}),
        h("thead", {}, h("tr", {}, ["Year", `Revenue`, "Net income", "EPS"].map((x, i) => h("th", {scope: "col", class: i ? "num" : "", text: x})))));
      const tb = h("tbody");
      for (const r of fy) tb.appendChild(h("tr", {}, h("th", {scope: "row", text: `FY${r.fy}`}),
        h("td", {class: "num u-num", text: money(r.revenue_usd_m)}), h("td", {class: "num u-num", text: money(r.net_income_usd_m)}),
        h("td", {class: "num u-num", text: fmtNumber(r.eps_rc, 2)})));
      t.appendChild(tb);
      s.appendChild(t);
    } else s.appendChild(noRecord("earnings history"));
    body.appendChild(s);
  }

  // 6. Estimate revisions.
  {
    const s = sub("Estimate revisions");
    const revs = (D && D.revisions) || [];
    const starts = view.lineage && view.lineage.consensusStarts;
    if (revs.length) {
      const t = h("table", {class: "pn-mini-table pn-revs"});
      t.appendChild(h("thead", {}, h("tr", {}, ["Measure", "Latest", `Since ${fmtDateShort(starts)}`, "Change", "Low to high"]
        .map((x, i) => h("th", {scope: "col", class: i ? "num" : "", text: x})))));
      const tb = h("tbody");
      for (const r of revs) {
        const name = r.metric === "PriceTarget" ? "12-month target" : `${r.metric} ${r.period}`;
        const chg = isNum(r.value) && isNum(r.first_value) && r.first_value !== 0 ? r.value / Math.abs(r.first_value) - Math.sign(r.first_value) : null;
        const counts = [isNum(r.revisions) ? `${r.revisions} ${r.revisions === 1 ? "revision" : "revisions"}` : null,
          isNum(r.n) ? `${r.n} ${r.n === 1 ? "estimate" : "estimates"}` : null].filter(Boolean).join(", ");
        tb.appendChild(h("tr", {}, h("th", {scope: "row"}, h("span", {class: "pn-rev-name", text: name}), counts ? h("span", {class: "u-meta pn-rev-n", text: counts}) : null),
          h("td", {class: "num u-num", text: fmtNumber(r.value, 2)}),
          h("td", {class: "num u-num", title: r.first_as_of ? `First record ${fmtDate(r.first_as_of)}` : null, text: fmtNumber(r.first_value, 2)}),
          h("td", {class: "num u-num", text: arrowPct(chg)}),
          h("td", {class: "num u-num", text: isNum(r.low) && isNum(r.high) ? `${fmtNumber(r.low, 2)} to ${fmtNumber(r.high, 2)}` : NULL_GLYPH})));
      }
      t.appendChild(tb);
      s.appendChild(h("div", {class: "pn-scroll-x"}, t));
    } else s.appendChild(h("p", {class: "pn-empty", text: D ? NA_TEXT.no_consensus : `No revision record in this payload for ${T}.`}));
    s.appendChild(h("p", {class: "u-meta", text: `The revision record starts on ${fmtDate(starts)}.`}));
    body.appendChild(s);
  }

  // 7. Recent results.
  {
    const s = sub("Recent results");
    const r = D && D.results;
    if (r) {
      const filing = ((D && D.filings) || []).find((f) => f.filed_date && r.period_end && f.filed_date >= r.period_end && /^(10-Q|10-K|6-K|20-F)/.test(f.form || ""));
      const dl = h("dl", {class: "pn-kv"});
      const kv = (k, v) => dl.append(h("dt", {text: k}), h("dd", {class: "u-num"}, v));
      kv("Quarter to", fmtDate(r.period_end));
      kv("Revenue", money(r.revenue_usd_m));
      if (isNum(r.yoy) && Math.abs(r.yoy) > MAX_ABS_GROWTH) {
        const dd = h("span", {class: "u-nm", tabindex: "0", text: "n.m."});
        bindTip(ctx, dd, "Not meaningful. Growth beyond 500% on a small base says little.", descHost);
        kv("On the year", dd);
      } else kv("On the year", arrowPct(r.yoy));
      kv("EPS", isNum(r.eps_rc) ? `${fmtNumber(r.eps_rc, 2)}${(D.earnings && D.earnings.unit) ? ` ${D.earnings.unit} per ordinary share` : ""}` : NULL_GLYPH);
      if (filing) kv("Filing", h("a", {href: filing.url, target: "_blank", rel: "noopener noreferrer", text: `${filing.form}, ${fmtDate(filing.filed_date)}`}));
      s.appendChild(dl);
    } else s.appendChild(noRecord("quarterly result"));
    body.appendChild(s);
  }

  // 8. Key catalysts.
  {
    const s = sub("Key catalysts");
    const cs = ((D && D.catalysts) || []).slice(0, 5);
    if (cs.length) {
      const ul = h("ul", {class: "pn-list"});
      for (const c of cs) {
        const derived = c.is_curated === false;
        const li = h("li", {class: "pn-cat"},
          h("span", {class: "u-num pn-cat-date", text: fmtDate(c.expected_date)}),
          h("div", {class: "pn-cat-body"},
            h("span", {class: "pn-cat-title", text: c.title || NULL_GLYPH}),
            h("div", {class: "pn-cat-meta"},
              c.type ? h("span", {class: "u-meta", text: c.type}) : null,
              derived ? chip("Derived, estimated date", "flag") : null,
              c.source_url ? h("a", {href: c.source_url, target: "_blank", rel: "noopener noreferrer", class: "pn-src-link", text: "Source",
                "aria-label": `Source for ${c.title || "this catalyst"}, opens a new tab`}) : null)));
        ul.appendChild(li);
      }
      s.appendChild(ul);
    } else s.appendChild(h("p", {class: "pn-empty", text: D ? "No pending catalysts on file." : `No catalyst record in this payload for ${T}.`}));
    body.appendChild(s);
  }

  // 9. Product and pipeline mix.
  {
    const s = sub("Product and pipeline mix");
    const P = D && D.products;
    if (P && (P.rows || []).length) {
      const t = h("table", {class: "pn-mini-table"}, h("caption", {class: "u-meta pn-cap", text: `Share of product revenue, FY${P.fiscal_year || ""}`}),
        h("thead", {}, h("tr", {}, h("th", {scope: "col", text: "Product"}), h("th", {scope: "col", class: "num", text: "Revenue"}), h("th", {scope: "col", class: "num", text: "Share"}))));
      const tb = h("tbody");
      for (const r of P.rows) tb.appendChild(h("tr", {}, h("th", {scope: "row", text: r.name}),
        h("td", {class: "num u-num", text: money(r.value_usd_m)}), h("td", {class: "num u-num", text: isNum(r.share) ? `${fmtNumber(r.share * 100, 1)}%` : NULL_GLYPH})));
      t.appendChild(tb);
      s.appendChild(t);
    } else s.appendChild(h("p", {class: "pn-empty", text: NA_TEXT.no_product_revenue}));
    const pipe = D && D.pipeline;
    if (pipe && pipe.compounds && Object.values(pipe.compounds).some((v) => isNum(v) && v > 0)) {
      s.appendChild(h("p", {class: "u-label", text: "Compounds by phase"}));
      const compounds = Object.fromEntries(Object.entries(pipe.compounds).filter(([, v]) => isNum(v) && v > 0));
      s.appendChild(phaseBars(compounds, {width: Math.max(220, Math.min(420, (root.clientWidth || 440) - 40))}));
      if (isNum(pipe.unattributed)) s.appendChild(h("p", {class: "u-meta", text: `Unattributed trials: ${pipe.unattributed}`}));
    } else s.appendChild(h("p", {class: "pn-empty", text: D ? NA_TEXT.no_trials : `No pipeline record in this payload for ${T}.`}));
    body.appendChild(s);
  }

  // 10. Relevant filings.
  {
    const s = sub("Relevant filings");
    const fs = ((D && D.filings) || []).slice(0, 5);
    if (fs.length) {
      const ul = h("ul", {class: "pn-list"});
      for (const f of fs) {
        ul.appendChild(h("li", {class: "pn-filing"}, chip(f.form || "Filing", "neutral"), h("span", {class: "u-num pn-cat-date", text: fmtDate(f.filed_date)}),
          f.url ? h("a", {href: f.url, target: "_blank", rel: "noopener noreferrer", text: f.title || f.form, title: "Opens a new tab"})
            : h("span", {text: f.title || f.form})));
      }
      s.appendChild(ul);
    } else s.appendChild(noRecord("filing list"));
    body.appendChild(s);
  }

  // 11. Notes.
  {
    const s = sub("Notes");
    const nid = uid("pnnote");
    const note = d.note || (stateOf(ctx).notes || {})[T] || null;
    const ta = h("textarea", {id: nid, class: "u-input pn-note", "data-key": `detail-note-${T}`, rows: "3", text: note ? note.text : ""});
    let orig = note ? note.text : "";
    ta.addEventListener("input", () => ta.setAttribute("data-dirty", "1"));
    ta.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); ta.blur(); } });
    ta.addEventListener("blur", () => setTimeout(() => {
      if (ta.value === orig) return;
      orig = ta.value;
      ta.removeAttribute("data-dirty");
      dispatch(ctx, {type: "SET_NOTE", ticker: T, text: ta.value, now: nowMs()});
      announce(ctx, `Note on ${T} saved. ${storageOk(ctx) ? SAVED_HERE : STATE_COPY.storage_unavailable.detail}`);
    }, 0));
    s.appendChild(h("label", {class: "u-label", for: nid, text: "Analyst note"}));
    s.appendChild(ta);
    s.appendChild(storageOk(ctx)
      ? h("p", {class: "u-meta", text: `${SAVED_HERE}${note && note.updated ? ` Last saved ${dateTime(note.updated)}.` : ""}`})
      : storageNote(ctx));
    const sys = D && D.notes && D.notes.system;
    if (sys && sys.excerpt) {
      s.appendChild(h("p", {class: "u-label pn-sys-lbl", text: `System-generated note, ${sys.model || "model not recorded"}, ${fmtDate(sys.generated_at)}`}));
      const ex = String(sys.excerpt).trim();
      s.appendChild(h("blockquote", {class: "pn-sys-note", text: /[.!?"”)]$/.test(ex) ? ex : `${ex}…`}));
    } else s.appendChild(h("p", {class: "pn-empty", text: "No system note for this company."}));
    body.appendChild(s);
  }

  // 12. Model values.
  if (d.model || d.modelState === "not_computed" || d.modelState === "failed") {
    const s = sub("Model values");
    if (d.model) {
      const M = d.model;
      const dl = h("dl", {class: "pn-kv"});
      const kv = (k, v) => dl.append(h("dt", {text: k}), h("dd", {}, h("span", {class: "u-num", text: v}), h("span", {class: "u-marker", "aria-hidden": "true", text: "M"})));
      kv("Fair value, USD", fmtNumber(M.fairValue, 2));
      kv("Rating", M.rating || NULL_GLYPH);
      kv("Range today, USD", Array.isArray(M.rangeToday) ? `${fmtNumber(M.rangeToday[0], 2)} to ${fmtNumber(M.rangeToday[1], 2)}` : NULL_GLYPH);
      kv("Forward 12 months, USD", fmtNumber(M.forward12m, 2));
      kv("Pipeline rNPV per share, risked", fmtNumber(M.pipelinePerShare, 2));
      kv("Pipeline rNPV per share, unrisked", fmtNumber(M.pipelineUnrisked, 2));
      s.appendChild(dl);
      s.appendChild(h("p", {class: "u-meta", text: M.note || "Model output. It does not drive the summary."}));
    } else {
      s.appendChild(h("p", {class: "pn-empty", text: d.modelState === "failed" ? NA_TEXT.model_failed : NA_TEXT.model_not_computed}));
    }
    body.appendChild(s);
  }

  // 13. Data lineage.
  {
    const s = sub("Data lineage");
    const lin = D && D.lineage;
    const srcs = lin && lin.sources ? Object.entries(lin.sources) : [];
    if (srcs.length) {
      const t = h("table", {class: "pn-mini-table pn-lineage"}, h("thead", {}, h("tr", {},
        h("th", {scope: "col", text: "Source"}), h("th", {scope: "col", text: "Last live fetch, UTC"}), h("th", {scope: "col", text: "Last error, UTC"}))));
      const tb = h("tbody");
      for (const [name, x] of srcs.sort((a, b) => a[0].localeCompare(b[0]))) {
        const failed = x.error && (!x.live || x.error > x.live);
        tb.appendChild(h("tr", {class: failed ? "is-flag" : ""}, h("th", {scope: "row", text: sourceName(name)}),
          h("td", {class: "u-num", text: shortStamp(x.live)}),
          h("td", {}, failed ? [h("span", {class: "u-marker amber", "aria-hidden": "true", text: "!"}), h("span", {class: "pn-flag-text", text: `Last fetch failed ${fmtDate(x.error)}`})]
            : h("span", {class: "u-meta", text: x.error ? `${shortStamp(x.error)}, recovered` : "none"}))));
      }
      t.appendChild(tb);
      s.appendChild(h("div", {class: "pn-scroll-x"}, t));
    } else s.appendChild(noRecord("source record"));
    const L = R.lineage || {};
    const dl = h("dl", {class: "pn-kv"});
    const kv = (k, v) => dl.append(h("dt", {text: k}), h("dd", {class: "u-num", text: v}));
    kv("Financials", `${fmtDate((lin && lin.financials && lin.financials.latest_period_end) || L.fy_period_end)}${((lin && lin.financials && lin.financials.sources) || [L.financials_source]).filter(Boolean).length
      ? `, ${((lin && lin.financials && lin.financials.sources) || [L.financials_source]).filter(Boolean).map((x) => x.replace(/_/g, " ")).join(", ")}` : ""}`);
    kv("Balance sheet", fmtDate(L.balance_sheet_as_of || (R.ev && R.ev.balance_sheet_as_of)));
    kv("FX", `ECB ${fmtDate((lin && lin.fx_as_of) || L.fx_as_of)}`);
    const run = (lin && lin.refresh_run) || (view.lineage && view.lineage.run);
    kv("Refresh run", run ? `${run.id}, ${run.status}, finished ${dateTime(run.finished_at)}` : NULL_GLYPH);
    s.appendChild(dl);
    body.appendChild(s);
  }
  void money;
}
