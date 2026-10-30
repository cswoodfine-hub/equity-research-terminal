"""The Medicare negotiated price's bear case: the cohort table read from CMS's fact
sheets, the engine's US price step, and the view joining them, no network."""

from __future__ import annotations

import ast
import html
import pathlib
import re
import sys

import pytest

import db
import forecast as F
import ira_bear
import seed
from test_loe_in_base import _product

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "frontend" / "streamlit_app.py"


def test_the_cohorts_carry_cms_savings_as_a_share_of_gross():
    got = ira_bear.cohorts()
    assert got[2026]["savings_share"] == pytest.approx(6 / 56.2)
    assert got[2027]["savings_share"] == pytest.approx(12 / 42.5)
    assert got[2026]["base_year"] == 2023 and got[2027]["base_year"] == 2024
    # No cohort is carried for a year whose prices CMS has not published.
    assert 2028 not in got


def test_the_price_step_cuts_the_us_line_from_its_year_and_leaves_the_regions():
    europe = [{"region": "EU", "label": "Europe", "share": 0.4, "share_basis": "filed",
               "year": 2040, "in_base": False, "basis": "stated"}]
    plain = F.build(_product(record=2040, regions=europe))
    stepped = F.build(dict(_product(record=2040, regions=europe),
                           price_step={"from_year": 2028, "factor": 0.25, "basis": "test"}))
    years = plain["years"]
    for i, year in enumerate(years):
        us_plain = plain["revenue_after_loe"][i] - plain["regions"][0]["revenue_after_loe"][i]
        us_step = stepped["revenue_after_loe"][i] - stepped["regions"][0]["revenue_after_loe"][i]
        assert us_step == pytest.approx(us_plain * (0.75 if year >= 2028 else 1.0))
        assert (stepped["regions"][0]["revenue_after_loe"][i]
                == pytest.approx(plain["regions"][0]["revenue_after_loe"][i]))
    assert stepped["npv"] < plain["npv"]
    assert any("cut by 25.0%" in n for n in stepped["notes"])


def test_the_bear_case_cuts_the_cohort_share_of_part_d_gross(tmp_path, monkeypatch):
    db_file = tmp_path / "t.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker = 'LLY'").fetchone()[0]
    conn.execute("UPDATE companies SET reporting_currency = 'USD' WHERE id = ?", (cid,))
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                 " VALUES (?, 'Testdrug', 1)", (cid,))
    aid = conn.execute("SELECT id FROM assets WHERE brand_name = 'Testdrug'").fetchone()[0]
    conn.commit()
    monkeypatch.setattr(ira_bear.ira, "selected", lambda c: [
        {"asset_id": aid, "in_force": True, "ipay": 2027, "drug": "TESTDRUG"}])
    # 1,000mm of Medicare Part D gross; the product sells 1,000mm a year in the US.
    monkeypatch.setattr(ira_bear.ira, "exposure", lambda c, a: {
        "part_d_spending": 1.0e9, "year": 2024, "reason": None})
    monkeypatch.setattr(ira_bear.assumptions_module, "load",
                        lambda c, a, s: _product(record=2040, revenue_growth_pct=0.0))
    got = ira_bear.for_asset(conn, aid)
    share = 12 / 42.5
    assert got["ipay"] == 2027 and got["annual_cut"] == pytest.approx(1000 * share)
    assert got["factor"] == pytest.approx(share, rel=1e-6)
    assert got["npv_bear"] < got["npv_base"]
    # A selection with no price in force has no bear case.
    monkeypatch.setattr(ira_bear.ira, "selected", lambda c: [
        {"asset_id": aid, "in_force": False, "ipay": 2028, "drug": "TESTDRUG"}])
    assert ira_bear.for_asset(conn, aid) is None


def test_the_page_states_the_cut_as_the_cohort_average():
    sys.path.insert(0, str(ROOT / "frontend"))
    import theme
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    names = {"_ira_bear_html", "_prof_rows", "_money_mm", "html_escape"}
    keep = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    space = {"html": html, "re": re, "T": theme}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(APP), "exec"), space)
    bear = {"ipay": 2026, "savings_share": 6 / 56.2, "part_d_year": 2024,
            "annual_cut": 2218.4, "currency": "USD", "factor": 0.182, "capped": False,
            "npv_base": 22211.0, "npv_bear": 18850.0}
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ",
                                                     "".join(space["_ira_bear_html"](bear)))))
    assert "from 2026 2,218 USD mm a year, 18% of the US line" in text
    assert "10.7% of Medicare Part D gross (2024), the 2026 cohort's average" in text
    assert "22.2 bn to 18.9 bn" in text
    assert space["_ira_bear_html"](None) == []
