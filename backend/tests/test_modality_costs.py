"""Cost of sales by what kind of product it is, normalised so the company total stands."""

from __future__ import annotations

import db
import modality_costs as MC


def _db(tmp_path, products):
    """A company with the given (brand, modality, generic, FY revenue) products."""
    path = str(tmp_path / "mod.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'TST', 'Test')")
    for index, (brand, modality, generic, revenue) in enumerate(products, start=10):
        conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, modality,"
                     " generic_name, is_marketed) VALUES (?, 1, ?, ?, ?, 1)",
                     (index, brand, modality, generic))
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value,"
                     " unit, source) VALUES (?, 2025, 'FY', ?, 'USD', 't')",
                     (index, revenue))
    conn.commit()
    return conn


def test_a_biologic_stays_a_biologic_whatever_its_name_ends_in():
    assert MC.classify("biologic", "dulaglutide") == "biologic"
    assert MC.classify("small molecule", "semaglutide") == "peptide"
    assert MC.classify("small molecule", "tirzepatide") == "peptide"
    assert MC.classify("small molecule", "abrocitinib") == "small molecule"
    assert MC.classify(None, None) == ""


def test_a_peptide_and_an_untagged_product_are_not_measured():
    assert MC.rate_for("biologic") == MC.BIOLOGIC_RATE
    assert MC.rate_for("small molecule") == MC.SMALL_MOLECULE_RATE
    assert MC.rate_for("small molecule", "semaglutide") is None
    assert MC.rate_for(None) is None


def test_the_factors_leave_the_companys_blended_ratio_where_it_was(tmp_path):
    conn = _db(tmp_path, [("Bio", "biologic", "anymab", 5e9),
                          ("Pill", "small molecule", "anynib", 5e9)])
    factors = MC.factors(conn, 1)
    shares = MC.mix(conn, 1)
    weighted = sum(shares[m] * factors[m] for m in factors)
    assert round(weighted, 9) == 1.0
    # Half and half, so the biologic carries more and the pill less, by the measured ratio.
    assert factors["biologic"] / factors["small molecule"] == \
        MC.BIOLOGIC_RATE / MC.SMALL_MOLECULE_RATE
    assert factors["biologic"] > 1 > factors["small molecule"]
    conn.close()


def test_a_peptide_keeps_the_blend_and_does_not_move_anyone_else(tmp_path):
    """Lilly is mostly peptide. The peptide takes no factor, and the factors on what was
    measured are normalised over the measured part alone."""
    conn = _db(tmp_path, [("Peptide", "small molecule", "tirzepatide", 8e9),
                          ("Bio", "biologic", "anymab", 1e9),
                          ("Pill", "small molecule", "anynib", 1e9)])
    factors = MC.factors(conn, 1)
    assert "peptide" not in factors
    measured = {m: s for m, s in MC.mix(conn, 1).items() if m in factors}
    weight = sum(measured.values())
    assert round(sum(measured[m] * factors[m] for m in factors) / weight, 9) == 1.0

    moved, why = MC.for_asset(conn, 1, "small molecule", 0.17, "tirzepatide")
    assert moved is None and why is None            # the peptide is left alone
    moved, why = MC.for_asset(conn, 1, "biologic", 0.17, "anymab")
    assert moved > 0.17 and "biologic at" in why
    conn.close()


def test_nothing_moves_without_a_mix_or_a_ratio(tmp_path):
    conn = _db(tmp_path, [("Pill", None, "anynib", 1e9)])
    assert MC.factors(conn, 1) == {}
    assert MC.for_asset(conn, 1, "biologic", 0.25) == (None, None)
    assert MC.for_asset(conn, 1, "small molecule", None) == (None, None)
    conn.close()


def test_a_book_of_one_kind_is_not_reshuffled(tmp_path):
    """Every product the same class means the blend already is that class's rate."""
    conn = _db(tmp_path, [("A", "small molecule", "anynib", 1e9),
                          ("B", "small molecule", "anyvir", 2e9)])
    assert round(MC.factors(conn, 1)["small molecule"], 9) == 1.0
    moved, _ = MC.for_asset(conn, 1, "small molecule", 0.25, "anynib")
    assert round(moved, 9) == 0.25
    conn.close()
