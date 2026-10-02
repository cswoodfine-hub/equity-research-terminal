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
    for needed in SHARED + ("_ki_columns", "_ki_figures", "_ki_track_items", "_ki_metric",
                            "_dr_list"):
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


DR_ROW = re.compile(
    r'<(a|div) class="dr-row" data-kind="([a-z]+)"[^>]*>'
    r'<span class="dr-lead( date)?">(.*?)(<span class="dr-m"[^>]*>M</span>)?</span>'
    r'<span class="dr-text">(.*?)</span></\1>', re.S)


def _dr_rows(markup: str) -> list:
    """(kind, lead, text) of every Drivers or Risks row, in the order drawn."""
    return [(m.group(2), _unesc(m.group(4)), _unesc(m.group(6))) for m in DR_ROW.finditer(markup)]


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
    own builders (the renderer only arranges their output): every measure in the cohort
    band, and the multiple in the call's last cell."""
    rec = sc["companies"][ticker]
    cols = view["_ki_columns"](sc, ticker, {}, {})
    measures = {r["id"]: (r["text"], r["place_text"]) for c in cols for r in c["rows"]
                if r.get("value") is not None}
    multiple = (rec.get("facts") or {}).get("multiple")
    cell = view["_ki_figures"]({}, {"source": None}, None, None, multiple, None)[3]
    return {"measures": measures, "multiple": cell[0], "multiple_key": cell[1]}


def _check_key_insights(ki: dict, sc: dict, ticker: str) -> None:
    """Every measure is the scorecard's own text and place; the multiple its own figure."""
    rec = sc["companies"][ticker]
    by_id = {m["id"]: m for p in (rec.get("pillars") or {}).values()
             for m in (p.get("metrics") or [])}
    for mid, (text, place) in ki["measures"].items():
        assert text == by_id[mid]["text"], mid
        assert place == f"{by_id[mid]['place']} of {by_id[mid]['n']}", mid
    multiple = (rec.get("facts") or {}).get("multiple")
    if multiple:
        assert ki["multiple"] == multiple["text"]
        assert ki["multiple_key"] == f"{multiple['label']} · median {multiple['median_text']}"
    else:
        assert ki["multiple"] == DOT


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
def test_key_insights_and_the_frame_print_the_same_numbers(view, frame, board, ticker):
    """Key insights' cohort band and the company panel print each measure as the same
    text, and the call's multiple is the panel's value measure against the same median."""
    rec = board["companies"][ticker]
    ki = _ki_from_builders(view, board, ticker)
    _check_key_insights(ki, board, ticker)
    v = frame[ticker]
    panel = {m["id"]: m for p in v["detail"]["pillars"] for m in (p.get("metrics") or [])}
    for mid, (text, _place) in ki["measures"].items():
        if mid in panel:
            assert panel[mid]["text"] == text, mid
    multiple = (rec.get("facts") or {}).get("multiple")
    if multiple:
        value = next(p for p in v["detail"]["pillars"] if p["id"] == "value")
        m = next(x for x in value["metrics"] if x["id"] == multiple["metric"])
        assert m["text"] == ki["multiple"]
        assert m["medianText"] == f"median {multiple['median_text']}"


def _dated(rows):
    return [r for r in rows if re.match(r"^\d{4}(-\d{2}){0,2}$", str(r.get("date") or ""))]


@pytest.mark.parametrize("ticker", ["AZN", "LLY", "CRSP"])
def test_the_track_leads_with_the_head_of_the_catalysts_list(view, board, ticker):
    """Key insights' track and the Catalysts list, drawn from the same saved context: the
    track labels the first four dated drivers, in the list's order."""
    ctx = json.loads((DRIVERS / f"ctx_{ticker}.json").read_text())
    feed = json.loads((DRIVERS / f"feed_{ticker}.json").read_text())
    part = D.section(ticker, ctx, board["companies"].get(ticker), feed, board["today"])
    events = D.rank_events(ctx)
    items, _ = view["_ki_track_items"](events, [], dt.date.fromisoformat(board["today"]))
    labelled = [it["label"] for it in items if it["kind"] != "minor"]
    assert labelled == [e["asset"] for e in _dated(events)][:4]
    shown = [r["asset"] for r in _dated(part["drivers"]["shown"])]
    assert labelled[:len(shown)] == shown[:len(labelled)]


def test_the_tracks_losses_are_the_risk_lists_exclusivity_rows(view, board):
    """For every company: the losses under the track and the exclusivity rows of Risks
    name the same products in the same order."""
    today = board["today"]
    checked = 0
    for ticker, rec in board["companies"].items():
        risks = D.risks(rec, None, [], today)
        items, _ = view["_ki_track_items"]([], risks, dt.date.fromisoformat(today))
        losses = [it["label"] for it in items if it["kind"] == "loss"]
        want = [f"{r['asset']} LOE" for r in risks if r["kind"] == "exclusivity"][:4]
        assert losses == want, ticker
        checked += bool(losses)
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
    # Key insights: every measure in its cohort band, as the scorecard prints it.
    body = "\n".join(page["ki"])
    view = _builders()
    for col in view["_ki_columns"](sc, ticker, {}, {}):
        for r in col["rows"]:
            if r.get("value") is not None:
                assert f"<b>{html.escape(r['text'], quote=False)}</b>" in body, r["id"]
    if rec.get("rank") is not None:
        assert f"of {rec['ranked_of']} · score {rec['score']}" in body


@live
def test_live_the_tracks_drivers_are_on_the_catalysts_list(page):
    body = "\n".join(page["ki"])
    track = next((m for m in page["ki"] if "ki-track" in m), "")
    drawn = [text.split(" · ")[0] for kind, lead, text in _dr_rows("".join(page["cat"]))
             if kind == "driver"]
    labels = re.findall(r'font-size="10"[^>]*font-weight="600"[^>]*>([^<]*)</text>', track)
    drivers_drawn = [html.unescape(x) for x in labels if not x.endswith(" LOE")
                     and not x.startswith("NCT")]
    for name in drivers_drawn:
        assert name.split(" → ")[0] in drawn, name
    if not drawn:
        assert "ki-track" not in body or not drivers_drawn


@live
def test_live_the_tracks_first_loss_is_the_first_exclusivity_risk(page):
    risks = [(lead, text) for kind, lead, text in _dr_rows("".join(page["cat"]))
             if kind == "exclusivity"]
    track = next((m for m in page["ki"] if "ki-track" in m), "")
    rec = page["sc"]["companies"][page["ticker"]]
    if not risks:
        assert " LOE<" not in track
        assert not rec.get("exclusivity_losses")
        return
    first = rec["exclusivity_losses"][0]
    assert f">{html.escape(first['asset'], quote=False)} LOE<" in track
