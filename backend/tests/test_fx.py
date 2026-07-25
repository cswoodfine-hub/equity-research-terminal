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
