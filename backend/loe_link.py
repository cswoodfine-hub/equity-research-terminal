"""A revenue line joined to the FDA application whose exclusivity governs it.

A company books revenue under a name the FDA does not know it by, or under a
partner's application: Sanofi's Dupixent is Regeneron's BLA, Pfizer's Eliquis is
Bristol's NDA, Merck's Lynparza is AstraZeneca's. The two books attach exclusivity to
the applicant, so such a line carried no date and its forecast ran to perpetuity.

``data/loe_link.csv`` holds only the join. The date still comes from the books, on
the rule every asset uses. Where the application already sits under another asset on
file, the line reads that asset's resolved date, curated compound patent and all.
Where nothing on file holds it, the book fetchers attach the application's own rows
to the line directly, and this module tells them which lines those are.
"""

from __future__ import annotations

import csv
import json
import pathlib
import urllib.parse
import urllib.request

from assets_util import normalize_appl

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
LINK_FILE = DATA_DIR / "loe_link.csv"
LINK_SOURCE = "openfda via loe_link"
_OPENFDA = "https://api.fda.gov/drug/drugsfda.json"


def _code(application_number: str) -> str:
    """'NDA022264' and 'NDA22264' are one application; the normalised form is the key."""
    text = (application_number or "").strip().upper()
    kind = text[:3] if text[:3] in ("NDA", "BLA", "ANDA") else ""
    return normalize_appl(kind[:1] if kind else "", text)


def _padded(code: str) -> str:
    """'NDA22332' as the six-digit form openFDA writes, 'NDA022332'."""
    kind = code[:3] if code[:3] in ("NDA", "BLA") else code[:4]
    digits = code[len(kind):]
    return f"{kind}{digits.zfill(6)}" if digits.isdigit() else code


def load(conn, path=None) -> dict:
    """{asset_id: {"code", "application_number", "note"}} for every line the file joins
    to an asset on file. A row naming an asset that is not on file is skipped, since a
    join to nothing is not a join."""
    source = pathlib.Path(path) if path else LINK_FILE
    if not source.exists():
        return {}
    with source.open(newline="", encoding="utf-8") as handle:
        rows = [line for line in handle if not line.lstrip().startswith("#")]
    out = {}
    for row in csv.DictReader(rows):
        ticker = (row.get("ticker") or "").strip().upper()
        name = (row.get("asset") or "").strip()
        appl = (row.get("application_number") or "").strip()
        if not (ticker and name and appl):
            continue
        found = conn.execute(
            """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                WHERE c.ticker = ? AND LOWER(TRIM(COALESCE(a.brand_name, a.generic_name)))
                      = LOWER(?) LIMIT 1""", (ticker, name)).fetchone()
        if found:
            out[found["id"]] = {"code": _code(appl), "application_number": appl,
                                "note": (row.get("note") or "").strip()}
    return out


def holders(conn, code: str, exclude=()) -> list[int]:
    """Assets on file that hold this application: by internal code, or by an approval
    row. Excludes the asking asset, so a line never resolves to itself."""
    seen, out = set(exclude), []
    # Codes on file come in both forms, 'NDA22332' and 'NDA022332', from different
    # fetchers; both are the same application.
    forms = {code, _padded(code)}
    for row in conn.execute(
            f"SELECT id FROM assets WHERE internal_code IN ({', '.join('?' for _ in forms)})"
            " ORDER BY id", list(forms)):
        if row["id"] not in seen:
            seen.add(row["id"]); out.append(row["id"])
    # An application folded into another product on a merge lives on as an alias of
    # that product: Prezista's original NDA021976 sits under the asset that carries
    # the later NDA202895, and the rows attached to either are one product's.
    for row in conn.execute(
            f"SELECT asset_id FROM asset_aliases WHERE internal_code IN "
            f"({', '.join('?' for _ in forms)})", list(forms)):
        if row["asset_id"] not in seen:
            seen.add(row["asset_id"]); out.append(row["asset_id"])
    # The approvals join is done in Python: the stored form keeps its leading zeros.
    for row in conn.execute(
            "SELECT DISTINCT asset_id, application_number FROM approvals"
            " WHERE application_number IS NOT NULL"):
        if _code(row["application_number"]) == code and row["asset_id"] not in seen:
            seen.add(row["asset_id"]); out.append(row["asset_id"])
    return out


def attach_targets(conn, links=None) -> dict:
    """{application code: [asset ids]} the book fetchers should attach rows to directly.

    Two kinds of asset. A linked line whose application no other asset on file holds,
    since resolution by reference has nothing to reach. And any asset already carrying
    the application as its internal code, whatever its applicant: Imbruvica sits on file
    as NDA217003 and Comirnaty as BLA125742, and both were skipped because Pharmacyclics
    and BioNTech are not in the applicant map. The fetchers still create nothing new
    for these; they attach to what is there.
    """
    links = load(conn) if links is None else links
    out: dict = {}
    for asset_id, link in links.items():
        if not holders(conn, link["code"], exclude=(asset_id,)):
            out.setdefault(link["code"], []).append(asset_id)
    for row in conn.execute(
            "SELECT id, internal_code FROM assets WHERE internal_code IS NOT NULL"):
        code = row["internal_code"].strip().upper()
        if code[:3] in ("NDA", "BLA"):
            out.setdefault(code, [])
            if row["id"] not in out[code]:
                out[code].append(row["id"])
    return out


def fetch_openfda(application_number: str, api_key: str | None = None) -> dict | None:
    """The application's sponsor and original approval date from openFDA drugsfda, or
    None when it has no record (CBER vaccines, for one, are not there)."""
    query = urllib.parse.quote(f'application_number:"{application_number}"')
    url = f"{_OPENFDA}?search={query}&limit=1" + (f"&api_key={api_key}" if api_key else "")
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            payload = json.load(resp)
    except Exception:
        return None
    results = payload.get("results") or []
    if not results:
        return None
    result = results[0]
    original = [s for s in result.get("submissions", [])
                if s.get("submission_type") == "ORIG"
                and s.get("submission_status") == "AP"
                and s.get("submission_status_date")]
    date = min((s["submission_status_date"] for s in original), default=None)
    return {"application_number": result.get("application_number"),
            "sponsor": result.get("sponsor_name"),
            "approval_date": (f"{date[:4]}-{date[4:6]}-{date[6:8]}" if date else None),
            "brand": next((p.get("brand_name") for p in result.get("products", [])
                           if p.get("brand_name")), None)}


def sync_approvals(conn, fetch=fetch_openfda, links=None) -> dict:
    """Give every linked line that has no approval row the application's own approval
    date, from openFDA, so the profile shows when it was approved and a biologic's
    statutory floor can be counted. Idempotent: a line with any approval row is left
    alone. Returns counts."""
    links = load(conn) if links is None else links
    written, skipped, unknown = 0, 0, []
    for asset_id, link in links.items():
        have = conn.execute("SELECT 1 FROM approvals WHERE asset_id = ? LIMIT 1",
                            (asset_id,)).fetchone()
        if have:
            skipped += 1
            continue
        found = fetch(link["application_number"])
        if not found or not found.get("approval_date"):
            unknown.append(link["application_number"])
            continue
        conn.execute(
            """INSERT INTO approvals (asset_id, region, agency, approval_date,
                                      indication_text, application_number, source)
               VALUES (?, 'US', 'FDA', ?, ?, ?, ?)""",
            (asset_id, found["approval_date"],
             f"original approval, {found.get('sponsor') or 'sponsor not stated'}",
             found["application_number"], LINK_SOURCE))
        # The application type says what the product is, where nothing on file does.
        modality = ("biologic" if found["application_number"].upper().startswith("BLA")
                    else "small molecule")
        conn.execute("UPDATE assets SET modality = COALESCE(modality, ?) WHERE id = ?",
                     (modality, asset_id))
        written += 1
    return {"written": written, "skipped": skipped, "unknown": unknown}
