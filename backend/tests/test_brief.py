"""The Key insights briefing rewrite: hash, write, read back, and the two routes.

The page writes its own rules briefing from a block of facts and shows it unless a
rewrite exists for exactly those facts. These tests hold that contract: a rewrite is
stored under the hash of the facts it read, is never written without a model, is never
returned for different facts, and is never read back as the company's morning note (by
``latest_note``, the note route or the Comps insights excerpt).

No network and no real model: ``llm.provider``, ``llm.model_name`` and ``llm.complete``
are replaced in every test that reaches them, and every database is built under
``tmp_path`` with ``db.init``, never the book.
"""

import hashlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import db
import insights
import seed

FACTS = ("Price: close $812.40, +1.2% on the day, +4.0% on the month\n"
         "Value: twelve-month value $905, rated Buy\n"
         "Next: Phase 3 readout of orforglipron due 2026-11")
OTHER_FACTS = FACTS.replace("$905", "$870")

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")


@pytest.fixture
def brief_db(tmp_path, monkeypatch):
    """A seeded database under tmp_path, and the default path pointed at it, so the
    routes (which pass no path) read and write the same file and never the book."""
    path = tmp_path / "brief.db"
    db.init(path)
    seed.load_companies(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def _rows(path: Path) -> list:
    conn = db.get_connection(path)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT i.horizon, i.body, i.model, i.source_change_ids, c.ticker"
            "  FROM insights i JOIN companies c ON i.company_id = c.id ORDER BY i.id")]
    finally:
        conn.close()


def _no_model(monkeypatch):
    """No note provider, and a model that fails the test if anything still calls it."""
    def must_not_run(*args, **kwargs):
        raise AssertionError("the model was called with no provider configured")

    monkeypatch.setattr(insights.llm, "provider", lambda prefer=None: None)
    monkeypatch.setattr(insights.llm, "model_name", lambda prefer=None: None)
    monkeypatch.setattr(insights.llm, "complete", must_not_run)


def _fake_model(monkeypatch, reply="The close was $812.40."):
    """A configured provider whose completion is ``reply`` (or the reply function's
    result), recording every call."""
    calls = []

    def fake_complete(system, user, max_tokens, prefer=None, thinking_budget=None):
        calls.append({"system": system, "user": user, "max_tokens": max_tokens,
                      "prefer": prefer, "thinking_budget": thinking_budget})
        return reply(len(calls)) if callable(reply) else reply

    monkeypatch.setattr(insights.llm, "provider", lambda prefer=None: "gemini")
    monkeypatch.setattr(insights.llm, "model_name", lambda prefer=None: "fake-gemini")
    monkeypatch.setattr(insights.llm, "complete", fake_complete)
    return calls


# --- brief_hash ---------------------------------------------------------------------


def test_brief_hash_is_stable_for_the_same_facts():
    assert insights.brief_hash(FACTS) == insights.brief_hash(FACTS)
    assert re.fullmatch(r"[0-9a-f]{12}", insights.brief_hash(FACTS))


def test_brief_hash_ignores_surrounding_whitespace():
    """The page and the route may each trim, or not; the key must not depend on it."""
    assert insights.brief_hash(f"  \n{FACTS}\n\n ") == insights.brief_hash(FACTS)


def test_brief_hash_differs_for_different_facts():
    """One changed figure makes a different key, so a rewrite of the old figures is
    never shown against the new ones."""
    assert insights.brief_hash(FACTS) != insights.brief_hash(OTHER_FACTS)


def test_brief_hash_is_the_key_the_page_computes():
    """streamlit_app's Key insights tab recomputes the hash itself to ask for a rewrite,
    so the two must stay the same function: sha1 of the trimmed facts, first 12 hex."""
    page = hashlib.sha1(FACTS.strip().encode("utf-8")).hexdigest()[:12]
    assert insights.brief_hash(f" {FACTS} ") == page


def test_brief_hash_of_no_facts_is_still_a_key():
    assert insights.brief_hash(None) == insights.brief_hash("") == insights.brief_hash("  ")


# --- the prompt ---------------------------------------------------------------------


def test_brief_prompt_keeps_the_house_style():
    """No em dash, and a banned word appears only in the one sentence that lists them."""
    assert "—" not in insights.BRIEF_PROMPT
    bans = re.findall(r"Never use the words[^.]*\.", insights.BRIEF_PROMPT)
    assert len(bans) == 1, "the prompt names the banned words once"
    ban = bans[0]
    assert all(w in ban for w in BANNED)
    rest = insights.BRIEF_PROMPT.replace(ban, "").lower()
    assert [w for w in BANNED if w in rest] == []


def test_brief_prompt_forbids_inventing_a_figure():
    prompt = insights.BRIEF_PROMPT
    assert "Never invent a number" in prompt
    assert "Keep every figure exactly as given" in prompt


def test_brief_prompt_forbids_giving_news_as_the_cause_of_a_move():
    """The data says what moved and what was announced, never that one caused the other:
    the built note says "despite", "with" or "alongside", and the rewrite may too."""
    prompt = insights.BRIEF_PROMPT
    assert "never give news as the reason for a move" in prompt
    assert "despite, with or" in prompt and "alongside news" in prompt


def test_brief_prompt_keeps_est_on_estimated_dates():
    """The facts mark an estimated readout date "est."; the rewrite must not drop it and
    turn an estimate into a stated date."""
    assert 'keep "est." on every date given as an estimate' in insights.BRIEF_PROMPT


# --- write_brief --------------------------------------------------------------------


@pytest.mark.parametrize("facts", ["", "   \n\t ", None])
def test_write_brief_without_facts_returns_an_error_and_writes_nothing(
        brief_db, monkeypatch, facts):
    calls = _fake_model(monkeypatch)
    out = insights.write_brief(brief_db, "lly", facts)
    assert out == {"ticker": "LLY", "body": None, "model": None,
                   "error": "no facts given"}
    assert calls == [], "no facts means no model call"
    assert _rows(brief_db) == []


def test_write_brief_without_a_note_model_returns_no_body_and_writes_nothing(
        brief_db, monkeypatch):
    _no_model(monkeypatch)
    out = insights.write_brief(brief_db, "LLY", FACTS)
    assert out["body"] is None and out["model"] is None
    assert out["error"] and "no note model key" in out["error"]
    assert _rows(brief_db) == []


def test_write_brief_stores_the_scrubbed_rewrite_under_its_facts_hash(
        brief_db, monkeypatch):
    reply = ("the close was $812.40 — up 1.2% on the day.\n"
             "Additionally, the twelve-month value is $905.")
    calls = _fake_model(monkeypatch, reply)

    out = insights.write_brief(brief_db, "lly", f"\n  {FACTS}  \n")

    # House style applied before storage: no em dash, the filler opener gone, and every
    # sentence and line start capitalised.
    expected = ("The close was $812.40, up 1.2% on the day.\n"
                "The twelve-month value is $905.")
    assert out["body"] == expected
    assert "—" not in out["body"] and "additionally" not in out["body"].lower()
    assert out["error"] is None
    assert out["model"] == "fake-gemini"
    assert out["ticker"] == "LLY"
    assert out["horizon"] == f"brief {insights.brief_hash(FACTS)}"
    assert out["source_change_ids"] == []

    # The model saw the brief prompt and the trimmed facts, pinned to the note provider.
    assert len(calls) == 1
    call = calls[0]
    assert call["system"] == insights.BRIEF_PROMPT
    assert call["user"] == f"Company: LLY\n\n{FACTS}\n\nWrite the note."
    assert call["prefer"] == insights.NOTE_PROVIDER
    assert call["max_tokens"] == insights.MAX_TOKENS
    assert call["thinking_budget"] == insights.THINKING_BUDGET

    rows = _rows(brief_db)
    assert rows == [{"horizon": f"brief {insights.brief_hash(FACTS)}", "body": expected,
                     "model": "fake-gemini", "source_change_ids": "[]", "ticker": "LLY"}]


def test_latest_brief_returns_the_rewrite_only_for_its_own_facts(brief_db, monkeypatch):
    _fake_model(monkeypatch, "The close was $812.40.")
    written = insights.write_brief(brief_db, "LLY", FACTS)
    key = insights.brief_hash(FACTS)

    found = insights.latest_brief(brief_db, "lly", key)
    assert found is not None
    assert found["body"] == "The close was $812.40."
    assert found["model"] == "fake-gemini"
    assert found["ticker"] == "LLY"
    assert found["id"] == written["id"]
    assert found["generated_at"] == written["generated_at"]

    assert insights.latest_brief(brief_db, "LLY", insights.brief_hash(OTHER_FACTS)) is None
    assert insights.latest_brief(brief_db, "LLY", "") is None
    assert insights.latest_brief(brief_db, "PFE", key) is None, "a rewrite is per company"


def test_latest_brief_returns_the_newest_rewrite_of_the_same_facts(brief_db, monkeypatch):
    """Two rewrites in the same second: the later one wins on id."""
    _fake_model(monkeypatch, lambda n: f"Rewrite number {n}.")
    insights.write_brief(brief_db, "LLY", FACTS)
    second = insights.write_brief(brief_db, "LLY", FACTS)
    found = insights.latest_brief(brief_db, "LLY", insights.brief_hash(FACTS))
    assert found["body"] == "Rewrite number 2." and found["id"] == second["id"]
    assert len(_rows(brief_db)) == 2, "history is appended, never overwritten"


def test_write_brief_degrades_when_the_model_errors(brief_db, monkeypatch):
    _fake_model(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("overloaded")

    monkeypatch.setattr(insights.llm, "complete", boom)
    out = insights.write_brief(brief_db, "LLY", FACTS)
    assert out == {"ticker": "LLY", "body": None, "model": None,
                   "error": "RuntimeError: overloaded"}
    assert _rows(brief_db) == []


@pytest.mark.parametrize("reply", ["", None])
def test_write_brief_on_an_empty_response_writes_nothing(brief_db, monkeypatch, reply):
    _fake_model(monkeypatch, lambda n: reply)
    out = insights.write_brief(brief_db, "LLY", FACTS)
    assert out["body"] is None and out["error"] == "empty response from the model"
    assert _rows(brief_db) == []


@pytest.mark.parametrize("reply", ["  \n\n ", "\t", "\n"])
def test_write_brief_on_a_whitespace_only_response_writes_nothing(
        brief_db, monkeypatch, reply):
    """A reply of nothing but whitespace is an empty reply: it used to pass the emptiness
    check, scrub to '' and be stored as a blank brief with no error."""
    calls = _fake_model(monkeypatch, reply)
    out = insights.write_brief(brief_db, "LLY", FACTS)
    assert out == {"ticker": "LLY", "body": None, "model": None,
                   "error": "empty response from the model"}
    assert len(calls) == 1, "the model did run; its reply is what was empty"
    assert _rows(brief_db) == []
    assert insights.latest_brief(brief_db, "LLY", insights.brief_hash(FACTS)) is None


# --- a rewrite is not a note ----------------------------------------------------------


def _insert(path: Path, ticker: str, horizon, body: str, model: str = "test") -> int:
    conn = db.get_connection(path)
    try:
        cid = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]
        rowid = conn.execute(
            "INSERT INTO insights (company_id, horizon, body, source_change_ids, model)"
            " VALUES (?, ?, ?, '[]', ?)", (cid, horizon, body, model)).lastrowid
        conn.commit()
        return rowid
    finally:
        conn.close()


def test_a_brief_rewrite_does_not_replace_the_morning_note(brief_db, monkeypatch):
    """The rewrite is written after the note, so it is the newest row; latest_note must
    still return the note, since a rewrite holds only for the facts it was written from."""
    _no_model(monkeypatch)
    note = insights.generate_note(brief_db, "LLY")
    assert note["model"] == insights.RULES_MODEL

    _fake_model(monkeypatch, "The close was $812.40.")
    brief = insights.write_brief(brief_db, "LLY", FACTS)
    assert brief["id"] > note["id"]

    latest = insights.latest_note(brief_db, "LLY")
    assert latest["id"] == note["id"]
    assert latest["body"] == note["body"]
    assert latest["model"] == insights.RULES_MODEL
    assert latest["horizon"] == "on_demand"


def test_latest_note_is_none_when_only_a_brief_rewrite_is_stored(brief_db, monkeypatch):
    _fake_model(monkeypatch, "The close was $812.40.")
    insights.write_brief(brief_db, "LLY", FACTS)
    assert insights.latest_note(brief_db, "LLY") is None
    assert insights.latest_brief(brief_db, "LLY", insights.brief_hash(FACTS)) is not None


def test_latest_note_keeps_a_note_with_no_horizon(brief_db, monkeypatch):
    """The horizon column is nullable. The filter that drops rewrites must not drop a
    note stored without one (a bare `horizon NOT LIKE` would, since NULL is not true)."""
    note_id = _insert(brief_db, "LLY", None, "A note with no horizon.")
    _fake_model(monkeypatch, "The close was $812.40.")
    insights.write_brief(brief_db, "LLY", FACTS)
    latest = insights.latest_note(brief_db, "LLY")
    assert latest["id"] == note_id and latest["body"] == "A note with no horizon."


def test_a_horizon_that_only_starts_with_brief_is_still_a_note(brief_db):
    """Rewrites are stored as 'brief <hash>'; only that prefix, with its space, marks one."""
    note_id = _insert(brief_db, "LLY", "briefing", "A note on a briefing horizon.")
    assert insights.latest_note(brief_db, "LLY")["id"] == note_id


def test_the_note_route_returns_the_note_not_the_rewrite(brief_db, monkeypatch):
    import main
    _no_model(monkeypatch)
    note = insights.generate_note(brief_db, "LLY")
    _fake_model(monkeypatch, "The close was $812.40.")
    insights.write_brief(brief_db, "LLY", FACTS)
    insights.write_brief(brief_db, "PFE", FACTS)

    client = TestClient(main.app)
    got = client.get("/companies/LLY/note").json()
    assert got["id"] == note["id"] and got["body"] == note["body"]
    assert got["error"] is None
    only_brief = client.get("/companies/PFE/note").json()
    assert only_brief["body"] is None and only_brief["model"] is None


def test_the_comps_insights_excerpt_skips_a_brief_rewrite(brief_db, monkeypatch):
    """comps_valuation reads every company's newest insights row into detail.notes.system,
    keeping the last row per company in (generated_at, id) order. A rewrite written after
    the note would win that order, so it is filtered out like it is in latest_note."""
    import datetime as dt
    import comps_valuation

    _no_model(monkeypatch)
    note = insights.generate_note(brief_db, "LLY")
    _fake_model(monkeypatch, "The close was $812.40.")
    brief = insights.write_brief(brief_db, "LLY", FACTS)
    assert brief["id"] > note["id"]
    insights.write_brief(brief_db, "PFE", FACTS)          # PFE has a rewrite and no note
    _insert(brief_db, "MRK", None, "A note with no horizon.", model="rules")

    built = comps_valuation.build(brief_db, today=dt.date(2026, 9, 29))
    by = {r["ticker"]: r for r in built["companies"]}

    lly = by["LLY"]["detail"]["notes"]["system"]
    assert lly is not None
    assert lly["excerpt"] == note["body"][:400]
    assert lly["model"] == insights.RULES_MODEL
    assert "812.40" not in lly["excerpt"]
    assert by["PFE"]["detail"]["notes"]["system"] is None
    mrk = by["MRK"]["detail"]["notes"]["system"]
    assert mrk["excerpt"] == "A note with no horizon." and mrk["model"] == "rules"


# --- the routes ---------------------------------------------------------------------


@pytest.fixture
def client(brief_db):
    import main
    assert Path(db.DB_PATH) == brief_db      # the routes read the tmp database
    return TestClient(main.app)


def test_get_brief_with_no_rewrite_returns_no_body(client):
    response = client.get("/companies/lly/brief", params={"hash": insights.brief_hash(FACTS)})
    assert response.status_code == 200
    assert response.json() == {"ticker": "LLY", "body": None, "model": None,
                               "generated_at": None}


def test_get_brief_without_a_hash_returns_no_body(client, brief_db, monkeypatch):
    _fake_model(monkeypatch)
    insights.write_brief(brief_db, "LLY", FACTS)
    assert client.get("/companies/LLY/brief").json()["body"] is None


def test_post_brief_writes_and_get_reads_it_back_for_the_same_facts(
        client, brief_db, monkeypatch):
    calls = _fake_model(monkeypatch, "the close was $812.40 — up 1.2% on the day.")

    posted = client.post("/companies/lly/brief", json={"facts": FACTS})
    assert posted.status_code == 200
    body = posted.json()
    key = insights.brief_hash(FACTS)
    assert body["hash"] == key
    assert body["error"] is None
    assert body["body"] == "The close was $812.40, up 1.2% on the day."
    assert body["model"] == "fake-gemini"
    assert body["horizon"] == f"brief {key}"
    assert len(calls) == 1

    got = client.get("/companies/LLY/brief", params={"hash": key})
    assert got.status_code == 200
    read = got.json()
    assert read["body"] == body["body"]
    assert read["model"] == "fake-gemini"
    assert read["generated_at"] == body["generated_at"]

    stale = client.get("/companies/LLY/brief",
                       params={"hash": insights.brief_hash(OTHER_FACTS)}).json()
    assert stale["body"] is None, "a rewrite of other figures is never shown"


def test_post_brief_hash_matches_padded_facts(client, monkeypatch):
    """The hash the route returns is the one the page will ask with, padding or not."""
    _fake_model(monkeypatch)
    body = client.post("/companies/LLY/brief", json={"facts": f"\n {FACTS} \n"}).json()
    assert body["hash"] == insights.brief_hash(FACTS)
    found = client.get("/companies/LLY/brief", params={"hash": body["hash"]}).json()
    assert found["body"] == "The close was $812.40."


def test_post_brief_without_a_note_model_writes_nothing(client, brief_db, monkeypatch):
    _no_model(monkeypatch)
    response = client.post("/companies/LLY/brief", json={"facts": FACTS})
    assert response.status_code == 200
    body = response.json()
    assert body["body"] is None and body["model"] is None
    assert "no note model key" in body["error"]
    assert body["hash"] == insights.brief_hash(FACTS)
    assert _rows(brief_db) == []
    assert client.get("/companies/LLY/brief",
                      params={"hash": body["hash"]}).json()["body"] is None


def test_post_brief_with_empty_facts_writes_nothing(client, brief_db, monkeypatch):
    calls = _fake_model(monkeypatch)
    body = client.post("/companies/LLY/brief", json={"facts": "  "}).json()
    assert body["body"] is None and body["error"] == "no facts given"
    assert calls == [] and _rows(brief_db) == []


def test_post_brief_requires_the_facts_field(client, brief_db, monkeypatch):
    calls = _fake_model(monkeypatch)
    assert client.post("/companies/LLY/brief", json={}).status_code == 422
    assert calls == [] and _rows(brief_db) == []


def test_get_brief_for_an_unknown_ticker_returns_no_body(client):
    response = client.get("/companies/zzzz/brief", params={"hash": "abc"})
    assert response.status_code == 200
    assert response.json()["body"] is None and response.json()["ticker"] == "ZZZZ"


def test_post_brief_for_an_unknown_ticker_neither_calls_the_model_nor_errors(
        brief_db, monkeypatch):
    """The ticker is checked before the model, so an unknown one costs no call and the
    route answers with the reason rather than a 500 from the store."""
    import main
    calls = _fake_model(monkeypatch)
    response = TestClient(main.app, raise_server_exceptions=False).post(
        "/companies/zzzz/brief", json={"facts": FACTS})
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "ZZZZ"
    assert body["body"] is None and body["model"] is None
    assert body["error"] == "unknown ticker ZZZZ"
    assert body["hash"] == insights.brief_hash(FACTS)
    assert calls == []
    assert _rows(brief_db) == []


def test_write_brief_for_an_unknown_ticker_returns_the_reason_before_the_model(
        brief_db, monkeypatch):
    calls = _fake_model(monkeypatch)
    out = insights.write_brief(brief_db, "zzzz", FACTS)
    assert out == {"ticker": "ZZZZ", "body": None, "model": None,
                   "error": "unknown ticker ZZZZ"}
    assert calls == [] and _rows(brief_db) == []


def test_write_brief_checks_the_ticker_before_the_model_key(brief_db, monkeypatch):
    """With no note model either, the unknown ticker is the reason given: it is checked
    first, and the model is never reached."""
    _no_model(monkeypatch)
    out = insights.write_brief(brief_db, "ZZZZ", FACTS)
    assert out["error"] == "unknown ticker ZZZZ"
    assert _rows(brief_db) == []
