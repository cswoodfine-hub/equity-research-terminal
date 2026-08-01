"""The engine as boxes: what area means, and what it refuses to mean."""

import db
import marketmap


def _universe(tmp_path):
    path = str(tmp_path / "m.db")
    db.init(path)
    conn = db.get_connection(path)
    for ticker, revenue, cash in (("BIG", 40e9, None), ("MID", 2e9, None),
                                  ("CG", 0, 300e6)):
        conn.execute("INSERT INTO companies (ticker, name) VALUES (?, ?)",
                     (ticker, ticker.title()))
        cid = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                           (ticker,)).fetchone()[0]
        conn.execute("INSERT INTO financials (company_id, metric, value, period_end,"
                     "  period_type, fiscal_year, unit) VALUES (?, 'Revenues', ?,"
                     "  '2025-12-31', 'FY', 2025, 'USD')", (cid, revenue))
        if cash:
            conn.execute("INSERT INTO financials (company_id, metric, value, period_end,"
                         "  period_type, unit) VALUES (?, 'CashAndEquivalents', ?,"
                         "  '2026-03-31', 'instant', 'USD')", (cid, cash))
        if ticker == "CG":
            conn.execute("INSERT INTO company_themes (company_id, theme, evidence)"
                         " VALUES (?, 'CAR-T', 'x')", (cid,))
        for day, close in (("-80 days", 100.0), ("-40 days", 105.0), ("-30 days", 110.0),
                           ("-20 days", 115.0), ("-1 days", 120.0)):
            conn.execute("INSERT INTO prices (company_id, as_of, close, interval)"
                         "  VALUES (?, date('now', ?), ?, '1d')", (cid, day, close))
    conn.commit()
    conn.close()
    return path


def test_a_revenue_engine_is_sized_by_revenue(tmp_path):
    out = marketmap.build(_universe(tmp_path), engine="pharma")
    assert out["metric"] == marketmap.BY_REVENUE
    assert [r["ticker"] for r in out["rows"]] == ["BIG"]
    assert out["rows"][0]["size"] == 40e9


def test_a_platform_engine_is_sized_by_cash(tmp_path):
    """A developer with no product has no revenue to be sized by, and cash is what it has
    and what decides how long it lasts."""
    out = marketmap.build(_universe(tmp_path), engine="cellgene")
    assert out["metric"] == marketmap.BY_CASH
    assert [r["ticker"] for r in out["rows"]] == ["CG"]
    assert out["rows"][0]["size"] == 300e6


def test_a_company_the_metric_cannot_size_is_counted_not_drawn(tmp_path):
    """An area of nothing reads as a company of nothing."""
    path = str(tmp_path / "n.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('NONE', 'None Inc')")
    conn.commit()
    conn.close()
    out = marketmap.build(path)          # the whole universe, so nothing is filtered out
    assert out["rows"] == []
    assert out["unsized"] == ["NONE"]


def test_the_boxes_are_largest_first(tmp_path):
    out = marketmap.build(_universe(tmp_path))
    assert [r["size"] for r in out["rows"]] == sorted(
        [r["size"] for r in out["rows"]], reverse=True)


def test_the_move_is_read_over_the_window(tmp_path):
    out = marketmap.build(_universe(tmp_path), engine="pharma")
    assert abs(out["rows"][0]["change"] - 0.20) < 0.01


def test_a_short_price_series_has_no_move(tmp_path):
    """An unknown move is not a flat one, and the box says so by taking no colour."""
    path = str(tmp_path / "s.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('THIN', 'Thin')")
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    conn.execute("INSERT INTO financials (company_id, metric, value, period_end,"
                 "  period_type, fiscal_year, unit) VALUES (?, 'Revenues', 9e9,"
                 "  '2025-12-31', 'FY', 2025, 'USD')", (cid,))
    conn.execute("INSERT INTO prices (company_id, as_of, close, interval)"
                 "  VALUES (?, date('now','-2 days'), 10.0, '1d')", (cid,))
    conn.commit()
    conn.close()
    assert marketmap.build(path, engine="pharma")["rows"][0]["change"] is None
