"""The other-costs charge below nil, bounded by amortisation inside the cost lines."""

import pytest

import charge_floor as CF
import db
import interest_addback as IA
import one_off_cash as OC
import replacement_capex as RC


def _db(tmp_path, ticker, cfo, capex, cogs=0.2976, sga=0.2291, rd=0.1487, tax=0.1081):
    path = str(tmp_path / "cf.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, ?, 'X')", (ticker,))
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed) VALUES (1, 1, 'x', 1)")
    for key, value in (("cogs_pct", cogs), ("sga_pct", sga), ("rd_pct", rd), ("tax_rate", tax), ("other_costs_pct", 0.0)):
        conn.execute("INSERT INTO assumptions (asset_id, key, value, source) VALUES (1, ?, ?, 's')", (key, value))
    for metric, value in (("Revenues", 61160e6), ("CashFlowOperating", cfo), ("CapitalExpenditure", capex)):
        conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                     " VALUES (1, ?, 'FY', 2025, '2025-12-31', ?, 'USD')", (metric, value))
    conn.commit()
    return conn


@pytest.fixture
def plain(monkeypatch):
    """The three restatements off, so the rebuild is the free cash margin alone."""
    for module, key in ((IA, "share"), (RC, "cut"), (OC, "cut")):
        monkeypatch.setattr(module, "measure", lambda conn, t, *a, _k=key, **kw: {_k: None})


def _amort(tmp_path, where, amount="7377"):
    path = tmp_path / "amort.csv"
    path.write_text("# c\nticker,fiscal_year,amount,unit,presented_in,accession,quote,note\n"
                    f"ABBV,2025,{amount},USD,{where},0001551152-26-000008,\"q\",\n")
    return path


def test_a_nil_charge_falls_to_the_rebuilt_figure_inside_the_amortisation_floor(tmp_path, plain):
    conn = _db(tmp_path, "ABBV", cfo=22000e6, capex=1214e6)       # cash margin above the book
    m = CF.measure(conn, "ABBV", _amort(tmp_path, "cost_of_sales"))
    book = 1 - 0.2976 - 0.2291 - 0.1487
    cash = (22000e6 - 1214e6) / 61160e6 / (1 - 0.1081)
    assert m["rebuilt"] == pytest.approx(book - cash) and -0.1206 < m["rebuilt"] < 0
    assert m["new"] == pytest.approx(book - cash)
    row = CF.restate_row({"value": 0.0, "source": "derived: ..."}, m)
    assert row["value"] == pytest.approx(book - cash)
    assert "Restated to the amortisation floor" in row["source"] and "$7,377mm" in row["source"] and "takes the rebuilt figure" in row["source"]
    assert CF.restate_row(row, m) is None


def test_the_charge_stops_at_the_amortisation_floor(tmp_path, plain):
    conn = _db(tmp_path, "ABBV", cfo=30000e6, capex=1000e6)
    m = CF.measure(conn, "ABBV", _amort(tmp_path, "cost_of_sales", amount="2000"))
    assert m["new"] == pytest.approx(-2000e6 / 61160e6)
    assert "stops at that floor" in CF.restate_row({"value": 0.0, "source": "s"}, m)["source"]


def test_amortisation_on_its_own_line_or_a_charge_above_nil_changes_nothing(tmp_path, plain):
    conn = _db(tmp_path, "ABBV", cfo=22000e6, capex=1214e6)
    separate = CF.measure(conn, "ABBV", _amort(tmp_path, "separate_line"))
    assert separate["new"] is None and "outside the cost lines" in separate["reason"]
    other = tmp_path / "low_cash"
    other.mkdir()
    low_cash = _db(other, "ABBV", cfo=15000e6, capex=1214e6)
    m = CF.measure(low_cash, "ABBV", _amort(tmp_path, "cost_of_sales"))
    assert m["new"] is None and "at or above nil" in m["reason"]
    assert CF.restate_row({"value": 0.05, "source": "s"}, {**m, "new": -0.02}) is None
