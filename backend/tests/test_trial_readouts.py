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
