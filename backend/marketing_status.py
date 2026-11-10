"""What the FDA says about whether an application is still on sale, read per asset.

openFDA states a marketing status on every application (``approvals.marketing_status``)
and two modules need the same reading of it: ``shelf``, which sorts a company's products
by where they stand, and ``loe``, which must not count a product withdrawn from the US
as losing US exclusivity. The rule is short and it is not the obvious one, so it lives
here once rather than twice.

The status of an asset is the **strongest** across every application it holds, not the
latest one's. A brand whose superseded formulation is discontinued and whose current one
is not is still sold, and reading the newest application alone withdrew $11.7bn of
revenue.

The reading is American. openFDA knows what the FDA approved and nothing about what a
filer sells in Europe or Japan, so a discontinued application means withdrawn in the US
and not withdrawn. Every caller has to say so.
"""

from __future__ import annotations

# openFDA's words for an application that is still on sale. Tentative approval is not:
# it means the FDA would approve but something, usually exclusivity on the brand, stops
# the product being marketed.
SELLING = ("Prescription", "Over-the-counter")

# Asset ids bound per statement. Well under any build's parameter limit.
_BATCH = 400


def sold_in_us(status: str | None) -> bool:
    """Whether the FDA says this product is on sale here.

    An unresolved status answers False and so does a withdrawal, which is why no caller
    may use this alone: the two are different facts and each view names which it has.
    """
    return status in SELLING


def for_assets(conn, asset_ids=None) -> dict:
    """{asset_id: status}, the strongest status across the asset's applications.

    An asset with no application carrying a status is absent rather than present with a
    null: the FDA not resolving a product is a gap in the registry, and recording it as
    a state would make it look like an answer.
    """
    ids = None if asset_ids is None else list(asset_ids)
    if ids is not None and not ids:
        return {}
    out = {}
    # Asked for in batches, because the cliff reads this for every asset carrying a date
    # still ahead of it and that list is 558 today. SQLite binds a limited number of
    # parameters per statement and the number is a build option, so the call site must
    # not be the thing that knows it.
    batches = ([ids[i:i + _BATCH] for i in range(0, len(ids), _BATCH)]
               if ids is not None else [None])
    for batch in batches:
        where, params = "", []
        if batch is not None:
            where = f" AND asset_id IN ({', '.join('?' for _ in batch)})"
            params = batch
        for row in conn.execute(
                "SELECT asset_id, GROUP_CONCAT(DISTINCT marketing_status) AS statuses"
                "  FROM approvals WHERE marketing_status IS NOT NULL" + where
                + " GROUP BY asset_id", params):
            seen = {s for s in (row["statuses"] or "").split(",") if s}
            if not seen:
                continue
            # Sorted where nothing sells, so an asset carrying two kinds of withdrawal
            # reads the same on every run rather than following the join's own order.
            out[row["asset_id"]] = (next((s for s in SELLING if s in seen), None)
                                    or sorted(seen)[0])
    return out
