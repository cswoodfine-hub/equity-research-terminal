"""parse_drugsfda runs against a saved drugsfda payload, no network."""

import json
from pathlib import Path

from fetchers.approvals_openfda import parse_drugsfda

FIXTURE = Path(__file__).parent / "fixtures" / "drugsfda_lly.json"


def test_parse_drugsfda_nda_and_bla():
    payload = json.loads(FIXTURE.read_text())
    rows = parse_drugsfda(payload, "LLY")
    by_code = {r["internal_code"]: r for r in rows}

    # An NDA and a BLA are kept; an application with no original approval is dropped.
    assert set(by_code) == {"NDA21368", "BLA205692"}

    cialis = by_code["NDA21368"]
    assert cialis["brand"] == "Cialis"
    assert cialis["modality"] == "small molecule"
    assert cialis["approval_date"] == "2003-11-21"

    basaglar = by_code["BLA205692"]
    assert basaglar["modality"] == "biologic"
    assert basaglar["approval_date"] == "2015-12-16"


# --- the two queries are unioned and deduped -----------------------------
def test_the_fetch_unions_sponsor_and_manufacturer():
    """openFDA files an approval under the entity holding it, which for an acquired
    product is the company that was bought. The parent surfaces those by sponsor, and
    the two result sets are merged on application number."""
    from fetchers.approvals_openfda import ApprovalsOpenFdaFetcher

    fetcher = ApprovalsOpenFdaFetcher("BMY")
    calls = []

    def fake_run(query):
        calls.append(query)
        if query.startswith("openfda.manufacturer_name"):
            return []                                  # Bristol finds nothing here
        return [{"application_number": "NDA202155"},   # Eliquis, via the parent
                {"application_number": "BLA125527"}]

    fetcher._run = fake_run
    merged = fetcher.fetch()["results"]

    assert any("sponsor_name" in c for c in calls)
    assert any("manufacturer_name" in c for c in calls)
    assert {r["application_number"] for r in merged} == {"NDA202155", "BLA125527"}


def test_an_application_from_both_queries_is_not_doubled():
    from fetchers.approvals_openfda import ApprovalsOpenFdaFetcher

    fetcher = ApprovalsOpenFdaFetcher("BMY")
    fetcher._run = lambda query: [{"application_number": "NDA202155"}]
    merged = fetcher.fetch()["results"]

    assert len(merged) == 1                            # same appl from both, kept once
