"""What the growth a forecast carries costs in capital, measured from what it has cost.

The engine has no capex line and no working capital line. Every cost a company pays sits
in four ratios, and each one is a share of revenue, so anything the model charges is
charged in proportion to how much a product sells rather than to how much more it sells
than last year. Growth investment does not work that way: a company that holds its
revenue flat replaces its plant, and one that doubles its revenue builds more of it.

The other-costs charge was solved so the book reproduces the company's own free cash
flow, and then two restatements took the growth out of it (``replacement_capex``,
``working_capital``): capex was charged at plant depreciation and the working capital
build was removed, on the reasoning that a run-off only replaces what it uses. The book
is not a run-off. Its products ramp, its franchise grows at expected inflation, and the
launch line adds revenue for sixty years. The model charged none of the capital that
growth takes, and its first forecast year read 1.3 times the cash the filers actually
generated, by a median across eighteen of them.

So growth is charged where it happens: a share of every dollar of revenue the forecast
adds, and nothing in a year that adds none. The share is what the filers have spent for
it, capex above plant depreciation plus the working capital they built, over the revenue
they added, pooled across the book.

Pooled, not per filer, because one company's own figure is dominated by what it bought or
sold rather than what it built: AbbVie reads 0.02 because Allergan's revenue arrived
without Allergan's plant, and Merck reads 1.35 because the Organon spin-off took revenue
out of the denominator while the plant stayed. The pool is revenue-weighted, so the
companies that added the most revenue count for the most.

A filer whose charge still carries its full capex, because no plant depreciation was on
file to restate it with, takes the working capital share alone. Charging it the capex
share too would charge the same plant twice.
"""

from __future__ import annotations

import time

import fx
import interest_addback as IA

# The first year to measure from. Long enough that a single build-out or a single year's
# working capital swing does not set a filer's figure, and inside what companyfacts
# carries for every filer in the book.
FIRST_YEAR = 2012
MIN_YEARS = 4
# The charge's own source says which restatements were applied to it: "Restated at
# replacement capex" took the growth capex out, "Checked at replacement capex" found
# nothing to take and left the filer's full capex in the charge.
CAPEX_MARKER = "Restated at replacement capex"
WC_MARKER = "Restated without working capital build"
_CACHE: dict = {}
_CACHE_SECONDS = 3600


def _flow(series: dict, years) -> float:
    """A cash-flow statement line summed over ``years``, absent years counting nil."""
    return sum(series[y]["value"] for y in years if y in series)


def filer(conn, company_id: int, first: int = FIRST_YEAR, last: int = 2025) -> dict:
    """One filer's growth investment and the revenue it added. Capex above plant
    depreciation, plus the working capital it built, over the years both are on file.

    The working capital build is the cash flow statement's own changes in receivables,
    inventories and payables, the same lines ``working_capital`` reads, so a balance
    sheet that moved on an acquisition or on a currency is not read as a build.
    """
    got = {m: IA.fy_series(conn, company_id, m, first - 1, last) for m in
           ("Revenues", "CapitalExpenditure", "Depreciation", "ReceivablesCashEffect",
            "InventoriesCashEffect", "PayablesCashEffect", "PayablesAccruedCashEffect")}
    years = sorted(set(got["Revenues"]) & set(got["CapitalExpenditure"])
                   & set(got["Depreciation"]))
    years = [y for y in years if y >= first]
    if len(years) < MIN_YEARS:
        return {"reason": f"capex and plant depreciation on file for {len(years)} years"}
    opening = got["Revenues"].get(years[0] - 1) or got["Revenues"].get(years[0])
    added = got["Revenues"][years[-1]]["value"] - opening["value"]
    capex = sum(abs(got["CapitalExpenditure"][y]["value"]) for y in years)
    depreciation = sum(got["Depreciation"][y]["value"] for y in years)
    payables = got["PayablesCashEffect"] or got["PayablesAccruedCashEffect"]
    build = -(_flow(got["ReceivablesCashEffect"], years)
              + _flow(got["InventoriesCashEffect"], years) + _flow(payables, years))
    return {"first": years[0], "last": years[-1], "years": len(years),
            "capex_gap": capex - depreciation, "wc_build": build, "added": added,
            "unit": got["Revenues"][years[-1]]["unit"],
            "intensity": ((capex - depreciation + build) / added) if added > 0 else None,
            "reason": None if added > 0 else "revenue fell over the window"}


def _db_key(conn) -> str:
    try:
        return next((row[2] for row in conn.execute("PRAGMA database_list")
                     if row[1] == "main"), "") or ""
    except Exception:
        return ""


def pooled(conn, refresh: bool = False) -> dict:
    """{capex, working_capital, intensity, filers, added}: what a dollar of revenue added
    has cost the book in capital, split into the two pieces so a filer whose charge still
    carries its own capex can take the working capital share alone. In dollars, so filers
    reporting in kroner and euro pool with the rest. Cached for an hour."""
    key = _db_key(conn)
    hit = _CACHE.get(key)
    if hit and not refresh and time.time() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    rates = fx.latest_usd_rates(key or None)
    filers, capex, build, added = [], 0.0, 0.0, 0.0
    for row in conn.execute("SELECT id, ticker FROM companies ORDER BY ticker").fetchall():
        if row["ticker"] not in IA.WINDOWS:
            continue
        got = filer(conn, row["id"])
        got["ticker"] = row["ticker"]
        filers.append(got)
        rate = 1.0 if got.get("unit") == "USD" else rates.get(got.get("unit") or "")
        if got.get("intensity") is None or not rate:
            continue
        capex += got["capex_gap"] * rate
        build += got["wc_build"] * rate
        added += got["added"] * rate
    out = {"filers": filers, "added": added,
           "capex": (capex / added) if added else None,
           "working_capital": (build / added) if added else None,
           "intensity": ((capex + build) / added) if added else None,
           "counted": sum(1 for f in filers if f.get("intensity") is not None)}
    _CACHE[key] = (time.time(), out)
    return out


def carries(source: str | None) -> tuple[bool, bool]:
    """(the charge holds capex at replacement, the charge excludes the working capital
    build), read off an other-costs row's own source text."""
    text = source or ""
    return CAPEX_MARKER in text, WC_MARKER in text  # "Checked ..." left the cost in


def for_company(conn, ticker: str, source: str | None = None) -> dict:
    """The share of added revenue to charge one company, and what it is made of. A charge
    that still carries the filer's own capex takes the working capital share alone."""
    pool = pooled(conn)
    if pool.get("intensity") is None:
        return {"value": None, "reason": "no growth investment measured across the book"}
    at_replacement, without_build = carries(source)
    value = ((pool["capex"] if at_replacement else 0.0)
             + (pool["working_capital"] if without_build else 0.0))
    parts = ([f"capex above plant depreciation {pool['capex']:.3f}"] if at_replacement else []) + \
            ([f"working capital {pool['working_capital']:.3f}"] if without_build else [])
    return {"value": value, "reason": None, "ticker": ticker.upper(),
            "basis": (f"{' and '.join(parts)} per dollar of revenue added, pooled across "
                      f"{pool['counted']} filers on "
                      f"${pool['added'] / 1e9:,.0f}bn of revenue added"
                      if parts else "the charge already carries both, so nothing is added")}
