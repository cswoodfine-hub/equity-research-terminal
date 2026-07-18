"""The note layer: rules fallback, mocked Anthropic path, and API failure. No network."""

import datetime as dt
import json
import types

import catalysts
import db
import diff
import insights
import seed


def _seed_feed(db_file):
    """A database with one high-significance change and one catalyst for LLY."""
    db.init(db_file)
    seed.load_companies(db_file)

    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    conn.execute(
        "INSERT INTO trials (nct_id, sponsor_company_id, title, phase, overall_status, "
        "primary_completion_date) VALUES ('NCT001', ?, 'X', 'Phase 3', 'Recruiting', "
        "'2027-06-30')",
        (cid,),
    )
    conn.commit()
    conn.close()

    diff.detect_changes(db_file)  # baseline
    conn = db.get_connection(db_file)
    conn.execute("UPDATE trials SET overall_status='Terminated' WHERE nct_id='NCT001'")
    conn.commit()
    conn.close()
    diff.detect_changes(db_file)  # emits a high status_change

    catalysts.add_catalyst(db_file, "LLY", "PDUFA",
                           (dt.date.today() + dt.timedelta(days=30)).isoformat(),
                           "PDUFA decision")


class _FakeMessages:
    def __init__(self, outcome):
        self._outcome = outcome
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        block = types.SimpleNamespace(type="text", text=self._outcome)
        return types.SimpleNamespace(content=[block])


class _FakeClient:
    def __init__(self, outcome):
        self.messages = _FakeMessages(outcome)


def test_scrub_removes_em_dashes():
    assert "—" not in insights._scrub("Revenue fell — sharply — in Q4.")


def test_rules_note_is_pure_and_lists_the_items():
    items = [
        {"significance": "high", "headline": "LLY trial NCT001: status Recruiting -> Terminated"},
        {"significance": "medium", "headline": "LLY PDUFA: decision (2026-08-17)"},
    ]
    note = insights.build_rules_note("lly", items)
    assert note.startswith("LLY: 2 flagged items (1 high, 1 medium).")
    assert "NCT001" in note and "PDUFA" in note


def test_rules_note_when_nothing_flagged():
    assert "no flagged changes" in insights.build_rules_note("LLY", [])


def test_generate_note_falls_back_to_rules_without_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db_file = tmp_path / "test.db"
    _seed_feed(db_file)

    out = insights.generate_note(db_file, "LLY")
    assert out["model"] == "rules"
    assert out["error"] is None
    assert "Terminated" in out["body"]
    assert out["source_change_ids"], "the note ties back to the change that produced it"

    stored = insights.latest_note(db_file, "LLY")
    assert stored["body"] == out["body"] and stored["model"] == "rules"


def test_generate_note_uses_the_model_when_a_client_is_supplied(tmp_path):
    db_file = tmp_path / "test.db"
    _seed_feed(db_file)
    client = _FakeClient("LLY has one high-severity change — a terminated phase 3.")

    out = insights.generate_note(db_file, "LLY", client=client)
    assert out["model"] == insights.MODEL
    assert out["error"] is None
    assert "—" not in out["body"]  # house style applied

    call = client.messages.calls[0]
    assert call["model"] == insights.MODEL
    assert call["thinking"] == {"type": "adaptive"}
    # Sampling params 400 on this model, and the feed must reach the prompt.
    assert not {"temperature", "top_p", "top_k"} & set(call)
    assert "NCT001" in call["messages"][0]["content"]

    conn = db.get_connection(db_file)
    try:
        row = conn.execute("SELECT model, source_change_ids FROM insights").fetchone()
    finally:
        conn.close()
    assert row["model"] == insights.MODEL and json.loads(row["source_change_ids"])


def test_generate_note_degrades_when_the_api_errors(tmp_path):
    db_file = tmp_path / "test.db"
    _seed_feed(db_file)
    client = _FakeClient(RuntimeError("overloaded"))

    out = insights.generate_note(db_file, "LLY", client=client)
    assert out["model"] == "rules"
    assert "RuntimeError: overloaded" in out["error"]
    assert "Terminated" in out["body"]  # the analyst still gets the facts
