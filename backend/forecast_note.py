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

    if v.get("mode") in ("marketed", "franchise") and not v.get("loe_year"):
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
            f"The answer rests on {top['lever']} more than anything else: a fifth either "
            f"way moves it {_mm(abs(top['span']) / 2)}. "
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


def company_headline(v: dict) -> str:
    if not v.get("per_share"):
        return (f"{v.get('name') or v.get('ticker')} has no modelled asset that "
                f"computes yet, so there is no company number to state.")
    price = v.get("close")
    lead = (f"{v['ticker']}'s modelled pipeline is worth "
            f"{_per_share(v['per_share'])} a share")
    if price:
        lead += (f" against a {_per_share(price)} share price, "
                 f"{v['pct_of_price']:.1%} of the company")
    coverage = v.get("coverage") or {}
    if coverage.get("share") is not None:
        lead += (f". That is {len(v.get('modelled') or [])} asset"
                 f"{'s' if len(v.get('modelled') or []) != 1 else ''} out of a book: "
                 f"the model covers {coverage['share']:.1%} of FY"
                 f"{coverage['fiscal_year']} product revenue")
        biggest = (coverage.get("unmodelled") or [None])[0]
        if biggest and biggest.get("share"):
            lead += (f", and {biggest['name']} alone is {biggest['share']:.0%} of what "
                     f"it does not")
    return lead + "."


def company_body(v: dict) -> list[str]:
    out = []
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
