"""CMS Part D formulary: the monthly ZIP read by HTTP Range, five members parsed or
counted, and coverage aggregated per brand on its brand RxCUIs. The fixture ZIP has the
live release's nested layout, member names and headers, with rows cut from the
2026-09-16 release (read 2026-10-05); no network."""

from __future__ import annotations

import copy
import io
import json
import zipfile
from pathlib import Path

import pytest

import db
from fetchers import formulary_cms
from fetchers.formulary_cms import (
    PartDFormularyFetcher, RangeReader, RangeRefused, access_rows, member_key,
    pipe_rows, plan_type, release_date_of)

_FIX = Path(__file__).resolve().parent / "fixtures"
_ZIP = (_FIX / "partd_formulary_sample.zip").read_bytes()
_CATALOGUE = json.loads((_FIX / "cms_catalogue_formulary.json").read_text())
_URL = ("https://data.cms.gov/sites/default/files/2026-09/"
        "903ba816-d276-4c17-9b5a-0224bbd4e949/2026_20260916.zip")


class _Ranges:
    """A remote ZIP served from bytes, one call per range, as CMS serves it."""

    def __init__(self, blob=_ZIP, refuse=False):
        self.blob = blob
        self.refuse = refuse
        self.calls = []

    def __call__(self, url, start, end):
        if self.refuse:
            raise RangeRefused(f"{url} answered a range request with HTTP 200")
        self.calls.append((url, start, end))
        return self.blob[start:end + 1], len(self.blob)


def _catalogue_with(url=None):
    catalogue = copy.deepcopy(_CATALOGUE)
    if url:
        newest = max((d for d in catalogue["dataset"] if d["title"].startswith("Monthly")),
                     key=lambda d: d["title"])
        newest["title"] = newest["title"].rsplit(" : ", 1)[0] + " : 2026-10-21"
        newest["distribution"][0]["downloadURL"] = url
    return lambda refresh=False: catalogue


def _db(tmp_path):
    path = str(tmp_path / "formulary.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1,'LLY','Eli Lilly'),"
                 " (2,'BMY','BMS'), (3,'PFE','Pfizer'), (4,'MRK','Merck')")
    conn.execute("""INSERT INTO assets (id, owner_company_id, brand_name, generic_name,
                    is_marketed) VALUES
        (198, 2, 'Eliquis', 'Apixaban', 1), (812, 3, 'Eliquis', 'Apixaban', 1),
        (31, 1, 'Mounjaro', 'Tirzepatide', 1), (22, 1, 'Taltz', 'Ixekizumab', 1),
        (412, 4, 'Keytruda', 'Pembrolizumab', 1)""")
    rows = []
    for asset_id in (198, 812):
        rows += [(asset_id, "rxcui", c, 1) for c in ("1364441", "1364447", "1992428")]
        rows += [(asset_id, "rxcui", "1364445", 0),            # the SCD: every maker's
                 (asset_id, "ndc9", "00003-0893", 1), (asset_id, "ndc9", "00003-0894", 1)]
    rows += [(31, "rxcui", c, 1) for c in ("2601746", "2601764", "2601770")]
    rows += [(22, "rxcui", "1745108", 1), (412, "rxcui", "1657751", 1)]
    conn.executemany("INSERT INTO drug_codes (asset_id, code_type, code, brand_specific,"
                     " basis) VALUES (?, ?, ?, ?, 'rxnav_application')", rows)
    conn.commit()
    conn.close()
    return path


def _fetcher(path, ranges, catalogue=None):
    fetcher = PartDFormularyFetcher(path, get_range=ranges,
                                    load_catalogue=catalogue or _catalogue_with())
    fetcher.force = True
    return fetcher


def _query(path, sql, params=()):
    conn = db.get_connection(path)
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def _access(path, asset_id, release="2026-09-16"):
    row = _query(path, "SELECT * FROM partd_formulary_access WHERE asset_id = ? AND"
                       " release_date = ?", (asset_id, release))[0]
    row["tier_counts"] = json.loads(row["tier_counts"])
    return row


def test_member_names_are_matched_with_cms_double_spaces():
    assert member_key("basic drugs formulary file  20260930.zip") == "basic drugs formulary file"
    assert member_key("plan information  20260930.zip") == "plan information"
    assert member_key("beneficiary cost file  20260930.zip") == "beneficiary cost file"
    assert member_key("insulin beneficiary cost file  20260930.zip") is None
    assert member_key("pharmacy networks file  20260930 part 1.zip") is None
    assert member_key("sample files 20260930.zip") is None


def test_release_date_and_contract_year_come_from_the_zip_name():
    assert release_date_of(_URL, "2026-09-23") == ("2026-09-16", 2026)
    # October's file already describes the next plan year.
    assert release_date_of(".../2026_20251020.zip", None) == ("2025-10-20", 2026)
    assert release_date_of(".../SPUF.zip", "2026-09-23") == ("2026-09-23", None)


def test_plan_types_follow_the_contract_letter():
    assert [plan_type(c) for c in ("H0169", "R0759", "S1030", "E1234")] == [
        "MA-PD", "MA-PD", "PDP", "Other"]


def test_a_renamed_column_fails_loudly():
    with pytest.raises(ValueError, match="TIER_LEVEL_VALUE"):
        list(pipe_rows("FORMULARY_ID|RXCUI\r\n1|2\r\n", "basic drugs formulary file"))


def test_the_range_reader_reads_only_the_members_it_needs(tmp_path):
    path = _db(tmp_path)
    ranges = _Ranges()
    result = _fetcher(path, ranges).run()
    assert result.errors == []
    pharmacy = next(i for i in zipfile.ZipFile(io.BytesIO(_ZIP)).infolist()
                    if i.filename.startswith("pharmacy networks"))
    member_end = pharmacy.header_offset + 30 + len(pharmacy.filename) + pharmacy.compress_size
    for _, start, end in ranges.calls:
        assert end < pharmacy.header_offset or start >= member_end
    release = _query(path, "SELECT * FROM partd_formulary_releases")[0]
    assert release["release_date"] == "2026-09-16" and release["contract_year"] == 2026
    assert release["catalogue_date"] == "2026-09-23" and release["member_date"] == "20260930"
    assert release["range_requests"] == len(ranges.calls)


def test_eliquis_is_listed_everywhere_for_both_owners(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _Ranges()).run()
    for asset_id in (198, 812):
        row = _access(path, asset_id)
        assert row["formularies_total"] == 4 and row["formularies_listing"] == 4
        assert row["tier_counts"] == {"1": 1, "3": 3}
        assert (row["pa_formularies"], row["st_formularies"], row["ql_formularies"]) == (0, 0, 3)
        # Six plans in the file, one suppressed: five counted, four MA-PD and one PDP.
        assert (row["plans_total"], row["plans_listing"]) == (5, 5)
        assert (row["mapd_plans_total"], row["mapd_plans_listing"]) == (4, 4)
        assert (row["pdp_plans_total"], row["pdp_plans_listing"]) == (1, 1)
        assert row["selected_drug"] == 1
        # The SCD is not a brand RxCUI, so it is neither known nor counted.
        assert (row["rxcuis_known"], row["rxcuis_listed"]) == (3, 3)
        # The starter pack's proxy NDC 00003-3764 is not among the codes the test map holds.
        assert row["ndc_mismatches"] == 1 and "00003376474" in row["note"]


def test_mounjaro_prior_authorisation_and_a_formulary_without_it(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _Ranges()).run()
    row = _access(path, 31)
    assert row["formularies_listing"] == 3                   # not on Kaiser's 00026405
    assert row["pa_formularies"] == 3 and row["pa_plans"] == 4
    assert row["tier_counts"] == {"1": 1, "3": 2}
    assert row["ndc_mismatches"] == 0 and row["note"] is None


def test_a_specialty_tier_is_counted_from_the_plan_cost_file(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _Ranges()).run()
    taltz = _access(path, 22)
    assert taltz["formularies_listing"] == 1 and taltz["tier_counts"] == {"5": 1}
    assert taltz["specialty_plans_listing"] == 1             # H0524 marks tier 5 specialty
    assert _access(path, 198)["specialty_plans_listing"] == 0


def test_a_brand_on_no_formulary_still_gets_its_row(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _Ranges()).run()
    keytruda = _access(path, 412)
    assert keytruda["formularies_listing"] == 0 and keytruda["plans_listing"] == 0
    assert keytruda["rxcuis_known"] == 1 and keytruda["tier_counts"] == {}


def test_entries_plans_and_the_counted_members(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _Ranges()).run()
    entries = _query(path, "SELECT * FROM partd_formulary_entries")
    assert {e["rxcui"] for e in entries} == {"1364441", "1364447", "1992428", "2601746",
                                            "2601764", "2601770", "1745108"}
    assert all(e["release_date"] == "2026-09-16" for e in entries)
    plans = {(p["contract_id"], p["plan_id"]): p for p in _query(
        path, "SELECT * FROM partd_plans")}
    assert len(plans) == 6 and plans[("H6824", "001")]["suppressed"] == 1
    assert plans[("H0169", "001")]["counties"] == 2 and plans[("H0169", "001")]["states"] == "IA"
    assert plans[("S1030", "001")]["plan_type"] == "PDP"
    release = _query(path, "SELECT * FROM partd_formulary_releases")[0]
    assert (release["excluded_rows"], release["excluded_plans"],
            release["excluded_book_rows"]) == (7, 2, 0)
    assert (release["indication_rows"], release["indication_plans"],
            release["indication_book_rows"]) == (6, 2, 4)
    assert (release["formularies"], release["plans"], release["plans_suppressed"]) == (4, 5, 1)
    assert release["assets_listed"] == 4


def test_each_release_writes_a_feed_and_a_per_asset_snapshot(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _Ranges()).run()
    snaps = _query(path, "SELECT entity_type, entity_key, payload FROM snapshots"
                         " WHERE source = 'partd_formulary'")
    feed = [json.loads(s["payload"]) for s in snaps if s["entity_type"] == "feed"]
    assert feed[0]["fetch_kind"] == "live" and feed[0]["release_date"] == "2026-09-16"
    per_asset = {s["entity_key"]: json.loads(s["payload"]) for s in snaps
                 if s["entity_type"] == "payer_access"}
    assert set(per_asset) == {"198", "812", "31", "22", "412"}
    assert per_asset["31"]["pa_formularies"] == 3


def test_a_known_release_makes_no_range_request_under_force(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _Ranges()).run()
    ranges = _Ranges()
    result = _fetcher(path, ranges).run()
    assert ranges.calls == []
    assert result.errors == [] and "already read" in result.notes[0]
    feed = _query(path, "SELECT payload FROM snapshots WHERE source = 'partd_formulary'"
                        " AND entity_type = 'feed' ORDER BY id DESC LIMIT 1")[0]
    assert json.loads(feed["payload"])["fetch_kind"] == "cache"


def test_a_refused_range_is_a_soft_error_and_nothing_is_stored(tmp_path):
    path = _db(tmp_path)
    result = _fetcher(path, _Ranges(refuse=True)).run()
    assert len(result.errors) == 1 and "range request" in result.errors[0]
    assert _query(path, "SELECT * FROM partd_formulary_releases") == []
    feed = _query(path, "SELECT payload FROM snapshots WHERE source = 'partd_formulary'")
    assert json.loads(feed[-1]["payload"])["fetch_kind"] == "error"


def test_a_server_that_ignores_the_range_is_refused_before_its_body(monkeypatch):
    class _WholeFile:
        status = 200
        headers = {}

        def read(self):
            raise AssertionError("the 2.3 GB body must never be read")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(formulary_cms.urllib.request, "urlopen",
                        lambda request, timeout=None: _WholeFile())
    with pytest.raises(RangeRefused):
        RangeReader(_URL)


def test_access_rows_append_across_releases_and_are_never_overwritten(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _Ranges()).run()
    first = _access(path, 198)
    later = _URL.replace("2026_20260916", "2027_20261014")
    _fetcher(path, _Ranges(), _catalogue_with(later)).run()
    rows = _query(path, "SELECT release_date, contract_year FROM partd_formulary_access"
                        " WHERE asset_id = 198 ORDER BY release_date")
    assert [r["release_date"] for r in rows] == ["2026-09-16", "2026-10-14"]
    assert rows[1]["contract_year"] == 2026          # the file's own CONTRACT_YEAR wins
    assert _access(path, 198) == first
    assert {e["release_date"] for e in _query(
        path, "SELECT release_date FROM partd_formulary_entries")} == {"2026-10-14"}


def test_the_best_placed_rxcui_sets_the_tier_and_any_rxcui_carries_a_flag():
    entries = [
        {"formulary_id": "F1", "rxcui": "A", "ndc11": "00003089321", "tier": 4,
         "prior_auth": 1, "step_therapy": 0, "quantity_limit": 0, "selected_drug": 0},
        {"formulary_id": "F1", "rxcui": "B", "ndc11": "00003089421", "tier": 2,
         "prior_auth": 0, "step_therapy": 1, "quantity_limit": 0, "selected_drug": 0},
        {"formulary_id": "F2", "rxcui": "B", "ndc11": "00003089421", "tier": 3,
         "prior_auth": 0, "step_therapy": 0, "quantity_limit": 1, "selected_drug": 0}]
    plans = {("H1", "001", "000"): {"contract_id": "H1", "plan_id": "001",
                                    "segment_id": "000", "formulary_id": "F1",
                                    "plan_type": "MA-PD", "suppressed": 0},
             ("S1", "001", "000"): {"contract_id": "S1", "plan_id": "001",
                                    "segment_id": "000", "formulary_id": "F2",
                                    "plan_type": "PDP", "suppressed": 0}}
    row = access_rows(entries, {7: {"A", "B"}}, {7: {"00003-0893", "00003-0894"}},
                      {"F1", "F2", "F3"}, plans, {("H1", "001", "000", "2")})[7]
    assert row["tier_counts"] == {"2": 1, "3": 1}
    assert (row["pa_formularies"], row["st_formularies"], row["ql_formularies"]) == (1, 1, 1)
    assert (row["formularies_listing"], row["formularies_total"]) == (2, 3)
    assert row["specialty_plans_listing"] == 1 and row["ndc_mismatches"] == 0
