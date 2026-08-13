"""The guidance extractor's gates. The model is a reader, not a source.

Every test here asks the same question of a figure the model returned: is it in the
document, or did it come from somewhere else. A reply that cannot be traced to the words
of the filing is refused, whatever it says, and no test lets a real model near the code.
"""

import json

import db
import guidance


SECTION_TEXT = (
    "Fourth quarter results were in line with expectations. "
    "For 2026, we expect total revenue of $350 million to $370 million, reflecting "
    "continued launch momentum. Our guidance assumes no change in reimbursement. "
    "The remainder of this exhibit consists of tables."
)


def _seed(tmp_path, text=SECTION_TEXT, section="exhibit", filed="2026-08-06"):
    path = str(tmp_path / "g.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'IOVA', 'Iovance')")
    conn.execute("INSERT INTO filing_sections (company_id, accession, form_type,"
                 " filed_date, section, char_count, text)"
                 " VALUES (1, '0001-26-000001', '8-K', ?, ?, ?, ?)",
                 (filed, section, len(text), text))
    conn.commit()
    conn.close()
    return path


def _reply(**kw):
    item = {"metric": "Revenue", "period": "FY2026", "low": 350000000,
            "high": 370000000, "currency": "USD",
            "quote": "For 2026, we expect total revenue of $350 million to $370 "
                     "million, reflecting continued launch momentum."}
    item.update(kw)
    return lambda *_args, **_kwargs: json.dumps({"found": True, "items": [item]})


def _stored(path):
    conn = db.get_connection(path)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM consensus_estimates ORDER BY id")]
    finally:
        conn.close()


def test_a_stated_range_is_written_with_its_midpoint_and_its_sentence(tmp_path):
    path = _seed(tmp_path)
    out = guidance.extract(path, complete=_reply())
    assert out == {"status": "ok", "read": 1, "found": 1, "errors": []}
    row = _stored(path)[0]
    assert (row["low"], row["high"], row["value"]) == (350000000.0, 370000000.0,
                                                       360000000.0)
    assert row["source"] == "guidance" and row["period"] == "FY2026"
    # The receipt: the sentence the figure was read out of, and the day it was filed.
    assert row["note"].startswith("For 2026, we expect total revenue")
    assert row["as_of"] == "2026-08-06"


def test_a_quote_the_filing_does_not_contain_is_refused(tmp_path):
    path = _seed(tmp_path)
    out = guidance.extract(path, complete=_reply(
        quote="We expect full-year revenue of $900 million, a record for the company."))
    assert out["found"] == 0 and _stored(path) == []


def test_a_period_the_filing_cannot_be_guiding_to_is_refused(tmp_path):
    path = _seed(tmp_path)
    assert guidance.extract(path, complete=_reply(period="FY2031"))["found"] == 0
    assert _stored(path) == []


def test_a_growth_range_quoted_as_an_amount_is_refused(tmp_path):
    text = ("For 2026 we now expect sales growth of 8 to 14 percent at constant "
            "exchange rates, unchanged from our previous guidance.")
    path = _seed(tmp_path, text=text, section="body")
    quote = ("For 2026 we now expect sales growth of 8 to 14 percent at constant "
             "exchange rates, unchanged from our previous guidance.")
    assert guidance.extract(path, complete=_reply(
        metric="RevenueGrowth", low=8e9, high=14e9, currency=None,
        quote=quote))["found"] == 0
    # Stated as the percentages the company actually used, it passes. A second database,
    # because the first section has been read and the ledger will not offer it twice.
    again = tmp_path / "again"
    again.mkdir()
    path = _seed(again, text=text, section="body")
    assert guidance.extract(path, complete=_reply(
        metric="RevenueGrowth", low=8, high=14, currency=None,
        quote=quote))["found"] == 1
    row = _stored(path)[0]
    assert (row["metric"], row["value"], row["currency"]) == ("RevenueGrowth", 11.0,
                                                              None)


def test_an_inverted_or_unparseable_range_is_refused(tmp_path):
    path = _seed(tmp_path)
    assert guidance.extract(path, complete=_reply(low=370000000,
                                                  high=350000000))["found"] == 0
    assert guidance.extract(path, complete=_reply(low="about $350m"))["found"] == 0
    assert _stored(path) == []


def test_risk_factors_are_never_read(tmp_path):
    # The 242 mentions of guidance in risk factors are forward-looking-statement
    # boilerplate, and reading them would drown the real rows in the same table.
    path = _seed(tmp_path, section="risk_factors")
    called = []

    def complete(*args, **kwargs):
        called.append(args)
        return _reply()()

    assert guidance.extract(path, complete=complete)["read"] == 0
    assert called == [] and _stored(path) == []


def test_a_section_with_no_guidance_language_costs_no_call(tmp_path):
    path = _seed(tmp_path, text="Item 8.01. The company announces a new director.")
    called = []
    guidance.extract(path, complete=lambda *a, **k: called.append(a) or _reply()())
    assert called == [] and _stored(path) == []
    # It is still ledgered, so it is never looked at again.
    conn = db.get_connection(path)
    assert conn.execute("SELECT found FROM guidance_scans").fetchone()["found"] == 0
    conn.close()


def test_a_section_is_read_once_and_never_again(tmp_path):
    path = _seed(tmp_path)
    assert guidance.extract(path, complete=_reply())["read"] == 1
    second = guidance.extract(path, complete=_reply())
    assert second["read"] == 0 and second["found"] == 0
    assert len(_stored(path)) == 1


def test_a_model_that_finds_nothing_writes_nothing(tmp_path):
    path = _seed(tmp_path)
    out = guidance.extract(path, complete=lambda *a, **k: '{"found": false}')
    assert out["read"] == 1 and out["found"] == 0 and _stored(path) == []


def test_an_unusable_reply_is_dropped_rather_than_guessed_at(tmp_path):
    path = _seed(tmp_path)
    assert guidance.extract(path, complete=lambda *a, **k: "I could not find any "
                                                           "guidance.")["found"] == 0
    assert _stored(path) == []


def test_a_model_that_raises_is_reported_and_the_run_continues(tmp_path):
    path = _seed(tmp_path)

    def boom(*_args, **_kwargs):
        raise RuntimeError("upstream 502")

    out = guidance.extract(path, complete=boom)
    assert out["found"] == 0 and out["errors"] and "upstream 502" in out["errors"][0]


def test_without_a_provider_the_module_says_so_and_does_nothing(tmp_path, monkeypatch):
    path = _seed(tmp_path)
    monkeypatch.setattr(guidance.llm, "provider", lambda: None)
    out = guidance.extract(path)
    assert out["status"] == "no key" and out["found"] == 0
    assert _stored(path) == []


def test_the_excerpt_is_the_window_around_the_guidance_language():
    padding = "x" * 5000
    text = padding + " For 2026, we expect revenue of $1 billion. " + padding
    window = guidance.excerpt(text)
    assert window is not None and "we expect revenue of $1 billion" in window
    assert len(window) <= guidance._WINDOW
    assert guidance.excerpt("A section that says nothing about the year ahead.") is None
