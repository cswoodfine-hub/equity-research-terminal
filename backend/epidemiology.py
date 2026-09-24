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

THE NAME HAS TO MATCH, WHICH IS WHY ALIASES EXIST. The lookup was exact, and the registry
names one disease several ways. The book holds three separate multiple sclerosis
indications: "Multiple Sclerosis" with 19 asset rows, which the file filled, and
"Multiple Sclerosis, Relapsing-Remitting" with 8 and "Multiple Sclerosis, Chronic
Progressive" with 10, which it did not. Those 18 assets could not be built for want of a
population that was already on file under a slightly different string.

An alias is only written where the population really is the same disease and the variant is
a clinical subtype of it or another name for it, because that is what this file already
assumes everywhere: it carries the disease and ``eligible_pct`` on the asset narrows it to
the label. Relapsing multiple sclerosis is a share of the 913,925 who have multiple
sclerosis, and the share belongs on the asset where it can be argued with.

An alias is NOT written where the variant is a different population, however close the
names look, and those are left to fail the lookup rather than be filled with a figure that
is not theirs. Smouldering multiple myeloma is a precursor state and not part of the
prevalent myeloma count. "Diabetes Mellitus" spans type 1 and type 2 and the file carries
type 2 alone. "Arthritis" is not rheumatoid arthritis, "Osteoarthritis" is not knee
osteoarthritis, "Nephritis" is not lupus nephritis, and "Intestinal Neoplasms" is not the
whole gastrointestinal tract. Nine near-misses were checked and four were refused.
"""

from __future__ import annotations

import csv
import pathlib

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "epidemiology.csv"

_CACHE: dict = {}

# {indication as the registry names it: the disease in the file whose population it shares}.
# Each one is a clinical subtype of the disease or another name for it, so the file's count
# is the right pool and the asset's own eligible_pct carries the narrowing. Checked one at a
# time; see the note above for the four near-misses deliberately left out.
ALIASES = {
    # Subtypes of the 913,925 in Wallin's national estimate, which counts relapsing and
    # progressive forms together. 18 asset rows between them.
    "Multiple Sclerosis, Relapsing-Remitting": "Multiple Sclerosis",
    "Multiple Sclerosis, Chronic Progressive": "Multiple Sclerosis",
    # The file's "Renal Insufficiency" row IS chronic kidney disease: 37mm US adults from
    # the CDC Chronic Kidney Disease Surveillance System. The same disease, named twice.
    "Renal Insufficiency, Chronic": "Renal Insufficiency",
    # The three assets on this row are all MASH programmes: GSK4532990 against HSD17B13,
    # tirzepatide's MASH line and ALN-PNP against PNPLA3.
    "Fatty Liver": "Non-alcoholic Fatty Liver Disease",
    # Reduced and preserved ejection fraction, both inside the 7.4mm with heart failure.
    "Heart Failure, Systolic": "Heart Failure",
    "Heart Failure, Diastolic": "Heart Failure",
}


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
    """One disease's row, or None where the file does not carry it.

    An exact name first, then the curated aliases, so a clinical subtype takes the
    disease's population and nothing else does. The row that comes back says which name
    answered, because an analyst reading a pool of 913,925 against an asset in progressive
    multiple sclerosis needs to know it is the whole disease and that the narrowing is
    theirs to set.
    """
    diseases = load(path)
    key = (name or "").strip()
    if key in diseases:
        return diseases[key]
    disease = ALIASES.get(key)
    if disease is None or disease not in diseases:
        return None
    row = dict(diseases[disease])
    row["via"] = disease
    row["note"] = (
        f"{key} takes the population of {disease}, of which it is a clinical subtype or "
        f"another name, so eligible_pct on the asset carries the narrowing. "
        + (row["note"] or "")).strip()
    return row
