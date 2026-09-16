"""Capital spending counted at depreciation in the other-costs calibration."""

import pytest

import db
import replacement_capex as RC


def _db(tmp_path, rows, tax=0.2):
    path = str(tmp_path / "rc.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly'),"
                 " (2, 'BIIB', 'Biogen'), (3, 'PFE', 'Pfizer')")
    for cid in (1, 2, 3):
        conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                     " VALUES (?, ?, 'x', 1)", (cid, cid))
        conn.execute("INSERT INTO assumptions (asset_id, key, value, source)"
                     " VALUES (?, 'tax_rate', ?, 't')", (cid, tax))
    for cid, metric, year, value in rows:
        conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                     " period_end, value, unit) VALUES (?, ?, 'FY', ?, ?, ?, 'USD')",
                     (cid, metric, year, f"{year}-12-31", value))
    conn.commit()
    return conn


def _years(cid, metric, first, last, value):
    return [(cid, metric, y, value) for y in range(first, last + 1)]


def test_a_builder_is_charged_its_depreciation_not_its_build(tmp_path):
    conn = _db(tmp_path, _years(1, "Revenues", 2018, 2025, 100.0)
               + _years(1, "CapitalExpenditure", 2018, 2025, -10.0)
               + _years(1, "Depreciation", 2018, 2025, 4.0))
    m = RC.measure(conn, "LLY")
    assert m["share"] == pytest.approx(0.06) and m["cut"] == pytest.approx(0.06 / 0.8)
    row = RC.restate_row({"value": 0.2846, "source": "derived: LLY turned ..."}, m, "LLY")
    assert row["value"] == pytest.approx(0.2846 - 0.075)
    assert "Restated at replacement capex" in row["source"] and "falls from 28.46%" in row["source"]
    assert RC.restate_row(row, m, "LLY") is None


def test_it_runs_both_ways_and_derives_plant_depreciation_where_only_the_combined_line_is_filed(tmp_path):
    conn = _db(tmp_path, _years(2, "Revenues", 2023, 2025, 10.0)
               + _years(2, "CapitalExpenditure", 2023, 2025, 0.2)
               + _years(2, "DepreciationAndAmortisation", 2023, 2025, 0.9)
               + _years(2, "AmortisationOfIntangibles", 2023, 2025, 0.6))
    m = RC.measure(conn, "BIIB")
    assert m["derived"] is True and m["depreciation"] == pytest.approx(0.9)
    assert m["share"] == pytest.approx(-0.1 * 3 / 30)
    row = RC.restate_row({"value": 0.06, "source": "s"}, m, "BIIB")
    assert row["value"] > 0.06 and "rises" in row["source"]


def test_a_missing_line_leaves_the_charge_standing(tmp_path):
    conn = _db(tmp_path, _years(3, "Revenues", 2023, 2025, 60.0)
               + _years(3, "CapitalExpenditure", 2023, 2025, 3.0)
               + [(3, "DepreciationAndAmortisation", y, 6.5) for y in (2023, 2024, 2025)]
               + [(3, "AmortisationOfIntangibles", y, 5.0) for y in (2023, 2024)])
    m = RC.measure(conn, "PFE")
    assert m["cut"] is None and "no plant depreciation" in m["reason"]
    assert RC.restate_row({"value": 0.17, "source": "s"}, m, "PFE")["value"] == 0.17
