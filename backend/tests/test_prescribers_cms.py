"""CMS Part D Prescribers: national rows matched to brands, the provider file reduced to
aggregates, and the release guards that hold under a forced run. Fixtures are live CMS
payloads (2024 data year, read 2026-10-05), trimmed; no network."""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import pytest

import cms
import db
from fetchers.prescribers_cms import (
    VOLUME_DECILE_NOTE, PartDPrescribersFetcher, ProviderAccumulator, concentration,
    days_covered, file_measures, match_national, parse_national)

_FIX = Path(__file__).resolve().parent / "fixtures"
_GEO = json.loads((_FIX / "cms_prescribers_geo_national.json").read_text())
_PROVIDER = json.loads((_FIX / "cms_prescribers_provider_sample.json").read_text())
_CATALOGUE = json.loads((_FIX / "cms_catalogue_partd_prescribers.json").read_text())

_PROVIDER_2024 = "d5aa71a8-dcc0-4570-8bcf-bd39deac69fe"
_PROVIDER_SERIES = "9552739e-3d05-4c1b-8eff-ecabf391e2e5"
_GEO_2024 = "9b4c142c-69cc-4a96-a09a-7cf2ba7f5816"
_GEO_2023 = "3463648b-1971-478d-84ca-80cadc758153"


class _FakeCms:
    """data.cms.gov as the fixtures saw it: the 2024 national rows (served for 2023 as
    well), the Repatha provider rows, and stats that count them."""

    def __init__(self, total_rows=28023892, found=None, extra=None):
        self.total_rows = total_rows
        self.found = found or {}
        self.extra = extra or {}
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        uuid = parsed.path.split("/dataset/")[1].split("/")[0]
        stats = parsed.path.endswith("/stats")
        if uuid in (_PROVIDER_2024, _PROVIDER_SERIES):
            assert "filter[Gnrc_Name]" not in query       # the slow filter is never sent
            brand = query.get("filter[Brnd_Name]")
            if stats and brand is None:
                return {"found_rows": self.total_rows, "total_rows": self.total_rows}
            rows = self.extra.get(brand, []) + _PROVIDER.get(brand, [])
            if stats:
                return {"found_rows": self.found.get(brand, len(rows)),
                        "total_rows": self.total_rows}
            offset, size = int(query["offset"]), int(query["size"])
            return rows[offset:offset + size]
        if uuid in (_GEO_2024, _GEO_2023):
            assert query["filter[Prscrbr_Geo_Lvl]"] == "National"
            return _GEO[int(query["offset"]):int(query["offset"]) + int(query["size"])]
        return []                               # 2020 to 2022: nothing matched

    def provider_pulls(self, brand):
        return [c for c in self.calls if "column=Prscrbr_NPI" in c
                and urllib.parse.quote_plus(brand) in c]


class _Catalogue:
    def __init__(self):
        self.refreshes = 0

    def __call__(self, refresh=False):
        self.refreshes += int(refresh)
        return _CATALOGUE


def _db(tmp_path):
    path = str(tmp_path / "partd.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1,'AMGN','Amgen'),"
                 " (2,'BMY','BMS'), (3,'PFE','Pfizer'), (4,'REGN','Regeneron'),"
                 " (5,'SNY','Sanofi'), (6,'AZN','AstraZeneca'), (7,'GSK','GSK')")
    conn.execute("""INSERT INTO assets (id, owner_company_id, brand_name, generic_name,
                    is_marketed) VALUES
        (10, 1, 'Repatha', 'Evolocumab', 1), (198, 2, 'Eliquis', 'Apixaban', 1),
        (812, 3, 'Eliquis', 'Apixaban', 1), (424, 4, 'Dupixent', 'Dupilumab', 1),
        (909, 5, 'Dupixent', 'Dupilumab', 1), (30, 3, 'Lyrica', 'Pregabalin', 1),
        (40, 6, 'Crestor', 'Rosuvastatin Calcium', 1),
        (50, 7, 'Shingrix', 'Zoster Vaccine Recombinant, Adjuvanted', 1)""")
    conn.commit()
    conn.close()
    return path


def _fetcher(path, fake, catalogue=None, budget_s=900, workers=1):
    fetcher = PartDPrescribersFetcher(path, budget_s=budget_s, get_json=fake,
                                      load_catalogue=catalogue or _Catalogue(),
                                      workers=workers)
    fetcher.force = True
    return fetcher


def _row(path, asset_id, year=2024):
    conn = db.get_connection(path)
    try:
        row = conn.execute("SELECT * FROM partd_prescribing WHERE asset_id = ?"
                           " AND data_year = ?", (asset_id, year)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _last_snapshot(path):
    conn = db.get_connection(path)
    try:
        return json.loads(conn.execute(
            "SELECT payload FROM snapshots WHERE source = 'partd_prescribers'"
            " ORDER BY id DESC LIMIT 1").fetchone()[0])
    finally:
        conn.close()


# --- parsing and matching -------------------------------------------------------------
def test_a_suppressed_count_is_null_never_zero():
    rows = {r["brand"]: r for r in parse_national(_GEO)}
    assert rows["Absorica Ld"]["beneficiaries"] is None          # Tot_Benes ''
    assert rows["Absorica Ld"]["benes_ge65"] is None             # GE65 flag '*'
    assert rows["Acetamin-Caff-Dihydrocodeine"]["beneficiaries"] == 26
    assert rows["Acetamin-Caff-Dihydrocodeine"]["benes_ge65"] is None   # GE65 flag '#'
    assert rows["Eliquis"]["prescribers"] == 556431


def _matched(tmp_path):
    path = _db(tmp_path)
    conn = db.get_connection(path)
    try:
        names, own = cms.brand_assets(conn), cms.own_names(conn)
    finally:
        conn.close()
    return match_national(parse_national(_GEO), names, own)


def test_generic_rows_are_dropped_and_a_different_product_stays_out(tmp_path):
    matched = _matched(tmp_path)
    assert matched[30]["cms_brands"] == [["Lyrica", "Pregabalin"]]   # not Pregabalin, not CR
    assert matched[40]["cms_brands"] == [["Crestor", "Rosuvastatin Calcium"]]
    assert matched[30]["national_beneficiaries"] == 11801


def test_containers_are_summed_and_said_to_be_an_upper_bound(tmp_path):
    repatha = _matched(tmp_path)[10]
    assert repatha["presentations"] == 3
    assert repatha["national_claims"] == 67989 + 1943410 + 233704
    assert repatha["national_beneficiaries"] == 19311 + 382343 + 58128
    assert "counted twice" in repatha["national_note"]


def test_a_suppressed_container_leaves_the_proxy_on_the_containers_it_can_pair(tmp_path):
    # Repatha's three containers, with CMS's beneficiary count for the Syringe blanked:
    # its 1.9 million claims of fills would otherwise sit over the other two containers'
    # people and take the proxy far past what any patient was supplied.
    path = _db(tmp_path)
    conn = db.get_connection(path)
    try:
        names, own = cms.brand_assets(conn), cms.own_names(conn)
    finally:
        conn.close()
    rows = parse_national(_GEO)
    for row in rows:
        if row["brand"] == "Repatha Syringe":
            row["beneficiaries"] = None
    repatha = match_national(rows, names, own)[10]
    others = [r for r in rows if r["brand"] in ("Repatha Pushtronex", "Repatha Sureclick")]
    assert repatha["national_beneficiaries"] == sum(r["beneficiaries"] for r in others)
    assert repatha["national_fills_30d"] == pytest.approx(
        sum(r["fills_30d"] for r in rows if r["brand"].startswith("Repatha")), abs=0.1)
    assert repatha["days_covered_share"] == days_covered(
        sum(r["fills_30d"] for r in others), sum(r["beneficiaries"] for r in others))
    assert "1 of 3 beneficiary counts were suppressed" in repatha["national_note"]
    assert "presentations whose beneficiary count CMS published" in repatha["national_note"]
    # Every container suppressed: no proxy at all, never a ratio over nobody.
    for row in rows:
        if row["brand"].startswith("Repatha"):
            row["beneficiaries"] = None
    assert match_national(rows, names, own)[10]["days_covered_share"] is None


def test_a_co_marketed_brand_is_stored_for_both_owners(tmp_path):
    matched = _matched(tmp_path)
    assert matched[198]["national_prescribers"] == matched[812]["national_prescribers"] \
        == 556431
    assert matched[424]["presentations"] == matched[909]["presentations"] == 2


def test_the_national_days_covered_proxy_for_eliquis():
    # 38,760,676.6 fills x 30 / (4,423,497 x 365): 0.72, as research measured it.
    assert days_covered(38760676.6, 4423497) == pytest.approx(0.7202, abs=1e-4)
    assert days_covered(100.0, None) is None


# --- arithmetic -----------------------------------------------------------------------
def test_deciles_and_shares_on_twenty_prescribers():
    got = concentration(list(range(1, 21)))           # 20 prescribers, 210 claims
    assert got["claims_share_by_npi_decile"] == pytest.approx(
        [c / 210 for c in (39, 35, 31, 27, 23, 19, 15, 11, 7, 3)], abs=1e-6)
    assert got["top10pct_claims_share"] == pytest.approx(39 / 210, abs=1e-6)
    assert got["top1pct_claims_share"] is None        # under 100 prescribers
    assert got["prescribers_for_50pct"] == 6
    assert got["prescribers_for_80pct"] == 12
    assert got["hhi"] == pytest.approx(10000 / 44100 * 2870, abs=0.01)
    assert got["median_claims_per_prescriber"] == 10.5


def test_too_few_prescribers_for_deciles_leaves_them_null():
    got = concentration([50, 20, 11])
    assert got["claims_share_by_npi_decile"] is None
    assert got["top10pct_claims_share"] is None
    assert got["prescribers_for_50pct"] == 1


def test_two_presentations_are_unioned_by_prescriber_not_double_counted():
    acc = ProviderAccumulator()
    for brand in ("Repatha Pushtronex", "Repatha Syringe"):
        acc.add(_PROVIDER[brand])
    every = _PROVIDER["Repatha Pushtronex"] + _PROVIDER["Repatha Syringe"]
    reduced = acc.reduce()
    assert reduced["file_prescribers"] == len({r["Prscrbr_NPI"] for r in every}) == 34
    assert reduced["file_claims"] == sum(int(r["Tot_Clms"]) for r in every)
    assert reduced["file_day_supply"] == sum(int(r["Tot_Day_Suply"]) for r in every)
    assert sum(s["claims_share"] for s in reduced["specialties"]) == pytest.approx(1.0)
    assert all(s["claims_share"] >= 0.01 for s in reduced["specialties"]
               if s["specialty"] != "Other")


def test_the_file_based_proxy_waits_for_95_percent_of_claims():
    national = {"national_claims": 1000, "national_beneficiaries": 10}
    short = file_measures(national, {"file_claims": 900, "file_day_supply": 27000})
    assert short["days_covered_share_file"] is None
    assert "95%" in short["file_note"] and "90.0%" in short["file_note"]
    assert short["days_supply_per_claim"] == 30.0
    full = file_measures(national, {"file_claims": 960, "file_day_supply": 28800})
    assert full["days_covered_share_file"] == pytest.approx(28800 / 3650, abs=1e-4)


# --- the fetcher ----------------------------------------------------------------------
def test_a_first_run_backfills_national_years_and_reduces_the_newest(tmp_path):
    path = _db(tmp_path)
    fake = _FakeCms()
    result = _fetcher(path, fake).run()
    assert not result.errors, result.errors
    national_reads = [c for c in fake.calls if "Prscrbr_Geo_Lvl" in c]
    assert len(national_reads) == 5                       # one request each, 2020 to 2024
    repatha = _row(path, 10)
    assert repatha["file_status"] == "complete"
    assert repatha["file_prescribers"] == 34
    assert repatha["prescribers_by_volume_decile"] is None
    assert repatha["volume_decile_note"] == VOLUME_DECILE_NOTE
    assert json.loads(repatha["cms_brands"])[0] == ["Repatha Pushtronex", "Evolocumab"]
    assert _row(path, 10, 2023)["file_status"] is None      # national only, not read
    assert _row(path, 10, 2023)["national_claims"] == repatha["national_claims"]
    # Eliquis is pulled once and stored for both owners.
    assert len(fake.provider_pulls("Eliquis")) == 1
    assert _row(path, 812)["file_status"] == _row(path, 198)["file_status"] == "complete"
    snap = _last_snapshot(path)
    assert snap["fetch_kind"] == "live" and snap["data_year"] == 2024
    assert snap["assets_pending"] == 0
    conn = db.get_connection(path)
    specialties = conn.execute("SELECT COUNT(*) FROM partd_prescriber_specialties"
                               " WHERE asset_id = 10").fetchone()[0]
    ledger = {(r[0], r[1]) for r in conn.execute(
        "SELECT dataset, data_year FROM partd_prescriber_releases")}
    conn.close()
    assert specialties >= 2
    assert ("provider", 2024) in ledger and ("geography", 2020) in ledger


def test_a_forced_run_with_nothing_new_makes_one_stats_call(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _FakeCms()).run()
    fake = _FakeCms()
    result = _fetcher(path, fake).run()
    assert not result.errors
    assert len(fake.calls) == 1 and "/stats" in fake.calls[0]
    assert any("no new Part D Prescribers release" in n for n in result.notes)
    assert _last_snapshot(path)["fetch_kind"] == "cache"


def test_a_changed_row_count_reads_the_catalogue_fresh_and_pulls_again(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _FakeCms()).run()
    catalogue = _Catalogue()
    fake = _FakeCms(total_rows=28023893)
    _fetcher(path, fake, catalogue=catalogue).run()
    assert catalogue.refreshes == 1
    assert fake.provider_pulls("Repatha Syringe")             # pulled again
    assert _row(path, 10)["file_status"] == "complete"


def test_the_budget_stops_part_way_and_the_next_run_resumes_the_rest(tmp_path):
    path = _db(tmp_path)
    first = _fetcher(path, _FakeCms(), budget_s=0).run()
    assert any("run budget" in n for n in first.notes)
    conn = db.get_connection(path)
    statuses = dict(conn.execute("SELECT asset_id, file_status FROM partd_prescribing"
                                 " WHERE data_year = 2024").fetchall())
    conn.close()
    done = [a for a, s in statuses.items() if s == "complete"]
    assert len(done) == 2                    # the largest brand, Eliquis, for both owners
    assert _last_snapshot(path)["assets_pending"] == len(statuses) - 2
    fake = _FakeCms()
    _fetcher(path, fake).run()
    assert not fake.provider_pulls("Eliquis")                 # done, not pulled again
    assert fake.provider_pulls("Repatha Syringe")
    assert _row(path, 10)["file_status"] == "complete"


def test_a_count_that_does_not_reconcile_is_left_incomplete(tmp_path):
    path = _db(tmp_path)
    result = _fetcher(path, _FakeCms(found={"Repatha Syringe": 9999})).run()
    repatha = _row(path, 10)
    assert repatha["file_status"] == "incomplete"
    assert repatha["file_claims"] is None
    assert "9999" in repatha["file_note"]
    assert any("Repatha" in e for e in result.errors)


def test_another_ingredient_under_the_brand_name_is_counted_but_not_folded_in(tmp_path):
    """The brand name is pulled whole, so the count against CMS's stats still holds, and
    a row of a different ingredient under the same name stays out of the aggregate."""
    path = _db(tmp_path)
    stray = {**_PROVIDER["Repatha Syringe"][0], "Prscrbr_NPI": "1999999999",
             "Gnrc_Name": "Something Else", "Tot_Clms": "500"}
    result = _fetcher(path, _FakeCms(extra={"Repatha Syringe": [stray]})).run()
    assert not result.errors
    repatha = _row(path, 10)
    assert repatha["file_status"] == "complete"
    assert repatha["file_prescribers"] == 34                  # the stray NPI is not in


def test_a_source_outage_is_a_soft_error_with_an_error_snapshot(tmp_path):
    path = _db(tmp_path)

    def down(_url):
        raise OSError("data.cms.gov unreachable")

    result = _fetcher(path, down).run()
    assert result.errors
    assert _last_snapshot(path)["fetch_kind"] == "error"


def test_pulls_that_keep_failing_stop_the_run_rather_than_retry_every_brand(tmp_path):
    path = _db(tmp_path)
    fake = _FakeCms()

    def flaky(url):
        if "column=Prscrbr_NPI" in url:
            raise OSError("timed out")
        return fake(url)

    result = _fetcher(path, flaky).run()
    assert any("failed in a row" in e for e in result.errors)
    conn = db.get_connection(path)
    statuses = [r[0] for r in conn.execute(
        "SELECT file_status FROM partd_prescribing WHERE data_year = 2024")]
    conn.close()
    assert statuses.count("incomplete") == 4     # Eliquis twice, Repatha, Shingrix
    assert "pending" in statuses                 # the rest wait for the next run


def test_concurrent_pulls_store_what_one_at_a_time_stores(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    one, four = _db(tmp_path / "a"), _db(tmp_path / "b")
    _fetcher(one, _FakeCms(), workers=1).run()
    result = _fetcher(four, _FakeCms(), workers=4).run()
    assert not result.errors
    fields = ("file_status", "file_prescribers", "file_claims", "hhi",
              "claims_share_by_npi_decile", "national_claims")
    for asset_id in (10, 198, 812, 424, 909, 30, 40, 50):
        assert [_row(one, asset_id)[f] for f in fields] == \
            [_row(four, asset_id)[f] for f in fields]
