"""Trial-readout classifier: the guarded validation, the candidate filter, and storage.
No network (the model reply and the documents are supplied directly)."""

import datetime as dt

import db
import seed
import trial_readouts

_DOC = ("Big Pharma today announced that its Phase 3 STELLAR trial of tirzepatide met "
        "its primary endpoint, demonstrating a statistically significant reduction in "
        "the primary measure. The safety profile was consistent with prior studies.")


# --- validation -------------------------------------------------------------
def test_validate_accepts_a_signed_phase3_readout():
    reply = {"found": True, "drug": "tirzepatide", "phase": 3, "outcome": "positive",
             "quote": "its Phase 3 STELLAR trial of tirzepatide met its primary "
                      "endpoint, demonstrating a statistically significant reduction in "
                      "the primary measure."}
    v = trial_readouts.validate(reply, _DOC)
    assert v["drug"] == "tirzepatide" and v["phase"] == 3 and v["outcome"] == "positive"


def test_validate_rejects_out_of_scope_and_unsupported():
    good_quote = ("its Phase 3 STELLAR trial of tirzepatide met its primary endpoint, "
                  "demonstrating a statistically significant reduction in the primary "
                  "measure.")
    assert trial_readouts.validate({"found": False}, _DOC) is None
    # Phase 1 is out of scope.
    assert trial_readouts.validate(
        {"found": True, "drug": "tirzepatide", "phase": 1, "outcome": "positive",
         "quote": good_quote}, _DOC) is None
    # A drug the document does not name is from the model's knowledge, not the filing.
    assert trial_readouts.validate(
        {"found": True, "drug": "aducanumab", "phase": 3, "outcome": "positive",
         "quote": good_quote}, _DOC) is None
    # A quote that is not in the document is rejected.
    assert trial_readouts.validate(
        {"found": True, "drug": "tirzepatide", "phase": 3, "outcome": "negative",
         "quote": "A sentence that does not appear anywhere in the filing about "
                  "endpoints and results."}, _DOC) is None


def test_validate_rejects_a_restatement_of_an_earlier_result():
    """A designation release that cites the readout, or a sentence that begins "as
    previously reported", is dated to the filing and not to the result, and can settle
    a sibling the original announcement already settled."""
    doc = ("Sanofi today announced a Breakthrough Therapy designation for venglustat. "
           "The designation is based on data from the LEAP2MONO phase 3 study in which "
           "patients receiving venglustat met the primary endpoint. As previously "
           "reported, the study met its primary endpoint with a 41% reduction. The "
           "application is based on positive data from the registrational phase II "
           "AZUR-1 trial of venglustat, which met its primary endpoint. Roche announced "
           "today late-breaking oral presentation data showing venglustat met its primary "
           "endpoint. Full results from the positive phase 3 study showed venglustat met "
           "its primary endpoint. Positive results from the venglustat study were "
           "previously published in The New England Journal of Medicine and met the "
           "primary endpoint.")
    for quote in ("The designation is based on data from the LEAP2MONO phase 3 study in "
                  "which patients receiving venglustat met the primary endpoint.",
                  "Roche announced today late-breaking oral presentation data showing "
                  "venglustat met its primary endpoint.",
                  "Full results from the positive phase 3 study showed venglustat met its "
                  "primary endpoint.",
                  "Positive results from the venglustat study were previously published in "
                  "The New England Journal of Medicine and met the primary endpoint.",
                  "The application is based on positive data from the registrational "
                  "phase II AZUR-1 trial of venglustat, which met its primary endpoint.",
                  "As previously reported, the study met its primary endpoint with a 41% "
                  "reduction."):
        assert trial_readouts.validate(
            {"found": True, "drug": "venglustat", "phase": 3, "outcome": "positive",
             "quote": quote}, doc) is None


# --- candidate filter -------------------------------------------------------
def _seed(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    lly = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    recent = (dt.date.today() - dt.timedelta(days=40)).isoformat()

    def filing(accession, form, title):
        conn.execute("INSERT INTO filings (company_id, form_type, filed_date, accession,"
                     " title, url) VALUES (?, ?, ?, ?, ?, ?)",
                     (lly, form, recent, accession, title,
                      f"https://sec.gov/{accession}.htm"))
    filing("8k-earn", "8-K", "Results of operations")           # earnings, excluded
    filing("8k-fd", "8-K", "Regulation FD disclosure")          # candidate
    filing("6k-1", "6-K", "6-K")                                # candidate
    filing("10k-1", "10-K", "Annual report")                    # wrong form, excluded
    filing("8k-seen", "8-K", "Other events")                    # candidate but already read
    conn.execute("INSERT INTO trial_readouts (accession, company_id, outcome, event_date)"
                 " VALUES ('8k-seen', ?, 'none', ?)", (lly, recent))
    conn.commit()
    conn.close()
    return lly


def test_candidates_keeps_result_bearing_forms_and_skips_seen(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    got = {c["accession"] for c in trial_readouts.candidates(db_file)}
    assert got == {"8k-fd", "6k-1"}          # not the earnings, the 10-K, or the seen one


def test_store_writes_a_signed_readout_and_is_idempotent(tmp_path):
    db_file = tmp_path / "t.db"
    lly = _seed(db_file)
    conn = db.get_connection(db_file)
    filing = {"accession": "6k-1", "company_id": lly, "filed_date": "2026-05-01",
              "url": "https://sec.gov/6k-1.htm", "form_type": "6-K"}
    result = {"drug": "tirzepatide", "phase": 3, "outcome": "positive",
              "quote": "met its primary endpoint"}
    trial_readouts._store(conn, filing, result)
    trial_readouts._store(conn, filing, result)          # again, no duplicate
    conn.commit()
    row = conn.execute("SELECT phase, outcome, drug FROM trial_readouts"
                       " WHERE accession = '6k-1'").fetchone()
    assert row["phase"] == 3 and row["outcome"] == "positive"
    assert conn.execute("SELECT COUNT(*) FROM trial_readouts"
                        " WHERE accession = '6k-1'").fetchone()[0] == 1
    conn.close()


def test_recent_returns_signed_readouts_recent_first(tmp_path):
    """The tab reader: signed Phase 2/3 readouts, newest first, none excluded."""
    db_file = tmp_path / "t.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='GSK'").fetchone()[0]
    for acc, drug, phase, outcome, date in [
        ("r1", "Ris-Rez", 3, "positive", "2026-07-10"),
        ("r2", "camlipixant", 3, "negative", "2026-07-17"),
        ("r3", "nothing", 3, "none", "2026-07-15"),        # read, no readout: excluded
    ]:
        conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase,"
                     " outcome, event_date) VALUES (?, ?, ?, ?, ?, ?)",
                     (acc, cid, drug, phase, outcome, date))
    conn.commit()
    conn.close()

    out = trial_readouts.recent(db_file, "GSK", today=dt.date(2026, 7, 26))
    assert [r["drug"] for r in out] == ["camlipixant", "Ris-Rez"]   # newest first
    assert out[0]["outcome"] == "negative"


# --- the second reading --------------------------------------------------------
_COVER_6K = ("FORM 6-K Report of Foreign Private Issuer. Novo Nordisk A/S. Novo Alle, "
             "Bagsvaerd. Indicate by check mark whether the registrant files annual "
             "reports under cover of Form 20-F or Form 40-F. Exhibit 99.1 attached.")
_COVER_8K_HINT = ("FORM 8-K Item 7.01 Regulation FD Disclosure. On 1 July 2026 the Company "
                  "issued a press release on its Phase 3 STELLAR trial of tirzepatide. "
                  "The press release is furnished as Exhibit 99.1.")
_INDEX = '{"directory": {"item": [{"name": "ex99-1.htm"}, {"name": "cover.htm"}]}}'


def _pages(cover):
    pages = {"https://sec.gov/x/cover.htm": cover,
             "https://sec.gov/x/index.json": _INDEX,
             "https://sec.gov/x/ex99-1.htm": "<html><body>" + _DOC + "</body></html>"}
    return lambda url: pages[url]


def test_a_6k_cover_is_followed_to_its_exhibit():
    """The first reader followed only an 8-K to its exhibit, so every foreign filer's
    release was read as the envelope around it."""
    filing = {"url": "https://sec.gov/x/cover.htm", "form_type": "6-K"}
    text, read_from = trial_readouts.readout_text(filing, get=_pages(_COVER_6K))
    assert read_from == "primary+exhibit"
    assert "met its primary endpoint" in text and "Novo Nordisk" in text   # joined, not swapped


def test_an_8k_cover_that_says_phase_3_is_still_an_envelope():
    """The cheap hint fires on "Phase 3" in the item description, which is exactly the
    cover that carries no result sentence."""
    filing = {"url": "https://sec.gov/x/cover.htm", "form_type": "8-K"}
    assert trial_readouts.HINT.search(_COVER_8K_HINT)
    text, read_from = trial_readouts.readout_text(filing, get=_pages(_COVER_8K_HINT))
    assert read_from == "primary+exhibit" and "statistically significant" in text


def test_a_primary_that_states_a_result_is_read_as_it_is():
    long_release = _DOC * 40                                   # past ENVELOPE_CHARS
    assert len(long_release) >= trial_readouts.ENVELOPE_CHARS
    filing = {"url": "https://sec.gov/x/cover.htm", "form_type": "8-K"}
    text, read_from = trial_readouts.readout_text(filing, get=_pages(long_release))
    assert read_from == "primary" and "Novo" not in text


def test_unread_puts_the_rows_a_catalyst_waits_on_first(tmp_path):
    db_file = tmp_path / "t.db"
    lly = _seed(db_file)
    conn = db.get_connection(db_file)
    mrk = conn.execute("SELECT id FROM companies WHERE ticker='MRK'").fetchone()[0]
    for acc, cid, day in (("n-late", lly, "2026-09-20"), ("n-early", mrk, "2026-03-01"),
                          ("n-wait", mrk, "2026-08-10")):
        conn.execute("INSERT INTO filings (company_id, form_type, filed_date, accession, title, url)"
                     " VALUES (?, '6-K', ?, ?, '6-K', ?)", (cid, day, acc, f"https://sec.gov/{acc}.htm"))
        conn.execute("INSERT INTO trial_readouts (accession, company_id, outcome, event_date)"
                     " VALUES (?, ?, 'none', ?)", (acc, cid, day))
    # A row already read again, and a labelled row, are not in the queue.
    conn.execute("INSERT INTO filings (company_id, form_type, filed_date, accession, title, url)"
                 " VALUES (?, '6-K', '2026-08-11', 'n-done', '6-K', 'https://sec.gov/n-done.htm')", (mrk,))
    conn.execute("INSERT INTO trial_readouts (accession, company_id, outcome, event_date, reread_at)"
                 " VALUES ('n-done', ?, 'none', '2026-08-11', '2026-11-08')", (mrk,))
    conn.execute("INSERT INTO catalysts (company_id, catalyst_type, expected_date, date_confidence,"
                 " title, status) VALUES (?, 'data readout', '2026-08-01', 'estimated', 'Phase 3, X', 'unknown')", (mrk,))
    conn.commit()
    conn.close()
    got = trial_readouts.unread(db_file)
    assert [r["accession"] for r in got][:1] == ["n-wait"]
    assert got[0]["waited_on"] is True and got[0]["form_type"] == "6-K"
    assert "n-done" not in {r["accession"] for r in got}
    assert {r["accession"] for r in got} >= {"n-late", "n-early", "8k-seen"}


def test_reread_relabels_a_blank_row_and_stamps_it_once(tmp_path, monkeypatch):
    """Read again with the exhibit, a row that said none becomes a signed readout; one
    that still says nothing is stamped so it is not read a third time."""
    db_file = tmp_path / "t.db"
    lly = _seed(db_file)
    conn = db.get_connection(db_file)
    conn.execute("UPDATE filings SET url = 'https://sec.gov/x/cover.htm' WHERE accession = '8k-seen'")
    conn.execute("INSERT INTO filings (company_id, form_type, filed_date, accession, title, url)"
                 " VALUES (?, '6-K', '2026-08-11', 'n-blank', '6-K', 'https://sec.gov/y/cover.htm')", (lly,))
    conn.execute("INSERT INTO trial_readouts (accession, company_id, outcome, event_date)"
                 " VALUES ('n-blank', ?, 'none', '2026-08-11')", (lly,))
    conn.commit()
    conn.close()

    pages = {"https://sec.gov/x/cover.htm": _COVER_6K, "https://sec.gov/x/index.json": _INDEX,
             "https://sec.gov/x/ex99-1.htm": _DOC,
             "https://sec.gov/y/cover.htm": "FORM 6-K. A dividend was declared. Phase 3 "
                                            "work continues on schedule.",
             "https://sec.gov/y/index.json": '{"directory": {"item": []}}'}
    monkeypatch.setattr(trial_readouts, "_get", lambda url: pages[url])
    monkeypatch.setattr(trial_readouts.llm, "provider", lambda prefer=None: "test")
    reply = ('{"found": true, "drug": "tirzepatide", "phase": 3, "outcome": "positive", '
             '"quote": "its Phase 3 STELLAR trial of tirzepatide met its primary endpoint, '
             'demonstrating a statistically significant reduction in the primary measure."}')
    calls = []

    def complete(system, user, max_tokens, thinking_budget=None):
        calls.append(user)
        return reply if "STELLAR" in user else '{"found": false}'
    monkeypatch.setattr(trial_readouts.llm, "complete", complete)
    monkeypatch.setattr(trial_readouts.time, "sleep", lambda s: None)

    got = trial_readouts.reread(db_file, today=dt.date(2026, 11, 8))
    assert got["read"] == 2 and got["positive"] == 1 and got["negative"] == 0
    conn = db.get_connection(db_file)
    seen = conn.execute("SELECT outcome, drug, phase, read_from, reread_at FROM trial_readouts"
                        " WHERE accession = '8k-seen'").fetchone()
    assert (seen["outcome"], seen["drug"], seen["phase"]) == ("positive", "tirzepatide", 3)
    assert seen["read_from"] == "primary+exhibit" and seen["reread_at"] == "2026-11-08"
    blank = conn.execute("SELECT outcome, reread_at FROM trial_readouts"
                         " WHERE accession = 'n-blank'").fetchone()
    assert blank["outcome"] == "none" and blank["reread_at"] == "2026-11-08"
    conn.close()
    # Nothing left to read: the stamp holds.
    assert trial_readouts.reread(db_file, today=dt.date(2026, 11, 9))["read"] == 0

