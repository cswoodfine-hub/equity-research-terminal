"""A derived catalyst names the asset of the trial it came from, after any rebuild.

The daily job builds its database from nothing: it loads the exported history, which
carries catalysts but not assets, and the refresh then numbers the assets afresh. A
restored catalyst kept the id it was derived with, and ``derive_readouts`` refreshed its
date and title but never its asset, so a Roche Tecentriq readout ended up on whatever
asset drew its old number, which on 2026-09-25 was Lilly's Humatrope. Lilly's catalyst
stakes then listed Roche's readouts.
"""

import datetime as dt

import catalysts
import db

LLY, ROG = 1, 10

# The user-visible check: a catalyst on another company's asset.
FOREIGN = """SELECT COUNT(*) FROM catalysts k JOIN assets a ON a.id = k.asset_id
              WHERE a.owner_company_id <> k.company_id"""


def _companies(conn):
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (?, 'LLY', 'Lilly')",
                 (LLY,))
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (?, 'ROG', 'Roche')",
                 (ROG,))


def _asset(conn, owner, brand):
    return conn.execute(
        "INSERT INTO assets (owner_company_id, brand_name, is_marketed) VALUES (?, ?, 1)",
        (owner, brand)).lastrowid


def _trial(conn, nct, asset_id, due):
    conn.execute(
        "INSERT INTO trials (nct_id, sponsor_company_id, asset_id, title, phase,"
        " overall_status, primary_completion_date) VALUES (?, ?, ?, 'A study',"
        " 'Phase 3', 'Recruiting', ?)", (nct, ROG, asset_id, due))


def _one(path, sql, *args):
    conn = db.get_connection(path)
    try:
        return conn.execute(sql, args).fetchone()
    finally:
        conn.close()


def test_a_derived_row_already_on_the_wrong_asset_is_repointed(tmp_path):
    """The state the 2026-09-25 database is in: the rebuild has already happened and
    the stale id is stored. The next derivation repairs it without anything refetched."""
    due = (dt.date.today() + dt.timedelta(days=120)).isoformat()
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    _companies(conn)
    humatrope = _asset(conn, LLY, "Humatrope")
    tecentriq = _asset(conn, ROG, "Tecentriq")
    _trial(conn, "NCT03148418", tecentriq, due)
    conn.execute("INSERT INTO catalysts (company_id, asset_id, catalyst_type,"
                 " expected_date, date_confidence, title, description, is_curated,"
                 " source_url, status) VALUES (?, ?, 'data readout', ?, 'estimated',"
                 " 'Phase 3, Tecentriq', 'NCT03148418', 0,"
                 " 'https://clinicaltrials.gov/study/NCT03148418', 'pending')",
                 (ROG, humatrope, due))
    conn.commit()
    conn.close()
    assert _one(path, FOREIGN)[0] == 1

    result = catalysts.derive_readouts(path)
    assert _one(path, FOREIGN)[0] == 0
    assert _one(path, "SELECT asset_id FROM catalysts")[0] == tecentriq
    assert (result["added"], result["updated"], result["reassigned"]) == (0, 1, 1)
    assert result["curated_mismatched"] == []

    # A trial that loses its mapping takes its readout's asset with it: null, not the
    # last one it had.
    conn = db.get_connection(path)
    conn.execute("UPDATE trials SET asset_id = NULL")
    conn.commit()
    conn.close()
    catalysts.derive_readouts(path)
    assert _one(path, "SELECT asset_id FROM catalysts")[0] is None
