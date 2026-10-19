/**
 * table.js: the comparable companies table of the Comps valuation view. Owner: C.
 *
 * Contract: docs/design/comps-valuation.md, section 4 (structure, column catalogue, formats,
 * markers, presets, summary rows, row behaviour, sorting, filtering, resizing, hiding, pinning,
 * conditional format modes), 7.1 to 7.5 (keys, focus, tooltips), 11.1, and revision 3 (12.7): a
 * toolbar of three controls (column preset, find column, one "View" menu) plus the hidden-columns
 * chip, and flag markers only where core.js says a flag bears on the printed value (`cell.marks`)
 * or costs confidence in the conclusion (`row.tickerFlags`):
 *
 *   mountTable(root, ctx) -> {update(view), focusCell(ticker, colId), scrollToColumn(colId),
 *                             getViewport(), destroy()}
 *
 * The table reads `view.table` (core.js deriveView) and the state through `ctx.getState()`. It
 * never reads the payload. Every change goes through `ctx.dispatch` with a core.js action, so the
 * shell persists the table configuration (preset, custom columns, hidden, pinned, widths, sort,
 * filters, format mode, density, text size, summary rows).
 *
 * Grid model (7.4): one `<table role="grid" tabindex="0">`, roving through
 * `aria-activedescendant` over cell ids `c-{ticker}-{colId}` (header `c-head-{colId}`, summary
 * `c-sum-{id}-{colId}`), described by `#tb-active-desc`, which this module rewrites whenever the
 * active cell moves. The grid consumes its own keys (arrows, j, k, Home, End, Page up, Page down,
 * Enter, o, Shift Enter, Space, s, x, Shift X, Delete) with preventDefault and stopPropagation,
 * so a shell key handler that skips `event.defaultPrevented` never acts on them twice.
 *
 * The active cell is local, so arrow keys never wait on a full re-derive; FOCUS_CELL is sent
 * 200 ms after the last move, for body rows only, so palette commands such as "Exclude" can read
 * `state.ui.focus`.
 */

import {
  COLUMNS, COLUMN_BY_ID, COLUMN_GROUPS, FROZEN_MAX_SHARE, PRESET_FOOTNOTE, CF_MODES, CF_MODE_LABEL,
  DENSITIES, TEXT_SIZES, SYSTEM_SUBGROUPS, RELEVANCE_COMPONENTS, STATE_COPY, NULL_GLYPH,
  canPin, compareCells, commandHint, COMMAND_BY_ID, keyLabel, normKey, presetColumns, fmtNumber,
} from "./core.js";

// ---------------------------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------------------------

/** The five frozen base columns, always first, in every preset (4.1). */
export const BASE_IDS = ["exp", "incl", "rel", "company", "ticker"];
const BASE_SET = new Set(BASE_IDS);

/** Frozen widths per layout (4.1): wide and ultrawide 332, laptop 384 with the primary, narrow 328. */
export const LAYOUT_WIDTHS = {
  ultrawide: {exp: 20, incl: 28, rel: 44, company: 176, ticker: 64, primary: null},
  wide: {exp: 20, incl: 28, rel: 44, company: 176, ticker: 64, primary: null},
  laptop: {exp: 20, incl: 28, rel: 44, company: 148, ticker: 60, primary: 84},
  narrow: {exp: 20, incl: 24, rel: 36, company: 112, ticker: 56, primary: 80},
};
/** Manual pins allowed per layout (4.1). */
export const MAX_PINS = {ultrawide: 2, wide: 2, laptop: 1, narrow: 0};
/** Resize limits (4.8). */
export const RESIZE_MIN = 56, RESIZE_MAX = 320;
/** Widest a column grows to fit its header before the analyst resizes it. */
export const AUTO_WIDTH_MAX = 120;
/** The primary column may grow further, so its "Primary" tag stays readable at wide. */
export const AUTO_WIDTH_PRIMARY_MAX = 150;
/** Summary rows kept at laptop and narrow until "Show mean and quartiles" (4.6). */
export const SUMMARY_SHORT = ["median", "n"];

const NO_RESIZE = new Set(["exp", "incl", "rel"]);
const MONEY_FMTS = new Set(["money1", "money0m"]);
const GROUP_LABEL = Object.fromEntries(COLUMN_GROUPS.map((g) => [g.id, g.label]));
const NULL = NULL_GLYPH;
const EXCLUDED_TEXT = "Excluded from statistics. Still shown. X includes it again.";
const PRIMARY_KEEP = "The primary metric stays visible. Change the primary in the dot plot.";
const PIN_REFUSED = "Pinned columns would cover more than 40% of the table. Unpin one first.";
const FILTER_NOTE = "Filters hide rows. Statistics still use every included peer.";
const SAVED_HERE = "Saved in this browser only.";
const CF_CAUTION = "A low multiple is never marked as good: a discount can reflect weaker growth, patent exposure or clinical risk.";
const RESET_NOOP = "Columns, widths and sort are already the preset's.";
const FLAGS_ELSEWHERE = "Enter or a click opens the details, where every data flag of the company is listed.";
/** The View menu's own height (12.7); the shared menu stops at 60vh. */
export const VIEW_MENU_CLASS = "tb-viewmenu";
/** Toolbar controls, left to right (12.7). The hidden chip shows only while columns are hidden. */
export const TOOLBAR_KEYS = ["preset", "find", "view", "hidden"];
/** Group heads of the View menu, in order (12.7). */
export const VIEW_GROUPS = [
  {id: "stats", label: "Statistics over"},
  {id: "outliers", label: "Outliers in statistics"},
  {id: "cf", label: "Conditional format"},
  {id: "density", label: "Density"},
  {id: "text", label: "Text size"},
  {id: "rows", label: "Rows"},
  {id: "layouts", label: "Layouts"},
];
const SOURCE_WORDS = {system: "System set", analyst: "Added by you", saved: "Saved peer set"};
const POOL_WORDS = {A: "pool A, same subsector and stage", B: "pool B, same subsector, other stage",
  C: "pool C, adjacent subsector"};
const LEVEL_BARS = {high: 3, medium: 2, low: 1};
const FOCUS_SEND_MS = 200;
const BOX_MIN_H = 180;   // header, focal row, one peer row and two summary rows
const BOX_PAD = 8;       // room under the box while it rests below the top of #main
const TIP_DELAY_MS = 300;

// ---------------------------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------------------------

function isNum(v) { return typeof v === "number" && Number.isFinite(v); }
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function round3(v) { return Math.round(v * 1000) / 1000; }
function round1(v) { return Math.round(v * 10) / 10; }

/** HTML-escape a value for text or attribute context. */
export function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (ch) => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[ch]));
}

export function normLayout(layout) { return LAYOUT_WIDTHS[layout] ? layout : "wide"; }
/** At laptop and narrow the primary column is frozen after the ticker (4.1). */
export function autoPinsPrimary(layout) {
  const l = normLayout(layout);
  return l === "laptop" || l === "narrow";
}

/**
 * `headerWidth(col)`: the width a column's header needs, estimated from its label (Archivo Narrow
 * 12 px, about 6.1 px a character) and its unit line (Plex Mono 10.5 px, 6.3 px a character),
 * plus the cell padding. Clamped between the catalogue width and AUTO_WIDTH_MAX: the unit line
 * reads unit first and provenance last, so what a narrow column cuts is the least needed part.
 */
export function headerWidth(col) {
  if (!col) return 84;
  const base = isNum(col.width) ? col.width : 84;
  const label = String(col.label || "").length * 6.1;
  const unit = String(col.unitLine || "").length * 6.3;
  const cap = col.isPrimary ? AUTO_WIDTH_PRIMARY_MAX : AUTO_WIDTH_MAX;
  return clamp(Math.ceil(Math.max(label, unit) + 22), base, Math.max(base, cap));
}

/**
 * `layoutColumns(columns, layout, {widths, boxWidth})` orders and sizes the table's columns for a
 * layout (4.1). `columns` is `view.table.columns` (base block, manual pins, the primary when the
 * preset lacks it, then the preset's columns). Returns `{cols, frozenCount, frozenWidth}` where
 * each col is the ColView plus `frozen`, `width`, `left` (px, frozen only), `pin` ("base",
 * "auto", "manual" or null, "manual-off" for a pin the layout cannot hold) and `groupStart`.
 *
 * - The base block is always frozen, at the layout's widths unless the analyst resized a column.
 * - At laptop and narrow the primary column is frozen directly after the ticker (84 / 80 px).
 * - Manual pins follow in pin order: at most 2 wide, 1 laptop, 0 narrow, and only while the
 *   frozen block stays within FROZEN_MAX_SHARE of the box width. A pin past either limit stays
 *   in its place, unfrozen. Pins keep the catalogue width, the one core.canPin budgets with.
 * - Every other column the analyst has not resized takes `headerWidth`.
 */
export function layoutColumns(columns, layout, opts = {}) {
  const L = normLayout(layout);
  const W = LAYOUT_WIDTHS[L];
  const widths = opts.widths || {};
  const wOf = (c, dflt) => (isNum(widths[c.id]) ? widths[c.id] : (isNum(dflt) ? dflt : (isNum(c.width) ? c.width : 84)));
  const list = Array.isArray(columns) ? columns : [];
  const base = BASE_IDS.map((id) => list.find((c) => c.id === id)).filter(Boolean)
    .map((c) => ({...c, frozen: true, width: wOf(c, W[c.id]), pin: "base"}));
  const rest = list.filter((c) => !BASE_SET.has(c.id));
  const primary = autoPinsPrimary(L) ? rest.find((c) => c.autoPinned || c.isPrimary) || null : null;
  const pins = rest.filter((c) => c.frozen && c !== primary);
  const others = rest.filter((c) => !c.frozen && c !== primary);
  const out = base.slice();
  if (primary) out.push({...primary, frozen: true, width: wOf(primary, W.primary), pin: "auto"});
  let frozenW = out.reduce((s, c) => s + c.width, 0);
  const budget = isNum(opts.boxWidth) && opts.boxWidth > 0 ? FROZEN_MAX_SHARE * opts.boxWidth : Infinity;
  const maxPins = MAX_PINS[L];
  const off = [];
  let taken = 0;
  for (const c of pins) {
    const w = wOf(c, c.width);
    if (taken < maxPins && frozenW + w <= budget) {
      out.push({...c, frozen: true, width: w, pin: "manual"});
      frozenW += w;
      taken++;
    } else {
      off.push({...c, frozen: false, width: w, pin: "manual-off"});
    }
  }
  for (const c of off.concat(others)) out.push(c.pin ? c : {...c, frozen: false, width: wOf(c, headerWidth(c)), pin: null});
  let left = 0;
  let frozenCount = 0;
  out.forEach((c, i) => {
    if (c.frozen) { c.left = left; left += c.width; frozenCount++; } else c.left = null;
    const prev = out[i - 1];
    c.groupStart = !!prev && prev.group !== c.group && !(prev.frozen && !c.frozen);
  });
  return {cols: out, frozenCount, frozenWidth: left};
}

/**
 * `groupRuns(cols)`: the group header cells, consecutive runs of one group, split where the
 * frozen block ends so a frozen run can stick on its own (4.1).
 */
export function groupRuns(cols) {
  const runs = [];
  (cols || []).forEach((c, i) => {
    const last = runs[runs.length - 1];
    if (last && last.id === c.group && last.frozen === !!c.frozen) {
      last.span++;
      last.end = i;
    } else {
      runs.push({id: c.group, label: GROUP_LABEL[c.group] || c.group || "", span: 1, frozen: !!c.frozen,
        start: i, end: i, left: c.frozen ? c.left : null, groupStart: !!c.groupStart});
    }
  });
  return runs;
}

/** Summary rows to draw (4.6): all visible rows at wide, median and n at laptop and narrow. */
export function visibleSummaryIds(summaryVisible, layout, expanded) {
  const vis = Array.isArray(summaryVisible) ? summaryVisible.slice() : [];
  if (!autoPinsPrimary(layout) || expanded) return vis;
  return vis.filter((id) => SUMMARY_SHORT.includes(id));
}

/**
 * `placeFocal(rows, sort, pinned)`: the focal row stays first while pinned (4.7). Unpinned and
 * sorted, it takes its sorted place among the peers by the same comparator (`compareCells`).
 */
export function placeFocal(rows, sort, pinned) {
  const list = (rows || []).slice();
  const i = list.findIndex((r) => r && r.isFocal);
  if (i < 0 || pinned || !sort || !sort.colId || sort.colId === "rel") return list;
  const [focal] = list.splice(i, 1);
  const fc = focal.cells ? focal.cells[sort.colId] : null;
  if (!fc) { list.unshift(focal); return list; }
  let at = list.findIndex((r) => {
    const pc = r.cells ? r.cells[sort.colId] : null;
    return !!pc && compareCells(fc, pc, sort.dir) < 0;
  });
  if (at < 0) at = list.length;
  list.splice(at, 0, focal);
  return list;
}

/**
 * `cellMarked(cell)` (12.7): whether a flag bears on the value this cell prints. core.js lists
 * those codes in `cell.marks` and computes `amber` and `red` from them; `cell.flags` is the wider
 * list the logic reads and never draws a marker. A cell with no `marks` is never marked, whatever
 * else it carries.
 */
export function cellMarked(cell) {
  return !!cell && Array.isArray(cell.marks) && cell.marks.length > 0 && !!(cell.amber || cell.red);
}

/**
 * `tickerMarked(row)` (12.7): the `!` after a ticker shows only while `row.tickerFlags` is not
 * empty, that is for a flag that cost a confidence point, a failed source or a failed calculation.
 * Every other flag of the company is listed in the detail panel.
 */
export function tickerMarked(row) {
  return !!row && Array.isArray(row.tickerFlags) && row.tickerFlags.length > 0;
}

/** The marker span after a ticker, or "" (12.7). */
export function tickerMarkHtml(row) {
  return tickerMarked(row) ? `<span class="u-marker amber" aria-hidden="true">!</span>` : "";
}

/**
 * `tickerTip(row)`: the ticker cell's tooltip. Its lines are the flags that mark the ticker
 * (`row.tickerLines`) and nothing else; a failed calculation leads with the row's own message.
 */
export function tickerTip(row) {
  if (!row) return null;
  const marked = tickerMarked(row);
  let lines = marked ? (row.tickerLines || []).slice() : [];
  if (row.error) {
    if (marked && row.tickerFlags[0] === "calc_failed") lines = lines.slice(1);
    lines.unshift(row.error);
  }
  lines.push(FLAGS_ELSEWHERE);
  return {title: row.ticker, body: row.name || null, lines};
}

/**
 * `markerFor(cell, col, cfMode)`: the 12 px marker slot after a number (4.4, 4.9, 12.7).
 * Returns `{text, tone}` with tone "amber", "muted" or "". Order: a per-cell basis fallback
 * (amber tag, the only amber tag), in data-quality mode a derived cell ("d"), a model cell ("M"),
 * in data-quality mode any tag letter, then "!" for a marking flag with no tag to show. Only
 * `cell.marks` draws the "!" and the "d": a flag that merely touches the cell does not.
 */
export function markerFor(cell, col, cfMode = "off") {
  const none = {text: "", tone: ""};
  if (!cell || !col || !col.numeric) return none;
  const marks = Array.isArray(cell.marks) ? cell.marks : [];
  const flagged = cellMarked(cell);
  if (cell.status === "err") return none;
  if (cell.status !== "ok") return flagged && cell.amber ? {text: "!", tone: "amber"} : none;
  if (cell.tagDiffers && cell.tag) return {text: cell.tag, tone: "amber"};
  const quality = cfMode === "quality";
  if (quality && (marks.includes("derived_operating_income") || marks.includes("derived_no_addback"))) {
    return {text: "d", tone: flagged ? "amber" : "muted"};
  }
  if (cell.tag === "M") return {text: "M", tone: "muted"};
  if (quality && cell.tag) return {text: cell.tag, tone: "muted"};
  if (flagged) return {text: "!", tone: "amber"};
  return none;
}

/** The status sentence of a cell (4.4): "No value. {reason}", "Not meaningful. {reason}". */
export function cellReasonText(cell) {
  if (!cell) return "";
  if (cell.status === "na" || cell.status === "err") return `No value. ${cell.reason || "No free data for this measure."}`;
  if (cell.status === "nm") return `Not meaningful. ${cell.reason || ""}`.trim();
  if (cell.status === "nb") return cell.reason || "Not burning cash on trailing operating cash flow.";
  return "";
}

/** The period line of a cell; a per-cell fallback names its period (4.4). */
export function periodText(cell, col) {
  if (!cell || !cell.period) return "";
  if (cell.tagDiffers) return `No LTM figure for this company, so this cell shows ${cell.period}, marked ${cell.tag || "A"}.`;
  const def = col ? COLUMN_BY_ID[col.id] : null;
  const spot = def && def.bases && def.bases[0] === "-";
  return spot ? `As of ${cell.period}.` : `Period: ${cell.period}.`;
}

/** Lines naming each relevance component, or why it was not scored (4.1). */
export function relevanceLines(rel) {
  if (!rel) return [];
  return RELEVANCE_COMPONENTS.map((c) => {
    const v = rel.components ? rel.components[c.id] : undefined;
    if (isNum(v)) return `${c.label}: ${Math.round(v * 100)}%, weight ${Math.round(c.weight * 100)}%`;
    const miss = (rel.missing || []).find((m) => m.id === c.id);
    return `${c.label}, not scored: ${miss ? miss.reason : "no data"}`;
  });
}

/** Words for where a peer came from: system set with its pool, added by the analyst, saved set. */
export function sourceText(row) {
  if (!row || row.isFocal) return "";
  const base = SOURCE_WORDS[row.source] || "Peer set";
  return row.source === "system" && row.pool && POOL_WORDS[row.pool] ? `${base}, ${POOL_WORDS[row.pool]}` : base;
}

/**
 * The flag lines a cell's tooltip shows (12.7): core.js writes `flagLines` from `marks` alone, so
 * these are the marking flags, plus the ECB translation line a reported-currency market value
 * carries. A cell with neither marks nor that line has none.
 */
export function markLines(cell) {
  return cell && Array.isArray(cell.flagLines) ? cell.flagLines : [];
}

/** Hover and focus tooltip of a data cell, or null when the cell has nothing beyond its value. */
export function cellTip(cell, col, row) {
  if (!cell || !col) return null;
  const lines = [];
  const body = cellReasonText(cell) || null;
  if (cell.tagDiffers) lines.push(periodText(cell, col));
  if (cell.quote) lines.push(cell.quote);
  for (const l of markLines(cell)) lines.push(l);
  const cf = cell.cf;
  if (cf && cf.tooltip) lines.push(cf.tooltip.endsWith(".") ? cf.tooltip : cf.tooltip + ".");
  if (cf && cf.kind === "outlier") {
    lines.push(cf.level === "extreme" ? "Extreme outlier: more than three interquartile ranges beyond the quartiles."
      : "Outlier: more than 1.5 interquartile ranges beyond the quartiles.");
  }
  if (row && row.excluded && col.numeric) lines.push(EXCLUDED_TEXT);
  if (!body && !lines.length) return null;
  if (cell.status === "ok" && cell.period && !cell.tagDiffers) lines.unshift(periodText(cell, col));
  return {title: `${row ? row.ticker + " · " : ""}${col.label}${col.unitText ? ", " + col.unitText : ""}`, body, lines};
}

/** The text of #tb-active-desc for a body cell (7.5): reason, period, flags, then the definition. */
export function describeCell(cell, col, row, cfMode = "off") {
  if (!col) return "";
  const parts = [];
  const r = cellReasonText(cell);
  if (r) parts.push(r);
  if (cell && cell.status === "ok" && cell.period) parts.push(periodText(cell, col));
  const mk = markerFor(cell, col, cfMode);
  if (mk.text === "M") parts.push("Model output.");
  if (cell && cell.quote) parts.push(cell.quote);
  for (const l of markLines(cell)) parts.push(l);
  if (cell && cell.cf && cell.cf.tooltip) parts.push(cell.cf.tooltip.endsWith(".") ? cell.cf.tooltip : cell.cf.tooltip + ".");
  if (row && row.excluded) parts.push(EXCLUDED_TEXT);
  if (col.tooltip) parts.push(col.tooltip);
  return parts.filter(Boolean).join(" ");
}

/**
 * The header's unit line (4.2): "{unit} · {basis chip} · {provenance word}". On the primary
 * column the "Primary" tag leads, so a narrow frozen column still says which metric it is; the
 * rest follows in the same order.
 */
export function unitLineText(col) {
  const line = String((col && col.unitLine) || "");
  const tag = " · Primary";
  if (col && col.isPrimary && line.endsWith(tag)) return `Primary · ${line.slice(0, -tag.length)}`;
  if (col && col.isPrimary && line === "Primary") return line;
  return line;
}

/** Short filter text for a column header: "≥ 10", "≤ 5", "has value", "“us”". */
export function filterShort(f) {
  if (!f) return "";
  if (f.op === ">=") return `≥ ${f.value}`;
  if (f.op === "<=") return `≤ ${f.value}`;
  if (f.op === "has") return "has value";
  return `“${f.value}”`;
}

/**
 * `parseFilterValue(raw)`: a number typed in the header's unit. Accepts a true minus, thousands
 * separators and a trailing "%" or "×". Null when it is not a number.
 */
export function parseFilterValue(raw) {
  const s = String(raw == null ? "" : raw).trim().replace(/[−–]/g, "-").replace(/[,\s%×]/g, "").replace(/x$/i, "");
  if (!s) return null;
  const v = Number(s);
  return Number.isFinite(v) ? v : null;
}

/**
 * `boxHeightFor(mainH, offset)`: the table box's max height (1.2, 1.6). `offset` is how far the
 * box's top sits below the top of #main. At rest the box takes what is left of the view, so its
 * sticky summary rows stay on screen; as #main scrolls the box up, it grows to the whole of
 * #main. Never under BOX_MIN_H unless #main itself is shorter.
 */
export function boxHeightFor(mainH, offset) {
  if (!isNum(mainH) || mainH <= 0) return null;
  const off = Math.max(0, isNum(offset) ? offset : 0);
  const avail = mainH - off - Math.min(BOX_PAD, off);
  return Math.round(clamp(avail, Math.min(BOX_MIN_H, mainH), mainH));
}

/** SORT cycles desc, asc, none: how many SORT actions reach `want` from the current sort. */
export function sortSteps(current, colId, want) {
  const seq = [null, "desc", "asc"];
  const cur = current && current.colId === colId ? current.dir : null;
  const i = seq.indexOf(cur), j = seq.indexOf(want || null);
  if (i < 0 || j < 0) return 0;
  return (j - i + 3) % 3;
}

/**
 * `moveActive(active, key, rowKeys, colIds, opts)`: the next active cell for a grid key.
 * key: up, down, left, right, home, end, pageup, pagedown, first, last. In a summary row the
 * frozen columns (`opts.labelCols`) are one label cell, so right from it goes to the first
 * column after the block and left from the block stays.
 */
export function moveActive(active, key, rowKeys, colIds, opts = {}) {
  if (!rowKeys || !rowKeys.length || !colIds || !colIds.length) return null;
  const dRow = opts.defaultRow && rowKeys.includes(opts.defaultRow) ? opts.defaultRow : rowKeys[Math.min(1, rowKeys.length - 1)];
  const dCol = opts.defaultCol && colIds.includes(opts.defaultCol) ? opts.defaultCol : colIds[0];
  let r = active ? rowKeys.indexOf(active.row) : -1;
  let c = active ? colIds.indexOf(active.col) : -1;
  if (r < 0 || c < 0) return {row: r < 0 ? dRow : active.row, col: c < 0 ? dCol : active.col};
  const page = opts.page || 10;
  const lastR = rowKeys.length - 1, lastC = colIds.length - 1;
  const labelCols = opts.labelCols || new Set();
  const inSummary = String(rowKeys[r]).startsWith("sum:");
  switch (key) {
    case "up": r = Math.max(0, r - 1); break;
    case "down": r = Math.min(lastR, r + 1); break;
    case "pageup": r = Math.max(0, r - page); break;
    case "pagedown": r = Math.min(lastR, r + page); break;
    case "first": r = 0; break;
    case "last": r = lastR; break;
    case "home": c = 0; break;
    case "end": c = lastC; break;
    case "left":
      if (inSummary && labelCols.has(colIds[c])) break;
      c = Math.max(0, c - 1);
      if (inSummary && labelCols.has(colIds[c])) c = 0;
      break;
    case "right":
      if (inSummary && labelCols.has(colIds[c])) {
        const j = colIds.findIndex((id) => !labelCols.has(id));
        c = j < 0 ? c : j;
      } else c = Math.min(lastC, c + 1);
      break;
    default: break;
  }
  return {row: rowKeys[r], col: colIds[c]};
}

/** The DOM id of a cell key (7.4). */
export function cellDomId(key, labelCols = BASE_SET) {
  if (!key || !key.row) return null;
  if (key.row === "head") return `c-head-${key.col}`;
  if (String(key.row).startsWith("sum:")) {
    const sid = key.row.slice(4);
    return labelCols.has(key.col) ? `c-sum-${sid}-label` : `c-sum-${sid}-${key.col}`;
  }
  return `c-${key.row}-${key.col}`;
}

/** Polyline points of a sparkline in a w by h box, 1 px inset top and bottom. */
export function sparkPoints(series, w = 72, h = 14) {
  const v = (series || []).filter(isNum);
  if (v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v);
  const span = hi - lo || 1;
  return v.map((y, i) => `${round1((i / (v.length - 1)) * w)},${round1(h - 1 - ((y - lo) / span) * (h - 2))}`).join(" ");
}

/**
 * `findColumns(query, columns, inTable, limit)`: the column finder's matches over labels and
 * definitions (4.8). Label prefix 4, word start 3, inside the label 2, inside the definition 1;
 * every word of a multi-word query must match somewhere. Ties keep catalogue order.
 */
export function findColumns(query, columns = COLUMNS, inTable = new Set(), limit = 12) {
  const q = String(query || "").trim().toLowerCase();
  const words = q.split(/\s+/).filter(Boolean);
  const scored = [];
  (columns || []).forEach((c, i) => {
    const label = String(c.label || "").toLowerCase();
    const tip = String(c.tooltip || "").toLowerCase();
    let score = 0;
    if (!q) score = 1;
    else if (label.startsWith(q)) score = 4;
    else if (label.split(/[\s/,()-]+/).some((w) => w && w.startsWith(q))) score = 3;
    else if (label.includes(q)) score = 2;
    else if (tip.includes(q)) score = 1;
    else if (words.length > 1 && words.every((w) => label.includes(w) || tip.includes(w))) score = 1;
    if (score) scored.push({c, score, i});
  });
  scored.sort((a, b) => (b.score - a.score) || (a.i - b.i));
  return scored.slice(0, limit).map(({c}) => ({id: c.id, label: c.label, group: GROUP_LABEL[c.group] || "",
    unit: c.unit ? String(c.unit).replace("{cur} ", "") : "", inTable: inTable.has(c.id)}));
}

/**
 * `toolbarModel(T, st, opts)` (12.7): the toolbar's controls, left to right, and nothing else:
 * the column preset, the column finder, the one "View" menu, then the hidden-columns chip while
 * columns are hidden. Each control is `{key, kind, label, value, kbd, count}`; `kind` is "menu",
 * "dialog" or "chip". `opts.findKey` is the finder's key hint ("" when single keys are off).
 */
export function toolbarModel(T, st = {}, opts = {}) {
  const t = T || {};
  const badge = t.viewBadge || {count: 0, lines: [], label: "View"};
  const hidden = Array.isArray(t.hidden) ? t.hidden : [];
  const out = [
    {key: "preset", kind: "menu", label: "Columns:", value: t.presetLabel || t.preset || "", kbd: "", count: 0},
    {key: "find", kind: "dialog", label: "", value: "Find column", kbd: opts.findKey || "", count: 0},
    {key: "view", kind: "menu", label: "", value: badge.label || "View", kbd: "", count: badge.count || 0},
  ];
  if (hidden.length) out.push({key: "hidden", kind: "chip", label: "", value: `${hidden.length} hidden`, kbd: "", count: hidden.length});
  return out;
}

/** The toolbar's markup for `toolbarModel` (12.7). Every control carries `data-tb` and `data-key`. */
export function toolbarHtml(model) {
  let h = "";
  for (const c of model || []) {
    const caret = `<span class="tb-caret" aria-hidden="true">▾</span>`;
    const k = esc(c.key);
    if (c.kind === "chip") {
      h += `<button type="button" class="u-chip tb-hid" data-tb="${k}" data-key="tb:${k}" aria-haspopup="menu"><span class="u-chip-label">${esc(c.value)}</span>${caret}</button>`;
      continue;
    }
    const lab = c.label ? `<span class="tb-bl">${esc(c.label)}</span> ` : "";
    const kbd = c.kbd ? `<kbd class="u-kbd">${esc(c.kbd)}</kbd>` : "";
    const on = c.key === "view" && c.count > 0 ? " tb-on" : "";
    h += `<button type="button" class="u-btn tb-b${on}" data-tb="${k}" data-key="tb:${k}" aria-haspopup="${c.kind === "dialog" ? "dialog" : "menu"}">`
      + `${lab}<span class="tb-bv">${esc(c.value)}</span>${kbd}${c.kind === "menu" ? caret : ""}</button>`;
  }
  return h;
}

/**
 * `toolbarTips(T, st, opts)`: the tooltip of each toolbar control, keyed like `toolbarModel`.
 * The View tooltip lists the settings away from their defaults (`viewBadge.lines`, 12.7).
 * opts: {keys: boolean (single keys on), storageOk: boolean}.
 */
export function toolbarTips(T, st = {}, opts = {}) {
  const t = T || {};
  const on = opts.keys !== false;
  const badge = t.viewBadge || {count: 0, lines: []};
  const hidden = Array.isArray(t.hidden) ? t.hidden : [];
  const tips = new Map();
  tips.set("preset", {title: "Column presets", body: "A preset sets the columns after the frozen block. The frozen company columns stay in every preset.",
    lines: [on ? "Keys 1 to 7 pick the presets in menu order." : "", PRESET_FOOTNOTE].filter(Boolean)});
  tips.set("find", {title: "Find a column", body: "Search metrics and their definitions. Enter shows the column and focuses the focal company's cell.", lines: []});
  const lines = (badge.lines || []).map((l) => (/[.!?]$/.test(l) ? l : `${l}.`));
  if (t.cfMode && t.cfMode !== "off") lines.push(CF_CAUTION);
  if (on) lines.push("U switches outliers, V the format, D the density. + and - change the text size.");
  tips.set("view", {title: "View",
    body: badge.count ? `${badge.count} ${badge.count === 1 ? "setting" : "settings"} away from the default.`
      : "Statistics group, outliers, conditional format, density, text size, summary rows and saved layouts. Every setting is at its default.",
    lines});
  if (hidden.length) {
    tips.set("hidden", {title: `${hidden.length} hidden ${hidden.length === 1 ? "column" : "columns"}`,
      body: hidden.map((id) => (COLUMN_BY_ID[id] ? COLUMN_BY_ID[id].label : id)).join(", "), lines: []});
  }
  return tips;
}

const cap = (w) => `${String(w).charAt(0).toUpperCase()}${String(w).slice(1)}`;
const low = (w) => `${String(w).charAt(0).toLowerCase()}${String(w).slice(1)}`;

/**
 * `viewMenuModel(view, st, opts)` (12.7): the items of the one "View" menu, in order. Seven
 * groups, each under a `{kind: "head", label}` item, then a closing `{kind: "note"}`:
 * Statistics over, Outliers in statistics, Conditional format, Density, Text size, Rows, Layouts.
 *
 * A selectable item is `{id, group, label, checked?, shortcut?, disabled?, reason?, actions?, run?,
 * stamp?, say?}`. `checked` is a boolean for a radio or a check and absent for a plain action.
 * `actions` are core.js actions to dispatch in order (`stamp` adds `now`); `run` names what the
 * mount does itself: "saveLayout", "resetLayout", "pinFocal", "summaryExpanded". `say` is the
 * announcement. A `shortcut` sits on the item its key would pick now: `u` on the other outlier
 * setting, `v` and `d` on the next mode in their cycles, `+` and `-` on the neighbouring sizes.
 *
 * opts: {layout, focalPinned, storageOk, keys (single keys on)}.
 */
export function viewMenuModel(view, st = {}, opts = {}) {
  const T = (view && view.table) || {};
  const layout = normLayout(opts.layout);
  const keys = opts.keys !== false;
  const key = (k) => (keys ? k : null);
  const items = [];
  const head = (id) => items.push({kind: "head", id: `head:${id}`, group: id, label: VIEW_GROUPS.find((g) => g.id === id).label});

  // Statistics over
  head("stats");
  const groups = (view && view.peers && Array.isArray(view.peers.subgroups)) ? view.peers.subgroups
    : SYSTEM_SUBGROUPS.map((name) => ({name, system: true, tickers: null}));
  const cur = st.statsGroup && st.statsGroup !== "all" ? st.statsGroup : "all";
  items.push({id: "stats:all", group: "stats", label: "All included peers", checked: cur === "all",
    actions: [{type: "SET_STATS_GROUP", group: "all"}], say: "Statistics over all included peers"});
  for (const g of groups) {
    const n = Array.isArray(g.tickers) ? g.tickers.length : null;
    items.push({id: `stats:${g.name}`, group: "stats", label: n == null ? g.name : `${g.name}, ${n}`, checked: cur === g.name,
      disabled: n === 0, reason: n === 0 ? "No peer in the set falls in this group." : null,
      actions: [{type: "SET_STATS_GROUP", group: g.name}], say: `Statistics over ${g.name}`});
  }

  // Outliers in statistics
  head("outliers");
  const outEx = st.outliers === "exclude";
  items.push({id: "outliers:include", group: "outliers", label: "Included", checked: !outEx, shortcut: outEx ? key("u") : null,
    actions: [{type: "SET_OUTLIERS", mode: "include"}], say: "Statistics include outliers"});
  items.push({id: "outliers:exclude", group: "outliers", label: "Excluded", checked: outEx, shortcut: outEx ? null : key("u"),
    actions: [{type: "SET_OUTLIERS", mode: "exclude"}], say: "Statistics exclude outliers, column by column"});

  // Conditional format
  head("cf");
  const cf = CF_MODES.includes(T.cfMode) ? T.cfMode : (CF_MODES.includes(st.cfMode) ? st.cfMode : "off");
  const cfNext = CF_MODES[(CF_MODES.indexOf(cf) + 1) % CF_MODES.length];
  for (const m of CF_MODES) {
    items.push({id: `cf:${m}`, group: "cf", label: CF_MODE_LABEL[m] || m, checked: cf === m, shortcut: m === cfNext ? key("v") : null,
      actions: [{type: "SET_CF_MODE", mode: m}], say: `Format: ${low(CF_MODE_LABEL[m] || m)}`});
  }

  // Density
  head("density");
  const den = DENSITIES.includes(T.density) ? T.density : (DENSITIES.includes(st.density) ? st.density : "default");
  const denNext = DENSITIES[(DENSITIES.indexOf(den) + 1) % DENSITIES.length];
  for (const d of DENSITIES) {
    items.push({id: `density:${d}`, group: "density", label: `${cap(d)} rows`, checked: den === d, shortcut: d === denNext ? key("d") : null,
      actions: [{type: "SET_DENSITY", density: d}], say: `${cap(d)} rows`});
  }

  // Text size
  head("text");
  const size = isNum(T.textSize) ? T.textSize : (isNum(st.textSize) ? st.textSize : TEXT_SIZES[0]);
  for (const s of TEXT_SIZES) {
    items.push({id: `text:${s}`, group: "text", label: `Text ${s} px`, checked: size === s,
      shortcut: s === size + 1 ? key("+") : (s === size - 1 ? key("-") : null),
      actions: [{type: "SET_TEXT_SIZE", size: s}], say: `Text ${s} pixels`});
  }

  // Rows
  head("rows");
  const sumOn = st.summaryRows !== false;
  items.push({id: "rows:summary", group: "rows", label: "Summary rows", checked: sumOn,
    actions: [{type: "TOGGLE_SUMMARY_ROWS"}], say: sumOn ? "Summary rows hidden; the n row stays" : "Summary rows shown"});
  if (autoPinsPrimary(layout)) {
    const ex = !!((st.summaryExpanded || {})[layout]);
    items.push({id: "rows:expanded", group: "rows", label: "Mean and quartiles in the summary", checked: ex,
      disabled: !sumOn, reason: sumOn ? null : "Summary rows are off.", run: "summaryExpanded"});
  }
  const pinned = opts.focalPinned !== false;
  items.push({id: "rows:pinfocal", group: "rows", label: "Pin the focal row", checked: pinned, run: "pinFocal",
    say: pinned ? "Focal row takes its sorted place" : "Focal row pinned first"});

  // Layouts
  head("layouts");
  const names = Object.keys(st.layouts || {}).sort((a, b) => a.localeCompare(b));
  items.push({id: "layouts:save", group: "layouts", label: "Save layout", run: "saveLayout"});
  for (const n of names) {
    items.push({id: `layouts:load:${n}`, group: "layouts", label: `Load ${n}`, actions: [{type: "LOAD_LAYOUT", name: n}], say: `Loaded layout ${n}`});
    items.push({id: `layouts:delete:${n}`, group: "layouts", label: `Delete ${n}`, actions: [{type: "DELETE_LAYOUT", name: n}], stamp: true,
      say: `Deleted layout ${n}. Undo with ${opts.isMac ? "Command" : "Control"} Z.`});
  }
  items.push({id: "layouts:reset", group: "layouts", label: "Reset columns, widths and sort", shortcut: key("shift+r"), run: "resetLayout"});
  items.push({kind: "note", id: "note", group: "layouts", label: opts.storageOk === false ? STATE_COPY.storage_unavailable.detail : SAVED_HERE, disabled: true});
  return items;
}

function inclState(row, outliersMode) {
  const T = row.ticker;
  if (row.error) return {glyph: "✕", cls: "is-err", label: `Calculation failed for ${T}, so it is not in statistics.`};
  if (row.excluded) return {glyph: "○", cls: "is-out", label: `${T} excluded from statistics. Include it again.`};
  if (outliersMode === "exclude" && row.outlier) {
    return {glyph: "◇", cls: "is-outlier", label: `${T} is an outlier on the primary metric and is left out of that column's statistics. Exclude it from all statistics.`};
  }
  return {glyph: "●", cls: "is-in", label: `${T} in statistics. Exclude it.`};
}

// ---------------------------------------------------------------------------------------------
// Mount
// ---------------------------------------------------------------------------------------------

/**
 * `mountTable(root, ctx)`: builds the toolbar, the table box and `#tb-active-desc` in `root`.
 * ctx (11.1): {dispatch, getState, getView, openDetail, closeDetail, openMethod, announce,
 * tooltip: {show, hide, describe}, menu: {open, close}, toast, storageOk, layout, ...}.
 */
export function mountTable(root, ctx = {}) {
  const doc = root.ownerDocument || document;
  const win = doc.defaultView || globalThis;
  const nav = win.navigator || {};
  const isMac = /Mac|iPhone|iPad/.test(String(nav.platform || nav.userAgent || ""));

  root.classList.add("tb");
  root.setAttribute("aria-busy", "true");
  if (!root.getAttribute("aria-label") && !root.getAttribute("aria-labelledby")) root.setAttribute("aria-labelledby", "tb-title");
  root.innerHTML = `<h2 class="u-sr" id="tb-title">Comparable companies</h2>`
    + `<div class="tb-bar" role="group" aria-label="Table controls"></div>`
    + `<div class="tb-box"><table class="tb-grid" id="tb-grid" role="grid" tabindex="0" aria-describedby="tb-active-desc"></table>`
    + `<div class="tb-skel" aria-hidden="true">${"<span class=\"u-skeleton\"></span>".repeat(8)}</div></div>`
    + `<div id="tb-active-desc" class="u-sr"></div><div class="tb-tipdesc u-sr"></div>`
    + `<style class="tb-fzstyle"></style>`;
  const bar = root.querySelector(".tb-bar");
  const box = root.querySelector(".tb-box");
  const table = root.querySelector(".tb-grid");
  const desc = root.querySelector("#tb-active-desc");
  const tipDesc = root.querySelector(".tb-tipdesc");
  const fzStyle = root.querySelector(".tb-fzstyle");

  let view = null;
  let L = {cols: [], frozenCount: 0, frozenWidth: 0};
  let layoutName = "wide";
  let rowsShown = [];
  let rowKeys = [];
  let colIds = [];
  let labelCols = BASE_SET;
  let summaryIds = [];
  let active = null;
  let lastActiveIndex = 0;
  let lastSent = null;
  let sendTimer = null;
  let pendingFocus = null;
  let pendingScrollCol = null;
  let focalPinned = true;
  let pop = null;
  let finderOpen = false;
  let rendering = false;
  let hoverEl = null;
  let hoverTimer = null;
  let tipAnchor = null;
  let barTips = new Map();
  let drag = null;
  let roTimer = null;
  let lastBoxWidth = 0;
  let destroyed = false;
  let firstRender = true;
  let pointerFocus = false;
  let pointerTimer = null;
  let pendingTop = null;
  let sortSeen = null;
  let lastFit = null;
  let fitRaf = null;
  let mainEl = null;

  // ----- ctx helpers -----
  const getState = () => { try { return (ctx.getState && ctx.getState()) || {}; } catch (e) { return {}; } };
  const dispatch = (a) => { if (typeof ctx.dispatch === "function") ctx.dispatch(a); };
  const announce = (t) => { if (t && typeof ctx.announce === "function") ctx.announce(t); };
  const storageOk = () => (typeof ctx.storageOk === "function" ? ctx.storageOk() : ctx.storageOk !== false);
  const now = () => Date.now();
  function getLayout() {
    const l = typeof ctx.layout === "function" ? ctx.layout() : ctx.layout;
    if (l && LAYOUT_WIDTHS[l]) return l;
    const app = doc.getElementById("app");
    const a = app && app.getAttribute("data-layout");
    return a && LAYOUT_WIDTHS[a] ? a : "wide";
  }
  function hint(cmdId) {
    const c = COMMAND_BY_ID[cmdId];
    return c ? commandHint(getState(), c, isMac) : "";
  }
  function keysOn() { return getState().singleKeys !== false; }
  function showTip(anchor, content) {
    if (!content || !ctx.tooltip || typeof ctx.tooltip.show !== "function") return;
    tipAnchor = anchor;
    ctx.tooltip.show(anchor, content);
  }
  function hideTip() {
    tipAnchor = null;
    if (ctx.tooltip && typeof ctx.tooltip.hide === "function") ctx.tooltip.hide();
  }
  function openDetail(ticker) {
    if (!ticker) return;
    if (typeof ctx.openDetail === "function") ctx.openDetail(ticker);
    else dispatch({type: "OPEN_DETAIL", ticker});
  }
  function openMenu(anchor, items, opts) {
    if (ctx.menu && typeof ctx.menu.open === "function") {
      ctx.menu.open(anchor, items, opts);
      if (opts && opts.cls) tagMenu(opts.cls);
      return;
    }
    fallbackMenu(anchor, items, opts);
  }
  /**
   * Give the shared menu just opened a class of this sheet (the View menu's own max height,
   * 12.7), then keep its foot inside the frame: the shell placed it at the shared height.
   */
  function tagMenu(cls) {
    const all = doc.querySelectorAll(".u-menu[role='menu']");
    const el = all.length ? all[all.length - 1] : null;
    if (!el || (pop && pop.el.contains(el))) return;
    el.classList.add(cls);
    const vh = win.innerHeight || 0;
    const r = el.getBoundingClientRect();
    if (vh && r.bottom > vh - 8) el.style.top = `${Math.max(8, Math.round(vh - 8 - r.height))}px`;
  }
  function colView(id) { return L.cols.find((c) => c.id === id) || null; }
  function rowView(t) { return rowsShown.find((r) => r.ticker === t) || null; }
  function focalTicker() { return view && view.focal ? view.focal.ticker : null; }

  // ------------------------------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------------------------------

  function update(v) {
    if (destroyed) return;
    view = v || null;
    render();
  }

  function render() {
    if (!view) return;
    rendering = true;
    try {
      root.removeAttribute("aria-busy");
      const skel = box.querySelector(".tb-skel");
      if (skel) skel.remove();
      const st = getState();
      layoutName = getLayout();
      root.setAttribute("data-layout", layoutName);
      const T = view.table;
      if (!T) {
        renderSectionError();
        return;
      }
      root.setAttribute("data-density", T.density || "default");
      lastBoxWidth = box.clientWidth || lastBoxWidth;
      L = layoutColumns(T.columns, layoutName, {widths: st.widths || {}, boxWidth: lastBoxWidth || undefined});
      labelCols = new Set(BASE_IDS);
      rowsShown = placeFocal(T.rows, T.sort, focalPinned);
      const expanded = !!((st.summaryExpanded || {})[layoutName]);
      summaryIds = visibleSummaryIds(T.summaryVisible, layoutName, expanded)
        .filter((id) => (T.summary || []).some((s) => s.id === id));
      rowKeys = ["head"].concat(rowsShown.map((r) => r.ticker), summaryIds.map((id) => `sum:${id}`));
      colIds = L.cols.map((c) => c.id);
      syncFocusFromState(st);
      const top = box.scrollTop, left = box.scrollLeft;
      rebuildKeep(table, tableHtml(T, st));
      writeFrozenStyle();
      box.scrollTop = top;
      box.scrollLeft = left;
      renderBar(T, st);
      fitBox();
      if (pendingTop && T.sort !== sortSeen) {
        if (colIds.includes(pendingTop) && rowKeys.length > 1) { active = {row: rowKeys[1], col: pendingTop}; box.scrollTop = 0; scheduleSend(); }
        pendingTop = null;
      }
      sortSeen = T.sort;
      const moved = validateActive();
      // A row that left the table hands focus to its neighbour: keep that cell in view.
      applyActive({scroll: moved && table.classList.contains("is-focused")});
      if (tipAnchor && !tipAnchor.isConnected) hideTip();
      if (firstRender) {
        firstRender = false;
        const vp = ctx.initialViewport;
        if (vp && typeof vp === "object") {
          if (isNum(vp.scrollTop)) box.scrollTop = vp.scrollTop;
          if (isNum(vp.scrollLeft)) box.scrollLeft = vp.scrollLeft;
        }
      }
      if (pendingFocus) {
        const pf = pendingFocus;
        if (doc.getElementById(cellDomId(pf, labelCols))) { pendingFocus = null; focusKey(pf); }
      }
      if (pendingScrollCol) {
        const c = pendingScrollCol;
        if (doc.getElementById(`c-head-${c}`)) { pendingScrollCol = null; scrollToColumn(c); }
      }
      syncFinder(st);
    } finally {
      rendering = false;
    }
  }

  function renderSectionError() {
    const err = (view.sectionErrors && view.sectionErrors.table) || {severity: "red",
      title: "This section could not be computed", detail: "Comparable companies table failed. The rest of the view is unaffected."};
    table.innerHTML = "";
    bar.innerHTML = "";
    let note = box.querySelector(".tb-secerr");
    if (!note) { note = doc.createElement("div"); note.className = "tb-secerr"; box.prepend(note); }
    note.innerHTML = stateHtml(err);
    rowKeys = []; colIds = []; active = null;
    applyActive({});
  }

  function stateHtml(msg, extraAction) {
    if (!msg) return "";
    const tone = msg.severity === "red" ? " red" : msg.severity === "amber" ? " amber" : "";
    const act = msg.action || extraAction || null;
    const btn = act ? `<button type="button" class="u-btn u-state-action" data-act="state" data-cmd="${esc(act.command)}" data-key="state:${esc(act.command)}">${esc(act.label)}</button>` : "";
    return `<div class="u-state${tone}"${msg.severity === "red" ? " role=\"alert\"" : ""}><p class="u-state-title">${esc(msg.title)}</p><p class="u-state-detail">${esc(msg.detail)}</p>${btn}</div>`;
  }

  function tableHtml(T, st) {
    const cols = L.cols;
    const nCols = cols.length + 1;
    const lastFz = L.frozenCount - 1;
    const info = {
      nCols, lastFz, cfMode: T.cfMode || "off", rep: !!(view.ctx && view.ctx.currency === "REPORTED"),
      selected: (st.ui && st.ui.detail) || (view.detail && view.detail.ticker) || null,
      outliers: st.outliers || "include", storage: storageOk(),
    };
    const sec = box.querySelector(".tb-secerr");
    if (sec) sec.remove();
    let h = `<caption class="u-sr">${esc(T.caption || "Comparable companies")}</caption><colgroup>`;
    for (const c of cols) h += `<col data-col="${esc(c.id)}" style="width:${c.width}px">`;
    h += `<col class="tb-fillc"></colgroup><thead><tr class="tb-grp" role="row">`;
    for (const g of groupRuns(cols)) {
      const fz = g.frozen ? ` tb-fz tb-fz-${g.start}${g.end === lastFz ? " tb-fzlast" : ""}` : "";
      h += `<th role="columnheader" scope="colgroup" colspan="${g.span}" class="tb-g${fz}${g.groupStart ? " tb-gs" : ""}">${esc(g.label)}</th>`;
    }
    h += `<th class="tb-fill" aria-hidden="true"></th></tr><tr class="tb-hrow" role="row">`;
    cols.forEach((c, i) => { h += headHtml(c, i, lastFz); });
    h += `<th class="tb-fill" aria-hidden="true"></th></tr></thead><tbody>`;
    const focalSticky = focalPinned;
    rowsShown.forEach((r) => { h += rowHtml(r, info, focalSticky); });
    if (T.empty) {
      const extra = T.empty.id === "filters_empty" ? {label: "Clear filters", command: "filters.reset"} : null;
      h += `<tr role="row" class="tb-emptyr"><td role="gridcell" colspan="${nCols}" class="tb-emptyc"><div class="tb-emptyin">${stateHtml(T.empty, extra)}</div></td></tr>`;
    }
    h += `</tbody>`;
    if (summaryIds.length) h += summaryHtml(T, info);
    return h;
  }

  function headHtml(c, i, lastFz) {
    const fz = c.frozen ? ` tb-fz tb-fz-${i}${i === lastFz ? " tb-fzlast" : ""}` : "";
    const gs = c.groupStart ? " tb-gs" : "";
    if (c.id === "exp") {
      return `<th role="columnheader" id="c-head-exp" class="tb-h tb-hx${fz}" data-col="exp" aria-label="Expand row"></th>`;
    }
    if (c.id === "incl") {
      return `<th role="columnheader" id="c-head-incl" class="tb-h tb-hx${fz}" data-col="incl" aria-label="In statistics"><span class="tb-hglyph" aria-hidden="true">●</span></th>`;
    }
    const num = c.numeric ? " num" : "";
    const sorted = c.sortDir ? " tb-sorted" : "";
    const aria = c.sortDir ? ` aria-sort="${c.sortDir === "desc" ? "descending" : "ascending"}"` : "";
    const sortG = c.sortDir ? `<span class="tb-hsort" aria-hidden="true">${c.sortDir === "desc" ? "▼" : "▲"}</span>` : "";
    const filt = c.filter ? `<span class="tb-hfilt">${esc(filterShort(c.filter))}</span>` : "";
    const rs = NO_RESIZE.has(c.id) ? "" : `<span class="tb-rs" data-act="resize" aria-hidden="true"></span>`;
    return `<th role="columnheader" scope="col" id="c-head-${esc(c.id)}" data-col="${esc(c.id)}" class="tb-h${num}${fz}${gs}${sorted}${c.isPrimary ? " tb-primary" : ""}"${aria}>`
      + `<span class="tb-hin"><span class="tb-hl"><span class="tb-hlab">${esc(c.label)}</span>${sortG}${filt}</span>`
      + `<span class="tb-hu">${esc(unitLineText(c))}</span></span>`
      + `<button type="button" class="tb-hmenu" tabindex="-1" data-act="hmenu" aria-label="Column menu, ${esc(c.label)}">▾</button>${rs}</th>`;
  }

  function rowHtml(r, info, focalSticky) {
    const cls = ["tb-r"];
    if (r.isFocal) cls.push("tb-focal", "u-on-wash");
    if (r.isFocal && focalSticky) cls.push("tb-stick");
    if (r.excluded) cls.push("tb-excl");
    if (r.error) cls.push("tb-err");
    const sel = info.selected === r.ticker;
    if (sel) cls.push("tb-sel");
    let h = `<tr role="row" class="${cls.join(" ")}" data-row="${esc(r.ticker)}"${sel ? " aria-selected=\"true\"" : ""}>`;
    L.cols.forEach((c, i) => { h += cellHtml(r, c, i, info); });
    h += `<td class="tb-fill" aria-hidden="true"></td></tr>`;
    if (r.expanded && !r.isFocal) h += subRowHtml(r, info);
    return h;
  }

  function cellHtml(r, c, i, info) {
    const id = `c-${esc(r.ticker)}-${esc(c.id)}`;
    const fz = c.frozen ? ` tb-fz tb-fz-${i}${i === info.lastFz ? " tb-fzlast" : ""}` : "";
    const gs = c.groupStart ? " tb-gs" : "";
    const T = esc(r.ticker);
    switch (c.id) {
      case "exp":
        if (r.isFocal) return `<td role="gridcell" id="${id}" class="tb-c tb-exp${fz}" data-col="exp"></td>`;
        return `<td role="gridcell" id="${id}" class="tb-c tb-exp${fz}" data-col="exp"><button type="button" class="tb-xbtn" tabindex="-1" data-act="expand" aria-expanded="${r.expanded ? "true" : "false"}" aria-label="${r.expanded ? "Collapse" : "Expand"} ${T}">${r.expanded ? "⌄" : "›"}</button></td>`;
      case "incl": {
        if (r.isFocal) return `<td role="gridcell" id="${id}" class="tb-c tb-incl${fz}" data-col="incl" aria-label="Focal company, not in statistics"></td>`;
        const s = inclState(r, info.outliers);
        return `<td role="gridcell" id="${id}" class="tb-c tb-incl ${s.cls}${r.excluded ? " u-hatch" : ""}${fz}" data-col="incl"><button type="button" class="tb-ibtn" tabindex="-1" data-act="exclude" aria-label="${esc(s.label)}"${r.error ? " disabled" : ""}>${s.glyph}</button></td>`;
      }
      case "rel": {
        if (r.isFocal || !r.relevance) return `<td role="gridcell" id="${id}" class="tb-c tb-rel${fz}" data-col="rel"></td>`;
        const n = LEVEL_BARS[r.relevance.level] || 0;
        const plus = r.source === "analyst" ? `<span class="tb-plus" aria-hidden="true">+</span>` : "";
        const sr = `Relevance ${r.relevance.score}, ${r.relevance.level}${r.source === "analyst" ? ", added by you" : ""}`;
        return `<td role="gridcell" id="${id}" class="tb-c tb-rel${fz}" data-col="rel"><span class="tb-in"><span class="tb-fit" data-n="${n}" aria-hidden="true"><i></i><i></i><i></i></span>${plus}<span class="u-sr">${esc(sr)}</span></span></td>`;
      }
      case "company":
        return `<th role="rowheader" scope="row" id="${id}" class="tb-c tb-co${fz}" data-col="company"><span class="tb-in tb-coname">${esc(r.name)}</span></th>`;
      case "ticker": {
        // 12.7: the marker follows `row.tickerFlags` alone, never every amber flag on the row.
        return `<td role="gridcell" id="${id}" class="tb-c tb-tk${fz}" data-col="ticker"><span class="tb-in"><span class="u-ticker">${T}</span>${tickerMarkHtml(r)}</span></td>`;
      }
      default:
        return dataCellHtml(r, c, id, fz + gs, info);
    }
  }

  function nullSpan(cell) {
    const st = cell ? cell.status : "na";
    if (st === "nm") return `<span class="tb-v u-nm">n.m.</span>`;
    if (st === "nb") return `<span class="tb-v u-noburn">no burn</span>`;
    return `<span class="tb-v u-null">${NULL}</span>`;
  }

  function dataCellHtml(r, c, id, extra, info) {
    const cell = r.cells ? r.cells[c.id] : null;
    const cls = ["tb-c"];
    if (c.numeric) cls.push("num");
    const tail = `id="${id}" data-col="${esc(c.id)}"`;
    if (!cell) return `<td role="gridcell" ${tail} class="${cls.join(" ")}${extra}"><span class="tb-in">${nullSpan(null)}</span></td>`;
    let inner = "", bar = "", pre = "";
    if (c.fmt === "spark") {
      inner = sparkHtml(cell);
    } else if (c.fmt === "chip") {
      inner = cell.status === "ok" && cell.text
        ? `<span class="u-chip${cell.tone === "clinical" ? " clinical" : ""}"><span class="u-chip-label">${esc(cell.text)}</span></span>` : nullSpan(cell);
    } else if (!c.numeric) {
      inner = cell.status === "ok" && cell.text ? `<span class="tb-v">${esc(cell.text)}</span>` : nullSpan(cell);
    } else {
      const cf = cell.cf;
      const wash = !r.isFocal;
      if (cf) {
        if (cf.kind === "premium" && isNum(cf.frac)) {
          bar = `<span class="tb-cfbar prem" data-side="${cf.side === "left" ? "left" : "right"}" style="--f:${round3(cf.frac)}" aria-hidden="true"></span><span class="tb-cftick" aria-hidden="true"></span>`;
          cls.push("tb-hasbar");
        } else if (cf.kind === "percentile" && isNum(cf.frac)) {
          bar = `<span class="tb-cfbar pct" style="--f:${round3(cf.frac)}" aria-hidden="true"></span>`;
          cls.push("tb-hasbar");
        } else if (cf.kind === "trend") {
          pre = `<span class="u-dir ${cf.dir === "up" ? "up" : "down"} tb-pre" aria-hidden="true">${cf.dir === "up" ? "▲" : "▼"}</span>`;
          if (wash) cls.push(cf.dir === "up" ? "tb-upwash" : "tb-downwash");
        } else if (cf.kind === "outlier") {
          pre = `<span class="tb-pre tb-oglyph${cf.level === "extreme" ? " extreme" : ""}" aria-hidden="true">◆</span>`;
          if (cf.level === "extreme" && wash) cls.push("tb-hatch");
        } else if (cf.kind === "quality" && cf.flagged && wash) {
          cls.push("tb-flagwash", "u-on-wash");
        }
      }
      const val = cell.status === "ok"
        ? `<span class="tb-v${cellMarked(cell) ? " u-flagged" : ""}">${esc(cell.text)}</span>` : nullSpan(cell);
      const mk = markerFor(cell, c, info.cfMode);
      const cur = info.rep && MONEY_FMTS.has(c.fmt) ? `<span class="u-cur-slot">${esc(cell.unit || "")}</span>` : "";
      inner = `${pre}${val}${cur}<span class="u-marker${mk.tone === "amber" ? " amber" : ""}${mk.text === "d" ? " tb-lc" : ""}" aria-hidden="true">${esc(mk.text)}</span>`;
    }
    return `<td role="gridcell" ${tail} class="${cls.join(" ")}${extra}">${bar}<span class="tb-in">${inner}</span></td>`;
  }

  function sparkHtml(cell) {
    const s = cell && cell.status === "ok" && Array.isArray(cell.series) ? cell.series.filter(isNum) : [];
    if (s.length < 2) return nullSpan(cell && cell.status === "ok" ? {status: "na"} : cell);
    const first = s[0], last = s[s.length - 1];
    const label = `Closes over 90 days, from ${fmtNumber(first, 2)} to ${fmtNumber(last, 2)} USD`;
    return `<svg class="tb-spark" viewBox="0 0 72 14" width="72" height="14" role="img" aria-label="${esc(label)}" focusable="false"><polyline points="${sparkPoints(s, 72, 14)}"></polyline></svg>`;
  }

  function subRowHtml(r, info) {
    const rel = r.relevance || {score: null, level: "", components: {}, missing: []};
    const comps = RELEVANCE_COMPONENTS.map((c) => {
      const v = rel.components ? rel.components[c.id] : undefined;
      if (isNum(v)) {
        const p = Math.round(v * 100);
        return `<li class="tb-comp"><span class="tb-comp-l">${esc(c.label)}</span><span class="tb-comp-bar" aria-hidden="true"><i style="width:${p}%"></i></span><span class="tb-comp-v">${p}%</span></li>`;
      }
      const miss = (rel.missing || []).find((m) => m.id === c.id);
      return `<li class="tb-comp is-miss"><span class="tb-comp-l">${esc(c.label)}</span><span class="tb-comp-miss">not scored: ${esc(miss ? miss.reason : "no data")}</span></li>`;
    }).join("");
    const t = esc(r.ticker);
    const noteHint = info.storage ? "Saved in this browser only" : STATE_COPY.storage_unavailable.detail;
    return `<tr role="row" class="tb-sub${r.excluded ? " tb-excl" : ""}" data-sub="${t}"><td role="gridcell" colspan="${info.nCols}" class="tb-subc"><div class="tb-subin">`
      + `<div class="tb-sub-rel"><p class="tb-sub-h"><span class="u-label">Relevance</span> <span class="tb-sub-score">${rel.score == null ? NULL : esc(rel.score)}</span> <span class="tb-sub-meta">of 100, ${esc(rel.level || "")}</span></p><ul class="tb-comps">${comps}</ul></div>`
      + `<div class="tb-sub-src"><p class="tb-sub-h"><span class="u-label">Source</span> <span>${esc(sourceText(r))}</span></p>`
      + `<p class="tb-sub-reason">${esc(r.reason || "")}</p>`
      + `<div class="tb-note-row"><label class="u-label" for="tb-note-${t}">Inclusion note</label><input type="text" id="tb-note-${t}" class="u-input tb-note" data-act="note" data-ticker="${t}" data-key="note:${t}" value="${esc(r.note || "")}" maxlength="280" placeholder="Why this peer is in or out" aria-describedby="tb-note-hint-${t}">`
      + `<span class="tb-sub-meta tb-note-hint" id="tb-note-hint-${t}">${esc(noteHint)}</span></div></div>`
      + `<div class="tb-sub-act"><button type="button" class="u-btn" data-act="open" data-key="open:${t}">Open details</button>`
      + `<button type="button" class="u-btn" data-act="exclude" data-key="excl:${t}">${r.excluded ? "Include" : "Exclude from statistics"}</button></div>`
      + `</div></td></tr>`;
  }

  function summaryHtml(T, info) {
    const cols = L.cols;
    const baseCount = cols.filter((c) => c.pin === "base").length;
    const canExpand = autoPinsPrimary(layoutName) && (T.summaryVisible || []).length > SUMMARY_SHORT.length;
    const st = getState();
    const expanded = !!((st.summaryExpanded || {})[layoutName]);
    const byId = Object.fromEntries((T.summary || []).map((s) => [s.id, s]));
    let h = `<tfoot>`;
    summaryIds.forEach((sid, k) => {
      const s = byId[sid];
      const fromBottom = summaryIds.length - 1 - k;
      const bottom = ` style="bottom:calc(var(--row-h-sum) * ${fromBottom})"`;
      const first = k === 0;
      const btn = first && canExpand
        ? `<button type="button" class="u-btn link tb-sexp" data-act="sumexp" data-key="sumexp">${expanded ? "Hide mean and quartiles" : "Show mean and quartiles"}</button>` : "";
      const lastBase = baseCount - 1 === L.frozenCount - 1 ? " tb-fzlast" : "";
      h += `<tr role="row" class="tb-s${first ? " tb-s-first" : ""}" data-row="sum:${sid}">`;
      h += `<th role="rowheader" scope="row" id="c-sum-${sid}-label" colspan="${baseCount}" class="tb-slab tb-fz tb-fz-0${lastBase}"${bottom}><span class="tb-slab-in"><span class="tb-slab-t">${esc(s ? s.label : sid)}</span>${btn}</span></th>`;
      cols.forEach((c, i) => {
        if (c.pin === "base") return;
        const fz = c.frozen ? ` tb-fz tb-fz-${i}${i === info.lastFz ? " tb-fzlast" : ""}` : "";
        const gs = c.groupStart ? " tb-gs" : "";
        const sc = s && s.cells ? s.cells[c.id] : null;
        h += `<td role="gridcell" id="c-sum-${sid}-${esc(c.id)}" data-col="${esc(c.id)}" class="tb-c${c.numeric ? " num" : ""}${fz}${gs}"${bottom}>${summaryInner(sc, c, info)}</td>`;
      });
      h += `<td class="tb-fill" aria-hidden="true"${bottom}></td></tr>`;
    });
    return h + `</tfoot>`;
  }

  function summaryInner(sc, c, info) {
    if (!c.numeric || !sc) return "";
    const txt = sc.text == null || sc.text === "" ? "" : sc.text;
    if (txt === "") return "";
    const val = txt === NULL ? `<span class="tb-v u-null">${NULL}</span>` : `<span class="tb-v">${esc(txt)}</span>`;
    const cur = info.rep && MONEY_FMTS.has(c.fmt) ? `<span class="u-cur-slot"></span>` : "";
    const mk = sc.lowN ? `<span class="u-marker amber" aria-hidden="true">•</span>` : `<span class="u-marker" aria-hidden="true"></span>`;
    return `<span class="tb-in">${val}${cur}${mk}</span>`;
  }

  /** Size the box to the part of #main it can show (1.6): see boxHeightFor. */
  function fitBox() {
    const main = doc.getElementById("main");
    if (!main || !main.contains(box)) { if (lastFit !== null) { lastFit = null; box.style.maxHeight = ""; } return; }
    const h = boxHeightFor(main.clientHeight, box.getBoundingClientRect().top - main.getBoundingClientRect().top);
    if (h === lastFit) return;
    lastFit = h;
    box.style.maxHeight = h === null ? "" : `${h}px`;
  }
  function onMainScroll() {
    if (fitRaf) return;
    fitRaf = (win.requestAnimationFrame || setTimeout)(() => { fitRaf = null; if (!destroyed) fitBox(); });
  }

  function writeFrozenStyle() {
    let css = "";
    L.cols.forEach((c, i) => { if (c.frozen) css += `#tb-grid .tb-fz-${i}{left:${c.left}px}`; });
    const tableW = L.cols.reduce((s, c) => s + c.width, 0);
    css += `#tb-grid{width:${tableW}px;--box-w:${Math.max(0, (box.clientWidth || lastBoxWidth || 0))}px;--fz-w:${L.frozenWidth}px}`;
    fzStyle.textContent = css;
  }

  // ----- toolbar (12.7): Columns, Find column, View, and the hidden chip while columns are hidden -----
  function renderBar(T, st) {
    const on = keysOn();
    barTips = toolbarTips(T, st, {keys: on, storageOk: storageOk()});
    rebuildKeep(bar, toolbarHtml(toolbarModel(T, st, {findKey: hint("columns.find")})));
    // Descriptions for screen readers: the same text as each tooltip.
    let d = "";
    for (const [key, t] of barTips) d += `<span id="tb-d-${key}">${esc([t.title, t.body].concat(t.lines || []).filter(Boolean).join(". ").replace(/\.\./g, "."))}</span>`;
    tipDesc.innerHTML = d;
    for (const el of bar.querySelectorAll("[data-tb]")) {
      const key = el.getAttribute("data-tb");
      if (barTips.has(key)) el.setAttribute("aria-describedby", `tb-d-${key}`);
    }
  }

  /** Replace a container's HTML, keeping focus and an input's typed text by `data-key`. */
  function rebuildKeep(container, html) {
    const ae = doc.activeElement;
    let key = null, val = null, s0 = null, s1 = null;
    if (ae && ae !== container && container.contains(ae)) {
      key = ae.getAttribute("data-key");
      if (key && ae.tagName === "INPUT") { val = ae.value; s0 = ae.selectionStart; s1 = ae.selectionEnd; }
    }
    container.innerHTML = html;
    if (!key) return;
    const sel = `[data-key="${win.CSS && win.CSS.escape ? win.CSS.escape(key) : key.replace(/"/g, "\\\"")}"]`;
    const el = container.querySelector(sel);
    if (!el) return;
    if (val !== null) {
      el.value = val;
      try { el.setSelectionRange(s0, s1); } catch (e) { /* not a text input */ }
    }
    el.focus({preventScroll: true});
  }

  // ------------------------------------------------------------------------------------------
  // Active cell, focus and scrolling
  // ------------------------------------------------------------------------------------------

  const sameKey = (a, b) => (!a && !b) || (!!a && !!b && a.row === b.row && a.col === b.col);
  const isBodyRow = (row) => !!row && row !== "head" && !String(row).startsWith("sum:");
  const sendable = (a) => (a && isBodyRow(a.row) ? {row: a.row, col: a.col} : null);

  /** Adopt a focus the state holds when it did not come from this table (a chart link, Esc). */
  function syncFocusFromState(st) {
    if (sendTimer) return;
    const f = st && st.ui ? st.ui.focus || null : null;
    if (sameKey(f, lastSent)) return;
    lastSent = f ? {row: f.row, col: f.col} : null;
    if (f) active = {row: f.row, col: f.col};
    else if (active && isBodyRow(active.row)) active = null;
  }

  function scheduleSend() {
    if (sendTimer) clearTimeout(sendTimer);
    sendTimer = setTimeout(() => {
      sendTimer = null;
      const s = sendable(active);
      if (sameKey(s, lastSent)) return;
      lastSent = s;
      dispatch({type: "FOCUS_CELL", row: s ? s.row : null, col: s ? s.col : null});
    }, FOCUS_SEND_MS);
  }

  function defaultActive() {
    const f = focalTicker();
    const prim = L.cols.find((c) => c.isPrimary);
    return {row: f && rowKeys.includes(f) ? f : rowKeys[Math.min(1, rowKeys.length - 1)], col: prim ? prim.id : "ticker"};
  }

  /** Keep the active cell on a row and column that exist. True when it had to move. */
  function validateActive() {
    if (!active) return false;
    if (!rowKeys.length) { active = null; return true; }
    let moved = false;
    let r = rowKeys.indexOf(active.row);
    if (r < 0) {
      const i = clamp(lastActiveIndex, Math.min(1, rowKeys.length - 1), rowKeys.length - 1);
      active = {row: rowKeys[i], col: active.col};
      r = i;
      moved = true;
      scheduleSend();
    }
    if (!colIds.includes(active.col)) {
      active = {row: active.row, col: colIds.includes("ticker") ? "ticker" : colIds[0]};
      moved = true;
      scheduleSend();
    }
    lastActiveIndex = r;
    return moved;
  }

  function applyActive(opts = {}) {
    const prev = table.querySelectorAll(".tb-active");
    prev.forEach((el) => el.classList.remove("tb-active"));
    if (!active) {
      table.removeAttribute("aria-activedescendant");
      desc.textContent = "";
      return null;
    }
    const id = cellDomId(active, labelCols);
    const el = id ? doc.getElementById(id) : null;
    if (!el || !table.contains(el)) {
      table.removeAttribute("aria-activedescendant");
      desc.textContent = "";
      return null;
    }
    el.classList.add("tb-active");
    table.setAttribute("aria-activedescendant", id);
    desc.textContent = describeKey(active);
    lastActiveIndex = Math.max(0, rowKeys.indexOf(active.row));
    if (opts.scroll) scrollCellIntoView(el);
    if (opts.tip) {
      const content = tipForKey(active);
      if (content) showTip(el, content); else hideTip();
    }
    return el;
  }

  function setActive(key, opts = {}) {
    if (!key) return;
    active = {row: key.row, col: key.col};
    applyActive({scroll: opts.scroll !== false, tip: !!opts.tip});
    if (opts.focus) table.focus({preventScroll: true});
    scheduleSend();
  }

  function focusKey(key) {
    setActive(key, {scroll: true, focus: true, tip: true});
    const el = doc.getElementById(cellDomId(active, labelCols));
    if (el) ensureInMain(el);
  }

  function scrollCellIntoView(el) {
    if (!el) return;
    const boxR = box.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    const inHead = !!el.closest("thead");
    const inFoot = !!el.closest("tfoot");
    const stickRow = el.closest("tr.tb-stick");
    const head = table.tHead ? table.tHead.getBoundingClientRect().height : 0;
    const stick = table.querySelector("tr.tb-stick");
    const stickH = stick ? stick.getBoundingClientRect().height : 0;
    const foot = table.tFoot ? table.tFoot.getBoundingClientRect().height : 0;
    if (!inHead && !inFoot && !stickRow) {
      const top = boxR.top + head + stickH;
      const bottom = boxR.top + box.clientHeight - foot;
      if (r.top < top) box.scrollTop -= (top - r.top);
      else if (r.bottom > bottom) box.scrollTop += Math.min(r.bottom - bottom, r.top - top);
    }
    if (!el.classList.contains("tb-fz")) {
      const left = boxR.left + L.frozenWidth;
      const right = boxR.left + box.clientWidth;
      if (r.left < left) box.scrollLeft -= (left - r.left);
      else if (r.right > right) box.scrollLeft += Math.min(r.right - right, r.left - left);
    }
  }

  /** Bring the table box into #main's view when the cell is outside it (1.2, "Look next"). */
  function ensureInMain(el) {
    const main = doc.getElementById("main");
    if (!main || !main.contains(box)) return;
    const mr = main.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    if (r.top >= mr.top && r.bottom <= mr.bottom) return;
    main.scrollTop += box.getBoundingClientRect().top - mr.top;
    scrollCellIntoView(el);
  }

  function scrollToColumn(colId) {
    const th = doc.getElementById(`c-head-${colId}`);
    if (!th || !table.contains(th)) { pendingScrollCol = colId; return; }
    if (th.classList.contains("tb-fz")) return;
    box.scrollLeft = Math.max(0, th.offsetLeft - L.frozenWidth - 8);
  }

  // ----- descriptions and tooltips -----
  function describeKey(key) {
    if (!key || !view || !view.table) return "";
    const col = colView(key.col);
    if (!col) return "";
    if (key.row === "head") return headerDesc(col);
    if (String(key.row).startsWith("sum:")) {
      const sid = key.row.slice(4);
      const s = (view.table.summary || []).find((x) => x.id === sid);
      if (!s) return "";
      if (labelCols.has(key.col)) return `${s.label}. Computed over included peers only; the focal company and excluded rows never count.`;
      const sc = s.cells ? s.cells[key.col] : null;
      if (!sc || !col.numeric) return `${s.label}, ${col.label}: no statistic for this column.`;
      return [`${s.label}, ${col.label}.`, sc.reason ? `${sc.reason}.` : "", sid !== "n" ? `Peers with a value: ${sc.n}.` : ""].filter(Boolean).join(" ");
    }
    const row = rowView(key.row);
    if (!row) return "";
    const t = rowTip(row, col);
    if (t) return [t.title, t.body].concat(t.lines || []).filter(Boolean).join(". ").replace(/\.\./g, ".");
    return describeCell(row.cells ? row.cells[col.id] : null, col, row, view.table.cfMode);
  }

  function headerDesc(col) {
    if (col.id === "exp") return "Expand a row for its relevance, inclusion reason and note. Shift Enter expands the focused row.";
    if (col.id === "incl") return "In statistics: a filled circle counts, a hollow circle is excluded, a diamond is an outlier left out, a cross is a failed calculation. X excludes or includes the focused row.";
    const parts = [col.tooltip || "", unitLineText(col)];
    if (col.basisChip && col.basisChip.tooltip) parts.push(col.basisChip.tooltip);
    if (col.sortDir) parts.push(`Sorted ${col.sortDir === "desc" ? "descending" : "ascending"}.`);
    if (col.filter) parts.push(`Filter ${filterShort(col.filter)}. ${FILTER_NOTE}`);
    parts.push("Enter opens the column menu. S sorts.");
    return parts.filter(Boolean).join(" ");
  }

  function headerTip(col) {
    if (col.id === "exp") return {title: "Expand", body: "Expand a row for its relevance, inclusion reason and note.", lines: ["Shift Enter expands the focused row."]};
    if (col.id === "incl") {
      return {title: "In statistics", body: "● counts in statistics, ○ excluded, ◇ outlier left out, ✕ calculation failed.",
        lines: ["Click a mark, or press X on a row, to exclude or include it. Excluded rows stay in view."]};
    }
    const lines = [];
    if (col.unitLine) lines.push(unitLineText(col));
    if (col.basisChip && col.basisChip.tooltip) lines.push(col.basisChip.tooltip);
    if (col.filter) lines.push(`Filter ${filterShort(col.filter)}. ${FILTER_NOTE}`);
    if (col.pin === "auto") lines.push("Primary metric, frozen after the ticker at this width.");
    lines.push("Click to sort. The ▾ button or Enter opens the column menu.");
    return {title: `${col.label}${col.unitText ? ", " + col.unitText : ""}`, body: col.tooltip || null, lines};
  }

  function rowTip(row, col) {
    if (!row || !col) return null;
    switch (col.id) {
      case "exp":
        return row.isFocal ? null : {title: row.ticker, body: row.expanded ? "Collapse this row." : "Expand for relevance, source and the inclusion note.", lines: ["Shift Enter toggles."]};
      case "incl": {
        if (row.isFocal) return {title: row.ticker, body: "Focal company, not in statistics."};
        if (row.error) return {title: row.ticker, body: row.error};
        if (row.excluded) return {title: row.ticker, body: EXCLUDED_TEXT};
        const s = inclState(row, getState().outliers);
        return {title: row.ticker, body: s.label, lines: ["X or a click toggles."]};
      }
      case "rel": {
        if (row.isFocal || !row.relevance) return null;
        const lines = relevanceLines(row.relevance);
        const src = sourceText(row);
        if (src) lines.push(src + ".");
        if (row.source === "analyst") lines.push("Added by you.");
        return {title: `Relevance ${row.relevance.score} of 100`, body: row.reason ? `${row.reason}.` : null, lines};
      }
      case "company": {
        const lines = [];
        if (row.isFocal) lines.push("Focal company. Enter or a click opens its details.");
        else {
          if (row.reason) lines.push(`${row.reason}.`);
          if (row.note) lines.push(`Note: ${row.note}`);
          lines.push("Enter or a click opens its details.");
        }
        return {title: row.name, body: null, lines};
      }
      case "ticker": return tickerTip(row);
      default: {
        const cell = row.cells ? row.cells[col.id] : null;
        return cellTip(cell, col, row);
      }
    }
  }

  function tipForKey(key) {
    if (!key || !view || !view.table) return null;
    const col = colView(key.col);
    if (!col) return null;
    if (key.row === "head") return headerTip(col);
    if (String(key.row).startsWith("sum:")) {
      const sid = key.row.slice(4);
      const s = (view.table.summary || []).find((x) => x.id === sid);
      if (!s) return null;
      if (labelCols.has(key.col)) {
        // The expand button is cut short in a narrow frozen block, so the tooltip names it in full.
        const st = getState();
        const canExpand = sid === summaryIds[0] && autoPinsPrimary(layoutName) && (view.table.summaryVisible || []).length > SUMMARY_SHORT.length;
        const lines = canExpand ? [`${(st.summaryExpanded || {})[layoutName] ? "Hide mean and quartiles" : "Show mean and quartiles"}: the button in this cell, or Space.`] : [];
        return {title: s.label, body: "Included peers only. The focal company, excluded rows and filters never change it.", lines};
      }
      const sc = s.cells ? s.cells[key.col] : null;
      if (!sc || !sc.reason) return null;
      return {title: `${s.label} · ${col.label}`, body: `${sc.reason}.`, lines: []};
    }
    return rowTip(rowView(key.row), col);
  }

  function keyOfCell(el) {
    if (!el) return null;
    const tr = el.closest("tr");
    const col = el.getAttribute("data-col");
    if (!tr) return null;
    if (tr.parentElement && tr.parentElement.tagName === "THEAD") return col ? {row: "head", col} : null;
    const rk = tr.getAttribute("data-row");
    if (!rk) return null;
    if (rk.startsWith("sum:")) return {row: rk, col: col || "exp"};
    return col ? {row: rk, col} : null;
  }

  // ------------------------------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------------------------------

  function toggleExclude(t) {
    const row = rowView(t);
    if (!row) return;
    if (row.isFocal) { announce("The focal company is never in statistics."); return; }
    if (row.error) { announce(row.error); return; }
    const was = row.excluded;
    dispatch({type: "TOGGLE_EXCLUDE", ticker: t});
    announce(was ? `${t} back in statistics` : `${t} excluded from statistics. Still shown.`);
  }

  function toggleExpand(t) {
    const row = rowView(t);
    if (!row || row.isFocal) return;
    const was = row.expanded;
    dispatch({type: "TOGGLE_ROW_EXPANDED", ticker: t});
    announce(was ? `${t} collapsed` : `${t} expanded`);
  }

  function removePeer(t) {
    const row = rowView(t);
    if (!row) return;
    if (row.isFocal) { announce("The focal company cannot be removed. Change the company with C."); return; }
    dispatch({type: "REMOVE_PEER", ticker: t, now: now()});
    announce(`Removed ${t} from peers. Undo with ${isMac ? "Command" : "Control"} Z.`);
  }

  function sortBy(colId) {
    if (!colId || colId === "exp" || colId === "incl") return;
    dispatch({type: "SORT", colId});
    announceSort(colId);
  }

  function sortTo(colId, want) {
    const n = sortSteps(getState().sort || null, colId, want);
    for (let i = 0; i < n; i++) dispatch({type: "SORT", colId});
    announceSort(colId);
  }

  function announceSort(colId) {
    const s = getState().sort;
    const c = COLUMN_BY_ID[colId] || colView(colId) || {label: colId};
    if (s && s.colId === colId) announce(`Sorted by ${c.label}, ${s.dir === "desc" ? "descending" : "ascending"}`);
    else announce("Sort cleared. Rows by relevance.");
  }

  function runStateCommand(cmd) {
    if (cmd === "peers.restore") dispatch({type: "RESTORE_SYSTEM", now: now()});
    else if (cmd === "filters.reset") dispatch({type: "CLEAR_FILTERS", now: now()});
    else if (cmd === "peers.addAdjacent") dispatch({type: "ADD_POOL_C"});
  }

  function onEnter() {
    if (!active) return;
    if (active.row === "head") {
      const th = doc.getElementById(cellDomId(active, labelCols));
      if (th) openHeaderMenu(active.col, th);
      return;
    }
    if (isBodyRow(active.row)) openDetail(active.row);
  }

  function onSpace() {
    if (!active) return;
    if (active.row === "head") { sortBy(active.col); return; }
    if (String(active.row).startsWith("sum:")) {
      if (labelCols.has(active.col)) {
        const b = table.querySelector("[data-act='sumexp']");
        if (b) toggleSummaryExpanded();
      }
      return;
    }
    if (active.col === "exp") toggleExpand(active.row);
    else if (active.col === "incl") toggleExclude(active.row);
    else if (active.col === "company" || active.col === "ticker") openDetail(active.row);
  }

  function toggleSummaryExpanded() {
    const st = getState();
    const was = !!((st.summaryExpanded || {})[layoutName]);
    dispatch({type: "TOGGLE_SUMMARY_EXPANDED", layout: layoutName});
    announce(was ? "Summary rows: median and n" : "Summary rows: mean, median, quartiles and n");
  }

  // ----- header menu -----
  function openHeaderMenu(colId, anchor) {
    const col = colView(colId);
    if (!col || colId === "exp" || colId === "incl") return;
    const st = getState();
    const def = COLUMN_BY_ID[colId];
    const back = () => setTimeout(() => { if (!destroyed) table.focus({preventScroll: true}); }, 0);
    const items = [
      {id: "sort-desc", label: "Sort descending", checked: col.sortDir === "desc", onSelect: () => { sortTo(colId, "desc"); back(); }},
      {id: "sort-asc", label: "Sort ascending", checked: col.sortDir === "asc", onSelect: () => { sortTo(colId, "asc"); back(); }},
    ];
    if (def) {
      const primaryLocked = col.pin === "auto";
      const order = presetColumns(st);
      const idx = order.indexOf(colId);
      items.push({id: "filter", label: col.filter ? "Edit filter" : "Filter", disabled: def.fmt === "spark",
        reason: def.fmt === "spark" ? "A sparkline has no value to filter on." : null, onSelect: () => openFilter(colId, anchor)});
      items.push({id: "hide", label: "Hide column", disabled: primaryLocked, reason: primaryLocked ? PRIMARY_KEEP : null,
        onSelect: () => { dispatch({type: "HIDE_COLUMN", colId}); announce(`Hid ${def.label}. The columns are now a custom set; the toolbar lists hidden columns.`); back(); }});
      if ((st.pinned || []).includes(colId)) {
        items.push({id: "unpin", label: "Unpin", onSelect: () => { dispatch({type: "UNPIN_COLUMN", colId}); announce(`Unpinned ${def.label}`); back(); }});
      } else {
        const chk = primaryLocked ? {ok: false, reason: "The primary metric is already frozen at this width."}
          : canPin(st, colId, {layout: layoutName, boxWidth: box.clientWidth || undefined});
        items.push({id: "pin", label: "Pin left", disabled: !chk.ok, reason: chk.ok ? null : chk.reason, onSelect: () => pinCol(colId)});
      }
      const notInPreset = idx < 0 ? "This column is shown because it is the primary metric; the preset does not list it." : null;
      items.push({id: "left", label: "Move left", disabled: idx <= 0, reason: idx < 0 ? notInPreset : "Already the first column of the preset.",
        onSelect: () => { dispatch({type: "MOVE_COLUMN", colId, dir: "left"}); announce(`Moved ${def.label} left`); back(); }});
      items.push({id: "right", label: "Move right", disabled: idx < 0 || idx >= order.length - 1, reason: idx < 0 ? notInPreset : "Already the last column of the preset.",
        onSelect: () => { dispatch({type: "MOVE_COLUMN", colId, dir: "right"}); announce(`Moved ${def.label} right`); back(); }});
    }
    if (!NO_RESIZE.has(colId)) {
      items.push({id: "wider", label: "Wider", onSelect: () => { resizeTo(colId, col.width + 16); back(); }});
      items.push({id: "narrower", label: "Narrower", onSelect: () => { resizeTo(colId, col.width - 16); back(); }});
      items.push({id: "fit", label: "Fit width to content", onSelect: () => { fitColumn(colId); back(); }});
    }
    // Anchors panels.js resolves (methodTarget): "def:{colId}" for a catalogue column, a section id otherwise.
    const defAnchor = def ? `def:${colId}` : (colId === "rel" ? "relevance" : "definitions");
    items.push({id: "def", label: "Definition", onSelect: () => {
      if (typeof ctx.openMethod === "function") ctx.openMethod(defAnchor);
      else dispatch({type: "OPEN_METHOD", anchor: defAnchor});
    }});
    const mb = anchor && anchor.querySelector ? anchor.querySelector(".tb-hmenu") : null;
    openMenu(mb && mb.getClientRects().length ? mb : anchor, items);
  }

  function pinCol(colId) {
    const st = getState();
    const chk = canPin(st, colId, {layout: layoutName, boxWidth: box.clientWidth || undefined});
    if (!chk.ok) { announce(chk.reason || PIN_REFUSED); return; }
    dispatch({type: "PIN_COLUMN", colId, layout: layoutName, boxWidth: box.clientWidth || undefined});
    const after = getState();
    announce((after.pinned || []).includes(colId) ? `Pinned ${COLUMN_BY_ID[colId].label} to the left` : PIN_REFUSED);
    setTimeout(() => { if (!destroyed) table.focus({preventScroll: true}); }, 0);
  }

  function resizeTo(colId, w) {
    const width = clamp(Math.round(w), RESIZE_MIN, RESIZE_MAX);
    dispatch({type: "RESIZE_COLUMN", colId, width});
    announce(`${(colView(colId) || {label: colId}).label} width ${width} pixels`);
  }

  function contentWidth(el) {
    if (!el) return 0;
    try {
      const r = doc.createRange();
      r.selectNodeContents(el);
      return r.getBoundingClientRect().width;
    } catch (e) { return el.scrollWidth || 0; }
  }

  function fitColumn(colId) {
    let w = 0;
    const th = doc.getElementById(`c-head-${colId}`);
    if (th) {
      w = Math.max(contentWidth(th.querySelector(".tb-hl")), contentWidth(th.querySelector(".tb-hu")));
    }
    for (const el of table.querySelectorAll(`tbody td[data-col="${colId}"] .tb-in, tbody th[data-col="${colId}"] .tb-in, tfoot td[data-col="${colId}"] .tb-in`)) {
      w = Math.max(w, contentWidth(el));
    }
    const pad = parseFloat(win.getComputedStyle ? win.getComputedStyle(root).getPropertyValue("--cell-px") : "8") || 8;
    resizeTo(colId, Math.ceil(w + 2 * pad + 6));
  }

  // ----- popovers: filter, layout name, column finder, fallback menu -----
  function openPop(anchor, html, opts = {}) {
    closePop(false);
    const el = doc.createElement("div");
    el.className = `u-pop tb-pop${opts.cls ? " " + opts.cls : ""}`;
    el.setAttribute("role", "dialog");
    if (opts.labelledby) el.setAttribute("aria-labelledby", opts.labelledby);
    el.innerHTML = html;
    doc.body.appendChild(el);
    placePop(el, anchor);
    const outside = (e) => { if (!el.contains(e.target) && !(anchor && anchor.contains && anchor.contains(e.target))) closePop(false); };
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closePop(true); return; }
      e.stopPropagation();
      if (opts.onKey) opts.onKey(e);
    };
    el.addEventListener("keydown", onKey);
    doc.addEventListener("pointerdown", outside, true);
    pop = {el, anchor, onClose: opts.onClose || null, returnTo: opts.returnTo || null, off: () => doc.removeEventListener("pointerdown", outside, true)};
    const first = el.querySelector(opts.focus || "input, select, button");
    if (first) first.focus({preventScroll: true});
    return el;
  }

  function placePop(el, anchor) {
    const vw = win.innerWidth || 1200, vh = win.innerHeight || 800;
    const r = anchor && anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : {left: 16, bottom: 16, top: 16};
    const w = el.offsetWidth || 300, hh = el.offsetHeight || 200;
    let left = clamp(r.left, 8, Math.max(8, vw - w - 8));
    let top = r.bottom + 4;
    if (top + hh > vh - 8) top = Math.max(8, r.top - hh - 4);
    el.style.left = `${Math.round(left)}px`;
    el.style.top = `${Math.round(top)}px`;
  }

  function closePop(returnFocus) {
    if (!pop) return;
    const p = pop;
    pop = null;
    p.off();
    p.el.remove();
    if (p.onClose) p.onClose();
    if (returnFocus) {
      const target = p.returnTo || table;
      if (target && target.isConnected) target.focus({preventScroll: true});
    }
  }

  function openFilter(colId, anchor) {
    const def = COLUMN_BY_ID[colId];
    if (!def) return;
    const col = colView(colId) || {label: def.label, unitText: ""};
    const numeric = !!col.numeric;
    const existing = (getState().filters || []).find((f) => f.colId === colId) || null;
    const unit = col.unitText ? `, ${col.unitText}` : "";
    const op = existing ? existing.op : (numeric ? ">=" : "text");
    const val = existing && existing.op !== "has" && existing.value != null ? String(existing.value) : "";
    let h = `<p class="u-pop-title" id="tb-flt-t">Filter: ${esc(def.label)}${esc(unit)}</p>`;
    if (numeric) {
      h += `<label class="tb-pop-field"><span class="u-label">Condition</span><select class="u-input tb-flt-op">`
        + `<option value=">="${op === ">=" ? " selected" : ""}>At least (≥)</option>`
        + `<option value="<="${op === "<=" ? " selected" : ""}>At most (≤)</option>`
        + `<option value="has"${op === "has" ? " selected" : ""}>Has a value</option></select></label>`
        + `<label class="tb-pop-field tb-flt-vrow"><span class="u-label">Value${esc(unit)}</span><input type="text" inputmode="decimal" class="u-input num tb-flt-v" value="${esc(val)}" autocomplete="off"></label>`;
    } else {
      h += `<label class="tb-pop-field"><span class="u-label">Contains</span><input type="text" class="u-input tb-flt-v" value="${esc(val)}" autocomplete="off"></label>`;
    }
    h += `<p class="tb-pop-note">${esc(FILTER_NOTE)}</p><p class="tb-pop-err" role="alert" hidden></p>`
      + `<div class="tb-pop-act"><button type="button" class="u-btn primary" data-pa="apply">Apply</button>`
      + (existing ? `<button type="button" class="u-btn" data-pa="remove">Remove filter</button>` : "")
      + `<button type="button" class="u-btn" data-pa="cancel">Cancel</button></div>`;
    const el = openPop(anchor, h, {labelledby: "tb-flt-t", focus: numeric ? ".tb-flt-v" : ".tb-flt-v",
      onKey: (e) => { if (e.key === "Enter" && e.target.tagName !== "BUTTON") { e.preventDefault(); apply(); } }});
    const opSel = el.querySelector(".tb-flt-op");
    const vIn = el.querySelector(".tb-flt-v");
    const err = el.querySelector(".tb-pop-err");
    const vRow = el.querySelector(".tb-flt-vrow");
    const syncOp = () => { if (opSel && vRow) vRow.hidden = opSel.value === "has"; };
    if (opSel) opSel.addEventListener("change", syncOp);
    syncOp();
    function apply() {
      let f;
      if (numeric) {
        const o = opSel.value;
        if (o === "has") f = {colId, op: "has", value: null};
        else {
          const v = parseFilterValue(vIn.value);
          if (v === null) { err.hidden = false; err.textContent = "Enter a number in the column's unit, for example 10."; vIn.focus(); return; }
          f = {colId, op: o, value: v};
        }
      } else {
        const t = String(vIn.value || "").trim();
        if (!t) { err.hidden = false; err.textContent = "Enter the text to look for."; vIn.focus(); return; }
        f = {colId, op: "text", value: t};
      }
      dispatch({type: "SET_FILTER", filter: f});
      closePop(true);
      const fresh = typeof ctx.getView === "function" ? ctx.getView() : view;
      const T = fresh && fresh.table;
      announce(`Filter ${def.label} ${filterShort(f)}. ${T ? `${Math.max(0, T.rows.length - 1)} peer rows shown.` : ""} ${FILTER_NOTE}`);
    }
    el.addEventListener("click", (e) => {
      const b = e.target.closest("[data-pa]");
      if (!b) return;
      const a = b.getAttribute("data-pa");
      if (a === "apply") apply();
      else if (a === "remove") { dispatch({type: "REMOVE_FILTER", colId}); closePop(true); announce(`Removed the ${def.label} filter`); }
      else closePop(true);
    });
  }

  function openLayoutSave(anchor) {
    const ok = storageOk();
    const h = `<p class="u-pop-title" id="tb-lay-t">Save layout</p>`
      + `<label class="tb-pop-field"><span class="u-label">Name</span><input type="text" class="u-input tb-lay-in" maxlength="40" autocomplete="off"></label>`
      + `<p class="tb-pop-note">${esc(ok ? SAVED_HERE : STATE_COPY.storage_unavailable.detail)}</p><p class="tb-pop-err" role="alert" hidden></p>`
      + `<div class="tb-pop-act"><button type="button" class="u-btn primary" data-pa="save">Save</button><button type="button" class="u-btn" data-pa="cancel">Cancel</button></div>`;
    const el = openPop(anchor, h, {labelledby: "tb-lay-t", returnTo: bar.querySelector("[data-tb='view']"),
      onKey: (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); save(); } }});
    const input = el.querySelector(".tb-lay-in");
    const err = el.querySelector(".tb-pop-err");
    function save() {
      const name = String(input.value || "").trim();
      if (!name) { err.hidden = false; err.textContent = "Enter a name for the layout."; input.focus(); return; }
      dispatch({type: "SAVE_LAYOUT", name, now: now()});
      closePop(true);
      announce(`Saved layout ${name}. ${ok ? SAVED_HERE : STATE_COPY.storage_unavailable.detail}`);
    }
    el.addEventListener("click", (e) => {
      const b = e.target.closest("[data-pa]");
      if (!b) return;
      if (b.getAttribute("data-pa") === "save") save(); else closePop(true);
    });
  }

  function fallbackMenu(anchor, items, opts = {}) {
    let h = `<ul class="tb-fmenu" role="menu"${opts.label ? ` aria-label="${esc(opts.label)}"` : ""}>`;
    items.forEach((it, i) => {
      if (it.kind === "note") { h += `<li class="u-menu-note" role="none">${esc(it.label)}</li>`; return; }
      if (it.kind === "head") { h += `<li class="u-menu-head" role="presentation">${esc(it.label)}</li>`; return; }
      if (it.kind === "sep") { h += `<li class="u-menu-sep" role="separator"></li>`; return; }
      h += `<li role="none"><button type="button" role="menuitem${it.checked != null ? "checkbox" : ""}" class="u-menu-item" data-i="${i}"`
        + `${it.checked != null ? ` aria-checked="${it.checked ? "true" : "false"}"` : ""}${it.disabled ? " aria-disabled=\"true\"" : ""}${it.reason ? ` title="${esc(it.reason)}"` : ""}>`
        + `<span class="u-menu-check" aria-hidden="true">${it.checked ? "✓" : ""}</span><span class="u-menu-label">${esc(it.label)}</span>`
        + `<span class="u-menu-key">${it.shortcut ? `<kbd class="u-kbd">${esc(keyLabel(it.shortcut, isMac))}</kbd>` : ""}</span></button></li>`;
    });
    h += `</ul>`;
    const el = openPop(anchor, h, {cls: `tb-fmenu-pop${opts.cls ? " " + opts.cls : ""}`, focus: ".u-menu-item:not([aria-disabled='true'])",
      onKey: (e) => {
        const btns = [...el.querySelectorAll(".u-menu-item")];
        const i = btns.indexOf(doc.activeElement);
        if (e.key === "ArrowDown") { e.preventDefault(); (btns[i + 1] || btns[0]).focus(); }
        if (e.key === "ArrowUp") { e.preventDefault(); (btns[i - 1] || btns[btns.length - 1]).focus(); }
      }});
    el.addEventListener("click", (e) => {
      const b = e.target.closest("[data-i]");
      if (!b || b.getAttribute("aria-disabled") === "true") return;
      const it = items[Number(b.getAttribute("data-i"))];
      closePop(false);
      if (it && typeof it.onSelect === "function") it.onSelect();
    });
  }

  // ----- column finder (4.8, `f`) -----
  function syncFinder(st) {
    const want = !!(st.ui && st.ui.overlay === "columnfinder");
    if (want && !finderOpen) openFinder();
    else if (!want && finderOpen && pop && pop.el.classList.contains("tb-finder")) closePop(false);
  }

  function openFinder() {
    const anchor = bar.querySelector("[data-tb='find']") || bar;
    finderOpen = true;
    const h = `<p class="u-pop-title" id="tb-find-t">Find a column</p>`
      + `<input type="text" class="u-input tb-find-in" role="combobox" aria-expanded="true" aria-autocomplete="list" aria-controls="tb-find-list" aria-labelledby="tb-find-t" placeholder="Search metrics and definitions" autocomplete="off">`
      + `<ul class="tb-find-list" id="tb-find-list" role="listbox" aria-label="Columns"></ul>`
      + `<p class="tb-pop-note">Enter shows the column and focuses the focal company's cell. A column outside the preset switches the table to custom columns.</p>`;
    let sel = 0;
    let results = [];
    const el = openPop(anchor, h, {cls: "tb-finder", labelledby: "tb-find-t", focus: ".tb-find-in", returnTo: table,
      onClose: () => {
        finderOpen = false;
        const st = getState();
        if (st.ui && st.ui.overlay === "columnfinder") dispatch({type: "CLOSE_OVERLAY"});
      },
      onKey: (e) => {
        if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(results.length - 1, sel + 1); paint(); }
        else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(0, sel - 1); paint(); }
        else if (e.key === "Enter") { e.preventDefault(); if (results[sel]) pick(results[sel].id); }
      }});
    const input = el.querySelector(".tb-find-in");
    const list = el.querySelector(".tb-find-list");
    function refresh() {
      const inTable = new Set(view && view.table ? view.table.columns.map((c) => c.id) : []);
      results = findColumns(input.value, COLUMNS, inTable, 12);
      sel = Math.min(sel, Math.max(0, results.length - 1));
      paint();
    }
    function paint() {
      list.innerHTML = results.length ? results.map((r, i) => `<li role="option" id="tb-find-${i}" data-col="${esc(r.id)}" aria-selected="${i === sel ? "true" : "false"}">`
        + `<span class="tb-find-l">${esc(r.label)}</span><span class="tb-find-m">${esc([r.group, r.unit, r.inTable ? "in the table" : ""].filter(Boolean).join(" · "))}</span></li>`).join("")
        : `<li class="tb-find-none" role="option" aria-disabled="true">No column matches. Try a word from a definition, such as cash or margin.</li>`;
      if (results.length) input.setAttribute("aria-activedescendant", `tb-find-${sel}`);
      else input.removeAttribute("aria-activedescendant");
      const cur = list.querySelector("[aria-selected='true']");
      if (cur && cur.scrollIntoView && list.scrollHeight > list.clientHeight) {
        const lr = list.getBoundingClientRect(), cr = cur.getBoundingClientRect();
        if (cr.top < lr.top) list.scrollTop -= lr.top - cr.top;
        else if (cr.bottom > lr.bottom) list.scrollTop += cr.bottom - lr.bottom;
      }
    }
    function pick(colId) {
      const inTable = !!(view && view.table && view.table.columns.some((c) => c.id === colId));
      const label = COLUMN_BY_ID[colId] ? COLUMN_BY_ID[colId].label : colId;
      closePop(false);
      if (!inTable) dispatch({type: "SHOW_COLUMN", colId});
      if (typeof ctx.flush === "function") ctx.flush();
      const f = focalTicker();
      scrollToColumn(colId);
      focusCell(f, colId);
      announce(inTable ? `Showing ${label}` : `Added ${label}. The columns are now a custom set.`);
    }
    input.addEventListener("input", () => { sel = 0; refresh(); });
    list.addEventListener("click", (e) => { const li = e.target.closest("[data-col]"); if (li) pick(li.getAttribute("data-col")); });
    refresh();
  }

  // ----- toolbar menus -----
  function presetMenu(anchor) {
    const T = view.table;
    const items = (T.presets || []).map((p) => ({id: p.id, label: p.label, shortcut: keysOn() ? p.key : null, checked: T.preset === p.id,
      onSelect: () => { dispatch({type: "SET_PRESET", preset: p.id}); announce(`Columns: ${p.label}`); }}));
    items.push({id: "note", kind: "note", label: T.presetFootnote || PRESET_FOOTNOTE, disabled: true});
    openMenu(anchor, items);
  }

  /** The one "View" menu (12.7): every setting the old Layouts, Statistics, Outliers, Format and Display buttons held. */
  function viewMenu(anchor) {
    const model = viewMenuModel(view, getState(), {layout: layoutName, focalPinned, storageOk: storageOk(), keys: keysOn(), isMac});
    const items = model.map((it) => (it.kind ? it : {...it, onSelect: () => runViewItem(it)}));
    openMenu(anchor, items, {label: "View", cls: VIEW_MENU_CLASS});
  }

  function runViewItem(it) {
    switch (it.run) {
      case "saveLayout": openLayoutSave(bar.querySelector("[data-tb='view']") || bar); return;
      case "summaryExpanded": toggleSummaryExpanded(); return;
      case "pinFocal":
        focalPinned = !focalPinned;
        render();
        break;
      case "resetLayout": {
        const before = getState();
        dispatch({type: "RESET_LAYOUT", now: now()});
        announce(getState() === before ? RESET_NOOP : "Reset the column layout");
        return;
      }
      default: break;
    }
    for (const a of it.actions || []) dispatch(it.stamp ? {...a, now: now()} : a);
    if (it.say) announce(it.say);
  }

  function hiddenMenu(anchor) {
    const T = view.table;
    const items = (T.hidden || []).map((id) => ({id, label: `Show ${COLUMN_BY_ID[id] ? COLUMN_BY_ID[id].label : id}`,
      onSelect: () => { dispatch({type: "SHOW_COLUMN", colId: id}); announce(`Showing ${COLUMN_BY_ID[id] ? COLUMN_BY_ID[id].label : id}`); }}));
    openMenu(anchor, items);
  }

  // ------------------------------------------------------------------------------------------
  // Events
  // ------------------------------------------------------------------------------------------

  function onTableClick(e) {
    if (drag || e.target.closest(".tb-rs")) return;
    const actEl = e.target.closest("[data-act]");
    const cellEl = e.target.closest("td, th");
    if (!cellEl || !table.contains(cellEl)) return;
    const act = actEl ? actEl.getAttribute("data-act") : null;
    const subRow = e.target.closest("tr.tb-sub");
    if (subRow) {
      const t = subRow.getAttribute("data-sub");
      if (act === "open") openDetail(t);
      else if (act === "exclude") toggleExclude(t);
      return;
    }
    if (act === "state") {
      // The button leaves with the note it sits in: hand focus to the grid before it goes.
      table.focus({preventScroll: true});
      runStateCommand(actEl.getAttribute("data-cmd"));
      return;
    }
    if (act === "sumexp") { toggleSummaryExpanded(); return; }
    const key = keyOfCell(cellEl);
    if (!key) return;
    if (act === "hmenu") { setActive(key, {scroll: false}); openHeaderMenu(key.col, cellEl); return; }
    if (key.row === "head") {
      setActive(key, {scroll: false, focus: true});
      sortBy(key.col);
      return;
    }
    setActive(key, {scroll: false, focus: true});
    if (act === "expand") { toggleExpand(key.row); return; }
    if (act === "exclude") { toggleExclude(key.row); return; }
    if (isBodyRow(key.row) && (key.col === "company" || key.col === "ticker")) openDetail(key.row);
  }

  function onTableDblClick(e) {
    if (e.target.closest("button, input, .tb-rs, thead, tfoot, tr.tb-sub")) return;
    const tr = e.target.closest("tr[data-row]");
    const t = tr ? tr.getAttribute("data-row") : null;
    if (isBodyRow(t)) openDetail(t);
  }

  function onTableKey(e) {
    if (e.target !== table) {
      const t = e.target;
      if (t.classList && t.classList.contains("tb-note")) {
        if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); saveNote(t); table.focus({preventScroll: true}); }
        else if (e.key === "Escape") {
          e.preventDefault(); e.stopPropagation();
          const row = rowView(t.getAttribute("data-ticker"));
          t.value = row ? row.note || "" : "";
          t.setAttribute("data-skip", "1");
          table.focus({preventScroll: true});
        }
      }
      return;
    }
    const k = normKey(e, isMac);
    let handled = true;
    const move = (dir) => {
      const next = moveActive(active, dir, rowKeys, colIds, {labelCols, defaultRow: defaultActive().row, defaultCol: defaultActive().col});
      if (next) setActive(next, {scroll: true, tip: true});
    };
    switch (k) {
      case "up": case "k": move("up"); break;
      case "down": case "j": move("down"); break;
      case "left": move("left"); break;
      case "right": move("right"); break;
      case "home": move("home"); break;
      case "end": move("end"); break;
      case "mod+home": move("first"); break;
      case "mod+end": move("last"); break;
      case "pageup": move("pageup"); break;
      case "pagedown": move("pagedown"); break;
      case "enter": case "o": onEnter(); break;
      case "shift+enter": if (active && isBodyRow(active.row)) toggleExpand(active.row); break;
      case "space": onSpace(); break;
      case "s":
        if (active) {
          // From a body cell the sorted order starts at the top: focus follows it there.
          if (isBodyRow(active.row) && active.col !== "exp" && active.col !== "incl") pendingTop = active.col;
          sortBy(active.col);
        }
        break;
      case "x": if (active && isBodyRow(active.row)) toggleExclude(active.row); break;
      case "shift+x": case "delete": if (active && isBodyRow(active.row)) removePeer(active.row); break;
      default: handled = false;
    }
    if (handled) { e.preventDefault(); e.stopPropagation(); }
  }

  function saveNote(input) {
    if (!input || rendering) return;
    if (input.getAttribute("data-skip")) { input.removeAttribute("data-skip"); return; }
    const t = input.getAttribute("data-ticker");
    const row = rowView(t);
    const text = String(input.value || "");
    if (row && (row.note || "") === text) return;
    dispatch({type: "SET_PEER_NOTE", ticker: t, text, now: now()});
    announce(storageOk() ? `Note saved for ${t}. Saved in this browser only.` : `Note kept for ${t} until the page reloads.`);
  }

  function onFocus(e) {
    if (e.target !== table) return;
    table.classList.add("is-focused");
    // A click sets its own cell; only keyboard focus picks the default cell and scrolls to it.
    if (pointerFocus) { applyActive({scroll: false}); return; }
    if (!active) setActive(defaultActive(), {scroll: true, tip: false});
    else applyActive({scroll: false});
  }
  function onBlur(e) {
    if (e.target !== table) return;
    table.classList.remove("is-focused");
    hideTip();
  }
  /** Cell buttons (menu, expand, include) hold tabindex -1: focus landing on one returns to the grid. */
  function onFocusIn(e) {
    const t = e.target;
    if (t !== table && t.matches && t.matches(".tb-hmenu, .tb-xbtn, .tb-ibtn")) table.focus({preventScroll: true});
  }
  function onPointerMark() {
    pointerFocus = true;
    clearTimeout(pointerTimer);
    pointerTimer = setTimeout(() => { pointerFocus = false; }, 400);
  }
  function onFocusOut(e) {
    const t = e.target;
    if (t && t.classList && t.classList.contains("tb-note") && t.isConnected && !rendering) saveNote(t);
  }

  function onOver(e) {
    const el = e.target.closest("td[id], th[id], th.tb-g");
    if (el === hoverEl) return;
    if (hoverEl && tipAnchor === hoverEl) hideTip();
    hoverEl = el && table.contains(el) ? el : null;
    clearTimeout(hoverTimer);
    if (!hoverEl) return;
    hoverTimer = setTimeout(() => {
      if (!hoverEl || !hoverEl.isConnected) return;
      // A group label cut short by a narrow group names itself on hover.
      if (hoverEl.classList.contains("tb-g")) {
        if (hoverEl.scrollWidth > hoverEl.clientWidth + 1) showTip(hoverEl, {title: hoverEl.textContent, body: "Column group."});
        return;
      }
      const key = keyOfCell(hoverEl);
      const content = key ? tipForKey(key) : null;
      if (content) showTip(hoverEl, content);
    }, TIP_DELAY_MS);
  }
  function onLeave() {
    clearTimeout(hoverTimer);
    if (hoverEl && tipAnchor === hoverEl) hideTip();
    hoverEl = null;
  }

  // ----- resize by drag -----
  function onPointerDown(e) {
    const h = e.target.closest(".tb-rs");
    if (!h || e.button !== 0) return;
    const th = h.closest("th");
    const colId = th && th.getAttribute("data-col");
    const col = colView(colId);
    if (!col) return;
    if (drag && !drag.done) onPointerUp();
    e.preventDefault();
    e.stopPropagation();
    const colEl = table.querySelector(`col[data-col="${colId}"]`);
    drag = {colId, startX: e.clientX, startW: col.width, w: col.width, colEl, handle: h, moved: false, pid: e.pointerId};
    h.classList.add("is-drag");
    try { h.setPointerCapture(e.pointerId); } catch (err) { /* capture unsupported */ }
    h.addEventListener("pointermove", onPointerMove);
    h.addEventListener("pointerup", onPointerUp);
    h.addEventListener("pointercancel", onPointerUp);
    // A release the handle never hears (capture lost, pointer left the frame) still ends the drag.
    h.addEventListener("lostpointercapture", onPointerUp);
    win.addEventListener("pointerup", onPointerUp, true);
  }
  function onPointerMove(e) {
    if (!drag || drag.done) return;
    const w = clamp(Math.round(drag.startW + (e.clientX - drag.startX)), RESIZE_MIN, RESIZE_MAX);
    if (w === drag.w) return;
    drag.w = w;
    drag.moved = true;
    if (drag.colEl) drag.colEl.style.width = `${w}px`;
    const i = L.cols.findIndex((c) => c.id === drag.colId);
    if (i >= 0) {
      L.cols[i] = {...L.cols[i], width: w};
      let left = 0;
      for (const c of L.cols) if (c.frozen) { c.left = left; left += c.width; }
      L.frozenWidth = left;
      writeFrozenStyle();
    }
  }
  function onPointerUp() {
    if (!drag || drag.done) return;
    const d = drag;
    d.handle.classList.remove("is-drag");
    d.handle.removeEventListener("pointermove", onPointerMove);
    d.handle.removeEventListener("pointerup", onPointerUp);
    d.handle.removeEventListener("pointercancel", onPointerUp);
    d.handle.removeEventListener("lostpointercapture", onPointerUp);
    win.removeEventListener("pointerup", onPointerUp, true);
    drag = {...d, done: true};
    setTimeout(() => { if (drag && drag.done) drag = null; }, 0);
    if (d.moved) resizeTo(d.colId, d.w);
  }
  function onDblResize(e) {
    const h = e.target.closest(".tb-rs");
    if (!h) return;
    e.preventDefault();
    e.stopPropagation();
    const th = h.closest("th");
    if (th) fitColumn(th.getAttribute("data-col"));
  }

  function onBarClick(e) {
    const b = e.target.closest("[data-tb]");
    if (!b || !view || !view.table) return;
    const key = b.getAttribute("data-tb");
    switch (key) {
      case "preset": presetMenu(b); break;
      case "find": dispatch({type: "OPEN_OVERLAY", overlay: "columnfinder"}); if (!finderOpen && !(getState().ui && getState().ui.overlay === "columnfinder")) openFinder(); break;
      case "view": viewMenu(b); break;
      case "hidden": hiddenMenu(b); break;
      default: break;
    }
  }
  let barHover = null, barTimer = null;
  function onBarOver(e) {
    const b = e.target.closest("[data-tb]");
    if (b === barHover) return;
    if (barHover && tipAnchor === barHover) hideTip();
    barHover = b;
    clearTimeout(barTimer);
    if (!b) return;
    barTimer = setTimeout(() => { if (barHover && barHover.isConnected) showTip(barHover, barTips.get(barHover.getAttribute("data-tb"))); }, TIP_DELAY_MS);
  }
  function onBarLeave() { clearTimeout(barTimer); if (barHover && tipAnchor === barHover) hideTip(); barHover = null; }
  function onBarFocus(e) {
    const b = e.target.closest("[data-tb]");
    if (b && e.target.matches(":focus-visible")) showTip(b, barTips.get(b.getAttribute("data-tb")));
  }
  function onBarBlur(e) { const b = e.target.closest("[data-tb]"); if (b && tipAnchor === b) hideTip(); }

  function onBoxScroll() {
    if (tipAnchor && table.contains(tipAnchor)) hideTip();
  }

  table.addEventListener("click", onTableClick);
  table.addEventListener("dblclick", onTableDblClick);
  table.addEventListener("keydown", onTableKey);
  table.addEventListener("focus", onFocus);
  table.addEventListener("blur", onBlur);
  table.addEventListener("focusout", onFocusOut);
  table.addEventListener("focusin", onFocusIn);
  table.addEventListener("pointerdown", onPointerMark, true);
  table.addEventListener("mouseover", onOver);
  table.addEventListener("mouseleave", onLeave);
  table.addEventListener("pointerdown", onPointerDown);
  table.addEventListener("dblclick", onDblResize, true);
  bar.addEventListener("click", onBarClick);
  bar.addEventListener("mouseover", onBarOver);
  bar.addEventListener("mouseleave", onBarLeave);
  bar.addEventListener("focusin", onBarFocus);
  bar.addEventListener("focusout", onBarBlur);
  box.addEventListener("scroll", onBoxScroll, {passive: true});
  mainEl = doc.getElementById("main");
  if (mainEl && mainEl.contains(root)) mainEl.addEventListener("scroll", onMainScroll, {passive: true});
  win.addEventListener("resize", onMainScroll);

  // Width changes (a docked side panel at ultrawide, a window resize, a layout switch) re-lay the
  // frozen block and the sub-row width without moving the scroll position or the active cell.
  let ro = null;
  if (typeof win.ResizeObserver === "function") {
    ro = new win.ResizeObserver(() => {
      if (roTimer) return;
      roTimer = (win.requestAnimationFrame || setTimeout)(() => {
        roTimer = null;
        if (destroyed || !view || !view.table || drag) return;
        fitBox();
        const w = box.clientWidth;
        const l = getLayout();
        if (l !== layoutName) { render(); return; }
        if (Math.abs(w - lastBoxWidth) < 1) return;
        const before = L.cols.filter((c) => c.frozen).map((c) => c.id).join(",");
        lastBoxWidth = w;
        const next = layoutColumns(view.table.columns, l, {widths: getState().widths || {}, boxWidth: w});
        if (next.cols.filter((c) => c.frozen).map((c) => c.id).join(",") !== before) render();
        else writeFrozenStyle();
      });
    });
    ro.observe(box);
    if (mainEl && mainEl.contains(root)) ro.observe(mainEl);
  }

  // ------------------------------------------------------------------------------------------
  // API (11.1)
  // ------------------------------------------------------------------------------------------

  function focusCell(ticker, colId) {
    const row = ticker || focalTicker();
    if (!row) return;
    const key = {row, col: colId || "ticker"};
    const id = cellDomId(key, labelCols);
    if (!id || !doc.getElementById(id) || !table.contains(doc.getElementById(id))) { pendingFocus = key; return; }
    pendingFocus = null;
    focusKey(key);
  }

  function getViewport() {
    return {scrollTop: box.scrollTop, scrollLeft: box.scrollLeft, focus: active ? {row: active.row, col: active.col} : null,
      width: box.clientWidth, height: box.clientHeight, layout: layoutName, frozenWidth: L.frozenWidth, focalPinned};
  }

  function destroy() {
    destroyed = true;
    clearTimeout(sendTimer);
    clearTimeout(hoverTimer);
    clearTimeout(barTimer);
    clearTimeout(pointerTimer);
    closePop(false);
    if (ro) ro.disconnect();
    table.removeEventListener("click", onTableClick);
    table.removeEventListener("dblclick", onTableDblClick);
    table.removeEventListener("keydown", onTableKey);
    table.removeEventListener("focus", onFocus);
    table.removeEventListener("blur", onBlur);
    table.removeEventListener("focusout", onFocusOut);
    table.removeEventListener("focusin", onFocusIn);
    table.removeEventListener("pointerdown", onPointerMark, true);
    table.removeEventListener("mouseover", onOver);
    table.removeEventListener("mouseleave", onLeave);
    table.removeEventListener("pointerdown", onPointerDown);
    table.removeEventListener("dblclick", onDblResize, true);
    bar.removeEventListener("click", onBarClick);
    bar.removeEventListener("mouseover", onBarOver);
    bar.removeEventListener("mouseleave", onBarLeave);
    bar.removeEventListener("focusin", onBarFocus);
    bar.removeEventListener("focusout", onBarBlur);
    box.removeEventListener("scroll", onBoxScroll);
    if (mainEl) mainEl.removeEventListener("scroll", onMainScroll);
    win.removeEventListener("resize", onMainScroll);
    win.removeEventListener("pointerup", onPointerUp, true);
    if (tipAnchor && root.contains(tipAnchor)) hideTip();
    root.innerHTML = "";
    root.classList.remove("tb");
    root.removeAttribute("data-density");
    root.removeAttribute("data-layout");
  }

  return {update, focusCell, scrollToColumn, getViewport, destroy};
}
