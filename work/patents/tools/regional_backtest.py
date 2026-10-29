"""Backtest rules for a European LOE date against the dates filers state.

Ground truth: the EU date the filer prints in its own patent table
(``data/disclosed_loe_regions.csv``, read by ``regional_loe.disclosed_for``). Each rule
sees only what the book holds for a product with no stated date: the US date
(``loe.for_assets``) and the substance's first EU authorisation
(``regional_loe.first_eu_authorisation``).

Bias, stated: filers state regional dates mostly for their largest products, which carry
the most later patents, so the sample leans to products whose protection runs long.

    ER_TOOL_DB=<copy> python3 work/patents/tools/regional_backtest.py
"""

import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import db  # noqa: E402
import loe  # noqa: E402
import regional_loe  # noqa: E402

RULES = {
    "inherit the US date": lambda us, first: us,
    "floor: max(US, first EU + 10)": lambda us, first: max(us, first + 10),
    "SPC cap: min(US, first EU + 15)": lambda us, first: min(us, first + 15),
    "floor beneath the cap: max(first EU + 10, min(US, first EU + 15))":
        lambda us, first: max(first + 10, min(us, first + 15)),
}


def main():
    conn = db.get_connection()
    us = loe.for_assets(conn, None, exclude_orphan=True)
    rows = []
    for (asset_id,) in conn.execute("SELECT id FROM assets"):
        eu = (regional_loe.disclosed_for(conn, asset_id) or {}).get("EU")
        eu_year = eu.get("year") if isinstance(eu, dict) else None
        first = regional_loe.first_eu_authorisation(conn, asset_id)
        us_date = (us.get(asset_id) or {}).get("date")
        if eu_year is None or not first or not us_date:
            continue
        rows.append((int(eu_year), int(us_date[:4]), int(first["date"][:4])))
    print(len(rows), "products with a stated EU date, a US date and a first EU authorisation")
    for name, rule in RULES.items():
        errors = [abs(rule(u, f) - e) for e, u, f in rows]
        within = sum(x <= 1 for x in errors) / len(errors)
        print(f"  {name}: median {statistics.median(errors)} years out, "
              f"within one year {within:.0%}, mean {statistics.mean(errors):.2f}")
    print("median US less stated EU:", statistics.median([u - e for e, u, _ in rows]))


if __name__ == "__main__":
    main()
