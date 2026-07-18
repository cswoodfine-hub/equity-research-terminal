"""Curated catalysts CRUD + calendar window, no network."""

import datetime as dt

import pytest

import catalysts
import db
import seed


def test_add_list_delete(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)

    near = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    far = (dt.date.today() + dt.timedelta(days=200)).isoformat()
    near_id = catalysts.add_catalyst(db_file, "LLY", "PDUFA", near, "Near PDUFA")
    catalysts.add_catalyst(db_file, "MRK", "data readout", far, "Far readout")

    # The 90-day calendar shows only the near catalyst.
    calendar = catalysts.list_catalysts(db_file, within_days=90)
    assert [c["ticker"] for c in calendar] == ["LLY"]
    assert calendar[0]["is_curated"] == 1 and calendar[0]["status"] == "pending"

    with pytest.raises(ValueError):
        catalysts.add_catalyst(db_file, "ZZZZ", "PDUFA", near, "bad ticker")

    assert catalysts.delete_catalyst(db_file, near_id) is True
    assert catalysts.list_catalysts(db_file, within_days=90) == []  # far one is beyond 90d


def _trial(conn, nct, ticker, phase, status, due, title="A study", asset_id=None):
    cid = conn.execute("SELECT id FROM companies WHERE ticker=?", (ticker,)).fetchone()[0]
    conn.execute(
        "INSERT INTO trials (nct_id, sponsor_company_id, asset_id, title, phase,"
        " overall_status, primary_completion_date) VALUES (?,?,?,?,?,?,?)",
        (nct, cid, asset_id, title, phase, status, due))


def _seed_trials(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    soon = (dt.date.today() + dt.timedelta(days=120)).isoformat()
    late = (dt.date.today() + dt.timedelta(days=900)).isoformat()
    past = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    conn = db.get_connection(db_file)
    try:
        _trial(conn, "NCT_P3", "LLY", "Phase 3", "Recruiting", soon, "Tirzepatide study")
        _trial(conn, "NCT_P3B", "MRK", "Phase 3", "Active not recruiting", soon)
        _trial(conn, "NCT_P2", "LLY", "Phase 2", "Recruiting", soon)       # wrong phase
        _trial(conn, "NCT_STOP", "LLY", "Phase 3", "Terminated", soon)     # stopped
        _trial(conn, "NCT_FAR", "LLY", "Phase 3", "Recruiting", late)      # outside window
        _trial(conn, "NCT_PAST", "LLY", "Phase 3", "Recruiting", past)     # already due
        conn.commit()
    finally:
        conn.close()
    return soon


def test_derive_readouts_selects_only_live_near_term_phase_three(tmp_path):
    db_file = tmp_path / "test.db"
    soon = _seed_trials(db_file)

    result = catalysts.derive_readouts(db_file)
    assert result["added"] == 2 and result["total"] == 2

    rows = catalysts.list_catalysts(db_file, within_days=365)
    assert {r["ticker"] for r in rows} == {"LLY", "MRK"}
    row = next(r for r in rows if r["ticker"] == "LLY")
    assert row["catalyst_type"] == "data readout"
    assert row["expected_date"] == soon
    assert row["is_curated"] == 0                      # derived, not the analyst's
    assert row["source_url"].endswith("NCT_P3")        # traceable to its trial


def test_derive_readouts_is_idempotent_and_tracks_a_slip(tmp_path):
    db_file = tmp_path / "test.db"
    _seed_trials(db_file)
    catalysts.derive_readouts(db_file)

    # Re-running adds nothing: the registry URL is the row's identity.
    again = catalysts.derive_readouts(db_file)
    assert again["added"] == 0 and again["updated"] == 0

    slipped = (dt.date.today() + dt.timedelta(days=200)).isoformat()
    conn = db.get_connection(db_file)
    conn.execute("UPDATE trials SET primary_completion_date=? WHERE nct_id='NCT_P3'",
                 (slipped,))
    conn.commit()
    conn.close()

    assert catalysts.derive_readouts(db_file)["updated"] == 1
    rows = catalysts.list_catalysts(db_file, within_days=365)
    assert next(r for r in rows if r["ticker"] == "LLY")["expected_date"] == slipped


def test_accepting_a_readout_protects_it_from_the_next_refresh(tmp_path):
    """The analyst's judgement outranks the derivation."""
    db_file = tmp_path / "test.db"
    _seed_trials(db_file)
    catalysts.derive_readouts(db_file)
    row = next(r for r in catalysts.list_catalysts(db_file, within_days=365)
               if r["ticker"] == "LLY")

    assert catalysts.accept_catalyst(db_file, row["id"]) is True
    assert catalysts.accept_catalyst(db_file, row["id"]) is False   # already curated

    # The trial stops, so the derivation would withdraw it. The accepted row stays.
    conn = db.get_connection(db_file)
    conn.execute("UPDATE trials SET overall_status='Terminated' WHERE nct_id='NCT_P3'")
    conn.commit()
    conn.close()

    catalysts.derive_readouts(db_file)
    kept = catalysts.list_catalysts(db_file, within_days=365)
    assert any(r["id"] == row["id"] for r in kept)


def test_derived_rows_are_withdrawn_when_the_trial_stops(tmp_path):
    db_file = tmp_path / "test.db"
    _seed_trials(db_file)
    catalysts.derive_readouts(db_file)

    conn = db.get_connection(db_file)
    conn.execute("UPDATE trials SET overall_status='Withdrawn' WHERE nct_id='NCT_P3'")
    conn.commit()
    conn.close()

    assert catalysts.derive_readouts(db_file)["withdrawn"] == 1
    assert {r["ticker"] for r in catalysts.list_catalysts(db_file, within_days=365)} == {"MRK"}


def test_month_only_dates_are_marked_and_do_not_say_readout_twice(tmp_path):
    """CT.gov reports some completion dates to the month only, 15% of the real set."""
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    month = (dt.date.today() + dt.timedelta(days=120)).strftime("%Y-%m")
    conn = db.get_connection(db_file)
    _trial(conn, "NCT_M", "LLY", "Phase 3", "Recruiting", month, "Retatrutide study")
    conn.commit()
    conn.close()

    catalysts.derive_readouts(db_file)
    row = catalysts.list_catalysts(db_file, within_days=365)[0]
    assert row["date_confidence"] == "month"
    # catalyst_type already says readout; the title must not repeat it.
    assert "readout" not in row["title"].lower()
    assert row["title"].startswith("Phase 3, ")
