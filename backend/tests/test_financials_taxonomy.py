"""The financials snapshot names the taxonomy its revenue came from, no network.

The comps view reads the accounting standard from this key (us-gaap is US GAAP,
ifrs-full is IFRS) rather than from the foreign-issuer flag, which three 20-F filers
carry as 0. Each fetcher is run end to end on a saved payload and the snapshot it wrote
is read back.
"""

import json
from pathlib import Path

import db
import seed
from fetchers import financials_esef as esef
from fetchers.financials_edgar import FinancialsEdgarFetcher
from fetchers.financials_esef import FinancialsEsefFetcher

FIXTURES = Path(__file__).parent / "fixtures"
LEI = "TEST00EXEMPLAPHARM68"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _db(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    return db_file


def _snapshot(db_file, ticker):
    conn = db.get_connection(db_file)
    try:
        row = conn.execute(
            "SELECT payload FROM snapshots WHERE source = 'financials' AND entity_key = ?"
            " ORDER BY id DESC LIMIT 1", (ticker,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["payload"])


def test_edgar_us_gaap_filer_records_us_gaap(tmp_path, monkeypatch):
    db_file = _db(tmp_path)
    monkeypatch.setattr(FinancialsEdgarFetcher, "fetch",
                        lambda self: _load("companyfacts_lly.json"))
    result = FinancialsEdgarFetcher("LLY", db_file).run()
    assert result.errors == []
    payload = _snapshot(db_file, "LLY")
    assert payload["fetch_kind"] == "live"
    assert payload["taxonomy"] == "us-gaap"


def test_edgar_ifrs_filer_records_ifrs_full(tmp_path, monkeypatch):
    db_file = _db(tmp_path)
    monkeypatch.setattr(FinancialsEdgarFetcher, "fetch",
                        lambda self: _load("companyfacts_nvo.json"))
    result = FinancialsEdgarFetcher("NVO", db_file).run()
    assert result.errors == []
    assert _snapshot(db_file, "NVO")["taxonomy"] == "ifrs-full"


def test_esef_filer_records_ifrs_full(tmp_path, monkeypatch):
    db_file = _db(tmp_path)
    conn = db.get_connection(db_file)
    try:
        conn.execute("UPDATE companies SET lei = ? WHERE ticker = 'BAYN'", (LEI,))
        conn.commit()
    finally:
        conn.close()
    reports = [
        {"period_end": "2024-12-31", "fxo_id": "exa-2024",
         "report": _load("esef_exempla_2024.json")},
        {"period_end": "2023-12-31", "fxo_id": "exa-2023",
         "report": _load("esef_exempla_2023.json")},
    ]
    monkeypatch.setattr(FinancialsEsefFetcher, "fetch",
                        lambda self: {"lei": LEI, "reports": reports})
    result = FinancialsEsefFetcher("BAYN", db_file).run()
    assert result.errors == []
    payload = _snapshot(db_file, "BAYN")
    assert payload["source"] == esef.ESEF_SOURCE
    assert payload["taxonomy"] == "ifrs-full"


def test_no_revenue_line_records_no_taxonomy():
    from fetchers.financials_edgar import _revenue_taxonomy
    assert _revenue_taxonomy({"lines": {}}) is None
