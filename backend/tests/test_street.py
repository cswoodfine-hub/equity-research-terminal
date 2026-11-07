"""The book against the street: agreement reported, accuracy left to the scorer."""

import db
import street


def _book(tmp_path):
    path = str(tmp_path / "s.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AAA', 'AAA')")
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (2, 'BBB', 'BBB')")
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (3, 'CCC', 'CCC')")
    for cid, tk, price, fv in ((1, "AAA", 100.0, 150.0), (2, "BBB", 100.0, 60.0), (3, "CCC", 100.0, 120.0)):
        conn.execute("INSERT INTO model_calls (as_of, ticker, cohort, price, price_date, fair_value, upside_12m)"
                     " VALUES ('2026-10-25', ?, 'biotech', ?, '2026-10-24', ?, ?)",
                     (tk, price, fv, fv / price - 1))
    conn.execute("INSERT INTO consensus_estimates (company_id, metric, period, value, as_of, low, high, note)"
                 " VALUES (1, 'PriceTarget', '12M', 130.0, '2026-10-30', 110, 160, '4 buy, 1 hold, 0 sell')")
    conn.execute("INSERT INTO consensus_estimates (company_id, metric, period, value, as_of, low, high, note)"
                 " VALUES (2, 'PriceTarget', '12M', 140.0, '2026-10-30', 120, 170, '6 buy, 0 hold, 0 sell')")
    conn.execute("INSERT INTO consensus_estimates (company_id, metric, period, value, as_of, low, high, note)"
                 " VALUES (3, 'PriceTarget', '12M', 125.0, '2026-10-30', 120, 130, '1 buy, 1 hold, 0 sell')")
    conn.commit()
    conn.close()
    return path


def test_stances_are_read_from_the_sign_of_each_upside(tmp_path):
    out = street.build(_book(tmp_path))
    by = {r["ticker"]: r for r in out["rows"]}
    assert by["AAA"]["stance"] == "both above the price"
    assert by["BBB"]["stance"] == "book below, street above"       # the book stands alone
    assert out["totals"]["alone"] == 1


def test_a_target_from_two_analysts_is_shown_but_not_read_as_the_street(tmp_path):
    out = street.build(_book(tmp_path))
    ccc = next(r for r in out["rows"] if r["ticker"] == "CCC")
    assert ccc["analysts"] == 2
    assert ccc["stance"] == "street too thin to read"
    assert out["totals"]["readable"] == 2


def test_the_analyst_count_comes_from_the_note():
    assert street._analysts("20 buy, 1 hold, 1 sell; per US-listed share") == 22
    assert street._analysts("12 estimates, per US-listed share") is None
