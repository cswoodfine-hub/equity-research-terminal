"""The Forecast tab's board: the company and its assets as yearly series a page can switch
between.

The valuation already computes every figure here and showed most of them one fixed way:
revenue as a three-year bar, cash flow as a table, plant spending not at all. The board
lays the same figures out by year so the page can plot whichever the reader asks for
(revenue, operating profit, free cash flow, each cost line, capex), for the company and
for each asset, with the reported years joined on the left.

Nothing is estimated and nothing is valued here. The board adds the assets up and reads
the filings; a test holds that its totals are the sum of its parts and that its value is
the sum of the parts' own. A view beside the valuation: nothing on the value path imports
it.

THE TWO BASES. "Weighted" multiplies each asset's figures by the probability in force,
the one its rNPV uses; "success" takes them in full. A marketed product and a revenue
line count in full on both.

LAUNCHES THE MODEL ASSUMES. The sum of the parts credits the company's R&D with the
launches it has historically bought (``future_pipeline``), and for a large company that
is a large share of the value. Its yearly flows are carried as a group of their own, so
the company's path is the path the value is the present value of, and the page can show
how much of each year no named product earns. The same on both bases: it is an
expectation already, not an asset with odds.

REPORTED AGAINST FORECAST. Reported operating profit is the filer's own line, after
amortisation and one-off charges; the forecast's is revenue less the four cost ratios.
Reported free cash flow is operating cash flow less capital spending; the forecast's is
before interest, with plant at the rule below. They are drawn on one axis and are not the
same definition, and the board says so in ``basis`` rather than restating either.

CAPEX. The engine has no capex line, but it does charge plant, twice over, and both
charges are measured from filings:

  upkeep  The other-costs charge carries capital spending at plant depreciation
          (``replacement_capex``): the filer's own depreciation over its own revenue.
  growth  Each dollar of revenue the book adds is charged the capex above depreciation
          the filers have spent per dollar they added, pooled across the book
          (``growth_investment``).

So forecast capex is what the valuation already takes out of the cash flow: the upkeep
rate on each year's revenue plus the capex share of that year's growth charge. A filer
whose charge was not restated still carries its full capex in the charge, and takes its
own capex over revenue with no growth share. Plotting a separate rule (a five-year share
of revenue, say) would draw a capex line that does not reconcile with the free cash flow
beside it. Where the filer's lines are not on file the forecast is None with the reason.

PAST THE MODEL. Each product is modelled year by year for ten years or to a few years
past its own loss of exclusivity, whichever is longer, and valued after that by a terminal
value. The terminal value is the present value of a path: the product runs on at its
growth to its exclusivity, takes its year-one drop and decays (``forecast.terminal_path``).
The board carries each part past its last modelled year on that same path, with every
line of its P&L in the final year's proportions, which is the stream the terminal value
discounts. So the company's path can be drawn past the last cliff that matters without a
product vanishing in the year its model happens to stop. A part with no terminal value
earns nothing past its model, as in the valuation.
"""

from __future__ import annotations

import datetime as dt

import evidence
import forecast
import growth_investment as GI
import interest_addback as IA
import product_areas
import replacement_capex as RC

HISTORY_YEARS = 10         # reported years drawn before the forecast
HORIZON_YEARS = 10         # forecast years drawn at the least
CLIFF_YEARS = 3            # years drawn after the last loss of exclusivity that matters
MAX_YEARS = 25             # and at the most
MATTERS = 0.01             # a cliff matters where the asset is this share of the named value
COST_KEYS = ("cogs", "sga", "rd", "other", "tax")
# measure -> the key in a forecast P&L row
ROW_KEY = {"revenue": "revenue", "operating_profit": "ebit", "free_cash_flow": "fcff",
           "cost_of_goods": "cogs", "sga": "sga", "rd": "rd", "other_costs": "other",
           "tax": "tax"}
# measure -> the reported line in ``financials``
REPORTED = {"revenue": "Revenues", "operating_profit": "OperatingIncomeLoss",
            "cost_of_goods": "CostOfRevenue", "sga": "SellingGeneralAndAdministrative",
            "rd": "ResearchAndDevelopmentExpense", "tax": "IncomeTaxExpense",
            "capex": "CapitalExpenditure"}
# where the cash went, as filed in the cash flow statement: outlays, drawn as positive
USES = {"operating_cash_flow": "CashFlowOperating", "acquisitions": "AcquisitionsNet",
        "intangibles": "AcquiredIntangibles", "dividends": "DividendsPaid",
        "buybacks": "ShareRepurchases", "financing": "CashFlowFinancing"}
SIGNED = ("operating_cash_flow", "financing")      # flows kept with the filer's sign
BASIS = {
    "operating_profit": "reported as filed, after amortisation and one-off charges; the "
                        "forecast is revenue less the model's cost ratios",
    "free_cash_flow": "reported is operating cash flow less capital spending; the forecast "
                      "is before interest, with plant at the model's own rule",
    "capex": "the forecast is what the valuation already takes out of cash flow: plant "
             "upkeep on each year's revenue and new plant on each year's added revenue",
    "cash_uses": "reported years are the cash flow statement's own lines; the forecast "
                 "carries plant and working capital only, and what is left is not "
                 "allotted to dividends, buybacks or deals",
}


def _mm(value) -> float | None:
    return None if value is None else value / 1e6


def reported(conn, company_id: int, first: int, last: int) -> dict:
    """{measure: {fiscal year: value in millions}} as filed. Capital spending is a
    positive outlay; free cash flow is operating cash flow less it, for the years both
    are on file. The uses of cash (deals, intangibles bought, dividends, buybacks) are
    outlays too, and a line the filer does not tag is absent, never nil."""
    out = {}
    for measure, metric in REPORTED.items():
        series = IA.fy_series(conn, company_id, metric, first, last)
        out[measure] = {y: (abs(_mm(r["value"])) if measure == "capex" else _mm(r["value"]))
                        for y, r in series.items()}
    for measure, metric in USES.items():
        series = IA.fy_series(conn, company_id, metric, first, last)
        out[measure] = {y: (_mm(r["value"]) if measure in SIGNED
                            else abs(_mm(r["value"]))) for y, r in series.items()}
    ocf = out["operating_cash_flow"]
    out["free_cash_flow"] = {y: ocf[y] - out["capex"][y] for y in ocf if y in out["capex"]}
    return out


def capex_rule(conn, ticker: str) -> dict:
    """The plant charge the valuation carries for this company, as two rates. ``reason``
    is set, and the rates None, where the filer's lines are not on file."""
    got = RC.measure(conn, ticker)
    if got.get("cut") is None:
        return {"upkeep_rate": None, "growth_rate": None, "reason": got.get("reason")}
    charge = conn.execute(
        """SELECT a.source FROM assumptions a JOIN assets s ON s.id = a.asset_id
             JOIN companies c ON c.id = s.owner_company_id
            WHERE c.ticker = ? AND a.key = 'other_costs_pct' LIMIT 1""",
        (ticker.upper(),)).fetchone()
    at_replacement, _ = GI.carries(charge["source"] if charge else None)
    pool = GI.pooled(conn)
    window = f"{got['first']} to {got['last']}"
    if at_replacement and pool.get("capex") is not None:
        upkeep = got["depreciation"] / got["revenue"]
        return {"upkeep_rate": upkeep, "growth_rate": pool["capex"], "reason": None,
                "at_replacement": True, "window": [got["first"], got["last"]],
                "basis": (f"plant upkeep at {upkeep:.1%} of revenue, the company's own plant "
                          f"depreciation over its revenue, {window}; new plant at "
                          f"{pool['capex']:.3f} per dollar of revenue added, measured "
                          f"across {pool['counted']} filers")}
    full = got["capex"] / got["revenue"]
    return {"upkeep_rate": full, "growth_rate": 0.0, "reason": None,
            "at_replacement": False, "window": [got["first"], got["last"]],
            "basis": (f"{full:.1%} of revenue, the company's own capital spending over its "
                      f"revenue, {window}; its charge was not restated to plant "
                      f"depreciation, so it carries the whole of it")}


def added(revenue: dict, opening) -> dict:
    """{year: the revenue that year adds over the one before}, never negative: a year
    that shrinks builds nothing and is not credited. The first year is measured against
    ``opening``, what the company already sells."""
    out, previous = {}, opening
    for year in sorted(revenue):
        out[year] = max(0.0, revenue[year] - previous) if previous is not None else 0.0
        previous = revenue[year]
    return out


ASSUMED = "Launches the model assumes"


def _assumed(sotp: dict) -> dict | None:
    """The launches the sum of the parts credits to R&D, as a part. Each cost line is the
    engine's own identity, the ratio it applies times the year's revenue
    (``future_pipeline.simulate``); the cash flow is before the plant its growth takes,
    as every other part's is, and that plant rides beside it."""
    future = sotp.get("future") or {}
    flows, ratios = future.get("flows") or [], future.get("ratios") or {}
    if not flows or not future.get("value"):
        return None
    rows = []
    for flow in flows:
        revenue = flow.get("revenue") or 0.0
        costs = {k: revenue * (ratios.get(k) or 0.0) for k in ("cogs", "sga", "rd", "other")}
        ebit = revenue - sum(costs.values())
        invested = flow.get("growth_investment") or 0.0
        rows.append({"revenue": revenue, **costs, "ebit": ebit,
                     "tax": max(0.0, ebit * (ratios.get("tax") or 0.0)),
                     "fcff": (flow.get("fcff") or 0.0) + invested,
                     "growth_investment": invested})
    return {"id": None, "name": ASSUMED, "kind": "assumed", "pos": 1.0, "counted": True,
            "years": [f["year"] for f in flows], "rows": rows, "row": future}


def _parts(verdict: dict) -> list:
    """Every modelled asset, every revenue line and the launches the model assumes as
    one shape. An asset the sum of the parts does not count (a placeholder) is carried
    and marked, so the page can show it without the totals including it."""
    parts = []
    for row in verdict.get("modelled") or []:
        parts.append({"id": row["asset_id"], "name": row["name"],
                      "counted": bool(row.get("counted", True)),
                      "kind": "marketed" if row.get("is_marketed") else "pipeline",
                      "pos": row.get("pos") if row.get("pos") is not None else 1.0,
                      "years": _years(row), "tail": row.get("terminal_tail"),
                      "rows": list(row.get("pnl_share") or []), "row": row})
    for stream in verdict.get("streams") or []:
        parts.append({"id": None, "name": stream.get("line"), "kind": "lines", "pos": 1.0,
                      "counted": True,
                      "years": _years(stream), "tail": stream.get("terminal_tail"),
                      "rows": list(stream.get("pnl_share") or []), "row": stream})
    assumed = _assumed(verdict.get("sotp") or {})
    if assumed:
        parts.append(assumed)
    for part in parts:
        part["modelled"] = min(len(part["years"]), len(part["rows"]))
    return parts


def _years(row: dict) -> list:
    """The years a part's P&L rows are for: the valuation window. A model that opens
    before the valuation year (a product launched since) has more ``years`` than rows,
    and pairing the rows with those drew its cash flow two years early."""
    return list(row.get("dcf_years") or row.get("years") or [])


def horizon(parts: list, first: int) -> int:
    """The last year drawn: ten years at the least, and past the last loss of
    exclusivity that matters by enough to see the fall."""
    named = [p for p in parts if p["id"] is not None and p["counted"]]
    value = sum(max(p["row"].get("per_share") or 0.0, 0.0) for p in named)
    cliffs = [p["row"]["loe_year"] for p in named
              if p["row"].get("loe_year") and value
              and (p["row"].get("per_share") or 0.0) / value >= MATTERS]
    end = max([first + HORIZON_YEARS - 1] + [c + CLIFF_YEARS for c in cliffs])
    return min(end, first + MAX_YEARS - 1)


def carry(part: dict, through: int) -> None:
    """Extend a part's years and rows to ``through`` on the path its terminal value
    takes. Every line of the final year's P&L moves with its revenue, which is the
    stream the terminal multiple discounts. No tail, no terminal value, nothing carried."""
    years, rows, tail = part["years"], part["rows"], part.get("tail")
    if not years or not rows or not tail or through <= years[-1]:
        return
    last, final = years[len(rows) - 1], rows[-1]
    later = list(range(last + 1, through + 1))
    path = {y: 0.0 for y in later}
    for share, loe, in_base in tail.get("parts") or []:
        for y, factor in forecast.terminal_path(
                tail.get("growth") or 0.0, last, loe, in_base, tail.get("year1_pct"),
                tail.get("decay_pct"), tail.get("late_decay_pct"),
                tail.get("late_from_year"), later).items():
            path[y] += share * factor
    del years[len(rows):]
    for y in later:
        years.append(y)
        rows.append({k: (v * path[y] if isinstance(v, (int, float)) else v)
                     for k, v in final.items()})


GROUPS = ("marketed", "lines", "pipeline", "assumed")


def total(parts: list, key: str, weighted: bool, kind: str | None = None,
          modelled: bool = False) -> dict:
    """{year: the sum of one P&L key over the parts}, at each part's odds when weighted.
    ``modelled`` leaves out the years a part is carried past its model."""
    out: dict = {}
    for part in parts:
        if not part["counted"] or (kind is not None and part["kind"] != kind):
            continue
        odds = part["pos"] if weighted else 1.0
        rows = part["rows"][:part.get("modelled", len(part["rows"]))] if modelled \
            else part["rows"]
        for year, row in zip(part["years"], rows):
            out[year] = out.get(year, 0.0) + (row.get(key) or 0.0) * odds
    return out


def _case(parts: list, weighted: bool, opening, share, rule: dict) -> dict:
    """One basis: every measure by year for the company and for each group."""
    book = [p for p in parts if p["kind"] != "assumed"]
    revenue = total(parts, "revenue", weighted)
    company = {m: total(parts, k, weighted) for m, k in ROW_KEY.items()}
    # The book's growth charge is laid on its net growth, not on any one asset, so it
    # comes off the total here as the valuation takes it off the value. The assumed
    # launches carry their own, charged on the growth they add to the book's.
    # On the modelled years alone, as the valuation charges it: the years a product
    # is carried are inside its terminal value, which takes no growth charge.
    grown = added(total(book, "revenue", weighted, modelled=True), opening)
    own = total(parts, "growth_investment", weighted, "assumed")
    company["growth_investment"] = {y: (share or 0.0) * grown.get(y, 0.0) + own.get(y, 0.0)
                                    for y in revenue}
    company["free_cash_flow"] = {y: company["free_cash_flow"].get(y, 0.0)
                                 - company["growth_investment"][y] for y in revenue}
    if rule.get("upkeep_rate") is not None:
        # New plant is the capex share of the growth charge the valuation takes.
        new = (rule["growth_rate"] / share) if share else 0.0
        company["capex"] = {y: rule["upkeep_rate"] * revenue[y]
                            + new * company["growth_investment"][y] for y in revenue}
    else:
        company["capex"] = None
    groups = {kind: {m: total(parts, k, weighted, kind)
                     for m, k in ROW_KEY.items()}
              for kind in GROUPS}
    return {"company": company, "groups": groups}


def _evidence(conn, asset_ids: list) -> dict:
    """{asset id: {evidence, partial evidence, assumption}} by count of base rows."""
    out = {a: {"evidence": 0, "partial evidence": 0, "assumption": 0} for a in asset_ids}
    if not asset_ids:
        return out
    marks = ",".join("?" * len(asset_ids))
    for row in conn.execute(
            f"SELECT asset_id, evidence, COUNT(*) AS n FROM assumptions"
            f" WHERE asset_id IN ({marks}) AND scenario = 'base'"
            f" GROUP BY asset_id, evidence", asset_ids):
        out[row["asset_id"]][evidence.evidence_class(row["evidence"])] += row["n"]
    return out


def _asset_reported(conn, asset_ids: list, first: int) -> dict:
    """{asset id: {fiscal year: reported revenue in millions}} for full years."""
    out: dict = {a: {} for a in asset_ids}
    if not asset_ids:
        return out
    marks = ",".join("?" * len(asset_ids))
    for row in conn.execute(
            f"SELECT asset_id, fiscal_year, value FROM asset_revenue"
            f" WHERE asset_id IN ({marks}) AND period = 'FY' AND fiscal_year >= ?"
            f"   AND value IS NOT NULL", [*asset_ids, first]):
        out[row["asset_id"]][row["fiscal_year"]] = _mm(row["value"])
    return out


def build(conn, db_path, ticker: str, verdict: dict, today: dt.date | None = None) -> dict:
    """The board for one company, from its verdict. {ok: False, why} where the company
    has no sum of the parts to lay out."""
    today = today or dt.date.today()
    base = {"ticker": ticker.upper(), "name": (verdict or {}).get("name")}
    sotp = (verdict or {}).get("sotp") or {}
    parts = _parts(verdict or {})
    if not (verdict or {}).get("ok") or not [p for p in parts if p["kind"] != "assumed"]:
        return {**base, "ok": False,
                "why": "No asset carries a model, so there is no forecast to lay out."}
    if not any(p["counted"] for p in parts if p["kind"] != "assumed"):
        return {**base, "ok": False,
                "why": "Every modelled asset rests on a placeholder, so nothing is counted "
                       "and there is no company forecast to lay out."}
    company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                           (ticker.upper(),)).fetchone()
    last_reported = (sotp.get("last_reported") or {}).get("fiscal_year")
    counted = [p for p in parts if p["counted"] and p["kind"] != "assumed"]
    f_first = min(y for p in counted for y in p["years"])
    f_last = horizon(parts, f_first)
    ends = [p["years"][p["modelled"] - 1] for p in counted if p["modelled"]]
    for part in parts:
        carry(part, f_last)
    carried_from = (min(ends) + 1) if ends and min(ends) < f_last else None
    r_last = last_reported or (f_first - 1)
    r_first = r_last - HISTORY_YEARS + 1
    rule = capex_rule(conn, ticker)
    growth = sotp.get("growth_investment") or {}
    opening, share = growth.get("opening"), growth.get("share")
    cases = {name: _case(parts, weighted, opening, share, rule)
             for name, weighted in (("weighted", True), ("success", False))}

    assets = [p for p in parts if p["id"] is not None]
    assumed = next((p for p in parts if p["kind"] == "assumed"), None)
    ids = [p["id"] for p in assets]
    mix = _evidence(conn, ids)
    areas = product_areas.areas_for(db_path, ids) if ids else {}
    seen = _asset_reported(conn, ids, r_first)
    placeholder = {p_["asset_id"] for p_ in (verdict.get("placeholders") or [])}
    value_total = sum((p["row"].get("per_share") or 0.0) for p in assets
                      if p["counted"] and (p["row"].get("per_share") or 0.0) > 0)

    def asset(part: dict) -> dict:
        row, grades = part["row"], mix[part["id"]]
        n = sum(grades.values())
        gate = row.get("gate") or {}
        return {
            "asset_id": part["id"], "name": part["name"], "kind": part["kind"],
            "counted": part["counted"],
            "pos": part["pos"], "per_share": row.get("per_share"),
            "share_of_value": ((row.get("per_share") or 0.0) / value_total
                               if (value_total and part["counted"]) else None),
            "per_share_success": row.get("per_share_success"),
            "peak_revenue": row.get("peak_revenue"), "peak_year": row.get("peak_year"),
            "loe_year": row.get("loe_year"), "area": areas.get(part["id"]),
            "next_date": gate.get("date"), "next_label": gate.get("label"),
            "placeholder": part["id"] in placeholder,
            "evidence": grades,
            "assumption_share": (grades["assumption"] / n) if n else None,
            "years": part["years"],
            "modelled_to": (part["years"][part["modelled"] - 1] if part["modelled"]
                            else None),
            "series": {m: [r.get(k) for r in part["rows"]] for m, k in ROW_KEY.items()},
            "reported": seen.get(part["id"]) or {},
        }

    asset_rows = sorted((asset(p) for p in assets),
                        key=lambda a: -(a["per_share"] or 0.0))
    held = [a for a in asset_rows if a["counted"] and (a["per_share"] or 0.0) > 0
            and a["assumption_share"] is not None]
    weight = sum(a["per_share"] for a in held)
    # The share of the assets' value resting on judgement or convention: each asset's
    # value times the share of its inputs graded so, over the value of all of them.
    rests = (sum(a["per_share"] * a["assumption_share"] for a in held) / weight
             if weight else None)
    shares = verdict.get("diluted_shares")

    def per_share(mm):
        return (mm * 1e6 / shares) if (shares and mm is not None) else None

    future = sotp.get("future") or {}
    value = [("Products on sale", (sotp.get("marketed") or {}).get("per_share")),
             ("Named pipeline", (sotp.get("pipeline") or {}).get("per_share")),
             ("Other revenue lines", (sotp.get("lines") or {}).get("per_share")),
             ("Launches the model assumes", per_share(future.get("value"))),
             ("Plant for growth", growth.get("per_share")),
             ("Rolled forward to today", sotp.get("carry_per_share")),
             ("Net cash or debt", sotp.get("net_cash_per_share")),
             ("Other claims", sotp.get("other_claims_per_share") or None)]
    close, equity = verdict.get("close"), sotp.get("equity_per_share")
    coverage = verdict.get("coverage") or {}
    return {
        **base, "ok": True, "currency": (sotp.get("fx") or {}).get("currency"),
        "strip": {"value": equity, "price": close, "close_date": verdict.get("close_date"),
                  "gap": (equity / close - 1.0) if (equity is not None and close) else None,
                  "twelve_month": sotp.get("forward_12m"),
                  "coverage": coverage.get("share"), "rests_on_assumption": rests,
                  "next_catalyst": verdict.get("next_catalyst")},
        "years": {"reported": list(range(r_first, r_last + 1)),
                  "forecast": list(range(f_first, f_last + 1)),
                  # the first year some part is carried on its terminal path
                  "carried_from": carried_from},
        "reported": reported(conn, company["id"], r_first, r_last) if company else {},
        "weighted": cases["weighted"], "success": cases["success"],
        "assets": asset_rows,
        "lines": [{"name": p["name"], "per_share": p["row"].get("per_share"),
                   "years": p["years"],
                   "series": {m: [r.get(k) for r in p["rows"]] for m, k in ROW_KEY.items()}}
                  for p in parts if p["kind"] == "lines"],
        "assumed": ({"name": ASSUMED, "per_share": per_share(future.get("value")),
                     "first_launch_year": future.get("first_launch_year"),
                     "rate": future.get("rate_used"), "lag_years": future.get("lag_years")}
                    if assumed else None),
        "value": {"equity_per_share": equity,
                  "source": [{"label": lab, "per_share": v} for lab, v in value
                             if v is not None]},
        "capex_rule": rule, "basis": BASIS,
        "not_valued": [u.get("name") for u in (coverage.get("unmodelled") or [])],
    }
