/**
 * figures.js: the Figures view of the Comps tab's Companies view.
 *
 * Contract: docs/design/comps-figures.md. One mount, `(root, ctx) -> {update(view), destroy()}`:
 *
 *   mountFigures  .fg-   three figures drawn from the cells the Table view prints:
 *                        1 where the company sits, one strip a measure
 *                        2 the peers on one measure, ranked
 *                        3 the whole set, each cell shaded by where it falls among the peers
 *
 * Nothing here computes a figure. Every value, percentile, distance from the median and summary
 * statistic comes from `view.table` (core.js buildTable), the same object table.js prints, so a
 * figure cannot disagree with the table. The pure functions (measures, tone, profileRows,
 * rankedBars, gridModel, position) arrange those cells for drawing and are what the node tests
 * exercise; the mount turns them into DOM. No colour literal: classes in figures.css, tokens only.
 *
 * A cell the table prints as not meaningful or not available is never drawn as a value: it has
 * no tick, no bar and no shade, and its row or its list says why.
 */

import {h, bindTip, hoverTip, stateBlock, sig} from "./charts.js";
import {COLUMN_BY_ID, PRESETS, fmtCell, fmtNumber} from "./core.js";

const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const TIMES = "×";
const MINUS = "−";

// ---------------------------------------------------------------------------------------------
// Pure: arranging the table's cells
// ---------------------------------------------------------------------------------------------

/** The measures of the table: its numeric columns, in the order the preset gives them. */
export function measures(table) {
  return ((table && table.columns) || []).filter((c) => c && c.numeric);
}

/** A cell's text with its unit where the unit is a suffix (16.2×, 8.6%); otherwise the text. */
export function withUnit(text, col) {
  if (!text || !col) return text || "";
  const unit = String(col.unitText || "");
  if (!/^[0-9+\-−]/.test(text)) return text;               // n.m., a dash: not a number
  if (unit === TIMES) return text + TIMES;
  if (unit === "%") return text + "%";
  return text;
}

/**
 * What a distance from the median means for this measure: "up" where the measure has a better
 * end and the value is on it, "down" where it is on the worse end, "none" where the measure has
 * no better end (a multiple: a premium is a premium, not good or bad) or the value sits on the
 * median or is not on file.
 */
export function tone(col, vsMedian) {
  if (!col || !isNum(vsMedian) || vsMedian === 0) return "none";
  if (col.dir === "+") return vsMedian > 0 ? "up" : "down";
  if (col.dir === "-") return vsMedian < 0 ? "up" : "down";
  return "none";
}

/** The distance from the median as words: "+5%", "−12%", "at median". */
export function distanceText(vsMedian) {
  if (!isNum(vsMedian)) return "";
  const pct = Math.round(vsMedian * 100);
  if (pct === 0) return "at median";
  return `${pct > 0 ? "+" : MINUS}${Math.abs(pct)}%`;
}

function plotted(cell) { return !!cell && cell.status === "ok" && isNum(cell.v); }

/** Where a value falls between the ends of a domain, 0 to 100, clamped. */
export function position(v, domain) {
  if (!isNum(v) || !domain) return null;
  const [lo, hi] = domain;
  if (!(hi > lo)) return 50;
  return Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
}

/** The ends a strip is drawn between: every plotted value, padded so no mark sits on the edge. */
export function domainOf(values, pad = 0.06) {
  const x = values.filter(isNum);
  if (!x.length) return null;
  const lo = Math.min(...x), hi = Math.max(...x);
  const span = hi - lo || Math.abs(hi) || 1;
  return [lo - span * pad, hi + span * pad];
}

/**
 * Figure 1: one row a measure. The focal company's figure, the peers' figures as ticks, the
 * median and the middle half from the table's own statistics, the distance from the median and
 * the rank among the peers in the statistics. A measure with nothing to plot keeps its row and
 * says why.
 */
export function profileRows(table) {
  const rows = (table && table.rows) || [];
  const focal = rows.find((r) => r.isFocal) || null;
  const stats = (table && table.stats) || {};
  return measures(table).map((col) => {
    const def = COLUMN_BY_ID[col.id] || col;
    const st = stats[col.id] || null;
    const fc = focal ? focal.cells[col.id] : null;
    const peers = rows.filter((r) => !r.isFocal).map((r) => ({ticker: r.ticker, name: r.name, excluded: !!r.excluded,
      cell: r.cells[col.id]}));
    const drawn = peers.filter((p) => plotted(p.cell));
    const counted = drawn.filter((p) => !p.excluded);
    const ok = plotted(fc);
    const text = (v) => withUnit(fmtCell({status: "ok", v}, def), col);
    const domain = domainOf(drawn.map((p) => p.cell.v).concat(ok ? [fc.v] : []));
    const hasStats = !!st && st.n >= 2 && isNum(st.median) && !st.mixedCurrency;
    return {
      colId: col.id, label: col.label, unit: col.unitLine || "", group: col.group, dir: col.dir,
      isPrimary: !!col.isPrimary, domain,
      focal: ok ? {v: fc.v, text: withUnit(fmtCell(fc, def), col), pos: position(fc.v, domain)}
        : {v: null, text: fmtCell(fc, def), pos: null, reason: (fc && fc.reason) || "No value on file"},
      median: hasStats ? {v: st.median, text: text(st.median), pos: position(st.median, domain)} : null,
      band: hasStats && isNum(st.p25) && isNum(st.p75)
        ? {from: position(st.p25, domain), to: position(st.p75, domain), text: `${text(st.p25)} to ${text(st.p75)}`} : null,
      n: st ? st.n : 0,
      vsMedian: ok && hasStats ? fc.vsMedian : null,
      distance: ok && hasStats ? distanceText(fc.vsMedian) : "",
      tone: ok && hasStats ? tone(col, fc.vsMedian) : "none",
      rank: ok && counted.length ? 1 + counted.filter((p) => p.cell.v > fc.v).length : null,
      of: ok && counted.length ? counted.length + 1 : null,
      peers: drawn.map((p) => ({ticker: p.ticker, name: p.name, v: p.cell.v, text: withUnit(fmtCell(p.cell, def), col),
        pos: position(p.cell.v, domain), excluded: p.excluded})),
      missing: peers.length - drawn.length,
    };
  });
}

/**
 * Figure 2: one measure, every company with a figure as a bar, largest first, on a scale that
 * holds nil so a negative figure is a bar to the left of it. Companies with no figure are
 * listed with the reason and not drawn.
 */
export function rankedBars(table, colId) {
  const col = measures(table).find((c) => c.id === colId) || measures(table)[0] || null;
  if (!col) return null;
  const def = COLUMN_BY_ID[col.id] || col;
  const st = ((table && table.stats) || {})[col.id] || null;
  const all = ((table && table.rows) || []).map((r) => ({ticker: r.ticker, name: r.name, isFocal: !!r.isFocal,
    excluded: !!r.excluded, cell: r.cells[col.id]}));
  const bars = all.filter((r) => plotted(r.cell)).sort((a, b) => b.cell.v - a.cell.v || a.ticker.localeCompare(b.ticker));
  const values = bars.map((b) => b.cell.v);
  const lo = Math.min(0, ...values), hi = Math.max(0, ...values);
  const domain = bars.length ? [lo, hi > lo ? hi : lo + 1] : null;
  const text = (v) => withUnit(fmtCell({status: "ok", v}, def), col);
  const hasStats = !!st && st.n >= 2 && isNum(st.median) && !st.mixedCurrency;
  return {
    colId: col.id, label: col.label, unit: col.unitLine || "", domain, zero: position(0, domain),
    bars: bars.map((b) => ({ticker: b.ticker, name: b.name, isFocal: b.isFocal, excluded: b.excluded, v: b.cell.v,
      text: withUnit(fmtCell(b.cell, def), col), pos: position(b.cell.v, domain)})),
    median: hasStats ? {v: st.median, text: text(st.median), pos: position(st.median, domain)} : null,
    quartiles: hasStats && isNum(st.p25) && isNum(st.p75)
      ? [{v: st.p25, pos: position(st.p25, domain)}, {v: st.p75, pos: position(st.p75, domain)}] : [],
    missing: all.filter((r) => !plotted(r.cell)).map((r) => ({ticker: r.ticker, name: r.name,
      why: fmtCell(r.cell, def) === "n.m." ? "not meaningful" : "no value"})),
  };
}

/**
 * Figure 3: the table's own grid, each cell carrying where it falls among the peers. `shade` is
 * 0 to 1: for a measure with a better end, how far the cell is from the median toward either
 * end, coloured by which; for one with none, how high the value ranks. A cell that is not a
 * value has no shade.
 */
export function gridModel(table) {
  const cols = measures(table);
  return {
    columns: cols.map((c) => ({id: c.id, label: c.label, unit: c.unitLine || "", dir: c.dir, isPrimary: !!c.isPrimary})),
    rows: ((table && table.rows) || []).map((r) => ({
      ticker: r.ticker, name: r.name, isFocal: !!r.isFocal, excluded: !!r.excluded,
      cells: cols.map((c) => {
        const cell = r.cells[c.id];
        const def = COLUMN_BY_ID[c.id] || c;
        const ok = plotted(cell) && isNum(cell.pct);
        const t = ok ? tone(c, cell.vsMedian) : "none";
        const shade = !ok ? null : c.dir === "n" ? cell.pct / 100 : Math.abs(cell.pct - 50) / 50;
        return {text: withUnit(fmtCell(cell, def), c), pct: ok ? cell.pct : null, tone: c.dir === "n" ? "size" : t,
          shade, reason: !plotted(cell) ? ((cell && cell.reason) || "") : ""};
      }),
    })),
  };
}

/** "6 of 17" with the ordinal words a tooltip wants. */
function rankText(row) { return row.rank && row.of ? `${row.rank} of ${row.of}` : ""; }

// ---------------------------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------------------------

function dispatch(ctx, action) { if (ctx && typeof ctx.dispatch === "function") ctx.dispatch(action); }
function openDetail(ctx, ticker) {
  if (ctx && typeof ctx.openDetail === "function") ctx.openDetail(ticker);
  else dispatch(ctx, {type: "OPEN_DETAIL", ticker});
}
function pctStyle(v) { return `${Math.round(v * 100) / 100}%`; }

export function mountFigures(root, ctx) {
  let selected = null;                 // the measure of figure 2; null follows the primary
  let lastSig = null;
  const descs = h("div", {hidden: true, class: "fg-desc"});
  const body = h("div", {class: "fg"});
  root.append(body, descs);

  /** Mark one peer on every strip, bar and grid row while the pointer rests on any of its marks. */
  function hot(ticker, on) {
    for (const el of body.querySelectorAll(`[data-ticker="${ticker}"]`)) el.classList.toggle("is-hot", on);
  }
  /** A mark that stands for one company: resting on it marks that company on every figure, and a
   * press opens its panel. With `label` the mark is also a stop for the keyboard: Tab reaches it,
   * Enter or Space opens the panel. The strips' ticks are not stops (there are a hundred of them);
   * every company they draw is a row of the ranked bars and of the grid, which are. */
  function bindPeer(el, ticker, tip, label) {
    el.setAttribute("data-ticker", ticker);
    el.addEventListener("mouseenter", () => hot(ticker, true));
    el.addEventListener("mouseleave", () => hot(ticker, false));
    el.addEventListener("click", (e) => { e.stopPropagation(); openDetail(ctx, ticker); });
    if (label) {
      el.setAttribute("tabindex", "0");
      el.setAttribute("aria-label", label);
      el.addEventListener("focus", () => hot(ticker, true));
      el.addEventListener("blur", () => hot(ticker, false));
      el.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        e.stopPropagation();
        openDetail(ctx, ticker);
      });
    }
    hoverTip(ctx, el, tip);
  }

  function presetControl(table) {
    const sel = h("select", {class: "u-input fg-preset", "aria-label": "Measures"},
      PRESETS.filter((p) => p.id !== "custom" || table.preset === "custom")
        .map((p) => h("option", {value: p.id, selected: p.id === table.preset, text: p.label})));
    sel.addEventListener("change", () => {
      dispatch(ctx, {type: "SET_PRESET", preset: sel.value});
      if (ctx && typeof ctx.announce === "function") ctx.announce(`Measures: ${sel.options[sel.selectedIndex].text}`);
    });
    return h("label", {class: "fg-ctl"}, h("span", {class: "fg-k", text: "Measures"}), sel);
  }

  function strip(row) {
    const el = h("div", {class: "fg-strip", role: "img",
      "aria-label": row.focal.v === null ? `${row.label}: ${row.focal.reason}`
        : `${row.label}: ${row.focal.text}${row.median ? `, median ${row.median.text}` : ""}${row.rank ? `, ${rankText(row)}` : ""}`});
    if (!row.domain) return el;
    if (row.band) {
      el.append(h("i", {class: "fg-band", style: `left:${pctStyle(row.band.from)};width:${pctStyle(Math.max(row.band.to - row.band.from, 0.6))}`,
        title: `Middle half of the peers: ${row.band.text}`}));
    }
    if (row.median) el.append(h("i", {class: "fg-median", style: `left:${pctStyle(row.median.pos)}`, title: `Median ${row.median.text}`}));
    for (const p of row.peers) {
      const tick = h("i", {class: `fg-tick${p.excluded ? " is-out" : ""}`, style: `left:${pctStyle(p.pos)}`});
      bindPeer(tick, p.ticker, () => `${p.name} (${p.ticker}): ${p.text}${p.excluded ? ", left out of the statistics" : ""}`);
      el.append(tick);
    }
    if (row.focal.pos !== null) {
      el.append(h("i", {class: `fg-focal fg-${row.tone}`, style: `left:${pctStyle(row.focal.pos)}`, title: `${row.focal.text}`}));
    }
    return el;
  }

  function profile(view, rows, activeId) {
    const T = view.focal && view.focal.ticker ? view.focal.ticker : "the company";
    const sec = h("section", {class: "fg-sec fg-profile", "aria-label": "Where the company sits"});
    sec.append(h("div", {class: "fg-head"},
      h("h3", {class: "fg-title", text: `Where ${T} sits`}),
      h("span", {class: "fg-sub", text: "each tick a peer, the band their middle half, the rule the median"})));
    const list = h("div", {class: "fg-rows", role: "list"});
    let group = null;
    for (const row of rows) {
      if (row.group !== group) {
        group = row.group;
        const label = (view.table.groups || []).find((g) => g.id === group);
        list.append(h("div", {class: "fg-group", text: label ? label.label : group}));
      }
      const r = h("button", {type: "button", role: "listitem", class: `fg-row${row.colId === activeId ? " is-active" : ""}`,
        "data-col": row.colId, "aria-pressed": String(row.colId === activeId)});
      r.append(
        h("span", {class: "fg-name"}, h("span", {class: "fg-label", text: row.label}),
          row.isPrimary ? h("span", {class: "fg-primary", text: "Primary"}) : null,
          h("span", {class: "fg-unit", text: row.unit})),
        strip(row),
        h("span", {class: `fg-value${row.focal.v === null ? " is-null" : ""}`, text: row.focal.text}),
        h("span", {class: `fg-dist fg-${row.tone}`, text: row.focal.v === null ? "" : row.distance}),
        h("span", {class: "fg-rank", text: rankText(row)}));
      bindTip(ctx, r, () => (row.focal.v === null
        ? {title: row.label, body: `${row.focal.reason}. ${row.peers.length} peers have a figure.`}
        : {title: `${row.label}: ${row.focal.text}`,
          body: [row.median ? `Median of ${row.n} peers ${row.median.text}` : "Too few peers for a median",
            row.band ? `middle half ${row.band.text}` : null, row.rank ? `ranks ${rankText(row)}, largest first` : null,
            row.missing ? `${row.missing} with no figure` : null, "Press to rank the peers on it"].filter(Boolean).join(". ") + "."}), descs);
      r.addEventListener("click", () => { selected = row.colId; lastSig = null; draw(ctx.getView ? ctx.getView() : view); });
      list.append(r);
    }
    sec.append(list);
    return sec;
  }

  function ranked(model) {
    const sec = h("section", {class: "fg-sec fg-ranked", "aria-label": "The peers on one measure"});
    sec.append(h("div", {class: "fg-head"},
      h("h3", {class: "fg-title", text: `The peers on ${model.label}`}),
      h("span", {class: "fg-sub", text: model.unit})));
    const list = h("div", {class: "fg-bars", role: "list"});
    for (const b of model.bars) {
      const from = Math.min(model.zero, b.pos), width = Math.max(Math.abs(b.pos - model.zero), 0.5);
      const track = h("span", {class: "fg-track"},
        h("i", {class: "fg-zero", style: `left:${pctStyle(model.zero)}`}),
        ...model.quartiles.map((q) => h("i", {class: "fg-quartile", style: `left:${pctStyle(q.pos)}`})),
        model.median ? h("i", {class: "fg-median", style: `left:${pctStyle(model.median.pos)}`}) : null,
        h("i", {class: `fg-bar${b.isFocal ? " is-focal" : ""}${b.excluded ? " is-out" : ""}`,
          style: `left:${pctStyle(from)};width:${pctStyle(width)}`}));
      const row = h("div", {class: `fg-barrow${b.isFocal ? " is-focal" : ""}`, role: "listitem"},
        h("span", {class: "fg-tk", text: b.ticker}), track, h("span", {class: "fg-bv", text: b.text}));
      const said = `${b.name}: ${b.text}${b.excluded ? ", left out of the statistics" : ""}`;
      bindPeer(row, b.ticker, () => `${said}. Press for the company.`, `${said}. Open the company.`);
      list.append(row);
    }
    sec.append(list);
    const foot = [];
    if (model.median) foot.push(`Median ${model.median.text}, the solid rule; the quartiles dotted.`);
    if (model.missing.length) {
      foot.push(`Not drawn: ${model.missing.map((m) => `${m.ticker} (${m.why})`).join(", ")}.`);
    }
    if (foot.length) sec.append(h("p", {class: "fg-note", text: foot.join(" ")}));
    return sec;
  }

  function grid(model) {
    const sec = h("section", {class: "fg-sec fg-grid", "aria-label": "The whole peer set"});
    sec.append(h("div", {class: "fg-head"},
      h("h3", {class: "fg-title", text: "The whole set"}),
      h("span", {class: "fg-sub", text: "each cell shaded by where it falls among the peers: green and red where a measure has a better end, grey by size where it has none"})));
    const head = h("tr", {}, h("th", {scope: "col", class: "fg-gco", text: "Company"}),
      ...model.columns.map((c) => h("th", {scope: "col", title: c.unit, class: c.isPrimary ? "is-primary" : null, text: c.label})));
    const rows = model.rows.map((r) => {
      const tr = h("tr", {class: `${r.isFocal ? "is-focal" : ""}${r.excluded ? " is-out" : ""}`.trim() || null},
        h("th", {scope: "row", class: "fg-gco"}, h("span", {class: "fg-tk", text: r.ticker}), h("span", {class: "fg-gname", text: r.name})),
        ...r.cells.map((c) => h("td", {class: `fg-cell fg-${c.tone}${c.shade === null ? " is-null" : ""}`,
          style: c.shade === null ? null : `--fg-a:${Math.round(c.shade * 100)}%`,
          title: c.shade === null ? (c.reason || null) : `${Math.round(c.pct)} percentile of the peers`, text: c.text})));
      bindPeer(tr, r.ticker, () => `${r.name}. Press for the company.`, `${r.name}. Open the company.`);
      return tr;
    });
    sec.append(h("div", {class: "fg-gridwrap"}, h("table", {class: "fg-table"}, h("thead", {}, head), h("tbody", {}, rows))));
    return sec;
  }

  function draw(view) {
    const table = view && view.table;
    body.textContent = "";
    descs.textContent = "";
    if (!table) return;
    if (table.empty) { body.append(stateBlock(table.empty)); return; }
    const rows = profileRows(table);
    if (!rows.length) {
      body.append(presetControl(table), h("p", {class: "fg-note", text: "This set of columns has no measures to draw. Choose another, or open the Table view."}));
      return;
    }
    const primary = rows.find((r) => r.isPrimary);
    const activeId = rows.some((r) => r.colId === selected) ? selected : (primary || rows[0]).colId;
    body.append(
      h("div", {class: "fg-top"}, presetControl(table),
        h("span", {class: "fg-hint", text: "Press a measure to rank the peers on it. Press a company for its facts."})),
      h("div", {class: "fg-cols"}, profile(view, rows, activeId), ranked(rankedBars(table, activeId))),
      grid(gridModel(table)));
  }

  return {
    update(view) {
      const t = view && view.table;
      // Everything a figure draws: the measures, each company's figures on them and whether
      // it counts. A change to anything else (a hover, an open panel) redraws nothing.
      const cols = t ? measures(t).map((c) => c.id) : [];
      const next = t ? sig(t.preset, t.caption, cols, selected, t.empty ? 1 : 0,
        (t.rows || []).map((r) => [r.ticker, r.excluded ? 1 : 0, cols.map((id) => (r.cells[id] || {}).v ?? null)])) : "none";
      if (next === lastSig) return;
      lastSig = next;
      draw(view);
    },
    destroy() { body.remove(); descs.remove(); },
  };
}
