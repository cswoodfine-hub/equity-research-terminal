"""One scorecard, every surface (company-scorecard.md 0.2, 1.2 and 7.2, E5).

The scorecard is computed once, in Python, and four surfaces print it: Key insights (the
call's multiple and the table against the cohort), Comps > Companies (the ranked table and
the chart), the company panel and Compare (both drawn by the compsval frame from core.js).
The spec's promise is that they print the same characters, so these tests read each surface
and hold it to ``scorecard.companies[T]``:

- the frame's side runs core.js in node over a payload (``deriveView`` with the panel open,
  then with Compare open on three companies) and returns what it would draw;
- the Key insights and Catalysts side runs the tab's own string builders, read out of the
  Streamlit script by name, or, in the live layer, the whole page through AppTest;
- Readouts and decisions on Key insights names only the assets the Drivers list on
  Catalysts ranks, on dates their catalysts carry, soonest first, and leaves out none the
  Drivers list calls decisive; the scorecard's next exclusivity loss, the first exclusivity
  row of Risks, leads Loss of exclusivity with the same date and share;
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
    for needed in SHARED + ("_ki_cohort_table", "_ki_figures", "_ki_readouts", "_ki_expiries",
                            "_ki_metric", "_dr_list"):
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


# The cohort table on Key insights shortens a measure's unit to fit its column: "4.6 years"
# prints "4.6y" and "77 months" "77mo", where the panel and Compare print the scorecard's
# text whole. This is the one change it may make; the figure is the scorecard's to the
# character.
KI_UNITS = ((" years", "y"), (" year", "y"), (" months", "mo"))


def _ki_unit(text) -> str:
    out = str(text or "")
    for long, short in KI_UNITS:
        out = out.replace(long, short)
    return out


def _ki_from_builders(view: dict, sc: dict, ticker: str) -> dict:
    """What Key insights prints for ``ticker`` from the scorecard block, through the tab's
    own builders (the renderer only arranges their output): every measure with a value in
    the table against the cohort, and the multiple in the call's last cell."""
    rec = sc["companies"][ticker]
    groups = view["_ki_cohort_table"](sc, ticker, {}, {})
    measures = {r["id"]: (r["text"], r["place_text"]) for g in groups for r in g["rows"]
                if r.get("value") is not None}
    multiple = (rec.get("facts") or {}).get("multiple")
    # The market row is five cells (close, 24 hours, 1 year, street, multiple): the
    # multiple is the last.
    figures = view["_ki_figures"]({}, {"source": None}, None, None, multiple, None)
    assert len(figures) == 5, [f[1] for f in figures]
    cell = figures[4]
    return {"measures": measures, "multiple": cell[0], "multiple_key": cell[1]}


def _check_key_insights(ki: dict, sc: dict, ticker: str) -> None:
    """Every measure is the scorecard's own text (its unit shortened) and place; the
    multiple its own figure. A measure the cohort reports without scoring (``other_metrics``)
    has no place, and prints none."""
    rec = sc["companies"][ticker]
    by_id = {m["id"]: m for p in (rec.get("pillars") or {}).values()
             for m in (p.get("metrics") or [])}
    for m in (rec.get("facts") or {}).get("other_metrics") or []:
        by_id.setdefault(m["id"], m)
    assert ki["measures"], f"{ticker}: no measure in the table against the cohort"
    for mid, (text, place) in ki["measures"].items():
        assert text == _ki_unit(by_id[mid]["text"]), (mid, text, by_id[mid]["text"])
        want = (f"{by_id[mid]['place']} of {by_id[mid]['n']}"
                if by_id[mid].get("place") and by_id[mid].get("n") else "")
        assert place == want, mid
    multiple = (rec.get("facts") or {}).get("multiple")
    if multiple:
        assert ki["multiple"] == multiple["text"]
        assert ki["multiple_key"] == f"{multiple['label']} · median {multiple['median_text']}"
    else:
        assert ki["multiple"] == DOT
        assert ki["multiple_key"] == "multiple · none on file"


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
    """Key insights' table against the cohort and the company panel print each measure as
    the same figure in the same place, and the call's multiple is the panel's value measure
    against the same median."""
    rec = board["companies"][ticker]
    ki = _ki_from_builders(view, board, ticker)
    _check_key_insights(ki, board, ticker)
    v = frame[ticker]
    panel = {m["id"]: m for p in v["detail"]["pillars"] for m in (p.get("metrics") or [])}
    compared = 0
    for mid, (text, place) in ki["measures"].items():
        if mid in panel:
            assert _ki_unit(panel[mid]["text"]) == text, mid
            if panel[mid].get("placeText"):
                assert panel[mid]["placeText"] == place, mid
            compared += 1
    assert compared >= 3, (ticker, compared)
    multiple = (rec.get("facts") or {}).get("multiple")
    if multiple:
        value = next(p for p in v["detail"]["pillars"] if p["id"] == "value")
        m = next(x for x in value["metrics"] if x["id"] == multiple["metric"])
        assert m["text"] == ki["multiple"]
        assert m["medianText"] == f"median {multiple['median_text']}"


def _decides(it: dict) -> bool:
    """A catalyst the Drivers list's own rules call decisive, so Readouts and decisions must
    carry it: a regulatory date or a late-stage readout (tiers 1 to 3), or any event of an
    unapproved asset worth DRIVER_MIN_PCT of the price or more. The list may carry more (a
    Phase 2 readout of a compound the model does not value); this is its floor."""
    asset = it.get("asset") if isinstance(it.get("asset"), dict) else {}
    value = it.get("asset_value") if isinstance(it.get("asset_value"), dict) else {}
    pct = value.get("pct_of_price")
    return (D._is_regulatory(it) or D._is_late_readout(it)
            or (bool(asset) and not asset.get("is_marketed") and pct is not None
                and pct >= D.DRIVER_MIN_PCT))


def _readouts(view: dict, items: list, today: dt.date, shown: int = None) -> dict:
    """Readouts and decisions as the renderer calls it, without the registry's programmes:
    every row is then a catalyst of the context."""
    kw = {"shown": shown} if shown is not None else {}
    return view["_ki_readouts"](items, today, prose=D.indication_prose,
                                min_pct=D.DRIVER_MIN_PCT, **kw)


def _ahead(iso: str, today: str) -> bool:
    """A catalyst date is still ahead: a month-only date ("2026-11", as ClinicalTrials.gov
    gives it) by its month, a day by its day."""
    iso = str(iso or "")[:10]
    return iso[:7] >= today[:7] if len(iso) < 10 else iso >= today


def _sources(items: list, row: dict) -> list:
    """The catalysts a readout row can come from: the same date, event and indication, of
    the asset it names or, for an event with no asset, of a title that starts with it."""
    out = []
    for it in items:
        asset = it.get("asset") if isinstance(it.get("asset"), dict) else {}
        name = D.product_name(asset.get("name"))
        title = re.sub(r"^Phase [0-9/]+,\s*", "", str(it.get("title") or ""))
        if not (name == row["asset"] if name else
                title.startswith(row["asset"]) or D.product_name(title).startswith(row["asset"])):
            continue
        ind = (it.get("indication") or {}).get("name")
        # One row a compound a month joins its trials' indications, so a catalyst is a
        # source of the row when its indication is one of them, in the same month.
        said = [x.strip() for x in str(row["indication"] or "").split(", ") if x.strip()]
        if (str(it.get("date") or "")[:7] == row["date"][:7]
                and D.event_text(it) == row["event"]
                and ((D.indication_prose(ind) in said) if ind else True)):
            out.append(it)
    return out


@pytest.mark.parametrize("ticker", ["AZN", "LLY", "CRSP"])
def test_the_readouts_are_the_catalysts_lists_events_soonest_first(view, board, ticker):
    """Readouts and decisions and the Catalysts list, drawn from the same saved context:
    every readout names an asset the Drivers list ranks, on a date, event and indication
    one of that asset's catalysts carries, still ahead, its date no more precise than the
    catalyst's and marked estimated unless the company stated or confirmed it; no asset
    the Drivers list's own rules call decisive (a regulatory date, a late-stage readout or
    a valued unapproved event) is left out; soonest first, the first five shown."""
    ctx = json.loads((DRIVERS / f"ctx_{ticker}.json").read_text())
    feed = json.loads((DRIVERS / f"feed_{ticker}.json").read_text())
    today = dt.date.fromisoformat(board["today"])
    part = D.section(ticker, ctx, board["companies"].get(ticker), feed, board["today"])
    ranked = {r["asset"] for r in part["drivers"]["rows"]}
    items = [it for it in ctx["catalysts"]["items"] if isinstance(it, dict)]

    full = _readouts(view, items, today, shown=10 ** 6)["rows"]
    shown = _readouts(view, items, today)
    if not items:
        assert not full and not shown["rows"] and not shown["more"]
        assert "No late-stage readout" in view["_ki_readouts_html"](shown)
        return
    assert len(full) >= 5, (ticker, len(full))
    for r in full:
        assert r["asset"] in ranked or any(x.startswith(r["asset"]) for x in ranked), \
            (ticker, r["asset"])
        src = _sources(items, r)
        assert src, (ticker, r)
        assert _ahead(r["date"], board["today"]), (ticker, r)
        # The date: estimated unless stated or confirmed, and never finer than the
        # Catalysts row prints it (a registry estimate to its month, a quarter as Q1).
        est = {it.get("date_confidence") not in ("confirmed", "stated") for it in src}
        assert r["estimated"] in est, (ticker, r)
        assert r["date_text"] == (f"est. {r['when']}" if r["estimated"] else r["when"]), r
        allowed = {D.month_text(r["date"])} | {D.date_parts(it)[0].removeprefix("est. ")
                                               for it in src}
        assert r["when"] in allowed, (ticker, r["when"], allowed)
        if r["estimated"]:
            assert not re.match(r"^\d", r["when"]), (ticker, r)    # never an estimated day
    dates = [r["date"] for r in full]
    assert dates == sorted(dates), (ticker, dates)
    listed = {r["asset"] for r in full}
    # A regimen, placebo or standard of care is an arm, not a compound: the list leaves it.
    arm = view.get("_KI_NOT_A_COMPOUND")
    decisive = {D.product_name(it["asset"]["name"]) for it in items
                if it.get("asset") and _ahead(it.get("date"), board["today"])
                and _decides(it) and not (arm and arm.search(str(it["asset"]["name"])))}
    assert decisive <= listed, (ticker, sorted(decisive - listed))
    assert shown["rows"] == full[:5]
    assert shown["more"] == len(full) - 5
    assert shown["total"] == len(full)


@pytest.mark.parametrize("ticker", [
    "AZN",
    "LLY"])
def test_the_readouts_list_a_compound_once_a_month(view, board, ticker):
    """key-insights.md R4.2: two trials of one compound in the same month are one row of
    Readouts and decisions, whatever indication each names."""
    ctx = json.loads((DRIVERS / f"ctx_{ticker}.json").read_text())
    today = dt.date.fromisoformat(board["today"])
    items = [it for it in ctx["catalysts"]["items"] if isinstance(it, dict)]
    full = _readouts(view, items, today, shown=10 ** 6)["rows"]
    keys = [(r["asset"].lower(), r["date"][:7]) for r in full]
    twice = sorted({k for k in keys if keys.count(k) > 1})
    assert not twice, (ticker, twice)


def _loe_when(view: dict, iso: str, basis) -> str:
    """A loss date as Loss of exclusivity prints it, at its source's precision by the tab's
    own rule (``_ki_loe_text``, pinned in test_insights_tab_ui.py), after checking that the
    rule prints that very date: the day as Risks prints it, its month, or its year (a
    filer's year stands in a year's last day for the year)."""
    when = view["_ki_loe_text"](iso, basis, day=True)
    assert when in (D.day_text(iso), D.month_text(iso), iso[:4]), (iso, basis, when)
    return when


def _shift_year(iso: str, years: int) -> str:
    d = dt.date.fromisoformat(iso[:10])
    return d.replace(year=d.year + years, day=min(d.day, 28)).isoformat()


def test_the_scorecards_next_exclusivity_loss_is_a_patent_expiry(view, board):
    """For every company: the scorecard's next exclusivity loss, the first exclusivity row of
    Risks, leads Loss of exclusivity with the same date (at its source's precision) and
    share of revenue, and the rest follow in the Risks list's order. The scorecard's date
    wins over the exclusivity file's for its products, and an orphan term is never taken
    for a product's loss of exclusivity."""
    today = board["today"]
    day = dt.date.fromisoformat(today)
    checked = 0
    for ticker, rec in board["companies"].items():
        losses = rec.get("exclusivity_losses") or []
        risks = [r for r in D.exclusivity_rows(rec, today)
                 if "orphan" not in str(r.get("basis") or "").lower()]
        if not risks:
            continue
        # The exclusivity file a year off the scorecard for every product: the scorecard's
        # date still wins.
        held = [{"asset_id": x.get("asset_id"), "brand_name": x["asset"],
                 "loe": _shift_year(x["date"], 1), "loe_basis": "drug substance patent"}
                for x in losses]
        rows = view["_ki_expiries"](held, {}, {}, losses, day, False)["rows"]
        assert rows, ticker
        first = risks[0]
        assert rows[0]["asset"].lower() == first["asset"].lower(), (ticker, rows[0], first)
        assert rows[0]["date"] == first["date"], (ticker, rows[0], first["date"])
        assert rows[0]["when"] == _loe_when(view, first["date"], first.get("basis")), \
            (ticker, rows[0], first.get("basis"))
        assert rows[0]["share_text"] == first["share_text"], (ticker, rows[0])
        assert ([r["asset"].lower() for r in rows]
                == [r["asset"].lower() for r in risks][:len(rows)]), ticker
        checked += 1
    assert checked >= 10, "too few companies with an exclusivity loss to mean anything"

    # An orphan term guards one indication, not the molecule: the scorecard's row for it is
    # not a loss of exclusivity here, and the next real loss leads.
    loss = {"asset": "Orphanex", "asset_id": 1, "date": _shift_year(today, 1),
            "share_of_revenue": 0.2, "share_text": "20.0%", "fy": "FY2025",
            "basis": "orphan drug exclusivity"}
    real = {"asset": "Patentex", "asset_id": 2, "date": _shift_year(today, 2),
            "share_of_revenue": 0.1, "share_text": "10.0%", "fy": "FY2025",
            "basis": "drug substance patent"}
    held = [{"asset_id": x["asset_id"], "brand_name": x["asset"], "loe": x["date"],
             "loe_basis": x["basis"]} for x in (loss, real)]
    rows = view["_ki_expiries"](held, {}, {}, [loss, real], day, False)["rows"]
    assert [r["asset"] for r in rows] == ["Patentex"], rows
    assert rows[0]["kind"] == "patent" and rows[0]["share_text"] == "10.0%", rows[0]


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
    # Key insights: every measure of the table against the cohort, its figure the
    # scorecard's and its place beside it, and the rank in the table's chip.
    body = "\n".join(page["ki"])
    view = _builders()
    ki = _ki_from_builders(view, sc, ticker)
    _check_key_insights(ki, sc, ticker)
    for g in view["_ki_cohort_table"](sc, ticker, {}, {}):
        for r in g["rows"]:
            if r.get("value") is not None:
                cell = (f'<span class="v">{html.escape(r["text"], quote=False)}</span>'
                        f'<span class="p {r.get("tone") or ""}">'
                        f'{html.escape(r["place_text"], quote=False)}</span>')
                assert cell in body, (r["id"], cell)
    if rec.get("rank") is not None:
        assert (f"{CS.ordinal(rec['rank'])} of {rec['ranked_of']} · right is better"
                in body)


# Readouts and decisions and Loss of exclusivity, as the tab draws their rows. An expiry's
# middle cell is "kind · 5.6% of revenue", the share left out where none is on file.
KI_READOUT = re.compile(
    r'<div class="ki-ro" title="([^"]*)"><span class="d"><i>([●○])</i>([^<]*)</span>'
    r'<span class="n(?: pipeline)?">([^<]*)</span><span class="w">([^<]*)</span></div>')
KI_EXPIRY = re.compile(
    r'<div class="ki-ex" title="([^"]*)"><span class="d">([^<]*)</span>'
    r'<span class="n">([^<]*)</span><span class="w">([^<]*)</span>'
    r'<span class="v">([^<]*)</span></div>')
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _period(text: str) -> tuple:
    """(first day, last day) of a date as the lists print it: "8 Sep 2027", "Sep 2027",
    "Q1 2027", "H2 2027", or "2027" (the year a filer gave without a day)."""
    text = text.strip()
    m = re.fullmatch(r"(\d{1,2}) ([A-Z][a-z]{2}) (\d{4})", text)
    if m:
        d = dt.date(int(m.group(3)), MONTHS.index(m.group(2)) + 1, int(m.group(1)))
        return d, d
    m = re.fullmatch(r"([A-Z][a-z]{2}) (\d{4})", text)
    if m:
        y, mo = int(m.group(2)), MONTHS.index(m.group(1)) + 1
        return dt.date(y, mo, 1), dt.date(y + mo // 12, mo % 12 + 1, 1) - dt.timedelta(days=1)
    m = re.fullmatch(r"([QH])([1-4]) (\d{4})", text)
    if m:
        y, n = int(m.group(3)), int(m.group(2))
        months = 3 if m.group(1) == "Q" else 6
        first = (n - 1) * months + 1
        last = first + months - 1
        return (dt.date(y, first, 1),
                dt.date(y + last // 12, last % 12 + 1, 1) - dt.timedelta(days=1))
    assert re.fullmatch(r"\d{4}", text), text
    return dt.date(int(text), 1, 1), dt.date(int(text), 12, 31)


def _when(text: str) -> dt.date:
    """A day, a month (its first day) or a year (its last day: the year a filer gave
    stands in for its last day) as one date."""
    first, last = _period(text)
    return last if re.fullmatch(r"\d{4}", text.strip()) else first


def _soonest_first(texts: list) -> bool:
    """No date lies wholly before the one listed above it: a month, quarter or half may
    hold the day listed before it."""
    spans = [_period(t) for t in texts]
    return all(b[1] >= a[0] for a, b in zip(spans, spans[1:]))


def _share_part(middle: str) -> str:
    """The "5.6% of revenue" part of an expiry's middle cell, or ""."""
    return next((p for p in middle.split(" · ") if p.endswith(" of revenue")), "")


def _get(path: str) -> dict:
    with urllib.request.urlopen(_api() + path, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


@live
def test_live_the_readouts_name_catalyst_assets_soonest_first(page):
    """Every row of Readouts and decisions names an asset the Catalysts tab ranks or the
    context carries a catalyst for, except a row marked as the registry's estimate, which
    is a programme's next readout past the catalysts; at most five, soonest first."""
    ticker = page["ticker"]
    body = "\n".join(page["ki"])
    rows = [(html.unescape(tip), mark, html.unescape(when), html.unescape(name))
            for tip, mark, when, name, _what in KI_READOUT.findall(body)]
    drawn = {text.split(" · ")[0] for kind, _lead, text in _dr_rows("".join(page["cat"]))
             if kind == "driver"}
    items = [it for it in (_get(f"/companies/{ticker}/comps-context").get("catalysts")
                           or {}).get("items") or [] if isinstance(it, dict)]
    assets = {D.product_name((it.get("asset") or {}).get("name")) for it in items} - {""}
    titles = [re.sub(r"^Phase [0-9/]+,\s*", "", str(it.get("title") or "")) for it in items
              if not it.get("asset")]
    programmes = {D.product_name(p.get("name")) for p in
                  _get(f"/companies/{ticker}/programmes").get("programmes") or []}
    for tip, mark, when, name in rows:
        if tip.endswith("registry estimate"):
            assert mark == "○" and name in programmes, (ticker, name, tip)
        else:
            assert (name in drawn or name in assets
                    or any(t.startswith(name) for t in titles)), (ticker, name, sorted(drawn))
    assert len(rows) <= 5, (ticker, [r[3] for r in rows])
    assert _soonest_first([when for _tip, _mark, when, _name in rows]), \
        (ticker, [r[2] for r in rows])
    if not rows:
        assert "No late-stage readout or regulatory date is on file" in body


def _expiry_rows(page) -> list:
    """(product, date, date text, share text) of every Loss of exclusivity row on the page;
    the share text is "5.6% of revenue", or "" where none is on file."""
    return [(html.unescape(name), _when(html.unescape(when)), html.unescape(when),
             _share_part(html.unescape(middle)))
            for _tip, when, name, middle, _value in KI_EXPIRY.findall("\n".join(page["ki"]))]


@live
def test_live_the_first_exclusivity_risk_is_a_patent_expiry(page):
    """The scorecard's next exclusivity loss heads Risks on Catalysts and is a row of Loss
    of exclusivity, with the same share of revenue and the same date at its source's
    precision (the year, where the filer gave only a year), unless five sooner losses fill
    the list. An orphan term is never listed as a product's loss."""
    sc, ticker = page["sc"], page["ticker"]
    rec = sc["companies"][ticker]
    risks = [text for kind, _lead, text in _dr_rows("".join(page["cat"]))
             if kind == "exclusivity"]
    want = D.exclusivity_rows(rec, sc["today"])
    if not want:
        assert not risks, (ticker, risks)
        return
    first = want[0]
    assert risks and risks[0] == first["text"], (ticker, risks[:1], first["text"])
    rows = _expiry_rows(page)
    if "orphan" in str(first.get("basis") or "").lower():
        assert not any(r[0].lower() == first["asset"].lower() for r in rows), \
            (ticker, first["asset"])
        return
    hit = [r for r in rows if r[0].lower() == first["asset"].lower()]
    if not hit and len(rows) == 5 and rows[-1][1] <= dt.date.fromisoformat(first["date"]):
        return                                  # five sooner losses fill the list
    assert hit, (ticker, first["asset"], rows)
    assert hit[0][3] == f"{first['share_text']} of revenue", (ticker, hit[0])
    assert hit[0][2] == _loe_when(_builders(), first["date"], first.get("basis")), \
        (ticker, hit[0], first["date"], first.get("basis"))


@live
def test_live_patent_expiries_leave_out_no_earlier_scorecard_loss(page):
    """Loss of exclusivity runs soonest first, so every exclusivity loss the scorecard dates
    before the last row shown is one of its rows: the same product, or the same share of
    revenue in the same year where the exclusivity file names a sibling brand. An orphan
    term is not a product's loss, and is not looked for."""
    sc, ticker = page["sc"], page["ticker"]
    rows = _expiry_rows(page)
    dates = [r[1] for r in rows]
    assert dates == sorted(dates), (ticker, [r[2] for r in rows])
    if not rows:
        return
    missing = []
    for loss in D.exclusivity_rows(sc["companies"][ticker], sc["today"]):
        if dt.date.fromisoformat(loss["date"]) >= dates[-1]:
            continue
        if "orphan" in str(loss.get("basis") or "").lower():
            continue
        if not any(r[0].lower() == loss["asset"].lower()
                   or (r[3] == f"{loss['share_text']} of revenue"
                       and r[1].year == int(loss["date"][:4]))
                   for r in rows):
            missing.append(loss["line"])
    assert not missing, (ticker, missing, [(r[0], r[2], r[3]) for r in rows])
