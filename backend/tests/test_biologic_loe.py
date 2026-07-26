"""Biologic LOE: the 12-year floor, the guarded 10-K extraction, and the derivation that
takes the later of the two. The model is faked, so no network."""

import datetime as dt
import json

import biologic_loe
import db
import seed


# --- the floor and the extractor --------------------------------------------
def test_statutory_floor_is_approval_year_plus_twelve():
    assert biologic_loe.statutory_floor_year("2014-09-04") == 2026
    assert biologic_loe.statutory_floor_year(None) is None
    assert biologic_loe.statutory_floor_year("not a date") is None


_DOC = ("Our results depend on a few products. The Company expects that sales of "
        "Keytruda will be materially negatively impacted by biosimilar competition "
        "between 2028 and 2029. Other products face their own risks.")


def test_extract_disclosed_keeps_only_verified_findings():
    def complete(system, user, max_tokens=900):
        return json.dumps({"findings": [
            # good: brand asked for, year in a quote that is in the document
            {"brand": "Keytruda", "year": 2028,
             "quote": "The Company expects that sales of Keytruda will be materially "
                      "negatively impacted by biosimilar competition between 2028 and 2029."},
            # a brand we did not ask about
            {"brand": "Humira", "year": 2030, "quote": "Humira faces competition in 2030."},
            # a year the quote does not contain
            {"brand": "Winrevair", "year": 2040,
             "quote": "The Company expects that sales of Keytruda will be impacted."},
        ]})
    names = {"Keytruda": "Keytruda", "Winrevair": "Winrevair"}
    got = biologic_loe.extract_disclosed(_DOC, names, complete)
    assert set(got) == {"Keytruda"}
    assert got["Keytruda"]["year"] == 2028


def test_extract_disclosed_matches_generic_names_and_keeps_the_latest_year():
    # A patent table names the product by its generic and gives several years; the finding
    # resolves to the brand and the latest year wins, since protection runs until then.
    doc = ("Patents covering pembrolizumab expire in 2028 in the United States. "
           "Additional patents covering pembrolizumab expire in 2032.")
    names = {"Keytruda": "Keytruda", "pembrolizumab": "Keytruda"}

    def complete(system, user, max_tokens=900):
        return json.dumps({"findings": [
            {"brand": "pembrolizumab", "year": 2028,
             "quote": "Patents covering pembrolizumab expire in 2028 in the United States."},
            {"brand": "pembrolizumab", "year": 2032,
             "quote": "Additional patents covering pembrolizumab expire in 2032."}]})
    got = biologic_loe.extract_disclosed(doc, names, complete)
    assert got == {"Keytruda": {"year": 2032,
                                "quote": "Additional patents covering pembrolizumab "
                                         "expire in 2032."}}


def test_extract_disclosed_without_a_model_is_empty(monkeypatch):
    monkeypatch.setattr(biologic_loe.llm, "provider", lambda: None)
    assert biologic_loe.extract_disclosed(_DOC, {"Keytruda": "Keytruda"}) == {}


# --- the derivation ---------------------------------------------------------
def _seed(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    mrk = conn.execute("SELECT id FROM companies WHERE ticker='MRK'").fetchone()[0]

    def biologic(brand, approval):
        aid = conn.execute(
            "INSERT INTO assets (owner_company_id, brand_name, modality, is_marketed)"
            " VALUES (?, ?, 'biologic', 1)", (mrk, brand)).lastrowid
        conn.execute("INSERT INTO approvals (asset_id, application_number, approval_date)"
                     " VALUES (?, ?, ?)", (aid, f"BLA{aid}", approval))
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, value, unit)"
                     " VALUES (?, 2025, 1000000000, 'USD')", (aid,))
        return aid

    keytruda = biologic("Keytruda", "2014-09-04")     # floor 2026, disclosed 2028
    winrevair = biologic("Winrevair", "2024-03-26")   # floor 2036, no disclosure
    conn.execute(
        "INSERT INTO filing_sections (company_id, accession, form_type, filed_date,"
        " section, char_count, text) VALUES (?, 'acc1', '10-K', '2026-02-20',"
        " 'risk_factors', ?, ?)", (mrk, len(_DOC), _DOC))
    conn.commit()
    conn.close()
    return keytruda, winrevair


def test_derive_takes_the_later_of_floor_and_disclosure(tmp_path):
    db_file = tmp_path / "t.db"
    keytruda, winrevair = _seed(db_file)

    def complete(system, user, max_tokens=900):
        return json.dumps({"findings": [{"brand": "Keytruda", "year": 2028,
            "quote": "The Company expects that sales of Keytruda will be materially "
                     "negatively impacted by biosimilar competition between 2028 and 2029."}]})

    summary = biologic_loe.derive(db_file, complete=complete)
    assert summary["derived"] == 2 and summary["from_disclosure"] == 1

    conn = db.get_connection(db_file)
    try:
        rows = {r["asset_id"]: dict(r) for r in conn.execute(
            "SELECT asset_id, loe_year, floor_year, disclosed_year, basis, evidence"
            " FROM biologic_loe")}
    finally:
        conn.close()
    # Keytruda's floor (2026) has passed, so the disclosed 2028 governs, the later date.
    assert rows[keytruda]["loe_year"] == 2028
    assert rows[keytruda]["floor_year"] == 2026
    assert rows[keytruda]["basis"] == "10-K and statutory floor"
    assert "biosimilar competition" in rows[keytruda]["evidence"]
    # Winrevair has no disclosure, so it values on the floor alone.
    assert rows[winrevair]["loe_year"] == 2036
    assert rows[winrevair]["disclosed_year"] is None
    assert rows[winrevair]["basis"] == "statutory floor"


def test_derive_without_a_model_still_sets_the_floor(tmp_path, monkeypatch):
    db_file = tmp_path / "t.db"
    _, winrevair = _seed(db_file)
    monkeypatch.setattr(biologic_loe.llm, "provider", lambda: None)   # no model at all
    biologic_loe.derive(db_file, complete=None)
    # With no model the extractor is skipped, but the floor is still written for every
    # target, so a biologic values on the conservative date rather than not at all.
    conn = db.get_connection(db_file)
    try:
        row = conn.execute("SELECT loe_year, basis FROM biologic_loe WHERE asset_id = ?",
                           (winrevair,)).fetchone()
    finally:
        conn.close()
    assert row["loe_year"] == 2036 and row["basis"] == "statutory floor"
