"""Zepbound's observed capture of the untreated obese pool, derived once.

Sixty-five percent of the book's pipeline value rests on one number: the share of the
untreated obese population that the incumbent incretin actually converts in a year. Every
obesity asset in the book is priced as a multiple of it. It was written out by hand in
seven assumption rows, in seven different forms, and the same fact graded five different
ways because the grader keys on words and one row happened to say "amylin analogue".

The fix is not a better sentence. It is that a number this load-bearing should be derived
from rows the database already holds, so it can be recomputed, tested and argued with.

WHAT IT MEASURES. Eli Lilly reports Zepbound's revenue. Divided by the net price a
patient-year costs, that is a stock of patients. Net of those who stop, the year-on-year
change in that stock is new starts. As a share of the pool still untreated, that is the
capture rate: 1.38% in 2024, 3.35% in 2025, 4.39% annualised in 2026.

THE THREE CONVENTIONS, named because none of them is forced and each moves the answer.
They are parameters here rather than prose, so a reader can see the alternative and what
it costs.

``annualise``  "quarter" takes the latest quarter times four, which is what forecast.py
               does in latest_run_rate and what the seeds used. "half" doubles the first
               half and gives 3.94%. The quarter is the more recent pace; the half is
               steadier. This book's own warning about annualising a half year concerns
               seasonal vaccines selling in H2, which argues for the quarter, not against.
``pool``       "untreated" shrinks the pool by cumulative new starts only, which is what
               the seeds did. "engine" also adds the incidence term, because
               forecast.patients_for_indication multiplies penetration by pool PLUS
               incidence, and gives 3.88%. The engine convention is the one the consuming
               code actually uses, so the two disagree by 13% and that gap is real.
``opening``    True carries Zepbound's 2023 revenue into the opening stock. The seeds
               dropped it, which flatters 2024 from 1.36% to 1.38%.

The default reproduces what the book already carries, so importing this module changes no
valuation. Moving the convention is a decision with a measured cost, not a refactor, and
it belongs to whoever owns the book rather than to whoever tidied it.

WHAT IT IS NOT. It is not a forecast and it is not any asset's penetration. An asset's
own rate is this anchor times a multiple that says how it expects to fare against the
incumbent, and that multiple is an analyst's judgement. The two are different kinds of
evidence and a row carrying both should say so.
"""

from __future__ import annotations

ZEPBOUND_ASSET_ID = 13

# The accessions the revenue is read from. Named in the basis string so a row built on
# this grades as arithmetic on filings, which is what it is, rather than as nothing.
FILINGS = ("10-K 0000059478-26-000013", "8-K exhibit 0000059478-26-000077")

# The years the series covers. 2023 is the opening stock rather than a measured year.
FIRST_YEAR, LAST_YEAR = 2024, 2026


def net_price(conn, asset_id: int) -> float | None:
    """The net cost of a patient-year, in the price unit the seeds carry (millions).

    List price times the gross-to-net share, read from the asset's own rows so the
    anchor and the forecast that consumes it cannot drift apart.
    """
    rows = {r["key"]: r["value"] for r in conn.execute(
        "SELECT key, value FROM assumptions WHERE asset_id = ? AND scenario = 'base'"
        "   AND year IS NULL AND key IN ('list_price_per_patient', 'gross_to_net_pct')",
        (asset_id,))}
    listed, share = rows.get("list_price_per_patient"), rows.get("gross_to_net_pct")
    if listed is None or share is None:
        return None
    return listed * share


def _revenue(conn, annualise: str) -> dict:
    """{year: revenue} in the same money unit as the price, with the latest year's pace
    annualised. Returns whole currency units divided down to millions."""
    out: dict = {}
    for row in conn.execute(
            "SELECT fiscal_year, period, value FROM asset_revenue"
            " WHERE asset_id = ? AND period = 'FY'", (ZEPBOUND_ASSET_ID,)):
        out[row["fiscal_year"]] = row["value"] / 1e6
    quarters = {r["period"]: r["value"] / 1e6 for r in conn.execute(
        "SELECT period, value FROM asset_revenue WHERE asset_id = ? AND fiscal_year = ?",
        (ZEPBOUND_ASSET_ID, LAST_YEAR))}
    if annualise == "quarter" and "Q2" in quarters:
        out[LAST_YEAR] = quarters["Q2"] * 4
    elif annualise == "half":
        half = quarters.get("Q1", 0.0) + quarters.get("Q2", 0.0)
        if half:
            out[LAST_YEAR] = half * 2
    return out


def measure(conn, asset_id: int, *, annualise: str = "quarter", pool: str = "untreated",
            opening: bool = False) -> dict | None:
    """The capture rate and everything behind it, or None where an input is missing.

    ``asset_id`` is the asset whose price, pool and discontinuation rows define the
    measurement. Every obesity asset in this book carries the same ones, so the answer
    is the same whichever is passed; taking it from a row rather than a constant is what
    keeps the anchor and the forecast on one set of inputs.
    """
    price = net_price(conn, asset_id)
    if not price:
        return None
    facts = {r["key"]: r["value"] for r in conn.execute(
        "SELECT key, value FROM assumptions WHERE asset_id = ? AND scenario = 'base'"
        "   AND key IN ('discontinuation_pct', 'prevalence', 'incidence')", (asset_id,))}
    stop = facts.get("discontinuation_pct")
    prevalence = facts.get("prevalence")
    incidence = facts.get("incidence") or 0.0
    if stop is None or not prevalence:
        return None

    revenue = _revenue(conn, annualise)
    if not all(revenue.get(y) for y in range(FIRST_YEAR, LAST_YEAR + 1)):
        return None

    stock = {y: revenue[y] / price for y in range(FIRST_YEAR, LAST_YEAR + 1)}
    prior = (revenue.get(FIRST_YEAR - 1, 0.0) / price) if opening else 0.0
    series, remaining, held = [], float(prevalence), prior
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        # Those still on therapy from last year, and the starts needed to reach this
        # year's stock on top of them.
        carried = held * (1.0 - stop)
        starts = max(0.0, stock[year] - carried)
        denominator = remaining + (incidence if pool == "engine" else 0.0)
        rate = starts / denominator if denominator else 0.0
        series.append({"year": year, "revenue": revenue[year], "stock": stock[year],
                       "starts": starts, "pool": denominator, "rate": rate})
        remaining = max(0.0, remaining - starts)
        held = stock[year]
    return {"rate": series[-1]["rate"], "series": series, "price": price,
            "discontinuation": stop, "prevalence": prevalence, "incidence": incidence,
            "annualise": annualise, "pool": pool, "opening": opening}


def basis(got: dict) -> str:
    """The sentence a seed row carries. Names the filings, so a row built on this grades
    as arithmetic on a filer's own reported revenue rather than as nothing at all."""
    if not got:
        return ""
    path = ", ".join(f"{s['rate'] * 100:.2f}% in {s['year']}" for s in got["series"])
    tail = "the latest quarter annualised" if got["annualise"] == "quarter" \
        else "the first half doubled"
    return (f"Zepbound's observed capture of the untreated obese pool, computed in "
            f"capture_anchor from Eli Lilly's reported revenue ({'; '.join(FILINGS)}) "
            f"at a net {got['price'] * 1e6:,.0f} per patient-year, net of the "
            f"{got['discontinuation']:.1%} who stop each year, against a pool of "
            f"{got['prevalence'] / 1e6:,.1f}mm: {path}, on {tail}")
