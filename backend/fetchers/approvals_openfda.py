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
import time
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


# How many molecules to ask about per company. Every one is a request, and a company
# with two hundred assets would otherwise make two hundred of them for the handful that
# are approved. Ordered by name so the cap is at least deterministic.
_MAX_GENERIC_QUERIES = 60
_POLITE_SLEEP_S = 0.12

# Words too common in a drug company's name to identify one. Without these, every
# "Pharmaceuticals" matches every other.
_COMMON_NAME_WORDS = {
    "inc", "corp", "corporation", "company", "co", "plc", "ltd", "limited", "holdings",
    "group", "holding", "the", "and", "pharmaceuticals", "pharmaceutical", "pharms",
    "pharma",
    "therapeutics", "biosciences", "bioscience", "sciences", "science", "biopharma",
    "biopharmaceuticals", "medicines", "laboratories", "labs", "health", "healthcare",
    "usa", "us", "america", "american", "international", "global", "nv", "sa", "ag",
    "as", "gmbh", "llc", "lp",
}


# How a trial names the same molecule twice: "Oral Treprostinil" and "Parenteral
# Treprostinil" are one drug given two ways, and openFDA indexes neither. The route and
# the form are stripped so the molecule is what gets asked for.
_FORM_WORDS = re.compile(
    r"^(?:oral|parenteral|inhaled|nebuli[sz]ed|intravenous|iv|subcutaneous|sc|topical|"
    r"injectable|injection|solution|tablet|capsule|extended[- ]release|autoinjector|"
    r"prefilled|recombinant|human|sterile)\s+", re.I)


def _molecule(generic: str) -> str:
    """A generic name reduced to the molecule, with the route and form removed."""
    text = (generic or "").strip()
    for _ in range(3):                      # "Oral Extended-Release Treprostinil"
        stripped = _FORM_WORDS.sub("", text)
        if stripped == text:
            break
        text = stripped
    return text.strip()


def _distinctive_words(name: str) -> set:
    """The words in a name that could identify the company.

    openFDA abbreviates a sponsor to "ALNYLAM PHARMS INC" or "UNITED THERAP", so an
    exact comparison is useless and the shared distinctive word is what survives. A
    prefix is enough on both sides, since "THERAP" is how it writes "Therapeutics".
    """
    words = set()
    for word in re.split(r"[^A-Za-z]+", (name or "").lower()):
        if len(word) >= 4 and word not in _COMMON_NAME_WORDS:
            words.add(word)
    return words


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

    def _by_generic_name(self) -> list[dict]:
        """Approvals found by asking openFDA for each molecule this company develops.

        Every result is checked against the company's own name before it is kept: a
        generic can be sold by a dozen manufacturers, and treprostinil returns nine
        applications of which only some are United Therapeutics'. The check is a shared
        distinctive word, which is what survives openFDA's abbreviations.
        """
        conn = db.get_connection(self.db_path)
        try:
            company = conn.execute(
                "SELECT id, name FROM companies WHERE ticker = ?",
                (self.ticker,)).fetchone()
            if company is None:
                return []
            generics = [r[0] for r in conn.execute(
                "SELECT DISTINCT generic_name FROM assets"
                "  WHERE owner_company_id = ? AND generic_name IS NOT NULL"
                "  ORDER BY generic_name LIMIT ?",
                (company["id"], _MAX_GENERIC_QUERIES))]
        finally:
            conn.close()
        if not generics:
            return []

        wanted = _distinctive_words(company["name"])
        found = []
        for generic in generics:
            generic = _molecule(generic)
            # A code number is not a generic name and matches nothing here.
            if not generic or len(generic) < 6 or re.search(r"\d", generic):
                continue
            for result in self._run(f'openfda.generic_name:"{generic}"'):
                if _distinctive_words(result.get("sponsor_name") or "") & wanted:
                    found.append(result)
            time.sleep(_POLITE_SLEEP_S)
        return found

    def fetch(self) -> dict:
        names = company_names.source_name(self.ticker, "openfda_manufacturer",
                                          MANUFACTURER_MAP.get(self.ticker), self.db_path)
        sponsor = company_names.source_name(self.ticker, "openfda_sponsor",
                                            SPONSOR_MAP.get(self.ticker), self.db_path)
        if isinstance(names, str):
            names = [names]

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

        # Nothing found by company name, so ask by molecule instead. The maps above are
        # hand-keyed and a company absent from them was being treated as clinical-stage,
        # which was wrong about Neurocrine, Alnylam, Ionis, Sarepta, Moderna and United
        # Therapeutics: all six sell drugs and all six had no approval on file. Guessing
        # harder at the sponsor string does not fix it, because openFDA writes them as
        # "ALNYLAM PHARMS INC", "UNITED THERAP" and "INCYTE CORP", which no rule derives
        # from a company name.
        #
        # A generic name does not have that problem. It identifies one molecule, it is
        # what the registry gave us for every asset these companies own, and the answer
        # carries the sponsor so the match can be checked rather than assumed.
        # Run whenever the maps do not know this company, rather than when nothing at
        # all was found. Neurocrine has an acquisition, so its acquired-sponsor query
        # returned a single application and that was enough to skip the discovery route
        # entirely, leaving three of its four approvals unfound.
        if not names and not sponsor:
            found = self._by_generic_name()
            results += found
            # The answers carry the sponsor string openFDA actually uses, which is the
            # thing no rule could derive: "ALNYLAM PHARMS INC", "UNITED THERAP",
            # "INCYTE CORP". Asking for it directly then returns the rest of the
            # portfolio, since a molecule search only ever finds the molecules we
            # already knew about. Alnylam goes from one approval to four this way and
            # Incyte from two to six, and the map stays empty: the fetcher discovers
            # the name instead of being told it.
            for sponsor_name in sorted({r.get("sponsor_name") for r in found
                                        if r.get("sponsor_name")}):
                results += self._run(f'sponsor_name:"{sponsor_name}"')
                time.sleep(_POLITE_SLEEP_S)

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
