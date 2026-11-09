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
    assert CO.resolve(path, today=TODAY, fetch=False) == {"met": 0, "missed": 0, "slipped": 0,
                                                          "unknown": 0, "open": 0, "overturned": 0}
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


def test_an_unknown_readout_names_the_filings_read_blank_inside_its_window(tmp_path):
    """263 readouts closed unknown on the first lookback run and 171 of them had a
    filing by the company inside the window that the reader had recorded as stating no
    result. Such a row carries no drug and no phase, so the match is the company's alone
    and the record says so: those are the filings a second reading goes back to."""
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
    assert led["evidence"].startswith("4 of the company's filings inside the window were read")
    assert "A-0, A-1, A-2 and 1 more" in led["evidence"] and "A-far" not in led["evidence"]
    assert "second reading" in led["basis"]


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
    # A page this short reads as an envelope, so the reader also looks for its exhibit;
    # the folder index is the one extra request, and no exhibit is listed in it.
    assert got["met"] == 1 and calls == ["https://x/a.htm", "https://x/index.json"]
    cached = conn.execute("SELECT text FROM filing_sections WHERE accession='A-5' AND section='readout'").fetchone()
    assert cached and "NCT00000002" in cached["text"]


def test_a_result_labelled_later_overturns_an_unknown(tmp_path):
    """The window closed with the filing read as an envelope, so the catalyst went
    unknown. When the reader goes back with the exhibit and labels the result, the next
    run overturns the unknown; both rows stay on the ledger and call_log reads met."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-08-01", "Phase 3, Rhapsido", "NCT00000001")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, outcome, event_date)"
                 " VALUES ('A-5', 1, 'none', '2026-08-15')")
    conn.commit()
    first = CO.resolve(path, today=TODAY, fetch=False)
    assert first["unknown"] == 1 and first["overturned"] == 0
    led = CO.ledger(path)[0]
    assert "were read and state no Phase 2 or 3 result: A-5" in led["evidence"]

    conn.execute("UPDATE trial_readouts SET drug = 'remibrutinib', phase = 3, outcome = 'positive',"
                 " quote = 'met its primary endpoint', reread_at = '2026-11-08' WHERE accession = 'A-5'")
    conn.commit()
    second = CO.resolve(path, today=TODAY, fetch=False)
    assert second["met"] == 1 and second["overturned"] == 1 and second["unknown"] == 0
    row = conn.execute("SELECT status, updated_at FROM catalysts WHERE id = 1").fetchone()
    assert row["status"] == "met" and row["updated_at"] == "2026-08-15"
    outcomes = sorted(r["outcome"] for r in CO.ledger(path))
    assert outcomes == ["met", "unknown"]
    # A third run changes nothing: the row is met, not unknown, so the pass skips it.
    assert CO.resolve(path, today=TODAY, fetch=False)["overturned"] == 0


def test_a_slip_or_grace_cannot_overturn_an_unknown(tmp_path):
    """Only an announced result overturns an unknown; the registry and grace tiers are
    not run again on a closed row."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-08-01", "Phase 3, Rhapsido", "NCT00000001")
    conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, asset_id, title, phase,"
                 " overall_status, primary_completion_date) VALUES ('NCT00000001', 1, 10, 'T',"
                 " 'Phase 3', 'Active not recruiting', '2026-08-01')")
    conn.commit()
    assert CO.resolve(path, today=TODAY, fetch=False)["unknown"] == 1
    conn.execute("UPDATE trials SET primary_completion_date = '2027-03-01' WHERE nct_id = 'NCT00000001'")
    conn.commit()
    again = CO.resolve(path, today=TODAY, fetch=False)
    assert again["overturned"] == 0 and again["slipped"] == 0
    assert conn.execute("SELECT status FROM catalysts WHERE id = 1").fetchone()[0] == "unknown"


def test_an_unknown_row_is_in_its_own_sibling_set_on_the_second_pass(tmp_path):
    """argenx: Vyvgart Hytrulo's readout closed unknown; five more Vyvgart Phase 3s sit
    pending for later years. The result labelled later names the unknown row's own
    trial, so that row resolves and none of the five future ones does."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-01-12", "Phase 3, Rhapsido", "NCT00000001")
    for i in range(2, 7):
        _catalyst(conn, i, "data readout", f"2027-0{i}-01", "Phase 3, Rhapsido", f"NCT0000000{i}")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, outcome, event_date)"
                 " VALUES ('A-6', 1, 'none', '2026-02-26')")
    conn.commit()
    assert CO.resolve(path, today=TODAY, fetch=False)["unknown"] == 1
    conn.execute("UPDATE trial_readouts SET drug = 'remibrutinib', phase = 3, outcome = 'positive',"
                 " quote = 'The NCT00000001 study met its primary endpoint.', reread_at = '2026-11-08'"
                 " WHERE accession = 'A-6'")
    conn.commit()
    got = CO.resolve(path, today=TODAY, fetch=False)
    assert got["overturned"] == 1 and got["met"] == 1
    status = {r[0]: r[1] for r in conn.execute("SELECT id, status FROM catalysts ORDER BY id")}
    assert status[1] == "met" and all(status[i] == "pending" for i in range(2, 7))


def test_the_second_pass_never_settles_a_pending_sibling(tmp_path):
    """argenx again, the other way round: the labelled release fits a 2027 sibling's
    registry words better than the unknown row's own. The sibling's window has not
    closed, so the second pass leaves it and the announcement alone."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-01-12", "Phase 3, Rhapsido", "NCT00000001")
    _catalyst(conn, 2, "data readout", "2027-06-01", "Phase 3, Rhapsido", "NCT00000002")
    conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, asset_id, title, phase, overall_status,"
                 " primary_completion_date, conditions) VALUES ('NCT00000002', 1, 10, 'Ocular study',"
                 " 'Phase 3', 'Recruiting', '2027-06-01', '[\"Ocular myasthenia gravis\"]')")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, outcome, event_date)"
                 " VALUES ('A-7', 1, 'none', '2026-02-20')")
    conn.commit()
    assert CO.resolve(path, today=TODAY, fetch=False)["unknown"] == 1
    conn.execute("UPDATE trial_readouts SET drug = 'remibrutinib', phase = 3, outcome = 'positive',"
                 " quote = 'The ocular myasthenia study met its primary endpoint.', reread_at = '2026-11-08'"
                 " WHERE accession = 'A-7'")
    conn.commit()
    got = CO.resolve(path, today=TODAY, fetch=False)
    assert got["overturned"] == 0 and got["met"] == 0
    status = {r[0]: r[1] for r in conn.execute("SELECT id, status FROM catalysts ORDER BY id")}
    assert status == {1: "unknown", 2: "pending"}
    assert all(r["outcome"] == "unknown" for r in CO.ledger(path))


def test_a_sibling_at_another_phase_is_not_a_sibling(tmp_path):
    """The phase is read off the catalyst's title, not the trial's registry title, which
    rarely states one: a Phase 2 Vyvgart study was admitted to the siblings of a Phase 3
    result and closed on it."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-10-01", "Phase 3, Rhapsido", "NCT00000001")
    _catalyst(conn, 2, "data readout", "2026-10-15", "Phase 2, Rhapsido", "NCT00000002")
    conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, asset_id, title, phase, overall_status,"
                 " primary_completion_date) VALUES ('NCT00000002', 1, 10, 'A study in adults', 'Phase 2',"
                 " 'Recruiting', '2026-10-15')")
    conn.commit()
    rows = CO._sibling_rows(conn, {"id": 1, "company_id": 1, "asset_id": 10}, 3)
    assert [r["id"] for r in rows] == [1]


def test_an_ambiguous_release_does_not_stop_a_later_one_being_read(tmp_path):
    """Two results for one drug inside one window: the first fits every sibling alike,
    the second names this row's trial. The first is logged ambiguous; the second
    resolves."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-10-01", "Phase 3, Rhapsido", "NCT00000001")
    _catalyst(conn, 2, "data readout", "2026-10-20", "Phase 3, Rhapsido", "NCT00000002")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date, quote)"
                 " VALUES ('A-8', 1, 'remibrutinib', 3, 'positive', '2026-09-20', 'The study met its endpoint.')")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date, quote)"
                 " VALUES ('A-9', 1, 'remibrutinib', 3, 'negative', '2026-10-05',"
                 " 'The NCT00000001 study did not meet its primary endpoint.')")
    conn.commit()
    got = CO.resolve(path, today=TODAY, fetch=False)
    assert got["missed"] == 1
    status = {r[0]: r[1] for r in conn.execute("SELECT id, status FROM catalysts ORDER BY id")}
    assert status == {1: "missed", 2: "pending"}
    outcomes = sorted((r["outcome"], r["evidence"][:12]) for r in CO.ledger(path))
    assert outcomes == [("ambiguous", "readout A-8:"), ("missed", "readout A-9:")]


def test_an_nct_pinned_result_resolves_without_drug_or_phase(tmp_path):
    """A row whose source states the trial needs no match on names: it is about this
    study. Here the pinned result is a press row that named the NCT."""
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-08-01", "Phase 3, Rhapsido", "NCT00000001")
    _catalyst(conn, 2, "data readout", "2026-08-01", "Phase 3, Rhapsido", "NCT00000002")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date, quote, source, nct_id)"
                 " VALUES ('news:7', 1, 'something else entirely', 2, 'positive', '2026-08-20', 'met.', 'press', 'NCT00000002')")
    conn.commit()
    got = CO.resolve(path, today=TODAY, fetch=False)
    assert got["met"] == 1
    status = {r[0]: r[1] for r in conn.execute("SELECT id, status FROM catalysts ORDER BY id")}
    assert status[2] == "met" and status[1] == "unknown"
    assert CO.ledger(path)[0]["source"] == "trial_readouts:press" or any(
        r["source"] == "trial_readouts:press" for r in CO.ledger(path))


def test_a_press_rows_body_is_fetched_the_way_the_press_reader_fetches(tmp_path, monkeypatch):
    """The EDGAR agent is refused by the companies' own sites, so a press row's body
    comes through the press reader's fetcher, and is cached like any other."""
    import press_readouts
    path, conn = _book(tmp_path)
    monkeypatch.setattr(press_readouts, "_get", lambda url: "<p>Release body naming NCT00000009.</p>")
    monkeypatch.setattr(CO.trial_readouts, "_get", lambda url: (_ for _ in ()).throw(RuntimeError("403")))
    readout = {"accession": "news:9", "company_id": 1, "quote": "met.", "source_url": "https://x/r",
               "source": "press", "event_date": "2026-10-01"}
    text = CO.announcement_text(conn, readout, True, None)
    assert "NCT00000009" in text
    assert conn.execute("SELECT COUNT(*) FROM filing_sections WHERE accession = 'news:9'").fetchone()[0] == 1


def test_a_release_that_lists_the_programme_resolves_only_the_study_that_was_due(tmp_path):
    """Saphnelo: one release named five studies due between 2025 and 2028. Twins are two
    studies due within a season of each other; five across three years is a programme
    list, and only the one whose window held the release resolves."""
    path, conn = _book(tmp_path)
    dates = {1: "2025-08-22", 2: "2026-11-02", 3: "2027-01-06", 4: "2027-02-23", 5: "2028-01-10"}
    for i, d in dates.items():
        _catalyst(conn, i, "data readout", d, "Phase 3, Rhapsido", f"NCT0000000{i}")
    ncts = ", ".join(f"NCT0000000{i}" for i in dates)
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date, quote)"
                 " VALUES ('A-10', 1, 'remibrutinib', 3, 'positive', '2025-09-17',"
                 f" 'The programme spans {ncts}; the study met its primary endpoint.')")
    conn.commit()
    got = CO.resolve(path, today=TODAY, fetch=False)
    assert got["met"] == 1
    status = {r[0]: r[1] for r in conn.execute("SELECT id, status FROM catalysts ORDER BY id")}
    assert status[1] == "met" and all(status[i] == "pending" for i in (3, 4, 5))
    assert status[2] in ("pending", "unknown")           # its own turn: no second result for it
    led = [r for r in CO.ledger(path) if r["outcome"] == "met"][0]
    assert "only NCT00000001 was due" in led["evidence"]


def test_two_named_studies_a_season_apart_are_not_twins(tmp_path):
    path, conn = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-07-21", "Phase 3, Rhapsido", "NCT00000001")
    _catalyst(conn, 2, "data readout", "2027-03-01", "Phase 3, Rhapsido", "NCT00000002")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date, quote)"
                 " VALUES ('A-11', 1, 'remibrutinib', 3, 'positive', '2026-08-20',"
                 " 'NCT00000001 met its endpoint; NCT00000002 continues.')")
    conn.commit()
    CO.resolve(path, today=TODAY, fetch=False)
    status = {r[0]: r[1] for r in conn.execute("SELECT id, status FROM catalysts ORDER BY id")}
    assert status == {1: "met", 2: "pending"}
