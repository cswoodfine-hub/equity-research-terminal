"""Revenue by year as stacked columns on the Forecast tab.

The builder lives in the Streamlit script, which runs the whole app on import, so it is
read out of its source by name and run on its own, as the scorecard view tests do. It is
a pure string builder and touches no Streamlit.
"""

from __future__ import annotations

import ast
import html
import pathlib
import re
import sys

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
APP = FRONTEND / "streamlit_app.py"
HELPERS = ("_revenue_bars", "_mix_hex")


@pytest.fixture(scope="module")
def bars():
    sys.path.insert(0, str(FRONTEND))
    try:
        from components import tokens as TK
    finally:
        sys.path.remove(str(FRONTEND))
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    keep = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in HELPERS]
    assert {n.name for n in keep} == set(HELPERS)
    space = {"html_escape": lambda t: html.escape(str(t), quote=True), "TK": TK}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(APP), "exec"), space)
    return space["_revenue_bars"]


def _shares(markup: str) -> list[float]:
    return [float(x) for x in re.findall(r"flex:([0-9.]+) 1 0", markup)]


PATH = [{"year": 2026, "marketed": 600.0, "lines": None, "pipeline": 300.0,
         "pipeline_risked": 100.0, "total_risked": 700.0},
        {"year": 2027, "marketed": 700.0, "lines": None, "pipeline": None,
         "pipeline_risked": None, "total_risked": 700.0}]
LAST = {"fiscal_year": 2025, "value": 650.0}


def test_each_year_stacks_to_its_share_of_the_tallest_and_the_haircut_sits_on_top(bars):
    out = bars(PATH, LAST, 500.0, [0.4, 0.0], False, True)
    # The tallest stack is 2026 unrisked (600 + 100 + 200 = 900): every column's
    # spacer and segments add to the same thousand, so the bars stay in proportion.
    cols = out.split('<div class="rb-col">')[1:]
    for col in cols:
        assert sum(_shares(col)) == pytest.approx(1000.0, abs=0.01)
    assert _shares(cols[1]) == pytest.approx([0.0, 200 / 9 * 10, 100 / 9 * 10, 600 / 9 * 10],
                                             abs=0.01)
    assert 'class="rb-seg hatch"' in cols[1] and "taken off by PoS: 200" in cols[1]
    # The label is the risked total, on the top segment only.
    assert cols[1].count("rb-v") == 1 and ">700</span>" in cols[1]


def test_a_null_is_a_gap_never_a_zero_bar(bars):
    out = bars(PATH, LAST, 500.0, [0.4, 0.0], False, True)
    col = out.split('<div class="rb-col">')[3]
    # 2027 has no pipeline figure: no pipeline segment is drawn at all.
    assert "pipeline" not in col and "marketed: 700" in col


def test_the_reported_year_is_one_bar_and_the_company_a_line(bars):
    out = bars(PATH, LAST, 500.0, [0.4, 0.0], False, True)
    first = out.split('<div class="rb-col">')[1]
    assert "the book, reported: 500" in first and "rb-g\"></span>" in first
    assert 'class="rb-line"' in out and "whole company, FY2025 650" in out
    assert "+40.0%" in out and 'rb-g up' in out


def test_no_revenue_draws_nothing(bars):
    assert bars([], None, None, [], False, False) == ""
