"""Step 6 value gate: every asset's value under one checkout's code, as JSON.

Run once with main's backend and once with the branch's, on the same database copy
(or on two copies that differ only where the branch's fetchers write differently), then
compare with ``gate_report.py``. Covers every asset with assumptions, marketed and
pipeline, with the NPV, the risk-adjusted NPV and the LOE date the valuation used.

    ER_TOOL_DB=<copy> python3 work/patents/tools/gate.py <backend dir> out.json
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(sys.argv[1]).resolve()))

import assumptions  # noqa: E402
import db  # noqa: E402
import forecast  # noqa: E402


def main(out_path):
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT DISTINCT a.id, a.is_marketed, c.ticker,"
        " COALESCE(a.brand_name, a.generic_name) AS nm"
        "  FROM assets a JOIN assumptions s ON s.asset_id = a.id"
        "  JOIN companies c ON c.id = a.owner_company_id").fetchall()
    out = {}
    for r in rows:
        rec = {"ticker": r["ticker"], "name": r["nm"], "marketed": bool(r["is_marketed"])}
        try:
            built = forecast.build(assumptions.load(conn, r["id"], "base"))
            rec.update(npv=built.get("npv"), rnpv=built.get("rnpv"),
                       loe_year=built.get("loe_year"), loe_basis=built.get("loe_basis"),
                       in_base=built.get("loe_in_base"), erosion=built.get("erosion_basis"),
                       erosion_shape=[built.get("erosion_year1_pct"),
                                      built.get("erosion_decay_pct")],
                       regions=[(g.get("region"), g.get("loe_year"), g.get("in_base"))
                                for g in built.get("regions") or []],
                       notes=[n for n in built.get("notes") or [] if "peak" in n.lower()])
        except Exception as exc:                            # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"[:200]
        out[r["id"]] = rec
    conn.close()
    pathlib.Path(out_path).write_text(json.dumps(out, indent=1, sort_keys=True, default=str))
    print(f"{len(out)} assets written to {out_path}")


if __name__ == "__main__":
    main(sys.argv[2])
