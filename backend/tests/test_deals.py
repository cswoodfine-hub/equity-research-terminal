"""The deal reader: the guard that a party and a value must be in the filing, multi-deal
extraction, candidate selection, and one filing through a fake model. No network."""

import datetime as dt

import db
import deals
import seed

_DOC = (
    "Biogen Inc. (Nasdaq: BIIB) today announced the successful completion of the "
    "acquisition of Apellis Pharmaceuticals, Inc. (Nasdaq: APLS) for $41 per share in "
    "cash. Apellis is a leader in complement-driven diseases."
)
_MULTI = (
    "Lilly to acquire Kelonia Therapeutics to advance in vivo CAR-T cell therapies. "
    "Lilly to acquire Ajax Therapeutics for patients with myelofibrosis."
)


def test_validate_returns_a_deal_grounded_in_the_text():
    reply = {"deals": [{"deal_type": "acquisition",
                        "counterparty": "Apellis Pharmaceuticals, Inc.",
                        "value": "$41 per share", "area": "complement-driven diseases",
                        "quote": "Biogen Inc. (Nasdaq: BIIB) today announced the "
                                 "successful completion of the acquisition of Apellis "
                                 "Pharmaceuticals, Inc."}]}
    out = deals.validate(reply, _DOC)
    assert len(out) == 1 and out[0]["counterparty"] == "Apellis Pharmaceuticals, Inc."
    assert out[0]["value"] == "$41 per share"


def test_validate_lists_every_deal_a_filing_announces():
    reply = {"deals": [
        {"deal_type": "acquisition", "counterparty": "Kelonia Therapeutics",
         "value": None, "area": "in vivo CAR-T cell therapies",
         "quote": "Lilly to acquire Kelonia Therapeutics to advance in vivo CAR-T "
                  "cell therapies"},
        {"deal_type": "acquisition", "counterparty": "Ajax Therapeutics", "value": None,
         "area": "myelofibrosis",
         "quote": "Lilly to acquire Ajax Therapeutics for patients with myelofibrosis"}]}
    out = deals.validate(reply, _MULTI)
    assert {d["counterparty"] for d in out} == {"Kelonia Therapeutics", "Ajax Therapeutics"}


def test_validate_drops_a_party_not_in_the_text():
    """A counterparty from the model's own knowledge cannot become an event."""
    reply = {"deals": [{"deal_type": "acquisition", "counterparty": "Nowhere Bio",
                        "value": None, "area": None,
                        "quote": "acquisition of Apellis Pharmaceuticals, Inc."}]}
    assert deals.validate(reply, _DOC) == []


def test_validate_drops_a_value_not_in_the_text():
    reply = {"deals": [{"deal_type": "acquisition",
                        "counterparty": "Apellis Pharmaceuticals", "value": "$6.5 billion",
                        "area": None,
                        "quote": "completion of the acquisition of Apellis "
                                 "Pharmaceuticals, Inc."}]}
    out = deals.validate(reply, _DOC)
    assert len(out) == 1 and out[0]["value"] is None


def test_validate_rejects_an_out_of_scope_type_and_a_non_deal():
    good_quote = "acquisition of Apellis Pharmaceuticals, Inc. (Nasdaq: APLS)"
    assert deals.validate({"deals": [{"deal_type": "financing",
                                      "counterparty": "Apellis Pharmaceuticals",
                                      "quote": good_quote}]}, _DOC) == []
    assert deals.validate({"deals": []}, _DOC) == []


def _seed_filing(db_file, ticker, form, title, date, accession):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]
    conn.execute("INSERT INTO filings (company_id, accession, form_type, filed_date,"
                 " title, url) VALUES (?, ?, ?, ?, ?, 'http://x/f.htm')",
                 (cid, accession, form, date, title))
    conn.commit()
    conn.close()


def test_candidates_pick_deal_titles_and_skip_the_already_read(tmp_path):
    db_file = tmp_path / "t.db"
    old = (dt.date.today() - dt.timedelta(days=20)).isoformat()
    _seed_filing(db_file, "LLY", "8-K", "Results of operations", old, "acc-earn")
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    # a routine 8-K that is not a deal title, and a deal filing already recorded
    conn.execute("INSERT INTO filings (company_id, accession, form_type, filed_date,"
                 " title, url) VALUES (?, 'acc-vote', '8-K', ?, 'Shareholder vote',"
                 " 'http://x/v.htm')", (cid, old))
    conn.execute("INSERT INTO deals (accession, company_id, deal_type) VALUES"
                 " ('acc-seen', ?, 'none')", (cid,))
    conn.execute("INSERT INTO filings (company_id, accession, form_type, filed_date,"
                 " title, url) VALUES (?, 'acc-seen', '8-K', ?, 'Other events',"
                 " 'http://x/s.htm')", (cid, old))
    conn.commit()
    conn.close()

    got = {c["accession"] for c in deals.candidates(db_file)}
    assert got == {"acc-earn"}          # earnings title kept, vote dropped, seen skipped


def test_store_writes_a_row_per_deal_and_a_none_marker(tmp_path):
    db_file = tmp_path / "t.db"
    _seed_filing(db_file, "LLY", "8-K", "Results of operations", "2026-04-30", "acc-multi")
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    filing = {"accession": "acc-multi", "company_id": cid, "filed_date": "2026-04-30",
              "url": "http://x/f.htm"}
    deals._store(conn, filing, [
        {"deal_type": "acquisition", "counterparty": "Kelonia Therapeutics",
         "value": None, "area": "in vivo CAR-T", "quote": "q1"},
        {"deal_type": "acquisition", "counterparty": "Ajax Therapeutics",
         "value": None, "area": "myelofibrosis", "quote": "q2"}])
    empty = {"accession": "acc-none", "company_id": cid, "filed_date": "2026-04-30",
             "url": "http://x/g.htm"}
    deals._store(conn, empty, [])
    conn.commit()
    parties = [r[0] for r in conn.execute(
        "SELECT counterparty FROM deals WHERE accession='acc-multi' ORDER BY counterparty")]
    assert parties == ["Ajax Therapeutics", "Kelonia Therapeutics"]
    assert conn.execute("SELECT deal_type FROM deals WHERE accession='acc-none'"
                        ).fetchone()[0] == "none"
    conn.close()


def test_classify_runs_the_model_and_validates(tmp_path):
    filing = {"form_type": "8-K", "filed_date": "2026-05-14"}

    def fake_complete(system, user, max_tokens, prefer=None, thinking_budget=None):
        return ('{"deals": [{"deal_type": "acquisition", "counterparty": '
                '"Apellis Pharmaceuticals, Inc.", "value": "$41 per share", '
                '"area": "complement-driven diseases", "quote": "acquisition of '
                'Apellis Pharmaceuticals, Inc. (Nasdaq: APLS) for $41 per share"}]}')

    out = deals._classify(_DOC, filing, fake_complete)
    assert len(out) == 1 and out[0]["value"] == "$41 per share"
