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
import csv, shutil, sqlite3, sys, pathlib

sys.path.insert(0, "backend")
import db, assumptions, indication_layer, forecast              # noqa: E402
import verify_seeds as V                                        # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
DRAFTS = HERE / "drafts"
SEEDS = pathlib.Path("data/assumptions")


def _rows(text):
    """The header line and the data lines, comments dropped. Line-based on purpose:
    round-tripping through csv rewrites every row, and one ragged row in a file nobody
    meant to touch is enough to lose it."""
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    return (lines[0], lines[1:]) if lines else ("", [])


def _key(header, line):
    row = dict(zip(next(csv.reader([header])), next(csv.reader([line]))))
    return tuple((row.get(f) or "").strip() for f in
                 ("ticker", "brand", "indication", "region", "scenario", "key", "year"))


def _write(draft: pathlib.Path, dst: pathlib.Path) -> None:
    """Append a draft's new rows to the seed file, or create it where there is none.

    Never a copy. A draft is named after its asset, so a layer file for a product the
    book already models lands on the existing seed -- and copying replaced 52 of them,
    throwing away the cost stack, the discount rate and the revenue anchor that made
    those products valuable. The database survived it, because load_seeds is
    insert-only and the rows were already there; the files did not, and a rebuild from
    seed would have lost every one.

    Rows already present by natural key are skipped, so running this twice adds nothing.
    """
    if not dst.exists():
        shutil.copy2(draft, dst)
        return
    old_header, old_rows = _rows(dst.read_text())
    new_header, new_rows = _rows(draft.read_text())
    if next(csv.reader([old_header])) != next(csv.reader([new_header])):
        raise SystemExit(f"{dst.name}: the seed file's columns differ from the draft's; "
                         f"refusing to append rather than guess the mapping")
    have = {_key(old_header, l) for l in old_rows}
    extra = [l for l in new_rows if _key(new_header, l) not in have]
    if not extra:
        return
    with dst.open("a") as fh:
        fh.write("\n# Indication layers, appended by work/indication_backfill.\n")
        fh.write("\n".join(extra) + "\n")


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
    print("\nwould write:" if not load else "\nwriting:")
    for path, _ in ok:
        dst = SEEDS / path.name
        verb = "append to" if dst.exists() else "create"
        print(f"    {verb} {dst}")
        if load:
            _write(path, dst)
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
