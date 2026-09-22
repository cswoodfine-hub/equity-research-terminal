"""Two policy lanes, and the gates that are the whole reason they can be trusted.

An agency and a search term alone put a Framework for Artificial Intelligence Diffusion
in a pharmaceutical tariff lane and six recurring information-collection notices in a
drug pricing one. Those notices carry a real comment deadline, so without a gate they
would write a date somebody has to care about onto the horizon rail.
"""

import json
import pathlib

import pytest

import db
from fetchers import policy_fedreg as P

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _payload(name):
    return json.loads((FIXTURES / name).read_text())


def test_the_pharmaceutical_lane_drops_what_is_not_about_medicines():
    """Five hits from the agency and the term, of which an artificial intelligence
    framework and a Section 232 investigation into personal protective equipment and
    medical devices are not. The title gate leaves the ones that are."""
    got = P.parse(_payload("fedreg_bis_pharma.json"), "bis_pharma",
                  P.LANES["bis_pharma"])
    titles = [r["title"] for r in got]
    assert len(got) == 1
    assert "Imports of Pharmaceuticals" in titles[0]
    # The anchor document the seed date exists for.
    assert got[0]["published_on"] == "2025-04-16"
    assert got[0]["comments_close_on"] == "2025-05-07"
    assert got[0]["effective_on"] is None


def test_the_docket_gate_drops_the_information_collection_notice():
    """The one the plan flagged, and the reason a term alone is not enough: it is
    recurring, it is not about price negotiation, and it carries a real deadline."""
    got = P.parse(_payload("fedreg_cms_ira.json"), "cms_ira", P.LANES["cms_ira"])
    assert len(got) == 2
    assert all("Agency Information Collection" not in r["title"] for r in got)
    assert {r["docket_id"] for r in got} == {"CMS-4219-N",
                                             "CMS-4208-F3 and CMS-4212-F"}


def test_a_null_date_stays_null():
    """Four of the seven gated CMS rows carry no comment deadline. Substituting a fetch
    date would put a date on the rail that nobody set."""
    got = {r["docket_id"]: r for r in P.parse(
        _payload("fedreg_cms_ira.json"), "cms_ira", P.LANES["cms_ira"])}
    assert got["CMS-4219-N"]["comments_close_on"] == "2026-09-18"
    assert got["CMS-4219-N"]["effective_on"] is None
    assert got["CMS-4208-F3 and CMS-4212-F"]["comments_close_on"] is None
    assert got["CMS-4208-F3 and CMS-4212-F"]["effective_on"] == "2026-06-01"


def test_a_document_with_no_docket_fails_a_docket_gate():
    """The gate exists to refuse what the agency publishes that is not this subject,
    so an ungated row is exactly what it is there to refuse."""
    payload = {"results": [{"document_number": "x", "title": "Medicare something",
                            "publication_date": "2026-01-01", "docket_ids": []}]}
    assert P.parse(payload, "cms_ira", P.LANES["cms_ira"]) == []
    # The pharmaceutical lane has no docket gate, so the same row passes on its title.
    payload["results"][0]["title"] = "Tariffs on Pharmaceuticals"
    assert len(P.parse(payload, "bis_pharma", P.LANES["bis_pharma"])) == 1


def test_an_api_error_is_raised_rather_than_read_as_a_quiet_week():
    """A bad agency slug returns errors rather than an empty result set, and the two
    look identical once the errors key is dropped."""
    with pytest.raises(ValueError, match="invalid value"):
        P.parse({"errors": {"agencies": "invalid value"}}, "cms_ira",
                P.LANES["cms_ira"])
    with pytest.raises(ValueError):
        P.parse(None, "cms_ira", P.LANES["cms_ira"])


def test_the_request_asks_for_subtype_and_never_the_field_that_four_hundreds():
    """fields[]=presidential_document_type is not valid and 400s the whole request
    with "field 'presidential_document_type' not valid". The field is subtype."""
    url = P._url(P.LANES["cms_ira"], "2025-01-01")
    assert "subtype" in url
    assert "presidential_document_type" not in url
    assert "centers-for-medicare-medicaid-services" in url
    assert "2025-01-01" in url


def test_the_lane_seeds_from_a_date_and_then_rolls(tmp_path):
    """The Section 232 initiation was published 2025-04-16, outside any window a daily
    fetcher would use. A rolling-only lane would never carry the document it exists
    for."""
    path = str(tmp_path / "pol.db")
    db.init(path)
    assert P.since_for(path) == P.SEED_FROM == "2025-01-01"

    fetcher = P.PolicyFedRegFetcher(db_path=path)
    fetcher.upsert(P.parse(_payload("fedreg_bis_pharma.json"), "bis_pharma",
                           P.LANES["bis_pharma"]))
    # Once something is held the window rolls instead, and is no longer the seed.
    assert P.since_for(path) != P.SEED_FROM
    assert P.since_for(path) > "2025-01-01"


def test_the_same_document_fetched_twice_writes_one_row(tmp_path):
    path = str(tmp_path / "pol2.db")
    db.init(path)
    fetcher = P.PolicyFedRegFetcher(db_path=path)
    rows = P.parse(_payload("fedreg_cms_ira.json"), "cms_ira", P.LANES["cms_ira"])
    assert fetcher.upsert(rows).rows_fetched == 2
    fetcher.upsert(rows)
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM policy_items").fetchone()[0] == 2
    # A document revised in place updates rather than duplicating.
    fetcher.upsert([{**rows[0], "comments_close_on": "2026-10-01"}])
    got = conn.execute("SELECT comments_close_on FROM policy_items"
                       " WHERE document_number = ?",
                       (rows[0]["document_number"],)).fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM policy_items").fetchone()[0] == 2
    conn.close()
    assert got == "2026-10-01"


def test_an_item_carries_no_company_and_no_modelled_number(tmp_path):
    """Neither lane's documents name a manufacturer, and rssfeed.match_company returns
    one company on a first match over an unordered map, so reusing it here would bind a
    universe-wide rule to whichever company matched first."""
    path = str(tmp_path / "pol3.db")
    db.init(path)
    P.PolicyFedRegFetcher(db_path=path).upsert(
        P.parse(_payload("fedreg_cms_ira.json"), "cms_ira", P.LANES["cms_ira"]))
    conn = db.get_connection(path)
    rows = conn.execute("SELECT company_id FROM policy_items").fetchall()
    conn.close()
    assert all(r["company_id"] is None for r in rows)
    # And nothing here is a number a valuation could read.
    assert set(P.recent(path, days=100000)[0]) == {
        "lane", "document_number", "title", "doc_type", "subtype", "docket_id",
        "published_on", "effective_on", "comments_close_on", "url"}


def test_a_live_snapshot_starts_the_ttl_and_a_cache_snapshot_does_not(tmp_path):
    path = str(tmp_path / "pol4.db")
    db.init(path)
    fetcher = P.PolicyFedRegFetcher(db_path=path)
    assert fetcher._within_ttl() is False
    rows = P.parse(_payload("fedreg_cms_ira.json"), "cms_ira", P.LANES["cms_ira"])
    fetcher.upsert(rows)
    fetcher.snapshot(rows)
    assert fetcher._within_ttl() is True
    conn = db.get_connection(path)
    payload = json.loads(conn.execute(
        "SELECT payload FROM snapshots WHERE source = 'policy'"
        " ORDER BY id DESC LIMIT 1").fetchone()[0])
    conn.close()
    assert payload["fetch_kind"] == "live"
    assert payload["lanes"] == {"cms_ira": 2}
