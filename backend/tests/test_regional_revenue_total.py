"""A product the filer prints only by region carries the sum of its regions as its year,
where the quoted table line prints that sum, and nothing is added to a filed figure."""

import pytest

import asset_revenue as AR
import db

QUOTE = ("Vaccines turnover – year ended 31 December 2025 | Total | US | Europe | "
         "International ... Shingrix | 3,558 | 6 | 8 | 1,200 | 2 | 1,317 | 9 | 1,041 | 7")


def _db(tmp_path, parts=(("US", 1200), ("EU", 1317), ("ROW", 1041)), quote=QUOTE, filed=None,
        curated=1):
    path = str(tmp_path / "r.db")
    db.init(path)
    c = db.get_connection(path)
    c.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'GSK', 'GSK')")
    c.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
              " VALUES (7, 1, 'Shingrix', 1)")
    for region, value in parts:
        c.execute("INSERT INTO asset_revenue_regions (asset_id, fiscal_year, member, region,"
                  " value, unit, source, note, is_curated) VALUES (7, 2025, ?, ?, ?, 'GBP',"
                  " 'annual report table', ?, ?)", (region, region, value * 1e6, quote, curated))
    if filed is not None:
        c.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit,"
                  " source) VALUES (7, 2025, 'FY', ?, 'GBP', 'sec_fsds')", (filed,))
    c.commit()
    c.close()
    return path


def test_the_year_is_the_sum_of_its_regions_where_the_line_prints_it(tmp_path):
    rows = AR.list_revenue(_db(tmp_path), "GSK")
    assert [(r["fiscal_year"], r["value"], r["unit"], r["source"]) for r in rows] == [
        (2025, pytest.approx(3558e6), "GBP", AR.REGIONAL_SOURCE)]
    assert rows[0]["brand_name"] == "Shingrix" and rows[0]["id"] is None
    assert "Shingrix | 3,558" in rows[0]["note"]


def test_a_filed_figure_stands_and_is_not_added_to(tmp_path):
    rows = AR.list_revenue(_db(tmp_path, filed=3.0e9), "GSK")
    assert [r["value"] for r in rows] == [3.0e9]


def test_regions_the_line_does_not_sum_to_or_not_entered_by_hand_give_no_year(tmp_path):
    assert AR.list_revenue(_db(tmp_path, parts=(("US", 1200), ("EU", 1317))), "GSK") == []
    (tmp_path / "x").mkdir()
    assert AR.list_revenue(_db(tmp_path / "x", curated=0), "GSK") == []
