/**
 * scorecard.js: the Scorecard view of the Comps tab's Companies view. Owner E2.
 *
 * Contract: docs/design/company-scorecard.md, sections 1.4, 3 and 4.2, revision 4 of this frame
 * (5.2, 6.3). Two mounts, each `(root, ctx) -> {update(view), destroy()}`:
 *
 *   mountScorecard  .sc-   the company map Python drew (`ctx.chart`, an SVG string the frame
 *                          never rebuilds), the ranked table with shaded pillar cells beside it,
 *                          and the lines under the chart
 *   mountCompare    .cmp-  the Compare sheet, laid over both while `state.ui.compareOpen`
 *
 * Nothing here scores or words a figure: every number and line comes from `view.scorecard` and
 * `view.compare` (core.js), which arrange `payload.scorecard` as the server built it. The frame
 * binds the chart's bubbles (`g.cm-pt[data-ticker]`): a click or Enter opens the company panel,
 * Space ticks the company for Compare. Hovering a row rings its bubble and hovering a bubble
 * marks its row. No colour literal: classes in scorecard.css, tokens only.
 */

import {h, chip, stateBlock, bindTip, uid, rebuildKeepingFocus, sig} from "./charts.js";
import {SCORECARD_COPY, COMPARE_MAX} from "./core.js";

const UP = "▲";
/** Under this frame height the how-to-read line moves into the key row's tooltip (3.3). */
export const SHORT_FRAME = 600;

function stateOf(ctx) {
  try { return ctx && typeof ctx.getState === "function" ? ctx.getState() || {} : {}; } catch (e) { return {}; }
}
function dispatch(ctx, action) { if (ctx && typeof ctx.dispatch === "function") ctx.dispatch(action); }
function announce(ctx, text) { if (ctx && typeof ctx.announce === "function" && text) ctx.announce(text); }
function chartOf(ctx) {
  try {
    const c = ctx ? (typeof ctx.chart === "function" ? ctx.chart() : ctx.chart) : null;
    return c && typeof c === "object" ? {svg: typeof c.svg === "string" ? c.svg : "", digest: String(c.digest || "")} : {svg: "", digest: ""};
  } catch (e) { return {svg: "", digest: ""}; }
}
function hiddenHost(parent) {
  const host = h("div", {hidden: true, class: "sc-desc"});
  parent.appendChild(host);
  return host;
}

// ---------------------------------------------------------------------------------------------
// Pure helpers, exported for the node tests
// ---------------------------------------------------------------------------------------------

/**
 * What a key or a click on the chart asks for: `{kind: "open"|"pick", ticker}` or null. A click,
 * or Enter on a focused bubble, opens the panel; Space ticks the company for Compare. A label
 * (`text.cm-label[data-ticker]`) opens its company too.
 */
export function chartAction(target, key = "click") {
  if (!target || typeof target.closest !== "function") return null;
  const g = target.closest(".cm-pt") || target.closest(".cm-label");
  if (!g) return null;
  const ticker = g.getAttribute("data-ticker");
  if (!ticker) return null;
  if (key === "click" || key === "Enter") return {kind: "open", ticker};
  if (key === " " || key === "Spacebar") return g.classList && g.classList.contains("cm-pt") ? {kind: "pick", ticker} : null;
  return null;
}

/** Run a chart action through the frame: open the panel, or tick for Compare (a fourth is
 * refused with the copy of 8.1). Returns true when the event was used. */
export function runChartAction(act, ctx) {
  if (!act) return false;
  if (act.kind === "open") {
    if (ctx && typeof ctx.openDetail === "function") ctx.openDetail(act.ticker);
    else dispatch(ctx, {type: "OPEN_DETAIL", ticker: act.ticker});
    return true;
  }
  if (act.kind === "pick") { togglePick(ctx, act.ticker); return true; }
  return false;
}

/** Tick or untick a company for Compare; a fourth tick is refused and said so. */
export function togglePick(ctx, ticker) {
  if (ctx && typeof ctx.toggleCompare === "function") return ctx.toggleCompare(ticker);
  const st = stateOf(ctx);
  const cur = (st.ui && st.ui.compare) || [];
  if (!cur.includes(ticker) && cur.length >= COMPARE_MAX) {
    announce(ctx, SCORECARD_COPY.compareFull);
    if (ctx && typeof ctx.toast === "function") ctx.toast(SCORECARD_COPY.compareFull);
    return false;
  }
  dispatch(ctx, {type: "TOGGLE_COMPARE", ticker});
  return true;
}

/** Mark the bubbles: `is-open` for the company in the panel, `is-picked` for Compare's picks,
 * `is-hover` for the row under the pointer. Works on any root with querySelectorAll. */
export function markChart(root, S, hover = null) {
  if (!root || typeof root.querySelectorAll !== "function") return 0;
  const picked = new Set(((S && S.rows) || []).filter((r) => r.picked).map((r) => r.ticker));
  const open = ((S && S.rows) || []).find((r) => r.open);
  let n = 0;
  for (const g of root.querySelectorAll(".cm-pt")) {
    const t = g.getAttribute("data-ticker");
    g.classList.toggle("is-picked", picked.has(t));
    g.classList.toggle("is-open", !!open && open.ticker === t);
    g.classList.toggle("is-hover", !!hover && hover === t);
    g.setAttribute("aria-pressed", String(picked.has(t)));
    n += 1;
  }
  return n;
}

/** Custom properties on an element: style.setProperty, since assigning them as style keys
 * does nothing. */
function setVars(el, vars) {
  if (!el || !vars) return;
  for (const [k, v] of Object.entries(vars)) el.style.setProperty(k, v);
}

/** Shading of a cell: the custom property the stylesheet mixes the token with. */
export function cellStyle(c) {
  return c && c.fill ? {"--sc-a": String(c.alpha)} : null;
}

// ---------------------------------------------------------------------------------------------
// mountScorecard
// ---------------------------------------------------------------------------------------------

export function mountScorecard(root, ctx) {
  root.classList.add("sc-root");
  const doc = root.ownerDocument;
  let view = null, lastSig = null, destroyed = false;
  let chartDigest = null, chartHost = null, chartWrap = null;
  let hover = null, scrolledFor = null;

  function short() {
    const w = doc.defaultView;
    return !!w && w.innerHeight > 0 && w.innerHeight < SHORT_FRAME;
  }

  function render() {
    if (destroyed || !view) return;
    const S = view.scorecard;
    const chart = chartOf(ctx);
    const s = sig(S && {...S, rows: (S.rows || []).map((r) => [r.ticker, r.picked, r.open, r.cells.map((c) => c.title)])},
      short(), chart.digest, view.focal && view.focal.ticker);
    if (s === lastSig) { markChart(chartHost, S, hover); return; }
    lastSig = s;
    // The chart host survives a rebuild of the table: the drawing is swapped only when Python
    // sent a new one, so a tick or an open panel never redraws it.
    const keep = chartWrap && chartWrap.isConnected ? chartWrap : null;
    if (keep) keep.remove();
    rebuildKeepingFocus(root, () => {
      root.textContent = "";
      build(S, chart, keep);
    });
    markChart(chartHost, S, hover);
    fitUnder();
    if (S && S.state === "ok" && scrolledFor !== (view.focal && view.focal.ticker)) {
      scrolledFor = view.focal && view.focal.ticker;
      const wrap = root.querySelector(".sc-table-wrap");
      const row = wrap ? wrap.querySelector("tr.is-focal") : null;
      if (wrap && row && row.offsetTop + row.offsetHeight > wrap.clientHeight) {
        wrap.scrollTop = Math.max(0, row.offsetTop - wrap.clientHeight / 2);
      }
    }
  }

  function build(S, chart, keep) {
    const descHost = hiddenHost(root);
    if (!S || S.state !== "ok") {
      const text = (S && S.errorText) || SCORECARD_COPY.failed.replace("{error}", "no result");
      const box = h("div", {class: "sc-failed"});
      box.appendChild(stateBlock({severity: "amber", title: "Scorecard unavailable", detail: text}));
      const b = h("button", {type: "button", class: "u-btn sc-to-table", "data-key": "sc-to-table", text: "Open the Table view"});
      b.addEventListener("click", () => setView("table"));
      box.appendChild(b);
      root.appendChild(box);
      chartHost = null;
      return;
    }
    const isShort = short();
    const wrap = h("div", {class: `sc-view${isShort ? " is-short" : ""}`});
    root.appendChild(wrap);

    // Chart column.
    const col = h("div", {class: "sc-chart-col"});
    wrap.appendChild(col);
    if (keep && chart.digest === chartDigest) {
      chartWrap = keep;
    } else {
      chartWrap = h("div", {class: "sc-chart-wrap"});
      const host = h("div", {class: "sc-chart", role: "group", "aria-label": `${S.contextText}: company score across, value score up`});
      chartWrap.appendChild(host);
      if (chart.svg) {
        host.innerHTML = chart.svg;
        const svg = host.querySelector("svg");
        if (svg) svg.classList.add("sc-svg");
      }
      else host.appendChild(h("p", {class: "sc-note", text: S.noChartText || "No chart for this cohort."}));
      chartDigest = chart.digest;
      bindChart(host);
    }
    chartHost = chartWrap.querySelector(".sc-chart");
    col.appendChild(chartWrap);
    // The key row's extras sit over the drawing's own key line, at its right end.
    const extras = h("div", {class: "sc-key-extra"});
    if (isShort) {
      const info = h("button", {type: "button", class: "u-btn link sc-how-btn", "data-key": "sc-how", "aria-label": S.howToRead,
        text: `${SCORECARD_COPY.howToReadShort} ⓘ`});
      bindTip(ctx, info, S.howToRead, descHost);
      extras.appendChild(info);
    }
    const method = h("button", {type: "button", class: "u-btn link sc-method-btn", "data-key": "sc-method", text: S.methodLink});
    method.addEventListener("click", () => {
      if (ctx && typeof ctx.openMethod === "function") ctx.openMethod("scorecard");
      else dispatch(ctx, {type: "OPEN_METHOD", anchor: "scorecard"});
    });
    extras.appendChild(method);
    chartWrap.querySelectorAll(".sc-key-extra").forEach((x) => x.remove());
    chartWrap.appendChild(extras);
    const under = h("div", {class: "sc-under"});
    if (!isShort) under.appendChild(h("p", {class: "sc-how", text: S.howToRead}));
    for (const t of [S.notRankedText, S.notOnChartText]) if (t) under.appendChild(h("p", {class: "sc-note", text: t}));
    if (under.childNodes.length) col.appendChild(under);

    // Table column.
    const tcol = h("div", {class: "sc-table-col"});
    wrap.appendChild(tcol);
    const tw = h("div", {class: "sc-table-wrap", "data-scroll-key": "sc-table"});
    tcol.appendChild(tw);
    const capId = uid("sccap");
    const table = h("table", {class: "sc-table", "aria-labelledby": capId});
    table.appendChild(h("caption", {class: "u-sr", id: capId,
      text: `${S.contextText}. Ranked by company score; cells are shaded by pillar score, green above the cohort middle and red below. Tick up to three to compare.`}));
    const C = SCORECARD_COPY.table;
    const hr = h("tr");
    hr.appendChild(h("th", {scope: "col", class: "sc-box"}, h("span", {class: "u-sr", text: "Compare"})));
    const th = (text, cls, title) => {
      const el = h("th", {scope: "col", class: cls, tabindex: title ? "0" : null, text});
      if (title) bindTip(ctx, el, title, descHost);
      return el;
    };
    hr.appendChild(th(C.rank, "sc-rank", C.rankTitle));
    hr.appendChild(th(C.range, "sc-range", C.rangeTitle));
    hr.appendChild(th(C.company, "sc-co", null));
    hr.appendChild(th(C.score, "sc-score", C.scoreTitle));
    for (const c of S.columns) hr.appendChild(th(c.header, "sc-pcol", c.title));
    table.appendChild(h("thead", {}, hr));
    const tb = h("tbody");
    for (const r of S.rows) tb.appendChild(rowEl(r, S, descHost));
    table.appendChild(tb);
    tw.appendChild(table);
  }

  function rowEl(r, S, descHost) {
    const cls = ["sc-row", r.focal ? "is-focal" : "", r.open ? "is-open" : "", r.picked ? "is-picked" : "",
      r.ranked ? "" : "is-unranked", hover === r.ticker ? "is-hover" : ""].filter(Boolean).join(" ");
    const tr = h("tr", {class: cls, "data-ticker": r.ticker});
    const box = h("input", {type: "checkbox", class: "sc-check", "data-key": `sc-pick-${r.ticker}`,
      "aria-label": `Compare ${r.ticker}`, checked: r.picked});
    box.addEventListener("click", (e) => {
      e.stopPropagation();
      const ok = togglePick(ctx, r.ticker);
      if (ok === false) e.preventDefault();
    });
    tr.appendChild(h("td", {class: "sc-box"}, box));
    tr.appendChild(h("td", {class: "sc-rank u-num", text: r.rank != null ? String(r.rank) : "·"}));
    tr.appendChild(h("td", {class: "sc-range u-num", text: r.rangeText || ""}));
    const tk = h("button", {type: "button", class: "sc-tk", "data-key": `sc-open-${r.ticker}`,
      "aria-label": `${r.ticker}, ${r.name}. Open its facts`, text: r.ticker});
    tk.addEventListener("click", (e) => { e.stopPropagation(); runChartAction({kind: "open", ticker: r.ticker}, ctx); });
    bindTip(ctx, tk, r.ranked ? r.name : r.rowTitle, descHost);
    tr.appendChild(h("td", {class: "sc-co"}, tk));
    const sc = h("td", {class: "sc-score"});
    if (r.score != null) {
      sc.appendChild(h("span", {class: "sc-bar", "aria-hidden": "true"}, h("span", {class: "sc-bar-fill", style: {width: `${Math.max(0, Math.min(100, r.score))}%`}})));
      sc.appendChild(h("span", {class: "u-num sc-score-n", text: String(r.score)}));
    } else {
      sc.appendChild(h("span", {class: "u-null", text: "·"}));
      if (r.reason) bindTip(ctx, sc, r.rowTitle, descHost);
    }
    tr.appendChild(sc);
    for (const c of r.cells) {
      const td = h("td", {class: `sc-cell${c.fill ? ` ${c.fill}` : ""}${c.missing ? " is-missing" : ""}`,
        tabindex: "-1"}, c.missing ? h("span", {"aria-hidden": "true", text: "·"}) : null, h("span", {class: "u-sr", text: c.title}));
      setVars(td, cellStyle(c));
      bindTip(ctx, td, c.title, null);
      tr.appendChild(td);
    }
    tr.addEventListener("click", () => runChartAction({kind: "open", ticker: r.ticker}, ctx));
    tr.addEventListener("mouseenter", () => setHover(r.ticker));
    tr.addEventListener("mouseleave", () => setHover(null));
    return tr;
  }

  function setHover(t) {
    if (hover === t) return;
    hover = t;
    markChart(chartHost, view && view.scorecard, hover);
    for (const tr of root.querySelectorAll("tr.sc-row")) tr.classList.toggle("is-hover", tr.getAttribute("data-ticker") === t);
  }

  function bindChart(host) {
    host.addEventListener("click", (e) => { if (runChartAction(chartAction(e.target, "click"), ctx)) e.preventDefault(); });
    host.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
      const act = chartAction(e.target, e.key);
      if (act && runChartAction(act, ctx)) { e.preventDefault(); e.stopPropagation(); }
    });
    host.addEventListener("mouseover", (e) => {
      const g = e.target && e.target.closest ? e.target.closest(".cm-pt") : null;
      setHover(g ? g.getAttribute("data-ticker") : null);
    });
    host.addEventListener("mouseleave", () => setHover(null));
  }

  // The lines under the chart take what they need; the drawing fits the rest of #main.
  function fitUnder() {
    const under = root.querySelector(".sc-under");
    const px = under ? Math.ceil(under.getBoundingClientRect().height) : 0;
    root.style.setProperty("--sc-under", `${px}px`);
  }

  function setView(v) {
    if (ctx && typeof ctx.setView === "function") ctx.setView(v);
    else dispatch(ctx, {type: "SET_VIEW", value: v});
  }

  const onResize = () => { lastSig = null; render(); };
  const win = doc.defaultView;
  if (win) win.addEventListener("resize", onResize);

  return {
    update(v) { view = v; render(); },
    destroy() {
      destroyed = true;
      if (win) win.removeEventListener("resize", onResize);
      root.textContent = "";
      root.classList.remove("sc-root");
    },
  };
}

// ---------------------------------------------------------------------------------------------
// mountCompare (4.2): never shown until asked for
// ---------------------------------------------------------------------------------------------

export function mountCompare(root, ctx) {
  root.classList.add("cmp-root");
  let view = null, lastSig = null, destroyed = false, wasOpen = false, opener = null;
  const doc = root.ownerDocument;

  function close() {
    if (ctx && typeof ctx.closeCompare === "function") ctx.closeCompare();
    else dispatch(ctx, {type: "CLOSE_COMPARE"});
  }

  function render() {
    if (destroyed || !view) return;
    const V = view.compare;
    const s = sig(V);
    if (s === lastSig) return;
    lastSig = s;
    root.toggleAttribute("data-open", !!V);
    if (!V) {
      root.textContent = "";
      if (wasOpen) {
        wasOpen = false;
        if (opener && opener.isConnected) { try { opener.focus({preventScroll: true}); } catch (e) { opener.focus(); } }
        opener = null;
      }
      return;
    }
    if (!wasOpen) {
      const ae = doc.activeElement;
      opener = ae && ae !== doc.body && !root.contains(ae) ? ae : null;
    }
    rebuildKeepingFocus(root, () => { root.textContent = ""; build(V); });
    if (!wasOpen) {
      wasOpen = true;
      const t = root.querySelector(".cmp-title");
      if (t) { try { t.focus({preventScroll: true}); } catch (e) { t.focus(); } }
    }
  }

  function build(V) {
    const descHost = h("div", {hidden: true, class: "cmp-desc"});
    const titleId = uid("cmpt");
    const sheet = h("section", {class: "cmp-sheet", role: "dialog", "aria-modal": "false", "aria-labelledby": titleId});
    sheet.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); } });
    const closeBtn = h("button", {type: "button", class: "u-btn cmp-close", "data-key": "cmp-close", text: V.closeLabel});
    closeBtn.addEventListener("click", close);
    sheet.appendChild(h("header", {class: "cmp-head"},
      h("h2", {class: "u-section-title cmp-title", id: titleId, tabindex: "-1", "data-key": "cmp-title", text: V.title}),
      V.mixedText ? h("p", {class: "cmp-mixed", text: V.mixedText}) : null,
      h("span", {class: "cmp-spacer"}), closeBtn));
    const body = h("div", {class: "cmp-body", "data-scroll-key": "cmp-body"});
    sheet.appendChild(body);
    const table = h("table", {class: "cmp-table"});
    table.appendChild(h("caption", {class: "u-sr", text: `Compare ${V.columns.map((c) => c.ticker).join(", ")}. An up triangle marks the best value in a row.`}));
    const hr = h("tr", {}, h("th", {scope: "col", class: "cmp-lab"}, h("span", {class: "u-sr", text: "Measure"})));
    for (const c of V.columns) {
      const b = h("button", {type: "button", class: "cmp-tk", "data-key": `cmp-open-${c.ticker}`, "aria-label": `${c.ticker}, ${c.name}. Open its facts`},
        h("span", {class: "u-ticker", text: c.ticker}), h("span", {class: "cmp-name", text: c.name}));
      b.addEventListener("click", () => runChartAction({kind: "open", ticker: c.ticker}, ctx));
      const unpick = h("button", {type: "button", class: "u-btn icon cmp-unpick", "data-key": `cmp-unpick-${c.ticker}`,
        "aria-label": `Remove ${c.ticker} from Compare`, text: "✕"});
      unpick.addEventListener("click", () => togglePick(ctx, c.ticker));
      hr.appendChild(h("th", {scope: "col", class: `cmp-col${c.focal ? " is-focal" : ""}`}, b, unpick));
    }
    table.appendChild(h("thead", {}, hr));
    for (const g of V.groups) {
      const tb = h("tbody", {class: `cmp-group cmp-g-${g.id}${g.open ? " is-open" : ""}`});
      g.rows.forEach((row, i) => {
        if (i > 0 && !g.open) return;
        const head = i === 0;
        const lab = h("th", {scope: "row", class: `cmp-lab${head ? " cmp-glab" : " cmp-mlab"}`});
        if (head && g.toggle) {
          const t = h("button", {type: "button", class: "cmp-toggle", "data-key": `cmp-g-${g.id}`, "aria-expanded": String(!!g.open),
            text: `${g.open ? "▾" : "▸"} ${g.label}`});
          t.addEventListener("click", () => dispatch(ctx, {type: "TOGGLE_COMPARE_ROW", pillar: g.id}));
          lab.appendChild(t);
        } else lab.appendChild(h("span", {text: head ? g.label : row.label}));
        const tr = h("tr", {class: `cmp-row cmp-k-${row.kind}`}, lab);
        for (const c of row.cells) tr.appendChild(cellEl(row, c, descHost));
        tb.appendChild(tr);
      });
      table.appendChild(tb);
    }
    body.appendChild(table);
    sheet.appendChild(descHost);
    root.appendChild(sheet);
  }

  function cellEl(row, c, descHost) {
    const shaded = row.kind === "pillar" && c.fill;
    const td = h("td", {class: `cmp-cell${c.best ? " is-best" : ""}${shaded ? ` cmp-shade ${c.fill}` : ""}${c.outside ? " is-outside" : ""}`});
    if (shaded) setVars(td, cellStyle(c));
    if (row.kind === "lines") {
      if (c.lines && c.lines.length) {
        const ul = h("ul", {class: "cmp-lines"});
        c.lines.forEach((l, i) => {
          const li = h("li", {text: l});
          if (c.sources && c.sources[i]) li.setAttribute("title", c.sources[i]);
          ul.appendChild(li);
        });
        td.appendChild(ul);
      } else td.appendChild(h("span", {class: "u-meta", text: c.text || "None"}));
      return td;
    }
    if (row.kind === "company") {
      if (c.chip) td.appendChild(chip(c.chip, "neutral", {class: "cmp-chip"}));
      if (c.extra) td.appendChild(h("span", {class: "u-meta cmp-sub", text: c.extra}));
      return td;
    }
    const main = h("span", {class: `cmp-v${row.kind === "text" ? " is-text" : " u-num"}`},
      c.best ? h("span", {class: "cmp-best", "aria-hidden": "true", text: `${UP} `}) : null, c.text,
      c.best ? h("span", {class: "u-sr", text: " (best)"}) : null);
    td.appendChild(main);
    if (c.sub) td.appendChild(h("span", {class: "u-meta cmp-sub", text: c.sub}));
    if (c.reason) {
      td.setAttribute("tabindex", "0");
      bindTip(ctx, td, c.reason, descHost);
      if (c.outside) td.appendChild(h("span", {class: "u-meta cmp-sub", text: c.reason}));
    }
    return td;
  }

  return {
    update(v) { view = v; render(); },
    destroy() { destroyed = true; root.textContent = ""; root.classList.remove("cmp-root"); },
  };
}
