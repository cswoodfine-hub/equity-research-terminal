"""Selling costs a filer tags under its own concept, put back into SG&A."""

import csv
import pathlib

import pytest

import db
import selling_costs as SC

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "fsds_num_nvo_costs.txt"
ADSH = "0000353278-26-000012"


def _rows():
    with FIXTURE.open(newline="", encoding="latin-1") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _db(tmp_path, sga):
    path = str(tmp_path / "sc.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'NVO', 'Novo Nordisk')")
    for metric, value in (("Revenues", 309064e6), ("SellingGeneralAndAdministrative", sga)):
        conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                     " period_end, value, unit) VALUES (1, ?, 'FY', 2025, '2025-12-31', ?, 'DKK')",
                     (metric, value))
    conn.commit()
    return conn


def test_the_extension_selling_line_is_read_consolidated_and_segment_rows_are_not():
    got = SC.parse_selling_costs(_rows(), ADSH)
    assert {y: v["value"] for y, v in got.items()} == {2023: 56743e6, 2024: 62101e6, 2025: 64310e6}
    assert got[2025]["tag"] == "SellingExpenseAndDistributionCosts" and got[2025]["unit"] == "DKK"


def test_only_a_selling_concept_counts():
    assert SC.is_selling_tag("SellingExpenseAndDistributionCosts", ADSH, ADSH)
    assert SC.is_selling_tag("DistributionCosts", "ifrs/2025", ADSH)
    assert not SC.is_selling_tag("SellingGeneralAndAdministrativeExpense", ADSH, ADSH)
    assert not SC.is_selling_tag("AdministrativeExpense", "ifrs/2025", ADSH)
    # An extension name is only trusted as an extension: the same spelling under a
    # standard taxonomy version is not a concept that exists.
    assert not SC.is_selling_tag("SalesAndDistributionCosts", "ifrs/2025", ADSH)


def test_sga_struck_on_administration_alone_takes_the_selling_line_and_the_charge_gives_it_up(tmp_path):
    conn = _db(tmp_path, 5969e6)
    filing = {"adsh": ADSH, "form": "20-F", "years": SC.parse_selling_costs(_rows(), ADSH)}
    m = SC.measure(conn, "NVO", filing, 2025, 0.0193)
    assert m["new"] == pytest.approx((5969 + 64310) / 309064)
    sga = SC.restate_sga({"value": 0.0193, "source": "NVO FY2025, from the filed lines"}, m)
    assert sga["value"] == pytest.approx(0.227393, abs=1e-6)
    assert "rises from 1.93% to 22.74%" in sga["source"] and ADSH in sga["source"]
    assert SC.restate_sga(sga, m) is None
    other = SC.restate_other({"value": 0.118922, "source": "derived: ..."}, m)
    assert other["value"] == 0.0 and "to nil" in other["source"]
    partial = SC.restate_other({"value": 0.30, "source": "s"}, m)
    assert partial["value"] == pytest.approx(0.30 - (m["new"] - 0.0193))


def test_a_seed_not_struck_on_the_sga_line_is_left_alone(tmp_path):
    conn = _db(tmp_path, 5969e6)
    filing = {"adsh": ADSH, "form": "20-F", "years": SC.parse_selling_costs(_rows(), ADSH)}
    m = SC.measure(conn, "NVO", filing, 2025, 0.2274)
    assert m["new"] is None and "not struck on the SG&A line" in m["reason"]
    assert SC.restate_sga({"value": 0.2274, "source": "s"}, m) is None
    assert SC.measure(conn, "NVO", None, 2025, 0.0193)["new"] is None
