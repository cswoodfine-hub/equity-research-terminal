"""A filed growth rate is faded by the length measured for its own band, and a rate
above 100% a year is bounded by a published peak.

The re-strike of 2026-11-27 moved 136 rates onto the third quarter and left each
product's growth_fade_years as it was. Fifteen rates had crossed into another band of
data/growth_analogues.csv, so each was fading over a length measured on different drugs,
and two (Uplizna +129%, Imdelltra +117%) had crossed 100%, where no fade is measured at
all: they compounded to $10.3bn and $8.1bn by 2030 and put $51 a share on Amgen. These
tests read the seed files, not a book. A file that breaks either rule and is known to is
listed in data/growth_convention_exceptions.txt with its reason, and the list cannot grow
unnoticed.
"""

import csv
import pathlib
import re

import growth_analogues as G

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
KNOWN = DATA / "growth_convention_exceptions.txt"
GROWTH = ("revenue_growth_pct", "franchise_growth_pct")


def _known() -> set:
    return {line.split("#")[0].strip() for line in KNOWN.read_text().splitlines()
            if line.split("#")[0].strip()}


def _products():
    """(file: name, {key: row}) for the base rows of every product and line."""
    for folder, column in (("assumptions", "brand"), ("company_lines", "line")):
        for path in sorted((DATA / folder).glob("*.csv")):
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(
                    line for line in handle if not line.lstrip().startswith("#")))
            by: dict = {}
            for row in rows:
                if (row.get("indication") or "").strip():
                    continue
                if ((row.get("scenario") or "base").strip() or "base") != "base":
                    continue
                by.setdefault(row[column], {})[row["key"]] = row
            for name, keyed in by.items():
                yield f"{folder}/{path.name}: {name}", keyed


def _growth(keyed: dict):
    row = next((keyed[k] for k in GROWTH if k in keyed), None)
    try:
        return float(row["value"]) if row else None
    except (TypeError, ValueError):
        return None


def band_mismatches() -> dict:
    out = {}
    for label, keyed in _products():
        growth, fade = _growth(keyed), keyed.get("growth_fade_years")
        if growth is None or fade is None:
            continue
        stated = re.search(r"drugs that grew (.+?):", fade.get("source") or "")
        if not stated:
            continue
        band = G.band_of(growth) if growth > 0 else None
        now = G.band_words(band) if band else "not growing"
        if stated.group(1) != now:
            out[label] = (stated.group(1), now)
    return out


def unbounded_launch_rates() -> dict:
    out = {}
    for label, keyed in _products():
        growth = _growth(keyed)
        if growth is None or growth <= 1.0 or "revenue_ceiling_musd" in keyed:
            continue
        try:
            fade = float((keyed.get("growth_fade_years") or {}).get("value") or 0)
        except ValueError:
            fade = 0
        if fade == 1:          # one year: the rate carries a base to a run rate and stops
            continue
        out[label] = round(growth, 3)
    return out


def test_a_fade_is_the_one_measured_for_the_band_its_rate_sits_in():
    found = band_mismatches()
    new = {k: v for k, v in found.items() if k not in _known()}
    assert not new, f"fade measured for another band (file: stated, the rate's band): {new}"


def test_a_rate_above_100_percent_carries_a_ceiling():
    found = unbounded_launch_rates()
    new = {k: v for k, v in found.items() if k not in _known()}
    assert not new, f"a rate above 100% a year with no revenue_ceiling_musd: {new}"


def test_the_exception_list_holds_nothing_that_has_been_fixed():
    still = set(band_mismatches()) | set(unbounded_launch_rates())
    fixed = _known() - still
    assert not fixed, f"no longer exceptions, remove from {KNOWN.name}: {sorted(fixed)}"
