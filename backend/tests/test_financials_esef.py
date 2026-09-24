"""The ESEF route to financials, against saved payloads, no network.

The two report fixtures are genuine xBRL-JSON: Arelle 2.45.2's saveLoadableOIM plugin,
the conversion filings.xbrl.org runs, applied to the two inline XBRL reports under
``fixtures/esef_exempla/``. Those reports are synthetic. They belong to a made-up filer,
Exempla Pharma AG, whose LEI carries valid check digits under a prefix no LEI issuer
uses, and they are built to carry what an ESEF report does and a 20-F's company facts do
not: German number formatting, sign attributes, a total tagged twice, a segment
breakdown of the same concept, a company extension concept, a nil fact, and a
comparative year the next report restates. To regenerate one::

    python -m arelle.CntlrCmdLine --internetConnectivity=offline \\
        --plugins saveLoadableOIM -f exa-2024-12-31.xhtml \\
        --saveLoadableOIM esef_exempla_2024.json

The index page is written by hand to the JSON:API shape the index serves, with the field
names the xbrl-filings-api client reads (``period_end``, ``json_url``, ``fxo_id``,
``processed``, the entity's ``identifier``). Replace it with a captured page once the
index is reachable from a session that can save one.
"""

import json
from pathlib import Path

import pytest

import db
import forecast_view
import seed
from fetchers import financials_esef as esef
from fetchers.financials_esef import FinancialsEsefFetcher

FIXTURES = Path(__file__).parent / "fixtures"
LEI = "TEST00EXEMPLAPHARM68"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _reports():
    return [
        {"period_end": "2024-12-31", "fxo_id": "exa-2024", "report": _load("esef_exempla_2024.json")},
        {"period_end": "2023-12-31", "fxo_id": "exa-2023", "report": _load("esef_exempla_2023.json")},
    ]


def _parsed():
    return esef.parse_reports(_reports(), LEI)


def _fy(parsed, key, year):
    periods = parsed["lines"][key]["periods"]
    return next(e["val"] for (end, kind), e in periods.items()
                if kind == "FY" and end == f"{year}-12-31")


# --- conversion ----------------------------------------------------------
def test_a_year_ends_on_its_last_day_not_the_next_midnight():
    parsed, _ = _parsed()
    assert parsed["fy_end"] == "2024-12-31"
    assert ("2024-12-31", "FY") in parsed["lines"]["Revenues"]["periods"]
    assert ("2024-12-31", "instant") in parsed["lines"]["CashAndEquivalents"]["periods"]


def test_values_arrive_scaled_and_signed():
    parsed, _ = _parsed()
    assert _fy(parsed, "Revenues", 2024) == 46_000_000_000
    assert _fy(parsed, "NetIncomeLoss", 2024) == -2_500_000_000
    assert _fy(parsed, "EarningsPerShareDiluted", 2024) == pytest.approx(-2.55)
    assert parsed["currency"] == "EUR"
    assert parsed["lines"]["EarningsPerShareDiluted"]["unit"] == "EUR/shares"


def test_the_later_report_restates_the_comparative():
    """The 2023 report said 47.6bn; the 2024 report restates 2023 at 47.5bn."""
    parsed, _ = _parsed()
    assert _fy(parsed, "Revenues", 2023) == 47_500_000_000
    assert _fy(parsed, "Revenues", 2022) == 50_700_000_000     # only the older report


def test_a_segment_member_is_not_the_total():
    facts, _ = esef.report_facts(_load("esef_exempla_2024.json"), LEI, "2024-12-31", "x")
    revenue = facts["ifrs-full"]["Revenue"]["units"]["EUR"]
    fy2024 = [e["val"] for e in revenue if e["end"] == "2024-12-31"]
    assert fy2024 == [46_000_000_000]      # tagged twice, kept once; the 18bn segment out


def test_extension_concepts_nil_facts_and_text_are_left_out():
    facts, _ = esef.report_facts(_load("esef_exempla_2024.json"), LEI, "2024-12-31", "x")
    concepts = set(facts["ifrs-full"])
    assert "CoreEbitda" not in concepts                          # exa:, not ifrs-full
    assert "Goodwill" not in concepts                            # nil
    assert "NameOfReportingEntityOrOtherMeansOfIdentification" not in concepts


def test_debt_resolves_from_borrowings():
    parsed, _ = _parsed()
    debt = parsed["lines"]["TotalDebt"]["periods"]
    assert debt[("2024-12-31", "instant")]["val"] == 34_000_000_000
    assert debt[("2022-12-31", "instant")]["val"] == 40_000_000_000


def test_another_entitys_facts_are_ignored():
    facts, _ = esef.report_facts(_load("esef_exempla_2024.json"), "529900OTHERENTITY0001",
                                 "2024-12-31", "x")
    assert facts == {}


def test_two_equally_precise_copies_that_disagree_give_neither():
    report = _load("esef_exempla_2024.json")
    report["facts"]["dup"] = dict(report["facts"]["f56"], value="46100000000.0")
    facts, notes = esef.report_facts(report, LEI, "2024-12-31", "x")
    revenue = facts["ifrs-full"]["Revenue"]["units"]["EUR"]
    assert not [e for e in revenue if e["end"] == "2024-12-31"]
    assert notes and "Revenue" in notes[0]


def test_the_more_precise_copy_stands():
    report = _load("esef_exempla_2024.json")
    report["facts"]["precise"] = dict(report["facts"]["f56"], value="46012000000.0",
                                      decimals=-3)
    facts, notes = esef.report_facts(report, LEI, "2024-12-31", "x")
    revenue = facts["ifrs-full"]["Revenue"]["units"]["EUR"]
    assert [e["val"] for e in revenue if e["end"] == "2024-12-31"] == [46_012_000_000]
    assert notes == []


# --- the index -----------------------------------------------------------
def test_the_index_query_filters_on_the_lei():
    url = esef.index_url(LEI)
    assert url.startswith("https://filings.xbrl.org/api/filings?")
    assert f"filter%5Bentity.identifier%5D={LEI}" in url
    assert "include=entity" in url


def test_select_reports_keeps_one_converted_report_per_period_for_the_lei():
    reports = esef.select_reports([_load("xbrl_filings_index_exempla.json")], LEI)
    assert [r["period_end"] for r in reports] == ["2024-12-31", "2023-12-31"]
    # Two copies of 2024: the one processed last is read. 2022 has no JSON yet, and
    # the other entity's filing is dropped.
    assert reports[0]["json_url"] == (
        f"https://filings.xbrl.org/{LEI}/2024-12-31/ESEF/DE/1/exa-2024-12-31-en.json")
    assert reports[0]["entity_name"] == "Exempla Pharma AG"


# --- the LEI -------------------------------------------------------------
def test_lei_check_digits():
    assert seed.valid_lei("549300J4U55H3WP1XT59")         # Bayer Aktiengesellschaft
    assert seed.valid_lei(LEI)
    assert not seed.valid_lei("549300J4U55H3WP3DE85")     # one transposition away
    assert not seed.valid_lei("549300J4U55H3WP1XT5")
    assert not seed.valid_lei(None)


# --- end to end ----------------------------------------------------------
@pytest.fixture
def loaded(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    try:
        conn.execute("UPDATE companies SET lei = ? WHERE ticker = 'BAYN'", (LEI,))
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(FinancialsEsefFetcher, "fetch",
                        lambda self: {"lei": LEI, "reports": _reports()})
    result = FinancialsEsefFetcher("BAYN", db_file).run()
    return db_file, result


def test_the_seed_carries_bayers_lei(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    try:
        row = conn.execute("SELECT lei, cik FROM companies WHERE ticker = 'BAYN'").fetchone()
    finally:
        conn.close()
    assert row["lei"] == "549300J4U55H3WP1XT59" and row["cik"] is None


def test_rows_land_in_financials_marked_as_esef(loaded):
    db_file, result = loaded
    assert result.errors == [] and result.rows_fetched > 0
    conn = db.get_connection(db_file)
    try:
        rows = conn.execute(
            """SELECT f.metric, f.value, f.unit, f.source FROM financials f
                JOIN companies c ON c.id = f.company_id
               WHERE c.ticker = 'BAYN' AND f.period_type = 'FY' AND f.fiscal_year = 2024
            """).fetchall()
        snap = conn.execute(
            "SELECT payload FROM snapshots WHERE source = 'financials'"
            " AND entity_key = 'BAYN' ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    by_metric = {r["metric"]: r for r in rows}
    assert by_metric["Revenues"]["value"] == 46_000_000_000
    assert by_metric["Revenues"]["unit"] == "EUR"
    assert {r["source"] for r in rows} == {"esef_xbrl"}
    payload = json.loads(snap["payload"])
    assert payload["source"] == "esef_xbrl" and payload["fetch_kind"] == "live"
    assert payload["revenue"] == 46_000_000_000


def test_the_share_divisor_follows_from_eps_and_the_adr_ratio(loaded):
    """No share count is tagged, so ordinary shares are net income over diluted EPS, and
    four ADSs make one share: 2.5bn / 2.55 ordinary, times four ADSs each, over the
    dollar rate, since the rNPV is in euro and the price in dollars."""
    db_file, _ = loaded
    conn = db.get_connection(db_file)
    try:
        company_id = conn.execute(
            "SELECT id FROM companies WHERE ticker = 'BAYN'").fetchone()["id"]
        conn.execute("INSERT INTO fx_rates (base, quote, rate, as_of, source)"
                     " VALUES ('EUR', 'USD', 1.10, '2026-09-23', 'test')")
        conn.commit()
        divisor = forecast_view._diluted_shares(conn, company_id)
    finally:
        conn.close()
    ordinary = 2_500_000_000 / 2.55
    assert divisor == pytest.approx(ordinary * 4 / 1.10, rel=1e-6)


def test_an_lei_missing_from_the_index_is_a_reported_error(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    monkeypatch.setattr(esef, "_get_json", lambda url: {"data": [], "links": {}})
    result = FinancialsEsefFetcher("BAYN", db_file).run()
    assert result.rows_fetched == 0
    assert result.errors and "indexes no converted ESEF report" in result.errors[0]


def test_fetch_follows_a_relative_next_link_and_reads_each_report(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    try:
        conn.execute("UPDATE companies SET lei = ? WHERE ticker = 'BAYN'", (LEI,))
        conn.commit()
    finally:
        conn.close()
    index = _load("xbrl_filings_index_exempla.json")
    first = {"data": index["data"][:1], "included": index["included"],
             "links": {"next": "/api/filings?page%5Bnumber%5D=2"}}
    second = {"data": index["data"][1:], "included": index["included"], "links": {}}
    served = {"https://filings.xbrl.org/api/filings?page%5Bnumber%5D=2": second}
    asked = []

    def get(url):
        asked.append(url)
        if url.startswith(esef.INDEX_URL + "?filter"):
            return first
        if url in served:
            return served[url]
        return {"documentInfo": {}, "facts": {}}

    monkeypatch.setattr(esef, "_get_json", get)
    raw = FinancialsEsefFetcher("BAYN", db_file).fetch()
    assert [r["period_end"] for r in raw["reports"]] == ["2024-12-31", "2023-12-31"]
    assert asked[1] == "https://filings.xbrl.org/api/filings?page%5Bnumber%5D=2"
    assert asked[2].endswith("exa-2024-12-31-en.json")
