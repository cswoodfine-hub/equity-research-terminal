"""House style and word budgets over every string the scorecard prints (company-scorecard.md
8 and 7.2, E5).

House style: sentence case for labels, no em dash, none of the words additionally,
highlight, underscore, pivotal, showcase, testament. The rules are core.js ``lintCopy``'s,
run twice: a Python port of the dash and word rules on everything, and ``lintCopy`` itself
in node (when node is installed) so a label's sentence case is judged by the frame's own
allow list.

Three sets of strings:

- the fixed copy of section 8: the reason texts, the how-to-read line, the method lines and
  the deal chip of ``company_score``, the frame's ``SCORECARD_COPY``, the Key insights and
  Drivers and risks constants, each held to the text section 8 prints;
- every generated sentence and line, for all 70 companies: the sample scorecard always, and
  the live ``GET /comps/valuation`` answer when the API is up (ER_API_BASE, default
  localhost:8000);
- the word budgets of 8.7 that can be measured without a browser: the one sentence (30
  words, 2.13), Key insights' prose (sentence and lines, 75), the Comps prose (the
  how-to-read line, 34), and every Risks row (under 15). The first-screen totals are
  measured in the screenshot pass.
"""

from __future__ import annotations

import ast
import datetime as dt
import html
import json
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
SPEC = ROOT / "docs" / "design" / "company-scorecard.md"
SAMPLE = pathlib.Path(__file__).resolve().parent / "fixtures" / "company_score" / \
    "sample_scorecard.json"

for _p in (str(FRONTEND), str(BACKEND)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import calendar_view  # noqa: E402
import company_score as CS  # noqa: E402
import drivers as D  # noqa: E402

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
EM_DASH = "—"
NULL_GLYPH = "—"          # core.js prints a bare em dash for a null table cell; never prose
PLACEHOLDER = re.compile(r"\{[A-Za-z_ ]*\}")
NODE = shutil.which("node")
BUDGET_TICKERS = ("AZN", "LLY", "PFE", "VRTX", "CRSP")

# 8.7, the measurable parts.
SENTENCE_MAX_WORDS = 30
KI_PROSE_MAX_WORDS = 75
# 3.3 and 8.7 hold the how-to-read line to 36 words, the count of the line 8.1 prints
# verbatim (revision 2 said 34, a miscount, corrected). A longer line fails.
COMPS_PROSE_MAX_WORDS = 36
RISK_ROW_MAX_WORDS = 14            # "under 15 words"
KI_LINES_SHOWN = 3


def words(text: str) -> int:
    """Words as 8.7 counts them: a figure is one word, a lone glyph ("·", "+") none."""
    return len([w for w in str(text or "").split() if re.search(r"[A-Za-z0-9]", w)])


def lint(text: str) -> list:
    """The dash and word rules of core.js ``lintCopy``, in Python: an em dash anywhere but
    the bare null glyph, and each banned word on a word boundary, any case."""
    s = str(text or "")
    issues = []
    if s != NULL_GLYPH and EM_DASH in s:
        issues.append("em dash")
    for w in BANNED:
        if re.search(rf"(^|[^A-Za-z]){w}([^A-Za-z]|$)", s, re.I):
            issues.append(f"banned: {w}")
    return issues


def test_the_python_lint_matches_the_rules():
    assert lint("8.6% revenue growth in FY2025, 4th best of 17 big pharma") == []
    assert lint("a pivotal readout") == ["banned: pivotal"]
    assert lint("Highlights") == []                 # a word boundary, as lintCopy has it
    assert lint("weak — strong") == ["em dash"]
    assert lint(NULL_GLYPH) == []


# --- node: lintCopy and SCORECARD_COPY from core.js --------------------------------------------
NODE_SCRIPT = r"""
import fs from "node:fs";
const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const core = await import(job.core);
const out = {copy: core.SCORECARD_COPY, issues: job.lint.map(([s, kind, extra]) => core.lintCopy(s, kind, extra || []))};
process.stdout.write(JSON.stringify(out));
"""


def _node_lint(items: list, tmp: pathlib.Path) -> dict:
    script = tmp / "lint.mjs"
    script.write_text(NODE_SCRIPT)
    spec = tmp / "lint.json"
    spec.write_text(json.dumps({"core": CORE.resolve().as_uri(), "lint": items}))
    done = subprocess.run([NODE, str(script), str(spec)], capture_output=True, text=True,
                          timeout=110, cwd=str(tmp))
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


@pytest.fixture(scope="module")
def frame_copy(tmp_path_factory):
    if NODE is None:
        pytest.skip("node is not installed")
    return _node_lint([], tmp_path_factory.mktemp("copy"))["copy"]


# --- the Streamlit constants, read out of the script by name -----------------------------------
def _app_constants() -> dict:
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    out = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.startswith(("_KI_", "_DR_"))):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return out


@pytest.fixture(scope="module")
def app_copy():
    found = _app_constants()
    assert "_KI_SEPARATOR" in found and "_KI_NO_NEXT" in found
    return found


# --- the spec's own tables, read from the design document --------------------------------------
def _spec_section(number: str) -> str:
    text = SPEC.read_text()
    start = text.index(f"### {number} ")
    end = text.find("\n### ", start + 4)
    end2 = text.find("\n## ", start + 4)
    ends = [e for e in (end, end2) if e != -1]
    return text[start:min(ends) if ends else len(text)]


def _table(section: str) -> list:
    rows = []
    for line in section.splitlines():
        if line.startswith("|") and not re.match(r"^\|[-| ]+\|$", line):
            rows.append([c.strip() for c in line.strip().strip("|").split(" | ")])
    return rows[1:]                                  # the header row off


def _norm(s: str) -> str:
    """Placeholders as {}, whitespace as one space: the spec names a placeholder by what it
    holds ({cohort label}), the code by its key ({label})."""
    return re.sub(r"\s+", " ", PLACEHOLDER.sub("{}", s)).strip()


@pytest.fixture(scope="module")
def spec_reasons() -> dict:
    return {row[0].strip("`"): row[1] for row in _table(_spec_section("8.4"))
            if row and row[0].startswith("`")}


@pytest.fixture(scope="module")
def spec_labels() -> dict:
    return {row[0]: row[1] for row in _table(_spec_section("8.1")) if len(row) >= 2}


# --- the payloads ------------------------------------------------------------------------------
def _api() -> str:
    return os.getenv("ER_API_BASE", "http://localhost:8000")


def _api_up() -> bool:
    try:
        with urllib.request.urlopen(_api() + "/health", timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _sample() -> dict:
    return json.loads(SAMPLE.read_text())


def _live() -> dict:
    with urllib.request.urlopen(_api() + "/comps/valuation", timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    board = payload.get("scorecard")
    assert isinstance(board, dict) and not board.get("error"), (board or {}).get("error")
    return board


@pytest.fixture(scope="module", params=["sample", "live"])
def board(request):
    if request.param == "live":
        if not _api_up():
            pytest.skip("API not running")
        return _live()
    return _sample()


def _generated(board: dict) -> list:
    """(where, text) of every string the scorecard generates for its companies and cohorts:
    sentences, lines, reasons, facts, measure texts and periods, places, notes. Deal quotes
    are headlines verbatim (2.10) and are not house copy, so they are left out."""
    out = []
    for cid, c in (board.get("cohorts") or {}).items():
        for key in ("label", "noun", "context_text"):
            if c.get(key):
                out.append((f"{cid}.{key}", c[key]))
        for line in c.get("method_text") or []:
            out.append((f"{cid}.method_text", line))
        for x in (c.get("not_ranked") or []) + (c.get("not_on_chart") or []):
            out.append((f"{cid}.{x.get('ticker')}.reason", x.get("reason") or ""))
        for x in c.get("not_scored") or []:
            out.append((f"{cid}.not_scored", x.get("text") or ""))
    for t, rec in (board.get("companies") or {}).items():
        out.append((f"{t}.sentence", rec.get("sentence") or ""))
        if rec.get("reason_text"):
            out.append((f"{t}.reason_text", rec["reason_text"]))
        for side in ("positives", "negatives"):
            for x in rec.get(side) or []:
                out.append((f"{t}.{side}", x.get("text") or ""))
                out.append((f"{t}.{side}.source", x.get("source") or ""))
        for pid, p in (rec.get("pillars") or {}).items():
            for key in ("reason_text", "note"):
                if p.get(key):
                    out.append((f"{t}.{pid}.{key}", p[key]))
            for m in p.get("metrics") or []:
                for key in ("text", "period", "place", "reason_text"):
                    if m.get(key):
                        out.append((f"{t}.{pid}.{m.get('id')}.{key}", str(m[key])))
        facts = rec.get("facts") or {}
        for key in ("loe_years_text", "product_coverage_text", "firepower_text"):
            if facts.get(key):
                out.append((f"{t}.facts.{key}", facts[key]))
        for key in ("lead_phase", "partner_on"):
            if isinstance(facts.get(key), dict) and facts[key].get("text"):
                out.append((f"{t}.facts.{key}", facts[key]["text"]))
        if isinstance(facts.get("multiple"), dict):
            out.append((f"{t}.facts.multiple.label", facts["multiple"].get("label") or ""))
        deals = facts.get("deals") or {}
        for key in ("count_text", "chip"):
            if deals.get(key):
                out.append((f"{t}.facts.deals.{key}", deals[key]))
        for x in rec.get("exclusivity_losses") or []:
            out.append((f"{t}.exclusivity.date_text", x.get("date_text") or ""))
    return out


# =============================================================================================
# 1. The fixed copy of section 8.
# =============================================================================================
def test_every_reason_text_is_the_one_section_8_4_prints(spec_reasons):
    assert set(CS.REASONS) == set(spec_reasons), (
        sorted(set(CS.REASONS) ^ set(spec_reasons)))
    for code, text in CS.REASONS.items():
        assert text == spec_reasons[code], code


def test_every_reason_code_the_payload_emits_has_its_text(board, spec_reasons):
    """Company, pillar and measure reasons, and the cohorts' not-ranked codes, each map to a
    text of 8.4, and the payload carries that text in ``method.reasons``."""
    method = board["method"]["reasons"]
    for code, text in method.items():
        assert spec_reasons.get(code) == text, code
    emitted = set()
    for c in board["cohorts"].values():
        emitted |= {x.get("code") for x in c.get("not_ranked") or [] if x.get("code")}
    for rec in board["companies"].values():
        if rec.get("reason"):
            emitted.add(rec["reason"])
        for p in (rec.get("pillars") or {}).values():
            if p.get("reason"):
                emitted.add(p["reason"])
            for m in p.get("metrics") or []:
                if m.get("reason"):
                    emitted.add(m["reason"])
        for m in (rec.get("facts") or {}).get("other_metrics") or []:
            if m.get("reason"):
                emitted.add(m["reason"])
    missing = sorted(code for code in emitted if code not in spec_reasons or code not in method)
    assert not missing, missing
    assert len(emitted) >= 10, sorted(emitted)


def test_the_how_to_read_and_method_lines_are_section_8s(spec_labels, frame_copy):
    how = spec_labels["How to read it"]
    assert CS.HOW_TO_READ == how
    assert frame_copy["howToRead"] == how
    spec = _spec_section("8.6")
    quoted = [m for m in re.findall(r'"([^"]+)"', re.sub(r"\s*\n\s*", " ", spec))]
    assert [_norm(x) for x in CS.METHOD_LINES] == [_norm(x) for x in quoted]
    assert CS.DEAL_CHIP == spec_labels["Deal list chip"]


@pytest.mark.parametrize("where, key", [
    ("Fourth pick", "compareFull"),
    ("Mixed cohorts", "mixed"),
    ("Scorecard failed", "failed"),
    ("Weights", "weights"),
    ("Pillar row, partial", "partial"),
    ("Cell outside a cohort's list", "outside"),
    ("Table cell tooltip", "cellTitle"),
    ("Key insights bars separator", "priceRule"),
])
def test_the_frames_fixed_copy_is_section_8_1s(spec_labels, frame_copy, where, key):
    assert _norm(frame_copy[key]) == _norm(spec_labels[where])


def test_the_tab_constants_are_section_8_1s(spec_labels, app_copy):
    assert app_copy["_KI_SEPARATOR"] == spec_labels["Key insights bars separator"]
    assert app_copy["_KI_NO_NEXT"] == spec_labels["Next, empty"]
    assert app_copy["_KI_NO_CHANGES"] == spec_labels["What changed, empty"]
    assert _norm(D.EMPTY) == _norm(spec_labels["Drivers and risks, empty"])
    assert spec_labels["Catalysts section"] == (
        f'{D.SECTION_TITLE} (basis "{D.SECTION_BASIS}")')
    assert spec_labels["Catalysts lists"].startswith(f"{D.DRIVERS_TITLE} (")
    assert spec_labels["Catalysts lists"].endswith(f" · {D.RISKS_TITLE}")
    assert D.more_label(20) == "Show 20 more" and spec_labels["Drivers more"] == "Show {n} more"
    assert spec_labels["Risks more"] == "Show {n} more"
    assert spec_labels["Calendar expander"] == "Calendar, 24 months · {n} dated events"
    assert calendar_view.expander_label([], 24, dt.date(2026, 10, 1)).startswith(
        "Calendar, 24 months · ")


def _fixed_strings(frame_copy, app_copy) -> list:
    """(where, text, kind) of every fixed string: labels are held to sentence case too."""
    out = [(f"REASONS.{k}", v, "sentence") for k, v in CS.REASONS.items()]
    out += [("HOW_TO_READ", CS.HOW_TO_READ, "sentence"), ("DEAL_CHIP", CS.DEAL_CHIP, "sentence")]
    out += [(f"METHOD_LINES[{i}]", v, "sentence") for i, v in enumerate(CS.METHOD_LINES)]
    out += [(f"PILLARS.{k}", v["label"], "label") for k, v in CS.PILLARS.items()]
    out += [(f"METRICS.{k}", v["label"], "label") for k, v in CS.METRICS.items()]
    out += [(f"METRICS.{k}.short", v["short"], "label") for k, v in CS.METRICS.items()
            if v.get("short")]
    out += [(f"COHORTS.{k}", v["label"], "label") for k, v in CS.COHORTS.items()]
    out += [(f"COHORTS.{k}.noun", v["noun"], "sentence") for k, v in CS.COHORTS.items()]
    for k, v in (frame_copy or {}).items():
        if isinstance(v, str):
            out.append((f"SCORECARD_COPY.{k}", v,
                        "label" if k in ("compareTitle", "close", "howToReadShort",
                                         "methodLink", "priceRule") else "sentence"))
        elif isinstance(v, dict):
            out += [(f"SCORECARD_COPY.{k}.{k2}", v2, "label") for k2, v2 in v.items()
                    if isinstance(v2, str)]
    for k, v in app_copy.items():
        if isinstance(v, str) and k.startswith("_KI_") and not v.startswith("<"):
            out.append((k, v, "sentence"))
    out += [("D.SECTION_TITLE", D.SECTION_TITLE, "label"), ("D.SECTION_BASIS", D.SECTION_BASIS,
                                                          "sentence"),
            ("D.DRIVERS_TITLE", D.DRIVERS_TITLE, "label"), ("D.RISKS_TITLE", D.RISKS_TITLE,
                                                           "label"),
            ("D.EMPTY", D.EMPTY, "sentence"), ("D.CONTEXT_FAILED", D.CONTEXT_FAILED, "sentence"),
            ("calendar_view.SOURCES", calendar_view.SOURCES, "sentence")]
    for label in ("Company score", "Positives and negatives", "Next", "What changed",
                  "Morning note", "last close", "model", "multiple", "next exclusivity loss"):
        out.append((f"Key insights.{label}", label, "label"))
    return out


def test_the_fixed_copy_keeps_the_house_style(app_copy, tmp_path):
    copy = _node_lint([], tmp_path)["copy"] if NODE else {}
    fixed = _fixed_strings(copy, app_copy)
    bad = [(where, text, lint(text)) for where, text, _kind in fixed if lint(text)]
    assert not bad, bad
    # Labels: the first word may open on a capital, no later word may, bar the frame's own
    # allow list (EPS, P/E, XLV, CAGR, FY1 ...). Judged by lintCopy itself.
    if NODE is None:
        pytest.skip("node is not installed: the sentence-case half needs core.js")
    items = [[PLACEHOLDER.sub("X", text), kind, []] for _where, text, kind in fixed]
    issues = _node_lint(items, tmp_path)["issues"]
    bad = [(where, text, i) for (where, text, _k), i in zip(fixed, issues) if i]
    assert not bad, bad


# =============================================================================================
# 2. Every generated sentence and line, for every company.
# =============================================================================================
def test_every_generated_string_keeps_the_house_style(board, tmp_path):
    made = _generated(board)
    assert len(made) > 500, len(made)
    bad = [(where, text, lint(text)) for where, text in made if lint(text)]
    assert not bad, bad[:20]
    if NODE is not None:
        issues = _node_lint([[text, "sentence", []] for _w, text in made], tmp_path)["issues"]
        bad = [(where, text, i) for (where, text), i in zip(made, issues) if i]
        assert not bad, bad[:20]


def test_no_generated_string_leaves_a_placeholder_unfilled(board):
    """A reason text with a figure of the company's own ("covers {c}% of revenue") is filled
    where it is emitted, at the measure and at the pillar it empties."""
    bad = [(where, text) for where, text in _generated(board) if PLACEHOLDER.search(text)]
    assert not bad, bad


def test_every_company_has_its_sentence_in_the_template(board):
    """2.13: at most 30 words, the score, rank and range first, then the strongest and
    weakest pillars by name, or the one not-scored sentence."""
    names = {v["label"].lower() for v in board["method"]["pillars"].values()}
    pillar = "(?:" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + ")"
    tail = (rf"(?:Strongest on {pillar}(?: and {pillar})?(?:, weakest on {pillar}"
            rf"(?: and {pillar})?)?\.|Weakest on {pillar}(?: and {pillar})?\."
            r"|No pillar above 60 or below 40\.)")
    assert len(board["companies"]) == 70
    for t, rec in board["companies"].items():
        s = rec["sentence"]
        assert words(s) <= SENTENCE_MAX_WORDS, (t, s)
        noun = board["cohorts"][rec["cohort"]]["noun"]
        if rec.get("score") is None:
            assert re.fullmatch(rf"{re.escape(t)} is not scored: \d+ of \d+ pillars have data, "
                                r"and a score needs \d+\.", s), s
            continue
        head = (rf"{re.escape(t)} scores {rec['score']}, {CS.ordinal(rec['rank'])} of "
                rf"{rec['ranked_of']} {re.escape(noun)}, range {re.escape(rec['range_text'])}\. ")
        assert re.fullmatch(head + tail, s), (t, s)


def test_every_line_leads_with_its_number_and_names_its_place(board):
    """2.12: number first ("Net debt of" and "Net cash of" read on their side of zero), and
    either the place in the cohort or one of the three absolute tests."""
    absolute = (", under two years", ", over half", ", above 3×")
    for t, rec in board["companies"].items():
        noun = board["cohorts"][rec["cohort"]]["noun"]
        place = re.compile(rf", (?:joint )?(?:best|worst|\d+(?:st|nd|rd|th) (?:best|worst)) "
                           rf"of \d+ {re.escape(noun)}$")
        for side in ("positives", "negatives"):
            for x in rec.get(side) or []:
                text = x["text"]
                assert re.match(r"[0-9+−$]|Net (?:debt|cash) of ", text), (t, text)
                assert place.search(text) or text.endswith(absolute), (t, text)
                assert x.get("source"), (t, text)


# =============================================================================================
# 3. The word budgets of 8.7 that can be measured here.
# =============================================================================================
def _ki_pick():
    """Key insights' own choice of lines, ``_ki_lines_pick``, lifted out of the script with
    the constants and the word count it reads."""
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    keep = [node for node in tree.body
            if (isinstance(node, ast.FunctionDef)
                and node.name in ("_ki_words", "_ki_lines_pick"))
            or (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ("_KI_LINES_SHOWN", "_KI_PROSE_WORDS"))]
    space = {"re": re}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(APP), "exec"), space)
    assert space["_KI_PROSE_WORDS"] == KI_PROSE_MAX_WORDS
    assert space["_KI_LINES_SHOWN"] == KI_LINES_SHOWN
    return space["_ki_lines_pick"]


@pytest.mark.parametrize("ticker", BUDGET_TICKERS)
def test_key_insights_prose_is_within_its_budget(board, ticker):
    """8.7: Key insights' prose, the sentence and the lines it shows, is at most 75 words.
    Key insights shows up to three positives and three negatives, fewer past the budget."""
    rec = board["companies"][ticker]
    pos, neg = _ki_pick()(rec)
    shown = pos + neg
    prose = words(rec["sentence"]) + sum(words(x["text"]) for x in shown)
    assert prose <= KI_PROSE_MAX_WORDS, (ticker, prose, [rec["sentence"]] + [
        x["text"] for x in shown])
    assert len(shown) >= min(2, len(rec["positives"][:3] + rec["negatives"][:3]))


def test_the_comps_prose_is_within_its_budget(board, frame_copy, spec_labels):
    """8.7: the Comps view's prose is the how-to-read line, 36 words."""
    assert words(spec_labels["How to read it"]) == COMPS_PROSE_MAX_WORDS
    assert words(board["method"]["text"]["how_to_read"]) <= COMPS_PROSE_MAX_WORDS
    assert words(frame_copy["howToRead"]) <= COMPS_PROSE_MAX_WORDS


def test_every_exclusivity_risk_row_runs_under_15_words(board):
    """1.5: every Risks row is under 15 words and starts with a number, for every company's
    exclusivity losses as the payload carries them."""
    rows = 0
    for t, rec in board["companies"].items():
        for r in D.exclusivity_rows(rec, board["today"]):
            assert r["words"] <= RISK_ROW_MAX_WORDS, (t, r["line"])
            assert re.match(r"\d", r["lead"]), (t, r["line"])
            rows += 1
    assert rows >= 10, rows
