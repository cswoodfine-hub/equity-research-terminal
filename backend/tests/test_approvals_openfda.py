"""parse_drugsfda runs against a saved drugsfda payload, no network."""

import json
from pathlib import Path

import db
from fetchers import approvals_openfda
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
def test_the_fetch_unions_sponsor_and_manufacturer(tmp_path):
    """openFDA files an approval under the entity holding it, which for an acquired
    product is the company that was bought. The parent surfaces those by sponsor, and
    the two result sets are merged on application number."""
    from fetchers.approvals_openfda import ApprovalsOpenFdaFetcher

    fetcher = ApprovalsOpenFdaFetcher(
        "BMY", _company(tmp_path, "BMY", "Bristol-Myers Squibb Company"))
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


def test_an_application_from_both_queries_is_not_doubled(tmp_path):
    from fetchers.approvals_openfda import ApprovalsOpenFdaFetcher

    fetcher = ApprovalsOpenFdaFetcher(
        "BMY", _company(tmp_path, "BMY", "Bristol-Myers Squibb Company"))
    fetcher._run = lambda query: [{"application_number": "NDA202155"}]
    merged = fetcher.fetch()["results"]

    assert len(merged) == 1                            # same appl from both, kept once


# --- finding a company openFDA does not name the way we do -----------------------------

import pytest

import db
from fetchers import approvals_openfda as A


@pytest.mark.parametrize("generic,molecule", [
    # A trial names one drug twice, by the route it is given. openFDA indexes neither.
    ("Oral Treprostinil", "Treprostinil"),
    ("Parenteral Treprostinil", "Treprostinil"),
    ("Nebulized Tyvaso", "Tyvaso"),
    ("Inhaled Insulin", "Insulin"),
    ("Valbenazine", "Valbenazine"),
])
def test_a_route_prefix_is_stripped_to_the_molecule(generic, molecule):
    assert A._molecule(generic) == molecule


@pytest.mark.parametrize("ours,theirs", [
    # openFDA abbreviates the sponsor, so an exact comparison is useless and the shared
    # distinctive word is what survives.
    ("Alnylam Pharmaceuticals, Inc.", "ALNYLAM PHARMS INC"),
    ("United Therapeutics Corporation", "UNITED THERAP"),
    ("Incyte Corporation", "INCYTE CORP"),
    ("Neurocrine Biosciences, Inc.", "NEUROCRINE"),
    ("BioMarin Pharmaceutical Inc.", "BIOMARIN PHARM"),
])
def test_a_sponsor_is_recognised_through_its_abbreviation(ours, theirs):
    assert A._distinctive_words(ours) & A._distinctive_words(theirs)


def test_two_unrelated_companies_do_not_match_on_common_words():
    """Every name here ends in Pharmaceuticals or Therapeutics. Matching on those would
    attribute half the register to whoever was asked for first."""
    assert not (A._distinctive_words("Alnylam Pharmaceuticals, Inc.")
                & A._distinctive_words("IONIS PHARMS INC"))


def _company(tmp_path, ticker, name, generics=()):
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES (?, ?)", (ticker, name))
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    for generic in generics:
        conn.execute("INSERT INTO assets (owner_company_id, generic_name) VALUES (?, ?)",
                     (cid, generic))
    conn.commit()
    conn.close()
    return path


def test_a_result_belonging_to_another_sponsor_is_refused(tmp_path, monkeypatch):
    """A generic is sold by many manufacturers: treprostinil returns nine applications
    and only some are United Therapeutics'. Keeping them all would credit one company
    with another's approvals."""
    path = _company(tmp_path, "UTHR", "United Therapeutics Corporation",
                    ["Oral Treprostinil"])
    fetcher = A.ApprovalsOpenFdaFetcher("UTHR", path)
    monkeypatch.setattr(fetcher, "_run", lambda q: [
        {"application_number": "NDA1", "sponsor_name": "UNITED THERAP"},
        {"application_number": "NDA2", "sponsor_name": "PAR PHARM INC"},
    ])
    found = fetcher._by_generic_name()
    assert [r["application_number"] for r in found] == ["NDA1"]


def test_discovery_runs_when_the_maps_do_not_know_the_company(tmp_path, monkeypatch):
    """It used to run only when nothing at all had been found, so Neurocrine's single
    acquired-sponsor result was enough to skip it and leave three approvals unfound."""
    path = _company(tmp_path, "NBIX", "Neurocrine Biosciences, Inc.", ["Valbenazine"])
    fetcher = A.ApprovalsOpenFdaFetcher("NBIX", path)
    calls = []

    def fake_run(query):
        calls.append(query)
        if "generic_name" in query:
            return [{"application_number": "NDA209241", "sponsor_name": "NEUROCRINE"}]
        if "sponsor_name" in query:
            return [{"application_number": "NDA218808", "sponsor_name": "NEUROCRINE"}]
        return [{"application_number": "NDA_ACQUIRED", "sponsor_name": "OTHER CO"}]

    monkeypatch.setattr(fetcher, "_run", fake_run)
    monkeypatch.setattr(A.acquired_sponsors, "for_company", lambda *a, **k: ["Some Bio"])
    results = fetcher.fetch()["results"]
    assert any("generic_name" in c for c in calls), "discovery did not run"
    assert {r["application_number"] for r in results} >= {"NDA209241", "NDA218808"}


def test_the_discovered_sponsor_is_swept_for_the_rest_of_the_portfolio(tmp_path,
                                                                      monkeypatch):
    """A molecule search only finds molecules already on file. The answer carries the
    sponsor string openFDA actually uses, and asking for it returns the rest: Alnylam
    goes from one approval to four this way."""
    path = _company(tmp_path, "ALNY", "Alnylam Pharmaceuticals, Inc.", ["Vutrisiran"])
    fetcher = A.ApprovalsOpenFdaFetcher("ALNY", path)
    swept = []

    def fake_run(query):
        if "generic_name" in query:
            return [{"application_number": "NDA215515",
                     "sponsor_name": "ALNYLAM PHARMS INC"}]
        swept.append(query)
        return [{"application_number": f"NDA{len(swept)}",
                 "sponsor_name": "ALNYLAM PHARMS INC"}]

    monkeypatch.setattr(fetcher, "_run", fake_run)
    monkeypatch.setattr(A.acquired_sponsors, "for_company", lambda *a, **k: [])
    fetcher.fetch()
    assert 'sponsor_name:"ALNYLAM PHARMS INC"' in swept


def test_a_company_with_no_generics_on_file_asks_nothing(tmp_path, monkeypatch):
    """A clinical-stage company with only code-numbered assets has nothing to ask about,
    and must not spend a request per asset finding that out."""
    path = _company(tmp_path, "BEAM", "Beam Therapeutics Inc.",
                    ["BEAM-101", "BEAM-302"])
    fetcher = A.ApprovalsOpenFdaFetcher("BEAM", path)
    calls = []
    monkeypatch.setattr(fetcher, "_run", lambda q: calls.append(q) or [])
    assert fetcher._by_generic_name() == []
    assert calls == []


def test_a_product_keeps_every_application_it_holds(tmp_path):
    """Cosentyx is a 2015 BLA and a 2023 one for the intravenous form, and both resolve
    to one asset. Keeping only the last read it as a 2023 launch."""
    import approval_dates
    path = str(tmp_path / "ap.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'NVS', 'Novartis')")
    conn.commit()
    conn.close()
    fetcher = approvals_openfda.ApprovalsOpenFdaFetcher("NVS", db_path=path)
    rows = [{"ticker": "NVS", "internal_code": "BLA125504", "application_number": "BLA125504",
             "brand": "Cosentyx", "generic": "secukinumab", "modality": "biologic",
             "approval_date": "2015-01-21", "marketing_status": "Prescription",
             "active_ingredients": None},
            {"ticker": "NVS", "internal_code": "BLA125504", "application_number": "BLA761349",
             "brand": "Cosentyx", "generic": "secukinumab", "modality": "biologic",
             "approval_date": "2023-10-06", "marketing_status": "Prescription",
             "active_ingredients": None}]
    fetcher.upsert({"approvals": rows, "supplements": []})
    conn = db.get_connection(path)
    got = conn.execute("SELECT approval_date FROM approvals ORDER BY approval_date").fetchall()
    assert [r["approval_date"] for r in got] == ["2015-01-21", "2023-10-06"]
    asset = conn.execute("SELECT id FROM assets WHERE brand_name = 'Cosentyx'").fetchone()
    assert approval_dates.first_approval(conn, asset["id"], "Cosentyx")[0] == "2015-01-21"
    conn.close()


def test_a_combination_product_is_asked_for_one_molecule_at_a_time():
    """openFDA stores a combination as one string joined by a semicolon, and its
    parser answers a quoted phrase containing one with 400 BAD_REQUEST, "Search not
    supported". The fetcher only ever expected a 404, so Axsome lost every approval to
    a raised error on refresh run 114."""
    from fetchers.approvals_openfda import _molecules

    assert _molecules("Bupropion Hydrochloride; Dextromethorphan Hydrobromide") == [
        "Bupropion Hydrochloride", "Dextromethorphan Hydrobromide"]
    assert _molecules("Meloxicam; Rizatriptan Benzoate") == [
        "Meloxicam", "Rizatriptan Benzoate"]


def test_a_single_molecule_is_unchanged_and_still_loses_its_route_and_form():
    from fetchers.approvals_openfda import _molecules

    assert _molecules("Solriamfetol Hydrochloride") == ["Solriamfetol Hydrochloride"]
    # The form words still come off, which is what the single-name path always did.
    assert _molecules("Oral Extended-Release Treprostinil") == ["Treprostinil"]
    assert _molecules("") == []
    assert _molecules(None) == []


def test_a_repeated_part_is_asked_for_once():
    """A name that says the same salt twice should not spend two requests on it."""
    from fetchers.approvals_openfda import _molecules

    assert _molecules("Meloxicam; Meloxicam") == ["Meloxicam"]
    assert _molecules("Meloxicam; meloxicam ") == ["Meloxicam"]
