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


def test_a_launch_rate_solved_to_its_ceiling_moves_with_it():
    """Kisunla's rate carries 625mm to 2,300mm over a seven-year fade. Doubling the ceiling
    re-solves the rate to reach 4,600mm the same way; a rate read off the filings keeps."""
    import forecast
    import forecast_view as V
    solved = {"base_revenue": 625.0, "revenue_growth_pct": 0.365963, "growth_fade_years": 7,
              "terminal_growth_pct": 0.0, "revenue_ceiling_musd": 2300.0}
    moved = V.apply_lever({"scalars": solved}, "revenue_ceiling_musd", 4600.0)["scalars"]
    assert moved["revenue_growth_pct"] > 0.365963
    path = forecast.grown_revenue(625.0, moved["revenue_growth_pct"], 7, fade_to=0.0,
                                  fade_years=7)
    assert path[-1] == pytest.approx(4600.0, rel=1e-6)

    filed = {**solved, "revenue_growth_pct": 0.60, "revenue_ceiling_musd": 72000.0}
    kept = V.apply_lever({"scalars": filed}, "revenue_ceiling_musd", 144000.0)["scalars"]
    assert kept["revenue_growth_pct"] == 0.60 and kept["revenue_ceiling_musd"] == 144000.0
    assert V.apply_lever({"scalars": filed}, "growth_fade_years", 0)["scalars"]["growth_fade_years"] == 1


def test_fade_and_ceiling_are_levers_and_the_uncapped_fade_shows_its_peaks(tmp_path):
    import assumptions
    import forecast_view as V
    path = _company(tmp_path, close=1.0)
    conn = db.get_connection(path)
    assumptions.save(conn, 1, [{"key": "revenue_ceiling_musd", "value": 3500,
                                "source": "judgement"}])
    conn.commit()
    conn.close()
    base = V.company_verdict(path, "AMGN")["sotp"]["equity_per_share"]
    path = _company(tmp_path / "b", close=base * 1.3)
    conn = db.get_connection(path)
    assumptions.save(conn, 1, [{"key": "revenue_ceiling_musd", "value": 3500,
                                "source": "judgement"}])
    conn.commit()
    conn.close()
    got = B.company(path, "AMGN")
    by_key = {(l["scope"], l["key"]): l for l in got["levers"]}
    fade = by_key[("asset", "growth_fade_years")]
    assert fade["kind"] == "years" and fade["model"] == 5
    assert (fade["evidence"], fade["basis"]) == ("convention", "the engine's five years, where no fade is stated")
    ceiling = by_key[("asset", "revenue_ceiling_musd")]
    # Uncapped, the product only grows to about 4,000mm over its fade, so no ceiling closes
    # a 30% gap: the lever says so rather than inventing a break.
    assert ceiling["kind"] == "level" and not ceiling["reachable"] and ceiling["break"] is None
    assert ceiling["evidence"] == "judgement"
    assert ("company", "fade_shift") in by_key and ("company", "ceiling_scale") in by_key
    uncapped = by_key[("company", "fade_shift_uncapped")]
    assert uncapped["reachable"] and uncapped["break"] > 5
    assert uncapped["shown"][0]["product"] == "Repatha"
    assert uncapped["shown"][0]["break"] > uncapped["shown"][0]["model"]


def test_years_and_levels_read_in_their_own_units_and_the_sentence_names_the_peak():
    fade = {"scope": "company", "name": "Lilly", "lever": "uncapped growth fade",
            "key": "fade_shift_uncapped", "kind": "years", "model": 4.989, "break": 7.989,
            "reachable": True, "evidence": "convention", "evidence_class": "assumption",
            "shown": [{"product": "Mounjaro", "model": 72000.0, "break": 279226.0}]}
    ceiling = {"scope": "asset", "name": "Foundayo", "lever": "revenue ceiling",
               "key": "revenue_ceiling_musd", "kind": "level", "model": 18000.0,
               "break": 267165.0, "reachable": True, "evidence": None,
               "evidence_class": "assumption"}
    scale = {"scope": "company", "name": "Lilly", "lever": "every revenue ceiling",
             "key": "ceiling_scale", "kind": "scale", "model": 1.0, "break": 8.28,
             "reachable": True, "evidence": "judgement", "evidence_class": "assumption"}
    assert B._value_words(fade, 8) == "8 years" and B._value_words(fade, 7.989) == "8.0 years"
    assert B._value_words(ceiling, 267165.0) == "$267,165mm"
    body = B.sentence({"name": "Lilly", "close": 1137.82, "equity_per_share": 555.21,
                       "direction": "up", "levers": [fade, ceiling, scale], "groups": []})["body"]
    assert ("uncapped growth fade reaches 8.0 years (the model has 5.0 years), which takes "
            "Mounjaro to $279,226mm at peak against $72,000mm") in body[0]
    assert "every revenue ceiling reaches 8.28 times the modelled peak or" not in body[0]
    assert "every revenue ceiling reaches 8.28 times the modelled peak, any one" in body[0]


def test_a_trial_that_changes_nothing_reproduces_the_verdict_exactly(tmp_path):
    """The identity of the whole engine. Every break-point is a search over this
    function, so if it does not agree with company_verdict where nothing has moved,
    every lever it reports is offset by whatever the disagreement is.

    It did not agree. company_verdict subtracts the growth-capital charge from
    enterprise value and price_gap rebuilt equity from part rNPVs alone, which never
    carried it, so a revalued book came back high by the charge: on the real database
    that was 57.65 a share on Lilly, 28.24 on Regeneron and 23.92 on Vertex.
    """
    import forecast_view as V

    path = _company(tmp_path, close=100.0)
    book = B.Book(path, "AMGN")
    assert book.ok
    identity = book.equity_with(lambda part, inputs: None, lambda part, scalars: None)
    assert identity == pytest.approx(
        V.company_verdict(path, "AMGN")["sotp"]["equity_per_share"], abs=1e-9)


def test_the_rebuilt_book_pays_the_growth_charge(tmp_path, monkeypatch):
    """The defect itself. price_gap took no growth charge, so the book it rebuilt was
    flat in it: a filer charging nothing per dollar of revenue added and one charging
    thirty cents came out at the same equity per share, and every lever searched over
    that function was offset by the difference. On the real database the offset was
    57.65 a share on Lilly, 28.24 on Regeneron and 23.92 on Vertex.

    The fixture company is too small to measure a pooled charge or a launch rate from,
    so the launch value and the charge are both handed in.
    """
    import forecast_view as V

    path = _company(tmp_path, close=100.0)
    book = B.Book(path, "AMGN")
    assert book.ok
    monkeypatch.setattr(V, "_future_pipeline",
                        lambda *a, **k: {"value": 0.0, "wacc": 0.08})
    book.growth_opening = 3000.0
    parts = [{"dcf_years": [2026, 2027],
              "pnl_share": [{"revenue": 3300.0}, {"revenue": 3600.0}]}]

    book.growth_share = {"value": 0.0, "basis": "nothing charged"}
    free = book.price_gap(10_000.0, parts)
    book.growth_share = {"value": 0.30, "basis": "thirty cents a dollar added"}
    charged = book.price_gap(10_000.0, parts)

    assert charged < free                       # before the fix these were equal
    # And by the charge itself, carried to the price date and put on a per-share basis.
    expected = V.growth_charge(parts, book.anchor, 0.08, book.growth_share,
                               opening=book.growth_opening)["value"]
    assert free - charged == pytest.approx(
        expected * book.carry * 1e6 / book.shares, rel=1e-9)


def test_the_charge_follows_the_revenue_path_it_is_given(tmp_path):
    """Capital the book's growth needs, so a book that grows nothing needs none, and
    the first step out of the reported year is charged like any other."""
    import forecast_view as V

    share = {"value": 0.5, "basis": "half a dollar per dollar added"}
    years = [2026, 2027]
    rising = [{"dcf_years": years, "pnl_share": [{"revenue": 1100.0},
                                                 {"revenue": 1200.0}]}]
    flat = [{"dcf_years": years, "pnl_share": [{"revenue": 1000.0},
                                               {"revenue": 1000.0}]}]
    # Undiscounted the charge is half of 100 added in each year, from an opening of
    # 1,000. Discounting at zero makes the arithmetic readable.
    assert V.growth_charge(rising, "2025-12-31", 0.0, share,
                           opening=1000.0)["value"] == pytest.approx(100.0)
    assert V.growth_charge(flat, "2025-12-31", 0.0, share,
                           opening=1000.0)["value"] == pytest.approx(0.0)
    # A year that shrinks is not credited back.
    falling = [{"dcf_years": years, "pnl_share": [{"revenue": 900.0},
                                                  {"revenue": 800.0}]}]
    assert V.growth_charge(falling, "2025-12-31", 0.0, share,
                           opening=1000.0)["value"] == pytest.approx(0.0)


def test_the_opening_rides_out_so_a_rebuild_starts_where_the_book_did(tmp_path):
    """Charged from the first modelled year instead, the step out of the reported year
    goes uncharged and the book gets its first year of growth free. 500 of it here."""
    import forecast_view as V

    share = {"value": 0.5, "basis": "half a dollar per dollar added"}
    parts = [{"dcf_years": [2026], "pnl_share": [{"revenue": 2000.0}]}]
    from_reported = V.growth_charge(parts, "2025-12-31", 0.0, share, opening=1000.0)
    from_nothing = V.growth_charge(parts, "2025-12-31", 0.0, share, opening=None)
    assert from_reported["value"] == pytest.approx(500.0)
    assert from_nothing["value"] == pytest.approx(0.0)
    # And it rides back out, on every path, so a caller never has to guess it.
    assert from_reported["opening"] == 1000.0
    assert V.growth_charge(parts, None, 0.0, share, opening=1000.0)["opening"] == 1000.0


def _company_priced_later(tmp_path, close, as_of="2026-09-21"):
    """The fixture prices on the valuation date itself, so its stub is nil and the
    carry is exactly one. The carry only exists where the close is later."""
    path = _company(tmp_path, close=close)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO prices (company_id, as_of, close, interval, source)"
                 " VALUES (1, ?, ?, '1d', 't')", (as_of, close))
    conn.commit()
    conn.close()
    return path


def test_the_carry_moves_with_the_trials_own_rate(tmp_path):
    """The carry rolls the year-end value forward to the close at the cost of equity.
    It was frozen at the base rate, so a trial that discounted every product a point
    harder still rolled the stub forward at the old rate. That is the one stretch of
    time the shift did not reach, and it runs the other way: a higher required return
    compounds the year-end value faster, so freezing it overstated what a rate rise
    costs, by 3.32 a share on Lilly at a full point."""
    path = _company_priced_later(tmp_path, close=100.0)
    book = B.Book(path, "AMGN")
    assert book.base_ke is not None and book.years_to_price > 0.5

    flat = [dict(p) for p in book.parts]
    assert book.rate_shift(flat) == pytest.approx(0.0)
    assert book.carry_for(flat) == pytest.approx(book.carry)

    harder = [{**p, "wacc": (p.get("wacc") or 0.0) + 0.01} for p in book.parts]
    assert book.rate_shift(harder) == pytest.approx(0.01)
    assert book.carry_for(harder) == pytest.approx(
        (1.0 + book.base_ke + 0.01) ** book.years_to_price)
    assert book.carry_for(harder) > book.carry


def test_composition_alone_never_moves_the_carry(tmp_path):
    """A lever that drops a product, or one that only moves revenue, is not a
    statement about the cost of capital. Weighting on the base book and averaging each
    part's own change rather than changing the average is what keeps it at nil."""
    path = _company_priced_later(tmp_path, close=100.0)
    book = B.Book(path, "AMGN")

    dropped = [dict(p) for p in book.parts[:-1]]
    assert book.rate_shift(dropped) == pytest.approx(0.0)
    assert book.carry_for(dropped) == pytest.approx(book.carry)

    richer = [{**p, "rnpv_share": (p.get("rnpv_share") or 0.0) * 3} for p in book.parts]
    assert book.rate_shift(richer) == pytest.approx(0.0)
    assert book.carry_for(richer) == pytest.approx(book.carry)

    # A part the base book never had cannot move it either.
    assert book.rate_shift([{"asset_id": 9999, "wacc": 0.5}]) == pytest.approx(0.0)
