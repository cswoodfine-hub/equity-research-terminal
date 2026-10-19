"""Medicaid prescriptions per product code and quarter, from the State Drug Utilization
Data (data.medicaid.gov).

Medicaid fee-for-service and managed care only, and gross of rebates: the dictionary
says the reimbursed totals are "not reduced or affected by Medicaid rebates paid to the
state". The figures are volume, never revenue.

data.medicaid.gov publishes one dataset per year ("State Drug Utilization Data 2025"),
found by title in the DKAN metastore, never keyed by hand. Each year's national rows
(state 'XX', about 320,000 a year against 5.3 million state rows) are paged from the
datastore query endpoint, 8,000 a page (the cap), sorted on NDC, quarter and utilisation
type, which no two national rows share, so the paging is stable. Only the two newest
full years are held; a year is full once it has national fourth-quarter rows.

Package NDCs are summed to the product code 'LLLLL-PPPP' that drug_codes keys on. A row
is kept when its product code is in drug_codes or its labeler is one of the book's own
labelers, so a code the map misses is already held when the map is corrected; rows are
keyed by product code and joined to assets at read time, which is what lets co-marketed
Eliquis belong to both of its owners. A suppressed package row has no figures and adds
to no sum, only to packages_suppressed.

The daily refresh runs forced, so the guard reads medicaid_sdud_releases: a year is read
again only when its dataset id or modified date changes (CMS revises past years), and is
then replaced whole.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import db
import ndc
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "medicaid_sdud"
ENTITY_KEY = "sdud"
TTL_SECONDS = 7 * 24 * 60 * 60
YEARS_HELD = 2
METASTORE_URL = "https://data.medicaid.gov/api/1/metastore/schemas/dataset/items"
QUERY_URL = "https://data.medicaid.gov/api/1/datastore/query/{dataset_id}/0"
NATIONAL = "XX"
_TITLE = re.compile(r"^State Drug Utilization Data (\d{4})$")
_PAGE = 8000                    # the datastore's cap: a larger limit is an HTTP 400
_SORTS = ("ndc", "quarter", "utilization_type")   # unique among national rows
_YEARS_EXAMINED = 5             # newest years asked about before giving up on two full
_SUMS = (("number_of_prescriptions", "prescriptions"),
         ("units_reimbursed", "units_reimbursed"),
         ("total_amount_reimbursed", "total_reimbursed"),
         ("medicaid_amount_reimbursed", "medicaid_reimbursed"),
         ("non_medicaid_amount_reimbursed", "non_medicaid_reimbursed"))
_SLEEP_S = 0.2
_TIMEOUT_S = 120
_ATTEMPTS = 3
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_GAP_EXAMPLES = 5


# --- pure parsing ---------------------------------------------------------------------

def parse_catalogue(items: list[dict]) -> dict:
    """{year: {dataset_id, modified}} for every State Drug Utilization Data dataset."""
    out = {}
    for item in items or []:
        match = _TITLE.match((item.get("title") or "").strip())
        if not match or not item.get("identifier"):
            continue
        out[int(match.group(1))] = {"dataset_id": item["identifier"],
                                    "modified": item.get("modified")}
    return out


def query_url(dataset_id: str, conditions: list[tuple], limit: int, offset: int = 0,
              count: bool = False, sort: bool = False) -> str:
    """A datastore query URL. conditions are (property, operator, value)."""
    params = []
    for i, (prop, op, value) in enumerate(conditions):
        params += [(f"conditions[{i}][property]", prop),
                   (f"conditions[{i}][operator]", op),
                   (f"conditions[{i}][value]", value)]
    if sort:
        for i, prop in enumerate(_SORTS):
            params += [(f"sorts[{i}][property]", prop), (f"sorts[{i}][order]", "asc")]
    params += [("limit", str(limit)), ("offset", str(offset)),
               ("count", "true" if count else "false"), ("results", "true"),
               ("schema", "false")]
    return QUERY_URL.format(dataset_id=dataset_id) + "?" + urllib.parse.urlencode(params)


def _num(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class SdudReducer:
    """National rows folded into product code x quarter x utilisation type as pages
    arrive, so a year's 320,000 rows are never held at once."""

    def __init__(self, year: int, codes: set, owner_labelers: set):
        self.year = year
        self.codes = codes
        self.owners = owner_labelers
        self.records: dict = {}
        self.national_rows = 0
        self.kept_rows = 0
        self.matched_rows = 0
        self.unmatched_owner_rows = 0
        self.skipped = 0            # not national, another year, or an unreadable NDC
        self._gaps: dict = {}       # unmatched book-labeler code -> [name, prescriptions]

    def add(self, rows: list[dict]) -> None:
        for row in rows:
            code11 = ndc.to_ndc11(row.get("ndc"))
            try:
                year, quarter = int(row.get("year")), int(row.get("quarter"))
            except (TypeError, ValueError):
                year = quarter = None
            kind = (row.get("utilization_type") or "").strip().upper()
            if (code11 is None or (row.get("state") or NATIONAL) != NATIONAL
                    or year != self.year or quarter not in (1, 2, 3, 4)
                    or kind not in ("FFSU", "MCOU")):
                self.skipped += 1
                continue
            self.national_rows += 1
            code9, labeler = ndc.ndc9(code11), code11[:5]
            mapped = code9 in self.codes
            if not mapped and labeler not in self.owners:
                continue
            self.kept_rows += 1
            self.matched_rows += int(mapped)
            self.unmatched_owner_rows += int(not mapped)
            key = (code9, quarter, kind)
            record = self.records.get(key)
            if record is None:
                record = self.records[key] = {
                    "ndc9": code9, "labeler_code": labeler, "year": year,
                    "quarter": quarter, "utilization_type": kind, "packages": 0,
                    "packages_suppressed": 0, "product_name": None,
                    **{field: None for _, field in _SUMS}}
            record["packages"] += 1
            name = (row.get("product_name") or "").strip()
            if name and not record["product_name"]:
                record["product_name"] = name
            if str(row.get("suppression_used") or "").strip().lower() == "true":
                record["packages_suppressed"] += 1
                continue
            for column, field in _SUMS:
                value = _num(row.get(column))
                if value is not None:
                    record[field] = (record[field] or 0) + value
            if not mapped:
                gap = self._gaps.setdefault(code9, [name, 0])
                gap[1] += int(_num(row.get("number_of_prescriptions")) or 0)

    def result(self) -> list[dict]:
        out = []
        for record in self.records.values():
            if record["prescriptions"] is not None:
                record["prescriptions"] = int(round(record["prescriptions"]))
            for _, field in _SUMS[1:]:
                if record[field] is not None:
                    record[field] = round(record[field], 3)
            out.append(record)
        out.sort(key=lambda r: (r["ndc9"], r["quarter"], r["utilization_type"]))
        return out

    def gaps(self, limit: int = _GAP_EXAMPLES) -> list[tuple]:
        """The book labelers' unmapped codes with the most prescriptions: possible gaps
        in the code map, or simply products the book does not follow."""
        ranked = sorted(self._gaps.items(), key=lambda kv: -kv[1][1])
        return [(code, name, rx) for code, (name, rx) in ranked[:limit]]


# --- network --------------------------------------------------------------------------

def _http_json(url: str):
    last = None
    for attempt in range(_ATTEMPTS):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise
            last = exc
        except (socket.timeout, TimeoutError, ConnectionError, urllib.error.URLError) as exc:
            last = exc
        time.sleep(2.0 * (attempt + 1))
    raise last


# --- fetcher --------------------------------------------------------------------------

class MedicaidSdudFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, db_path=None, get_json=None, years_held: int = YEARS_HELD,
                 page: int = _PAGE):
        super().__init__(db_path)
        self._get_json = get_json or _http_json
        self.years_held = years_held
        self.page = page
        self._notes: list[str] = []
        self._errors: list[str] = []
        self._meta: dict = {}

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def _within_ttl(self) -> bool:
        return False            # the release guard holds under force; see module

    def _get(self, url: str):
        result = self._get_json(url)
        time.sleep(_SLEEP_S if self._get_json is _http_json else 0)
        return result

    # --- fetch ------------------------------------------------------------------------
    def fetch(self) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            ledger = {r["year"]: dict(r) for r in conn.execute(
                "SELECT * FROM medicaid_sdud_releases")}
            code_assets: dict = {}
            for r in conn.execute("SELECT code, asset_id, brand_specific FROM drug_codes"
                                  " WHERE code_type = 'ndc9'"):
                code_assets.setdefault(r["code"], []).append(
                    (r["asset_id"], r["brand_specific"]))
            owners = {r[0] for r in conn.execute(
                "SELECT DISTINCT labeler_code FROM drug_codes WHERE is_owner_labeler = 1"
                " AND labeler_code IS NOT NULL")}
        finally:
            conn.close()
        if not code_assets and not owners:
            # Nothing could be kept: a pull would read some 640,000 national rows to
            # store none, and would mark both years read, so a book whose codes arrive a
            # day later would wait for CMS's next revision to see its first row.
            self._notes.append("medicaid_sdud: drug_codes holds no product code yet, so "
                               "nothing was read; the codes fetcher runs first")
            self._meta = {"skipped": True}
            return {"pulled": {}}

        catalogue = parse_catalogue(self._get(METASTORE_URL))
        if not catalogue:
            raise RuntimeError("the Medicaid metastore lists no State Drug Utilization "
                               "Data dataset")
        held, probes = self._held_years(catalogue, ledger)
        due = [y for y in held if self._due(ledger.get(y), catalogue[y])]
        self._meta = {"held": held, "probes": probes, "catalogue": catalogue,
                      "code_assets": code_assets}
        if not due:
            self._notes.append(
                f"medicaid_sdud: no new State Drug Utilization Data release for "
                f"{', '.join(map(str, held)) or 'any full year'}, so nothing was read")
            self._meta["skipped"] = True
            return {"pulled": {}}

        pulled = {}
        for year in sorted(due, reverse=True):
            entry = catalogue[year]
            reducer = SdudReducer(year, set(code_assets), owners)
            try:
                read, expected = self._national(entry["dataset_id"], reducer)
            except Exception as exc:
                self._errors.append(f"medicaid_sdud: {year}: the national rows could not "
                                    f"be read ({exc}), so the stored year stands")
                continue
            if read != expected:
                self._errors.append(
                    f"medicaid_sdud: {year}: read {read} national rows where the "
                    f"datastore counts {expected}, so the stored year stands")
                continue
            pulled[year] = {"dataset_id": entry["dataset_id"],
                            "modified": entry["modified"], "records": reducer.result(),
                            "national_rows": reducer.national_rows,
                            "kept_rows": reducer.kept_rows,
                            "matched_rows": reducer.matched_rows,
                            "unmatched_owner_rows": reducer.unmatched_owner_rows,
                            "skipped": reducer.skipped, "gaps": reducer.gaps()}
        return {"pulled": pulled}

    @staticmethod
    def _due(seen: dict | None, entry: dict) -> bool:
        return (seen is None or seen.get("fetched_at") is None
                or seen.get("dataset_id") != entry["dataset_id"]
                or seen.get("modified") != entry["modified"])

    def _held_years(self, catalogue: dict, ledger: dict):
        """The newest full years, and the fullness answers asked for this run."""
        held, probes = [], {}
        for year in sorted(catalogue, reverse=True)[:_YEARS_EXAMINED]:
            entry, seen = catalogue[year], ledger.get(year) or {}
            if (seen.get("full_year") is not None
                    and seen.get("checked_dataset_id") == entry["dataset_id"]
                    and seen.get("checked_modified") == entry["modified"]):
                full = bool(seen["full_year"])
            else:
                page = self._get(query_url(
                    entry["dataset_id"],
                    [("state", "=", NATIONAL), ("quarter", "=", "4")], limit=1))
                full = bool((page or {}).get("results"))
                probes[year] = {"dataset_id": entry["dataset_id"],
                                "modified": entry["modified"], "full_year": int(full)}
            if full:
                held.append(year)
                if len(held) == self.years_held:
                    break
        return held, probes

    def _national(self, dataset_id: str, reducer: SdudReducer) -> tuple:
        read, offset, expected = 0, 0, None
        while True:
            page = self._get(query_url(dataset_id, [("state", "=", NATIONAL)],
                                       limit=self.page, offset=offset,
                                       count=expected is None, sort=True))
            if expected is None:
                expected = int(page.get("count") or 0)
            rows = page.get("results") or []
            reducer.add(rows)
            read += len(rows)
            if len(rows) < self.page:
                return read, expected
            offset += self.page

    # --- normalise --------------------------------------------------------------------
    def normalise(self, raw: dict) -> list[dict]:
        return [{"year": year, **pulled} for year, pulled in sorted(raw["pulled"].items())]

    # --- snapshot ---------------------------------------------------------------------
    def _asset_prescriptions(self, years: list[dict]) -> dict:
        """{asset_id: {year: brand prescriptions}} over the brand's own codes."""
        code_assets = self._meta.get("code_assets") or {}
        out: dict = {}
        for year in years:
            for record in year["records"]:
                for asset_id, brand_specific in code_assets.get(record["ndc9"], ()):
                    if brand_specific != 1 or record["prescriptions"] is None:
                        continue
                    by_year = out.setdefault(str(asset_id), {})
                    by_year[str(year["year"])] = (by_year.get(str(year["year"]), 0)
                                                  + record["prescriptions"])
        return out

    def snapshot(self, years: list[dict]) -> None:
        if self._meta.get("skipped") or not years:
            self._snapshot_cache()
            return
        self._write_snapshot({
            "held_years": self._meta.get("held"),
            "years": {str(y["year"]): {
                "dataset_id": y["dataset_id"], "modified": y["modified"],
                "national_rows": y["national_rows"], "kept_rows": y["kept_rows"],
                "matched_rows": y["matched_rows"],
                "unmatched_owner_rows": y["unmatched_owner_rows"]} for y in years},
            "asset_prescriptions": self._asset_prescriptions(years),
            "fetch_kind": "live",
        })

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            years = {str(r["year"]): {"dataset_id": r["dataset_id"],
                                      "modified": r["modified"],
                                      "national_rows": r["national_rows"],
                                      "matched_rows": r["matched_rows"]}
                     for r in conn.execute("SELECT * FROM medicaid_sdud_releases"
                                           " WHERE fetched_at IS NOT NULL")}
        finally:
            conn.close()
        self._write_snapshot({"held_years": self._meta.get("held"), "years": years,
                              "fetch_kind": "cache"})

    def _write_snapshot(self, payload: dict) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'feed', ?, ?, ?)",
                (self.source, ENTITY_KEY, json.dumps(payload), self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    # --- upsert -----------------------------------------------------------------------
    def upsert(self, years: list[dict]) -> RefreshResult:
        written = 0
        conn = db.get_connection(self.db_path)
        try:
            with conn:
                for year, probe in (self._meta.get("probes") or {}).items():
                    conn.execute(
                        """
                        INSERT INTO medicaid_sdud_releases
                            (year, full_year, checked_dataset_id, checked_modified,
                             checked_at)
                        VALUES (?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(year) DO UPDATE SET
                            full_year = excluded.full_year,
                            checked_dataset_id = excluded.checked_dataset_id,
                            checked_modified = excluded.checked_modified,
                            checked_at = excluded.checked_at
                        """, (year, probe["full_year"], probe["dataset_id"],
                              probe["modified"]))
            for year in years:
                with conn:      # a revised year is replaced whole, or not at all
                    conn.execute("DELETE FROM medicaid_utilization WHERE year = ?",
                                 (year["year"],))
                    conn.executemany(
                        """
                        INSERT INTO medicaid_utilization
                            (ndc9, labeler_code, year, quarter, utilization_type,
                             prescriptions, units_reimbursed, total_reimbursed,
                             medicaid_reimbursed, non_medicaid_reimbursed, packages,
                             packages_suppressed, product_name)
                        VALUES (:ndc9, :labeler_code, :year, :quarter, :utilization_type,
                                :prescriptions, :units_reimbursed, :total_reimbursed,
                                :medicaid_reimbursed, :non_medicaid_reimbursed, :packages,
                                :packages_suppressed, :product_name)
                        """, year["records"])
                    conn.execute(
                        """
                        INSERT INTO medicaid_sdud_releases
                            (year, dataset_id, modified, national_rows, kept_rows,
                             matched_rows, unmatched_owner_rows, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(year) DO UPDATE SET
                            dataset_id = excluded.dataset_id,
                            modified = excluded.modified,
                            national_rows = excluded.national_rows,
                            kept_rows = excluded.kept_rows,
                            matched_rows = excluded.matched_rows,
                            unmatched_owner_rows = excluded.unmatched_owner_rows,
                            fetched_at = excluded.fetched_at
                        """, (year["year"], year["dataset_id"], year["modified"],
                              year["national_rows"], year["kept_rows"],
                              year["matched_rows"], year["unmatched_owner_rows"]))
                written += len(year["records"])
                if year["gaps"]:
                    self._notes.append(
                        f"medicaid_sdud: {year['year']}: {year['unmatched_owner_rows']} "
                        f"rows of the book's own labelers sit on codes no asset carries, "
                        f"held for a corrected map; the largest: "
                        + "; ".join(f"{code} {name or 'unnamed'} ({rx:,} prescriptions)"
                                    for code, name, rx in year["gaps"]))
                if year["skipped"]:
                    self._notes.append(
                        f"medicaid_sdud: {year['year']}: {year['skipped']} rows were not "
                        f"national rows of the year or had no readable NDC, and were left "
                        f"out")
        finally:
            conn.close()
        return RefreshResult(self.source, written, errors=list(self._errors),
                             notes=list(self._notes))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Read the national Medicaid State Drug Utilization Data rows.")
    parser.parse_args(argv)
    fetcher = MedicaidSdudFetcher()
    fetcher.force = True
    result = fetcher.run()
    print(json.dumps({"rows_written": result.rows_fetched, "errors": result.errors,
                      "notes": result.notes, "elapsed_ms": result.elapsed_ms}, indent=1))


if __name__ == "__main__":
    main()
