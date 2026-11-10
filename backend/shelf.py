"""Where a marketed product actually stands: still sold, off patent, or withdrawn.

"Marketed" in this book has meant "was approved and nobody has said otherwise", and that
runs three different things together under one word and one blank revenue column:

- a product the company stopped selling, whose revenue is blank because there is none;
- a product that sells and that the filer does not break out, whose revenue is blank
  because no free source states it;
- a product nobody has modelled yet.

They look identical on the page and need opposite responses. The first should leave the
book, the second is genuinely no free data and should say so, and only the third is work.
Of 1,524 marketed products, 421 are withdrawn in the US and 416 of those carry no
revenue: the blank was the truth rather than a gap.

Two readings settle it, and both are already on file:

- **sold**, from openFDA's marketing status on the application
  (``marketing_status.for_assets``). Prescription and over-the-counter are sold;
  Discontinued is not.
- **exclusivity**, from the book's own LOE (``loe.for_assets``). A date in the past means
  generics or biosimilars are on the market, whatever the brand still earns.

Nothing here is estimated. A product whose application the FDA does not resolve is
reported as unknown rather than assumed to be selling.

The reading is American, and the states say so. openFDA knows what the FDA approved and
nothing about what a filer sells in Europe or Japan, while the revenue row beside it is
worldwide. Where the two disagree the product gets its own state rather than being filed
under either: Pfizer's Vyndaqel is discontinued here, because Vyndamax replaced it, and
carries $6,380mm of the tafamidis family's worldwide sales. Calling that withdrawn would
read as $6.4bn of dead revenue, and calling it selling would contradict the FDA. It is
both, and the state is the pair.

The 218 assets with no status at all are mostly the filers who register elsewhere, and
they carry $205.5bn, so this classification covers the American book and says where it
does not reach.
"""

from __future__ import annotations

import datetime as dt

import db
import loe
import marketing_status

# Re-exported: callers that read a shelf row should not have to know which module holds
# the FDA's vocabulary.
SELLING = marketing_status.SELLING

# Two different unknowns, kept apart. A product the FDA says is on sale and whose
# exclusivity the book does not hold is a gap in the patent data; one whose status the
# FDA does not resolve is a gap in the registry. Running them together put $216.9bn of
# revenue under one word that meant neither.
#
# And two different withdrawals. One is the common case, a product that stopped selling
# and earns nothing. The other is a product the FDA says is gone that still files
# revenue, which is the American status meeting a worldwide revenue line, and it is five
# products carrying $8,525mm.
STATES = ("selling, protected", "selling, off patent", "selling, exclusivity unknown",
          "withdrawn in the US, still earning", "withdrawn in the US", "status unknown")


def state_for(status: str | None, loe_date: str | None, today: dt.date,
              revenue: float | None = None) -> str:
    """One product's state, from its FDA status and the book's own exclusivity."""
    if status and not marketing_status.sold_in_us(status):
        return ("withdrawn in the US, still earning" if (revenue or 0) > 0
                else "withdrawn in the US")
    if not status:
        return "status unknown"
    if not loe_date:
        return "selling, exclusivity unknown"
    return ("selling, off patent"
            if dt.date.fromisoformat(loe_date) < today else "selling, protected")


def states_for(conn, asset_ids, today=None) -> dict:
    """{asset_id: {marketing_status, state, loe, loe_basis}} for any list of assets.

    The product page reads this beside each card and ``for_company`` totals it, so a card
    and the board behind it cannot disagree about what a product is.
    """
    ids = list(asset_ids)
    if not ids:
        return {}
    today = today or dt.date.today()
    statuses = marketing_status.for_assets(conn, ids)
    dates = loe.for_assets(conn, ids)
    revenue = {r["asset_id"]: r["value"] for r in conn.execute(
        f"""SELECT asset_id, value FROM asset_revenue
             WHERE period = 'FY' AND asset_id IN ({', '.join('?' for _ in ids)})
               AND fiscal_year = (SELECT MAX(fiscal_year) FROM asset_revenue r2
                                   WHERE r2.asset_id = asset_revenue.asset_id
                                     AND r2.period = 'FY')""", ids)}
    out = {}
    for asset_id in ids:
        entry = dates.get(asset_id) or {}
        status = statuses.get(asset_id)
        out[asset_id] = {
            "marketing_status": status,
            "loe": entry.get("date"), "loe_basis": entry.get("basis"),
            "state": state_for(status, entry.get("date"), today, revenue.get(asset_id)),
        }
    return out


def for_company(db_path=None, ticker: str = "", today=None) -> dict:
    """Every marketed product of one company, by where it stands. {rows, totals}."""
    today = today or dt.date.today()
    conn = db.get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT a.id, COALESCE(a.brand_name, a.generic_name) AS name,
                      (SELECT r.value / 1e6 FROM asset_revenue r
                        WHERE r.asset_id = a.id AND r.period = 'FY'
                        ORDER BY r.fiscal_year DESC LIMIT 1) AS revenue
                 FROM assets a JOIN companies c ON c.id = a.owner_company_id
                WHERE c.ticker = ? AND a.is_marketed = 1
                ORDER BY a.id""", (ticker.upper(),))]
        found = states_for(conn, [r["id"] for r in rows], today=today)
    finally:
        conn.close()

    out = [{**row, **found.get(row["id"], {})} for row in rows]
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
