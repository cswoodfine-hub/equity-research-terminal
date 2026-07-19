"""The note layer: rules fallback, mocked model path, and API failure. No network."""

import datetime as dt
import json

import catalysts
import db
import diff
import insights
import llm
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


def test_rules_note_groups_by_kind_and_leads_with_the_top_item():
    items = [
        {"kind": "change", "significance": "high", "date": "2026-07-18",
         "headline": "LLY trial NCT001: status Recruiting -> Terminated"},
        {"kind": "catalyst", "significance": "medium", "date": "2026-08-17",
         "headline": "LLY PDUFA: decision (2026-08-17)"},
        {"kind": "loe", "significance": "medium", "date": "2027-01-04",
         "headline": "LLY LOE: Verzenio loses exclusivity 2027-01-04"},
    ]
    note = insights.build_rules_note("LLY", items)

    assert "Most significant: LLY trial NCT001" in note
    for heading in ("Changes since the last refresh (1)",
                    "Catalysts inside 60 days (1)",
                    "Loss of exclusivity ahead (1)"):
        assert heading in note
    # Reading order: what changed, then what is coming, then what expires.
    assert (note.index("Changes since") < note.index("Catalysts inside")
            < note.index("Loss of exclusivity"))
    # A date already in the headline is not repeated.
    assert "decision (2026-08-17)\n" in note or note.endswith("decision (2026-08-17)")
    assert "status Recruiting -> Terminated (2026-07-18)" in note


def test_rules_note_keeps_items_of_an_unknown_kind():
    """A new feed kind must not vanish from the note."""
    items = [{"kind": "something_new", "significance": "high", "date": "2026-07-18",
              "headline": "LLY surprise item"}]
    note = insights.build_rules_note("LLY", items)
    assert "Other flagged items (1)" in note and "LLY surprise item" in note


def test_rules_note_counts_one_item_in_the_singular():
    note = insights.build_rules_note("LLY", [{"kind": "loe", "significance": "medium",
                                              "date": "2027-09-27", "headline": "LLY LOE"}])
    assert "1 flagged item (" in note


def test_rules_note_when_nothing_flagged():
    assert "no flagged changes" in insights.build_rules_note("LLY", [])


def test_generate_note_falls_back_to_rules_without_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    db_file = tmp_path / "test.db"
    _seed_feed(db_file)

    out = insights.generate_note(db_file, "LLY")
    assert out["model"] == "rules"
    assert out["error"] is None
    assert "Terminated" in out["body"]
    assert out["source_change_ids"], "the note ties back to the change that produced it"

    stored = insights.latest_note(db_file, "LLY")
    assert stored["body"] == out["body"] and stored["model"] == "rules"


def test_generate_note_uses_the_model_when_one_is_configured(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    _seed_feed(db_file)
    seen = {}

    def fake_complete(system, user, max_tokens):
        seen["system"], seen["user"] = system, user
        return "LLY has one high-severity change — a terminated phase 3."

    monkeypatch.setattr(insights.llm, "provider", lambda: "gemini")
    monkeypatch.setattr(insights.llm, "model_name", lambda: "gemini-2.0-flash")
    monkeypatch.setattr(insights.llm, "complete", fake_complete)

    out = insights.generate_note(db_file, "LLY")
    assert out["model"] == "gemini-2.0-flash"
    assert out["error"] is None
    assert "—" not in out["body"]                 # house style applied
    assert seen["system"] == insights.SYSTEM_PROMPT
    assert "NCT001" in seen["user"]               # the feed reaches the prompt

    conn = db.get_connection(db_file)
    try:
        row = conn.execute("SELECT model, source_change_ids FROM insights").fetchone()
    finally:
        conn.close()
    assert row["model"] == "gemini-2.0-flash" and json.loads(row["source_change_ids"])


def test_generate_note_degrades_when_the_api_errors(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    _seed_feed(db_file)

    def boom(*args, **kwargs):
        raise RuntimeError("overloaded")

    monkeypatch.setattr(insights.llm, "provider", lambda: "gemini")
    monkeypatch.setattr(insights.llm, "complete", boom)

    out = insights.generate_note(db_file, "LLY")
    assert out["model"] == "rules"
    assert "RuntimeError: overloaded" in out["error"]
    assert "Terminated" in out["body"]            # the analyst still gets the facts
