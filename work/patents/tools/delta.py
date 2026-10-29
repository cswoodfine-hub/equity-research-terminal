"""Compare two ``baseline.py`` files: which products' LOE moved, why, and the NPV change.

    python3 work/patents/tools/delta.py before.json after.json [--md out.md]
"""

import json
import sys


def main(before_path, after_path, md_path=None):
    before = json.load(open(before_path))
    after = json.load(open(after_path))
    moved = []
    for key, new in after.items():
        old = before.get(key) or {}
        if (old.get("date"), old.get("basis")) == (new.get("date"), new.get("basis")):
            continue
        npv0, npv1 = old.get("npv"), new.get("npv")
        change = (npv1 - npv0 if isinstance(npv0, (int, float))
                  and isinstance(npv1, (int, float)) else None)
        moved.append((new["ticker"], new["name"], old.get("date"), old.get("basis"),
                      new.get("date"), new.get("basis"), npv0, npv1, change))
    moved.sort(key=lambda m: -(abs(m[8]) if m[8] is not None else 0))
    lines = ["| ticker | product | LOE before | basis before | LOE after | basis after |"
             " NPV before | NPV after | change |", "|---|---|---|---|---|---|---|---|---|"]

    def num(v):
        return f"{v:,.0f}" if isinstance(v, (int, float)) else (v or "")

    for m in moved:
        lines.append("| " + " | ".join([m[0] or "", m[1] or "", m[2] or "", m[3] or "",
                                        m[4] or "", m[5] or "", num(m[6]), num(m[7]),
                                        num(m[8])]) + " |")
    total = sum(m[8] for m in moved if m[8] is not None)
    head = (f"{len(moved)} of {len(after)} products moved; NPV change across them "
            f"{total:,.0f}mm.")
    text = head + "\n\n" + "\n".join(lines) + "\n"
    if md_path:
        open(md_path, "w").write(text)
    print(head)
    print("\n".join(lines[:60]))


if __name__ == "__main__":
    args = sys.argv[1:]
    md = None
    if "--md" in args:
        md = args[args.index("--md") + 1]
        args = args[:args.index("--md")]
    main(*args, md_path=md)
