"""Medicare Part D prescribing per brand, from the two CMS Part D Prescribers datasets.

Medicare Part D only. Two datasets are read for each data year.

Prescribers by Geography and Drug gives one national row per brand: all prescribers,
claims, standardised 30-day fills, drug cost and distinct beneficiaries. It is one paged
request a year, and every year from 2020 is held (partd_prescribing.national_*).

Prescribers by Provider and Drug gives one row per prescriber, brand and ingredient. It is
read for the newest year only, per brand, with only the columns needed, and reduced in
memory to the brand's aggregates: how concentrated its claims are among prescribers, the
prescribers' specialties, days supplied per claim. No per-prescriber row, name or NPI is
stored. The file leaves out any prescriber with fewer than 11 claims for the drug, so
those aggregates describe the file population, which is said wherever they are shown.

A brand is matched to assets the way the Spending by Drug reader matches it (cms.py),
with two differences. A row CMS names by its own ingredient is a generic row and is
dropped: the question is brand prescribing. And a co-marketed brand belongs to every
owner's asset, so Eliquis is read once and stored against Bristol-Myers Squibb's asset
and Pfizer's.

The daily refresh runs forced, which skips every TTL, so the guards here read the data
tables. One /data/stats call on the provider series says whether CMS has published or
revised a year: the series id always serves the newest year, so its row count changes
when a year arrives. The 17.7 MB catalogue (data.json) is read from a week-old copy
unless that count changed. A geography year is read again only when the catalogue's
modified date for it changes, or after 30 days so a new asset is matched. The provider
pull covers only brands not yet complete for the newest year, largest first, and stops at
a time budget; the next run resumes. Each brand's rows are counted against /data/stats,
and a brand whose count does not reconcile is left incomplete rather than stored short.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import socket
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

import cms
import cms_catalogue
import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "partd_prescribers"
ENTITY_KEY = "partd_prescribers"
TTL_SECONDS = 30 * 24 * 60 * 60
RUN_BUDGET_S = 900
FIRST_YEAR = 2020
GEOGRAPHY_TITLE = "Medicare Part D Prescribers - by Geography and Drug"
PROVIDER_TITLE = "Medicare Part D Prescribers - by Provider and Drug"
API = "https://data.cms.gov/data-api/v1/dataset/{uuid}/data"
COVERAGE_GATE = 0.95                    # file share of claims the file-based proxy needs
SPECIALTY_FLOOR = 0.01                  # a specialty below 1% of claims goes to Other
_PAGE = 5000                            # the documented maximum; more returned 6,500
_SLEEP_S = 0.2
_TIMEOUT_S = 150
_ATTEMPTS = 3
_GIVE_UP_AFTER = 3                      # consecutive failed pulls: the source is down
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_GEOGRAPHY_COLUMNS = ("Brnd_Name,Gnrc_Name,Tot_Prscrbrs,Tot_Clms,Tot_30day_Fills,"
                      "Tot_Drug_Cst,Tot_Benes,GE65_Tot_Benes")
_PROVIDER_COLUMNS = ("Prscrbr_NPI,Prscrbr_Type,Tot_Clms,Tot_30day_Fills,Tot_Day_Suply,"
                     "Tot_Drug_Cst")
VOLUME_DECILE_NOTE = (
    "Not computed: CMS does not say whether its national prescriber count includes "
    "prescribers with fewer than 11 claims, so the prescribers missing from the file "
    "cannot be ranked")


# --- pure parsing and arithmetic ------------------------------------------------------

def _num(value) -> float | None:
    """A CMS number, or None where CMS left it blank (a suppressed count reads as null,
    never zero)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _int(value) -> int | None:
    n = _num(value)
    return int(round(n)) if n is not None else None


def parse_national(rows: list[dict]) -> list[dict]:
    """The national Geography and Drug rows, as numbers. The GE65 suppression flags ('*'
    and '#') are not read: a suppressed count is a blank, and a blank is null."""
    out = []
    for row in rows:
        brand = (row.get("Brnd_Name") or "").strip()
        if not brand:
            continue
        out.append({
            "brand": brand, "generic": (row.get("Gnrc_Name") or "").strip(),
            "prescribers": _int(row.get("Tot_Prscrbrs")),
            "claims": _int(row.get("Tot_Clms")),
            "fills_30d": _num(row.get("Tot_30day_Fills")),
            "drug_cost": _num(row.get("Tot_Drug_Cst")),
            "beneficiaries": _int(row.get("Tot_Benes")),
            "benes_ge65": _int(row.get("GE65_Tot_Benes")),
        })
    return out


def match_national(rows: list[dict], names: dict, own: dict) -> dict:
    """{asset_id: national figures} for the parsed national rows of one year.

    names is cms.brand_assets, own is cms.own_names. Generic rows are dropped; the
    containers of one brand and ingredient are summed; between ingredients the asset's
    own names win.
    """
    candidates: dict = {}
    for row in rows:
        if cms.is_generic_row(row["brand"], row["generic"]):
            continue
        assets, base = cms.match_brand(row["brand"], names)
        if not assets:
            continue
        for asset_id in assets:
            candidates.setdefault(asset_id, []).append(
                {**row, "base": base, "generic_norm": cms.norm(row["generic"])})
    return {asset_id: combine(found, *own.get(asset_id, ("", "")))
            for asset_id, found in candidates.items()}


def combine(candidates: list[dict], own_brand: str, own_generic: str) -> dict:
    """One asset's national figures for one year from the CMS rows matched to it."""
    groups: dict = {}
    for row in candidates:
        groups.setdefault((row["base"], row["generic_norm"]), []).append(row)

    def score(key):
        base, generic = key
        claims = sum(r["claims"] or 0 for r in groups[key])
        return (2 * int(bool(own_brand) and base == own_brand)
                + int(bool(own_generic) and generic == own_generic), claims)

    ranked = sorted(groups, key=score, reverse=True)
    chosen, dropped = groups[ranked[0]], [r for k in ranked[1:] for r in groups[k]]
    chosen = sorted(chosen, key=lambda r: r["brand"])

    def total(field, all_needed=False):
        values = [r[field] for r in chosen]
        present = [v for v in values if v is not None]
        if not present or (all_needed and len(present) < len(values)):
            return None
        return sum(present)

    benes = total("beneficiaries")
    fills = total("fills_30d")
    notes = []
    if len(chosen) > 1:
        notes.append(
            f"summed over the {len(chosen)} presentations CMS lists separately ("
            + ", ".join(r["brand"] for r in chosen)
            + "); prescribers and beneficiaries are sums of distinct counts, so a person "
              "under two of them is counted twice")
    suppressed = sum(1 for r in chosen if r["beneficiaries"] is None)
    if suppressed:
        notes.append(f"{suppressed} of {len(chosen)} beneficiary counts were suppressed "
                     f"by CMS and are not in the total")
    if dropped:
        notes.append("CMS lists other products against this asset too ("
                     + ", ".join(sorted(f"{r['brand']} / {r['generic']}" for r in dropped))
                     + "), which are not added in")
    return {
        "cms_brands": [[r["brand"], r["generic"]] for r in chosen],
        "presentations": len(chosen),
        "national_prescribers": total("prescribers"),
        "national_claims": total("claims"),
        "national_fills_30d": round(fills, 1) if fills is not None else None,
        "national_drug_cost": total("drug_cost"),
        "national_beneficiaries": benes,
        "national_benes_ge65": total("benes_ge65", all_needed=True),
        "national_note": "; ".join(notes) or None,
        "days_covered_share": days_covered(fills, benes),
    }


def days_covered(fills_30d: float | None, beneficiaries: int | None) -> float | None:
    """National 30-day fills x 30 over beneficiaries x 365: a proxy for the share of each
    beneficiary's year the drug was supplied for, not a proportion of days covered."""
    if not fills_30d or not beneficiaries:
        return None
    return round(fills_30d * 30 / (beneficiaries * 365), 4)


def concentration(claims: list[int]) -> dict:
    """How concentrated a brand's file claims are among its prescribers.

    Deciles are equal-count tenths of the prescribers, heaviest first, each as its share
    of the file's claims. Top 10% is the first decile; top 1% the heaviest hundredth.
    Too few prescribers for a measure leaves it null rather than a share of nobody.
    """
    empty = {"claims_share_by_npi_decile": None, "top1pct_claims_share": None,
             "top10pct_claims_share": None, "prescribers_for_50pct": None,
             "prescribers_for_80pct": None, "hhi": None,
             "median_claims_per_prescriber": None}
    ordered = sorted((c for c in claims if c and c > 0), reverse=True)
    n, total = len(ordered), sum(ordered)
    if not n or total <= 0:
        return empty
    deciles = None
    if n >= 10:
        deciles = [round(sum(ordered[n * k // 10: n * (k + 1) // 10]) / total, 6)
                   for k in range(10)]
    reach, running, cut50, cut80 = 0, 0, None, None
    for count in ordered:
        running += count
        reach += 1
        if cut50 is None and running >= 0.5 * total:
            cut50 = reach
        if cut80 is None and running >= 0.8 * total:
            cut80 = reach
            break
    return {
        "claims_share_by_npi_decile": deciles,
        "top1pct_claims_share": (round(sum(ordered[:n // 100]) / total, 6)
                                 if n >= 100 else None),
        "top10pct_claims_share": deciles[0] if deciles else None,
        "prescribers_for_50pct": cut50,
        "prescribers_for_80pct": cut80,
        "hhi": round(sum((c / total * 100) ** 2 for c in ordered), 2),
        "median_claims_per_prescriber": float(statistics.median(ordered)),
    }


class ProviderAccumulator:
    """One brand's provider rows reduced while they stream in: per NPI only claims and
    specialty, summed across the brand's presentations so the NPI union is exact."""

    def __init__(self):
        self.by_npi: dict = {}
        self.fills = 0.0
        self.day_supply = 0
        self.cost = 0.0
        self.rows = 0
        self.unreadable = 0

    def add(self, rows: list[dict]) -> set:
        """Fold a page in; returns the NPIs it carried, for the per-string count."""
        seen = set()
        for row in rows:
            npi = (row.get("Prscrbr_NPI") or "").strip()
            claims = _int(row.get("Tot_Clms"))
            if not npi or claims is None:
                self.unreadable += 1
                continue
            self.rows += 1
            seen.add(npi)
            held = self.by_npi.get(npi)
            specialty = (row.get("Prscrbr_Type") or "").strip() or "Not stated"
            if held is None:
                self.by_npi[npi] = [claims, specialty]
            else:
                held[0] += claims
            fills, days, cost = (_num(row.get("Tot_30day_Fills")),
                                 _int(row.get("Tot_Day_Suply")),
                                 _num(row.get("Tot_Drug_Cst")))
            if fills is None or days is None or cost is None:
                self.unreadable += 1
            self.fills += fills or 0.0
            self.day_supply += days or 0
            self.cost += cost or 0.0
        return seen

    def reduce(self) -> dict:
        """The brand's file aggregates and specialty mix. The NPIs end here."""
        claims = [held[0] for held in self.by_npi.values()]
        total = sum(claims)
        mix: dict = {}
        for count, specialty in self.by_npi.values():
            entry = mix.setdefault(specialty, [0, 0])
            entry[0] += 1
            entry[1] += count
        specialties, other = [], [0, 0]
        for specialty, (prescribers, count) in sorted(
                mix.items(), key=lambda kv: kv[1][1], reverse=True):
            if total and count / total >= SPECIALTY_FLOOR and specialty != "Other":
                specialties.append({"specialty": specialty, "prescribers": prescribers,
                                    "claims": count,
                                    "claims_share": round(count / total, 6)})
            else:
                other[0] += prescribers
                other[1] += count
        if other[1]:
            specialties.append({"specialty": "Other", "prescribers": other[0],
                                "claims": other[1],
                                "claims_share": round(other[1] / total, 6)})
        return {"file_prescribers": len(self.by_npi), "file_claims": total,
                "file_fills_30d": round(self.fills, 1),
                "file_day_supply": self.day_supply,
                "file_drug_cost": round(self.cost, 2),
                **concentration(claims), "specialties": specialties,
                "unreadable_rows": self.unreadable}


def file_measures(national: dict, file: dict) -> dict:
    """The measures that need both files: coverage of national claims, days per claim and
    the file-based days-covered proxy, which waits for 95% coverage."""
    out = {"file_claims_share": None, "days_supply_per_claim": None,
           "days_covered_share_file": None}
    notes = []
    claims_n = national.get("national_claims")
    if claims_n and file["file_claims"] is not None:
        out["file_claims_share"] = round(file["file_claims"] / claims_n, 6)
    if file["file_claims"]:
        out["days_supply_per_claim"] = round(file["file_day_supply"] / file["file_claims"], 2)
    share, benes = out["file_claims_share"], national.get("national_beneficiaries")
    if share is not None and share >= COVERAGE_GATE and benes:
        out["days_covered_share_file"] = round(
            file["file_day_supply"] / (benes * 365), 4)
    elif share is not None:
        notes.append(f"file-based days covered held back: the file carries "
                     f"{share:.1%} of national claims, under the 95% it needs")
    if file.get("unreadable_rows"):
        notes.append(f"{file['unreadable_rows']} provider rows had a blank figure")
    out["file_note"] = "; ".join(notes) or None
    return out


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

class PartDPrescribersFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, db_path=None, budget_s: float = RUN_BUDGET_S, get_json=None,
                 load_catalogue=None):
        super().__init__(db_path)
        self.budget_s = budget_s
        self._get_json = get_json or _http_json
        self._load_catalogue = load_catalogue or cms_catalogue.load
        self._notes: list[str] = []
        self._errors: list[str] = []
        self._meta: dict = {}

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def _within_ttl(self) -> bool:
        return False            # the release guards below hold under force; see module

    def _call(self, uuid: str, params: dict, stats: bool = False):
        url = API.format(uuid=uuid) + ("/stats" if stats else "")
        result = self._get_json(f"{url}?{urllib.parse.urlencode(params)}")
        time.sleep(_SLEEP_S if self._get_json is _http_json else 0)
        return result

    # --- fetch ------------------------------------------------------------------------
    def fetch(self) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            ledger = {(r["dataset"], r["data_year"]): dict(r) for r in conn.execute(
                "SELECT * FROM partd_prescriber_releases")}
            names, own = cms.brand_assets(conn), cms.own_names(conn)
            marketed = {r[0] for r in conn.execute(
                "SELECT id FROM assets WHERE is_marketed = 1")}
            stored = {}
            for row in conn.execute(
                    "SELECT asset_id, data_year, file_status, cms_brands,"
                    " national_prescribers FROM partd_prescribing"):
                stored[(row["asset_id"], row["data_year"])] = dict(row)
        finally:
            conn.close()

        catalogue = self._load_catalogue()
        year, provider, geography = self._newest(catalogue)
        total = self._call(provider["latest_uuid"] or provider["uuid"], {},
                           stats=True)["total_rows"]
        held = ledger.get(("provider", year))
        if held is not None and held["total_rows"] != total:
            # The series changed under a catalogue up to a week old: read it fresh.
            catalogue = self._load_catalogue(refresh=True)
            year, provider, geography = self._newest(catalogue)
            total = self._call(provider["latest_uuid"] or provider["uuid"], {},
                               stats=True)["total_rows"]
            held = ledger.get(("provider", year))
        reset = (held is None or held["total_rows"] != total
                 or held["uuid"] != provider["uuid"])

        cutoff = (dt.datetime.now(dt.timezone.utc)
                  - dt.timedelta(seconds=self.ttl_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        national: dict = {}
        geography_meta: dict = {}
        for y in range(FIRST_YEAR, year + 1):
            entry = geography.get(y)
            if entry is None:
                continue
            seen = ledger.get(("geography", y))
            due = (seen is None or seen["catalogue_modified"] != entry["modified"]
                   or (seen["fetched_at"] or "") < cutoff or (y == year and reset))
            if not due:
                continue
            rows = self._national_rows(entry["uuid"])
            national[y] = {asset_id: figures for asset_id, figures in match_national(
                parse_national(rows), names, own).items() if asset_id in marketed}
            geography_meta[y] = {"uuid": entry["uuid"], "rows_read": len(rows),
                                 "catalogue_modified": entry["modified"]}

        # Which brands still need the provider pull for the newest year.
        if year in national:
            matched = {a: dict(v) for a, v in national[year].items()}
        else:
            matched = {}
            for (asset_id, y), row in stored.items():
                if y == year and row["cms_brands"]:
                    matched[asset_id] = {"national_prescribers": row["national_prescribers"],
                                         "cms_brands": json.loads(row["cms_brands"])}
        statuses = {a: stored.get((a, year), {}).get("file_status") for a in matched}
        pending = [a for a in matched if reset or statuses[a] != "complete"]

        if not national and not pending:
            self._notes.append(
                f"partd_prescribers: no new Part D Prescribers release, and every one of "
                f"the {len(matched)} brands matched for {year} is complete")
            self._meta = {"year": year, "skipped": True}
            return {"year": year, "national": {}, "provider": {}, "geography_meta": {},
                    "reset": False}

        provider_results, rows_read, left = self._pull_providers(
            year, provider, matched, pending)
        self._meta = {"year": year, "reset": reset, "total_rows": total,
                      "provider": provider, "rows_read": rows_read, "left": left,
                      "matched": len(matched), "statuses": statuses,
                      "geography_meta": geography_meta}
        return {"year": year, "national": national, "provider": provider_results,
                "geography_meta": geography_meta, "reset": reset}

    def _newest(self, catalogue: dict):
        provider = {r["year"]: r for r in cms_catalogue.years(catalogue, PROVIDER_TITLE)}
        geography = {r["year"]: r for r in cms_catalogue.years(catalogue, GEOGRAPHY_TITLE)}
        both = set(provider) & set(geography)
        if not both:
            raise RuntimeError("the CMS catalogue lists no Part D Prescribers year with "
                               "both the provider and the geography file")
        year = max(both)
        return year, provider[year], geography

    def _national_rows(self, uuid: str) -> list[dict]:
        rows, offset = [], 0
        while True:
            page = self._call(uuid, {"filter[Prscrbr_Geo_Lvl]": "National",
                                     "column": _GEOGRAPHY_COLUMNS, "size": _PAGE,
                                     "offset": offset})
            rows.extend(page)
            if len(page) < _PAGE:
                return rows
            offset += _PAGE

    def _pull_providers(self, year, provider, matched, pending):
        """Pull and reduce each pending brand, largest first, until the budget runs out.
        Co-marketed assets that share their CMS names share one pull."""
        order = sorted(pending, key=lambda a: -(matched[a].get("national_prescribers") or 0))
        results: dict = {}
        done_pairs: dict = {}
        started, rows_read, failed_in_a_row = time.monotonic(), 0, 0
        for index, asset_id in enumerate(order):
            pairs = tuple(tuple(p) for p in matched[asset_id].get("cms_brands") or ())
            if pairs in done_pairs:
                results[asset_id] = done_pairs[pairs]
                continue
            # At least one brand per run, so a budget smaller than the largest pull
            # still makes progress.
            if done_pairs and time.monotonic() - started > self.budget_s:
                left = len(order) - index
                self._notes.append(
                    f"partd_prescribers: stopped at the {int(self.budget_s)}s run budget "
                    f"with {left} of {len(order)} {year} brands left for the next run")
                return results, rows_read, left
            outcome, read = self._pull_one(provider["uuid"], pairs)
            rows_read += read
            done_pairs[pairs] = outcome
            results[asset_id] = outcome
            if outcome["status"] == "incomplete":
                self._errors.append(f"partd_prescribers: {', '.join(p[0] for p in pairs)}"
                                    f" {year}: {outcome['note']}")
            failed_in_a_row = failed_in_a_row + 1 if outcome.get("failed") else 0
            if failed_in_a_row >= _GIVE_UP_AFTER:
                left = len(order) - index - 1
                self._errors.append(
                    f"partd_prescribers: {_GIVE_UP_AFTER} brand pulls failed in a row, so "
                    f"the run stopped with {left} {year} brands left")
                return results, rows_read, left
        return results, rows_read, 0

    def _pull_one(self, uuid: str, pairs) -> tuple:
        acc = ProviderAccumulator()
        read = 0
        for brand, generic in pairs:
            filters = {"filter[Brnd_Name]": brand}
            if generic:
                filters["filter[Gnrc_Name]"] = generic
            try:
                expected = self._call(uuid, filters, stats=True)["found_rows"]
                seen, offset = set(), 0
                count = 0
                while True:
                    page = self._call(uuid, {**filters, "column": _PROVIDER_COLUMNS,
                                             "size": _PAGE, "offset": offset})
                    seen |= acc.add(page)
                    count += len(page)
                    if len(page) < _PAGE:
                        break
                    offset += _PAGE
            except Exception as exc:
                return {"status": "incomplete", "failed": True,
                        "note": f"the pull for {brand} failed: {exc}"}, read
            read += count
            if count != expected or len(seen) != expected:
                return {"status": "incomplete",
                        "note": f"{brand}: read {count} rows over {len(seen)} prescribers "
                                f"where CMS counts {expected}, so the pull was not stored"
                        }, read
        return {"status": "complete", **acc.reduce()}, read

    # --- normalise --------------------------------------------------------------------
    def normalise(self, raw: dict) -> list[dict]:
        """One record per asset and year: national figures where read, file figures
        where the provider pull finished."""
        records: dict = {}
        year = raw["year"]
        for y, by_asset in raw["national"].items():
            for asset_id, figures in by_asset.items():
                records[(asset_id, y)] = {"asset_id": asset_id, "data_year": y,
                                          "national": figures, "file": None}
        stored_national = self._stored_national(
            [a for a in raw["provider"] if (a, year) not in records], year)
        for asset_id, outcome in raw["provider"].items():
            record = records.setdefault((asset_id, year), {
                "asset_id": asset_id, "data_year": year, "national": None, "file": None})
            nat = record["national"] or stored_national.get(asset_id) or {}
            if outcome["status"] == "complete":
                record["file"] = {**{k: v for k, v in outcome.items()
                                     if k not in ("specialties", "unreadable_rows")},
                                  **file_measures(nat, outcome),
                                  "specialties": outcome["specialties"]}
            else:
                record["file"] = {"status": "incomplete", "file_note": outcome["note"]}
        return list(records.values())

    def _stored_national(self, asset_ids, year) -> dict:
        if not asset_ids:
            return {}
        conn = db.get_connection(self.db_path)
        try:
            marks = ",".join("?" * len(asset_ids))
            return {r["asset_id"]: dict(r) for r in conn.execute(
                f"SELECT asset_id, national_claims, national_beneficiaries"
                f" FROM partd_prescribing WHERE data_year = ? AND asset_id IN ({marks})",
                (year, *asset_ids))}
        finally:
            conn.close()

    # --- snapshot ---------------------------------------------------------------------
    def snapshot(self, records: list[dict]) -> None:
        meta = self._meta
        if meta.get("skipped") or not records:
            self._snapshot_cache()
            return
        year = meta["year"]
        statuses = dict(meta.get("statuses") or {})
        if meta.get("reset"):
            statuses = {a: "pending" for a in statuses}
        for record in records:
            if record["data_year"] == year and record["file"] is not None:
                statuses[record["asset_id"]] = record["file"].get("status", "complete")
        self._write_snapshot({
            "data_year": year,
            "brands_matched": meta.get("matched", 0),
            "assets_complete": sum(1 for s in statuses.values() if s == "complete"),
            "assets_pending": sum(1 for s in statuses.values() if s != "complete"),
            "provider_rows_read": meta.get("rows_read", 0),
            "geography_years_read": sorted({r["data_year"] for r in records
                                            if r["national"] is not None}),
            "fetch_kind": "live",
        })

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT MAX(data_year) FROM partd_prescribing").fetchone()
            year = row[0] if row else None
            counts = conn.execute(
                "SELECT COUNT(*), SUM(file_status = 'complete') FROM partd_prescribing"
                " WHERE data_year = ?", (year,)).fetchone()
        finally:
            conn.close()
        self._write_snapshot({"data_year": year, "brands_matched": counts[0] or 0,
                              "assets_complete": counts[1] or 0,
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
    def upsert(self, records: list[dict]) -> RefreshResult:
        meta = self._meta
        if meta.get("skipped"):
            return RefreshResult(self.source, 0, notes=list(self._notes))
        year, reset = meta["year"], meta.get("reset")
        written = 0
        conn = db.get_connection(self.db_path)
        try:
            for record in records:
                with conn:
                    if record["national"] is not None:
                        self._write_national(conn, record, year, reset)
                        written += 1
                    if record["file"] is not None:
                        self._write_file(conn, record)
            with conn:
                for y, entry in (meta.get("geography_meta") or {}).items():
                    conn.execute(
                        """
                        INSERT INTO partd_prescriber_releases
                            (dataset, data_year, uuid, catalogue_modified, rows_read,
                             fetched_at)
                        VALUES ('geography', ?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(dataset, data_year) DO UPDATE SET
                            uuid = excluded.uuid,
                            catalogue_modified = excluded.catalogue_modified,
                            rows_read = excluded.rows_read, fetched_at = datetime('now')
                        """, (y, entry["uuid"], entry["catalogue_modified"],
                              entry["rows_read"]))
                provider = meta["provider"]
                conn.execute(
                    """
                    INSERT INTO partd_prescriber_releases
                        (dataset, data_year, uuid, series_uuid, total_rows,
                         catalogue_modified, rows_read, fetched_at)
                    VALUES ('provider', ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(dataset, data_year) DO UPDATE SET
                        uuid = excluded.uuid, series_uuid = excluded.series_uuid,
                        total_rows = excluded.total_rows,
                        catalogue_modified = excluded.catalogue_modified,
                        rows_read = CASE WHEN ? THEN excluded.rows_read
                                         ELSE COALESCE(partd_prescriber_releases.rows_read, 0)
                                              + excluded.rows_read END,
                        fetched_at = datetime('now')
                    """, (year, provider["uuid"], provider["latest_uuid"],
                          meta["total_rows"], provider["modified"], meta["rows_read"],
                          int(bool(reset))))
        finally:
            conn.close()
        return RefreshResult(self.source, written, errors=list(self._errors),
                             notes=list(self._notes))

    def _write_national(self, conn, record, year, reset) -> None:
        n = record["national"]
        newest = record["data_year"] == year
        conn.execute(
            """
            INSERT INTO partd_prescribing
                (asset_id, data_year, cms_brands, presentations, national_prescribers,
                 national_claims, national_fills_30d, national_drug_cost,
                 national_beneficiaries, national_benes_ge65, national_note,
                 days_covered_share, file_status, prescribers_by_volume_decile,
                 volume_decile_note, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, datetime('now'))
            ON CONFLICT(asset_id, data_year) DO UPDATE SET
                cms_brands = excluded.cms_brands,
                presentations = excluded.presentations,
                national_prescribers = excluded.national_prescribers,
                national_claims = excluded.national_claims,
                national_fills_30d = excluded.national_fills_30d,
                national_drug_cost = excluded.national_drug_cost,
                national_beneficiaries = excluded.national_beneficiaries,
                national_benes_ge65 = excluded.national_benes_ge65,
                national_note = excluded.national_note,
                days_covered_share = excluded.days_covered_share,
                file_status = CASE
                    WHEN ? THEN 'pending'
                    WHEN ? AND partd_prescribing.file_status IS NULL THEN 'pending'
                    ELSE partd_prescribing.file_status END,
                fetched_at = datetime('now')
            """,
            (record["asset_id"], record["data_year"], json.dumps(n["cms_brands"]),
             n["presentations"], n["national_prescribers"], n["national_claims"],
             n["national_fills_30d"], n["national_drug_cost"],
             n["national_beneficiaries"], n["national_benes_ge65"], n["national_note"],
             n["days_covered_share"], "pending" if newest else None, VOLUME_DECILE_NOTE,
             int(bool(newest and reset)), int(newest)))

    def _write_file(self, conn, record) -> None:
        f = record["file"]
        asset_id, year = record["asset_id"], record["data_year"]
        if f.get("status") == "incomplete":
            conn.execute(
                "UPDATE partd_prescribing SET file_status = 'incomplete', file_note = ?,"
                " file_fetched_at = datetime('now') WHERE asset_id = ? AND data_year = ?",
                (f["file_note"], asset_id, year))
            return
        conn.execute(
            """
            UPDATE partd_prescribing SET
                file_status = 'complete', file_prescribers = ?, file_claims = ?,
                file_fills_30d = ?, file_day_supply = ?, file_drug_cost = ?,
                file_claims_share = ?, top1pct_claims_share = ?,
                top10pct_claims_share = ?, prescribers_for_50pct = ?,
                prescribers_for_80pct = ?, hhi = ?, claims_share_by_npi_decile = ?,
                median_claims_per_prescriber = ?, prescribers_by_volume_decile = NULL,
                volume_decile_note = ?, days_supply_per_claim = ?,
                days_covered_share_file = ?, file_note = ?,
                file_fetched_at = datetime('now')
            WHERE asset_id = ? AND data_year = ?
            """,
            (f["file_prescribers"], f["file_claims"], f["file_fills_30d"],
             f["file_day_supply"], f["file_drug_cost"], f["file_claims_share"],
             f["top1pct_claims_share"], f["top10pct_claims_share"],
             f["prescribers_for_50pct"], f["prescribers_for_80pct"], f["hhi"],
             json.dumps(f["claims_share_by_npi_decile"])
             if f["claims_share_by_npi_decile"] is not None else None,
             f["median_claims_per_prescriber"], VOLUME_DECILE_NOTE,
             f["days_supply_per_claim"], f["days_covered_share_file"], f["file_note"],
             asset_id, year))
        conn.execute("DELETE FROM partd_prescriber_specialties WHERE asset_id = ?"
                     " AND data_year = ?", (asset_id, year))
        for s in f["specialties"]:
            conn.execute(
                "INSERT INTO partd_prescriber_specialties (asset_id, data_year, specialty,"
                " prescribers, claims, claims_share) VALUES (?, ?, ?, ?, ?, ?)",
                (asset_id, year, s["specialty"], s["prescribers"], s["claims"],
                 s["claims_share"]))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Read the CMS Part D Prescribers files for the book's brands.")
    parser.add_argument("--budget", type=float, default=RUN_BUDGET_S,
                        help="seconds of provider pulls before the run stops")
    args = parser.parse_args(argv)
    fetcher = PartDPrescribersFetcher(budget_s=args.budget)
    fetcher.force = True
    result = fetcher.run()
    print(json.dumps({"rows_written": result.rows_fetched, "errors": result.errors,
                      "notes": result.notes, "elapsed_ms": result.elapsed_ms}, indent=1))


if __name__ == "__main__":
    main()
