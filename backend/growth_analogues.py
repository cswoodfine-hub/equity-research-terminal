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
does not outvote the rest. A drug still growing at its last reported year has not shown
its peak, so it is left out of the measurement and counted as censored: its fade can only
be longer than what it has shown, which makes the measured lengths a floor rather than an
estimate biased long.
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


def observations(series: dict) -> tuple[list, list]:
    """(observations, censored). An observation is one year of a peaked drug before its
    peak with positive growth: {product, year, growth, climb, fade, years_to_peak}.
    ``censored`` names the drugs still at or near their best."""
    out, censored = [], []
    for product, entry in series.items():
        years = entry["years"]
        if len(years) < 3:
            continue
        peak_year = max(years, key=lambda y: years[y])
        last = max(years)
        if not (peak_year < last and years[last] <= PEAKED_BELOW * years[peak_year]):
            censored.append(product)
            continue
        for year in sorted(years):
            if (year >= peak_year or (year - 1) not in years or years[year - 1] <= 0
                    or year in entry.get("breaks", ())):
                continue
            growth = years[year] / years[year - 1] - 1.0
            if growth <= 0:
                continue
            climb = years[peak_year] / years[year]
            out.append({"product": product, "year": year, "growth": growth, "climb": climb,
                        "fade": fitted_fade(growth, climb),
                        "years_to_peak": peak_year - year})
    return out, censored


def by_band(observed: list) -> list[dict]:
    """Per growth band: the drugs in it, each at its own median fade, and the quartiles
    across drugs. A band with fewer than three drugs gives no quartiles."""
    out = []
    for band in BANDS:
        per_product: dict = {}
        for o in observed:
            if band_of(o["growth"]) == band:
                per_product.setdefault(o["product"], []).append(o)
        fades = sorted(statistics.median(x["fade"] for x in obs)
                       for obs in per_product.values())
        peaks = sorted(statistics.median(x["years_to_peak"] for x in obs)
                       for obs in per_product.values())
        row = {"band": band, "products": sorted(per_product), "n": len(fades)}
        if len(fades) >= 3:
            q = statistics.quantiles(fades, n=4, method="inclusive")
            row.update(low=q[0], median=q[1], high=q[2],
                       years_to_peak_median=statistics.median(peaks))
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
    return row if "median" in row else None


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


def fade_source(row: dict, censored: int, path_name: str = "data/growth_analogues.csv") -> str:
    """The source text for a measured fade row."""
    return (f"measured from peaked drugs: {row['n']} that grew {band_words(row['band'])} "
            f"took a median {row['median']:g} years of fading growth to reach their peak "
            f"revenue (quartiles {row['low']:g} to {row['high']:g}), fitted to each drug's "
            f"actual climb in {path_name}. {censored} drugs still near their best are left "
            "out, so this is a floor")
