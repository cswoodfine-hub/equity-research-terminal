"""The products the book refused to value, and what would make it value them.

A refusal is written as a seed file with a comment block and no rows: the engine finds
nothing to build, and the next person finds the reasoning where they would have looked
for the numbers. Nine of them carry a line beginning "What would settle it", which is a
dated, falsifiable condition: Crenessity's FY2026 full year, Neuraceq's first comparable
half, Datroway's first full year. Each is a moment the book is forced to reprice.

This reads them into a calendar. The trigger is kept verbatim, because the condition is
the analyst's and paraphrasing it would change it. A date is attached only where the
trigger names a reporting year, and then it is the window that year's annual report is
filed in rather than a day: "FY2026" means February or March 2027 for a December
year-end filer, and the view says "filing window" rather than printing a date it does
not hold.

A refusal with no settling condition, which is a divestiture, is listed and not dated:
nothing will make the book value a product the company sold.
"""

from __future__ import annotations

import pathlib
import re

SEEDS = pathlib.Path(__file__).resolve().parent.parent / "data" / "assumptions"

TITLE = re.compile(r"^#\s*(?P<brand>.+?)\s*\((?P<ticker>[A-Z0-9.]+)\)\.\s*(?P<rest>.*)$")
MARK = re.compile(r"\b(NOT YET VALUABLE|NOT VALUABLE|DIVESTED)\b[:.]?\s*(?P<why>.*)")
SETTLE = re.compile(r"(?i)what would settle it:\s*(?P<text>.*)")
FY = re.compile(r"\bFY(20\d\d)\b|\b(20\d\d)\s+(?:full year|10-K|figure)\b")


def _comment_block(path: pathlib.Path) -> list[str]:
    return [l.rstrip("\n") for l in path.read_text(encoding="utf-8").splitlines()
            if l.startswith("#")]


def is_refusal(path: pathlib.Path) -> bool:
    """A seed with a header and no rows is a refusal; one with rows is a model."""
    rows = [l for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]
    return len(rows) <= 1


def filing_window(year: int) -> dict:
    """When a December year-end filer's annual report for ``year`` lands."""
    return {"year": year, "from": f"{year + 1}-02-01", "to": f"{year + 1}-03-31",
            "basis": f"the FY{year} annual report, filed in the first quarter of {year + 1}"}


def parse(path: pathlib.Path) -> dict | None:
    lines = _comment_block(path)
    if not lines:
        return None
    head = TITLE.match(lines[0])
    if not head:
        return None
    mark = MARK.search(" ".join(lines[:3]))
    if not mark:
        return None
    # The reason runs to the end of its sentence, which may wrap onto the next line.
    why = mark.group("why").strip()
    if why and not why.endswith("."):
        for nxt in lines[1:3]:
            why += " " + nxt.lstrip("# ").strip()
            if why.endswith("."):
                break
    settle = None
    for i, line in enumerate(lines):
        m = SETTLE.search(line)
        if m:
            text = m.group("text").strip()
            for nxt in lines[i + 1:i + 4]:          # the sentence may wrap
                body = nxt.lstrip("# ").strip()
                if not body or SETTLE.search(nxt):
                    break
                text += " " + body
                if body.endswith("."):
                    break
            settle = text.strip()
            break
    # The first year the trigger names is the trigger's. A sentence that goes on to
    # explain what is computable today can mention an earlier year, and Neuraceq's did:
    # "the FY2026 10-K ... being the $51.4mm of FY2025", and the earliest of those is
    # not the settling condition.
    years = [int(a or b) for a, b in FY.findall(settle or "")]
    return {"file": path.name, "ticker": head.group("ticker"), "brand": head.group("brand"),
            "kind": mark.group(1).lower(), "why": why.rstrip("."),
            "settles": settle.rstrip(".") if settle else None,
            "window": filing_window(years[0]) if years else None}


def build(directory=None) -> dict:
    root = pathlib.Path(directory) if directory else SEEDS
    rows = []
    for path in sorted(root.glob("*.csv")):
        if not is_refusal(path):
            continue
        got = parse(path)
        if got:
            rows.append(got)
    rows.sort(key=lambda r: ((r["window"] or {}).get("from") or "9999", r["ticker"]))
    return {"rows": rows,
            "totals": {"refusals": len(rows),
                       "dated": sum(1 for r in rows if r["window"]),
                       "undated": sum(1 for r in rows if not r["window"] and r["settles"]),
                       "never": sum(1 for r in rows if not r["settles"])}}
