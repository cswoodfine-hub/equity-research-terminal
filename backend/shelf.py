"""Where a marketed product actually stands: still sold, off patent, or withdrawn.

"Marketed" in this book has meant "was approved and nobody has said otherwise", and that
runs three different things together under one word and one blank revenue column:

- a product the company stopped selling, whose revenue is blank because there is none;
- a product that sells and that the filer does not break out, whose revenue is blank
  because no free source states it;
- a product nobody has modelled yet.

They look identical on the page and need opposite responses. The first should leave the
book, the second is genuinely no free data and should say so, and only the third is work.
Of 141 applications of the eight largest filers checked against openFDA, 20 are
Discontinued and 19 of those carry no revenue.

Two readings settle it, and both are already on file once the fetcher stops dropping the
first:

- **sold**, from openFDA's ``marketing_status`` on the application (``approvals``).
  Prescription and over-the-counter are sold; Discontinued is not.
- **exclusivity**, from the book's own LOE (``loe.for_assets``). A date in the past means
  generics or biosimilars are on the market, whatever the brand still earns.

Nothing here is estimated. A product whose application the FDA does not resolve is
reported as unknown rather than assumed to be selling.

The reading is American, and the state says so. openFDA knows what the FDA approved and
nothing about what a filer sells in Europe or Japan, so a discontinued application means
withdrawn in the US and not withdrawn: $8.5bn of revenue sits on applications the FDA
calls Discontinued, which is a product that stopped selling here and did not stop
selling. The 218 assets with no status at all are mostly the filers who register
elsewhere, and they carry $205.5bn, so this classification covers the American book and
says where it does not reach.
"""

from __future__ import annotations

import datetime as dt

import db
import loe

# openFDA's words for an application that is still on sale. Tentative approval is not:
# it means the FDA would approve but something, usually exclusivity on the brand, stops
# the product being marketed.
SELLING = ("Prescription", "Over-the-counter")

# Two different unknowns, kept apart. A product the FDA says is on sale and whose
# exclusivity the book does not hold is a gap in the patent data; one whose status the
# FDA does not resolve is a gap in the registry. Running them together put $216.9bn of
# revenue under one word that meant neither.
STATES = ("selling, protected", "selling, off patent", "selling, exclusivity unknown",
          "withdrawn in the US", "status unknown")


def _state(status: str | None, loe_date: str | None, today: dt.date) -> str:
    if status and status not in SELLING:
        return "withdrawn in the US"
    if not status:
        return "status unknown"
    if not loe_date:
        return "selling, exclusivity unknown"
    return ("selling, off patent"
            if dt.date.fromisoformat(loe_date) < today else "selling, protected")


def for_company(db_path=None, ticker: str = "", today=None) -> dict:
    """Every marketed product of one company, by where it stands. {rows, totals}."""
    today = today or dt.date.today()
    conn = db.get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT a.id, COALESCE(a.brand_name, a.generic_name) AS name,
                      (SELECT r.value / 1e6 FROM asset_revenue r
                        WHERE r.asset_id = a.id AND r.period = 'FY'
                        ORDER BY r.fiscal_year DESC LIMIT 1) AS revenue,
                      (SELECT GROUP_CONCAT(DISTINCT ap.marketing_status)
                         FROM approvals ap
                        WHERE ap.asset_id = a.id
                          AND ap.marketing_status IS NOT NULL) AS statuses
                 FROM assets a JOIN companies c ON c.id = a.owner_company_id
                WHERE c.ticker = ? AND a.is_marketed = 1
                ORDER BY a.id""", (ticker.upper(),))]
        dates = loe.for_assets(conn, [r["id"] for r in rows]) if rows else {}
    finally:
        conn.close()

    out = []
    for row in rows:
        entry = dates.get(row["id"]) or {}
        # The strongest status across every application the asset holds, not the latest
        # one's: a brand whose superseded formulation is discontinued and whose current
        # one is not is still sold, and reading the newest application alone withdrew
        # $11.7bn of selling revenue.
        seen = {s for s in (row.pop("statuses", "") or "").split(",") if s}
        status = next((s for s in SELLING if s in seen), None) or next(iter(seen), None)
        out.append({**row, "marketing_status": status,
                    "loe": entry.get("date"), "loe_basis": entry.get("basis"),
                    "state": _state(status, entry.get("date"), today)})
    totals = {state: {"products": 0, "revenue": 0.0} for state in STATES}
    for row in out:
        bucket = totals[row["state"]]
        bucket["products"] += 1
        bucket["revenue"] += row.get("revenue") or 0.0
    return {"ticker": ticker.upper(), "as_of": str(today), "rows": out,
            "totals": totals,
            # The count that was the question: products carrying no revenue, split by
            # whether that is because nothing is sold or because nothing is disclosed.
            "no_revenue": {
                state: sum(1 for r in out
                           if r["state"] == state and not (r.get("revenue") or 0))
                for state in STATES},
            }
