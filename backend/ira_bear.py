"""The bear case for a Medicare negotiated price: what the cohort's average cut would cost.

The plan's step 4 asks for a selected drug to step down to its negotiated price from the
year the price applies, as a bear case. The cut a drug takes is the fall from its net
price to the negotiated one, and its net price is confidential, so no drug's own cut is
in any free source (``ira.py`` sets out why). CMS does publish, for each cohort, what its
negotiated prices would have saved Medicare net against the cohort's gross Part D
spending (``data/ira_cohorts.csv``): 10.7% of gross for the 2026 cohort, 28.2% for 2027.

So the bear case cuts the drug's US line, from the year its price applies, by that share
of the drug's own Medicare Part D gross spending: the cohort's average cut, applied to
this drug. It is labelled as an average because a drug's own cut can sit well above or
below it. Beside the value, never in it: the base case is unchanged.
"""

from __future__ import annotations

import copy
import csv
import pathlib

import assumptions as assumptions_module
import forecast
import fx
import ira

COHORTS = pathlib.Path(__file__).resolve().parent.parent / "data" / "ira_cohorts.csv"


def cohorts(path=None) -> dict:
    """{ipay: {base_year, gross_usd_bn, net_savings_usd_bn, savings_share, ...}}."""
    source = pathlib.Path(path) if path else COHORTS
    if not source.exists():
        return {}
    with source.open(newline="", encoding="utf-8") as handle:
        rows = [line for line in handle if not line.lstrip().startswith("#")]
    out = {}
    for row in csv.DictReader(rows):
        gross, saved = float(row["gross_usd_bn"]), float(row["net_savings_usd_bn"])
        out[int(row["ipay"])] = {**row, "base_year": int(row["base_year"]),
                                 "savings_share": saved / gross if gross else None}
    return out


def _cohort_of(conn, asset_id: int) -> dict | None:
    """The asset's selection with a price in force, the earliest year it applies."""
    mine = [s for s in ira.selected(conn) if s["asset_id"] == asset_id and s["in_force"]]
    return min(mine, key=lambda s: s["ipay"]) if mine else None


def for_asset(conn, asset_id: int, cohort_path=None) -> dict | None:
    """The bear case for one asset, or None where it is not selected, has no price in
    force, its cohort has no published savings, or it has no Part D spending or forecast.
    {ipay, drug, savings_share, part_d_spending, part_d_year, annual_cut, factor,
    npv_base, npv_bear, currency}."""
    chosen = _cohort_of(conn, asset_id)
    if chosen is None:
        return None
    cohort = cohorts(cohort_path).get(int(chosen["ipay"]))
    exposure = ira.exposure(conn, asset_id)
    if not cohort or not cohort["savings_share"] or exposure.get("reason"):
        return None
    inputs = assumptions_module.load(conn, asset_id, "base")
    if not inputs or not inputs.get("scalars"):
        return None
    try:
        base = forecast.build(inputs)
    except forecast.ForecastError:
        return None
    currency = conn.execute(
        "SELECT c.reporting_currency FROM assets a JOIN companies c"
        " ON c.id = a.owner_company_id WHERE a.id = ?", (asset_id,)).fetchone()[0] or "USD"
    row = conn.execute("PRAGMA database_list").fetchone()
    rates = fx.latest_usd_rates((row["file"] or None) if row is not None else None)
    per_unit = 1.0 if currency == "USD" else rates.get(currency)
    ipay = int(chosen["ipay"])
    if not per_unit or ipay not in base["years"]:
        return None
    annual_cut_usd = exposure["part_d_spending"] * cohort["savings_share"]
    annual_cut = annual_cut_usd / per_unit / 1e6
    index = base["years"].index(ipay)
    us_line = base["revenue"][index] * base["us_share"]
    if us_line <= 0:
        return None
    factor = min(1.0, annual_cut / us_line)
    bear_inputs = copy.deepcopy(inputs)
    bear_inputs["price_step"] = {
        "from_year": ipay, "factor": factor,
        "basis": f"Medicare negotiated price, the {ipay} cohort's average cut of "
                 f"{cohort['savings_share']:.1%} of Part D gross"}
    bear = forecast.build(bear_inputs)
    return {"ipay": ipay, "drug": chosen["drug"], "savings_share": cohort["savings_share"],
            "cohort_saving_pct": float(cohort["net_savings_pct"]),
            "cohort_base_year": cohort["base_year"],
            "part_d_spending": exposure["part_d_spending"], "part_d_year": exposure["year"],
            "annual_cut": annual_cut, "us_line": us_line, "factor": factor,
            "capped": factor >= 1.0, "currency": currency,
            "npv_base": base["npv"], "npv_bear": bear["npv"]}
