"""One-off cash taken out of the other-costs charge."""

import pytest

import db
import one_off_cash as OC

HEADER = "ticker,fiscal_year,kind,amount,unit,accession,quote,note\n"


def _db(tmp_path, tax=0.1331):
    path = str(tmp_path / "oc.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'MRK', 'Merck'), (2, 'LLY', 'Lilly')")
    for cid in (1, 2):
        conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed) VALUES (?, ?, 'x', 1)", (cid, cid))
        conn.execute("INSERT INTO assumptions (asset_id, key, value, source) VALUES (?, 'tax_rate', ?, 't')", (cid, tax))
    for year, value in ((2023, 60115e6), (2024, 64168e6), (2025, 65011e6)):
        conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                     " VALUES (1, 'Revenues', 'FY', ?, ?, ?, 'USD')", (year, f"{year}-12-31", value))
    for year in range(2018, 2026):
        conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                     " VALUES (2, 'Revenues', 'FY', ?, ?, 40000e6, 'USD')", (year, f"{year}-12-31"))
    conn.commit()
    return conn


def _file(tmp_path, body):
    path = tmp_path / "one_offs.csv"
    path.write_text("# a comment\n" + HEADER + body)
    return path


MERCK = ("MRK,2023,deal_payments,4200,USD,a,\"q\",\n"
         "MRK,2024,deal_payments,1100,USD,a,\"q\",\n"
         "MRK,2025,deal_payments,3000,USD,a,\"q\",\n"
         "MRK,2023,legal_settlement,572.5,USD,a,\"q\",\n"
         "MRK,2022,transition_tax_liability,2200,USD,a,\"q\",\n"
         "MRK,2023,transition_tax_liability,1500,USD,a,\"q\",\n"
         "MRK,2024,transition_tax_liability,518,USD,a,\"q\",\n")


def test_deals_and_settlements_come_out_net_of_tax_and_the_transition_tax_gross(tmp_path):
    conn = _db(tmp_path)
    m = OC.measure(conn, "MRK", _file(tmp_path, MERCK))
    revenue = 189294e6
    assert m["deals"] == 8300 and m["settlements"] == 572.5
    # Balances alone are not payments: nothing is counted until an instalment is stated.
    assert m["transition"] == 0
    assert m["cut"] == pytest.approx(8872.5e6 / revenue)
    row = OC.restate_row({"value": 0.0748, "source": "derived: ..."}, m)
    assert row["value"] == pytest.approx(0.0748 - m["cut"])
    assert "Restated without one-off cash" in row["source"] and "$8,300mm of deal payments" in row["source"]
    assert OC.restate_row(row, m) is None


def test_a_charge_cannot_fall_below_nil(tmp_path):
    conn = _db(tmp_path)
    m = OC.measure(conn, "MRK", _file(tmp_path, MERCK))
    row = OC.restate_row({"value": 0.01, "source": "s"}, m)
    assert row["value"] == 0.0 and "falls from 1.00% to 0.00%" in row["source"]


def test_deal_cash_booked_under_investing_changes_nothing(tmp_path):
    conn = _db(tmp_path)
    m = OC.measure(conn, "LLY", _file(tmp_path, "LLY,2023,deal_payments_investing,3944,USD,a,\"q\",\n"))
    assert m["cut"] is None and "booked under investing" in m["reason"]
    assert OC.restate_row({"value": 0.2, "source": "s"}, m)["value"] == 0.2
    assert OC.measure(conn, "LLY", _file(tmp_path, ""))["reason"] == "no one-off cash stated for the window"


def test_rows_outside_the_window_and_in_another_unit_are_not_taken(tmp_path):
    conn = _db(tmp_path)
    m = OC.measure(conn, "MRK", _file(tmp_path, "MRK,2021,deal_payments,999,USD,a,\"q\",\n"
                                                 "MRK,2024,legal_settlement,100,USD,a,\"q\",\n"))
    assert m["deals"] == 0 and m["settlements"] == 100
    mixed = OC.measure(conn, "MRK", _file(tmp_path, "MRK,2024,legal_settlement,100,EUR,a,\"q\",\n"
                                                     "MRK,2025,legal_settlement,50,USD,a,\"q\",\n"))
    assert mixed["settlements"] == 50 and mixed["left_out"] == ["100mm EUR of legal settlement in 2024, printed only in EUR"]
    assert "Left out: 100mm EUR" in OC.restate_row({"value": 0.1, "source": "s"}, mixed)["source"]


def test_only_stated_instalments_count_as_transition_tax_paid(tmp_path):
    """Merck's 2024 balance is net of foreign tax credits, so a fall in the balance is not
    cash; the instalment is added back gross, since it is a tax."""
    conn = _db(tmp_path)
    m = OC.measure(conn, "MRK", _file(tmp_path, "MRK,2022,transition_tax_liability,2200,USD,a,\"q\",\n"
                                                 "MRK,2024,transition_tax_liability,518,USD,a,\"q\",\n"
                                                 "MRK,2025,transition_tax,1200,USD,a,\"q\",\n"))
    assert m["transition"] == 1200 and m["transition_basis"] == "2025 instalment 1,200mm"
    assert m["cut"] == pytest.approx(1200e6 / 189294e6 / (1 - 0.1331))
