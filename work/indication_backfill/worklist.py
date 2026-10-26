"""Build the indication-layer worklist, and keep it current without losing state.

The unit of work is one (asset, indication): the layer an unapproved indication adds to
a product that already sells something else. Each unit carries a status that a later run
must not clobber, so this merges onto whatever worklist.json already holds rather than
rewriting it. Re-running after new catalysts arrive adds the new units and refreshes the
facts on the old ones, leaving every decision in place.

Statuses:
  todo        nothing done yet
  parked      too early to price (Phase 1, Phase 1/2) — the engine refuses these anyway
  reuse_pool  the disease's pool is already sourced in the book; copy it, do not research
  researched  an agent has produced draft rows; awaiting the verifier
  verified    the verifier passed it
  seeded      written to a CSV under data/assumptions and loaded
  nil         deliberately worth nothing (overlap 1.0, or a failed programme)
  blocked     cannot be sourced; the reason says why
"""
from __future__ import annotations
import json, sys, sqlite3, collections, pathlib

sys.path.insert(0, "backend")
import db, approved_indications, indication_mapping                  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "worklist.json"
LAYER_PHASES = {"Phase 3", "Phase 2/3", "Phase 2"}
PARK_PHASES = {"Phase 1", "Phase 1/2"}
SELLING = ("marketed", "franchise", "launch")
# The keys that mean somebody has already priced this layer.
LAYER_KEYS = {"base_pool_overlap_pct", "pos", "penetration_peak_pct",
              "prevalence", "incidence", "eligible_pct"}

# Words a MeSH descriptor carries that a label expresses differently or leaves implicit.
# MeSH writes "Carcinoma, Non-Small-Cell Lung"; the label writes "non-small cell lung
# cancer". MeSH writes "Leukemia, Lymphocytic, Chronic, B-Cell"; the label writes
# "chronic lymphocytic leukemia", because in CLL the B-cell lineage goes without saying.
# approved_indications tests the descriptor's tokens as a subset of the label's, so both
# read as unapproved on an asset that has sold them for years -- Calquence in CLL since
# 2019, Alecensa and Enhertu and Krazati and Rybrevant in NSCLC.
#
# These are not auto-decided here. Dropping the words and matching anyway would be a
# guess, and the failure mode is silent: a layer on an approved indication builds the
# existing business a second time underneath revenue that already contains it. So the
# unit is flagged for someone to read the actual label, which is a question an agent
# with an FDA label in front of it answers in one step.
_IMPLIED = {"carcinoma", "neoplasms", "neoplasm", "b", "cell", "disease", "diseases",
            "syndrome"}


def build(conn) -> dict:
    mode = {r["asset_id"]: r["text_value"] for r in conn.execute(
        "SELECT asset_id, text_value FROM assumptions WHERE key='therapy_mode'")}
    selling = [a for a, m in mode.items() if m in SELLING]

    revenue = {r["asset_id"]: r["value"] for r in conn.execute(
        "SELECT asset_id, value FROM assumptions WHERE indication_id IS NULL"
        "   AND key IN ('base_revenue','franchise_revenue') AND value > 0")}

    seeded = collections.defaultdict(set)
    for r in conn.execute("SELECT asset_id, indication_id, key FROM assumptions"
                          " WHERE indication_id IS NOT NULL"):
        seeded[(r["asset_id"], r["indication_id"])].add(r["key"])

    pool_known = {}
    for r in conn.execute(
            "SELECT indication_id, key, value, source FROM assumptions"
            " WHERE indication_id IS NOT NULL AND key IN ('prevalence','incidence')"
            "   AND value IS NOT NULL AND source IS NOT NULL"):
        pool_known.setdefault(r["indication_id"], {}).setdefault(r["key"],
                                                                 (r["value"], r["source"]))

    cats = collections.defaultdict(list)
    for r in conn.execute(
            "SELECT id, asset_indication_id, expected_date, catalyst_type, title"
            "  FROM catalysts WHERE asset_indication_id IS NOT NULL AND status='pending'"):
        cats[r["asset_indication_id"]].append(dict(r))

    units = {}
    for aid in selling:
        approved = approved_indications.for_asset(conn, aid)
        for r in conn.execute(
                "SELECT ai.id pair_id, ai.indication_id, ai.phase, ai.development_status,"
                "       i.name iname, i.therapeutic_area ta, a.brand_name, a.generic_name,"
                "       a.internal_code, c.ticker FROM asset_indications ai"
                "  JOIN indications i ON i.id=ai.indication_id"
                "  JOIN assets a ON a.id=ai.asset_id"
                "  JOIN companies c ON c.id=a.owner_company_id"
                " WHERE ai.asset_id=?", (aid,)):
            if r["pair_id"] in approved or (r["phase"] or "") in ("Approved", "Phase 4"):
                continue
            if (r["phase"] or "") not in LAYER_PHASES | PARK_PHASES:
                continue
            key = f"{aid}:{r['indication_id']}"
            has = seeded.get((aid, r["indication_id"]), set())
            units[key] = {
                "key": key, "asset_id": aid, "indication_id": r["indication_id"],
                "ticker": r["ticker"], "mode": mode[aid],
                "brand": r["brand_name"] or r["generic_name"] or r["internal_code"],
                "indication": r["iname"], "area": r["ta"], "phase": r["phase"],
                "dev_status": r["development_status"],
                "already_seeded": sorted(has & LAYER_KEYS),
                "label_known": bool((approved_indications.current_label(conn, aid)
                                     or "").strip()),
                # Revenue is what makes a missing label dangerous. A product with
                # sales must be approved in something, so no label means the book
                # cannot tell an expansion from the business it already has. An asset
                # with no sales is approved in nothing, and every indication on it is
                # genuinely unapproved -- ceralasertib and monalizumab are that case.
                "revenue": bool(revenue.get(aid)),
                "maybe_approved": maybe_approved(conn, aid, r["iname"]),
                "pool_in_book": pool_known.get(r["indication_id"]) is not None,
                "catalysts": cats.get(r["pair_id"], []),
            }
    return units


def maybe_approved(conn, asset_id: int, name: str) -> list:
    """The descriptor's words the label does not literally contain, when every other
    word of it is there. Empty means no suspicion."""
    text = approved_indications.current_label(conn, asset_id) or ""
    if not text:
        return []
    said = set(indication_mapping.tokens(text))
    mine = set(indication_mapping.tokens(name))
    if not mine or mine <= said:
        return []
    missing = mine - said
    return sorted(missing) if missing and missing <= _IMPLIED else []


def initial_status(u: dict) -> tuple:
    # An asset with no label text cannot be asked what it is already approved for.
    # approved_indications.for_asset then has only the Phase 4 test left, so every
    # indication on the product reads as unapproved -- including the ones it has sold
    # for years. Tezspire is the proof: the book holds no label for it, and its four
    # "unapproved" units include Asthma, which it was approved in on 2021-12-17, and
    # Rhinosinusitis, approved 2025-10-17. A layer seeded on either would build the
    # existing business a second time underneath the revenue that already contains it.
    #
    # So these are held back rather than researched. The fix is a label, not a pool.
    if not u["label_known"] and u["revenue"]:
        return "blocked_no_label", ("the book holds no label text for this asset, so "
                                    "it cannot say what the product is already "
                                    "approved for; fetch the label before pricing a "
                                    "layer here")
    if u["maybe_approved"]:
        return "check_already_approved", (
            "the label names this disease except for "
            f"{', '.join(u['maybe_approved'])}, which MeSH spells out and a label "
            "usually does not. Read the label before pricing a layer: if the product "
            "is already approved here, the revenue already contains it")
    if u["already_seeded"]:
        return "seeded", "carries layer rows already"
    if u["phase"] in PARK_PHASES:
        return "parked", (f"{u['phase']} is outside the layer gate the engine prices "
                          "(forecast_view._LAYER_GATE_PHASES), so a pool here buys "
                          "nothing until it advances")
    if u["pool_in_book"]:
        return "reuse_pool", "the disease's pool is already sourced in the book"
    return "todo", ""


def main():
    conn = db.get_connection(); conn.row_factory = sqlite3.Row
    fresh = build(conn)
    old = {}
    if OUT.exists():
        old = {u["key"]: u for u in json.loads(OUT.read_text())["units"]}
    out = []
    for key, u in sorted(fresh.items()):
        prev = old.get(key)
        if prev:
            u["status"] = prev["status"]
            u["note"] = prev.get("note", "")
            u["wave"] = prev.get("wave")
            # A merge keeps decisions, but a unit nobody has started yet is not a
            # decision. Re-deciding those lets a guard added later actually reach the
            # rows it was written for, which is how blocked_no_label found Tezspire's
            # Asthma row after the worklist had already been built once.
            if u["status"] in ("todo", "reuse_pool", "blocked_no_label",
                               "check_already_approved"):
                u["status"], u["note"] = initial_status(u)
        else:
            u["status"], u["note"] = initial_status(u)
            u["wave"] = None
        u["priority"] = len(u["catalysts"])
        out.append(u)
    OUT.write_text(json.dumps({"units": out}, indent=1))
    c = collections.Counter(u["status"] for u in out)
    print(f"units: {len(out)}")
    for k, v in c.most_common():
        print(f"  {v:4d}  {k}")
    live = [u for u in out if u["status"] in ("todo", "reuse_pool")]
    print(f"\nopen units with a pending catalyst: "
          f"{sum(1 for u in live if u['catalysts'])}")
    print("open by ticker:",
          dict(collections.Counter(u["ticker"] for u in live).most_common()))


if __name__ == "__main__":
    main()
