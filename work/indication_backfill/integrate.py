"""Move verified draft seeds into the book, and say what moved.

Deliberately two steps away from the agents. A draft lands in work/.../drafts/, the
verifier passes it, a person reads a sample, and only then does this copy it into
data/assumptions/ where load_seeds will read it. Nothing an agent writes reaches the
book without passing through here.

Refuses to copy a file the verifier rejects, so --load cannot be used to skip the gate.

  python3 work/indication_backfill/integrate.py              # dry run, says what would move
  python3 work/indication_backfill/integrate.py --load       # copy, load, and report
"""
from __future__ import annotations
import shutil, sqlite3, sys, pathlib

sys.path.insert(0, "backend")
import db, assumptions, indication_layer, forecast              # noqa: E402
import verify_seeds as V                                        # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
DRAFTS = HERE / "drafts"
SEEDS = pathlib.Path("data/assumptions")


def main(load: bool) -> int:
    conn = db.get_connection(); conn.row_factory = sqlite3.Row
    files = sorted(DRAFTS.glob("*.csv"))
    if not files:
        print("no drafts"); return 0
    ok, bad = [], []
    for path in files:
        fails = V.check(path, conn)
        (ok if not fails else bad).append((path, fails))
    print(f"{len(ok)} of {len(files)} draft files pass the verifier\n")
    for path, fails in bad:
        print(f"REJECTED {path.name}")
        for line in fails[:6]:
            print(f"    {line}")
        if len(fails) > 6:
            print(f"    ... and {len(fails) - 6} more")
    if not ok:
        return 1
    print("\nwould copy:" if not load else "\ncopying:")
    for path, _ in ok:
        print(f"    {path.name} -> {SEEDS / path.name}")
        if load:
            shutil.copy2(path, SEEDS / path.name)
    if not load:
        print("\ndry run. Re-run with --load to copy and seed.")
        return 0

    before = conn.execute("SELECT COUNT(*) FROM assumptions").fetchone()[0]
    got = assumptions.load_seeds(conn)
    after = conn.execute("SELECT COUNT(*) FROM assumptions").fetchone()[0]
    print(f"\nload_seeds: {got}   assumption rows {before} -> {after}")

    # What actually became priceable, which is the only number that matters.
    import json
    units = json.loads((HERE / "worklist.json").read_text())["units"]
    built = 0
    for u in units:
        b = indication_layer.build(conn, u["asset_id"], u["indication_id"])
        if b and b.get("ok"):
            built += 1
    print(f"layers indication_layer will now price: {built} of {len(units)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--load" in sys.argv))
