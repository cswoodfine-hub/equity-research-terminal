"""The value each assumption must reach, moved alone, for the model to meet the price."""

import math

import pytest

import breakpoints as B
import db


def test_solve_finds_the_crossing_from_the_current_value():
    got = B.solve(lambda x: x - 0.37, 0.1, 0.0, 1.0)
    assert got["reachable"] and got["value"] == pytest.approx(0.37, abs=1e-9)
    # Downward: the crossing sits below the current value.
    got = B.solve(lambda x: x - 0.02, 0.1, 0.0, 1.0)
    assert got["value"] == pytest.approx(0.02, abs=1e-9)


def test_a_year_is_the_first_whole_year_that_crosses():
    got = B.solve(lambda y: y - 2031.4, 2028, 2013, 2058, integer=True)
    assert got == {"value": 2032, "reachable": True, "bound": None}


def test_a_lever_that_cannot_get_there_alone_says_so():
    got = B.solve(lambda x: 5.0 - x, 0.5, 0.0, 1.0)
    assert not got["reachable"] and got["value"] is None and got["bound"] == 1.0
    assert B.solve(lambda x: math.nan, 0.5, 0.0, 1.0)["reachable"] is False


def _company(tmp_path, close):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = str(tmp_path / "bp.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AMGN', 'Amgen')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed) VALUES (1, 1, 'Repatha', 1)")
    rows = [("therapy_mode", None, "marketed", "approved and selling"),
            ("base_revenue", 3000, None, "Amgen 10-K (0000318154-26-000010)"),
            ("revenue_growth_pct", 0.10, None, "Amgen 10-Q (0000318154-26-000126)"),
            ("terminal_growth_pct", 0.0, None, "convention: faded to flat"),
            ("forecast_start_year", 2026, None, "the year after the last reported full year"),
            ("forecast_years", 10, None, "convention"),
            ("wacc", 0.08, None, "judgement"), ("pos", 1.0, None, "approved and selling"),
            ("cogs_pct", 0.3, None, "filed lines"), ("sga_pct", 0.2, None, "filed lines"),
            ("rd_pct", 0.1, None, "filed lines"), ("tax_rate", 0.15, None, "filed lines")]
    import assumptions
    assumptions.save(conn, 1, [{"key": k, "value": v, "text_value": t, "source": s}
                               for k, v, t, s in rows])
    for metric, value in (("Revenues", 3000e6), ("WeightedAverageDilutedShares", 100e6)):
        conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                     " VALUES (1, ?, 'FY', 2025, '2025-12-31', ?, 'USD')", (metric, value))
    for metric, value in (("CashAndEquivalents", 1000e6), ("TotalDebt", 3000e6)):
        conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                     " VALUES (1, ?, 'instant', 2025, '2025-12-31', ?, 'USD')", (metric, value))
    conn.execute("INSERT INTO prices (company_id, as_of, close, interval, source) VALUES (1, '2025-12-31', ?, '1d', 't')", (close,))
    conn.commit()
    conn.close()
    return path


def test_the_break_point_is_where_equity_meets_the_price(tmp_path):
    """Moved to its break-point, a lever makes equity per share equal the close; the
    growth row rests on a filing and the discount rate on a judgement, and each says so."""
    import forecast_view as V
    path = _company(tmp_path, close=1.0)
    base = V.company_verdict(path, "AMGN")["sotp"]["equity_per_share"]
    close = base * 1.3
    path = _company(tmp_path / "b", close=close)
    got = B.company(path, "AMGN")
    assert got["ok"] and got["direction"] == "up"
    growth = next(l for l in got["levers"] if l["key"] == "revenue_growth_pct")
    assert growth["reachable"] and growth["break"] > 0.10
    assert (growth["evidence"], growth["evidence_class"]) == ("filed", "evidence")
    rate = next(l for l in got["levers"] if l["key"] == "wacc" and l["scope"] == "asset")
    assert rate["break"] < 0.08 and rate["evidence_class"] == "assumption"

    import assumptions, forecast
    conn = db.get_connection(path)
    inputs = assumptions.load(conn, 1)
    conn.close()
    trial = V.apply_lever(inputs, "revenue_growth_pct", growth["break"])
    moved = forecast.build(trial)["rnpv"]
    assert (moved * 1e6 + (1000e6 - 3000e6)) / 100e6 == pytest.approx(close, rel=1e-4)


def test_groups_read_the_file_and_match_what_the_company_carries(tmp_path):
    import risk_groups
    path = tmp_path / "groups.csv"
    path.write_text(
        "# c\ngroup,kind,ticker,member,source,quote,note\n"
        "Lp(a) lowering,mechanism,AMGN,Olpasiran,NCT05581303,\"q\",\n"
        "Lp(a) lowering,mechanism,LLY,Lepodisiran,NCT06292013,\"q\",\n"
        "Medicare price negotiation,payer,AMGN,Otezla,0000318154-26-000126,\"q\",\n"
        "Medicare price negotiation,payer,AMGN,Enbrel,x,\"q\",\n"
        "Nonsense,other,AMGN,Otezla,x,\"q\",\n")
    parts = [{"asset_id": 1, "name": "Olpasiran"}, {"asset_id": 2, "name": "Otezla"},
             {"line": "Other products", "rnpv": 1.0}]
    got = {g["group"]: g for g in risk_groups.for_company("AMGN", parts, path)}
    assert set(got) == {"Lp(a) lowering", "Medicare price negotiation"}
    assert got["Lp(a) lowering"]["elsewhere"] == ["LLY"]
    assert [m["name"] for m in got["Medicare price negotiation"]["members"]] == ["Otezla"]


def test_the_sentence_names_the_three_with_least_room_and_their_evidence():
    levers = [
        {"scope": "asset", "name": "MariTide", "lever": "peak uptake", "key": "penetration_peak_pct",
         "kind": "scale", "model": 1.0, "break": 0.9, "reachable": True, "evidence": "judgement",
         "evidence_class": "assumption", "shown": [{"model": 0.03, "break": 0.027}]},
        {"scope": "asset", "name": "MariTide", "lever": "net price", "key": "net_price_per_patient",
         "kind": "price", "model": 0.0033, "break": 0.0031, "reachable": True, "evidence": "analogue",
         "evidence_class": "partial evidence"},
        {"scope": "company", "name": "Amgen", "lever": "every discount rate", "key": "wacc_shift",
         "kind": "rate", "model": 0.071, "break": 0.0715, "reachable": True, "evidence": "measured",
         "evidence_class": "evidence"},
        {"scope": "asset", "name": "Repatha", "lever": "near-term growth", "key": "revenue_growth_pct",
         "kind": "rate", "model": 0.24, "break": 0.19, "reachable": True, "evidence": "filed",
         "evidence_class": "evidence"},
    ]
    result = {"name": "Amgen", "close": 376.35, "equity_per_share": 379.15, "direction": "down",
              "levers": levers, "groups": []}
    body = B.sentence(result, lambda name: 320.66 if name == "MariTide" else None)["body"]
    assert body[0].startswith("Amgen reads $379.15 against a $376.35 price, and holds it while")
    assert "MariTide's peak uptake stays above 2.70%" in body[0] and "Repatha" in body[0]
    assert "net price" not in body[0]                  # one lever per product
    assert body[1].startswith("We have evidence for every discount rate (measured data) and Repatha's near-term growth (the filings); ")
    assert "MariTide's peak uptake (a judgement) remains an assumption" in body[1]
    assert body[2] == "If MariTide fails outright, Amgen is worth $320.66 a share."
