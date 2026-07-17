"""CIK resolver runs against a saved fixture, never the network.

The fixture is a real trimmed subset of EDGAR's company_tickers.json. It includes
the ROG -> Rogers Corp (CIK 84748) decoy so the test proves a non-filer is skipped
rather than mis-resolved to an unrelated company.
"""

import json
from pathlib import Path

import db
import seed

FIXTURE = Path(__file__).parent / "fixtures" / "company_tickers.json"


def _seeded_companies(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT ticker, us_adr_ticker, is_sec_filer FROM companies"
            )
        ]
    finally:
        conn.close()


def test_build_ticker_map_zero_pads():
    raw = {"0": {"cik_str": 59478, "ticker": "lly", "title": "ELI LILLY & Co"}}
    assert seed.build_ticker_map(raw) == {"LLY": "0000059478"}


def test_resolver_fills_filers_and_skips_non_filers(tmp_path):
    companies = _seeded_companies(tmp_path)
    ticker_map = seed.build_ticker_map(json.loads(FIXTURE.read_text()))

    resolved, unresolved = seed.resolve_ciks(companies, ticker_map)

    # Spot-check exact 10-digit CIKs for a US filer and a foreign ADR filer.
    assert resolved["LLY"] == "0000059478"
    assert resolved["NVO"] == "0000353278"

    # Non-filers are skipped and left null even though ROG exists in the map
    # (as Rogers Corp) — proving the is_sec_filer guard, not a lookup miss.
    assert resolved["ROG"] is None
    assert resolved["BAYN"] is None

    # Every SEC filer resolves; nothing is left unresolved for this universe.
    assert unresolved == []
    filers = [c for c in companies if int(c["is_sec_filer"])]
    assert len(filers) == 16
    assert sum(1 for cik in resolved.values() if cik is not None) == 16

    # Every resolved CIK is 10-digit zero-padded.
    for cik in resolved.values():
        if cik is not None:
            assert len(cik) == 10 and cik.isdigit()
