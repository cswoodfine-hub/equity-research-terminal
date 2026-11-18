"""The universe as the daily pulse reads it: ``data/pulse_universe.json``.

The pulse is a scheduled Claude run with no copy of the terminal. Before it tags an item
it fetches this file from the repository's main branch, so it names a covered company by
the ticker the terminal holds it under (ROG, not RHHBY), knows the names the press uses
for it (Kite is Gilead, Genentech is Roche) and the drugs it owns (Zolgensma is
Novartis's, asundexian Bayer's), and knows the names that look like a covered company
and are not one (Merck KGaA is not Merck & Co). Nothing in it is a value: names only.

The refresh writes it after every run and commits it with the day's history, so it is
never older than the book it describes. A drug name two covered companies share, a
generic or a co-marketed brand, is left out of both, since it could only mislead.

    python backend/pulse_universe.py            # writes data/pulse_universe.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import company_names  # noqa: E402
import db  # noqa: E402

SCHEMA = 1
OUT = db.BACKEND_DIR.parent / "data" / "pulse_universe.json"
# A registry name with a code or a formulation in brackets ("Radium-223 dichloride
# (Xofigo, BAY88-8223)") is longer than any headline would print; the parts are listed
# on their own where they are an asset's own name.
MAX_NAME = 40
# A short pipeline list keeps the file readable; the brands and the late-stage names are
# what headlines carry.
MAX_PIPELINE = 40


def _clean(name) -> str | None:
    name = " ".join(str(name or "").split())
    if len(name) < 4 or len(name) > MAX_NAME or "(" in name or ";" in name:
        return None
    return name


def build(conn) -> dict:
    """The file's contents, read from the companies and assets tables. Pure of any clock,
    so the file only changes when the universe does."""
    owners: dict = {}
    rows = list(conn.execute(
        """SELECT a.owner_company_id AS cid, a.brand_name, a.generic_name, a.internal_code,
                  a.is_marketed,
                  (SELECT MAX(CASE lower(ai.phase) WHEN 'phase 4' THEN 4
                                  WHEN 'phase 3' THEN 3 WHEN 'phase 2/3' THEN 3
                                  WHEN 'phase 2' THEN 2 ELSE 1 END)
                     FROM asset_indications ai WHERE ai.asset_id = a.id) AS stage
             FROM assets a WHERE a.owner_company_id IS NOT NULL"""))
    for r in rows:
        for name in (r["brand_name"], r["generic_name"], r["internal_code"]):
            name = _clean(name)
            if name:
                owners.setdefault(name.lower(), set()).add(r["cid"])
    brands: dict = {}
    pipeline: dict = {}
    for r in sorted(rows, key=lambda r: (-(r["stage"] or 0), r["generic_name"] or "")):
        for name, marketed in ((r["brand_name"], True), (r["generic_name"], r["is_marketed"]),
                               (r["internal_code"], False)):
            name = _clean(name)
            # An application number is how the FDA files a product, not what a headline
            # calls it.
            if not name or re.fullmatch(r"(?:NDA|BLA|ANDA)\d+", name) \
                    or len(owners.get(name.lower(), ())) != 1:
                continue
            bucket = brands if marketed else pipeline
            bucket.setdefault(r["cid"], [])
            if name not in bucket[r["cid"]] and name.lower() not in {
                    n.lower() for n in brands.get(r["cid"], []) + pipeline.get(r["cid"], [])}:
                bucket[r["cid"]].append(name)
    companies = []
    for c in conn.execute("SELECT id, ticker, name, us_adr_ticker FROM companies ORDER BY ticker"):
        press = [n for n in dict.fromkeys(
            (company_names.bare(c["name"]), *company_names.press_names(c["ticker"], c["name"])))]
        companies.append({
            "ticker": c["ticker"], "name": c["name"],
            "us_adr_ticker": c["us_adr_ticker"] or None,
            "press_names": press,
            "aliases": list(company_names.PRESS_ALIASES.get(c["ticker"], ())),
            "brands": sorted(brands.get(c["id"], []), key=str.lower),
            "pipeline": pipeline.get(c["id"], [])[:MAX_PIPELINE]})
    return {"schema": SCHEMA,
            "about": ("The companies the equity research terminal covers. Tag an item with "
                      "these tickers only; a name under not_these is a different company."),
            "companies": companies,
            "not_these": [{"name": n, "is_not": t}
                          for n, t in sorted(company_names.NOT_THESE.items())]}


def write(db_path=None, out: Path = OUT) -> Path:
    conn = db.get_connection(db_path)
    try:
        payload = build(conn)
    finally:
        conn.close()
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    path = write(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"wrote {path}")
