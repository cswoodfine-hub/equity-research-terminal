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
    assert CO.resolve(path, today=TODAY, fetch=False)["met"] == 1
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
    got = CO.resolve(path, today=TODAY, fetch=False)
    assert got["slipped"] == 1 and got["open"] == 0
    assert conn.execute("SELECT status FROM catalysts WHERE id = 1").fetchone()[0] == "slipped"
    assert conn.execute("SELECT status FROM catalysts WHERE id = 2").fetchone()[0] == "pending"
    assert "catalyst 2" in CO.ledger(path)[0]["evidence"]


def test_a_regulatory_catalyst_with_no_approval_is_never_missed(tmp_path):
    """There is no free register of complete response letters, so an absent approval is
    unknown after the grace period, not a refusal the book did not read."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "PDUFA", "2026-08-01", "Something PDUFA")
    got = CO.resolve(path, today=TODAY, fetch=False)
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
    got = CO.resolve(path, today=TODAY, fetch=False)
    assert got["missed"] == 1 and got["met"] == 0
    assert conn.execute("SELECT updated_at FROM catalysts WHERE id = 1").fetchone()[0] == "2026-11-04"


def test_a_registry_slip_is_logged_and_the_row_stays_pending(tmp_path):
    """derive_readouts updates a derived readout in place when the registry moves its
    date, so a terminal status here would block its own successor."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-10-15", "Phase 3, Rhapsido", "NCT00000001")
    conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, title, phase, overall_status,"
                 " primary_completion_date) VALUES ('NCT00000001', 1, 'T', 'Phase 3', 'Recruiting', '2027-03-31')")
    conn.commit()
    got = CO.resolve(path, today=TODAY, fetch=False)
    assert got["slipped"] == 1
    assert conn.execute("SELECT status FROM catalysts WHERE id = 1").fetchone()[0] == "pending"
    assert "2027-03-31" in CO.ledger(path)[0]["evidence"]
    # Idempotent: the same slip is not logged twice.
    assert CO.resolve(path, today=TODAY, fetch=False)["slipped"] == 0


def test_a_window_still_open_is_left_alone(tmp_path):
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-11", "Phase 3, Rhapsido", "NCT00000001")   # the month is open
    assert CO.resolve(path, today=TODAY, fetch=False) == {"met": 0, "missed": 0, "slipped": 0, "unknown": 0, "open": 0}
    assert conn.execute("SELECT status FROM catalysts WHERE id = 1").fetchone()[0] == "pending"


def test_an_nct_named_in_the_announcement_resolves_that_sibling_alone(tmp_path):
    """Two pending Rhapsido Phase 2s; the announcement names one trial's NCT."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-10-01", "Phase 2, Rhapsido", "NCT00000001")
    _catalyst(conn, 2, "data readout", "2026-10-15", "Phase 2, Rhapsido", "NCT00000002")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date, quote)"
                 " VALUES ('A-1', 1, 'remibrutinib', 2, 'positive', '2026-10-03', 'The NCT00000002 study met its endpoint.')")
    conn.commit()
    got = CO.resolve(path, today=TODAY, fetch=False)
    assert got["met"] == 1
    assert conn.execute("SELECT status FROM catalysts WHERE id = 2").fetchone()[0] == "met"
    assert conn.execute("SELECT status FROM catalysts WHERE id = 1").fetchone()[0] == "pending"


def test_twin_studies_named_together_both_resolve_on_the_one_result(tmp_path):
    """REMODEL-1 and REMODEL-2 read out in a single Novartis release carrying one
    outcome. Each named sibling is closed on it; the unnamed third stays pending."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-07-21", "Phase 3, Rhapsido", "NCT05147220")
    _catalyst(conn, 2, "data readout", "2026-07-22", "Phase 3, Rhapsido", "NCT05156281")
    _catalyst(conn, 3, "data readout", "2026-10-15", "Phase 3, Rhapsido", "NCT00000003")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date, quote)"
                 " VALUES ('A-3', 1, 'remibrutinib', 3, 'positive', '2026-08-20',"
                 " 'REMODEL-1/-2 (NCT05147220, NCT05156281) met their primary endpoint.')")
    conn.commit()
    got = CO.resolve(path, today=TODAY, fetch=False)
    # The third's window has closed too, and the one announcement is spent on the twins
    # it names: it must not take it as its own on its turn, so it stays open.
    assert got["met"] == 2 and got["open"] == 1
    status = {r[0]: r[1] for r in conn.execute("SELECT id, status FROM catalysts")}
    assert status == {1: "met", 2: "met", 3: "pending"}
    led = CO.ledger(path)
    assert len(led) == 2 and all("read out together" in r["evidence"] for r in led)
    assert all(r["event_date"] == "2026-08-20" for r in led)


def test_an_unknown_readout_names_the_announcements_nobody_labelled(tmp_path):
    """263 readouts closed unknown on the first lookback run and 160 of them had a
    filing by the company inside the window flagged as a readout and never labelled. An
    unlabelled row carries no drug and no phase, so the match is the company's alone and
    the record says so. The labelling queue is the ledger itself."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-08-01", "Phase 3, Rhapsido", "NCT00000001")
    for i, day in enumerate(("2026-08-15", "2026-08-20", "2026-09-01", "2026-09-10")):
        conn.execute("INSERT INTO trial_readouts (accession, company_id, outcome, event_date)"
                     " VALUES (?, 1, 'none', ?)", (f"A-{i}", day))
    conn.execute("INSERT INTO trial_readouts (accession, company_id, outcome, event_date)"
                 " VALUES ('A-far', 1, 'none', '2026-10-30')")        # outside the window
    conn.commit()
    got = CO.resolve(path, today=TODAY, fetch=False)
    assert got["unknown"] == 1
    led = CO.ledger(path)[0]
    assert led["outcome"] == "unknown"
    assert led["evidence"].startswith("4 of the company's announcements")
    assert "A-0, A-1, A-2 and 1 more" in led["evidence"] and "A-far" not in led["evidence"]
    assert "unlabelled" in led["basis"]


def test_an_announced_trial_the_book_never_held_resolves_nothing_and_says_so(tmp_path):
    """The announcement names two trials that are no catalyst at all, while readouts of
    the same drug sit pending. None of them happened. Since the register reads back as
    far as the announcements go, this is now a trial the book never fetched."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-10-01", "Phase 3, Rhapsido", "NCT00000001")
    _catalyst(conn, 2, "data readout", "2026-10-15", "Phase 3, Rhapsido", "NCT00000002")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date, quote)"
                 " VALUES ('A-2', 1, 'remibrutinib', 3, 'positive', '2026-10-03',"
                 " 'REMODEL-1/-2 (NCT05147220, NCT05156281) met their primary endpoint.')")
    conn.commit()
    got = CO.resolve(path, today=TODAY, fetch=False)
    assert got["met"] == 0
    assert {r[0] for r in conn.execute("SELECT status FROM catalysts")} == {"pending"}
    led = CO.ledger(path)
    assert len(led) == 1 and led[0]["outcome"] == "elsewhere" and "NCT05147220" in led[0]["evidence"]


def test_the_registrys_own_words_single_out_a_sibling_when_no_nct_is_named(tmp_path):
    """GSK's three Jemperli Phase 2s are rectal, lung and head-and-neck studies, and the
    announcement says dMMR/MSI-H rectal cancer and cCR12."""
    path, conn = _book(tmp_path)
    for cid, nct, title, cond, mesh, po in (
            (1, "NCT00000011", "Phase 2, Jemperli", '["Neoplasms, Rectal"]',
             '{"meshes":[{"term":"Rectal Neoplasms"}]}', "sustained complete clinical response (cCR12)"),
            (2, "NCT00000012", "Phase 2, Jemperli", '["Lung Cancer, Non-Small Cell"]',
             '{"meshes":[{"term":"Carcinoma, Non-Small-Cell Lung"}]}', "adverse events"),
            (3, "NCT00000013", "Phase 2, Jemperli", '["Neoplasms, Head and Neck"]',
             '{"meshes":[{"term":"Head and Neck Neoplasms"}]}', "event-free survival")):
        _catalyst(conn, cid, "data readout", "2026-10-01", title, nct)
        conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, title, phase, overall_status,"
                     " conditions, mesh_terms, primary_outcome) VALUES (?, 1, ?, 'Phase 2', 'Recruiting', ?, ?, ?)",
                     (nct, "A Study of Dostarlimab in " + cond, cond, mesh, po))
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date, quote)"
                 " VALUES ('A-3', 1, 'Jemperli', 2, 'positive', '2026-10-03',"
                 " 'Positive data in dMMR/MSI-H rectal cancer: the single arm trial met its"
                 " primary objective, a sustained clinical complete response at 12 months (cCR12).')")
    conn.commit()
    got = CO.resolve(path, today=TODAY, fetch=False)
    assert got["met"] == 1
    assert conn.execute("SELECT status FROM catalysts WHERE id = 1").fetchone()[0] == "met"
    assert conn.execute("SELECT status FROM catalysts WHERE id = 2").fetchone()[0] == "pending"
    assert "tokens" in CO.ledger(path)[0]["basis"]


def test_words_that_fit_every_sibling_alike_stay_ambiguous(tmp_path):
    path, conn = _book(tmp_path)
    for cid, nct in ((1, "NCT00000021"), (2, "NCT00000022")):
        _catalyst(conn, cid, "data readout", "2026-10-01", "Phase 2, Rhapsido", nct)
        conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, title, phase, overall_status, conditions)"
                     " VALUES (?, 1, 'Remibrutinib in chronic urticaria', 'Phase 2', 'Recruiting', '[\"Urticaria\"]')", (nct,))
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date, quote)"
                 " VALUES ('A-4', 1, 'remibrutinib', 2, 'positive', '2026-10-03', 'Urticaria study met its endpoint.')")
    conn.commit()
    got = CO.resolve(path, today=TODAY, fetch=False)
    assert got["met"] == 0
    assert {r[0] for r in conn.execute("SELECT status FROM catalysts")} == {"pending"}
    assert CO.ledger(path)[0]["outcome"] == "ambiguous"


def test_a_fetched_announcement_is_cached_and_read_once(tmp_path):
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-10-01", "Phase 2, Rhapsido", "NCT00000001")
    _catalyst(conn, 2, "data readout", "2026-10-15", "Phase 2, Rhapsido", "NCT00000002")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date, quote, source_url)"
                 " VALUES ('A-5', 1, 'remibrutinib', 2, 'positive', '2026-10-03', 'met.', 'https://x/a.htm')")
    conn.commit()
    calls = []
    def get(url):
        calls.append(url)
        return "<html><body>Results of the NCT00000002 study: met.</body></html>"
    got = CO.resolve(path, today=TODAY, fetch=True, get=get)
    assert got["met"] == 1 and calls == ["https://x/a.htm"]
    cached = conn.execute("SELECT text FROM filing_sections WHERE accession='A-5' AND section='readout'").fetchone()
    assert cached and "NCT00000002" in cached["text"]
