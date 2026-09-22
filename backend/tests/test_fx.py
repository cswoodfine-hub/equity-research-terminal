"""FX to USD from the ECB set: the parse, the store, and the never-fabricate rule."""

import datetime as dt

import pytest

import asset_revenue
import db
import fx
import seed
from fetchers.fx_ecb import FxEcbFetcher

_ECB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube><Cube time='2026-07-24'>
    <Cube currency='USD' rate='1.10'/>
    <Cube currency='GBP' rate='0.85'/>
    <Cube currency='DKK' rate='7.46'/>
    <Cube currency='CHF' rate='0.95'/>
  </Cube></Cube>
</gesmes:Envelope>"""


def test_parse_gives_usd_per_unit_with_usd_at_one():
    as_of, rates = fx.parse_ecb(_ECB_XML)
    assert as_of == "2026-07-24"
    assert rates["USD"] == pytest.approx(1.0)          # USD per USD is exactly one
    assert rates["EUR"] == pytest.approx(1.10)         # 1 EUR = 1.10 USD
    assert rates["GBP"] == pytest.approx(1.10 / 0.85)  # via the EUR cross
    assert rates["DKK"] == pytest.approx(1.10 / 7.46)


def test_parse_rejects_a_set_without_usd():
    with pytest.raises(ValueError, match="no USD"):
        fx.parse_ecb(_ECB_XML.replace("USD", "SEK"))


def test_store_and_latest_roundtrip(tmp_path):
    db_file = tmp_path / "t.db"
    db.init(db_file)
    _, rates = fx.parse_ecb(_ECB_XML)
    fx.store(db_file, "2026-07-24", rates)
    latest = fx.latest_usd_rates(db_file)
    assert latest["as_of"] == "2026-07-24"
    assert latest["GBP"] == pytest.approx(1.10 / 0.85)


def test_latest_takes_the_newest_date(tmp_path):
    db_file = tmp_path / "t.db"
    db.init(db_file)
    fx.store(db_file, "2026-07-20", {"USD": 1.0, "GBP": 1.20})
    fx.store(db_file, "2026-07-24", {"USD": 1.0, "GBP": 1.29})
    assert fx.latest_usd_rates(db_file)["GBP"] == pytest.approx(1.29)


def test_to_usd_never_fabricates_a_missing_rate():
    rates = {"USD": 1.0, "GBP": 1.29, "as_of": "2026-07-24"}
    assert fx.to_usd(100.0, "GBP", rates) == pytest.approx(129.0)
    assert fx.to_usd(100.0, "JPY", rates) is None      # no rate: not zero, unknown
    assert fx.to_usd(None, "USD", rates) is None
    assert fx.to_usd(100.0, None, rates) is None


def test_empty_rate_store_reports_no_date(tmp_path):
    db_file = tmp_path / "t.db"
    db.init(db_file)
    assert fx.latest_usd_rates(db_file) == {"as_of": None}


def test_universe_at_risk_carries_usd_when_a_rate_exists(tmp_path):
    db_file = tmp_path / "t.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    this_year = dt.date.today().year
    cid = conn.execute("SELECT id FROM companies WHERE ticker='NVO'").fetchone()[0]
    cur = conn.execute("INSERT INTO assets (owner_company_id, brand_name,"
                       " internal_code, modality, is_marketed) VALUES"
                       " (?, 'Wegovy', 'W1', 'small molecule', 1)", (cid,))
    aid = cur.lastrowid
    conn.execute("INSERT INTO exclusivities (asset_id, protection_type, identifier,"
                 " expiry_date, source) VALUES (?, 'patent', 'X', ?, 'orange_book')",
                 (aid, f"{this_year + 2}-01-01"))
    conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, value, unit)"
                 " VALUES (?, ?, 100000000000.0, 'DKK')", (aid, this_year - 1))
    conn.commit()
    conn.close()
    _, rates = fx.parse_ecb(_ECB_XML)
    fx.store(db_file, "2026-07-24", rates)

    built = asset_revenue.build_universe_at_risk(db_file)
    assert built["fx_as_of"] == "2026-07-24"
    nvo = next(r for r in built["rows"] if r["ticker"] == "NVO")
    assert nvo["priced_total_usd"] == pytest.approx(100000000000.0 * (1.10 / 7.46))
    assert nvo["at_risk_5y_usd"] is not None


def test_universe_at_risk_leaves_usd_null_without_a_rate(tmp_path):
    """No rates stored: a real tagged total still has a null USD figure, not zero."""
    db_file = tmp_path / "t.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    this_year = dt.date.today().year
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    cur = conn.execute("INSERT INTO assets (owner_company_id, brand_name,"
                       " internal_code, modality, is_marketed) VALUES"
                       " (?, 'Zep', 'Z1', 'small molecule', 1)", (cid,))
    aid = cur.lastrowid
    conn.execute("INSERT INTO exclusivities (asset_id, protection_type, identifier,"
                 " expiry_date, source) VALUES (?, 'patent', 'X', ?, 'orange_book')",
                 (aid, f"{this_year + 2}-01-01"))
    conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, value, unit)"
                 " VALUES (?, ?, 5000000000.0, 'USD')", (aid, this_year - 1))
    conn.commit()
    conn.close()
    built = asset_revenue.build_universe_at_risk(db_file)
    assert built["fx_as_of"] is None
    lly = next(r for r in built["rows"] if r["ticker"] == "LLY")
    assert lly["priced_total"] == pytest.approx(5000000000.0)  # native is real
    assert lly["priced_total_usd"] is None                     # USD unknown, not zero


def test_fetcher_normalise_parses_the_payload():
    f = FxEcbFetcher(None)
    rows = f.normalise([{"xml": _ECB_XML}])
    assert rows[0]["as_of"] == "2026-07-24"
    assert rows[0]["usd_rates"]["USD"] == pytest.approx(1.0)


def test_history_is_oldest_first_and_stops_where_the_record_starts(tmp_path):
    """The ECB set starts on a real date. Asking for more shows where the line begins
    rather than making a short series look flat."""
    path = str(tmp_path / "fxh.db")
    db.init(path)
    fx.store(path, "2026-09-18", {"EUR": 1.1720, "USD": 1.0})
    fx.store(path, "2026-09-21", {"EUR": 1.1490, "USD": 1.0})
    got = fx.history(path, "EUR")
    assert [r["as_of"] for r in got] == ["2026-09-18", "2026-09-21"]
    assert got[-1]["rate"] == pytest.approx(1.1490)
    assert [r["as_of"] for r in fx.history(path, "EUR", "2026-09-21")] == ["2026-09-21"]
    assert fx.history(path, "EUR", "2019-01-01") == got
    assert fx.history(path, "ZZZ") == []

    conn = db.get_connection(path)
    assert len(fx.history(path, "EUR", conn=conn)) == 2
    conn.execute("SELECT 1")            # lent, so not closed under the caller
    conn.close()


def _company(conn, ticker, currency, cid=None):
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (?, ?, ?, ?)", (cid, ticker, ticker, currency))


def test_the_snapshot_carries_the_rates_the_universe_reports_in(tmp_path):
    """It used to carry the date and a count of currencies, so a diff could see that
    the file had moved to a new day and nothing about whether a rate the book uses had
    moved with it."""
    import json

    from fetchers.fx_ecb import FxEcbFetcher

    path = str(tmp_path / "snap.db")
    db.init(path)
    conn = db.get_connection(path)
    for i, (ticker, cur) in enumerate((("NVO", "DKK"), ("SNY", "EUR"),
                                       ("LLY", "USD")), start=1):
        _company(conn, ticker, cur, i)
    conn.commit()
    conn.close()

    fetcher = FxEcbFetcher(db_path=path)
    fetcher.snapshot([{"as_of": "2026-09-21",
                       "usd_rates": {"DKK": 0.1537, "EUR": 1.1490, "USD": 1.0,
                                     "JPY": 0.0068}}])
    conn = db.get_connection(path)
    payload = json.loads(conn.execute(
        "SELECT payload FROM snapshots WHERE source = 'fx'").fetchone()[0])
    conn.close()
    assert payload["fetch_kind"] == "live"
    # The crosses the universe reports in, and only those: the yen is in the file and
    # no covered company reports in it.
    assert payload["crosses"] == {"DKK": 0.1537, "EUR": 1.1490}
    assert "USD" not in payload["crosses"]


def test_a_cross_is_flagged_against_the_level_it_was_last_flagged_from(tmp_path):
    """Measured daily moves are 0.18% on the euro and the krone and 0.25% on the
    franc, so a two percent bar is a walk rather than a day, and needs an anchor."""
    import market_signals as MS

    path = str(tmp_path / "fxsig.db")
    db.init(path)
    conn = db.get_connection(path)
    _company(conn, "NVO", "DKK", 1)
    conn.commit()
    fx.store(path, "2026-08-20", {"DKK": 0.1500, "USD": 1.0})
    conn = db.get_connection(path)
    assert MS.evaluate_fx(conn) == []            # first sighting baselines
    conn.commit()
    conn.close()

    # Four days of about half a percent each: no single day trips a 2% bar.
    for day, rate in (("2026-08-21", 0.1508), ("2026-08-24", 0.1516),
                      ("2026-08-25", 0.1524)):
        fx.store(path, day, {"DKK": rate, "USD": 1.0})
        conn = db.get_connection(path)
        assert MS.evaluate_fx(conn) == []
        conn.commit()
        conn.close()

    fx.store(path, "2026-08-26", {"DKK": 0.1533, "USD": 1.0})
    conn = db.get_connection(path)
    fired = MS.evaluate_fx(conn)
    conn.close()
    assert len(fired) == 1
    assert fired[0]["base"] == "DKK"
    assert fired[0]["move_pct"] == pytest.approx(2.2, abs=0.05)
    assert fired[0]["anchor_as_of"] == "2026-08-20"


def test_a_cross_is_fanned_out_to_its_filers_and_to_no_one_else(tmp_path):
    """A rate move is one fact about the market. A cross moving is one fact about each
    company that reports in it and nothing at all about the fifteen in dollars."""
    import diff
    import market_signals as MS
    import whatchanged

    path = str(tmp_path / "fanout.db")
    db.init(path)
    conn = db.get_connection(path)
    for i, (ticker, cur) in enumerate((("SNY", "EUR"), ("BAYN", "EUR"),
                                       ("LLY", "USD")), start=1):
        _company(conn, ticker, cur, i)
    conn.commit()
    conn.close()
    fx.store(path, "2026-08-20", {"EUR": 1.1000, "USD": 1.0})
    conn = db.get_connection(path)
    MS.evaluate_fx(conn)
    conn.commit()
    conn.close()
    fx.store(path, "2026-09-21", {"EUR": 1.1490, "USD": 1.0})

    conn = db.get_connection(path)
    assert diff._diff_fx(conn, None) == 2          # one row each for SNY and BAYN
    conn.commit()
    rows = conn.execute("SELECT entity_key, field, old_value, new_value"
                        "  FROM changes WHERE entity_type = 'market'").fetchall()
    conn.close()
    assert {r["entity_key"] for r in rows} == {"EUR|SNY", "EUR|BAYN"}
    assert all(r["field"] == "rate@2026-08-20" for r in rows)
    assert "the euro is 4.5% stronger" in rows[0]["new_value"].lower()

    # Sanofi sees it; Lilly does not.
    assert any(it["kind"] == "market"
               for it in whatchanged.build_feed(path, days=3650, ticker="SNY"))
    assert not any(it["kind"] == "market"
                   for it in whatchanged.build_feed(path, days=3650, ticker="LLY"))


def test_a_day_the_ecb_did_not_publish_is_a_gap_and_never_filled(tmp_path):
    """Three business days in the stored set carry no reference rates at all
    (2026-08-12, 2026-08-27, 2026-09-02). Interpolating them would invent a rate on a
    day the ECB did not set one, and a ratchet would then measure against it."""
    path = str(tmp_path / "gaps.db")
    db.init(path)
    fx.store(path, "2026-08-11", {"EUR": 1.1000, "USD": 1.0})
    fx.store(path, "2026-08-13", {"EUR": 1.1100, "USD": 1.0})
    got = fx.history(path, "EUR")
    assert [r["as_of"] for r in got] == ["2026-08-11", "2026-08-13"]
    # The missing Wednesday is absent, not carried and not averaged.
    assert all(r["as_of"] != "2026-08-12" for r in got)
    assert fx.rates_on(path, "2026-08-12")["as_of"] == "2026-08-11"


def test_the_translation_lens_is_exact_and_only_for_a_foreign_filer(tmp_path):
    """The rate is folded into the divisor as shares over rate, so equity per share is
    linear in it and 5% either way is arithmetic rather than a rerun."""
    import fair_value

    class _Book:
        pass

    book = _Book()
    book.equity = 66.06
    book.sotp = {"fx": {"currency": "EUR", "rate": 1.1490, "as_of": "2026-09-21"}}
    lens = fair_value.translation_range(book)
    assert lens["low"] == pytest.approx(66.06 * 0.95)
    assert lens["high"] == pytest.approx(66.06 * 1.05)
    assert "1.1490 USD on 2026-09-21" in lens["basis"]

    book.sotp = {"fx": {"currency": "USD", "rate": None, "as_of": None}}
    assert fair_value.translation_range(book) is None


def test_cash_is_converted_when_it_is_being_ranked(tmp_path):
    """The treemap sized by revenue converted and the one sized by cash did not, so
    Novo's kroner ranked against Lilly's dollars at six and a half times their worth."""
    import runway

    path = str(tmp_path / "cash.db")
    db.init(path)
    conn = db.get_connection(path)
    _company(conn, "NVO", "DKK", 1)
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                 " period_end, value, unit) VALUES"
                 " (1, 'CashAndEquivalents', 'instant', 2025, '2025-12-31', 1e9, 'DKK')")
    conn.commit()
    rates = {"DKK": 0.1537, "as_of": "2026-09-21"}

    filed = runway.liquidity(conn, 1)
    assert filed["available"] == pytest.approx(1e9)
    assert filed["currency"] == "DKK" and filed["converted"] is False

    usd = runway.liquidity(conn, 1, rates)
    assert usd["available"] == pytest.approx(1e9 * 0.1537)
    assert usd["currency"] == "USD" and usd["converted"] is True
    assert usd["filed_currency"] == "DKK" and usd["fx_as_of"] == "2026-09-21"

    # A currency with no stored rate drops out rather than ranking at the wrong size.
    none_rate = runway.liquidity(conn, 1, {"as_of": "2026-09-21"})
    assert none_rate["available"] is None
    conn.close()


def test_the_currency_paragraph_states_an_exact_effect_not_a_measured_one(tmp_path):
    """Every other macro sentence reruns the book. This one does not need to: the rate
    is folded into the divisor as shares over rate, so dollar value per share is linear
    in it and the effect is the move itself."""
    import market_signals as MS

    fired = {"base": "DKK", "anchor_value": 0.1500, "anchor_as_of": "2026-08-20",
             "value": 0.1537, "as_of": "2026-09-21", "move_pct": 2.4667,
             "change_type": "fx_move", "significance": "medium"}
    said = MS.fx_sentence(fired, "NVO")
    assert said.startswith("The krone is 2.5% stronger against the dollar")
    assert "NVO converts 2.5% higher" in said
    assert "one for one" in said
    # And it says what did not move, because a reader should not think the forecast
    # was rebuilt.
    assert "The forecast itself is unchanged: it runs in DKK." in said
    assert "Dates compared: 2026-08-20 and 2026-09-21." in said

    weaker = MS.fx_sentence({**fired, "value": 0.1450, "move_pct": -3.3333}, "NVO")
    assert "3.3% weaker" in weaker and "converts 3.3% lower" in weaker


def test_a_flagged_cross_is_replayed_from_its_own_row(tmp_path):
    import market_signals as MS

    path = str(tmp_path / "fxreplay.db")
    db.init(path)
    fx.store(path, "2026-08-20", {"CHF": 1.2516, "USD": 1.0})
    fx.store(path, "2026-09-21", {"CHF": 1.2174, "USD": 1.0})
    conn = db.get_connection(path)
    got = MS.replay_fx(conn, "CHF", "rate@2026-08-20", "1.251600")
    assert got["move_pct"] == pytest.approx(-2.73, abs=0.01)
    assert got["anchor_as_of"] == "2026-08-20" and got["as_of"] == "2026-09-21"
    # A row with no date on its field cannot be replayed and says so.
    assert MS.replay_fx(conn, "CHF", "rate", "1.2516") is None
    assert MS.replay_fx(conn, "CHF", "rate@2026-08-20", None) is None
    conn.close()
