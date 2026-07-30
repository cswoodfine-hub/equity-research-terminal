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
