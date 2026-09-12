"""The written half of the forecast: what the model says, in sentences.

A number in millions is not a view. An analyst's output is prose that states the answer,
the range around it, what the answer rests on and what will settle it, and this writes
exactly that from the facts ``forecast_view.verdict`` assembles.

Rules only, deliberately. ``insights.py`` earns its model call because it reads a month of
unstructured change and has to choose what matters. Here the facts are already chosen and
already numeric, so a model could only paraphrase them, and paraphrase is where invented
numbers come from. Every sentence below is a template over a value the engine computed.

It describes rather than recommends. What a share is worth against what it costs is the
model's output; what to do about it is not this file's business and not this product's.
"""

from __future__ import annotations

# A share of NPV that comes from the terminal value rather than the forecast horizon.
# Past this, the answer is mostly about what happens after the model stops looking.
TERMINAL_HEAVY = 0.35


def _mm(value) -> str:
    if value is None:
        return "an unknown amount"
    if abs(value) >= 1000:
        return f"${value / 1000:,.1f}bn"
    return f"${value:,.0f}mm"


def _per_share(value) -> str:
    return "an unknown amount" if value is None else f"${value:,.2f}"


def headline(v: dict) -> str:
    """The answer, in one sentence, leading with the number."""
    if v.get("per_share") is None:
        return (f"{v['name']} carries {_mm(v.get('owner_rnpv'))} of risk-adjusted value. "
                f"No diluted share count is on file, so it cannot be put per share.")
    price = v.get("close")
    if not price:
        return (f"{v['name']} carries {_per_share(v['per_share'])} a share of "
                f"risk-adjusted value, {_mm(v.get('owner_rnpv'))} in total.")
    return (f"{v['name']} carries {_per_share(v['per_share'])} a share of risk-adjusted "
            f"value against a {_per_share(price)} share price, so this one asset "
            f"explains {v['pct_of_price']:.1%} of what the company costs today.")


def body(v: dict) -> list[str]:
    """The paragraphs under the headline, each one a fact the engine produced."""
    out = []

    if v.get("mode") in ("marketed", "franchise") and not v.get("loe_year") \
            and not v.get("loe_in_base"):
        out.append(
            "No exclusivity is on file for this product, so nothing erodes and the "
            "revenue runs to the horizon and into the terminal value. For a marketed "
            "drug that is the most dangerous default in the model: set an LOE year, or "
            "read this as a deliberate perpetuity.")

    implied = v.get("implied_patients")
    if implied:
        # A price per course buys a course, not a year of treatment, and the count it
        # implies has to be named for what it is.
        unit = "courses" if (v.get("price_basis") or "") == "course" else "patients"
        out.append(
            f"At the net price on file the first forecast year implies "
            f"{implied:,.0f} {unit}. That is the check the price is for in a mode "
            f"valued off revenue: hold it against what the product actually treats, and "
            f"if it does not fit, one of the two is wrong.")

    horizon_end = v.get("horizon_end")
    if v.get("loe_year") and horizon_end and v["loe_year"] > horizon_end:
        out.append(
            f"Exclusivity runs to {v['loe_year']} and the forecast stops at "
            f"{horizon_end}, so the cliff never happens inside the window and the "
            f"terminal value carries revenue that has a known end date. Lengthen the "
            f"horizon past the LOE, or the perpetuity is doing work the patent will not.")

    if v.get("peak_revenue") and v.get("peak_year"):
        line = (f"Revenue peaks at {_mm(v['peak_revenue'])} in {v['peak_year']}")
        if v.get("loe_year"):
            line += (f", and exclusivity runs out in {v['loe_year']}"
                     + (f" on the {v['loe_basis']}" if v.get("loe_basis") else ""))
        out.append(line + ".")

    spread = v.get("spread") or {}
    bear, bull = spread.get("bear"), spread.get("bull")
    if not v.get("has_range"):
        out.append(
            "There is no bear or bull case on file, so this is one set of assumptions "
            "rather than a range. A scenario inherits the base and restates only what it "
            "changes, and nothing has been restated.")
    elif bear and bull and bear.get("per_share") and bull.get("per_share"):
        out.append(
            f"The scenarios run {_per_share(bear['per_share'])} to "
            f"{_per_share(bull['per_share'])} a share, a "
            f"{bull['per_share'] / bear['per_share']:.1f}x spread between the bear case "
            f"and the bull case. Same engine, three sets of assumptions.")

    levers = v.get("levers") or []
    if levers:
        top = levers[0]
        out.append(
            f"The answer rests on {top['lever']} more than anything else: "
            f"{top.get('step') or 'a fifth either way'} moves it "
            f"{_mm(abs(top['span']) / 2)}. "
            + (f"Next is {levers[1]['lever']} at {_mm(abs(levers[1]['span']) / 2)}."
               if len(levers) > 1 else ""))

    if v.get("terminal_share") and v["terminal_share"] > TERMINAL_HEAVY:
        out.append(
            f"{v['terminal_share']:.0%} of the NPV is terminal value, so most of this "
            f"number is about what happens after the forecast stops looking rather than "
            f"inside it.")

    catalyst = v.get("next_catalyst")
    if catalyst and catalyst.get("expected_date"):
        out.append(
            f"The next thing that settles any of it is a "
            f"{catalyst.get('catalyst_type') or 'catalyst'} on "
            f"{catalyst['expected_date']}.")

    if v.get("pos") is not None:
        line = f"Probability of success is {v['pos']:.0%}"
        if v.get("pos_basis"):
            line += f", {v['pos_basis']}"
        if v.get("wacc") is not None:
            line += f", discounted at {v['wacc'] * 100:.2f}%"
            if v.get("wacc_basis"):
                line += f" ({v['wacc_basis']})"
        out.append(line + ".")

    unsourced = v.get("unsourced") or []
    if unsourced:
        shown = ", ".join(unsourced[:4])
        more = f" and {len(unsourced) - 4} more" if len(unsourced) > 4 else ""
        out.append(
            f"Carrying no source, and therefore the analyst's own risk: {shown}{more}.")
    return out


def write(v: dict) -> dict:
    """The note, or the reason there is not one."""
    if not v or not v.get("ok"):
        missing = ", ".join((v or {}).get("missing") or ["assumptions"])
        return {"ok": False,
                "headline": f"No forecast for {(v or {}).get('name') or 'this asset'} yet.",
                "body": [f"Still missing: {missing}."]}
    return {"ok": True, "headline": headline(v), "body": body(v)}


# --- the company ------------------------------------------------------------
# An analyst covers a name, not a compound, so the per-asset calls have to add up. What
# makes the sum honest is stating in the same breath how much of the business it covers.

# Below this share of product revenue, the model is a sample of the company rather than a
# view of it, and the note says so before it says anything else.
THIN_COVERAGE = 0.25


def _coverage_clause(v: dict) -> str:
    """How much of the business the figure in front of it actually covers.

    Never optional. A model over a fraction of the revenue will always look small
    against a market capitalisation, and reading that as "the market is wrong" rather
    than "the model is thin" is the easiest mistake this page could invite. So no
    headline states a per-share number without this behind it.
    """
    coverage = v.get("coverage") or {}
    if coverage.get("share") is None:
        return ""
    counted = [m for m in v.get("modelled") or [] if m.get("counted", True)]
    streams = v.get("streams") or []
    parts = [f"{len(counted)} asset{'s' if len(counted) != 1 else ''}"]
    if streams:
        parts.append(f"{len(streams)} revenue line{'s' if len(streams) != 1 else ''} "
                     f"no asset carries")
    clause = (f" That is {' and '.join(parts)} out of a book: the model covers "
              f"{coverage['share']:.1%} of FY{coverage['fiscal_year']} "
              f"{'reported' if coverage.get('basis') == 'reported total' else 'tagged'}"
              f" revenue")
    # "X alone is Y% of what it does not" has to be a share of what is uncovered, not
    # of the whole. The row carries its share of total revenue, which is the same thing
    # only when coverage is thin: on a company covering 97%, Datroway's 0.1% of revenue
    # printed as "0% of what it does not", which is both wrong and says nothing.
    biggest = (coverage.get("unmodelled") or [None])[0]
    # From the absolutes, not by dividing one ratio by another: the covered share and
    # the row's share are measured against the same denominator, and taking their
    # quotient compounds both roundings into a figure that can exceed 100%.
    denominator = coverage.get("reported_revenue") or coverage.get("tagged_revenue")
    uncovered = (denominator - (coverage.get("modelled_revenue") or 0.0)
                 - (coverage.get("stream_revenue") or 0.0)) if denominator else None
    if biggest and biggest.get("revenue") and uncovered and uncovered > 0:
        of_the_gap = biggest["revenue"] / uncovered
        if of_the_gap >= 0.05:
            clause += (f", and {biggest['name']} alone is {of_the_gap:.0%} of what "
                       f"it does not")
    return clause + "."


def _sotp_headline(v: dict) -> str | None:
    """The company in one sentence: what the parts add up to per share, today and in
    twelve months, against the price. None where a part is missing."""
    s = v.get("sotp") or {}
    if not s.get("close"):
        return None
    if s.get("equity_per_share") is None:
        # The sum stops at enterprise value where the balance sheet cannot be added.
        if s.get("enterprise_per_share") is None:
            return None
        lead = (f"On the model {v['ticker']}'s business is worth "
                f"{_per_share(s['enterprise_per_share'])} a share of enterprise value "
                f"against a {_per_share(s['close'])} share price")
        if s.get("cash_per_share") is not None:
            lead += (f", before {_per_share(s['cash_per_share'])} a share of cash on "
                     f"hand that no debt line is filed against")
    else:
        lead = (f"On the model {v['ticker']}'s equity is worth "
                f"{_per_share(s['equity_per_share'])} a share today")
        if s.get("forward_12m") is not None:
            lead += f" and {_per_share(s['forward_12m'])} in twelve months"
        lead += f" against a {_per_share(s['close'])} share price"
        if s.get("upside") is not None:
            lead += f", {s['upside']:+.0%} on the twelve-month figure"
    parts = []
    m, p, lines = s.get("marketed") or {}, s.get("pipeline") or {}, s.get("lines") or {}
    if m.get("n"):
        parts.append(f"{m['n']} marketed product{'s' if m['n'] != 1 else ''} "
                     f"{_per_share(m['per_share'])}")
    if p.get("n"):
        parts.append(f"{p['n']} unapproved asset{'s' if p['n'] != 1 else ''} "
                     f"{_per_share(p['per_share'])} after probability")
    if lines.get("n"):
        parts.append(f"{lines['n']} line{'s' if lines['n'] != 1 else ''} no asset "
                     f"carries {_per_share(lines['per_share'])}")
    if s.get("net_cash_per_share") is not None:
        word = "net cash" if s["net_cash_per_share"] >= 0 else "net debt"
        parts.append(f"{word} {_per_share(s['net_cash_per_share'])}")
    return (lead + (": " + ", ".join(parts) if parts else "") + "."
            + _coverage_clause(v))


def _sotp_body(v: dict) -> list[str]:
    s = v.get("sotp") or {}
    out = []
    if not s:
        return out
    p = s.get("pipeline") or {}
    if p.get("n") and p.get("per_share_unrisked") and p.get("per_share") is not None:
        out.append(
            f"The pipeline is in the sum at its risk-adjusted value: "
            f"{_per_share(p['per_share_unrisked'])} a share before each asset's "
            f"probability of success, {_per_share(p['per_share'])} after it. An approved "
            f"product is counted at its own risk-adjusted value, which is its NPV unless "
            f"durability or reimbursement factors are on file.")
    if s.get("forward_12m") is not None and s.get("cost_of_equity") is not None:
        line = (f"The twelve-month figure rolls today's value forward at a "
                f"{s['cost_of_equity']:.1%} cost of equity")
        if s.get("dps"):
            line += (f" and takes off the {_per_share(s['dps'])} a share paid out as "
                     f"dividends in FY{s.get('dividends_year')}")
        out.append(line + ". It is arithmetic on the parts above it, not a target.")
    gaps = []
    if s.get("not_valued"):
        gaps.append("revenue with no forecast, " + ", ".join(
            f"{n['name']} ({_mm(n['revenue'])})" for n in s["not_valued"][:3]))
    coverage = v.get("coverage") or {}
    if coverage.get("untagged_revenue") and coverage.get("reported_revenue") and (
            coverage["untagged_revenue"] / coverage["reported_revenue"]) > 0.005:
        gaps.append(f"{_mm(coverage['untagged_revenue'] / 1e6)} of reported revenue "
                    f"with neither a product row nor a line")
    if s.get("upside") is not None and s["upside"] < -0.25:
        gaps.append("everything past the horizon: each product fades to its long-run "
                    "rate and erodes at its LOE, and nothing is counted for products "
                    "not yet in the pipeline table, so the figure is what today's book "
                    "is worth rather than what the company will find next")
    if gaps:
        out.append("What the model does not hold, and the price does: "
                   + "; ".join(gaps) + ".")
    for missing in s.get("missing") or []:
        out.append(f"Missing from the sum: {missing}.")
    return out


def company_headline(v: dict) -> str:
    whole = _sotp_headline(v)
    if whole:
        return whole
    if not v.get("per_share"):
        placeholders = v.get("placeholders") or []
        if placeholders:
            named = ", ".join(str(p.get("name")) for p in placeholders[:3])
            return (f"{v.get('name') or v.get('ticker')} has nothing counted yet: "
                    f"{named} {'draws' if len(placeholders) == 1 else 'draw'} on a "
                    f"placeholder uptake curve and stays out of the per-share number "
                    f"until a real ceiling is committed from the curve shaper.")
        return (f"{v.get('name') or v.get('ticker')} has no modelled asset that "
                f"computes yet, so there is no company number to state.")
    price = v.get("close")
    lead = (f"{v['ticker']}'s modelled pipeline is worth "
            f"{_per_share(v['per_share'])} a share")
    if price:
        lead += (f" against a {_per_share(price)} share price, "
                 f"{v['pct_of_price']:.1%} of the company")
    return lead + "." + _coverage_clause(v)


def company_body(v: dict) -> list[str]:
    out = _sotp_body(v)
    coverage = v.get("coverage") or {}
    if coverage.get("share") is not None and coverage["share"] < THIN_COVERAGE:
        out.append(
            "Read the share of price with that in mind. A model over a fraction of the "
            "revenue will always look small against a market capitalisation, and the "
            "answer to that is to point it at the rest rather than to conclude the "
            "market is wrong.")

    modelled = v.get("modelled") or []
    if len(modelled) > 1:
        ranked = ", ".join(f"{m['name']} at {_per_share(m['per_share'])}"
                           for m in modelled[:4] if m.get("per_share"))
        out.append(f"What is modelled, largest first: {ranked}.")

    unmodelled = coverage.get("unmodelled") or []
    if unmodelled:
        queue = ", ".join(f"{u['name']} ({_mm(u['revenue'] / 1e6)})"
                          for u in unmodelled[:4])
        out.append(f"What is not, by last year's revenue: {queue}. That is the work "
                   f"queue, in the order it would change the answer.")

    streams = v.get("streams") or []
    if streams:
        named = ", ".join(f"{s['line']} at {_per_share(s['per_share'])}"
                          if s.get("per_share") else s["line"] for s in streams[:4])
        out.append(f"Revenue no asset carries, modelled as its own line: {named}. "
                   f"These are what the filer reports and does not split, and without "
                   f"them the model could never reconcile to the total the company "
                   f"actually reported.")

    untagged = coverage.get("untagged_revenue")
    if untagged and coverage.get("reported_revenue") and (
            untagged / coverage["reported_revenue"]) > 0.005:
        out.append(f"{_mm(untagged / 1e6)} of FY{coverage['fiscal_year']} revenue, "
                   f"{untagged / coverage['reported_revenue']:.1%} of it, has neither a "
                   f"product row nor a line: it is reported in the total and nowhere "
                   f"else on file. Until it is named it is the part of the company the "
                   f"model cannot see.")
    elif coverage.get("basis") == "tagged rows":
        out.append("No reported total is on file for that year, so coverage is measured "
                   "against the product rows the data sets tag, which is a ceiling on "
                   "the company rather than the company.")

    placeholders = v.get("placeholders") or []
    if placeholders:
        named = ", ".join(str(p.get("name")) for p in placeholders[:4])
        out.append(f"Drawn and not counted: {named}. Each runs on a placeholder uptake "
                   f"curve, 5% of the eligible pool at peak and half of it by year four, "
                   f"which exists so there is a shape to argue with and is not a view. "
                   f"Their revenue is in the build, hatched; their value is left out of "
                   f"the per-share figure until a real ceiling is committed from the "
                   f"curve shaper.")

    for f in v.get("franchises") or []:
        members = " and ".join(f.get("members") or [])
        if f.get("problems"):
            out.append(
                f"The {members} franchise does not hold together: "
                f"{'; '.join(f['problems'])}. Until that is fixed the two are being "
                f"forecast against different pools and their revenue can be counted "
                f"twice, which is the whole thing a franchise is there to stop.")
        elif f.get("complete"):
            out.append(
                f"{members} are one franchise, not two products: they share a pool of "
                f"{_mm(f['pool'])} and their shares of it sum to 100% in every year. "
                f"Neither can be read alone, and neither has a growth rate. What is "
                f"forecast is the share, and the judgement in it is where that share "
                f"settles.")
        else:
            out.append(
                f"{members} share a pool of {_mm(f['pool'])} but hold only "
                f"{f['share_now']:.0%} of it between them. The rest belongs to members "
                f"that are not modelled, so this is a part of the franchise rather than "
                f"the franchise.")

    refused = v.get("refused") or []
    if refused:
        named = ", ".join(str(r.get("name") or r.get("asset_id")) for r in refused[:4])
        out.append(f"Started and not finished: {named}. Each has assumptions on file "
                   f"and something still missing.")

    catalyst = v.get("next_catalyst")
    if catalyst and catalyst.get("expected_date"):
        out.append(f"The next dated event on anything modelled is a "
                   f"{catalyst.get('catalyst_type') or 'catalyst'} on "
                   f"{catalyst['expected_date']}.")
    return out


def write_company(v: dict) -> dict:
    if not v or not v.get("ok"):
        return {"ok": False, "headline": "No company forecast yet.", "body": []}
    return {"ok": True, "headline": company_headline(v), "body": company_body(v)}
