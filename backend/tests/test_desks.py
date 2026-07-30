"""The four ways into the terminal, and what each card is allowed to claim."""

import pytest

import db
import desks


def _row(**kw):
    base = {"ticker": "AAA", "name": "A", "fresh_share": 0.5, "revenue_latest": 40e9,
            "inferred_revenue": None, "curated_revenue": None}
    return {**base, **kw}


def test_the_headline_names_the_two_ends():
    card = desks._major(None, [_row(ticker="TOP", fresh_share=0.73),
                               _row(ticker="MID", fresh_share=0.2),
                               _row(ticker="LOW", fresh_share=0.0)])
    assert "TOP earns 73%" in card["headline"]
    assert "LOW 0%" in card["headline"]


def test_an_inferred_figure_stays_out_of_the_headline():
    """Moderna reads 100% inferred from its whole marketed register rather than from any
    drug's own date. The page's most prominent line should not rest on its weakest
    evidence."""
    card = desks._major(None, [
        _row(ticker="INF", fresh_share=1.0, inferred_revenue=2e9),
        _row(ticker="REAL", fresh_share=0.73),
        _row(ticker="LOW", fresh_share=0.0)])
    assert "INF" not in card["headline"]
    assert "REAL earns 73%" in card["headline"]


def test_a_curated_figure_stays_out_of_the_headline():
    card = desks._major(None, [
        _row(ticker="CUR", fresh_share=0.99, curated_revenue=5e9),
        _row(ticker="REAL", fresh_share=0.73),
        _row(ticker="LOW", fresh_share=0.0)])
    assert "CUR" not in card["headline"]


def test_a_small_company_stays_out_of_the_headline():
    """Sarepta reading 100% off a single product is a true figure and a thin claim, and
    the sentence is about major pharma."""
    card = desks._major(None, [_row(ticker="TINY", fresh_share=1.0, revenue_latest=2e9),
                               _row(ticker="BIG", fresh_share=0.73),
                               _row(ticker="ALSO", fresh_share=0.0)])
    assert "TINY" not in card["headline"]


def test_the_count_is_everything_measurable_not_the_headline_pool():
    """Reusing one list for both reported 14 of 28 measurable when 23 were."""
    card = desks._major(None, [
        _row(ticker="A", fresh_share=1.0, inferred_revenue=1e9),
        _row(ticker="B", fresh_share=0.5),
        _row(ticker="C", fresh_share=0.1),
        _row(ticker="D", fresh_share=None)])
    assert card["detail"].startswith("3 of 4")


def test_no_comparable_pair_gives_no_headline_rather_than_half_a_sentence():
    assert desks._major(None, [_row(ticker="ONLY")])["headline"] is None


# --- the biotech card -----------------------------------------------------------------

def _runway(**kw):
    base = {"ticker": "BIO", "runway_months": 10.0, "funded_to_readout": True,
            "burn_flattered": False}
    return {**base, **kw}


def test_the_biotech_card_leads_on_the_unfunded():
    card = desks._biotech(None, [
        _runway(ticker="SHORT", runway_months=4.0, funded_to_readout=False),
        _runway(ticker="OK")])
    assert "1 reach their next readout only after the cash runs out" in card["headline"]
    assert "SHORT has 4 months" in card["headline"]


def test_a_burn_flattered_by_a_receipt_is_not_counted_as_unfunded():
    """Arrowhead's runway reads 49 years because a licence payment offsets the burn. It
    is not a company about to run out."""
    card = desks._biotech(None, [
        _runway(ticker="ODD", funded_to_readout=False, burn_flattered=True),
        _runway(ticker="OK")])
    assert card["detail"].startswith("0 ")


def test_the_biotech_card_falls_back_to_the_shortest_runway():
    card = desks._biotech(None, [_runway(ticker="OK", runway_months=18.0)])
    assert "shortest runway" in card["headline"]


# --- the frontier and feed cards ------------------------------------------------------

def test_the_frontier_card_leads_on_the_widest_gap():
    """That gap is the desk's subject: a reader taking the programme count for the truth
    would conclude nobody does gene editing."""
    card = desks._frontier(None, [
        {"theme": "Narrow", "companies": 8, "assets": 20, "platform_companies": ["A"] * 8},
        {"theme": "Wide", "companies": 1, "assets": 1, "platform_companies": ["A"] * 15}],
        {"companies_on_platform": 58, "companies": 70})
    assert card["headline"].startswith("Wide spans 15 companies")


def test_the_feed_card_counts_kinds_rather_than_quoting_headlines():
    """Three headlines run together and clipped read as debris, and they are nearly
    always the same kind of thing."""
    feed = ([{"significance": "high", "change_type": "date_slip", "headline": "x"}] * 3
            + [{"significance": "high", "change_type": "leadership_change",
                "headline": "y"}]
            + [{"significance": "low", "change_type": "date_slip", "headline": "z"}])
    card = desks._changed(None, feed)
    assert card["headline"] == "3 trial dates slipped, 1 senior changes"
    assert card["detail"] == "4 ranked high"
    assert card["count"] == 5


# --- which companies a desk covers ----------------------------------------------------

def test_a_desk_covers_its_own_stage_and_the_unplaceable(tmp_path):
    """A company the stage test cannot place stays on both desks rather than falling off
    the terminal: Roche and Bayer file nothing with the SEC."""
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('BIG', 'Big')")
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('BIO', 'Bio')")
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('MYST', 'Mystery')")
    for ticker, metric in (("BIG", "Inventory"), ("BIO", "CashAndEquivalents")):
        cid = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                           (ticker,)).fetchone()[0]
        conn.execute("INSERT INTO financials (company_id, metric, value, period_end,"
                     "  period_type, unit) VALUES (?, ?, 1e8, '2025-12-31',"
                     "  'instant', 'USD')", (cid, metric))
    conn.commit()
    conn.close()
    assert set(desks.tickers_for(path, "major")) == {"BIG", "MYST"}
    assert set(desks.tickers_for(path, "biotech")) == {"BIO", "MYST"}


def test_the_frontier_and_feed_cover_the_universe(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('A', 'A')")
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('B', 'B')")
    conn.commit()
    conn.close()
    assert set(desks.tickers_for(path, "frontier")) == {"A", "B"}
    assert set(desks.tickers_for(path, "changed")) == {"A", "B"}
    assert set(desks.tickers_for(path, None)) == {"A", "B"}
