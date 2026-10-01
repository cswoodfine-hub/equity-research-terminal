"""One scorecard, every surface (company-scorecard.md 0.2, 1.2 and 7.2, E5).

The scorecard is computed once, in Python, and four surfaces print it: Key insights (the
strip, the sentence, the bars, the lines), Comps > Companies (the ranked table and the
chart), the company panel and Compare (both drawn by the compsval frame from core.js). The
spec's promise is that they print the same characters, so these tests read each surface
and hold it to ``scorecard.companies[T]``:

- the frame's side runs core.js in node over a payload (``deriveView`` with the panel open,
  then with Compare open on three companies) and returns what it would draw;
- the Key insights and Catalysts side runs the tab's own string builders, read out of the
  Streamlit script by name, or, in the live layer, the whole page through AppTest;
- Next on Key insights is the head of the Drivers list on Catalysts, and the strip's next
  exclusivity loss is the first exclusivity row of Risks;
- the measures both core.js and ``company_score`` compute (P/E NTM, EV to sales on FY0,
  revenue growth) agree to 1e-9, and both leave free cash flow yield empty on negative free
  cash flow.

Two layers. The first runs on saved data (the sample scorecard, the frame's fixture payload,
the book fixture, the saved comps-context answers) and needs node only. The second drives the
app in-process against the API (ER_API_BASE, default localhost:8000) for AZN, LLY, PFE, VRTX
and CRSP, and is skipped when the API is not up, like the other tab tests.
"""

from __future__ import annotations

import ast
import datetime as dt
import html
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
APP = FRONTEND / "streamlit_app.py"
CORE = FRONTEND / "components" / "compsval" / "core.js"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "company_score" / "sample_scorecard.json"
BOOK = FIXTURES / "company_score" / "book_2026-10-01.json"
DRIVERS = FIXTURES / "drivers"
FRAME_PAYLOAD = FRONTEND / "tests" / "compsval" / "fixture_payload.json"

for _p in (str(FRONTEND), str(BACKEND)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import company_score as CS  # noqa: E402
import drivers as D  # noqa: E402

TICKERS = ("AZN", "LLY", "PFE", "VRTX", "CRSP")
# Compare opens on the company and the next two of the list, so the set crosses cohorts
# (PFE with VRTX and CRSP, CRSP with two big pharma) as well as staying inside one.
PICKS = {"AZN": ("LLY", "PFE"), "LLY": ("PFE", "VRTX"), "PFE": ("VRTX", "CRSP"),
         "VRTX": ("CRSP", "AZN"), "CRSP": ("AZN", "LLY")}
DOT = "·"
EN_DASH = "–"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

# The frame's side: core.js over a payload, as the frame would arrange it. Written to a
# temporary file per run; the job names the payload, the views and the records to compute.
NODE_SCRIPT = r"""
import fs from "node:fs";
const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const core = await import(job.core);
const out = {};
const read = (p) => JSON.parse(fs.readFileSync(p, "utf8"));
if (job.payload) {
  const p = read(job.payload);
  if (job.scorecard) p.scorecard = read(job.scorecard);
  out.views = {};
  for (const [focal, picks] of Object.entries(job.views || {})) {
    const run = (acts) => {
      let st = core.defaultState(p, {focal, engine: job.engine || ""}, null, null);
      for (const a of acts) st = core.reduce(st, a, p);
      return core.deriveView(p, st);
    };
    const d = run([{type: "OPEN_DETAIL", ticker: focal}]);
    const c = run(picks.map((t) => ({type: "TOGGLE_COMPARE", ticker: t})).concat([{type: "OPEN_COMPARE"}]));
    const S = d.scorecard, P = d.detail && d.detail.scorecard, C = c.compare;
    out.views[focal] = {
      errors: d.sectionErrors || {},
      compareState: c.scorecard ? {label: c.scorecard.compareLabel, enabled: c.scorecard.compareEnabled} : null,
      scorecard: S && {state: S.state, errorText: S.errorText, contextText: S.contextText, cohort: S.cohort,
        rows: (S.rows || []).map((r) => ({ticker: r.ticker, rank: r.rank, rangeText: r.rangeText, score: r.score,
          ranked: r.ranked, focal: r.focal, cells: (r.cells || []).map((x) => ({id: x.id, score: x.score, missing: x.missing, title: x.title}))}))},
      detail: P && {state: P.state, errorText: P.errorText || null, scoreLine: P.scoreLine, sentence: P.sentence,
        weightsText: P.weightsText, positives: (P.positives || []).map((x) => x.text), negatives: (P.negatives || []).map((x) => x.text),
        pillars: (P.business || []).concat(P.price || []).map((x) => ({id: x.id, score: x.score, median: x.median,
          metrics: (x.metrics || []).map((m) => ({id: m.id, text: m.text, period: m.period, placeText: m.placeText, medianText: m.medianText, line: m.line}))})),
        exclusivity: P.exclusivityRows || []},
      compare: C && {columns: C.columns.map((x) => x.ticker), mixed: C.mixed,
        groups: C.groups.map((g) => ({id: g.id, rows: g.rows.map((r) => ({id: r.id, kind: r.kind, metric: r.metric || null,
          cells: r.cells.map((x) => ({text: x.text ?? null, sub: x.sub ?? null, lines: x.lines || null, best: !!x.best}))}))}))},
    };
  }
}
if (job.records) {
  const cols = {pe_ntm: ["pe", "NTM"], ev_sales: ["ev_revenue", "FY0"], rev_growth: ["revenue_growth", "FY0"], fcf_yield: ["fcf_yield", "FY0"]};
  out.parity = {};
  for (const rec of read(job.records)) {
    const row = {};
    for (const [id, [col, basis]] of Object.entries(cols)) {
      const c = core.cell(rec, col, {basis});
      row[id] = {v: c.v, status: c.status};
    }
    out.parity[rec.ticker] = row;
  }
}
process.stdout.write(JSON.stringify(out));
"""


def _node(job: dict, tmp: pathlib.Path) -> dict:
    """Run the frame's side over ``job``; core.js is imported by its file URL."""
    script = tmp / "scorecard_frame.mjs"
    script.write_text(NODE_SCRIPT)
    spec = tmp / "scorecard_job.json"
    spec.write_text(json.dumps({"core": CORE.resolve().as_uri(), **job}))
    done = subprocess.run([NODE, str(script), str(spec)], capture_output=True, text=True,
                          timeout=110, cwd=str(tmp))
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


# --- the Streamlit tab builders, read out of the script by name -----------------------------
SHARED = ("html_escape", "change_row")


def _builders() -> dict:
    """The Key insights (``_ki_``) and Drivers and risks (``_dr_``) string builders. The
    script runs the whole app on import, so the pure functions are lifted out of its tree."""
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    keep, names = [], set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            name = node.name
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            name = node.targets[0].id
        else:
            continue
        if name.startswith(("_ki_", "_KI_", "_dr_", "_DR_")) or name in SHARED:
            keep.append(node)
            names.add(name)
    for needed in SHARED + ("_ki_strip_cells", "_ki_lines_html", "_ki_next_html",
                            "_ki_pillar_rows", "_dr_list"):
        assert needed in names, f"{needed} is not in streamlit_app.py"
    space = {"html": html, "re": re, "dt": dt}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(APP), "exec"), space)
    return space


@pytest.fixture(scope="module")
def view():
    return _builders()


@pytest.fixture(scope="module")
def board():
    return json.loads(SAMPLE.read_text())


@pytest.fixture(scope="module")
def frame(board, tmp_path_factory):
    """The frame's views for the five companies, on its fixture payload with the sample
    scorecard: the same block Key insights reads below."""
    if NODE is None:
        pytest.skip("node is not installed")
    tmp = tmp_path_factory.mktemp("frame")
    return _node({"payload": str(FRAME_PAYLOAD), "scorecard": str(SAMPLE),
                  "views": {t: list(PICKS[t]) for t in TICKERS}}, tmp)["views"]


# --- markup readers ----------------------------------------------------------------------------
def _unesc(s: str) -> str:
    return html.unescape(s)


def _strip_cells(markup: str) -> list:
    out = []
    for m in re.finditer(r'<span class="ki-cell"[^>]*>(.*?)</span></span>', markup):
        cell = m.group(1) + "</span>"
        k = re.search(r'<span class="k">(.*?)</span>', cell)
        v = re.search(r'<span class="v[^"]*">(.*?)</span>', cell)
        s = re.search(r'<span class="sub">(.*?)</span>', cell)
        out.append({"key": _unesc(k.group(1)), "value": _unesc(v.group(1)),
                    "sub": _unesc(s.group(1)), "title": _unesc(
                        (re.search(r'title="([^"]*)"', m.group(0)) or [None, ""])[1])})
    return out


def _lines(markup: str) -> list:
    """(glyph, text) of the positives and negatives block."""
    return [(_unesc(g), _unesc(t)) for g, t in re.findall(
        r'<span class="ki-g [a-z]+">([^<]*)</span><span class="ki-t">([^<]*)</span>', markup)]


def _next_rows(markup: str) -> list:
    """(lead, text) of the Next block."""
    return [(_unesc(a), _unesc(b)) for a, b in re.findall(
        r'<span class="ki-lead[^"]*">([^<]*)</span><span class="ki-t">([^<]*)</span>', markup)]


DR_ROW = re.compile(
    r'<(a|div) class="dr-row" data-kind="([a-z]+)"[^>]*>'
    r'<span class="dr-lead( date)?">(.*?)(<span class="dr-m"[^>]*>M</span>)?</span>'
    r'<span class="dr-text">(.*?)</span></\1>', re.S)


def _dr_rows(markup: str) -> list:
    """(kind, lead, text) of every Drivers or Risks row, in the order drawn."""
    return [(m.group(2), _unesc(m.group(4)), _unesc(m.group(6))) for m in DR_ROW.finditer(markup)]


def _bars(markup: str) -> dict:
    """pillar id -> the number its bar prints, from charts.pillar_bars."""
    out = {}
    for pid, body in re.findall(r'<g class="pb-row" data-pillar="([a-z_]+)">(.*?)</g>', markup,
                                re.S):
        num = re.search(r'class="pb-num">([^<]*)<', body)
        out[pid] = int(num.group(1)) if num else None
    return out


# --- what the payload says each surface prints -------------------------------------------------
def _range_text(rec: dict) -> str:
    lo, hi = rec["rank_range"]
    return str(lo) if lo == hi else f"{lo}{EN_DASH}{hi}"


def _range_words(rec: dict) -> str:
    lo, hi = rec["rank_range"]
    return CS.ordinal(lo) if lo == hi else f"{CS.ordinal(lo)} to {CS.ordinal(hi)}"


def _noun(sc: dict, rec: dict) -> str:
    return sc["cohorts"][rec["cohort"]]["noun"]


def _cohort_ids(sc: dict, rec: dict) -> list:
    return [p["id"] for p in sc["cohorts"][rec["cohort"]]["pillars"]]


def _check_frame(v: dict, sc: dict, focal: str, picks) -> None:
    """The frame's table, panel and Compare for ``focal`` against the scorecard block."""
    companies = sc["companies"]
    rec = companies[focal]
    cohort = sc["cohorts"][rec["cohort"]]
    assert v["errors"] == {}, v["errors"]

    # The ranked table: the cohort in rank order, then the companies not ranked.
    S = v["scorecard"]
    assert S["state"] == "ok", S["errorText"]
    assert S["cohort"]["n"] == cohort["n"]
    want_order = list(cohort["ranked"]) + [x["ticker"] for x in cohort.get("not_ranked") or []]
    assert [r["ticker"] for r in S["rows"]] == want_order
    for row in S["rows"]:
        r = companies[row["ticker"]]
        assert row["score"] == r["score"], row["ticker"]
        if row["ranked"]:
            assert row["rank"] == r["rank"], row["ticker"]
            assert row["rangeText"] == r["range_text"] == _range_text(r), row["ticker"]
        for c in row["cells"]:
            p = r["pillars"].get(c["id"]) or {}
            assert c["score"] == p.get("score"), (row["ticker"], c["id"])
            assert c["missing"] == (p.get("score") is None), (row["ticker"], c["id"])
            if p.get("score") is not None:
                assert c["title"].split(",")[0].endswith(f" {p['score']}"), c["title"]

    # The panel: the score line, the sentence, every line, every pillar and measure.
    P = v["detail"]
    assert P["state"] == "ok", P["errorText"]
    assert P["sentence"] == rec["sentence"]
    if rec["score"] is not None:
        assert P["scoreLine"] == (f"{rec['score']} · {CS.ordinal(rec['rank'])} of "
                                  f"{rec['ranked_of']} {_noun(sc, rec)} · {_range_words(rec)} "
                                  "in 90 of 100 weightings")
        lo, hi = rec["rank_range"]
        assert P["weightsText"] == (
            "Equal weights. Under 90 of 100 random weightings the rank stays between "
            f"{CS.ordinal(lo)} and {CS.ordinal(hi)}." if lo != hi else
            f"Equal weights. Under 90 of 100 random weightings the rank stays {CS.ordinal(lo)}.")
    assert P["positives"] == [x["text"] for x in rec["positives"]]
    assert P["negatives"] == [x["text"] for x in rec["negatives"]]
    assert [p["id"] for p in P["pillars"]] == [
        pid for pid in _cohort_ids(sc, rec) if pid not in ("value", "momentum")] + [
        pid for pid in ("value", "momentum") if pid in _cohort_ids(sc, rec)]
    for p in P["pillars"]:
        want = rec["pillars"][p["id"]]
        assert p["score"] == want["score"], p["id"]
        by_id = {m["id"]: m for m in want.get("metrics") or []}
        for m in p["metrics"]:
            w = by_id[m["id"]]
            assert m["text"] == (w["text"] if w.get("text") not in (None, "") else None), m
            if w.get("place") and w.get("n") is not None:
                assert m["placeText"] == f"{w['place']} of {w['n']}", m
    excl = rec.get("exclusivity_losses") or []
    assert [x["asset"] for x in P["exclusivity"]] == [x["asset"] for x in excl]
    for got, want in zip(P["exclusivity"], excl):
        assert got["text"] == f"{want['asset']} exclusivity ends {want['date_text']}"
        assert got["lead"] == f"{want['share_text']} of {want['fy']} revenue"

    # Compare: the company first, the score with its rank and range, the pillar scores,
    # every measure's value, the first three lines of each side.
    C = v["compare"]
    assert C is not None, "Compare did not open on three companies"
    assert C["columns"][0] == focal and sorted(C["columns"]) == sorted((focal,) + tuple(picks))
    groups = {g["id"]: g for g in C["groups"]}
    recs = [companies[t] for t in C["columns"]]
    score_row = groups["score"]["rows"][0]
    for cell, r in zip(score_row["cells"], recs):
        if r["score"] is None:
            assert cell["text"] == DOT
            continue
        assert cell["text"] == str(r["score"])
        assert cell["sub"] == (f"{CS.ordinal(r['rank'])} of {r['ranked_of']}, "
                               f"range {r['range_text']}")
    for gid, g in groups.items():
        if gid not in CS.PILLARS:
            continue
        pillar = g["rows"][0]
        assert pillar["kind"] == "pillar"
        for cell, r in zip(pillar["cells"], recs):
            p = r["pillars"].get(gid) if gid in _cohort_ids(sc, r) else None
            want = str(p["score"]) if p and p.get("score") is not None else DOT
            assert cell["text"] == want, (gid, r["ticker"])
        for row in g["rows"][1:]:
            for cell, r in zip(row["cells"], recs):
                p = r["pillars"].get(gid) if gid in _cohort_ids(sc, r) else None
                m = next((x for x in (p or {}).get("metrics") or []
                          if x.get("id") == row["metric"]), None)
                if m is None:
                    continue                    # outside the cohort's list: its own text
                want = m["text"] if m.get("text") not in (None, "") else DOT
                assert cell["text"] == want, (row["id"], r["ticker"])
    for side in ("positives", "negatives"):
        for cell, r in zip(groups[side]["rows"][0]["cells"], recs):
            assert (cell["lines"] or []) == [x["text"] for x in r[side][:3]], (side, r["ticker"])


def _ki_from_builders(view: dict, sc: dict, ticker: str) -> dict:
    """What Key insights prints for ``ticker`` from the scorecard block, through the tab's
    own builders (the renderer only arranges their output)."""
    rec = sc["companies"][ticker]
    cohort = sc["cohorts"][rec["cohort"]]
    cells = _strip_cells(view["_ki_strip_html"](view["_ki_strip_cells"]("1.00", 0.0, {}, rec)))
    rows = view["_ki_pillar_rows"](rec, cohort, sc["method"])
    return {"cells": cells, "lines": _lines(view["_ki_lines_html"](rec)),
            "bars": {r["id"]: r["score"] for r in rows if "id" in r}}


def _check_key_insights(ki: dict, sc: dict, ticker: str, sentence_markup: str = None) -> None:
    rec = sc["companies"][ticker]
    if sentence_markup is not None:
        assert html.escape(rec["sentence"], quote=False) in sentence_markup
    # Up to three of each side, the head of each list, fewer where the sentence and the
    # lines would pass 8.7's 75 words (``_ki_lines_pick``).
    plus = [t for g, t in ki["lines"] if g == "+"]
    minus = [t for g, t in ki["lines"] if g == "−"]
    assert ki["lines"] == [("+", t) for t in plus] + [("−", t) for t in minus]
    assert plus == [x["text"] for x in rec["positives"][:len(plus)]] and len(plus) <= 3
    assert minus == [x["text"] for x in rec["negatives"][:len(minus)]] and len(minus) <= 3
    assert len(ki["lines"]) >= min(2, len(rec["positives"][:3] + rec["negatives"][:3]))
    for pid in _cohort_ids(sc, rec):
        assert ki["bars"].get(pid) == rec["pillars"][pid]["score"], pid
    cells = ki["cells"]
    assert [c["key"] for c in cells] == ["last close", "model", "multiple",
                                         "next exclusivity loss"]
    multiple = (rec.get("facts") or {}).get("multiple")
    if multiple:
        assert cells[2]["value"] == multiple["text"]
        assert cells[2]["sub"] == f"{multiple['label']}, median {multiple['median_text']}"
    else:
        assert (cells[2]["value"], cells[2]["sub"]) == (DOT, "no multiple on file")


def _sentence_numbers(sc: dict, ticker: str) -> None:
    """The sentence carries the score, rank and range the table and Compare print."""
    rec = sc["companies"][ticker]
    if rec["score"] is None:
        return
    assert rec["sentence"].startswith(
        f"{ticker} scores {rec['score']}, {CS.ordinal(rec['rank'])} of {rec['ranked_of']} "
        f"{_noun(sc, rec)}, range {rec['range_text']}.")


# =============================================================================================
# 1. On saved data: the sample scorecard, the frame's fixture payload, the saved contexts.
# =============================================================================================
@needs_node
@pytest.mark.parametrize("ticker", TICKERS)
def test_the_frame_table_panel_and_compare_print_the_scorecard(frame, board, ticker):
    _check_frame(frame[ticker], board, ticker, PICKS[ticker])
    _sentence_numbers(board, ticker)


@needs_node
@pytest.mark.parametrize("ticker", TICKERS)
def test_key_insights_and_the_frame_print_the_same_numbers_and_lines(view, frame, board,
                                                                     ticker):
    rec = board["companies"][ticker]
    ki = _ki_from_builders(view, board, ticker)
    _check_key_insights(ki, board, ticker)
    v = frame[ticker]
    # The lines: Key insights' are the head of the panel's lists (all of them there) and of
    # Compare's cells, up to three of each.
    plus = [t for g, t in ki["lines"] if g == "+"]
    minus = [t for g, t in ki["lines"] if g == "−"]
    assert plus == v["detail"]["positives"][:len(plus)]
    assert minus == v["detail"]["negatives"][:len(minus)]
    groups = {g["id"]: g for g in v["compare"]["groups"]}
    col = v["compare"]["columns"].index(ticker)
    assert groups["positives"]["rows"][0]["cells"][col]["lines"] == v["detail"]["positives"][:3]
    # The bars: the panel's pillar scores, the table's shaded cells and Compare's cells.
    panel = {p["id"]: p["score"] for p in v["detail"]["pillars"]}
    assert ki["bars"] == panel
    row = next(r for r in v["scorecard"]["rows"] if r["ticker"] == ticker)
    assert {c["id"]: c["score"] for c in row["cells"]} == {
        k: panel[k] for k in panel if k != "momentum"}
    for pid, score in panel.items():
        assert groups[pid]["rows"][0]["cells"][col]["text"] == (DOT if score is None
                                                                 else str(score))
    # The multiple: the strip's cell is the panel's value measure, against the same median.
    multiple = (rec.get("facts") or {}).get("multiple")
    if multiple:
        value = next(p for p in v["detail"]["pillars"] if p["id"] == "value")
        m = next(x for x in value["metrics"] if x["id"] == multiple["metric"])
        assert m["text"] == ki["cells"][2]["value"]
        assert m["medianText"] == f"median {multiple['median_text']}"


@pytest.mark.parametrize("ticker", ["AZN", "LLY", "CRSP"])
def test_next_is_the_first_three_drivers(view, board, ticker):
    """Key insights' Next and the Catalysts list, drawn from the same saved context: the same
    leads, the same words, in the same order."""
    ctx = json.loads((DRIVERS / f"ctx_{ticker}.json").read_text())
    feed = json.loads((DRIVERS / f"feed_{ticker}.json").read_text())
    part = D.section(ticker, ctx, board["companies"].get(ticker), feed, board["today"])
    drawn = [(lead, text) for kind, lead, text in
             _dr_rows(view["_dr_list"](part["drivers"]["shown"], "driver"))]
    events = D.rank_events(ctx)
    nxt = _next_rows(view["_ki_next_html"](events[:view["_KI_NEXT_SHOWN"]]))
    assert nxt == drawn[:3]
    assert view["_KI_NEXT_SHOWN"] == 3
    if not events:
        assert nxt == [] and drawn == []
    else:
        assert view["_ki_next_basis"](len(events), D.drivers_basis(len(events))).endswith(
            part["drivers"]["basis"] + ", Catalysts has them all")


def test_the_strips_exclusivity_cell_is_the_first_exclusivity_risk(view, board):
    """For every company: the strip's next exclusivity loss and the first exclusivity row of
    Risks name the same product, month and share of revenue, or both say there is none."""
    today = board["today"]
    checked = 0
    for ticker, rec in board["companies"].items():
        cell = view["_ki_strip_cells"]("1.00", 0.0, {}, rec)[3]
        risks = [r for r in D.risks(rec, None, [], today) if r["kind"] == "exclusivity"]
        if not risks:
            assert cell[1:3] == (DOT, "none in 24 months"), ticker
            continue
        first = risks[0]
        assert cell[1] == D.month_text(first["date"]), ticker
        share = first["lead"].replace(" of revenue", "")
        assert cell[2].startswith(f"{share} of "), (ticker, cell[2], first["lead"])
        assert cell[2].endswith(", " + first["asset"]), (ticker, cell[2], first["asset"])
        # The row cuts a long name at a word to stay under 15 words (1.5): JNJ's
        # "Prezista / Prezcobix / Rezolsta / Symtuza" prints "Prezista / Prezcobix /
        # Rezolsta /…". The strip's sub is one clamped line and keeps it whole.
        name = first["text"].split(" exclusivity ends ")[0]
        assert name == first["asset"] or (
            name.endswith("…") and first["asset"].startswith(name[:-1])), (ticker, name)
        checked += 1
    assert checked >= 10, "too few companies with an exclusivity loss to mean anything"


@needs_node
def test_the_measures_both_sides_compute_agree(tmp_path):
    """P/E NTM, EV to sales on FY0 and revenue growth, computed by company_score and by
    core.js from the same record, agree to 1e-9 wherever both have a value; free cash flow
    yield is empty on negative free cash flow in both."""
    book = json.loads(BOOK.read_text())
    records = tmp_path / "records.json"
    records.write_text(json.dumps(book["records"]))
    js = _node({"records": str(records)}, tmp_path)["parity"]
    today = dt.date.fromisoformat(book["today"])
    compared = {"pe_ntm": 0, "ev_sales": 0, "rev_growth": 0}
    negative_fcf = 0
    for rec in book["records"]:
        t = rec["ticker"]
        py = CS.metric_values(rec, book["inputs"].get(t) or {}, today)
        for metric in compared:
            a, b = py[metric][0], js[t][metric]["v"]
            if a is None or b is None:
                continue
            assert math.isclose(a, b, rel_tol=0, abs_tol=1e-9), (t, metric, a, b)
            compared[metric] += 1
        fcf = ((rec.get("periods") or {}).get("FY0") or {}).get("fcf_usd_m")
        if isinstance(fcf, (int, float)) and fcf < 0:
            negative_fcf += 1
            assert py["fcf_yield"] == (None, "fcf_negative"), t
            assert js[t]["fcf_yield"]["v"] is None and js[t]["fcf_yield"]["status"] == "nm", t
    # Not vacuous: on the 2026-10-01 book 21 companies have P/E NTM on both sides, 27 EV
    # to sales and 35 revenue growth (the rest are clinical, flagged or under the floor).
    assert compared["pe_ntm"] >= 18 and compared["ev_sales"] >= 24, compared
    assert compared["rev_growth"] >= 30, compared
    assert negative_fcf >= 5, negative_fcf


# =============================================================================================
# 2. Live: the page itself, through AppTest, against the API.
# =============================================================================================
def _api() -> str:
    return os.getenv("ER_API_BASE", "http://localhost:8000")


def _api_up() -> bool:
    try:
        with urllib.request.urlopen(_api() + "/health", timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


live = pytest.mark.skipif(not _api_up(), reason="API not running")


def _patch_button_group_serialisation():
    """The AppTest defect the other tab tests work around: a single-select segmented
    control's value is a string, and ButtonGroup.indices iterates its characters."""
    from streamlit.testing.v1 import element_tree

    def indices(self):
        values = self.value
        if values is None:
            return []
        if not isinstance(values, (list, tuple)):
            values = [values]
        labels = [getattr(o, "content", o) for o in self.options]
        out = []
        for v in values:
            label = self.format_func(v) if self.format_func else v
            label = getattr(label, "content", label)
            if label in labels:
                out.append(labels.index(label))
        return out

    element_tree.ButtonGroup.indices = property(indices)


def _walk(block):
    for child in getattr(block, "children", {}).values():
        yield child
        yield from _walk(child)


def _tab(app, label: str):
    found = [t for t in app.tabs if t.label == label]
    assert found, f"no {label} tab"
    return found[0]


def _markdown(block) -> list:
    return [str(e.value) for e in _walk(block) if getattr(e, "type", "") == "markdown"]


def _full_args(app) -> dict:
    """The full compsval frame's args, parsed strictly: the payload the frame draws from."""
    def fail(constant):
        pytest.fail(f"non-JSON {constant} in the comps args")

    for node in app.get("component_instance"):
        if node.proto.component_name != "components.compsval.compsval":
            continue
        args = json.loads(node.proto.json_args, parse_constant=fail)
        if (args.get("mode") or "full") == "full":
            return args
    pytest.fail("no full compsval frame on the page")


@pytest.fixture(scope="module", params=TICKERS)
def page(request, tmp_path_factory):
    """One run of the whole page for a company, and the frame's views over the very payload
    the page handed the frame."""
    if not _api_up():
        pytest.skip("API not running")
    if NODE is None:
        pytest.skip("node is not installed")
    from streamlit.testing.v1 import AppTest

    _patch_button_group_serialisation()
    ticker = request.param
    app = AppTest.from_file(str(APP), default_timeout=300)
    app.query_params["ticker"] = ticker
    app.run()
    assert not app.exception, [str(e.value)[:400] for e in app.exception]
    args = _full_args(app)
    tmp = tmp_path_factory.mktemp(f"live_{ticker}")
    payload = tmp / "payload.json"
    payload.write_text(json.dumps(args["payload"]))
    frame_views = _node({"payload": str(payload), "engine": args.get("engine") or "",
                         "views": {ticker: list(PICKS[ticker])}}, tmp)["views"]
    return {"ticker": ticker, "args": args, "sc": args["payload"]["scorecard"],
            "frame": frame_views[ticker],
            "ki": _markdown(_tab(app, "Key insights")),
            "cat": _markdown(_tab(app, "Catalysts"))}


@live
def test_live_every_surface_prints_the_payloads_scorecard(page):
    sc, ticker = page["sc"], page["ticker"]
    assert not sc.get("error"), sc.get("error")
    rec = sc["companies"][ticker]
    _sentence_numbers(sc, ticker)
    # Comps: the frame's table, panel and Compare over the payload it was handed.
    _check_frame(page["frame"], sc, ticker, PICKS[ticker])
    # Comps: the chart's bubble for the company names the same rank, range and scores.
    if rec.get("chart"):
        lo, hi = rec["rank_range"]
        aria = (f"{ticker}, rank {rec['rank']}, range {lo} to {hi}, company score "
                f"{rec['score']}" + (f", value {rec['value']}" if rec.get("value") is not None
                                     else ""))
        assert f'aria-label="{aria}"' in page["args"]["chart_svg"], aria
    # Key insights: the strip, the sentence, the bars and the lines.
    body = "\n".join(page["ki"])
    strip = next(m for m in page["ki"] if "ki-strip" in m)
    bars = next(m for m in page["ki"] if 'class="pb-row"' in m)
    lines = next(m for m in page["ki"] if 'class="ki-lines"' in m or 'class="ki-empty"' in m
                 and "quarter of the cohort" in m)
    ki = {"cells": _strip_cells(strip), "lines": _lines(lines), "bars": _bars(bars)}
    _check_key_insights(ki, sc, ticker, sentence_markup=body)
    assert ki["bars"] == {p["id"]: p["score"] for p in page["frame"]["detail"]["pillars"]}


@live
def test_live_next_is_the_first_three_drivers_on_catalysts(page):
    nxt_block = next((m for m in page["ki"] if 'class="ki-next"' in m), "")
    nxt = _next_rows(nxt_block)
    drawn = [(lead, text) for kind, lead, text in _dr_rows("".join(page["cat"]))
             if kind == "driver"]
    assert len(nxt) == min(3, len(drawn))
    assert nxt == drawn[:3]
    if not drawn:
        assert "No event dated in the next 12 months." in "".join(page["ki"])


@live
def test_live_the_strips_exclusivity_cell_is_the_first_risk(page):
    strip = next(m for m in page["ki"] if "ki-strip" in m)
    cell = _strip_cells(strip)[3]
    risks = [(lead, text) for kind, lead, text in _dr_rows("".join(page["cat"]))
             if kind == "exclusivity"]
    rec = page["sc"]["companies"][page["ticker"]]
    if not risks:
        assert (cell["value"], cell["sub"]) == (DOT, "none in 24 months")
        assert not rec.get("exclusivity_losses")
        return
    lead, text = risks[0]
    first = rec["exclusivity_losses"][0]
    assert lead == f"{first['share_text']} of revenue"
    assert cell["sub"] == f"{first['share_text']} of {first['fy']} revenue, {first['asset']}"
    assert text.startswith(f"{first['asset']} exclusivity ends ")
    assert text.endswith(first["date_text"])
    assert cell["value"] == D.month_text(first["date"])
