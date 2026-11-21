"""How each quarter landed against the street: Nasdaq's earnings surprise table.

Fixtures are live payloads captured on 2026-11-21 for Lilly, for Novo's ADR and for
Beam, which reports losses.
"""

import json
import pathlib

import db
from fetchers import earnings_nasdaq as EN

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def test_a_quarter_label_and_a_report_date_read_as_iso():
    assert EN.quarter_end("Sep 2026") == "2026-09"
    assert EN.quarter_end("Sept") is None and EN.quarter_end("") is None
    assert EN.reported_on("10/29/2026") == "2026-10-29"
    assert EN.reported_on("8/5/2026") == "2026-08-05"
    assert EN.reported_on("N/A") is None


def test_lly_reads_four_quarters_with_the_street_eps_not_the_filed_one():
    rows = EN.parse(7, _load("nasdaq_earnings_surprise_lly.json"))
    assert [r["quarter_end"] for r in rows] == ["2026-09", "2026-06", "2026-03", "2025-12"]
    latest = rows[0]
    assert (latest["eps"], latest["consensus_eps"], latest["surprise_pct"]) == (
        7.48, 5.38, 39.03)
    assert latest["reported_on"] == "2026-10-29"
    # The filed diluted EPS for the quarter is 7.22. This table is the street's count.
    assert latest["eps"] != 7.22


def test_an_adr_reads_in_dollars_per_listed_share():
    rows = EN.parse(3, _load("nasdaq_earnings_surprise_nvo.json"))
    assert (rows[0]["eps"], rows[0]["consensus_eps"]) == (0.89, 0.81)
    assert rows[0]["reported_on"] == "2026-11-04"


def test_a_wider_loss_is_a_miss_and_a_narrower_one_a_beat():
    rows = {r["quarter_end"]: r for r in EN.parse(9, _load("nasdaq_earnings_surprise_beam.json"))}
    assert rows["2026-09"]["eps"] == -1.28 and rows["2026-09"]["surprise_pct"] == -9.4
    assert rows["2025-12"]["eps"] == -0.1 and rows["2025-12"]["surprise_pct"] == 91.15


def test_nothing_missing_becomes_a_zero_and_a_blank_surprise_is_worked_out():
    assert EN.parse(1, None) == [] and EN.parse(1, {"data": None}) == []
    payload = {"data": {"earningsSurpriseTable": {"rows": [
        {"fiscalQtrEnd": "Sep 2026", "dateReported": "11/3/2026", "eps": -1.0,
         "consensusForecast": "-2", "percentageSurprise": "N/A"},
        {"fiscalQtrEnd": "Jun 2026", "dateReported": "8/4/2026", "eps": 0.5,
         "consensusForecast": "0", "percentageSurprise": "N/A"},
        {"fiscalQtrEnd": "Mar 2026", "dateReported": "5/7/2026", "eps": 0.5,
         "consensusForecast": "N/A", "percentageSurprise": "N/A"},
    ]}}}
    rows = EN.parse(1, payload)
    # A loss half the size expected is a beat of fifty per cent, not a miss.
    assert rows[0]["surprise_pct"] == 50.0
    # Against a consensus of nothing there is no percentage to state.
    assert rows[1]["surprise_pct"] is None
    # No consensus, no row: a reported EPS alone says nothing about how it landed.
    assert len(rows) == 2


def test_a_quarter_is_one_row_and_only_a_changed_one_is_written(tmp_path):
    path = str(tmp_path / "e.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (7, 'LLY', 'Lilly')")
    conn.commit()
    conn.close()
    fetcher = EN.EarningsNasdaqFetcher("LLY", path)
    rows = EN.parse(7, _load("nasdaq_earnings_surprise_lly.json"))
    assert fetcher.upsert(rows).rows_fetched == 4
    assert fetcher.upsert(rows).rows_fetched == 0
    restated = [dict(rows[0], eps=7.50, surprise_pct=39.41)] + rows[1:]
    assert fetcher.upsert(restated).rows_fetched == 1
    conn = db.get_connection(path)
    stored = conn.execute(
        "SELECT COUNT(*) n, MAX(eps) top FROM earnings_surprises").fetchone()
    conn.close()
    assert (stored["n"], stored["top"]) == (4, 8.55)
