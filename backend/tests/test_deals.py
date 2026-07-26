"""The deal reader: the guard that a party and a value must be in the filing, candidate
selection, and one classified filing through a fake model. No network."""

import datetime as dt

import db
import deals
import seed

_DOC = (
    "Biogen Inc. (Nasdaq: BIIB) today announced the successful completion of the "
    "acquisition of Apellis Pharmaceuticals, Inc. (Nasdaq: APLS) for $41 per share in "
    "cash. Apellis is a leader in complement-driven diseases."
)


def test_validate_accepts_a_deal_grounded_in_the_text():
    reply = {"found": True, "deal_type": "acquisition",
             "counterparty": "Apellis Pharmaceuticals, Inc.", "value": "$41 per share",
             "area": "complement-driven diseases",
             "quote": "Biogen Inc. (Nasdaq: BIIB) today announced the successful "
                      "completion of the acquisition of Apellis Pharmaceuticals, Inc."}
    out = deals.validate(reply, _DOC)
    assert out["deal_type"] == "acquisition"
    assert out["counterparty"] == "Apellis Pharmaceuticals, Inc."
    assert out["value"] == "$41 per share" and out["area"] == "complement-driven diseases"


def test_validate_rejects_a_party_not_in_the_text():
    """A counterparty the model produced from its own knowledge cannot become an event."""
    reply = {"found": True, "deal_type": "acquisition", "counterparty": "Kelonia",
             "value": None, "area": None,
             "quote": "Biogen Inc. today announced the successful completion of the "
                      "acquisition of Apellis Pharmaceuticals, Inc."}
    assert deals.validate(reply, _DOC) is None


def test_validate_drops_a_value_not_in_the_text():
    """The deal stands, but an unverifiable price is dropped rather than reported."""
    reply = {"found": True, "deal_type": "acquisition",
             "counterparty": "Apellis Pharmaceuticals", "value": "$6.5 billion",
             "area": None,
             "quote": "completion of the acquisition of Apellis Pharmaceuticals, Inc."}
    out = deals.validate(reply, _DOC)
    assert out is not None and out["value"] is None


def test_validate_rejects_an_out_of_scope_type_and_a_non_deal():
    base = {"found": True, "counterparty": "Apellis Pharmaceuticals",
            "quote": "acquisition of Apellis Pharmaceuticals, Inc."}
    assert deals.validate({**base, "deal_type": "financing"}, _DOC) is None
    assert deals.validate({"found": False}, _DOC) is None


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
    _seed_filing(db_file, "BIIB", "8-K", "Material agreement signed, Acquisition or "
                 "disposition completed", old, "acc-deal")
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='BIIB'").fetchone()[0]
    # a routine 8-K that is not a deal, and a deal already recorded
    conn.execute("INSERT INTO filings (company_id, accession, form_type, filed_date,"
                 " title, url) VALUES (?, 'acc-earnings', '8-K', ?, 'Results of"
                 " operations', 'http://x/e.htm')", (cid, old))
    conn.execute("INSERT INTO deals (accession, company_id, deal_type) VALUES"
                 " ('acc-seen', ?, 'none')", (cid,))
    conn.execute("INSERT INTO filings (company_id, accession, form_type, filed_date,"
                 " title, url) VALUES (?, 'acc-seen', '8-K', ?, 'Material agreement"
                 " signed', 'http://x/s.htm')", (cid, old))
    conn.commit()
    conn.close()

    got = {c["accession"] for c in deals.candidates(db_file)}
    assert got == {"acc-deal"}          # the deal title, not earnings, not the read one


def test_classify_runs_the_model_and_validates(tmp_path):
    filing = {"form_type": "8-K", "filed_date": "2026-05-14"}

    def fake_complete(system, user, max_tokens, prefer=None, thinking_budget=None):
        return ('{"found": true, "deal_type": "acquisition", "counterparty": '
                '"Apellis Pharmaceuticals, Inc.", "value": "$41 per share", '
                '"area": "complement-driven diseases", "quote": "acquisition of '
                'Apellis Pharmaceuticals, Inc. (Nasdaq: APLS) for $41 per share"}')

    out = deals._classify(_DOC, filing, fake_complete)
    assert out["counterparty"] == "Apellis Pharmaceuticals, Inc."
    assert out["value"] == "$41 per share"
