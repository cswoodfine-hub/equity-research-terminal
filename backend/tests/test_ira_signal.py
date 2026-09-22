"""Medicare price negotiation: the one policy fact that reaches a named asset exactly.

CMS publishes the brand, so this binds to a company without a guess. Everything below
is about not letting that exactness turn into a claim the data cannot support.
"""

import pytest

import db
import diff
import ira
import market_signals as MS


def _seed(tmp_path, name="ira.db", rows=(), assets=(), demand=(), revenue=None):
    path = str(tmp_path / name)
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, 'BMY', 'Bristol Myers', 'USD')")
    for asset_id, brand in assets:
        conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                     " VALUES (?, 1, ?, 1)", (asset_id, brand))
    for drug, ipay, ndc9, mfp, eff_from, eff_to, kind in rows:
        conn.execute(
            """INSERT INTO negotiated_prices (drug, ipay, ndc9, mfp_30des,
                   effective_from, effective_to, update_kind, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'cms')""",
            (drug, ipay, ndc9, mfp, eff_from, eff_to, kind))
    for asset_id, year, spending, claims in demand:
        conn.execute(
            "INSERT INTO drug_demand (asset_id, part, year, total_spending,"
            " total_claims) VALUES (?, 'D', ?, ?, ?)",
            (asset_id, year, spending, claims))
    if revenue is not None:
        conn.execute("INSERT INTO financials (company_id, metric, period_type,"
                     " fiscal_year, period_end, value, unit) VALUES"
                     " (1, 'Revenues', 'FY', 2025, '2025-12-31', ?, 'USD')", (revenue,))
    conn.commit()
    return conn


def test_a_multi_brand_string_becomes_one_row_per_brand():
    """CMS puts several trade names in one cell. Each is a product a reader looks up."""
    assert ira.brands("OZEMPIC; RYBELSUS; WEGOVY") == ["OZEMPIC", "RYBELSUS", "WEGOVY"]
    assert ira.brands("ELIQUIS") == ["ELIQUIS"]
    assert ira.brands("") == []


def test_every_selection_year_survives_not_just_the_first(tmp_path):
    """CMS reselects, so a drug can appear again for a later year at a new price. The
    ipay used to be taken as the first one found per drug, which is right only for as
    long as no drug spans two cycles."""
    conn = _seed(tmp_path, rows=(
        ("ELIQUIS", 2026, "111", 237.25, "2026-01-01", None, "New IPAY"),
        ("ELIQUIS", 2028, "111", 200.00, "2028-01-01", None, "New IPAY"),
    ), assets=((1, "ELIQUIS"),))
    got = ira.selected(conn)
    conn.close()
    assert sorted(r["ipay"] for r in got) == [2026, 2028]
    assert {r["brand"] for r in got} == {"ELIQUIS"}
    assert {r["mfp_30des"] for r in got} == {237.25, 200.00}


def test_a_drug_the_book_does_not_model_is_reported_without_an_asset(tmp_path):
    """A brand CMS names that nothing here models is a real gap, not a row to drop."""
    conn = _seed(tmp_path, rows=(
        ("SOMETHING", 2026, "111", 10.0, "2026-01-01", None, "New IPAY"),
    ))
    got = ira.selected(conn)
    conn.close()
    assert len(got) == 1 and got[0]["asset_id"] is None and got[0]["ticker"] is None


def test_one_asset_with_several_brands_is_counted_once(tmp_path):
    """Ozempic, Rybelsus and Wegovy are one asset. Counting Part D spending per brand
    would multiply the exposure by the number of trade names."""
    conn = _seed(tmp_path, rows=(
        ("OZEMPIC; RYBELSUS", 2027, "111", 100.0, "2027-01-01", None, "New IPAY"),
    ), assets=((1, "OZEMPIC"), (2, "RYBELSUS")),
        demand=((1, 2024, 1e9, 1e6), (2, 2024, 5e8, 5e5)), revenue=10e9)
    got = ira.company_exposure(conn, "BMY", rates={})
    conn.close()
    assert got["brands"] == 2 and got["assets"] == 2
    # Two distinct assets here, so both count: 1.5bn of 10bn.
    assert got["part_d_spending"] == pytest.approx(1.5e9)
    assert got["share"] == pytest.approx(0.15)


def test_an_asset_with_no_part_d_row_is_counted_as_a_gap_not_a_zero(tmp_path):
    conn = _seed(tmp_path, rows=(
        ("ELIQUIS; POMALYST", 2026, "111", 10.0, "2026-01-01", None, "New IPAY"),
    ), assets=((1, "ELIQUIS"), (2, "POMALYST")),
        demand=((1, 2024, 2e9, 1e6),), revenue=10e9)
    got = ira.company_exposure(conn, "BMY", rates={})
    conn.close()
    assert got["assets_without_part_d"] == 1
    assert got["share"] == pytest.approx(0.20)       # a floor, not the whole figure


def test_the_note_stays_quiet_under_the_gate(tmp_path):
    """A selected drug is a fact for the feed whatever its size. A paragraph in a
    morning note needs the exposure to be worth a reader's attention."""
    conn = _seed(tmp_path, rows=(
        ("ELIQUIS", 2026, "111", 10.0, "2026-01-01", None, "New IPAY"),
    ), assets=((1, "ELIQUIS"),), demand=((1, 2024, 5e6, 1e5),), revenue=10e9)
    got = ira.company_exposure(conn, "BMY", rates={})
    assert got["share"] == pytest.approx(0.0005)     # 0.05%, under the 1% gate
    assert ira.sentence(conn, "BMY", 2026) is None
    conn.close()
    assert ira.NOTE_GATE == 0.01


def test_the_note_says_what_the_share_is_and_is_not(tmp_path):
    conn = _seed(tmp_path, rows=(
        ("ELIQUIS", 2026, "111", 10.0, "2026-01-01", None, "New IPAY"),
    ), assets=((1, "ELIQUIS"),), demand=((1, 2024, 2e9, 1e6),), revenue=10e9)
    said = ira.sentence(conn, "BMY", 2026)
    conn.close()
    assert "CMS lists 1 BMY drug for IPAY 2026: ELIQUIS" in said
    assert "20.0% of its latest reported revenue" in said
    # The caveat is not optional: gross at list against net revenue.
    assert "not revenue at risk" in said
    assert "confidential" in said


def test_a_deselection_is_taken_from_the_column_not_from_prose(tmp_path):
    """The file end dates a row for three different reasons. update_kind separates a
    deselection from the annual inflation rebasing directly."""
    conn = _seed(tmp_path, rows=(
        ("ELIQUIS", 2026, "111", 10.0, "2026-01-01", "2026-12-31", "Deselect"),
        ("POMALYST", 2027, "222", 20.0, "2027-01-01", "2027-12-31", "Inflation"),
        ("ORENCIA", 2028, "333", 30.0, "2028-01-01", "2028-12-31", "End Date"),
    ), assets=((1, "ELIQUIS"), (2, "POMALYST"), (3, "ORENCIA")))
    got = ira.signals(conn)
    conn.close()
    assert [d["drug"] for d in got["deselections"]] == ["ELIQUIS"]
    assert ira.DESELECT_KIND == "Deselect"


def test_a_deselection_writes_a_review_row_and_no_loe_date(tmp_path):
    """The curated file owns a deselection date, because a date there moves an erosion
    clock and so moves modelled revenue. This lane only asks for a look."""
    conn = _seed(tmp_path, rows=(
        ("ELIQUIS", 2026, "111", 10.0, "2026-01-01", None, "New IPAY"),
    ), assets=((1, "ELIQUIS"),))
    assert diff._diff_ira(conn, None) == 0            # first pass baselines
    conn.commit()
    conn.execute("INSERT INTO negotiated_prices (drug, ipay, ndc9, effective_from,"
                 " effective_to, update_kind, source) VALUES ('ELIQUIS', 2026, '112',"
                 " '2026-01-01', '2026-12-31', 'Deselect', 'cms')")
    conn.commit()
    assert diff._diff_ira(conn, None) == 1
    conn.commit()
    row = conn.execute("SELECT entity_type, change_type, new_value FROM changes"
                       " WHERE change_type = 'ira_deselected'").fetchone()
    assert row["entity_type"] == "policy"
    assert "Review" in row["new_value"]
    # Nothing was written anywhere an LOE is read from.
    assert conn.execute("SELECT COUNT(*) FROM changes"
                        " WHERE change_type LIKE '%loe%'").fetchone()[0] == 0
    conn.close()


def test_the_first_pass_baselines_and_the_rerun_is_quiet(tmp_path):
    """Installing the terminal must not announce three years of past selections. The
    state table is shared with the rate signals, so the test is whether this lane has
    run, not whether the table is empty."""
    conn = _seed(tmp_path, rows=(
        ("ELIQUIS", 2026, "111", 10.0, "2026-01-01", None, "New IPAY"),
        ("POMALYST", 2027, "222", 20.0, "2027-01-01", None, "New IPAY"),
    ), assets=((1, "ELIQUIS"), (2, "POMALYST")))
    # A rate signal has already anchored, which used to make this look like a re-run.
    MS.set_anchor(conn, "DGS10:25", 0.05, "2026-09-18")
    conn.commit()

    assert diff._diff_ira(conn, None) == 0
    conn.commit()
    assert diff._diff_ira(conn, None) == 0
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0] == 0

    # A genuinely new year for a company already baselined does flag.
    conn.execute("INSERT INTO negotiated_prices (drug, ipay, ndc9, mfp_30des,"
                 " effective_from, update_kind, source) VALUES ('ELIQUIS', 2028,"
                 " '113', 9.0, '2028-01-01', 'New IPAY', 'cms')")
    conn.commit()
    assert diff._diff_ira(conn, None) == 1
    conn.commit()
    row = conn.execute("SELECT new_value FROM changes").fetchone()
    assert "IPAY 2028" in row["new_value"]
    conn.close()


def test_the_ceiling_cut_is_a_bound_and_never_negative():
    assert ira.ceiling_cut(1000.0, 250.0) == pytest.approx(0.75)
    # A negotiated price above what Medicare already pays cuts nothing.
    assert ira.ceiling_cut(100.0, 250.0) == 0.0
    assert ira.ceiling_cut(None, 250.0) is None
    assert ira.ceiling_cut(1000.0, None) is None


def test_the_bound_and_the_exposure_are_never_multiplied(tmp_path):
    """Both are gross of rebates nobody publishes, so their product would be a loss
    estimate free data cannot support. The view carries them side by side."""
    conn = _seed(tmp_path, rows=(
        ("ELIQUIS", 2026, "111", 250.0, "2026-01-01", None, "New IPAY"),
    ), assets=((1, "ELIQUIS"),), demand=((1, 2024, 2e9, 2e6),), revenue=10e9)
    view = ira.company_view(conn, "BMY", rates={})
    conn.close()
    assert view["selected"][0]["ceiling_cut"] == pytest.approx(0.75)
    assert view["exposure"]["share"] == pytest.approx(0.20)
    assert "loss" not in str(view)
