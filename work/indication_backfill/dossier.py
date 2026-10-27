"""Everything an agent needs to research one company's indication layers, and nothing
it would have to guess at.

The point is to make fabrication unnecessary before making it detectable. An agent that
is not told the book already holds a prevalence for this disease will go and find one,
and the two will disagree; an agent that is not given the NCT numbers will search for
the trial by name and may find a different one. So the dossier carries the book's own
answer wherever the book has one.

Usage:  python3 work/indication_backfill/dossier.py AZN > /tmp/azn.md
"""
from __future__ import annotations
import json, sys, sqlite3, pathlib, collections

sys.path.insert(0, "backend")
import db, assumptions as A, forecast, indication_layer                # noqa: E402
import brand_components                                                # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
CT = "https://clinicaltrials.gov/study/"


def dossier(conn, ticker: str) -> str:
    units = [u for u in json.loads((HERE / "worklist.json").read_text())["units"]
             if u["ticker"] == ticker and u["status"] in ("todo", "reuse_pool")]
    units.sort(key=lambda u: (-len(u["catalysts"]), u["brand"], u["indication"]))
    out = [f"# {ticker}: {len(units)} indication layers to research", ""]

    by_asset = collections.defaultdict(list)
    for u in units:
        by_asset[(u["asset_id"], u["brand"])].append(u)

    for (asset_id, brand), group in sorted(by_asset.items(), key=lambda kv: kv[0][1]):
        scal = {r["key"]: dict(r) for r in conn.execute(
            "SELECT key, value, text_value, unit, source FROM assumptions"
            " WHERE asset_id=? AND indication_id IS NULL", (asset_id,))}
        rev = scal.get("base_revenue") or scal.get("franchise_revenue")
        mode = (scal.get("therapy_mode") or {}).get("text_value") or "?"
        out.append(f"## {brand}  (asset_id {asset_id})")
        out.append(f"- mode **{mode}**, "
                   f"revenue anchor {rev['value']:,.0f}mm USD" if rev else f"- mode **{mode}**")
        # What the engine itself says is missing at asset level. These block every
        # layer on the product at once, so they are worth more than any single pool:
        # 73 assets lack a price and all 182 open units lack a discontinuation rate.
        loaded = A.load(conn, asset_id, "base")
        gaps = []
        if loaded and loaded.get("scalars"):
            sc = loaded["scalars"]
            gaps = [k for k in indication_layer.ASSET_KEYS if sc.get(k) is None]
            if forecast.net_price(sc) is None:
                gaps.append("net_price_per_patient")
        price = scal.get("list_price_per_patient") or scal.get("net_price_per_patient")
        if price:
            out.append(f"- price on file: `{price['key']}` = {price['value']} "
                       f"{price['unit'] or ''} — {(price['source'] or '')[:120]}")
        # The CMS series, reached through the brand's components where the reported
        # line names several products. A Wave 1 agent concluded Nurtec had no demand
        # data and wrote a placeholder price, because rimegepant's Part D series is
        # filed against the single-brand row while the model sits on the combined one.
        demand = brand_components.demand_rows(conn, asset_id)
        if demand:
            latest = {}
            for d in demand:
                latest[d["part"]] = max(latest.get(d["part"], (0,))[0], d["year"]), d
            for part, (_, d) in sorted(latest.items()):
                if d["total_beneficiaries"]:
                    per = d["total_spending"] / d["total_beneficiaries"]
                    out.append(
                        f"- **CMS Part {part} {d['year']}** ({d['brand_name']}): "
                        f"${d['total_spending']:,.0f} over {d['total_beneficiaries']:,} "
                        f"beneficiaries = **${per:,.0f} per beneficiary a year**. This "
                        f"is the basis the book prices on — see amgn_abp_206.csv.")
        if gaps:
            out.append(f"- **blocked at asset level on {', '.join(gaps)}.** Every layer "
                       f"below needs these, so find them once for the product:")
            if "net_price_per_patient" in gaps:
                out.append("    - `list_price_per_patient` in mm USD a year, from the "
                           "manufacturer's own WAC disclosure or a state price "
                           "transparency filing, with the dose and schedule you "
                           "multiplied shown in the source; plus `gross_to_net_pct`.")
            if "discontinuation_pct" in gaps:
                out.append("    - `discontinuation_pct`, the share of the patient stock "
                           "stopping each year. Derive it from a published median "
                           "duration of response, progression-free survival or "
                           "persistence, and say which and from where.")
        out.append("")
        for u in group:
            out.append(f"### {u['indication']}   [{u['phase']}, {u['dev_status']}]")
            out.append(f"- unit key `{u['key']}`, therapeutic area {u['area']}")
            pool = conn.execute(
                "SELECT a.key, a.value, a.unit, a.source FROM assumptions a"
                "  WHERE a.indication_id=? AND a.key IN ('prevalence','incidence')"
                "    AND a.value IS NOT NULL AND a.source IS NOT NULL"
                "  ORDER BY a.key", (u["indication_id"],)).fetchall()
            if pool:
                out.append("- **the book already holds this pool — reuse it verbatim, "
                           "do not research a second figure:**")
                for key in sorted({p["key"] for p in pool}):
                    p = next(x for x in pool if x["key"] == key)
                    out.append(f"    - `{p['key']}` = {p['value']:,.0f} {p['unit'] or ''}")
                    out.append(f"      source: {p['source']}")
            else:
                out.append("- the book holds no pool for this disease; it has to be "
                           "researched and sourced")
            # The trial's own asset pointer is the live one; trial_asset_map is the
            # curated override beside it. Both, because a readout that reaches the
            # asset only through the override is still the asset's.
            trials = conn.execute(
                "SELECT DISTINCT t.nct_id, t.phase, t.overall_status, t.enrollment,"
                "       t.primary_completion_date, t.title, t.conditions FROM trials t"
                "  LEFT JOIN trial_asset_map m ON m.nct_id = t.nct_id"
                " WHERE t.asset_id = ? OR m.asset_id = ?"
                " ORDER BY t.primary_completion_date", (asset_id, asset_id)).fetchall()
            mine = [t for t in trials
                    if _mentions(conn, t["nct_id"], u["indication_id"])]
            for t in mine[:6]:
                out.append(f"- trial {t['nct_id']}  {t['phase']}, {t['overall_status']}, "
                           f"n={t['enrollment']}, primary completion "
                           f"{t['primary_completion_date']}")
                out.append(f"    {(t['title'] or '')[:150]}")
            for c in u["catalysts"]:
                out.append(f"- **pending catalyst** {c['expected_date']} "
                           f"({c['catalyst_type']}): {(c['title'] or '')[:110]}")
            out.append("")
    return "\n".join(out)


def _has(conn, table) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone())


def _mentions(conn, nct, indication_id) -> bool:
    row = conn.execute(
        "SELECT 1 FROM trials t WHERE t.nct_id=? AND ("
        "  EXISTS (SELECT 1 FROM indications i WHERE i.id=? AND ("
        "     LOWER(t.conditions) LIKE '%'||LOWER(i.name)||'%'"
        "     OR LOWER(COALESCE(t.mesh_terms,'')) LIKE '%'||LOWER(i.name)||'%')))",
        (nct, indication_id)).fetchone()
    return bool(row)


if __name__ == "__main__":
    conn = db.get_connection(); conn.row_factory = sqlite3.Row
    print(dossier(conn, sys.argv[1].upper()))
