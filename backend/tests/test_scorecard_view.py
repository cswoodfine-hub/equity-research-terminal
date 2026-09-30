"""The clinical scorecard's view: the table's range column and dagger, the tooltip head,
the words under the table and the method text (specification 5.5).

The helpers live in the Streamlit script, which runs the whole app on import, so they
are read out of its source by name and run on their own. Only pure string builders are
read; none of them touches Streamlit.
"""

from __future__ import annotations

import ast
import html
import pathlib
import re

import pytest

import landscape_score as S
from tests.test_landscape_score import BANNED, _general

APP = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "streamlit_app.py"
HELPERS = ("_score_cell", "_score_range", "_score_tip", "_score_why", "_score_rows",
           "_score_footnote", "_score_method", "_stage_chip", "_decap", "_SCORE_TERMS")


@pytest.fixture(scope="module")
def view():
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    keep = []
    for node in tree.body:
        name = (node.name if isinstance(node, ast.FunctionDef)
                else node.targets[0].id if isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name) else None)
        if name in HELPERS:
            keep.append(node)
    assert {getattr(n, "name", None) or n.targets[0].id for n in keep} == set(HELPERS)
    module = ast.Module(body=keep, type_ignores=[])
    space = {"html_escape": lambda t: html.escape(str(t), quote=True)}
    exec(compile(module, str(APP), "exec"), space)
    return space


def _asset(name, ticker, rank, lo, hi, basis="ranked", eff=80.0):
    return {"name": name, "ticker": ticker, "stage": "Marketed", "rank": rank,
            "rank_range": [lo, hi], "overall": 70.4, "placed": True,
            "rank_line": f"{name} ranks {rank} of 3 scored drugs.",
            "efficacy": {"score": eff, "size_basis": basis,
                         "lines": ["E one.", "E two.", "E three."], "notes": ["E note."]},
            "safety": {"score": 61.6, "lines": ["S one."], "notes": ["S note."]},
            "evidence": {"score": 55.0}}


def _text(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup)))


def test_the_range_sits_after_the_rank_and_shows_the_rank_where_it_never_moved(view):
    placed = [_asset("Alpha", "AAA", 1, 1, 1), _asset("Beta", "BBB", 2, 2, 3)]
    table = view["_score_rows"](placed, "AAA")
    head = re.findall(r"<th[^>]*>([^<]*)</th>", table)
    assert head[:3] == ["", "range", "compound"]
    cells = re.findall(r'<td class="n m sc-rng">([^<]*)</td>', table)
    assert cells == ["1", "2 to 3"]
    assert 'class="sc-mine"' in table and "<b>Alpha</b>" in table
    assert "†" not in table and "sc-dg" not in table


def test_a_drug_on_strength_and_wins_alone_carries_a_dagger_and_the_line_that_explains_it(view):
    placed = [_asset("Alpha", "AAA", 1, 1, 2), _asset("Beta", "BBB", 2, 1, 3, "not comparable")]
    table = view["_score_rows"](placed, "AAA")
    slots = re.findall(r'<span class="sc-dg">([^<]*)</span>', table)
    assert slots == ["", "†"]                   # every efficacy cell has the slot
    foot = _text(view["_score_footnote"](placed))
    assert foot.strip() == ("† Size of effect not compared: no peer was tested against the "
                            "same control on the same measure in trials of about the same "
                            "length, so its size counts at 50, what the average drug scores "
                            "against its peers.")
    assert view["_score_footnote"]([_asset("Alpha", "AAA", 1, 1, 1)]) == ""


def test_an_indication_with_no_size_says_every_efficacy_score_is_strength_and_wins(view):
    placed = [_asset("Alpha", "AAA", 1, 1, 2, None), _asset("Beta", "BBB", 2, 1, 2, None)]
    foot = view["_score_footnote"](placed)
    assert "every efficacy score is strength and wins alone" in foot
    assert "sc-dg" not in view["_score_rows"](placed, "AAA")


def test_the_tooltip_head_carries_the_rank_and_where_it_could_sit(view):
    tip = view["_score_tip"](_asset("Beta", "BBB", 2, 2, 3))
    assert tip.startswith("Beta (BBB), Marketed. Overall 70, rank 2 (could sit 2 to 3): "
                          "efficacy 80, safety 62, evidence 55. E one. E two. E three. S one.")
    fixed = view["_score_tip"](_asset("Alpha", "AAA", 1, 1, 1))
    assert "Overall 70, rank 1: efficacy 80" in fixed and "could sit" not in fixed
    assert "note" not in fixed                  # notes are on demand, never in the tooltip


def test_lines_print_under_the_chart_and_notes_only_on_demand(view):
    a = _asset("Beta", "BBB", 2, 2, 3)
    short = _text(view["_score_why"](a))
    assert "E one. E two. E three. S one." in short and "note" not in short
    full = view["_score_why"](a, numbered=True, notes=True)
    assert "<b>2. Beta</b>" in full and "rank could sit 2 to 3" in full
    assert full.index("S one.") < full.index("E note.") < full.index("S note.")


def test_the_method_text_carries_the_range_after_overall_and_glosses_its_terms(view):
    sc = S.scorecard(_general())
    out = view["_score_method"](sc["method"])
    words = _text(out)
    assert words.index("Overall:") < words.index("The range beside a rank") < words.index(
        "Scores cross trials")
    for term in ("z-score:", "Allowing for the number each trial tested:", "95% interval:",
                 "Hazard ratio:", "Moved toward the class average:",
                 "Moved toward the average of the drugs here:"):
        assert term in words


def test_every_string_the_view_adds_is_in_house_style(view):
    sc = S.scorecard(_general())
    placed = [a for a in sc["assets"] if a["placed"]]
    pieces = [view["_score_method"](sc["method"]), view["_score_rows"](placed, "AAA"),
              view["_score_footnote"](placed)]
    pieces += [view["_score_tip"](a) + view["_score_why"](a, True, True) for a in placed]
    for markup in pieces:
        words = _text(markup)
        assert not any(b in words.lower() for b in BANNED), words
        assert "—" not in words.replace("<td class=\"n m\">—</td>", ""), words
    for k, v in view["_SCORE_TERMS"]:
        assert v.endswith(".") and "—" not in k + v
        assert not any(b in (k + v).lower() for b in BANNED)


def test_the_live_scorecard_builds_its_view_without_error(view):
    sc = S.scorecard(_general())
    placed = [a for a in sc["assets"] if a["placed"]]
    ticker = placed[0]["ticker"]
    table = view["_score_rows"](placed, ticker)
    assert table.count("<tr") == len(placed) + 1
    for a in placed:
        lo, hi = a["rank_range"]
        assert (view["_score_range"](a) == "") == (lo == hi)
        assert a["rank_line"].startswith(a["name"])
