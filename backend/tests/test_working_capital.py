"""Working capital build taken out of the other-costs calibration."""

import pytest

import db
import working_capital as WC


def _db(tmp_path, rows, tax=0.2):
    path = str(tmp_path / "wc.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly'),"
                 " (2, 'REGN', 'Regeneron'), (3, 'AZN', 'AstraZeneca')")
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


def test_a_build_lowers_the_charge_and_names_the_payables_line_it_read(tmp_path):
    # Receivables and inventories each take $3mm a year and payables with accruals give $2mm
    # back: a build of $4mm a year on revenue of $100mm.
    conn = _db(tmp_path, _years(1, "Revenues", 2018, 2025, 100e6)
               + _years(1, "ReceivablesCashEffect", 2018, 2025, -3e6)
               + _years(1, "InventoriesCashEffect", 2018, 2025, -3e6)
               + _years(1, "PayablesAccruedCashEffect", 2018, 2025, 2e6))
    m = WC.measure(conn, "LLY")
    assert m["share"] == pytest.approx(0.04) and m["cut"] == pytest.approx(0.05)
    assert m["payables_as"] == "payables and accrued liabilities"
    row = WC.restate_row({"value": 0.2025, "source": "derived: LLY turned ..."}, m, "LLY")
    assert row["value"] == pytest.approx(0.1525)
    assert "Restated without working capital build" in row["source"]
    assert "payables and accrued liabilities up $16mm" in row["source"]
    assert "falls from 20.25% to 15.25%" in row["source"]
    assert WC.restate_row(row, m, "LLY") is None


def test_the_narrow_payables_line_wins_where_both_are_tagged(tmp_path):
    conn = _db(tmp_path, _years(1, "Revenues", 2018, 2025, 100.0)
               + _years(1, "ReceivablesCashEffect", 2018, 2025, -1.0)
               + _years(1, "InventoriesCashEffect", 2018, 2025, -1.0)
               + _years(1, "PayablesCashEffect", 2018, 2025, 0.5)
               + _years(1, "PayablesAccruedCashEffect", 2018, 2025, 9.0))
    m = WC.measure(conn, "LLY")
    assert m["payables_as"] == "payables" and m["share"] == pytest.approx(0.015)


def test_a_release_raises_the_charge(tmp_path):
    conn = _db(tmp_path, _years(2, "Revenues", 2023, 2025, 50e6)
               + _years(2, "ReceivablesCashEffect", 2023, 2025, -0.5e6)
               + _years(2, "InventoriesCashEffect", 2023, 2025, -1e6)
               + _years(2, "PayablesCashEffect", 2023, 2025, 2.5e6))
    m = WC.measure(conn, "REGN")
    assert m["build"] == pytest.approx(-3e6) and m["cut"] == pytest.approx(-0.025)
    row = WC.restate_row({"value": 0.0425, "source": "s"}, m, "REGN")
    assert row["value"] == pytest.approx(0.0675)
    assert "a working capital release of $3mm, 2.00% of revenue" in row["source"] and "rises from 4.25% to 6.75%" in row["source"]


def test_a_charge_falls_no_further_than_the_amortisation_floor():
    m = {"cut": 0.05}
    assert WC.charge(0.02, m, rebuilt=0.02, bound=-0.0431) == pytest.approx(-0.0300)
    assert WC.charge(0.02, m, rebuilt=0.02, bound=-0.01) == pytest.approx(-0.01)
    # A filer with no amortisation inside its cost lines stops at nil.
    assert WC.charge(0.02, m, rebuilt=0.02) == 0.0


def test_a_held_charge_moves_from_its_rebuilt_figure():
    # Held at a -11.70% floor while the filed figures rebuild it at -14.77%: a release of
    # 1.16 points does not lift it off the floor.
    assert WC.charge(-0.1170, {"cut": -0.0116}, rebuilt=-0.1477, bound=-0.1170) == pytest.approx(-0.1170)
    # Held at nil with no floor, it stays at nil.
    assert WC.charge(0.0, {"cut": 0.0172}, rebuilt=-0.0468) == 0.0
    # A row that is neither at nil nor at the floor moves from its own value, even where
    # the filed ratios rebuild it lower.
    assert WC.charge(0.0206, {"cut": 0.0329}, rebuilt=-0.0346, bound=-0.0431) == pytest.approx(-0.0123)


def test_a_missing_line_leaves_the_charge_standing(tmp_path):
    conn = _db(tmp_path, _years(3, "Revenues", 2023, 2025, 60.0)
               + _years(3, "ReceivablesCashEffect", 2023, 2025, -1.0)
               + _years(3, "InventoriesCashEffect", 2023, 2025, -1.0))
    m = WC.measure(conn, "AZN")
    assert m["cut"] is None and "no change in payables" in m["reason"]
    row = WC.restate_row({"value": -0.0472, "source": "s"}, m, "AZN")
    assert row["value"] == -0.0472
    assert "Checked without working capital build" in row["source"] and "stands" in row["source"]


def test_a_held_row_says_where_it_was_held():
    m = {"cut": -0.0116, "first": 2023, "last": 2025, "unit": "USD", "build": -997e6,
         "share": -0.0101, "payables_as": "payables",
         "effects": {"receivables": -3250e6, "inventories": 3909e6, "payables": 338e6}}
    row = WC.restate_row({"value": -0.1170, "source": "s"}, m, "AMGN", rebuilt=-0.1477, bound=-0.1170)
    assert row["value"] == pytest.approx(-0.1170)
    assert "receivables up $3,250mm, inventories down $3,909mm, payables up $338mm" in row["source"]
    assert "held at the amortisation floor, -11.70% where the filed figures rebuild it at -14.77%, and stays there." in row["source"]
