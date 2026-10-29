"""The value at each end of a product's LOE range, through the engine's stated year."""

import loe as loe_module
import loe_range
from tests.test_loe_in_base import _product


def test_each_end_is_valued_through_the_stated_year(monkeypatch):
    inputs = _product(record=2033, late=True)
    monkeypatch.setattr(loe_range.assumptions_module, "load", lambda conn, aid, sc: inputs)
    monkeypatch.setattr(loe_module, "for_assets", lambda conn, ids, exclude_orphan: {
        ids[0]: {"date": "2033-06-01", "basis": "drug substance patent", "past": False,
                 "molecule_date": "2030-01-01", "molecule_patent": "111",
                 "latest_patent_date": "2036-01-01", "latest_patent": "222"}})
    got = loe_range.for_asset(None, 7)
    assert [got[e]["date"] for e in ("bear", "base", "bull")] == [
        "2030-01-01", "2033-06-01", "2036-01-01"]
    # An earlier cliff is worth less and a later one more, nothing else moving.
    assert got["bear"]["npv"] < got["base"]["npv"] < got["bull"]["npv"]
    assert "111" in got["why_bear"] and "222" in got["why_bull"]


def test_no_date_no_range(monkeypatch):
    monkeypatch.setattr(loe_module, "for_assets", lambda conn, ids, exclude_orphan: {})
    assert loe_range.for_asset(None, 7) is None
