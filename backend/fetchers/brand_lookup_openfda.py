"""The ingredient behind a brand the company sells but does not hold the application for.

The approvals fetcher searches openFDA by sponsor, which is the right question for "what
has this company had approved" and the wrong one for "what is this product". Pfizer books
revenue on Xtandi, Padcev and Adcetris and holds the application for none of them:
Astellas holds the first two and Seattle Genetics the third. Those products reach the
database from the revenue table as a brand and nothing else, and every rule that asks a
row to prove it is a drug then rejects Pfizer's own oncology franchise.

So this asks openFDA the other question, by brand rather than by sponsor, for the rows
nothing else has been able to identify. It runs last, after the merge and after the fill
from data already on file, so it only reaches what those cannot answer.

What it writes is the ingredient and the application number, and it records the sponsor
alongside. It never writes an approval row: the application belongs to the company that
holds it, and adding one here would count a single approval twice everywhere approvals
are counted, and credit Pfizer with Astellas's filing. A row filled here is corroborated,
not credited.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import asset_identity
import db
from asset_merge import canonical_brand

DRUGSFDA_URL = "https://api.fda.gov/drug/drugsfda.json"

_USER_AGENT = os.getenv("SEC_USER_AGENT", "Novatalis Research contact@example.com")
_TIMEOUT_S = 20
# openFDA allows 240 requests a minute without a key. A quarter of a second between calls
# stays under that with room to spare, and this only ever runs on rows nothing else could
# identify, which is a short list that shrinks every time it runs.
_SLEEP_S = 0.25
# A ceiling on one run, so a database full of unidentifiable names cannot turn a refresh
# into a thousand requests. What is left is picked up on the next run.
MAX_LOOKUPS = 60


def _search(brand: str, get=None) -> dict | None:
    """The first drugsfda record for a brand, or None where openFDA has no match."""
    params = {"search": f'openfda.brand_name:"{brand}"', "limit": 1}
    api_key = (os.getenv("OPENFDA_API_KEY") or "").strip()
    if api_key:
        params["api_key"] = api_key
    url = f"{DRUGSFDA_URL}?{urllib.parse.urlencode(params)}"
    if get is not None:
        return get(url)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            results = json.loads(response.read().decode("utf-8")).get("results", [])
    except urllib.error.HTTPError as exc:
        if exc.code == 404:                 # openFDA says 404 for no matches
            return None
        raise
    return results[0] if results else None


def read(record: dict) -> dict | None:
    """{generic, application, sponsor} from one drugsfda record, or None if it says
    nothing useful. A record with no ingredient identifies nothing and is skipped."""
    if not record:
        return None
    openfda = record.get("openfda") or {}
    generics = openfda.get("generic_name") or []
    generic = (generics[0] if generics else "").strip()
    if not generic:
        return None
    return {"generic": generic.title(),
            "application": (record.get("application_number") or "").strip() or None,
            "sponsor": (record.get("sponsor_name") or "").strip() or None}


def unresolved(conn, limit: int = MAX_LOOKUPS) -> list:
    """Marketed rows still carrying a brand and nothing else, largest companies first.

    Marketed only. An unidentified row that is not on the market is a name read out of a
    filing, and openFDA has nothing to say about a compound with no approval anywhere.
    """
    return conn.execute(
        "SELECT a.id, a.brand_name, c.ticker FROM assets a"
        "  JOIN companies c ON c.id = a.owner_company_id"
        " WHERE a.is_marketed = 1 AND a.brand_name IS NOT NULL AND a.brand_name <> ''"
        "   AND a.generic_name IS NULL AND a.internal_code IS NULL"
        "   AND NOT EXISTS (SELECT 1 FROM approvals ap WHERE ap.asset_id = a.id)"
        " ORDER BY a.brand_name LIMIT ?", (limit,)).fetchall()


def resolve(db_path=None, limit: int = MAX_LOOKUPS, get=None) -> dict:
    """Fill what openFDA can identify by brand. Never overwrites, and writes no approval."""
    conn = db.get_connection(db_path)
    found, missing, errors = 0, 0, []
    try:
        rows = unresolved(conn, limit)
        for index, row in enumerate(rows):
            brand = (row["brand_name"] or "").strip()
            # A concatenated XBRL member name is not a brand openFDA can match. Two
            # products joined into one string, "Braftovi Mektovi", identify neither and
            # asking is a request spent on a certain miss.
            if len(canonical_brand(brand)) < 3 or not asset_identity.looks_like_a_product(brand):
                continue
            if index and get is None:
                time.sleep(_SLEEP_S)
            try:
                record = read(_search(brand, get))
            except Exception as exc:                    # a soft, reported failure
                errors.append(f"{row['ticker']} {brand}: {exc}")
                continue
            if not record:
                missing += 1
                continue
            note = f"ingredient from openFDA by brand"
            if record["sponsor"]:
                note += f"; application held by {record['sponsor']}"
            conn.execute(
                "UPDATE assets SET generic_name = COALESCE(generic_name, ?),"
                "  internal_code = COALESCE(internal_code, ?),"
                "  notes = COALESCE(notes, ?), updated_at = datetime('now')"
                " WHERE id = ?",
                (record["generic"], record["application"], note, row["id"]))
            found += 1
        conn.commit()
    finally:
        conn.close()
    return {"found": found, "missing": missing, "errors": errors}
