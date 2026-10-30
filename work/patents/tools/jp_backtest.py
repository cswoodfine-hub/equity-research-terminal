"""Backtest a Japanese LOE date against the dates filers state.

Ground truth: the JP date the filer prints in its own patent table
(``data/disclosed_loe_regions.csv``). Each rule sees only what the book holds: the US
date (``loe.for_assets``) and the substance's first Japanese approval as a new active
ingredient (``regional_loe.first_jp_approval``, from the PMDA list in ``jp_approvals``).

Bias, stated: the PMDA list starts in April 2004, so only products first approved in
Japan since then can be tested, and filers state dates mostly for their largest products.

    ER_TOOL_DB=<copy> python3 work/patents/tools/jp_backtest.py
"""

import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import db  # noqa: E402
import loe  # noqa: E402
import regional_loe as R  # noqa: E402


def _floor(r, orphan_years):
    return r["first"] + (orphan_years if r["orphan"] else R.JP_REEXAMINATION_YEARS)


RULES = {
    "inherit the US date": lambda r: r["us"],
    "floor: max(US, first JP + 8)": lambda r: max(r["us"], _floor(r, 8)),
    "floor: max(US, first JP + 8, orphan + 10)":
        lambda r: max(r["us"], _floor(r, R.JP_ORPHAN_REEXAMINATION_YEARS)),
}


def main():
    conn = db.get_connection()
    us = loe.for_assets(conn, None, exclude_orphan=True)
    rows, untestable = [], 0
    for (asset_id,) in conn.execute("SELECT id FROM assets"):
        jp = (R.disclosed_for(conn, asset_id) or {}).get("JP")
        if not isinstance(jp, dict) or jp.get("year") is None:
            continue
        first = R.first_jp_approval(conn, asset_id)
        us_date = (us.get(asset_id) or {}).get("date")
        if not first or not us_date:
            untestable += 1
            continue
        name = conn.execute("SELECT brand_name FROM assets WHERE id = ?",
                            (asset_id,)).fetchone()[0]
        rows.append({"name": name, "jp": int(jp["year"]), "us": int(us_date[:4]),
                     "first": int(first["date"][:4]), "orphan": first["orphan"]})
    print(len(rows), "products with a stated JP date, a US date and a first JP approval;",
          untestable, "without one of them")
    for name, rule in RULES.items():
        errors = [abs(rule(r) - r["jp"]) for r in rows]
        print(f"  {name}: within one year {sum(e <= 1 for e in errors) / len(errors):.0%},"
              f" exact {sum(e == 0 for e in errors) / len(errors):.0%},"
              f" mean {statistics.mean(errors):.2f}")
    final = list(RULES.values())[-1]
    for r in rows:
        if final(r) != r["us"]:
            print(f"  the floor moves {r['name']}: US {r['us']}, floor {final(r)},"
                  f" stated {r['jp']}")


if __name__ == "__main__":
    main()
