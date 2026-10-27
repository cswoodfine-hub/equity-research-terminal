"""What an agent needs to build a marketed forecast for an asset the book does not model.

Different work from a layer. A layer is a pool and a penetration on top of a product
that already has a model; this is the model: a revenue anchor, a growth rate to a
published peak, a cost stack, a discount rate and a horizon. The book holds 353 of them
to copy the shape from, and the company-level half -- ratios, tax, discount rate -- is
already on a sibling seed and should be reused rather than researched again.

  python3 work/indication_backfill/asset_dossier.py AZN > /tmp/azn_assets.md
"""
from __future__ import annotations
import sqlite3, sys

sys.path.insert(0, "backend")
import db, brand_components                                        # noqa: E402

WANT = ("cogs_pct", "sga_pct", "rd_pct", "other_costs_pct", "tax_rate", "risk_free",
        "erp", "beta", "cost_of_debt", "debt_weight", "terminal_growth_pct")


def main(ticker: str) -> int:
    conn = db.get_connection(); conn.row_factory = sqlite3.Row
    modelled = {r["asset_id"] for r in conn.execute(
        "SELECT DISTINCT asset_id FROM assumptions WHERE key='therapy_mode'")}
    rows = conn.execute(
        """SELECT a.id, a.brand_name, a.generic_name, a.internal_code, a.is_marketed
             FROM assets a JOIN companies c ON c.id = a.owner_company_id
            WHERE c.ticker = ? AND a.is_marketed = 1""", (ticker,)).fetchall()
    todo = [r for r in rows if r["id"] not in modelled
            and conn.execute("SELECT 1 FROM catalysts cat JOIN asset_indications ai"
                             "  ON ai.id = cat.asset_indication_id"
                             " WHERE ai.asset_id = ? AND cat.status='pending'",
                             (r["id"],)).fetchone()]
    print(f"# {ticker}: {len(todo)} marketed assets the book does not model\n")

    sib = conn.execute(
        """SELECT a.brand_name FROM assets a JOIN companies c ON c.id=a.owner_company_id
            WHERE c.ticker=? AND a.id IN (SELECT asset_id FROM assumptions
                 WHERE key='other_costs_pct') ORDER BY a.id LIMIT 1""", (ticker,)).fetchone()
    if sib:
        print(f"**The company half is already written.** Copy `cogs_pct`, `sga_pct`, "
              f"`rd_pct`, `other_costs_pct`, `tax_rate`, `risk_free`, `erp`, `beta`, "
              f"`cost_of_debt`, `debt_weight` and `terminal_growth_pct` verbatim, with "
              f"their sources, from the seed for **{sib['brand_name']}**. They are the "
              f"company's, not the product's, and re-deriving them would put two "
              f"answers in the book for one company.\n")
    for r in todo:
        name = r["brand_name"] or r["generic_name"] or r["internal_code"]
        print(f"## {name}  (asset_id {r['id']})")
        if r["generic_name"]:
            print(f"- generic: {r['generic_name']}")
        demand = brand_components.demand_rows(conn, r["id"])
        latest: dict = {}
        for d in demand:
            if d["year"] >= latest.get(d["part"], (0,))[0]:
                latest[d["part"]] = (d["year"], d)
        for part, (_, d) in sorted(latest.items()):
            if d["total_beneficiaries"]:
                print(f"- CMS Part {part} {d['year']} ({d['brand_name']}): "
                      f"${d['total_spending']:,.0f} over {d['total_beneficiaries']:,} "
                      f"beneficiaries")
        for c in conn.execute(
                """SELECT cat.expected_date, cat.catalyst_type, cat.title, i.name ind,
                          ai.phase FROM catalysts cat
                     JOIN asset_indications ai ON ai.id = cat.asset_indication_id
                     JOIN indications i ON i.id = ai.indication_id
                    WHERE ai.asset_id = ? AND cat.status='pending'
                    ORDER BY cat.expected_date""", (r["id"],)):
            print(f"- **pending catalyst** {c['expected_date']} ({c['catalyst_type']}) "
                  f"in {c['ind']} [{c['phase']}]: {(c['title'] or '')[:80]}")
        inds = [x[0] for x in conn.execute(
            "SELECT i.name FROM asset_indications ai JOIN indications i"
            "  ON i.id=ai.indication_id WHERE ai.asset_id=? AND ai.phase='Approved'",
            (r["id"],))]
        if inds:
            print(f"- approved on file: {', '.join(inds[:6])}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1].upper()))
