"""What became of each catalyst, and the rules that decide it, each pinned by a case."""

import datetime as dt

import catalyst_outcomes as CO
import db

TODAY = dt.date(2026, 11, 7)


def _book(tmp_path):
    path = str(tmp_path / "c.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AAA', 'AAA')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name, is_marketed)"
                 " VALUES (10, 1, 'Rhapsido', 'remibrutinib', 0)")
    conn.commit()
    return path, conn


def _catalyst(conn, cid, kind, due, title, description=None, asset_id=10):
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type, expected_date,"
                 " date_confidence, title, description, status) VALUES (?, 1, ?, ?, ?, 'confirmed', ?, ?, 'pending')",
                 (cid, asset_id, kind, due, title, description))
    conn.commit()


def test_a_pdufa_resolves_met_on_an_approval_row_and_is_dated_by_the_approval(tmp_path):
    """Zilganersen: approved 2026-09-03 under NDA220210, PDUFA due 2026-09-22, and the
    resolution date call_log reads must be the approval's, not the resolver's."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "PDUFA", "2026-09-22", "Zilganersen PDUFA")
    conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date, application_number, source)"
                 " VALUES (10, 'US', 'FDA', '2026-09-03', 'NDA220210', 'openfda')")
    conn.commit()
    assert CO.resolve(path, today=TODAY)["met"] == 1
    row = conn.execute("SELECT status, updated_at FROM catalysts WHERE id = 1").fetchone()
    assert row["status"] == "met" and row["updated_at"] == "2026-09-03"
    led = CO.ledger(path)[0]
    assert led["source"] == "approvals" and "NDA220210" in led["evidence"]


def test_a_superseded_pdufa_is_slipped_and_names_its_successor(tmp_path):
    """Deramiocel: due 2026-08-22 on three rows, the extension to 2026-11-22 arrived as a
    fourth. The old rows slip; the successor stays pending and is never touched."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "PDUFA", "2026-08-22", "Deramiocel PDUFA")
    _catalyst(conn, 2, "PDUFA", "2026-11-22", "Deramiocel PDUFA, extended")
    got = CO.resolve(path, today=TODAY)
    assert got["slipped"] == 1 and got["open"] == 0
    assert conn.execute("SELECT status FROM catalysts WHERE id = 1").fetchone()[0] == "slipped"
    assert conn.execute("SELECT status FROM catalysts WHERE id = 2").fetchone()[0] == "pending"
    assert "catalyst 2" in CO.ledger(path)[0]["evidence"]


def test_a_regulatory_catalyst_with_no_approval_is_never_missed(tmp_path):
    """There is no free register of complete response letters, so an absent approval is
    unknown after the grace period, not a refusal the book did not read."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "PDUFA", "2026-08-01", "Something PDUFA")
    got = CO.resolve(path, today=TODAY)
    assert got["unknown"] == 1 and got["missed"] == 0


def test_a_readout_resolves_on_an_announced_result_matched_on_drug_and_phase(tmp_path):
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-11-03", "Phase 3, Rhapsido", "NCT05677451")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date)"
                 " VALUES ('0001-26-1', 1, 'remibrutinib', 3, 'negative', '2026-11-04')")
    # A same-company Phase 2 result for another drug must not resolve this one.
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date)"
                 " VALUES ('0001-26-2', 1, 'otherdrug', 2, 'positive', '2026-11-04')")
    conn.commit()
    got = CO.resolve(path, today=TODAY)
    assert got["missed"] == 1 and got["met"] == 0
    assert conn.execute("SELECT updated_at FROM catalysts WHERE id = 1").fetchone()[0] == "2026-11-04"


def test_a_registry_slip_is_logged_and_the_row_stays_pending(tmp_path):
    """derive_readouts updates a derived readout in place when the registry moves its
    date, so a terminal status here would block its own successor."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-10-15", "Phase 3, Rhapsido", "NCT1")
    conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, title, phase, overall_status,"
                 " primary_completion_date) VALUES ('NCT1', 1, 'T', 'Phase 3', 'Recruiting', '2027-03-31')")
    conn.commit()
    got = CO.resolve(path, today=TODAY)
    assert got["slipped"] == 1
    assert conn.execute("SELECT status FROM catalysts WHERE id = 1").fetchone()[0] == "pending"
    assert "2027-03-31" in CO.ledger(path)[0]["evidence"]
    # Idempotent: the same slip is not logged twice.
    assert CO.resolve(path, today=TODAY)["slipped"] == 0


def test_a_window_still_open_is_left_alone(tmp_path):
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-11", "Phase 3, Rhapsido", "NCT1")   # the month is open
    assert CO.resolve(path, today=TODAY) == {"met": 0, "missed": 0, "slipped": 0, "unknown": 0, "open": 0}
    assert conn.execute("SELECT status FROM catalysts WHERE id = 1").fetchone()[0] == "pending"


def test_a_readout_that_fits_two_pending_catalysts_resolves_neither(tmp_path):
    """GSK had three pending Jemperli Phase 2 readouts and one announced result. The
    announcement carries no trial id, so it fits all three, and resolving any is a guess."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-10-01", "Phase 2, Rhapsido", "NCT1")
    _catalyst(conn, 2, "data readout", "2026-10-15", "Phase 2, Rhapsido", "NCT2")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date)"
                 " VALUES ('0001-26-9', 1, 'remibrutinib', 2, 'positive', '2026-10-03')")
    conn.commit()
    got = CO.resolve(path, today=TODAY)
    assert got["met"] == 0 and got["missed"] == 0
    assert {r["status"] for r in conn.execute("SELECT status FROM catalysts")} == {"pending"}
    assert any(r["outcome"] == "ambiguous" for r in CO.ledger(path))
