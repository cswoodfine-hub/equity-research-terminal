"""Medicaid State Drug Utilization Data: national rows summed to product codes, kept by
code rather than by asset, and the release guard that holds under a forced run. The
fixture is live data.medicaid.gov payloads (read 2026-10-05), trimmed; no network."""

from __future__ import annotations

import copy
import json
import urllib.parse
from pathlib import Path

import db
from fetchers.utilization_medicaid import (
    METASTORE_URL, MedicaidSdudFetcher, SdudReducer, parse_catalogue, query_url)

_FIX = json.loads((Path(__file__).resolve().parent / "fixtures"
                   / "sdud_national_sample.json").read_text())
_IDS = {"2023": "d890d3a9-6b00-43fd-8b31-fcba4c8e2909",
        "2024": "61729e5a-7aa8-448c-8903-ba3e0cd0ea3c",
        "2025": "158a1baa-5506-400a-8ec3-97756f0b0536",
        "2026": "2957a7f9-9a15-453e-9afd-3bbdcbac8fd3"}


class _FakeMedicaid:
    """data.medicaid.gov as the fixture saw it: the metastore, and a datastore query
    that applies '=' conditions, the sorts, limit, offset and count."""

    def __init__(self, metastore=None, national=None, count_offset=0):
        self.metastore = metastore or copy.deepcopy(_FIX["metastore"])
        self.national = national or copy.deepcopy(_FIX["national"])
        self.count_offset = count_offset
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url == METASTORE_URL:
            return self.metastore
        parsed = urllib.parse.urlparse(url)
        dataset_id = parsed.path.split("/query/")[1].split("/")[0]
        year = next(y for y, i in _IDS.items() if i == dataset_id)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        rows = list(self.national.get(year, []))
        i = 0
        while f"conditions[{i}][property]" in query:
            prop, value = query[f"conditions[{i}][property]"], query[f"conditions[{i}][value]"]
            assert query[f"conditions[{i}][operator]"] == "="
            rows = [r for r in rows if str(r[prop]) == value]
            i += 1
        keys = [query[f"sorts[{j}][property]"] for j in range(3)
                if f"sorts[{j}][property]" in query]
        if keys:
            rows.sort(key=lambda r: tuple(str(r[k]) for k in keys))
        offset, limit = int(query["offset"]), int(query["limit"])
        out = {"results": rows[offset:offset + limit]}
        if query["count"] == "true":
            out["count"] = len(rows) + self.count_offset
        return out

    def data_calls(self):
        return [c for c in self.calls if c != METASTORE_URL and "limit=1&" not in c]


def _db(tmp_path):
    path = str(tmp_path / "sdud.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1,'LLY','Eli Lilly'),"
                 " (2,'BMY','BMS'), (3,'PFE','Pfizer'), (4,'INCY','Incyte'),"
                 " (5,'BAYN','Bayer')")
    conn.execute("""INSERT INTO assets (id, owner_company_id, brand_name, generic_name,
                    is_marketed) VALUES
        (198, 2, 'Eliquis', 'Apixaban', 1), (812, 3, 'Eliquis', 'Apixaban', 1),
        (1, 1, 'Olumiant', 'Baricitinib', 1), (3595, 4, 'Olumiant', 'Baricitinib', 1),
        (20, 1, 'Humalog', 'Insulin Lispro', 1), (22, 1, 'Taltz', 'Ixekizumab', 1),
        (13, 1, 'Zepbound', 'Tirzepatide', 1), (481, 5, 'Miralax', 'Polyethylene Glycol', 1),
        (500, 2, 'Kenalog', 'Triamcinolone', 1)""")
    codes = [(198, "00003-0893", 1, 1), (812, "00003-0893", 1, 1),
             (198, "00003-0894", 1, 1), (812, "00003-0894", 1, 1),
             (198, "00003-3764", 1, 1), (812, "00003-3764", 1, 1),
             (1, "00002-4182", 1, 1), (3595, "00002-4182", 1, 0),
             (20, "00002-7737", 0, 1), (22, "00002-1445", 1, 1),
             (13, "00002-0152", 1, 1), (481, "52268-0800", 1, None)]
    conn.executemany(
        "INSERT INTO drug_codes (asset_id, code_type, code, brand_specific, labeler_code,"
        " is_owner_labeler, basis) VALUES (?, 'ndc9', ?, ?, substr(?, 1, 5), ?,"
        " 'rxnav_application')", [(a, c, b, c, o) for a, c, b, o in codes])
    conn.commit()
    conn.close()
    return path


def _fetcher(path, fake, page=20):
    fetcher = MedicaidSdudFetcher(path, get_json=fake, page=page)
    fetcher.force = True
    return fetcher


def _query(path, sql, params=()):
    conn = db.get_connection(path)
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def _asset_rx(path, asset_id, year, brand_only=True):
    """An asset's prescriptions, joined through drug_codes as a reader would."""
    rows = _query(path, """
        SELECT SUM(m.prescriptions) AS rx FROM medicaid_utilization m
          JOIN drug_codes d ON d.code_type = 'ndc9' AND d.code = m.ndc9
         WHERE d.asset_id = ? AND m.year = ? AND (? = 0 OR d.brand_specific = 1)
        """, (asset_id, year, int(brand_only)))
    return rows[0]["rx"]


def _fixture_rx(year, product_codes):
    return sum(int(r["number_of_prescriptions"] or 0) for r in _FIX["national"][year]
               if r["ndc"][:5] + "-" + r["ndc"][5:9] in product_codes)


def _last_snapshot(path):
    return json.loads(_query(path, "SELECT payload FROM snapshots WHERE source ="
                                   " 'medicaid_sdud' ORDER BY id DESC LIMIT 1")[0]["payload"])


def test_catalogue_reads_every_sdud_year_and_nothing_else():
    catalogue = parse_catalogue(_FIX["metastore"])
    assert sorted(catalogue) == [2023, 2024, 2025, 2026]
    assert catalogue[2025]["dataset_id"] == _IDS["2025"]
    assert catalogue[2025]["modified"] == "2026-07-13T15:28:32+00:00"


def test_query_url_sorts_on_the_national_row_key():
    url = query_url(_IDS["2025"], [("state", "=", "XX")], limit=8000, offset=16000,
                    count=True, sort=True)
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert query["conditions[0][value]"] == "XX"
    assert [query[f"sorts[{i}][property]"] for i in range(3)] == [
        "ndc", "quarter", "utilization_type"]
    assert query["limit"] == "8000" and query["offset"] == "16000"


def test_two_newest_full_years_are_held_and_a_part_year_is_not(tmp_path):
    path = _db(tmp_path)
    result = _fetcher(path, _FakeMedicaid()).run()
    assert result.errors == []
    ledger = {r["year"]: r for r in _query(path, "SELECT * FROM medicaid_sdud_releases")}
    assert ledger[2026]["full_year"] == 0 and ledger[2026]["fetched_at"] is None
    assert ledger[2025]["full_year"] == 1 and ledger[2025]["fetched_at"] is not None
    assert ledger[2024]["fetched_at"] is not None
    assert 2023 not in ledger                   # two full years found before it
    years = {r["year"] for r in _query(path, "SELECT DISTINCT year FROM medicaid_utilization")}
    assert years == {2024, 2025}


def test_eliquis_belongs_to_both_owners_with_the_national_sums(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _FakeMedicaid()).run()
    expected = _fixture_rx("2025", {"00003-0893", "00003-0894", "00003-3764"})
    assert expected > 2_000_000
    assert _asset_rx(path, 198, 2025) == expected
    assert _asset_rx(path, 812, 2025) == expected
    assert _asset_rx(path, 198, 2024) == _fixture_rx("2024", {"00003-0893", "00003-0894"})
    rows = _query(path, "SELECT * FROM medicaid_utilization WHERE ndc9 = '00003-0894'"
                        " AND year = 2025 ORDER BY quarter, utilization_type")
    assert [(r["quarter"], r["utilization_type"]) for r in rows] == [
        (1, "FFSU"), (1, "MCOU"), (2, "FFSU"), (2, "MCOU"), (3, "FFSU"), (3, "MCOU"),
        (4, "FFSU"), (4, "MCOU")]
    assert rows[0]["product_name"] == "Eliquis"


def test_suppressed_packages_add_to_no_sum_and_an_all_suppressed_code_is_null(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _FakeMedicaid()).run()
    taltz = _query(path, "SELECT * FROM medicaid_utilization WHERE ndc9 = '00002-1445'"
                         " AND quarter = 2 AND utilization_type = 'FFSU'")[0]
    assert taltz["packages"] == 4 and taltz["packages_suppressed"] == 1
    assert taltz["prescriptions"] == 189 + 6046 + 444
    zepbound = _query(path, "SELECT * FROM medicaid_utilization WHERE ndc9 = '00002-0152'"
                            " AND quarter = 4 AND utilization_type = 'FFSU'")[0]
    assert zepbound["packages_suppressed"] == zepbound["packages"] == 1
    assert zepbound["prescriptions"] is None and zepbound["total_reimbursed"] is None


def test_unbranded_codes_are_kept_apart_from_brand_volume(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _FakeMedicaid()).run()
    assert _asset_rx(path, 20, 2025) is None                 # Humalog brand: no rows
    lispro = _asset_rx(path, 20, 2025, brand_only=False)     # its authorised generic
    assert lispro == _fixture_rx("2025", {"00002-7737"}) > 0
    snap = _last_snapshot(path)
    assert snap["fetch_kind"] == "live"
    assert "20" not in snap["asset_prescriptions"]
    assert snap["asset_prescriptions"]["198"]["2025"] == _asset_rx(path, 198, 2025)


def test_book_labeler_rows_are_held_and_others_dropped(tmp_path):
    path = _db(tmp_path)
    result = _fetcher(path, _FakeMedicaid()).run()
    held = {r["ndc9"] for r in _query(path, "SELECT DISTINCT ndc9 FROM medicaid_utilization")}
    assert "00003-0293" in held                  # Kenalog-40: BMS's labeler, no code yet
    assert "00054-8297" not in held              # furosemide: not the book's
    assert "52268-0800" in held                  # Miralax under a labeler the map named
    ledger = _query(path, "SELECT * FROM medicaid_sdud_releases WHERE year = 2025")[0]
    assert ledger["national_rows"] == len(_FIX["national"]["2025"])
    assert ledger["unmatched_owner_rows"] == sum(
        1 for r in _FIX["national"]["2025"] if r["ndc"].startswith("000030293"))
    assert ledger["kept_rows"] == ledger["matched_rows"] + ledger["unmatched_owner_rows"]
    assert any("00003-0293 KENALOG-40" in n for n in result.notes)


def test_a_corrected_code_map_moves_rows_without_a_refetch(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _FakeMedicaid()).run()
    assert _asset_rx(path, 500, 2025) is None
    conn = db.get_connection(path)
    conn.execute("INSERT INTO drug_codes (asset_id, code_type, code, brand_specific,"
                 " labeler_code, is_owner_labeler, basis) VALUES (500, 'ndc9',"
                 " '00003-0293', 1, '00003', 1, 'curated')")
    conn.commit()
    conn.close()
    assert _asset_rx(path, 500, 2025) == _fixture_rx("2025", {"00003-0293"}) > 0


def test_forced_rerun_with_no_new_release_reads_only_the_metastore(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _FakeMedicaid()).run()
    fake = _FakeMedicaid()
    result = _fetcher(path, fake).run()
    assert fake.calls == [METASTORE_URL]        # no fullness probe, no data page
    assert result.errors == [] and "nothing was read" in result.notes[0]
    assert _last_snapshot(path)["fetch_kind"] == "cache"


def test_a_revised_year_is_replaced_whole_and_the_other_left_alone(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _FakeMedicaid()).run()
    before_2024 = _query(path, "SELECT id FROM medicaid_utilization WHERE year = 2024")
    fake = _FakeMedicaid()
    for item in fake.metastore:
        if item["identifier"] == _IDS["2025"]:
            item["modified"] = "2026-10-12T00:00:00+00:00"
    fake.national["2025"] = [r for r in fake.national["2025"]
                             if not r["ndc"].startswith("000030293")]
    _fetcher(path, fake).run()
    held = {r["ndc9"] for r in _query(path, "SELECT DISTINCT ndc9 FROM medicaid_utilization"
                                            " WHERE year = 2025")}
    assert "00003-0293" not in held and "00003-0894" in held
    assert _query(path, "SELECT id FROM medicaid_utilization WHERE year = 2024") == before_2024
    assert all(_IDS["2024"] not in c for c in fake.data_calls())
    assert _query(path, "SELECT modified FROM medicaid_sdud_releases WHERE year = 2025"
                  )[0]["modified"] == "2026-10-12T00:00:00+00:00"


def test_a_short_read_keeps_the_stored_year_and_reports_it(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _FakeMedicaid()).run()
    stored = _query(path, "SELECT COUNT(*) AS n FROM medicaid_utilization")[0]["n"]
    fake = _FakeMedicaid(count_offset=1)
    for item in fake.metastore:
        if item["identifier"] == _IDS["2025"]:
            item["modified"] = "2026-10-12T00:00:00+00:00"
    result = _fetcher(path, fake).run()
    assert any("stored year stands" in e for e in result.errors)
    assert _query(path, "SELECT COUNT(*) AS n FROM medicaid_utilization")[0]["n"] == stored
    ledger = _query(path, "SELECT modified FROM medicaid_sdud_releases WHERE year = 2025")[0]
    assert ledger["modified"] == "2026-07-13T15:28:32+00:00"    # still due next run


def test_the_reducer_skips_state_rows_and_other_years():
    reducer = SdudReducer(2025, {"00003-0894"}, set())
    row = dict(next(r for r in _FIX["national"]["2025"] if r["ndc"] == "00003089421"))
    reducer.add([row, {**row, "state": "NY"}, {**row, "year": "2024"},
                 {**row, "ndc": "0003089421"}])
    assert reducer.national_rows == 1 and reducer.skipped == 3
    assert reducer.result()[0]["prescriptions"] == int(row["number_of_prescriptions"])


def test_a_book_with_no_codes_yet_reads_nothing_and_marks_no_year_read(tmp_path):
    path = _db(tmp_path)
    conn = db.get_connection(path)
    conn.execute("DELETE FROM drug_codes")
    conn.commit()
    conn.close()
    fake = _FakeMedicaid()
    result = _fetcher(path, fake).run()
    assert fake.calls == []                      # not even the metastore
    assert result.errors == [] and "no product code yet" in result.notes[0]
    assert _query(path, "SELECT * FROM medicaid_sdud_releases") == []
    assert _last_snapshot(path)["fetch_kind"] == "cache"
