"""What leads an engine, and the ranking that decides it."""

import datetime as dt

import db
import headlines

TODAY = dt.date(2026, 7, 30)


def _seed(tmp_path):
    path = str(tmp_path / "h.db")
    db.init(path)
    conn = db.get_connection(path)
    for ticker in ("JNJ", "MRK", "SRPT"):
        conn.execute("INSERT INTO companies (ticker, name) VALUES (?, ?)",
                     (ticker, ticker.title()))
    conn.commit()
    return path, conn


def _deal(conn, ticker, counterparty, date, **terms):
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                       (ticker,)).fetchone()[0]
    conn.execute(
        "INSERT INTO deals (company_id, deal_type, counterparty, event_date,"
        "  upfront_usd, equity_usd, milestones_usd, option_usd, total_usd, headline_usd,"
        "  terms_evidence) VALUES (?, 'collaboration', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (cid, counterparty, date, terms.get("upfront"), terms.get("equity"),
         terms.get("milestones"), terms.get("option"), terms.get("total"),
         terms.get("headline"), terms.get("evidence")))
    conn.commit()


def test_a_deal_leads_and_carries_its_structure(tmp_path):
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "Sail Biomedicines", "2026-07-29", upfront=785e6, equity=465e6,
          milestones=140e6, option=2.58e9, headline=2.58e9,
          evidence="Under the terms of the agreements...")
    conn.close()

    rows = headlines.build(path, today=TODAY)
    assert rows[0]["kind"] == "deal"
    assert rows[0]["figure"] == "$2.58bn"
    assert rows[0]["detail"] == (
        "$785m upfront, $465m equity, $140m milestones, $2.58bn option to acquire")


def test_a_deal_with_no_terms_is_not_a_headline(tmp_path):
    """"J&J announces collaboration with Sail" says something happened and nothing about
    whether it counts. Without a figure there is no way to tell a research tie-up from a
    takeover."""
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "Sail Biomedicines", "2026-07-29")
    conn.close()
    assert headlines.build(path, today=TODAY) == []


def test_the_bigger_deal_leads(tmp_path):
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "Small Co", "2026-07-29", total=1e9, headline=1e9)
    _deal(conn, "MRK", "Big Co", "2026-07-28", total=9e9, headline=9e9)
    conn.close()
    assert [r["ticker"] for r in headlines.build(path, today=TODAY)] == ["MRK", "JNJ"]


def test_one_headline_per_company(tmp_path):
    """Four headlines about one filer is a page about that filer, not about the engine."""
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "One", "2026-07-29", total=9e9, headline=9e9)
    _deal(conn, "JNJ", "Two", "2026-07-28", total=8e9, headline=8e9)
    conn.close()
    rows = headlines.build(path, today=TODAY)
    assert [r["ticker"] for r in rows] == ["JNJ"]
    assert rows[0]["headline"].endswith("One")


def test_an_engine_sees_only_its_own_companies(tmp_path):
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "One", "2026-07-29", total=9e9, headline=9e9)
    _deal(conn, "SRPT", "Two", "2026-07-28", total=8e9, headline=8e9)
    conn.close()
    rows = headlines.build(path, tickers=["SRPT"], today=TODAY)
    assert [r["ticker"] for r in rows] == ["SRPT"]


def test_an_old_deal_is_not_a_headline(tmp_path):
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "Old", "2026-05-01", total=9e9, headline=9e9)
    conn.close()
    assert headlines.build(path, today=TODAY) == []


def test_the_order_is_stated_rather_than_scored():
    """A reader who disagrees with the ranking can see it, which is the point of writing
    it down as a tuple instead of computing a score."""
    assert headlines.ORDER.index("deal") < headlines.ORDER.index("approval")
    assert headlines.ORDER.index("approval") < headlines.ORDER.index("leadership")
    assert headlines.ORDER.index("leadership") < headlines.ORDER.index("trial_stopped")


def test_a_trial_starting_is_not_a_trial_stopping():
    """A status change to Recruiting is a programme beginning. Only Terminated, Withdrawn
    and Suspended are the fastest a programme's value ever changes."""
    assert headlines._STOPPED.search("trial NCT1: status Active -> Terminated")
    assert not headlines._STOPPED.search(
        "trial NCT1: status Not yet recruiting -> Recruiting")


# --- the forward view ------------------------------------------------------------------

def _catalyst(conn, ticker, kind, date, title, curated=0, nct=None):
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]
    conn.execute(
        "INSERT INTO catalysts (company_id, catalyst_type, expected_date, title,"
        "  description, is_curated, date_confidence, status)"
        "  VALUES (?, ?, ?, ?, ?, ?, 'estimated', 'pending')",
        (cid, kind, date, title, nct, curated))
    conn.commit()


def test_the_forward_view_is_a_calendar(tmp_path):
    """Soonest first: it answers "what is coming", and a ranking by kind would bury
    tomorrow under something three weeks out."""
    path, conn = _seed(tmp_path)
    _catalyst(conn, "MRK", "data readout", "2026-08-20", "Phase 3, Keytruda")
    _catalyst(conn, "JNJ", "data readout", "2026-08-02", "Phase 2, Something")
    conn.close()
    rows = headlines.ahead(path, today=TODAY)
    assert [r["date"] for r in rows] == ["2026-08-02", "2026-08-20"]


def test_the_firmest_kind_leads_its_day(tmp_path):
    """A decision date outranks the vote that informs it, which outranks a readout the
    registry only estimates."""
    path, conn = _seed(tmp_path)
    _catalyst(conn, "MRK", "data readout", "2026-08-10", "Phase 3, Something")
    _catalyst(conn, "JNJ", "PDUFA", "2026-08-10", "Icotyde PDUFA", curated=1)
    conn.close()
    assert [r["kind"] for r in headlines.ahead(path, today=TODAY)] == [
        "PDUFA", "data readout"]


def test_a_derived_readout_says_it_is_derived(tmp_path):
    """A registry completion date is an estimate that slips, and the box has to say so
    rather than leaving a reader to know it."""
    path, conn = _seed(tmp_path)
    _catalyst(conn, "MRK", "data readout", "2026-08-10", "Phase 3, X", nct="NCT1")
    conn.close()
    row = headlines.ahead(path, today=TODAY)[0]
    assert row["curated"] is False
    confidence = next(p for p in row["summary"] if p["label"] == "Confidence")
    assert "registry primary completion date" in confidence["value"]
    assert any(p["label"] == "Study" and p["value"] == "NCT1" for p in row["summary"])


def test_a_curated_date_says_the_company_stated_it(tmp_path):
    path, conn = _seed(tmp_path)
    _catalyst(conn, "JNJ", "PDUFA", "2026-08-10", "Icotyde PDUFA", curated=1)
    conn.close()
    row = headlines.ahead(path, today=TODAY)[0]
    assert row["curated"] is True
    confidence = next(p for p in row["summary"] if p["label"] == "Confidence")
    assert "curated" in confidence["value"]


def test_nothing_outside_the_window(tmp_path):
    path, conn = _seed(tmp_path)
    _catalyst(conn, "MRK", "data readout", "2026-11-01", "Phase 3, Far off")
    _catalyst(conn, "JNJ", "data readout", "2026-07-01", "Phase 3, Gone by")
    conn.close()
    assert headlines.ahead(path, today=TODAY) == []


def test_the_forward_view_respects_the_engine(tmp_path):
    path, conn = _seed(tmp_path)
    _catalyst(conn, "MRK", "data readout", "2026-08-10", "Phase 3, Theirs")
    _catalyst(conn, "SRPT", "data readout", "2026-08-11", "Phase 3, Ours")
    conn.close()
    rows = headlines.ahead(path, tickers=["SRPT"], today=TODAY)
    assert [r["ticker"] for r in rows] == ["SRPT"]


def test_every_headline_carries_a_summary_to_open(tmp_path):
    """The box is a disclosure, so an item with nothing behind it opens onto nothing."""
    path, conn = _seed(tmp_path)
    _deal(conn, "JNJ", "Sail Biomedicines", "2026-07-29", upfront=785e6, equity=465e6,
          option=2.58e9, headline=2.58e9, evidence="Under the terms...")
    conn.close()
    row = headlines.build(path, today=TODAY)[0]
    labels = [p["label"] for p in row["summary"]]
    assert labels[:3] == ["Upfront", "Equity", "Option to acquire"]
    assert "Counterparty" in labels


def test_a_week_is_the_window():
    """The page answers "what happened since I last looked". A fortnight put things on it
    that had already been read and acted on."""
    assert headlines.LOOKBACK_DAYS == 7


def test_a_decision_date_does_not_claim_the_registry(tmp_path):
    """A PDUFA date is read out of an 8-K. Calling it "derived from the registry" names a
    source that never carried it."""
    path, conn = _seed(tmp_path)
    _catalyst(conn, "JNJ", "PDUFA", "2026-08-10", "Icotyde PDUFA",
              nct="The Company's BLA remains on track for a target action date.")
    conn.close()
    row = headlines.ahead(path, today=TODAY)[0]
    confidence = next(p for p in row["summary"] if p["label"] == "Confidence")
    assert "8-K" in confidence["value"]
    assert "registry" not in confidence["value"]
    # The announcing sentence is a quote, not a study identifier.
    assert not any(p["label"] == "Study" for p in row["summary"])
    assert row["evidence"].startswith("The Company's BLA")
    # Somebody stated it, so it is firm even though it was extracted rather than typed.
    assert row["curated"] is True
