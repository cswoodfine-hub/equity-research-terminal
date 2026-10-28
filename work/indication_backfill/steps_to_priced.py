"""What stands between each unpriced catalyst and a price, and who it belongs to.

The plan's unit. Counting catalysts by bucket says which problems exist; counting what
each one is still missing says which to work on, because a catalyst needing two things
is worth nothing until both are done and a catalyst needing one is a day's work.

  python3 work/indication_backfill/steps_to_priced.py <nogate.json> [--phase 1a|1b]
"""
from __future__ import annotations
import collections, json, sqlite3, sys

sys.path.insert(0, "backend")
import db, indication_mapping as im, indication_layer, forecast     # noqa: E402
import assumptions as A                                            # noqa: E402

CT = im._CTGOV_URL
LAYER_PHASES = {"Phase 3", "Phase 2/3", "Phase 2"}
SELLING = ("marketed", "franchise", "launch")


def classify(conn, rows) -> list:
    mode = {r["asset_id"]: r["text_value"] for r in conn.execute(
        "SELECT asset_id, text_value FROM assumptions WHERE key='therapy_mode'")}
    out = []
    for r in rows:
        steps, pid, pair = [], r.get("asset_indication_id"), None
        if not pid:
            steps.append("link")
            cat = conn.execute("SELECT source_url FROM catalysts WHERE id=?",
                               (r["id"],)).fetchone()
            url = (cat["source_url"] or "") if cat else ""
            t = (conn.execute("SELECT asset_id FROM trials WHERE nct_id=?",
                              (url[len(CT):],)).fetchone()
                 if url.startswith(CT) else None)
            aid = t["asset_id"] if t else None
        else:
            pair = conn.execute(
                "SELECT asset_id, indication_id, phase FROM asset_indications WHERE id=?",
                (pid,)).fetchone()
            aid = pair["asset_id"] if pair else None
            if pair and (pair["phase"] or "") not in LAYER_PHASES:
                steps.append("phase")
        if aid is None:
            continue
        if mode.get(aid) not in SELLING:
            steps.append("asset model")
        else:
            sc = (A.load(conn, aid, "base") or {}).get("scalars") or {}
            if forecast.net_price(sc) is None or sc.get("discontinuation_pct") is None:
                steps.append("asset price/disc")
            if pair:
                b = indication_layer.build(conn, pair["asset_id"], pair["indication_id"])
                if not (b and b.get("ok")):
                    steps.append("layer seeds")
            else:
                steps.append("layer seeds")
        info = conn.execute(
            "SELECT COALESCE(a.brand_name, a.generic_name) AS brand, c.ticker,"
            "       a.is_marketed FROM assets a"
            "  JOIN companies c ON c.id = a.owner_company_id WHERE a.id=?", (aid,)).fetchone()
        ind = conn.execute("SELECT name FROM indications WHERE id=?",
                           (pair["indication_id"],)).fetchone() if pair else None
        out.append({"catalyst": r["id"], "asset_id": aid, "ticker": info["ticker"],
                    "brand": info["brand"], "is_marketed": info["is_marketed"],
                    "indication": ind["name"] if ind else None,
                    "date": r.get("expected_date"), "steps": steps})
    return out


def main() -> int:
    conn = db.get_connection(); conn.row_factory = sqlite3.Row
    rows = classify(conn, json.load(open(sys.argv[1])))
    want = sys.argv[sys.argv.index("--phase") + 1] if "--phase" in sys.argv else None
    if not want:
        for k, v in collections.Counter(" + ".join(r["steps"]) or "nothing"
                                        for r in rows).most_common():
            print(f"  {v:4d}  {k}")
        return 0
    if want == "1a":
        picked = [r for r in rows if r["steps"] == ["layer seeds"]]
        units = {}
        for r in picked:
            units.setdefault((r["asset_id"], r["indication"]), r)
        print(f"Phase 1a — {len(picked)} catalysts, {len(units)} (asset, indication) units\n")
        for (aid, ind), r in sorted(units.items(), key=lambda kv: (kv[1]["ticker"], kv[1]["brand"])):
            print(f"  {r['ticker']:5} {r['brand'][:26]:<28} {str(ind)[:38]:<40} {r['date']}")
    else:
        picked = [r for r in rows if r["steps"] == ["asset model"]]
        assets = {}
        for r in picked:
            assets.setdefault(r["asset_id"], r)
        mk = [r for r in assets.values() if r["is_marketed"]]
        cl = [r for r in assets.values() if not r["is_marketed"]]
        print(f"Phase 1b — {len(picked)} catalysts, {len(assets)} assets "
              f"({len(mk)} marketed, {len(cl)} clinical-stage)\n")
        for label, group in (("MARKETED", mk), ("CLINICAL-STAGE", cl)):
            print(f"  --- {label} ---")
            for r in sorted(group, key=lambda x: (x["ticker"], x["brand"])):
                print(f"  {r['ticker']:5} {r['brand'][:34]:<36} {r['date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
