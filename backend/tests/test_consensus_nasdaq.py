"""The keyless street feed: Nasdaq's annual EPS consensus and price target.

Fixtures are live payloads captured on 2026-09-17 for Lilly and for Novo's ADR.
"""

import json
import pathlib

import db
from fetchers import consensus_nasdaq as CN

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def test_fiscal_end_labels_the_year_the_way_the_financials_table_does():
    assert CN.fiscal_period("Dec 2026") == "FY2026"
    assert CN.fiscal_period("Mar 2027") == "FY2026"
    assert CN.fiscal_period("Sept") is None and CN.fiscal_period("") is None


def test_lly_eps_years_and_price_target_parse_with_their_ranges():
    rows = CN.parse(7, _load("nasdaq_earnings_forecast_lly.json"),
                    _load("nasdaq_targetprice_lly.json"))
    eps = {r["period"]: r for r in rows if r["metric"] == "EPS"}
    assert set(eps) == {"FY2026", "FY2027", "FY2028", "FY2029"}
    assert (eps["FY2026"]["value"], eps["FY2026"]["low"], eps["FY2026"]["high"]) == (36.53, 35.53, 38.64)
    assert eps["FY2026"]["note"].startswith("8 estimates")
    target = next(r for r in rows if r["metric"] == "PriceTarget")
    assert (target["value"], target["low"], target["high"]) == (1382.05, 940.0, 1600.0)
    assert target["period"] == "12M" and "19 buy" in target["note"]


def test_an_adr_parses_in_dollars_per_listed_share_and_nothing_missing_becomes_zero():
    rows = CN.parse(3, _load("nasdaq_earnings_forecast_nvo.json"),
                    _load("nasdaq_targetprice_nvo.json"))
    assert next(r for r in rows if r["metric"] == "EPS" and r["period"] == "FY2026")["value"] == 3.53
    assert next(r for r in rows if r["metric"] == "PriceTarget")["value"] == 44.0
    assert CN.parse(3, {"data": None}, {"data": {"consensusOverview": {}}}) == []


def test_only_a_changed_figure_earns_a_row(tmp_path):
    path = str(tmp_path / "n.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (7, 'LLY', 'Lilly')")
    conn.commit()
    conn.close()
    fetcher = CN.ConsensusNasdaqFetcher("LLY", path)
    rows = CN.parse(7, _load("nasdaq_earnings_forecast_lly.json"),
                    _load("nasdaq_targetprice_lly.json"))
    assert fetcher.upsert(rows).rows_fetched == 5
    assert fetcher.upsert(rows).rows_fetched == 0
