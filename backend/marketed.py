"""What a company sells, taken from the register it puts its own name on.

Four sources set ``is_marketed`` and all four miss the same cohort. drugsfda is CDER's
and returns 404 for every BLA. The Orange Book carries no biologics at all. The Purple
Book covers them unevenly. A product revenue line needs a filing that breaks revenue out
by product, which a company one year into its first launch does not have. So Krystal
Biotech, which has sold Vyjuvek since May 2023, held eight assets with every one of them
unmarketed and no approval row anywhere, and the terminal read it as clinical stage.

The NDC directory answers exactly this question. A labeler is the company whose name is
on the package, so a row this company labels, licensed under an NDA or a BLA, is a
product this company sells. Both halves of that test are load-bearing. The labeler test
is what the fetcher tightened, and without it Sana Biotechnology owns every Chinese
cosmetics house with "Biotechnology" in its name. The application test is what keeps a
sunscreen and a hand sanitiser out: they are marketed, and they are not drugs.

Matching the register's brand against an existing asset was the first thing tried and it
resolves nothing. Krystal's eight assets are KB301, KB407 and six more, because they came
from its trials and a trial names a compound by its code; the register says VYJUVEK. The
two never meet. Across the whole universe that route promoted no asset at all, so a
product the register names and the asset table does not is written as a new asset, the
same way a product named in a revenue table already is.

Products are keyed by application rather than by brand, because the register lists
packages: Aleve is five brand rows against one NDA and Humalog is four against one BLA,
and each of those is one product. That key is also what the Orange Book, the Purple Book
and openFDA store, so a product already on file is found rather than duplicated.

No approval is written. A marketing date is not an approval date, and the asset carries
only the fact that it is sold; ``approval_dates`` labels the date itself as marketing
wherever it surfaces.
"""

from __future__ import annotations

import re

import approval_dates
import assets_util
import db

# Only a package licensed under an application. The register also lists monograph and
# unapproved products, which is how a sunscreen and a bottle of Epsom salt get an NDC
# number, and neither is a drug this terminal has any business calling a product.
_APPLICATION = re.compile(r"^(?:NDA|BLA)\d+$", re.I)

NOTE = ("this company labels the package in openFDA's NDC directory, under the "
        "application recorded here; no approval row, which drugsfda holds for no "
        "biologic at all")


def _products(conn, company_id: int) -> dict:
    """{application: brand} for what this company labels, one entry per product.

    The shortest brand on an application names it. Five Aleve rows differ by how the
    caplet opens, and "Aleve Caplets" describes the product better than "Aleve Caplets
    Easy Open Arthritis" does.
    """
    products: dict = {}
    for row in conn.execute(
        "SELECT brand_name, application_number FROM ndc_products"
        "  WHERE company_id = ? AND brand_name IS NOT NULL", (company_id,)):
        application = (row["application_number"] or "").strip().upper()
        if not _APPLICATION.match(application):
            continue
        code = assets_util.normalize_appl(application[:3], application)
        brand = row["brand_name"].strip()
        if not code or not brand:
            continue
        current = products.get(code)
        if current is None or (len(brand), brand) < (len(current), current):
            products[code] = brand
    return products


def _existing(conn, company_id: int, code: str, brand: str):
    """The asset this product is already on file as, if it is.

    By application first, which is exact and is how every other marketed-product source
    keys the same row. Then by name within the company, so a product the revenue table
    already named is marked rather than written twice.
    """
    row = conn.execute(
        "SELECT id, is_marketed FROM assets WHERE internal_code = ?", (code,)).fetchone()
    if row is not None:
        return row
    key = approval_dates.normalise(brand)
    if len(key) < 4:
        return None
    for candidate in conn.execute(
        "SELECT id, is_marketed, brand_name, generic_name FROM assets"
        "  WHERE owner_company_id = ?", (company_id,)):
        for field in ("brand_name", "generic_name"):
            if approval_dates.normalise(candidate[field]) == key:
                return candidate
    return None


def derive(db_path=None) -> dict:
    """Mark, or write, an asset for every product a company labels itself.

    Idempotent: a second run finds every product already on file and changes nothing.
    """
    conn = db.get_connection(db_path)
    created = promoted = 0
    try:
        for company in conn.execute("SELECT id FROM companies"):
            for code, brand in _products(conn, company["id"]).items():
                asset = _existing(conn, company["id"], code, brand)
                if asset is None:
                    conn.execute(
                        "INSERT INTO assets (owner_company_id, brand_name,"
                        "  internal_code, modality, is_marketed, notes)"
                        " VALUES (?, ?, ?, ?, 1, ?)",
                        (company["id"], brand, code,
                         # The application says which register licensed it, and a BLA is
                         # a biologic by definition. Nothing else here is inferred.
                         "biologic" if code.startswith("BLA") else "small molecule",
                         NOTE))
                    created += 1
                elif not asset["is_marketed"]:
                    conn.execute(
                        "UPDATE assets SET is_marketed = 1,"
                        "  internal_code = COALESCE(internal_code, ?),"
                        "  updated_at = datetime('now') WHERE id = ?",
                        (code, asset["id"]))
                    promoted += 1
        conn.commit()
    finally:
        conn.close()
    return {"created": created, "promoted": promoted}
