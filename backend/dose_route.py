"""Whether a product is taken by mouth, from the Orange Book's own route column.

Generic entry erodes an oral brand much faster than anything else: measured on Medicare
Part D after 104 first generic launches (work/patents/BACKTEST.md), an oral brand keeps a
median 0.245 of its cost in the first full year and a non-oral one (inhaled, injected,
applied, instilled) 0.41. A pharmacist substitutes a tablet automatically and rarely a
device, a pen or a cream. So the erosion default is chosen by route as well as by
modality.

The route is FDA's: each Orange Book product row carries "DF;Route", the dose form and
route ("TABLET;ORAL", "SOLUTION;SUBCUTANEOUS", "POWDER;INHALATION"), which the Orange
Book fetcher reduces per application and keeps on ``orange_book_listings``. Not the
RxNorm product names the payer views hold, which no valuation module may read
(test_payer_access). A product the Orange Book does not carry (a
biologic) or whose live strengths are taken both ways has no route on file and keeps its
modality's row.
"""

from __future__ import annotations

ORAL, NON_ORAL = "oral", "non-oral"

# Taken by mouth and substituted at the pharmacy like a tablet.
_ORAL_ROUTES = ("ORAL", "SUBLINGUAL", "BUCCAL")


def from_orange_book(df_route: str | None) -> str | None:
    """"oral", "non-oral" or None from an Orange Book "DF;Route" value. Pure."""
    route = (df_route or "").partition(";")[2].strip().upper()
    if not route:
        return None
    if any(route.startswith(r) for r in _ORAL_ROUTES):
        return ORAL
    return NON_ORAL


def for_asset(conn, asset_id: int) -> str | None:
    try:
        row = conn.execute("SELECT route FROM orange_book_listings WHERE asset_id = ?",
                           (asset_id,)).fetchone()
    except Exception:                       # noqa: BLE001 - before migration 097
        return None
    return row[0] if row else None
