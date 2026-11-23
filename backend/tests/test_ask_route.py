"""POST /ask: what the page sends is what the Ask box is handed.

The model is stood in, so no key is needed. The route had no test of its own; the box's
behaviour is pinned in test_desk_chat.py, and this pins the seam in front of it.
"""

import pytest
from fastapi.testclient import TestClient

import db
import desk_chat
import main
import seed


@pytest.fixture
def asked(tmp_path, monkeypatch):
    path = tmp_path / "book.db"
    db.init(path)
    seed.load_companies(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    seen = {}

    def answer(question, history=None, context=None, fetch=None, **_):
        seen.update(question=question, history=history, context=context, fetch=fetch)
        return {"ok": True, "answer": "stood in", "steps": []}

    monkeypatch.setattr(desk_chat, "answer", answer)
    return TestClient(main.app), seen


def test_a_question_reaches_the_box_with_its_company_and_its_history(asked):
    client, seen = asked
    got = client.post("/ask", json={
        "question": "Is it funded?", "ticker": "LLY", "name": "Eli Lilly",
        "history": [{"role": "user", "text": "earlier"}]})
    assert got.status_code == 200 and got.json() == {"ok": True, "answer": "stood in",
                                                     "steps": []}
    assert seen["question"] == "Is it funded?"
    assert seen["history"] == [{"role": "user", "text": "earlier"}]
    assert seen["context"] == {"ticker": "LLY", "name": "Eli Lilly", "showing": None}
    assert callable(seen["fetch"])


def test_the_panels_open_on_the_board_reach_the_box_as_they_were_sent(asked):
    """The route passes them on untouched. Which of them the model is told is the box's
    decision (desk_chat.on_screen), so it is made in one place."""
    client, seen = asked
    showing = [{"panel": "news", "ticker": "LLY"}, {"panel": "not_a_panel", "ticker": "x"}]
    got = client.post("/ask", json={"question": "What is new?", "ticker": "LLY",
                                    "showing": showing})
    assert got.status_code == 200
    assert seen["context"]["showing"] == showing


def test_a_request_with_no_question_is_refused_before_the_box_is_asked(asked):
    client, seen = asked
    assert client.post("/ask", json={"ticker": "LLY"}).status_code == 422
    assert seen == {}


def test_asking_is_never_served_from_the_cache_and_clears_nothing():
    import response_cache
    assert not response_cache.cacheable("/ask", "")
    assert any("/ask".startswith(prefix) for prefix in response_cache.QUIET_WRITES)
