"""The gates on the page: builds 1 to 3 drawn in one pass (docs/design/development-cost.md
section 10, comps-valuation.md section 12, the launch section of docs/pipeline_coverage.md).

The builders live in the Streamlit script, which runs the whole app on import, so they are
read out of its source by name and run on payloads the API served for real assets on a copy
of the book on 6 October 2026 (``fixtures/gates_ui``, trimmed to what the builders read):

- the Forecast tab's Next gate block (``_gate_*``): Eloralintide (a published gate with a
  held note and a PoS band), Retatrutide (stated PoS, implied odds), Cagrilintide (a gate
  study due since 2024, a DKK cost), Povetacicept (an FDA gate a stated PoS implies, an amber
  floor), Olpasiran (a red floor set by another study than the gate's), Clazakizumab (a cost
  the registry cannot read), a GSK vaccine (refused) and Mounjaro (marketed, no gate);
- the company view's next-gate table (AZN, two gates that cost more than they are worth);
- the Catalysts tab's At stake rows (``_stake_*``): LLY's ten derived stakes, VRTX's stated
  Casgevy row beside two derived ones;
- the Pipeline tab's value cell (``_prog_value_cell``) and the launch floor's flag it shares
  with Key insights (``_launch_*``).

Nothing here starts Streamlit or calls the API, bar the one AppTest check at the foot, which
runs only with ER_TOOL_APPTEST=1 against a running API.
"""

from __future__ import annotations

import ast
import copy
import html
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
APP = FRONTEND / "streamlit_app.py"
CSS = FRONTEND / "assets" / "research.css"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "gates_ui"

if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

import theme  # noqa: E402

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
EM_DASH = "—"
PREFIXES = ("_gate_", "_GATE_", "_stake_", "_STAKE_", "_prog_", "_launch_", "_LAUNCH_",
            "_dr_")
SHARED = ("html_escape", "_ki_month", "_ki_day", "_KI_MONTHS")


@pytest.fixture(scope="module")
def view():
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
        if name.startswith(PREFIXES) or name in SHARED:
            keep.append(node)
            names.add(name)
    assert {"_gate_summary", "_stake_row_html", "_prog_value_cell", "_launch_flagged"} <= names
    # The renderers draw with Streamlit; they are read here only to check what they call.
    space = {"html": html, "re": re, "T": theme}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(APP), "exec"), space)
    return space


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def text_of(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def house_style(text: str) -> None:
    assert EM_DASH not in text, text
    low = text.lower()
    assert not [w for w in BANNED if re.search(rf"\b{w}\b", low)], text


def summary(view, key: str, **kw):
    return view["_gate_summary"](load(f"{key}_verdict"), load(f"{key}_development"), **kw)


def rows_by_key(view, s) -> dict:
    return {r["k"]: r for r in view["_gate_rows"](s)}


# --- the launch floor's flag, one mark on three tabs --------------------------------------
def test_the_flag_is_red_before_the_floor_amber_where_the_seed_cites_and_nothing_else(view):
    flag = view["_launch_flag"]
    assert flag({"status": "before_floor", "flag": "red"}) == "red"
    assert flag({"status": "before_floor_cited", "flag": "amber"}) == "amber"
    assert flag({"status": "before_floor"}) == "red"            # read off the status alone
    for status in ("part_year", "clear", "decision_passed", "no_registry_basis", "no_clock",
                   "not_assessed"):
        assert flag({"status": status, "flag": None}) == "", status
    assert flag(None) == "" and flag("red") == ""


def test_a_flagged_figure_is_underlined_with_the_floors_message_as_its_tooltip(view):
    launch = load("AMGN_1631_verdict")["launch"]
    marked = view["_launch_flagged"]("4.00", launch)
    assert marked.startswith('<span class="u-flagged red" title="2027 in the model, but the '
                             'earliest approval is Nov 2028')
    assert marked.endswith(">4.00</span>")
    # A row with one tooltip for everything carries the mark and no title of its own.
    assert view["_launch_flagged"]("4.00", launch, tip=False) == \
        '<span class="u-flagged red">4.00</span>'
    clear = load("LLY_1514_verdict")["launch"]
    assert view["_launch_flagged"]("5.02", clear) == "5.02"
    quoted = view["_launch_flagged"]("1", {"flag": "amber", "message": 'a "quote" <b>'})
    assert 'title="a &quot;quote&quot; &lt;b&gt;"' in quoted


def test_the_css_draws_red_with_the_down_token_and_amber_with_the_flag_token():
    css = CSS.read_text()
    assert ".u-flagged.red { text-decoration-color: var(--down); }" in css
    assert ".u-flagged.amber { text-decoration-color: var(--flag); }" in css


# --- the Pipeline tab's value cell -----------------------------------------------------------
def test_the_pipeline_value_cell_carries_the_flag_and_nothing_for_a_part_year(view):
    cell = view["_prog_value_cell"]
    verdict = load("LLY_forecast-verdict")
    valued = {m["asset_id"]: m.get("per_share") for m in verdict["modelled"]}
    launch = {m["asset_id"]: m.get("launch") for m in verdict["modelled"]}
    red = cell(1499, valued, {}, {}, launch[1499])              # Lepodisiran
    assert '<span class="u-flagged red" title="2027 in the model' in red
    assert ">2.03</span></span>" in red
    assert cell(1514, valued, {}, {}, launch[1514]) == (       # Eloralintide, clear
        '<span class="prog-v" title="rNPV a share, counted in the company total">5.02</span>')
    amgn = load("AMGN_forecast-verdict")["modelled"]
    maritide = next(m for m in amgn if m["asset_id"] == 1623)
    assert maritide["launch"]["status"] == "part_year"
    assert "u-flagged" not in cell(1623, {1623: maritide["per_share"]}, {}, {},
                                   maritide["launch"])
    # The other three states are unchanged and never flagged.
    assert "held *" in cell(7, {}, {7: None}, {}, {"flag": "red"})
    assert ">needs</span>" in cell(8, {}, {}, {8: ["peak"]}, {"flag": "red"})
    assert "&mdash;" in cell(9, {}, {}, {}, {"flag": "red"})


# --- the Forecast tab: the Next gate block --------------------------------------------------
def test_the_next_gate_block_reads_the_gate_its_legs_its_cost_and_the_earliest_approval(view):
    s = summary(view, "LLY_1514")
    assert view["_gate_head"](s) == "Phase 3 readout · est. Jan 2028 · NCT07282600"
    rows = view["_gate_rows"](s)
    assert [r["k"] for r in rows] == ["chance", "if it passes", "if it fails", "held",
                                      "cost to reach", "net", "at DiMasi's level",
                                      "earliest approval"]
    got = {r["k"]: (text_of(r["v"]) if r.get("html") else r["v"], r["note"]) for r in rows}
    assert got["chance"] == ("61%", "published")
    assert got["if it passes"] == ("8.23", "a share, against 5.02 now")
    assert got["if it fails"] == ("nil", "the model's convention for a failed programme")
    assert got["held"] == ("55%", "4 other Phase 3s open")
    assert got["cost to reach"] == ("0.15", "138mm after tax, 2018 prices, not restated")
    assert got["net"] == ("4.87", "breaks even at a 1.9% chance")
    assert got["at DiMasi's level"] == ("0.44", "net 4.59, a high bound")
    assert got["earliest approval"] == ("Sep 2028", "from this gate; model 2030")
    # Detail on demand: the held rule and the legs' sources sit in the tooltips.
    by = rows_by_key(view, s)
    assert by["held"]["tip"] == ("A miss leaves 4 other Phase 3s open, and the model holds it "
                                 "at 55% until they read out.")
    assert by["chance"]["tip"].startswith("Phase 3 to NDA/BLA 61.0% then NDA/BLA to approval")
    assert "DiMasi 2016" in by["at DiMasi's level"]["tip"]
    lines = view["_gate_lines"](s)
    assert lines[0].startswith("The cost to reach is the Phase 3 programme in the modelled "
                               "disease, not the gate study alone: 5 open studies")
    assert lines[1] == ("Already paid inside the company's R&D ratio, so none of it is taken "
                        "off the value. Trial costs are at 2018 prices, not restated.")
    assert len(lines) == 2                                      # a clear floor says nothing


def test_the_picture_is_the_users_headline_the_chance_times_the_success_leg_less_the_cost(view):
    dev = load("LLY_1514_development")
    s = summary(view, "LLY_1514")
    steps = view["_gate_steps"](s)
    assert [(x["label"], x["kind"]) for x in steps] == [
        ("if it passes", "start"), ("39% it fails", "step"), ("risked now", "end"),
        ("cost to reach", "step"), ("net", "end")]
    success, p, g = steps[0]["value"], s["p"], dev["gate"]
    assert success == pytest.approx(g["success_leg_per_share"])
    now = success + steps[1]["value"]
    assert now == pytest.approx(g["rnpv_per_share"], rel=1e-12)  # p x success leg = rNPV
    assert now + steps[3]["value"] == pytest.approx(g["net_per_share"], rel=1e-12)
    assert p * success == pytest.approx(g["rnpv_per_share"], rel=1e-12)
    # The verdict's leg and the cost view's are the same figure, so the block reads one.
    assert load("LLY_1514_verdict")["gate"]["per_share_success"] == pytest.approx(success)


def test_a_stated_pos_reads_implied_odds_and_says_the_stated_figure_governs(view):
    by = rows_by_key(view, summary(view, "LLY_1492"))
    assert (by["chance"]["v"], by["chance"]["note"]) == ("98%", "implied by the stated PoS")
    assert by["held"]["note"] == "5 other Phase 3s open; the stated PoS governs"
    assert by["chance"]["tip"].startswith("implied, not published")


def test_a_gate_study_past_its_date_reads_due_and_a_danish_cost_says_its_currency(view):
    s = summary(view, "NVO_2337")
    assert view["_gate_head"](s) == "Phase 3 readout · due since Oct 2024 · NCT05567796"
    by = rows_by_key(view, s)
    assert by["cost to reach"]["note"] == "725mm DKK after tax, 2018 prices, not restated"
    assert by["cost to reach"]["v"] == "0.02"                  # a share, as the verdict reads it


def test_an_fda_gate_a_stated_pos_implies_reads_the_floor_from_the_registry_flagged(view):
    s = summary(view, "VRTX_2915")
    assert view["_gate_head"](s) == "FDA decision · no date on file"
    by = rows_by_key(view, s)
    assert by["chance"]["note"] == "stated PoS implies a filing"
    assert "held" not in by
    assert by["if it passes"]["tip"] == ""                      # approval is the gate itself
    approval = by["earliest approval"]
    assert approval["v"].startswith('<span class="u-flagged amber" title="2027 in the model')
    assert text_of(approval["v"]) == "Aug 2029"
    assert approval["note"] == "from the registry; model 2027"
    lines = view["_gate_lines"](s)
    assert lines[0] == ("The cost to reach is Sertkaya's FDA review out of pocket, $2.6mm, "
                        "spent as the review starts.")
    assert lines[-1].startswith("2027 in the model, but the earliest approval is Aug 2029")


def test_a_red_floor_set_by_another_study_names_the_gate_study_in_its_message(view):
    s = summary(view, "AMGN_1631")
    approval = rows_by_key(view, s)["earliest approval"]
    assert 'class="u-flagged red"' in approval["v"] and text_of(approval["v"]) == "Feb 2029"
    assert approval["note"] == "from this gate; model 2027"
    assert view["_gate_lines"](s)[-1].endswith(
        "The gate study is NCT07293260, completing 15 Jun 2028, which puts the earliest "
        "approval from it at Feb 2029.")


def test_a_cost_the_registry_cannot_read_is_no_free_data_never_nil(view):
    dev = load("LLY_6459_development")
    assert dev["gate"]["unread"] is True
    line = next(m for m in load("LLY_forecast-verdict")["modelled"] if m["asset_id"] == 6459)
    s = view["_gate_summary"]({"gate": line["gate"], "launch": line["launch"]}, dev)
    by = rows_by_key(view, s)
    assert by["cost to reach"]["v"] == "no free data" and by["cost to reach"]["tone"] == "none"
    assert "net" not in by and "at DiMasi's level" not in by
    steps = view["_gate_steps"](s)
    assert steps[-1] == {"label": "cost to reach", "value": None, "kind": "step",
                         "tip": dev["gate"]["basis"]}            # hatched, and no net after it
    assert view["_gate_lines"](s)[0].startswith("No free data for the cost to reach: no open "
                                                "study at this gate")
    table = view["_gate_table_html"](view["_gate_rows"](s))
    assert '<td class="v none">no free data</td>' in table and ">0.00<" not in table
    assert "no free data" in view["_gate_ladder_html"](dev)


def test_a_refused_cost_keeps_the_legs_and_says_why(view):
    s = summary(view, "GSK_2062")
    by = rows_by_key(view, s)
    assert {"chance", "if it passes", "if it fails"} <= set(by)
    assert not {"cost to reach", "net"} & set(by)
    assert view["_gate_lines"](s)[0].startswith("A vaccine: neither published source has a "
                                                "vaccine class")
    assert [x["label"] for x in view["_gate_steps"](s)][-1] == "risked now"
    assert view["_gate_ladder_html"](load("GSK_2062_development")) == ""


def test_a_failed_read_of_the_costs_says_it_did_not_load(view):
    s = view["_gate_summary"](load("LLY_1514_verdict"), None, dev_error="timed out.")
    assert view["_gate_lines"](s)[0] == ("The trial costs did not load: timed out. Reload in "
                                         "a minute.")
    by = rows_by_key(view, s)
    assert by["if it passes"]["v"] == "8.23" and "cost to reach" not in by


def _stated(failure=3.1):
    """Eloralintide as forecast_view._gate returns it where success and failure legs are
    stated on file: no gate odds, the stated failure leg, no held note and no band; the
    cost view refuses stated legs."""
    verdict = copy.deepcopy(load("LLY_1514_verdict"))
    verdict["gate"].update(legs_basis="stated", p_gate=None, p_gate_published=None,
                           placed=None, evidence=None, held=None, band=None,
                           per_share_failure=failure,
                           basis="stated success and failure legs on file")
    dev = {"ok": False, "reason": "stated_legs",
           "why": "Stated success and failure legs are on file; the cost view reads the "
                  "derived gates only."}
    return verdict, dev


def test_stated_legs_show_the_stated_failure_leg_never_the_conventions_nil(view):
    s = view["_gate_summary"](*_stated())
    by = rows_by_key(view, s)
    assert (by["if it fails"]["v"], by["if it fails"]["note"]) == (
        "3.10", "a share, the stated leg on file")
    assert by["if it fails"]["tip"] == "stated success and failure legs on file"
    assert (by["chance"]["v"], by["chance"]["note"]) == ("·", "stated legs carry no gate odds")
    assert by["if it passes"]["v"] == "8.23"
    # No gate odds, so no picture of a chance it fails; the table says what the legs are.
    assert view["_gate_steps"](s) == []
    assert view["_gate_lines"](s)[0].startswith("Stated success and failure legs are on file")
    for words in [text_of(view["_gate_table_html"](view["_gate_rows"](s)))] + \
            view["_gate_lines"](s):
        house_style(words)
    # A stated failure leg of nothing still reads nil, and derived legs keep the convention.
    nil = rows_by_key(view, view["_gate_summary"](*_stated(failure=0.0)))["if it fails"]
    assert (nil["v"], nil["note"]) == ("nil", "a share, the stated leg on file")
    assert rows_by_key(view, summary(view, "LLY_1514"))["if it fails"]["v"] == "nil"


def test_the_block_draws_no_empty_picture_where_there_are_no_steps():
    source = ast.get_source_segment(APP.read_text(), next(
        n for n in ast.parse(APP.read_text()).body
        if isinstance(n, ast.FunctionDef) and n.name == "_next_gate_layer"))
    assert source.index("if steps:") < source.index("CH.waterfall(steps")


def test_a_marketed_product_has_no_gate_block_and_no_gate_range(view):
    s = summary(view, "LLY_31")
    assert s == {}
    assert view["_gate_rows"](s) == [] and view["_gate_steps"](s) == []
    assert view["_gate_lines"](s) == []
    assert view["_gate_range_rows"](load("LLY_31_verdict")) == []


def test_the_range_is_nil_to_the_success_leg_with_the_pos_band_its_own_row(view):
    rows = view["_gate_range_rows"](load("LLY_1514_verdict"))
    assert [r["label"] for r in rows] == ["Phase 3 readout, derived", "PoS band"]
    assert rows[0]["low"] == 0.0 and rows[0]["high"] == pytest.approx(8.2344, abs=1e-4)
    assert rows[1]["low"] < 5.0234 < rows[1]["high"]
    assert len(view["_gate_range_rows"](load("LLY_1492_verdict"))) == 1   # stated: no band


def test_the_ladder_and_the_studies_are_detail_on_demand(view):
    dev = load("LLY_1514_development")
    ladder = text_of(view["_gate_ladder_html"](dev))
    assert ladder.startswith("gate date chance cost to reach if it passes net breaks even "
                             "Phase 3 readout Jan 2028 61% 0.15 8.23 4.87 1.9% FDA decision "
                             "no date 89% 0.00 9.21 8.23 0.02%")
    assert "Today, with every later trial cost paid: 4.87 a share against 5.02 risked" in ladder
    assert view["_GATE_LADDER"] == "After later trial costs"
    studies = view["_gate_studies_html"](dev)
    assert studies.count('href="https://clinicaltrials.gov/study/NCT07') == 5
    words = text_of(studies)
    assert "NCT07282600 Phase 3 1,035 $49k 61% 31mm" in words
    assert "Outside the headline: 1 other open study, its cost already spent" in words
    assert "Sertkaya A, Beleche T" in words and "DiMasi JA" in words


def test_the_company_table_puts_failing_gates_first_and_reconciles_with_the_books_rd(view):
    pay = load("AZN_development")
    rows = view["_gate_book_rows"](pay)
    assert [r["name"] for r in rows[:2]] == ["AZD5335", "AZD0120"]
    assert all(r["tone"] == "down" for r in rows[:2])
    assert [r["tone"] for r in rows[-3:]] == ["none"] * 3          # costs not read, last
    markup = view["_gate_book_html"](pay)
    assert markup.count('<td class="t n pipeline">') == len(rows)  # every compound purple
    assert '<td class="v down">−0.05</td>' in markup
    words = text_of(markup)
    assert "AZD0780 Phase 3 readout no date on file 64% no free data 1.07 ·" in words
    assert pay["reconciliation"]["sentence"] in words
    assert ("Not read: Ceralasertib (no gate is left to price: the probability in force is "
            "nil or the Phase 3 read out negative)") in words
    empty = view["_gate_book_html"]({"failing": [], "rows": [], "uncosted": []})
    assert text_of(empty).startswith("No counted pipeline line has a gate to cost")


def test_every_word_the_gate_builders_write_keeps_the_house_style(view):
    made = []
    for key in ("LLY_1514", "LLY_1492", "NVO_2337", "VRTX_2915", "AMGN_1631", "GSK_2062"):
        s = summary(view, key)
        made.append(text_of(view["_gate_table_html"](view["_gate_rows"](s))))
        made += view["_gate_lines"](s)
        made.append(view["_gate_head"](s))
        made.append(text_of(view["_gate_ladder_html"](load(f"{key}_development"))))
    made.append(text_of(view["_gate_book_html"](load("AZN_development"))))
    for words in made:
        house_style(words)
    for label in (view["_GATE_LADDER"], "Trials and sources", "Next gate",
                  "Pipeline development, next gate"):
        assert label[0].isupper() and label[1:] == label[1:].lower(), label


# --- the Catalysts tab: At stake ---------------------------------------------------------------
def test_met_and_missed_are_drawn_only_where_the_back_end_takes_a_resolve(view):
    ok = view["_stake_resolvable"]
    lly = load("LLY_catalysts_stakes")["priced"]
    for row in lly:
        assert ok(row) is (row["gate"] == "p3_to_nda"), row["asset_name"]
    assert ok(dict(lly[0], priced=False)) is False             # an unpriced row never
    assert ok(dict(lly[0], resolvable=None)) is False
    casgevy = next(r for r in load("VRTX_catalysts_stakes")["priced"]
                   if r["legs_basis"] == "stated")
    assert ok(casgevy) is True


def test_the_renderer_draws_no_button_on_a_row_that_is_not_resolvable():
    source = ast.get_source_segment(APP.read_text(), next(
        n for n in ast.parse(APP.read_text()).body
        if isinstance(n, ast.FunctionDef) and n.name == "_stake_row"))
    guard = source.index("if not _stake_resolvable(row):\n        return")
    assert guard < source.index("st.button(")


def test_every_derived_row_says_derived_and_a_missed_leg_of_nothing_is_nil(view):
    for row in load("LLY_catalysts_stakes")["priced"]:
        markup = view["_stake_row_html"](row)
        assert re.search(r'<span class="u-tag" title="[^"]+">derived</span>', markup)
        words = text_of(markup)
        assert words.endswith("nil missed") or "nil missed " in words
        assert "0.00 missed" not in words
        if not view["_stake_resolvable"](row):
            assert row["resolve_note"] in words
        house_style(words)
    eloralintide = text_of(view["_stake_row_html"](load("LLY_catalysts_stakes")["priced"][1]))
    assert eloralintide.startswith("Eloralintide 2028-01 · Phase 3 readout · A Study of "
                                   "Eloralintide (LY3841136)")
    assert ("+8.23/sh · PoS 0.55 now, 0.89 met, nil missed A miss leaves 4 other Phase 3s "
            "open") in eloralintide


def test_a_stated_row_carries_no_tag_and_keeps_its_missed_leg(view):
    priced = load("VRTX_catalysts_stakes")["priced"]
    casgevy = next(r for r in priced if r["legs_basis"] == "stated")
    markup = view["_stake_row_html"](casgevy)
    assert "u-tag" not in markup
    assert text_of(markup).endswith("PoS 0.81 now, 0.95 met, 0.40 missed")
    vx880 = text_of(view["_stake_row_html"](next(r for r in priced
                                                  if r["asset_name"] == "VX-880")))
    assert "The gate study NCT06832410 passed its completion date" in vx880


def test_six_rows_are_open_and_the_rest_fold(view):
    shown, rest = view["_stake_split"](load("LLY_catalysts_stakes")["priced"])
    assert (len(shown), len(rest)) == (6, 4)
    assert view["_stake_split"](load("VRTX_catalysts_stakes")["priced"])[1] == []


def test_a_resolve_under_a_stated_pos_says_the_stated_figure_still_governs(view):
    said = view["_stake_resolved_note"]({"route": "gate evidence", "stated_pos_governs": True,
                                          "pos_applied": 0.875})
    assert said == ("Recorded as gate evidence. The stated PoS of 88% still governs; clear it "
                    "under Assumptions to let the gate move it.")
    assert view["_stake_resolved_note"]({"route": "gate evidence"}) == ""
    assert view["_stake_resolved_note"]({"route": "stated legs",
                                         "stated_pos_governs": True}) == ""
    assert view["_stake_resolved_note"](None) == ""


def test_a_derived_stake_in_drivers_says_where_its_legs_come_from(view):
    tip = view["_dr_tip"]("driver", {"model": True, "value_kind": "stake",
                                     "pct_of_price": 0.018, "title": "Phase 3, A Study",
                                     "lead_note": "modelled swing, derived from published "
                                                  "transition rates"})
    assert tip.startswith("Model output, modelled swing, derived from published transition "
                          "rates: the swing between the met and missed cases")
    plain = view["_dr_tip"]("driver", {"model": True, "value_kind": "stake",
                                       "pct_of_price": 0.018, "title": ""})
    assert plain.startswith("Model output: the swing")


# --- the page, through AppTest ---------------------------------------------------------------
# Opt in with ER_TOOL_APPTEST=1 against a running API: a plain test run never calls it.
API = os.environ.get("ER_API_BASE", "http://localhost:8000")


def api_up() -> bool:
    if os.environ.get("ER_TOOL_APPTEST") != "1":
        return False
    try:
        with urllib.request.urlopen(API + "/health", timeout=2):
            return True
    except (urllib.error.URLError, OSError):
        return False


@pytest.mark.skipif(not api_up(), reason="ER_TOOL_APPTEST is unset or the API is down")
def test_the_forecast_tab_has_a_next_gate_layer_for_a_pipeline_asset_only():
    from streamlit.testing.v1 import AppTest

    def page(asset_id):
        at = AppTest.from_file(str(APP), default_timeout=600)
        at.query_params["ticker"] = "LLY"
        at.session_state["fc_pick_LLY"] = asset_id
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        return at

    eloralintide = page(1514)
    assert "Next gate" in [t.label for t in eloralintide.tabs]
    body = " ".join(str(m.value) for m in eloralintide.markdown)
    assert "Phase 3 readout · est. Jan 2028 · NCT07282600" in body
    assert "After later trial costs" in [e.label for e in eloralintide.expander]
    # Met and missed only on the rows the back end takes a resolve on.
    with urllib.request.urlopen(API + "/companies/LLY/catalysts/stakes", timeout=120) as resp:
        priced = json.loads(resp.read())["priced"]
    keys = {b.key for b in eloralintide.button}
    for row in priced:
        assert (f"cat_met_LLY_{row['id']}" in keys) is (row.get("resolvable") is True)
    assert "Next gate" not in [t.label for t in page(31).tabs]          # Mounjaro
