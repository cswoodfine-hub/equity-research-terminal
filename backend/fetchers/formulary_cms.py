"""Medicare Part D plan coverage per brand, from CMS's monthly Prescription Drug Plan
Formulary and Pharmacy Network Information file.

Medicare Part D plans only, and not all of them: CMS's methodology leaves out non-Part D
plans, national PACE plans, employer-sponsored plans and demonstration plans (MMPs are
included). Coverage is counted in formularies and plans, never in people, since the file
carries no enrolment.

Each monthly release is one ZIP of about 2.3 GB, nearly all of it pharmacy networks. The
release is found in the CMS catalogue (cms_catalogue.downloads) and read with HTTP Range
requests: the ZIP's central directory, then five members of about 9 MB together, each
itself a ZIP holding one pipe-delimited Latin-1 text file. The basic drugs formulary,
plan information and beneficiary cost files are parsed; the excluded drugs file (the
excluded drugs enhanced plans cover as a supplemental benefit) and the indication based
coverage file (drugs on formulary for named FDA-approved indications only) are counted,
not stored. If the server will not serve a range, the fetch fails soft: the 2.3 GB file
is never downloaded whole.

A brand is matched on its brand-specific RxCUIs from drug_codes (SBD and BPCK), so a
co-marketed brand's coverage is stored against every owner. On each formulary the
brand's best-placed RxCUI sets its tier; a prior authorisation, step therapy or quantity
limit on any of its RxCUIs counts the formulary.

The daily refresh runs forced, so the guard reads partd_formulary_releases: a release
already read is never read again, and one a week-old catalogue has not yet listed is
picked up when the catalogue copy is renewed.
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import re
import urllib.request
import zipfile

import cms_catalogue
import db
import ndc
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "partd_formulary"
ENTITY_KEY = "partd_formulary"
TTL_SECONDS = 7 * 24 * 60 * 60
SERIES = "Monthly Prescription Drug Plan Formulary and Pharmacy Network Information"
# Inner members by their name with spaces collapsed (CMS puts two before the date).
BASIC, PLANS, COSTS = ("basic drugs formulary file", "plan information",
                       "beneficiary cost file")
EXCLUDED, INDICATION = ("excluded drugs formulary file",
                        "indication based coverage formulary file")
MEMBERS = (BASIC, PLANS, COSTS, EXCLUDED, INDICATION)
REQUIRED = (BASIC, PLANS)
_COLUMNS = {
    BASIC: ("FORMULARY_ID", "FORMULARY_VERSION", "CONTRACT_YEAR", "RXCUI", "NDC",
            "TIER_LEVEL_VALUE", "QUANTITY_LIMIT_YN", "QUANTITY_LIMIT_AMOUNT",
            "QUANTITY_LIMIT_DAYS", "PRIOR_AUTHORIZATION_YN", "STEP_THERAPY_YN",
            "SELECTED_DRUG_YN"),
    PLANS: ("CONTRACT_ID", "PLAN_ID", "SEGMENT_ID", "FORMULARY_ID", "STATE", "SNP",
            "PLAN_SUPPRESSED_YN"),
    COSTS: ("CONTRACT_ID", "PLAN_ID", "SEGMENT_ID", "TIER", "TIER_SPECIALTY_YN"),
    EXCLUDED: ("CONTRACT_ID", "PLAN_ID", "RXCUI"),
    INDICATION: ("CONTRACT_ID", "PLAN_ID", "RXCUI", "DISEASE"),
}
_ZIP_NAME = re.compile(r"/(\d{4})_(\d{8})\.zip$", re.IGNORECASE)
_MEMBER_DATE = re.compile(r"(\d{8})")
_TIMEOUT_S = 120
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_NOTE_EXAMPLES = 3


class RangeRefused(RuntimeError):
    """The server answered a Range request with something other than a range."""


# --- ranged reading -------------------------------------------------------------------

def _http_range(url: str, start: int, end: int) -> tuple:
    """(bytes start..end inclusive, the file's full size). A server that answers with
    the whole file instead of the range is refused before its body is read."""
    request = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
        if resp.status != 206 or not resp.headers.get("Content-Range"):
            raise RangeRefused(f"{url} answered a range request with HTTP {resp.status}"
                               f" and no Content-Range, so it was not read")
        total = int(resp.headers["Content-Range"].rsplit("/", 1)[1])
        return resp.read(), total


class RangeReader(io.RawIOBase):
    """A remote file zipfile can seek in, each read one Range request."""

    def __init__(self, url: str, get_range=None):
        self.url = url
        self._get_range = get_range or _http_range
        self.pos = 0
        self.requests = 0
        self.bytes_read = 0
        data, self.size = self._fetch(0, 0)

    def _fetch(self, start: int, end: int) -> tuple:
        data, total = self._get_range(self.url, start, end)
        self.requests += 1
        self.bytes_read += len(data)
        return data, total

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self.pos = offset
        elif whence == io.SEEK_CUR:
            self.pos += offset
        else:
            self.pos = self.size + offset
        return self.pos

    def readinto(self, buffer) -> int:
        wanted = len(buffer)
        if wanted == 0 or self.pos >= self.size:
            return 0
        end = min(self.size, self.pos + wanted) - 1
        data, _ = self._fetch(self.pos, end)
        buffer[:len(data)] = data
        self.pos += len(data)
        return len(data)


def member_key(name: str) -> str | None:
    """Which of the five members a ZIP entry is, by its name with spaces collapsed."""
    flat = " ".join(name.lower().split())
    for key in MEMBERS:
        if flat.startswith(key):
            return key
    return None


def _inner_text(data: bytes) -> str:
    """A member's text: each member is a ZIP of one text file."""
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as inner:
            names = [n for n in inner.namelist() if n.lower().endswith(".txt")]
            if len(names) != 1:
                raise ValueError(f"expected one text file in the member, found {names}")
            data = inner.read(names[0])
    return data.decode("latin-1")


def read_release(url: str, get_range=None) -> dict:
    """{members: {key: (name, text)}, requests, bytes_read} for one monthly ZIP."""
    raw = RangeReader(url, get_range)
    members = {}
    # Unbuffered on purpose: zipfile asks for exact byte counts (a local header, then a
    # member's compressed bytes), so each request reads only what is needed, and a
    # buffer would read on into the pharmacy network members.
    with zipfile.ZipFile(raw) as outer:
        found = {}
        for name in outer.namelist():
            key = member_key(name)
            if key and key not in found:
                found[key] = name
        missing = [k for k in REQUIRED if k not in found]
        if missing:
            raise ValueError(f"the release has no {', '.join(missing)} member")
        for key, name in found.items():
            members[key] = (name, _inner_text(outer.read(name)))
    return {"members": members, "requests": raw.requests, "bytes_read": raw.bytes_read}


# --- pure parsing ---------------------------------------------------------------------

def pipe_rows(text: str, key: str):
    """The rows of a pipe-delimited member as dicts, after checking the header carries
    every column this reader uses (a renamed column fails loudly, not as blanks)."""
    lines = text.splitlines()
    if not lines:
        raise ValueError(f"the {key} member is empty")
    header = [h.strip() for h in lines[0].split("|")]
    missing = [c for c in _COLUMNS[key] if c not in header]
    if missing:
        raise ValueError(f"the {key} member has no {', '.join(missing)} column")
    for line in lines[1:]:
        if line.strip():
            yield dict(zip(header, (v.strip() for v in line.split("|"))))


def plan_type(contract_id: str) -> str:
    """MA-PD for local (H) and regional (R) Medicare Advantage, PDP for stand-alone (S)."""
    head = (contract_id or "")[:1].upper()
    return {"H": "MA-PD", "R": "MA-PD", "S": "PDP"}.get(head, "Other")


def parse_plans(text: str) -> dict:
    """{(contract, plan, segment): plan} with the county rows collapsed."""
    plans: dict = {}
    for row in pipe_rows(text, PLANS):
        key = (row["CONTRACT_ID"], row["PLAN_ID"], row["SEGMENT_ID"])
        plan = plans.get(key)
        if plan is None:
            plan = plans[key] = {"contract_id": key[0], "plan_id": key[1],
                                 "segment_id": key[2], "formulary_id": row["FORMULARY_ID"],
                                 "plan_type": plan_type(key[0]), "snp": row["SNP"] or None,
                                 "states": set(), "counties": 0, "suppressed": 0}
        if row["STATE"]:
            plan["states"].add(row["STATE"])
        plan["counties"] += 1
        if row["PLAN_SUPPRESSED_YN"].upper() == "Y":
            plan["suppressed"] = 1
    return plans


def parse_specialty(text: str | None) -> set:
    """{(contract, plan, segment, tier)} the cost file marks a specialty tier."""
    if text is None:
        return set()
    return {(r["CONTRACT_ID"], r["PLAN_ID"], r["SEGMENT_ID"], r["TIER"])
            for r in pipe_rows(text, COSTS) if r["TIER_SPECIALTY_YN"].upper() == "Y"}


def parse_formulary(text: str, rxcuis: set) -> dict:
    """The basic formulary: every formulary's id, the contract years, and the rows on
    the book's RxCUIs."""
    formularies, years, kept, read = set(), set(), [], 0
    for row in pipe_rows(text, BASIC):
        read += 1
        formularies.add(row["FORMULARY_ID"])
        years.add(row["CONTRACT_YEAR"])
        if row["RXCUI"] not in rxcuis:
            continue
        try:
            tier = int(row["TIER_LEVEL_VALUE"])
        except ValueError:
            tier = None
        kept.append({
            "formulary_id": row["FORMULARY_ID"], "rxcui": row["RXCUI"],
            "formulary_version": row["FORMULARY_VERSION"] or None,
            "ndc11": row["NDC"] or None, "tier": tier,
            "quantity_limit": int(row["QUANTITY_LIMIT_YN"].upper() == "Y"),
            "ql_amount": row["QUANTITY_LIMIT_AMOUNT"] or None,
            "ql_days": row["QUANTITY_LIMIT_DAYS"] or None,
            "prior_auth": int(row["PRIOR_AUTHORIZATION_YN"].upper() == "Y"),
            "step_therapy": int(row["STEP_THERAPY_YN"].upper() == "Y"),
            "selected_drug": int(row["SELECTED_DRUG_YN"].upper() == "Y")})
    return {"formularies": formularies, "contract_years": sorted(years),
            "rows": kept, "rows_read": read}


def count_member(text: str | None, key: str, rxcuis: set) -> dict:
    """Rows, plans and book-RxCUI rows of a member that is counted, not stored."""
    if text is None:
        return {"rows": None, "plans": None, "book_rows": None}
    rows = list(pipe_rows(text, key))
    return {"rows": len(rows),
            "plans": len({(r["CONTRACT_ID"], r["PLAN_ID"]) for r in rows}),
            "book_rows": sum(1 for r in rows if r["RXCUI"] in rxcuis)}


def access_rows(entries: list[dict], asset_rxcuis: dict, asset_ndc9s: dict,
                formularies: set, plans: dict, specialty: set) -> dict:
    """{asset_id: access row} for every asset with a brand RxCUI, listed or not."""
    active = [p for p in plans.values() if not p["suppressed"]]
    by_formulary = collections.defaultdict(list)
    for plan in active:
        by_formulary[plan["formulary_id"]].append(plan)
    totals = collections.Counter(p["plan_type"] for p in active)
    by_rxcui = collections.defaultdict(list)
    for entry in entries:
        by_rxcui[entry["rxcui"]].append(entry)

    out = {}
    for asset_id, rxcuis in asset_rxcuis.items():
        listing: dict = {}
        listed, mismatched = set(), set()
        own_ndc9s = asset_ndc9s.get(asset_id) or set()
        for rxcui in sorted(rxcuis):
            for entry in by_rxcui.get(rxcui, ()):
                listed.add(rxcui)
                held = listing.setdefault(entry["formulary_id"], {
                    "tier": None, "pa": 0, "st": 0, "ql": 0, "selected": 0})
                if entry["tier"] is not None and (held["tier"] is None
                                                  or entry["tier"] < held["tier"]):
                    held["tier"] = entry["tier"]
                held["pa"] |= entry["prior_auth"]
                held["st"] |= entry["step_therapy"]
                held["ql"] |= entry["quantity_limit"]
                held["selected"] |= entry["selected_drug"]
                if own_ndc9s and ndc.ndc9(entry["ndc11"]) not in own_ndc9s:
                    mismatched.add((rxcui, entry["ndc11"]))
        plans_listing = [p for f in listing for p in by_formulary.get(f, ())]
        types = collections.Counter(p["plan_type"] for p in plans_listing)
        tiers = collections.Counter(h["tier"] for h in listing.values()
                                    if h["tier"] is not None)
        specialty_plans = sum(
            1 for p in plans_listing
            if (p["contract_id"], p["plan_id"], p["segment_id"],
                str(listing[p["formulary_id"]]["tier"])) in specialty)
        note = None
        if mismatched:
            examples = "; ".join(f"{code} for rxcui {rxcui}"
                                 for rxcui, code in sorted(mismatched)[:_NOTE_EXAMPLES])
            note = (f"{len(mismatched)} proxy NDCs on the formularies are not among this "
                    f"asset's product codes (for example {examples})")
        out[asset_id] = {
            "formularies_total": len(formularies),
            "formularies_listing": len(listing),
            "plans_total": len(active), "plans_listing": len(plans_listing),
            "mapd_plans_total": totals["MA-PD"], "mapd_plans_listing": types["MA-PD"],
            "pdp_plans_total": totals["PDP"], "pdp_plans_listing": types["PDP"],
            "tier_counts": {str(t): n for t, n in sorted(tiers.items())},
            "pa_formularies": sum(h["pa"] for h in listing.values()),
            "st_formularies": sum(h["st"] for h in listing.values()),
            "ql_formularies": sum(h["ql"] for h in listing.values()),
            "pa_plans": sum(listing[p["formulary_id"]]["pa"] for p in plans_listing),
            "st_plans": sum(listing[p["formulary_id"]]["st"] for p in plans_listing),
            "ql_plans": sum(listing[p["formulary_id"]]["ql"] for p in plans_listing),
            "specialty_plans_listing": specialty_plans,
            "selected_drug": int(any(h["selected"] for h in listing.values())),
            "rxcuis_known": len(rxcuis), "rxcuis_listed": len(listed),
            "ndc_mismatches": len(mismatched), "note": note,
        }
    return out


def release_date_of(url: str, fallback: str | None) -> tuple:
    """(posted date YYYY-MM-DD, contract year) from CMS's YYYY_YYYYMMDD.zip name."""
    match = _ZIP_NAME.search(url or "")
    if not match:
        return fallback, None
    day = match.group(2)
    return f"{day[:4]}-{day[4:6]}-{day[6:]}", int(match.group(1))


# --- fetcher --------------------------------------------------------------------------

class PartDFormularyFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, db_path=None, get_range=None, load_catalogue=None):
        super().__init__(db_path)
        self._get_range = get_range
        self._load_catalogue = load_catalogue or cms_catalogue.load
        self._notes: list[str] = []
        self._errors: list[str] = []
        self._meta: dict = {}

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def _within_ttl(self) -> bool:
        return False            # the release guard holds under force; see module

    # --- fetch ------------------------------------------------------------------------
    def fetch(self) -> dict:
        releases = cms_catalogue.downloads(self._load_catalogue(), SERIES)
        if not releases:
            raise RuntimeError("the CMS catalogue lists no monthly Part D formulary file")
        newest = releases[-1]
        release_date, contract_year = release_date_of(newest["url"], newest["title_date"])
        conn = db.get_connection(self.db_path)
        try:
            seen = conn.execute(
                "SELECT release_date FROM partd_formulary_releases"
                " WHERE release_date = ? OR zip_url = ?",
                (release_date, newest["url"])).fetchone()
            asset_rxcuis: dict = collections.defaultdict(set)
            for r in conn.execute("SELECT asset_id, code FROM drug_codes WHERE code_type"
                                  " = 'rxcui' AND brand_specific = 1"):
                asset_rxcuis[r["asset_id"]].add(r["code"])
            asset_ndc9s: dict = collections.defaultdict(set)
            for r in conn.execute("SELECT asset_id, code FROM drug_codes"
                                  " WHERE code_type = 'ndc9'"):
                asset_ndc9s[r["asset_id"]].add(r["code"])
        finally:
            conn.close()
        self._meta = {"release_date": release_date, "contract_year": contract_year,
                      "catalogue_date": newest["title_date"], "zip_url": newest["url"]}
        if seen is not None:
            self._notes.append(f"partd_formulary: the {release_date} release is already "
                               f"read, so nothing was fetched")
            self._meta["skipped"] = True
            return {}

        read = read_release(newest["url"], self._get_range)
        members = read["members"]
        text = {k: v[1] for k, v in members.items()}
        names = {k: v[0] for k, v in members.items()}
        rxcuis = set().union(*asset_rxcuis.values()) if asset_rxcuis else set()
        formulary = parse_formulary(text[BASIC], rxcuis)
        plans = parse_plans(text[PLANS])
        for key in (COSTS, EXCLUDED, INDICATION):
            if key not in text:
                self._notes.append(f"partd_formulary: the {release_date} release has no "
                                   f"{key} member, so its figures are null")
        if len(formulary["contract_years"]) == 1:
            contract_year = int(formulary["contract_years"][0])
        member_date = _MEMBER_DATE.search(names[BASIC])
        self._meta.update({
            "contract_year": contract_year,
            "member_date": member_date.group(1) if member_date else None,
            "requests": read["requests"], "bytes_read": read["bytes_read"]})
        return {"formulary": formulary, "plans": plans,
                "specialty": parse_specialty(text.get(COSTS)),
                "excluded": count_member(text.get(EXCLUDED), EXCLUDED, rxcuis),
                "indication": count_member(text.get(INDICATION), INDICATION, rxcuis),
                "asset_rxcuis": dict(asset_rxcuis), "asset_ndc9s": dict(asset_ndc9s)}

    # --- normalise --------------------------------------------------------------------
    def normalise(self, raw: dict) -> dict:
        if self._meta.get("skipped"):
            return {}
        formulary = raw["formulary"]
        access = access_rows(formulary["rows"], raw["asset_rxcuis"], raw["asset_ndc9s"],
                             formulary["formularies"], raw["plans"], raw["specialty"])
        plans = raw["plans"]
        return {"entries": formulary["rows"], "plans": list(plans.values()),
                "access": access,
                "release": {
                    "formularies": len(formulary["formularies"]),
                    "plans": sum(1 for p in plans.values() if not p["suppressed"]),
                    "plans_suppressed": sum(p["suppressed"] for p in plans.values()),
                    "rows_read": formulary["rows_read"],
                    "rows_kept": len(formulary["rows"]),
                    "assets_listed": sum(1 for a in access.values()
                                         if a["formularies_listing"]),
                    "excluded": raw["excluded"], "indication": raw["indication"]}}

    # --- snapshot ---------------------------------------------------------------------
    def snapshot(self, data: dict) -> None:
        if self._meta.get("skipped") or not data:
            self._snapshot_cache()
            return
        meta, release = self._meta, data["release"]
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'feed', ?, ?, ?)",
                (self.source, ENTITY_KEY, json.dumps({
                    "release_date": meta["release_date"],
                    "contract_year": meta["contract_year"],
                    "formularies": release["formularies"], "plans": release["plans"],
                    "assets_listed": release["assets_listed"],
                    "rows_kept": release["rows_kept"], "fetch_kind": "live"}),
                 self.refresh_run_id))
            conn.executemany(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'payer_access', ?, ?, ?)",
                [(self.source, str(asset_id), json.dumps({
                    "release_date": meta["release_date"],
                    "contract_year": meta["contract_year"],
                    **{k: v for k, v in row.items() if k != "note"},
                    "fetch_kind": "live"}), self.refresh_run_id)
                 for asset_id, row in sorted(data["access"].items())])
            conn.commit()
        finally:
            conn.close()

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT release_date, contract_year, formularies, plans, assets_listed,"
                " rows_kept FROM partd_formulary_releases ORDER BY release_date DESC"
                " LIMIT 1").fetchone()
            payload = dict(row) if row else {}
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'feed', ?, ?, ?)",
                (self.source, ENTITY_KEY, json.dumps({**payload, "fetch_kind": "cache"}),
                 self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    # --- upsert -----------------------------------------------------------------------
    def upsert(self, data: dict) -> RefreshResult:
        if self._meta.get("skipped") or not data:
            return RefreshResult(self.source, 0, notes=list(self._notes))
        meta, release = self._meta, data["release"]
        day = meta["release_date"]
        conn = db.get_connection(self.db_path)
        try:
            with conn:
                conn.execute("DELETE FROM partd_formulary_entries")
                conn.executemany(
                    """
                    INSERT INTO partd_formulary_entries
                        (formulary_id, rxcui, formulary_version, ndc11, tier,
                         quantity_limit, ql_amount, ql_days, prior_auth, step_therapy,
                         selected_drug, release_date)
                    VALUES (:formulary_id, :rxcui, :formulary_version, :ndc11, :tier,
                            :quantity_limit, :ql_amount, :ql_days, :prior_auth,
                            :step_therapy, :selected_drug, :release_date)
                    """, [{**e, "release_date": day} for e in data["entries"]])
                conn.execute("DELETE FROM partd_plans")
                conn.executemany(
                    """
                    INSERT INTO partd_plans
                        (contract_id, plan_id, segment_id, formulary_id, plan_type, snp,
                         states, counties, suppressed, release_date)
                    VALUES (:contract_id, :plan_id, :segment_id, :formulary_id,
                            :plan_type, :snp, :states, :counties, :suppressed,
                            :release_date)
                    """, [{**p, "states": ",".join(sorted(p["states"])) or None,
                           "release_date": day} for p in data["plans"]])
                for asset_id, row in data["access"].items():
                    conn.execute(
                        """
                        INSERT INTO partd_formulary_access
                            (asset_id, release_date, contract_year, formularies_total,
                             formularies_listing, plans_total, plans_listing,
                             mapd_plans_total, mapd_plans_listing, pdp_plans_total,
                             pdp_plans_listing, tier_counts, pa_formularies,
                             st_formularies, ql_formularies, pa_plans, st_plans, ql_plans,
                             specialty_plans_listing, selected_drug, rxcuis_known,
                             rxcuis_listed, ndc_mismatches, note)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?)
                        ON CONFLICT(asset_id, release_date) DO NOTHING
                        """,
                        (asset_id, day, meta["contract_year"], row["formularies_total"],
                         row["formularies_listing"], row["plans_total"],
                         row["plans_listing"], row["mapd_plans_total"],
                         row["mapd_plans_listing"], row["pdp_plans_total"],
                         row["pdp_plans_listing"], json.dumps(row["tier_counts"]),
                         row["pa_formularies"], row["st_formularies"],
                         row["ql_formularies"], row["pa_plans"], row["st_plans"],
                         row["ql_plans"], row["specialty_plans_listing"],
                         row["selected_drug"], row["rxcuis_known"],
                         row["rxcuis_listed"], row["ndc_mismatches"], row["note"]))
                excluded, indication = release["excluded"], release["indication"]
                conn.execute(
                    """
                    INSERT INTO partd_formulary_releases
                        (release_date, contract_year, catalogue_date, zip_url,
                         member_date, formularies, plans, plans_suppressed, rows_read,
                         rows_kept, assets_listed, excluded_rows, excluded_plans,
                         excluded_book_rows, indication_rows, indication_plans,
                         indication_book_rows, range_requests, bytes_read)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (day, meta["contract_year"], meta["catalogue_date"], meta["zip_url"],
                     meta.get("member_date"), release["formularies"], release["plans"],
                     release["plans_suppressed"], release["rows_read"],
                     release["rows_kept"], release["assets_listed"], excluded["rows"],
                     excluded["plans"], excluded["book_rows"], indication["rows"],
                     indication["plans"], indication["book_rows"], meta.get("requests"),
                     meta.get("bytes_read")))
        finally:
            conn.close()
        mismatched = sum(1 for a in data["access"].values() if a["ndc_mismatches"])
        if mismatched:
            self._notes.append(
                f"partd_formulary: {mismatched} assets have formulary rows whose proxy NDC "
                f"is not one of their product codes; see partd_formulary_access.note")
        return RefreshResult(self.source, len(data["access"]), errors=list(self._errors),
                             notes=list(self._notes))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Read the newest monthly CMS Part D formulary for the book's brands.")
    parser.parse_args(argv)
    fetcher = PartDFormularyFetcher()
    fetcher.force = True
    result = fetcher.run()
    print(json.dumps({"assets_written": result.rows_fetched, "errors": result.errors,
                      "notes": result.notes, "elapsed_ms": result.elapsed_ms}, indent=1))


if __name__ == "__main__":
    main()
