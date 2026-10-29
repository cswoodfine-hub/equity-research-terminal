"""Every modelled marketed product's LOE date, basis, identifier and NPV, as JSON.

Run before and after a change to the LOE rule and diff the two files with
``delta.py``. Reads the database ``ER_TOOL_DB`` names; run it on a copy, never the book.

    ER_TOOL_DB=<copy> python3 work/patents/tools/baseline.py out.json
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import assumptions  # noqa: E402
import db  # noqa: E402
import forecast  # noqa: E402
import loe  # noqa: E402


def main(out_path):
    conn = db.get_connection()
    ids = [r["id"] for r in conn.execute(
        "SELECT DISTINCT a.id FROM assets a JOIN assumptions s ON s.asset_id = a.id"
        " WHERE a.is_marketed = 1")]
    resolved = loe.for_assets(conn, ids, exclude_orphan=True)
    names = {r["id"]: (r["ticker"], r["nm"]) for r in conn.execute(
        "SELECT a.id, c.ticker, COALESCE(a.brand_name, a.generic_name) AS nm"
        " FROM assets a JOIN companies c ON c.id = a.owner_company_id")}
    out = {}
    for asset_id in ids:
        found = resolved.get(asset_id) or {}
        npv = peak = None
        try:
            built = forecast.build(assumptions.load(conn, asset_id, "base"))
            npv = built.get("npv")
            path = [v for v in (built.get("revenue") or []) if v is not None]
            peak = max(path) if path else None
        except Exception as exc:                           # noqa: BLE001
            npv = f"error: {type(exc).__name__}"
        ticker, name = names.get(asset_id, (None, None))
        out[asset_id] = {"ticker": ticker, "name": name, "date": found.get("date"),
                         "basis": found.get("basis"),
                         "identifier": found.get("identifier"),
                         "past": found.get("past"), "npv": npv, "peak": peak}
    conn.close()
    pathlib.Path(out_path).write_text(json.dumps(out, indent=1, sort_keys=True))
    print(f"{len(out)} products written to {out_path}")


if __name__ == "__main__":
    main(sys.argv[1])
