"""The cost of debt comes out of the other-costs charge exactly once."""

import pytest

import db
import interest_addback as IA


def _db(tmp_path, rows):
    path = str(tmp_path / "ia.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'PFE', 'Pfizer'),"
                 " (2, 'GSK', 'GSK'), (3, 'INCY', 'Incyte')")
    for cid, metric, year, value, unit in rows:
        conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                     " period_end, value, unit) VALUES (?, ?, 'FY', ?, ?, ?, ?)",
                     (cid, metric, year, f"{year}-12-31", value, unit))
    conn.commit()
    return conn


PFE = [(1, "Revenues", 2023, 59.55e9, "USD"), (1, "Revenues", 2024, 63.63e9, "USD"),
       (1, "Revenues", 2025, 62.58e9, "USD"),
       (1, "InterestPaidOperating", 2023, 2.215e9, "USD"),
       (1, "InterestPaidOperating", 2024, 3.227e9, "USD"),
       (1, "InterestPaidOperating", 2025, 2.739e9, "USD")]


def test_the_charge_falls_by_interest_over_revenue_across_the_window(tmp_path):
    conn = _db(tmp_path, PFE)
    m = IA.measure(conn, "PFE")
    assert m["share"] == pytest.approx(8.181e9 / 185.76e9)
    assert IA.revised(0.22177, m["share"]) == pytest.approx(0.22177 - 8.181e9 / 185.76e9)
    assert IA.revised(0.0, m["share"]) == 0.0              # never below nil
    row = IA.restate_row({"value": "0.22177", "source": "derived: Pfizer generated ..."}, m, "Pfizer")
    assert row["value"] == pytest.approx(0.22177 - m["share"])
    assert "Restated before interest: Pfizer paid $8,181mm" in row["source"]
    assert "from 22.18% to" in row["source"]
    assert IA.restate_row(row, m) is None                  # idempotent


def test_financing_booked_interest_and_a_gap_leave_the_charge_standing(tmp_path):
    conn = _db(tmp_path, [
        (2, "Revenues", y, 30e9, "GBP") for y in (2023, 2024, 2025)] + [
        (2, "InterestPaidFinancing", y, 0.7e9, "GBP") for y in (2023, 2024, 2025)] + [
        (3, "Revenues", y, 4e9, "USD") for y in (2023, 2024, 2025)])
    gsk = IA.measure(conn, "GSK")
    assert gsk["share"] is None and gsk["booked"] == "financing"
    assert IA.revised(0.0144, gsk["share"]) == 0.0144
    assert "booked under financing" in IA.clause(gsk, 0.0144, 0.0144)
    incy = IA.measure(conn, "INCY")
    assert incy["share"] is None and "no interest paid on file" in incy["reason"]


def test_a_seed_file_changes_only_its_charge_lines(tmp_path):
    path = tmp_path / "pfe_x.csv"
    path.write_text("# a comment, kept\n"
                    "ticker,brand,indication,region,scenario,key,year,value,text_value,unit,source,note\n"
                    "PFE,X,,US,base,cogs_pct,,0.2567,,share of revenue,\"filed, lines\",\n"
                    "PFE,X,,US,base,other_costs_pct,,0.22177,,share of revenue,\"derived: a, b\",note\n")
    n = IA.rewrite_csv(path, lambda f: {**f, "value": 0.1777, "source": f["source"] + " restated"})
    text = path.read_text()
    assert n == 1
    assert "# a comment, kept" in text and '"filed, lines"' in text
    assert "PFE,X,,US,base,other_costs_pct,,0.1777,,share of revenue,\"derived: a, b restated\",note" in text


def test_a_seed_file_keeps_its_line_endings(tmp_path):
    path = tmp_path / "crlf.csv"
    path.write_bytes(b"# c\r\nticker,brand,indication,region,scenario,key,year,value,text_value,unit,source,note\r\n"
                     b"PFE,X,,US,base,cogs_pct,,0.25,,u,s,\r\n"
                     b"PFE,X,,US,base,other_costs_pct,,0.2,,u,s,\r\n")
    IA.rewrite_csv(path, lambda f: {**f, "value": 0.1})
    raw = path.read_bytes()
    assert raw.count(b"\r\n") == 4 and b"\n" not in raw.replace(b"\r\n", b"")
    assert b"PFE,X,,US,base,cogs_pct,,0.25,,u,s,\r\n" in raw


def test_a_fiscal_year_filed_twice_is_counted_once(tmp_path):
    """J&J's FY2023 is on file ending 2023-12-31 and 2024-01-01. Summing both overstated
    the window's revenue and interest; the latest-dated row is the year."""
    conn = _db(tmp_path, PFE)
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                 " period_end, value, unit) VALUES (1, 'Revenues', 'FY', 2023, '2023-12-30',"
                 " 99e9, 'USD'), (1, 'InterestPaidOperating', 'FY', 2023, '2023-12-30', 9e9, 'USD')")
    conn.commit()
    assert IA.measure(conn, "PFE")["share"] == pytest.approx(8.181e9 / 185.76e9)
