"""Filing text stored, diffed into a change once, and read back with the passages that
moved. No network: the section text is seeded directly."""

import db
import diff
import filing_diff
import seed
from fetchers.filing_text_edgar import FilingTextEdgarFetcher

_PRIOR = (
    "You should carefully consider the following risks in evaluating the company.\n"
    "A small number of products account for most of the company's revenue today.\n"
    "Patent expiration would allow generic competition and reduce product revenue.")
_CURRENT = _PRIOR + (
    "\nA new government drug pricing law could materially lower the prices we charge.")


def _seed(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    lly = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    for accession, filed, text in (
            ("0001-24-000010", "2025-02-19", _PRIOR),
            ("0001-25-000010", "2026-02-18", _CURRENT)):
        conn.execute(
            "INSERT INTO filing_sections (company_id, accession, form_type, filed_date,"
            " section, char_count, text) VALUES (?, ?, '10-K', ?, 'risk_factors', ?, ?)",
            (lly, accession, filed, len(text), text))
    conn.commit()
    conn.close()
    return lly


def _fs_count(db_file):
    conn = db.get_connection(db_file)
    try:
        return conn.execute("SELECT COUNT(*) FROM filing_sections").fetchone()[0]
    finally:
        conn.close()


def test_diff_emits_one_risk_factors_change_and_is_idempotent(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    conn = db.get_connection(db_file)
    try:
        emitted = diff._diff_filing_text(conn, None)
        conn.commit()
        assert emitted == 1
        row = conn.execute(
            "SELECT entity_type, entity_key, field, change_type, significance, new_value"
            " FROM changes WHERE change_type = 'risk_factors_change'").fetchone()
        assert row["entity_type"] == "filing"
        assert row["entity_key"] == "0001-25-000010"      # keyed on the newer filing
        assert row["field"] == "risk_factors"
        assert row["new_value"].startswith("LLY risk factors changed: 1 added")

        # A second pass sees the change is already recorded and emits nothing.
        assert diff._diff_filing_text(conn, None) == 0
    finally:
        conn.close()


def test_no_prior_of_a_form_emits_nothing(tmp_path):
    db_file = tmp_path / "t.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    lly = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    conn.execute(
        "INSERT INTO filing_sections (company_id, accession, form_type, filed_date,"
        " section, char_count, text) VALUES (?, 'a', '10-K', '2026-02-18',"
        " 'risk_factors', 10, 'only one filing so nothing to compare it against yet')",
        (lly,))
    conn.commit()
    try:
        assert diff._diff_filing_text(conn, None) == 0     # a single filing baselines
    finally:
        conn.close()


def test_company_filing_diff_returns_added_passages(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    sections = filing_diff.company_filing_diff(db_file, "LLY")
    risk = next(s for s in sections if s["form"] == "10-K"
                and s["section"] == "risk_factors")
    assert risk["added"] == 1 and risk["removed"] == 0
    assert risk["prior_date"] == "2025-02-19"
    assert "government drug pricing law" in risk["added_passages"][0]


def test_fetcher_upsert_is_idempotent_on_accession_section(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    before = _fs_count(db_file)
    rows = [{"company_id": 1, "accession": "0001-25-000010", "form_type": "10-K",
             "filed_date": "2026-02-18", "section": "risk_factors", "text": _CURRENT}]
    # The section is already stored, so re-upserting it writes nothing.
    assert FilingTextEdgarFetcher("LLY", db_file).upsert(rows).rows_fetched == 0
    assert _fs_count(db_file) == before
