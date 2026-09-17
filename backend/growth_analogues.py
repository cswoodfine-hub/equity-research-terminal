"""How long a drug's growth lasts, measured from drugs that have already peaked.

Every marketed product's near-term growth fades to its long-run rate over
``growth_fade_years``, and that length was a convention of five years. Across the book the
model read a median 25% below the share price while its 2026 revenue sat within a few
percent of guidance, so the gap is in conventions like this one rather than in the
forecast level. A five-year fade from any growth rate is a guess; how long growth lasted
is on file for the drugs that came before.

``data/growth_analogues.csv`` holds annual worldwide revenue for past and present
blockbusters, each year read from the company's own annual report with its quote. For a
drug that has peaked, every year before the peak is an observation: the growth it had
that year, and the rest of its climb, peak revenue over that year's revenue. The fade
length is the whole number of years that, in the engine's own shape (growth falling in a
straight line to nothing), carries that growth rate to that climb. It is fitted to the
climb rather than read off the years to the peak, because the climb is what the value
rests on.

Observations are grouped by the growth rate they start from, since a drug growing 60% a
year is at a different point in its life from one growing 8%. Each drug counts once in a
band, at the median of its own years there, so a long-lived drug with many years in a band
does not outvote the rest.

Two kinds of drug have not shown how long their growth would have lasted, and dropping
them would bias every length short, since the drugs that grow longest are the ones most
likely to be growing still. A drug still near its best has a climb that is only a lower
bound. A drug whose revenue fell by more than 40% within two years of its peak lost
exclusivity at the peak (Humira, Revlimid), and the engine already charges that fall
through erosion, so its growth was cut rather than spent. Both are kept as censored
observations, "at least this long", and the lengths are read off a Kaplan-Meier estimate
rather than a plain median. A quartile the censoring leaves undetermined is left out, not
guessed.
"""

from __future__ import annotations

import csv
import math
import pathlib
import statistics

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "growth_analogues.csv"
# Growth rates an observation starts from. The top band starts where launch products'
# solved rates sit; the bottom one is a mature product still edging up.
BANDS = ((0.0, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 1.00), (1.00, math.inf))
MAX_FADE = 30
# A drug has peaked when its last reported year is at least this far below its best.
PEAKED_BELOW = 0.90
# A fall this steep this soon after the peak is a loss of exclusivity, not a spent climb.
CLIFF_DROP, CLIFF_YEARS = 0.40, 2


# A drug that changed hands is one drug: Humira under Abbott and then AbbVie, Revlimid
# under Celgene and then Bristol.
SUCCESSOR = {"ABT": "ABBV", "CELG": "BMY"}


def load(path=None) -> dict:
    """{"<TICKER> <product>": {"years": {year: revenue}, "unit", "scope"}}, keyed by the
    filer after any acquisition and the product, so a drug two companies both book
    (Imbruvica at AbbVie and at Johnson & Johnson) stays two series."""
    source = pathlib.Path(path) if path else DATA
    series: dict = {}
    if not source.exists():
        return series
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle if not line.lstrip().startswith("#")):
            try:
                year, value = int(row["fiscal_year"]), float(row["revenue"])
            except (TypeError, ValueError, KeyError):
                continue
            # A part year is not a year: Bristol booked Revlimid only from the close of
            # the Celgene deal in November 2019.
            if (row.get("partial_year") or "").strip() in ("1", "yes", "true"):
                continue
            ticker = (row.get("ticker") or "").strip().upper()
            product = " ".join((row.get("product") or "").split())
            key = f"{SUCCESSOR.get(ticker, ticker)} {product}"
            entry = series.setdefault(key, {"years": {}, "breaks": set(),
                                            "unit": (row.get("unit") or "").strip(),
                                            "scope": (row.get("scope") or "").strip()})
            entry["years"][year] = value
            # The first year on a new basis (Biogen booking all of Tysabri from 2013): the
            # level is real, the step into it is not growth.
            if (row.get("basis_break") or "").strip() in ("1", "yes", "true"):
                entry["breaks"].add(year)
    return series


def fade_path(growth: float, fade: int) -> float:
    """The climb the engine's fade produces: revenue after ``fade`` years over revenue
    now, growth falling in a straight line from ``growth`` to nothing."""
    level = 1.0
    for i in range(fade):
        level *= 1.0 + growth * (1.0 - i / fade)
    return level


def fitted_fade(growth: float, climb: float) -> int:
    """The whole number of years whose fade carries ``growth`` to ``climb``."""
    target = math.log(max(climb, 1e-9))
    return min(range(1, MAX_FADE + 1),
               key=lambda n: abs(math.log(fade_path(growth, n)) - target))


def band_of(growth: float):
    return next((b for b in BANDS if b[0] < growth <= b[1]), None)


def status(years: dict) -> str:
    """peaked, cliff (lost exclusivity at the peak) or growing (still near its best)."""
    peak_year = max(years, key=lambda y: years[y])
    last = max(years)
    if not (peak_year < last and years[last] <= PEAKED_BELOW * years[peak_year]):
        return "growing"
    after = [years[y] for y in range(peak_year + 1, peak_year + CLIFF_YEARS + 1) if y in years]
    if after and min(after) <= (1.0 - CLIFF_DROP) * years[peak_year]:
        return "cliff"
    return "peaked"


def observations(series: dict) -> tuple[list, list]:
    """(observations, censored). An observation is one year before a drug's best with
    measurable growth: {product, year, growth, climb, fade, years_to_peak, censored}.
    ``censored`` names the drugs whose climb is a lower bound, with why."""
    out, censored = [], []
    for product, entry in series.items():
        years = entry["years"]
        if len(years) < 3:
            continue
        state = status(years)
        if state != "peaked":
            censored.append(f"{product} ({'still near its best' if state == 'growing' else 'lost exclusivity at its peak'})")
        peak_year = max(years, key=lambda y: years[y])
        first = min(years)
        for year in sorted(years):
            # The first year on file is usually a launch year sold for part of it, so the
            # step out of it is not a year's growth.
            if (year >= peak_year or (year - 1) not in years or years[year - 1] <= 0
                    or year - 1 == first or year in entry.get("breaks", ())):
                continue
            growth = years[year] / years[year - 1] - 1.0
            if growth <= 0:
                continue
            climb = years[peak_year] / years[year]
            out.append({"product": product, "year": year, "growth": growth, "climb": climb,
                        "fade": fitted_fade(growth, climb),
                        "years_to_peak": peak_year - year, "censored": state != "peaked"})
    return out, censored


def kaplan_meier(values: list) -> list:
    """[(time, survival)] for (value, censored) pairs: the share still growing past each
    length, where a censored value is known only to be at least that long."""
    times = sorted({v for v, c in values if not c})
    survival, curve = 1.0, []
    for t in times:
        at_risk = sum(1 for v, _ in values if v >= t)
        events = sum(1 for v, c in values if v == t and not c)
        if at_risk:
            survival *= 1.0 - events / at_risk
        curve.append((t, survival))
    return curve


def km_quantile(curve: list, p: float):
    """The shortest length by which a share ``p`` of drugs had stopped growing, or None
    where the censoring leaves it undetermined."""
    return next((t for t, s in curve if s <= 1.0 - p + 1e-12), None)


def by_band(observed: list) -> list[dict]:
    """Per growth band: each drug once, at its median fade there, censored if its climb
    is a lower bound, and the Kaplan-Meier quartiles across drugs."""
    out = []
    for band in BANDS:
        per_product: dict = {}
        for o in observed:
            if band_of(o["growth"]) == band:
                per_product.setdefault(o["product"], []).append(o)
        values = [(statistics.median(x["fade"] for x in obs), obs[0]["censored"])
                  for obs in per_product.values()]
        row = {"band": band, "products": sorted(per_product), "n": len(values),
               "peaked": sum(1 for _, c in values if not c),
               "censored": sum(1 for _, c in values if c)}
        curve = kaplan_meier(values)
        median = km_quantile(curve, 0.5)
        if row["peaked"] >= 3 and median is not None:
            row.update(low=km_quantile(curve, 0.25), median=median,
                       high=km_quantile(curve, 0.75))
            if row["high"] is None:
                row["high_at_least"] = max(v for v, _ in values)
        out.append(row)
    return out


def measure(path=None) -> dict:
    series = load(path)
    observed, censored = observations(series)
    return {"bands": by_band(observed), "observations": observed,
            "censored": sorted(censored), "products": len(series)}


def for_growth(measured: dict, growth: float) -> dict | None:
    """The band a growth rate sits in, where it has quartiles. None for a rate at or
    below nothing, where there is no climb ahead to measure."""
    band = band_of(growth) if growth and growth > 0 else None
    if band is None:
        return None
    row = next(b for b in measured["bands"] if b["band"] == band)
    return row if row.get("median") is not None and row.get("low") is not None else None


def whole_years(value: float) -> int:
    """A fade length in whole years, halves rounded up: the engine reads whole years, and
    a measured 4.5 is not four."""
    return int(math.floor(value + 0.5))


def band_words(band: tuple) -> str:
    lo, hi = band
    return (f"more than {lo:.0%} a year" if math.isinf(hi)
            else f"{lo:.0%} to {hi:.0%} a year")


# The growth a fade starts from, by how the product is built.
GROWTH_KEYS = {"marketed": "revenue_growth_pct", "franchise": "franchise_growth_pct"}


def applies(scalars: dict, rows: list) -> tuple | None:
    """(growth key, growth) where a measured fade replaces the convention; None where it
    does not. It applies to a product anchored on reported revenue, or a franchise pool,
    that fades to a long-run rate from growth read off its filings. A rate solved to reach
    a published peak by a year already has its length set by that year, and a product
    that is not growing has no climb ahead to measure."""
    key = GROWTH_KEYS.get(scalars.get("therapy_mode"))
    if key is None or scalars.get("terminal_growth_pct") is None:
        return None
    growth = scalars.get(key)
    if growth is None or growth <= 0:
        return None
    source = next((r.get("source") or "" for r in rows
                   if r["key"] == key and r.get("indication_id") is None
                   and r.get("scenario", "base") == "base"), "")
    if source.strip().lower().startswith("solved"):
        return None
    return key, growth


def fade_source(row: dict, path_name: str = "data/growth_analogues.csv") -> str:
    """The source text for a measured fade row."""
    high = (f"{row['high']:g}" if row.get("high") is not None
            else f"at least {row['high_at_least']:g}")
    return (f"measured from {row['n']} drugs that grew {band_words(row['band'])}: the median "
            f"took {row['median']:g} years of fading growth to reach its peak revenue "
            f"(quartiles {row['low']:g} to {high}), each fitted to its own climb in "
            f"{path_name}. Kaplan-Meier across drugs, {row['censored']} of them censored "
            "because they are still near their best or lost exclusivity at their peak")
