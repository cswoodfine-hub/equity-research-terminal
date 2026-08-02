"""Give a brand-only row the ingredient and the application number already on file.

A product reaches the database from whichever source names it first, and the sources do
not agree on what a product is. openFDA files an approval under the company that holds
the application. A revenue table files a brand under the company that books the sales.
Where those differ, the second company gets a row carrying a brand and nothing else.

Pfizer is the case. Its exhibit states revenue for Eliquis, Xtandi, Padcev and Adcetris,
and Pfizer holds the application for none of them: Bristol Myers holds Eliquis, Astellas
holds Xtandi. So Pfizer's rows for its own largest products had no ingredient, no code
and no approval, and every rule that asks a row to prove it is a drug rejected them.

Two facts are filled in, and only these two:

- The ingredient behind a brand, taken from any row anywhere that names it. An ingredient
  is a fact about the drug, not about who books it: apixaban is what Eliquis is whether
  Bristol Myers or Pfizer is counting the sale. Filled only where the universe agrees on
  one ingredient for that brand, never where two rows disagree.
- The application number, taken from the NDC directory where the FDA lists the company's
  own labeller against that brand. That is the company's own registration, not a
  partner's.

The approval itself is never copied. NDA202155 is one application held by one company,
and writing it under a second would count one approval twice everywhere approvals are
counted. A row filled here is corroborated, not credited.
"""

from __future__ import annotations

import re

import db
from asset_merge import canonical_brand

# Names that are revenue line items rather than products. An asset row exists for any
# name once seen in a revenue table, and the SEC data sets name their rows after XBRL
# members, so "Launches", "Collaboration Arrangement Including Arrangements With
# Affiliate" and "Product And Service Other" are assets in the same sense Eliquis is.
_NOT_A_PRODUCT = re.compile(
    r"^(launches|licen[cs]e|grant|technology|product and service|collaboration|"
    r"royalt|contract|milestone|service|other|total|subtotal|rest of|all other|"
    r"revenue|sales|net |gross )", re.I)


def looks_like_a_product(name: str) -> bool:
    """Whether a name could be a drug rather than a line on an income statement."""
    return bool(name) and not _NOT_A_PRODUCT.match(name.strip())


def ingredients(conn) -> dict:
    """{canonical brand: ingredient} for every brand the universe agrees on.

    A brand two rows give different ingredients for identifies neither, so it is dropped
    rather than filled from whichever row was read first.
    """
    seen: dict = {}
    for row in conn.execute(
            "SELECT brand_name, generic_name FROM assets"
            "  WHERE brand_name IS NOT NULL AND brand_name <> ''"
            "    AND generic_name IS NOT NULL AND generic_name <> ''"):
        brand = canonical_brand(row["brand_name"])
        if len(brand) > 2:
            seen.setdefault(brand, set()).add(row["generic_name"])
    return {brand: names.pop() for brand, names in seen.items() if len(names) == 1}


def registrations(conn) -> dict:
    """{(company_id, canonical brand): application number} from the NDC directory."""
    out: dict = {}
    for row in conn.execute(
            "SELECT company_id, brand_name, application_number FROM ndc_products"
            "  WHERE application_number IS NOT NULL AND application_number <> ''"
            "    AND company_id IS NOT NULL"):
        brand = canonical_brand(row["brand_name"])
        if len(brand) > 2:
            out.setdefault((row["company_id"], brand), row["application_number"])
    return out


def fill(db_path=None) -> dict:
    """Fill the ingredient and application number of every row that has neither.

    Never overwrites. A row that already names its ingredient is the better record, and
    this only reaches rows where every field behind the name is empty.
    """
    conn = db.get_connection(db_path)
    named = coded = 0
    try:
        by_brand = ingredients(conn)
        by_registration = registrations(conn)
        rows = conn.execute(
            "SELECT id, owner_company_id, brand_name FROM assets"
            "  WHERE brand_name IS NOT NULL AND brand_name <> ''"
            "    AND generic_name IS NULL AND internal_code IS NULL"
            "    AND NOT EXISTS (SELECT 1 FROM approvals ap WHERE ap.asset_id = assets.id)"
        ).fetchall()
        for row in rows:
            brand = canonical_brand(row["brand_name"])
            ingredient = by_brand.get(brand)
            registration = by_registration.get((row["owner_company_id"], brand))
            if not ingredient and not registration:
                continue
            conn.execute(
                "UPDATE assets SET generic_name = COALESCE(generic_name, ?),"
                "  internal_code = COALESCE(internal_code, ?),"
                "  updated_at = datetime('now') WHERE id = ?",
                (ingredient, registration, row["id"]))
            named += bool(ingredient)
            coded += bool(registration)
        conn.commit()
    finally:
        conn.close()
    return {"named": named, "coded": coded}
