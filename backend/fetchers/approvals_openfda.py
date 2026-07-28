"""FDA approvals from openFDA drugsfda.

Queries drugsfda by both the sponsor name and the openFDA manufacturer name, and unions
the two. Neither field alone is enough. The manufacturer name is the legal entity that
holds the application, which for an acquired product is the company that was bought:
Bristol Myers Squibb holds Opdivo as E.R. Squibb & Sons, Revlimid as Celgene, Camzyos as
Myokardia, so a manufacturer query for Bristol found nothing. The sponsor name catches
those but misses the drugs an acquirer never re-registered, so both run and the results
are merged on application number.

Covers NDAs and BLAs, so approvals link to the same marketed assets the Orange and
Purple Book create, by application number.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import db
import acquired_sponsors
import company_names
from assets_util import normalize_appl, upsert_asset
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "approvals"
OPENFDA_SOURCE = "openfda"
TTL_SECONDS = 24 * 60 * 60

DRUGSFDA_URL = "https://api.fda.gov/drug/drugsfda.json"
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 30
_LIMIT = 100

# ticker -> openFDA manufacturer-name phrases (matched as phrases against the
# tokenized field). Distinctive short phrases match more product records.
MANUFACTURER_MAP = {
    "LLY": ["Eli Lilly and Company"],
    "NVO": ["Novo Nordisk"],
    "MRK": ["Merck Sharp & Dohme"],
    "PFE": ["Pfizer"],
    "ABBV": ["AbbVie"],
    "JNJ": ["Janssen"],
    "AZN": ["AstraZeneca"],
    "GSK": ["GlaxoSmithKline"],
    "NVS": ["Novartis"],
    "ROG": ["Genentech", "Hoffmann-La Roche"],
    "SNY": ["sanofi-aventis", "Genzyme"],
    "BMY": ["Bristol-Myers Squibb"],
    "AMGN": ["Amgen"],
    "GILD": ["Gilead Sciences"],
    "VRTX": ["Vertex Pharmaceuticals"],
    "REGN": ["Regeneron Pharmaceuticals"],
    "BIIB": ["Biogen"],
    "BAYN": ["Bayer"],
}

# ticker -> sponsor_name terms. A term search, not a phrase: a quoted phrase 404s here,
# and the terms match only the exact sponsor anyway (a Merck query returns none of
# Merck KGaA). The sponsor is the parent, so this is where an acquired product surfaces.
SPONSOR_MAP = {
    "LLY": "ELI LILLY", "NVO": "NOVO NORDISK", "MRK": "MERCK SHARP DOHME",
    "PFE": "PFIZER", "ABBV": "ABBVIE", "JNJ": "JANSSEN", "AZN": "ASTRAZENECA",
    "GSK": "GLAXOSMITHKLINE", "NVS": "NOVARTIS", "ROG": "GENENTECH", "SNY": "SANOFI",
    "BMY": "BRISTOL MYERS SQUIBB", "AMGN": "AMGEN", "GILD": "GILEAD",
    "VRTX": "VERTEX", "REGN": "REGENERON", "BIIB": "BIOGEN", "BAYN": "BAYER",
}


def _approval_date(submissions) -> str | None:
    """Earliest original approval date (YYYYMMDD -> ISO) from the submissions list."""
    dates = [
        s.get("submission_status_date")
        for s in submissions or []
        if s.get("submission_type") == "ORIG" and s.get("submission_status") == "AP"
        and s.get("submission_status_date")
    ]
    if not dates:
        return None
    raw = min(dates)
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}" if len(raw) == 8 else None


def _modality(application_number: str) -> str:
    return "biologic" if application_number.upper().startswith("BLA") else "small molecule"


def _iso(raw) -> str | None:
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}" if raw and len(raw) == 8 else None


def parse_drugsfda(payload: dict, ticker: str) -> list[dict]:
    """Turn a drugsfda payload into approval rows. Pure."""
    rows = []
    for result in payload.get("results", []):
        appl = (result.get("application_number") or "").upper()
        match = re.match(r"([A-Za-z]+)(\d+)", appl)
        if not match:
            continue
        internal_code = normalize_appl(match.group(1), match.group(2))
        approval_date = _approval_date(result.get("submissions"))
        if approval_date is None:
            continue
        products = result.get("products") or [{}]
        brand = products[0].get("brand_name")
        generic = _generic(result, products[0])
        rows.append(
            {
                "ticker": ticker,
                "internal_code": internal_code,
                "application_number": appl,
                "brand": brand.title() if brand else None,
                "generic": generic,
                "modality": _modality(appl),
                "approval_date": approval_date,
                "marketing_status": products[0].get("marketing_status"),
            }
        )
    return rows


def _generic(result: dict, product: dict) -> str | None:
    """The active ingredient behind a brand, from the product entry or the openFDA
    block, or None when the payload states neither.

    Without it a marketed product is only its brand, and the registry names drugs by
    ingredient: Jaypirca and pirtobrutinib were two rows for one drug, which put an
    approved product in the pipeline as an unapproved compound. Title case, since the
    payload shouts and the rest of the app does not.
    """
    ingredients = product.get("active_ingredients") or []
    if ingredients and ingredients[0].get("name"):
        return str(ingredients[0]["name"]).title()
    openfda = (result.get("openfda") or {}).get("generic_name") or []
    return str(openfda[0]).title() if openfda else None


def parse_supplements(payload: dict, ticker: str) -> list[dict]:
    """Approved efficacy supplements from the same payload. Pure.

    An entry in submissions[] with class EFFICACY and status AP is a label expansion
    that already happened; the application number and the approval date come straight
    off it, so no second call is needed.
    """
    rows = []
    for result in payload.get("results", []):
        appl = (result.get("application_number") or "").upper()
        if not re.match(r"[A-Za-z]+\d+", appl):
            continue
        brand = (result.get("products") or [{}])[0].get("brand_name")
        for sub in result.get("submissions") or []:
            if sub.get("submission_class_code") != "EFFICACY" \
                    or sub.get("submission_status") != "AP":
                continue
            approval_date = _iso(sub.get("submission_status_date"))
            if approval_date is None:
                continue
            rows.append({
                "ticker": ticker,
                "application_number": appl,
                "internal_code": normalize_appl(
                    *re.match(r"([A-Za-z]+)(\d+)", appl).groups()),
                "submission_number": str(sub.get("submission_number") or ""),
                "submission_class_code": "EFFICACY",
                "approval_date": approval_date,
                "brand": brand.title() if brand else None,
                "description": sub.get("submission_class_code_description")
                or "Efficacy supplement",
            })
    return rows


class ApprovalsOpenFdaFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()

    @property
    def entity_key(self) -> str:
        return self.ticker

    def _company_id(self, conn) -> int | None:
        row = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (self.ticker,)
        ).fetchone()
        return row[0] if row else None

    def _run(self, query: str) -> list[dict]:
        params = {"search": query, "limit": _LIMIT}
        api_key = (os.getenv("OPENFDA_API_KEY") or "").strip()
        if api_key:
            params["api_key"] = api_key
        url = f"{DRUGSFDA_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8")).get("results", [])
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # openFDA returns 404 for no matches
                return []
            raise

    def fetch(self) -> dict:
        names = company_names.source_name(self.ticker, "openfda_manufacturer",
                                          MANUFACTURER_MAP.get(self.ticker), self.db_path)
        sponsor = company_names.source_name(self.ticker, "openfda_sponsor",
                                            SPONSOR_MAP.get(self.ticker), self.db_path)
        if isinstance(names, str):
            names = [names]
        if not names and not sponsor:
            # A clinical-stage company has no approved product and so no manufacturer
            # string at openFDA. That is the ordinary state of half this universe now,
            # not a misconfiguration, so it returns nothing rather than raising.
            return {"results": [], "note": "no approved products at openFDA"}

        results: list[dict] = []
        if names:
            phrase = " ".join(f'"{n}"' for n in names)
            results += self._run(f"openfda.manufacturer_name:({phrase})")
        if sponsor:
            results += self._run(f"sponsor_name:({sponsor})")
        # The products this company owns because it bought the company that registered
        # them. openFDA files an approval under the manufacturer named on it, and that
        # name is not updated when the manufacturer is acquired: Tavneos is filed under
        # ChemoCentryx years after Amgen bought it, so Amgen's own searches miss a drug
        # it sells. Each acquired name is asked for separately, so one that matches
        # nothing costs a 404 and no results rather than breaking the query.
        for acquired in acquired_sponsors.for_company(self.db_path, self.ticker):
            results += self._run(f'openfda.manufacturer_name:("{acquired}")')

        # An application can come back from both queries. The application number is its
        # identity, so a later parse keying on it dedupes, but merging here keeps the
        # count honest and the payload small.
        seen, merged = set(), []
        for item in results:
            number = item.get("application_number")
            if number and number in seen:
                continue
            seen.add(number)
            merged.append(item)
        return {"results": merged}

    def normalise(self, raw) -> dict:
        # Both signals come from the one payload: the approvals, and the approved
        # efficacy supplements sitting inside the same submissions arrays.
        return {"approvals": parse_drugsfda(raw, self.ticker),
                "supplements": parse_supplements(raw, self.ticker)}

    # --- snapshots -------------------------------------------------------
    def _write_snapshot(self, conn, payload):
        conn.execute(
            """
            INSERT INTO snapshots (source, entity_type, entity_key, payload, refresh_run_id)
            VALUES (?, 'company', ?, ?, ?)
            """,
            (self.source, self.ticker, json.dumps(payload), self.refresh_run_id),
        )

    def snapshot(self, rows: dict) -> None:
        approvals = rows["approvals"] if isinstance(rows, dict) else rows
        latest = max((r["approval_date"] for r in approvals), default=None)
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(
                conn,
                {"ticker": self.ticker, "approvals": len(approvals),
                 "supplements": len(rows.get("supplements", []))
                 if isinstance(rows, dict) else 0,
                 "latest_approval": latest, "source": OPENFDA_SOURCE, "fetch_kind": "live"},
            )
            conn.commit()
        finally:
            conn.close()

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            company_id = self._company_id(conn)
            if company_id is None:
                return
            n = conn.execute(
                """
                SELECT COUNT(*) FROM approvals ap JOIN assets a ON ap.asset_id = a.id
                 WHERE a.owner_company_id = ? AND ap.source = ?
                """,
                (company_id, OPENFDA_SOURCE),
            ).fetchone()[0]
            if not n:
                return
            self._write_snapshot(conn, {"ticker": self.ticker, "approvals": n,
                                        "source": OPENFDA_SOURCE, "fetch_kind": "cache"})
            conn.commit()
        finally:
            conn.close()

    # --- current-state table ---------------------------------------------
    def upsert(self, rows: dict) -> RefreshResult:
        approvals = rows["approvals"] if isinstance(rows, dict) else rows
        supplements = rows.get("supplements", []) if isinstance(rows, dict) else []
        conn = db.get_connection(self.db_path)
        try:
            company_id = self._company_id(conn)
            if company_id is None:
                return RefreshResult(self.source, 0, [f"unknown ticker {self.ticker}"], False, 0)
            for row in approvals:
                asset_id = upsert_asset(
                    conn, company_id, row["internal_code"], row["brand"],
                    row["generic"], row["modality"],
                )
                conn.execute(
                    "DELETE FROM approvals WHERE asset_id = ? AND source = ?",
                    (asset_id, OPENFDA_SOURCE),
                )
                conn.execute(
                    """
                    INSERT INTO approvals
                        (asset_id, region, agency, approval_date, application_number, source)
                    VALUES (?, 'US', 'FDA', ?, ?, ?)
                    """,
                    (asset_id, row["approval_date"], row["application_number"], OPENFDA_SOURCE),
                )
            # Efficacy supplements attach to the asset that holds the application, so
            # they resolve against the same internal_code the approval created.
            for sup in supplements:
                asset = conn.execute(
                    "SELECT id FROM assets WHERE owner_company_id = ?"
                    " AND internal_code = ?",
                    (company_id, sup["internal_code"])).fetchone()
                conn.execute(
                    """
                    INSERT INTO supplements (asset_id, application_number,
                        submission_number, submission_class_code, approval_date,
                        description)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(application_number, submission_number) DO UPDATE SET
                        approval_date=excluded.approval_date,
                        asset_id=excluded.asset_id, fetched_at=datetime('now')
                    """,
                    (asset["id"] if asset else None, sup["application_number"],
                     sup["submission_number"], sup["submission_class_code"],
                     sup["approval_date"], sup["description"]))
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(approvals) + len(supplements), [], False, 0)
