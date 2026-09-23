"""How many people have a disease, held once for the disease rather than once per drug.

Prevalence is a fact about a disease and it was being written on each asset separately.
The copies drifted: four assets carried multiple myeloma at 36,110 and a fifth at 36,000,
two carried follicular lymphoma at 13,619 and 13,960. Two drugs cannot honestly disagree
about how many people have a disease, and the difference is not a rounding: it is one of
them being wrong.

So the figure lives in data/epidemiology.csv, one row per disease, and an asset takes it
unless it says otherwise. An asset's own row still wins, because an analyst may have a
reason to model a narrower population than the disease carries, in the same way a stated
probability beats the published table. What this removes is the accidental disagreement,
not the deliberate one.

It also unblocks assets that could not be modelled at all. Seventy-nine diseases with two
or more unmodelled late-stage assets had no prevalence anywhere in the book, and an asset
whose disease has no pool cannot be built. The twenty-two diseases here are the ones that
block the most.

WHAT IT DOES NOT DO. It does not decide who is treatable. Almost none of these counts is
the population a drug is sold to: 86.3mm Americans have fatty liver disease and the label
pool is the 6.7mm with moderate fibrosis. That funnel is ``eligible_pct`` on the asset,
where an analyst can see and argue with it, and this module deliberately leaves it alone.
"""

from __future__ import annotations

import csv
import pathlib

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "epidemiology.csv"

_CACHE: dict = {}


def clear_cache() -> None:
    _CACHE.clear()


def load(path=None) -> dict:
    """{indication name: {prevalence, incidence, source, note}}.

    A blank prevalence stays None rather than becoming zero. Six diseases in the file
    carry one, because no free citable US count exists for them, and a zero would read
    as a disease nobody has.
    """
    source = pathlib.Path(path) if path else DATA
    key = str(source)
    if key in _CACHE:
        return _CACHE[key]
    out: dict = {}
    if source.exists():
        with source.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(line for line in handle
                                      if not line.lstrip().startswith("#")):
                name = (row.get("indication") or "").strip()
                if not name:
                    continue

                def number(field):
                    raw = (row.get(field) or "").strip()
                    try:
                        return float(raw) if raw else None
                    except ValueError:
                        return None

                out[name] = {"prevalence": number("prevalence"),
                             "incidence": number("incidence"),
                             "source": (row.get("source") or "").strip(),
                             "note": (row.get("note") or "").strip()}
    _CACHE[key] = out
    return out


def for_indication(name: str, path=None) -> dict | None:
    """One disease's row, or None where the file does not carry it."""
    return load(path).get((name or "").strip())
