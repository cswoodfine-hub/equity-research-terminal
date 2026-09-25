"""Write a researcher's context file for each unvalued asset the sort marks NEW. Usage:
  ctx.py [--phase "Phase 2"] [--phase "Phase 2/3"]      (default: Phase 2 and Phase 2/3)
Reads the book (backend/er_tool.db) and data/pipeline_sort.csv, writes ctx/<TICKER>_<slug>.json
and appends [ticker, name, slug] to index.json. An asset already in index.json is skipped."""
import argparse, json, pathlib, re, sys
sys.path.insert(0, "/home/user/equity-research-terminal/backend")
import db, pipeline_sort

HERE = pathlib.Path(__file__).resolve().parent
RANK = {"Phase 2": 2.0, "Phase 2/3": 2.5, "Phase 3": 3.0}
# Words too common in drug names to say two rows are related.
COMMON = {"vaccine", "injection", "tablet", "tablets", "oral", "placebo", "biological", "combination",
          "product", "therapy", "sodium", "hydrochloride", "extended", "release", "candidate"}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]


def related(conn, asset_id: int, texts: list[str]) -> list[dict]:
    words = {w for t in texts for w in re.findall(r"[a-z0-9]{5,}", (t or "").lower())} - COMMON
    out, seen = [], {asset_id}
    for w in sorted(words):
        for r in conn.execute(
                """SELECT a.id, c.ticker, a.generic_name, a.brand_name, a.internal_code, a.is_marketed,
                          EXISTS (SELECT 1 FROM assumptions s WHERE s.asset_id = a.id) AS modelled
                     FROM assets a JOIN companies c ON c.id = a.owner_company_id
                    WHERE LOWER(COALESCE(a.generic_name,'') || ' ' || COALESCE(a.brand_name,'') || ' '
                                || COALESCE(a.internal_code,'')) LIKE ?""", (f"%{w}%",)):
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            out.append({"id": r["id"], "ticker": r["ticker"], "generic": r["generic_name"],
                        "brand": r["brand_name"], "code": r["internal_code"],
                        "is_marketed": r["is_marketed"], "modelled": bool(r["modelled"])})
    return out[:12]


def build(conn, asset_id: int, ticker: str, name: str, sort_row: dict) -> dict:
    a = conn.execute("""SELECT a.*, c.name AS company FROM assets a JOIN companies c
                         ON c.id = a.owner_company_id WHERE a.id = ?""", (asset_id,)).fetchone()
    inds = [{"name": r["name"], "phase": r["phase"], "development_status": r["development_status"]}
            for r in conn.execute("""SELECT i.name, ai.phase, ai.development_status FROM asset_indications ai
                                      JOIN indications i ON i.id = ai.indication_id WHERE ai.asset_id = ?
                                      ORDER BY ai.phase DESC, i.name""", (asset_id,))]
    trials = [dict(r) for r in conn.execute(
        """SELECT DISTINCT t.nct_id, t.phase, t.overall_status, t.primary_completion_date, t.enrollment,
                  t.last_update_posted, t.lead_sponsor, t.title FROM trials t
            WHERE t.asset_id = ? OR t.nct_id IN (SELECT nct_id FROM trial_asset_map WHERE asset_id = ?)
            ORDER BY t.phase DESC, t.primary_completion_date""", (asset_id, asset_id))]
    aliases = [r[0] for r in conn.execute("SELECT internal_code FROM asset_aliases WHERE asset_id = ?",
                                          (asset_id,))]
    return {"ticker": ticker, "company": a["company"], "name": name,
            "inn_or_identity": "", "sort_evidence": sort_row.get("evidence") or "",
            "approved": sort_row.get("approved") or "", "indications": inds, "trials": trials,
            "aliases": aliases,
            "related_assets_in_book": related(conn, asset_id, [a["generic_name"], a["brand_name"],
                                                               a["internal_code"]])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", action="append")
    args = ap.parse_args()
    phases = set(args.phase or ["Phase 2", "Phase 2/3"])
    conn = db.get_connection()
    sort = pipeline_sort.load()
    index_path = HERE / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else []
    have = {(t, n) for t, n, _ in index}
    (HERE / "ctx").mkdir(exist_ok=True)
    written = 0
    for p in pipeline_sort.population(conn):
        row = sort.get((p["ticker"].upper(), p["name"].lower()))
        if not row or row["class"] != "NEW" or (p["ticker"], p["name"]) in have:
            continue
        best = max((RANK.get(r[0], 0) for r in conn.execute(
            "SELECT phase FROM asset_indications WHERE asset_id = ?", (p["asset_id"],))), default=0)
        if not any(RANK[ph] == best for ph in phases):
            continue
        s = slug(p["name"])
        ctx = build(conn, p["asset_id"], p["ticker"], p["name"], row)
        (HERE / "ctx" / f"{p['ticker']}_{s}.json").write_text(json.dumps(ctx, indent=1, ensure_ascii=False))
        index.append([p["ticker"], p["name"], s])
        written += 1
    index_path.write_text(json.dumps(index, indent=1, ensure_ascii=False))
    print("context files written:", written)


if __name__ == "__main__":
    main()
