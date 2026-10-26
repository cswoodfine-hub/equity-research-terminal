"""A second reader for the evidence grades.

evidence.py grades a row by matching its own words against a rule set, which makes the
grade reproducible and makes it one opinion. evidence_reviewed is meant to say a second
party looked, so the queue is read again and only the agreements are confirmed. The
model is a reader, not a source: it sees the row's own words and nothing else, and a
disagreement writes nothing.
"""

import assumptions as A
import db
import grade_review as G


def _book(tmp_path):
    path = str(tmp_path / "g.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1,'LLY','Lilly')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, modality)"
                 " VALUES (1, 1, 'Verzenio', 'small molecule')")
    conn.commit()
    return path, conn


def _reviewed(conn):
    return {r["key"]: r["evidence_reviewed"] for r in A.rows(conn, 1)}


# --- reading the reply ----------------------------------------------------------------

def test_a_clean_reply_gives_its_grade():
    assert G.parse_reply('{"grade": "filed", "why": "a 10-K"}') == "filed"
    assert G.parse_reply('```json\n{"grade": "measured"}\n```') == "measured"


def test_a_reply_that_is_not_one_of_the_six_is_dropped():
    assert G.parse_reply('{"grade": "vibes"}') is None
    assert G.parse_reply("the grade is probably filed") is None
    assert G.parse_reply("") is None


def test_a_grade_survives_a_reply_whose_json_never_closed():
    """A thinking model spends the budget before it answers. Reading a complete field
    out of a truncated object is reading what is there, not guessing."""
    assert G._grade_in('{"grade": "convention", "why": "Rule or') == "convention"
    assert G._grade_in('{"why": "no grade here"') is None
    assert G._grade_in('{"grade": "vibes"') is None


# --- what reaches the book ------------------------------------------------------------

def test_agreement_confirms_every_row_resting_on_the_sentence(tmp_path):
    path, conn = _book(tmp_path)
    for n in range(3):
        A.save(conn, 1, [{"key": f"forecast_years_{n}", "value": 10.0,
                          "source": "the house convention for a horizon"}])
    conn.commit(); conn.close()
    out = G.review(path, ask=lambda key, src, note: "convention")
    assert out["agreed"] == 3 and out["confirmed"] == 3 and out["disagreed"] == 0
    conn = db.get_connection(path)
    assert all(v == 1 for v in _reviewed(conn).values())
    conn.close()


def test_a_disagreement_writes_nothing_and_keeps_both_opinions(tmp_path):
    """The only honest thing to do with a disagreement about evidence."""
    path, conn = _book(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "source": "a judgement"}])
    conn.commit(); conn.close()
    out = G.review(path, ask=lambda key, src, note: "filed")
    assert out["disagreed"] == 1 and out["confirmed"] == 0
    split = out["disagreements"][0]
    assert split["rules"] == "judgement" and split["second_read"] == "filed"
    conn = db.get_connection(path)
    assert _reviewed(conn)["pos"] == 0, "still in the queue"
    conn.close()


def test_an_unreadable_reply_confirms_nothing(tmp_path):
    path, conn = _book(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "source": "a judgement"}])
    conn.commit(); conn.close()
    out = G.review(path, ask=lambda key, src, note: None)
    assert out["unreadable"] == 1 and out["confirmed"] == 0 and out["agreed"] == 0


def test_a_grade_is_never_changed_by_the_second_read(tmp_path):
    """It confirms or it does not. It never regrades."""
    path, conn = _book(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "source": "a judgement"}])
    conn.commit(); conn.close()
    G.review(path, ask=lambda key, src, note: "filed")
    conn = db.get_connection(path)
    assert A.rows(conn, 1)[0]["evidence"] == "judgement"
    conn.close()


def test_one_sentence_is_asked_about_once_however_many_rows_rest_on_it(tmp_path):
    path, conn = _book(tmp_path)
    for n in range(5):
        A.save(conn, 1, [{"key": "forecast_years", "year": 2020 + n, "value": 10.0,
                          "source": "the house convention for a horizon"}])
    conn.commit(); conn.close()
    asked = []
    G.review(path, ask=lambda key, src, note: asked.append(src) or "convention")
    assert len(asked) == 1, "one sentence, one question"


def test_a_failing_model_stops_rather_than_half_confirming(tmp_path):
    path, conn = _book(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "source": "a judgement"}])
    conn.commit(); conn.close()

    def boom(key, src, note):
        raise RuntimeError("the provider is down")

    out = G.review(path, ask=boom)
    assert "stopped" in out and out["confirmed"] == 0


def test_with_no_provider_it_does_nothing_and_says_so(tmp_path, monkeypatch):
    path, conn = _book(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "source": "a judgement"}])
    conn.commit(); conn.close()
    monkeypatch.setattr(G.llm, "provider", lambda prefer=None: None)
    out = G.review(path)
    assert out["skipped"] and out["confirmed"] == 0
