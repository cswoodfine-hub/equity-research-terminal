"""What the price implies: one revenue factor, one shift of every cliff, one discount rate."""

from __future__ import annotations

import pytest

import breakpoints as B
import db
import forecast_view as V
import implied
from tests.test_breakpoints import _company


def _priced(tmp_path, times: float, loe: int | None = None):
    """The one-product Amgen book, priced at ``times`` its own value, with a cliff in
    ``loe`` where given."""
    base = V.company_verdict(_company(tmp_path / "base", close=1.0),
                             "AMGN")["sotp"]["equity_per_share"]
    path = _company(tmp_path / "priced", close=base * times)
    if loe is not None:
        conn = db.get_connection(path)
        conn.execute("INSERT INTO assumptions (asset_id, region, scenario, key, value,"
                     " source) VALUES (1, 'US', 'base', 'loe_year', ?, 'test')", (loe,))
        conn.commit()
        conn.close()
    return path


def test_the_revenue_factor_meets_the_price(tmp_path):
    path = _priced(tmp_path, 1.5)
    claims = implied.Claims(B.Book(path, "AMGN"), held_year=None)
    found = claims.revenue_factor()
    assert found["reachable"] and found["value"] > 1.0
    assert claims.gap(factor=found["value"]) == pytest.approx(0.0, abs=1e-6)


def test_holding_the_current_year_asks_more_of_the_years_after_it(tmp_path):
    """The current year is mostly reported, so its extra cash flow is taken back out
    and the years still to come carry the price: a larger factor, and the held year
    reads at the model."""
    path = _priced(tmp_path, 1.5)
    book = B.Book(path, "AMGN")
    free = implied.Claims(book, held_year=None).revenue_factor()["value"]
    held = implied.Claims(book).revenue_factor()["value"]
    assert held > free
    got = implied.company(path, "AMGN")
    first = got["revenue"]["years"][0]
    assert first["held"] and first["implied"] == first["model"]
    later = got["revenue"]["years"][1]
    assert later["implied"] == pytest.approx(later["model"] * got["revenue"]["factor"])


def test_a_later_cliff_is_the_durability_the_price_needs(tmp_path):
    path = _priced(tmp_path, 1.1, loe=2029)
    claims = implied.Claims(B.Book(path, "AMGN"))
    found = claims.durability()
    assert found["reachable"] and found["value"] > 0
    assert claims.gap(extra=found["value"]) >= 0 > claims.gap(extra=found["value"] - 1)


def test_a_price_no_cliff_can_reach_says_exclusivity_alone_never_gets_there(tmp_path):
    """Lilly's case: no shift of every loss of exclusivity meets the price, and the
    sentence says so rather than naming a year nobody would hold."""
    got = implied.company(_priced(tmp_path, 20.0), "AMGN")
    assert got["durability"]["extra_years"] is None
    assert any("Exclusivity alone does not get there" in s for s in implied.sentence(got))


def test_the_rate_the_price_discounts_at(tmp_path):
    """Priced above the model, the market accepts a lower rate; below, it offers more."""
    above = implied.company(_priced(tmp_path / "a", 1.3), "AMGN")["rate"]
    below = implied.company(_priced(tmp_path / "b", 0.7), "AMGN")["rate"]
    assert above["implied"] < above["model"] < below["implied"]


def test_the_sentences_keep_the_house_style(tmp_path):
    text = " ".join(implied.sentence(implied.company(_priced(tmp_path, 1.5, loe=2029),
                                                     "AMGN")))
    assert text.startswith("At $") and "the price implies every product sells" in text
    assert "\u2014" not in text
    for word in ("additionally", "highlight", "underscore", "pivotal", "showcase",
                 "testament"):
        assert word not in text.lower()
