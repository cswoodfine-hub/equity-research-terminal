"""Risks the model treats as independent that are not.

Every product and every probability of success is valued on its own, which is right for
the arithmetic and wrong for the downside. Two obesity agents from two companies are
covered or not by one payer decision; two PD-1 x VEGF bispecifics live or die on one
biology; two Lp(a) drugs wait on the same outcomes question; every product selected for
Medicare price negotiation takes a government-set price in the same programme. A book
that holds several of them has one risk, not several.

``data/risk_groups.csv`` names the groups, each member with its source and quote. This
module reads the file and matches its members to what a company carries, products by
brand or generic name and company lines by name. Valuing a group, its exposure and, for
a mechanism group, the company's value with every pipeline member failed together, is done
by the break-points (breakpoints.py), which hold the book the arithmetic needs. The joint
case is a stress, not a probability.
"""

from __future__ import annotations

import csv
import pathlib

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "risk_groups.csv"
KINDS = ("mechanism", "payer")


def load(path=None) -> list[dict]:
    source = pathlib.Path(path) if path else DATA
    if not source.exists():
        return []
    with source.open(newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(line for line in handle if not line.lstrip().startswith("#"))
        return [r for r in rows if (r.get("group") or "").strip()
                and (r.get("kind") or "").strip() in KINDS]


def _key(text) -> str:
    return (text or "").strip().lower()


def for_company(ticker: str, parts: list, path=None) -> list[dict]:
    """The groups this company holds a member of: {"group", "kind", "members": [part],
    "elsewhere": [tickers], "sources": [...]}. ``parts`` are the verdict's counted products
    (with "name") and lines (with "line")."""
    rows = load(path)
    by_name = {}
    for part in parts:
        name = part.get("name") or part.get("line")
        if name:
            by_name.setdefault(_key(name), part)
    out: dict = {}
    for row in rows:
        group = row["group"].strip()
        entry = out.setdefault(group, {"group": group, "kind": row["kind"].strip(),
                                       "members": [], "elsewhere": set(), "sources": []})
        if row["ticker"].strip().upper() != ticker.upper():
            entry["elsewhere"].add(row["ticker"].strip().upper())
            continue
        part = by_name.get(_key(row["member"]))
        if part is None:
            continue
        if part not in entry["members"]:
            entry["members"].append(part)
            entry["sources"].append({"member": row["member"].strip(),
                                     "source": row.get("source"), "quote": row.get("quote"),
                                     "note": row.get("note")})
    return [{**g, "elsewhere": sorted(g["elsewhere"])} for g in out.values()
            if g["members"]]
