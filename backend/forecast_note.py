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

import re

import pos_granular

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


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _month(iso: str) -> str:
    """"Jan 2028" from 2028-01 or 2028-01-21; the text unchanged where it is neither."""
    match = re.match(r"^(\d{4})-(\d{2})", iso or "")
    if not match or not 1 <= int(match.group(2)) <= 12:
        return iso or ""
    return f"{_MONTHS[int(match.group(2)) - 1]} {match.group(1)}"


def _day(iso: str) -> str:
    """"26 Oct 2026" from a full date, else the month."""
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not match or not 1 <= int(match.group(2)) <= 12:
        return _month(iso)
    return f"{int(match.group(3))} {_MONTHS[int(match.group(2)) - 1]} {match.group(1)}"


def _gate_range(v: dict) -> str | None:
    """The range the next gate sets where no scenario sets one, or None. It leads with
    the number, names the event and its date, and says what holds after a miss."""
    gate = v.get("gate") or {}
    success, now = gate.get("per_share_success"), gate.get("per_share_now")
    if not v.get("gate_range") or success is None or now is None:
        return None
    failure = gate.get("per_share_failure")
    lost = "nil" if not failure else f"{_per_share(failure)} a share"
    date = gate.get("date")
    if gate.get("gate") == "nda_to_approval":
        when = f" (decision due {_day(date)})" if date else ""
        event = (f"{_per_share(success)} a share if the FDA approves it{when}, {lost} if "
                 f"it does not")
    else:
        when = ("" if not date else
                f", due since {_month(date)} with no readout on file," if gate.get("due")
                else f", est. {_month(date)},")
        event = (f"{_per_share(success)} a share if its {gate.get('label') or 'next gate'}"
                 f"{when} passes, {lost} if it fails")
    line = (f"No bear or bull case is on file, so the next gate sets the range: {event}, "
            f"against {_per_share(now)} now.")
    held = gate.get("held") or {}
    if held.get("open") and held.get("pos") is not None:
        line += " " + pos_granular.held_note(held["open"], held["pos"],
                                             bool(held.get("stated_governs")))
    return line


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
        # A pipeline asset's next gate sets a range the scenarios do not: derived from
        # its legs, never a scenario, and said as that.
        out.append(_gate_range(v) or
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


def _plain_name(name: str) -> str:
    """A product's name without the form in brackets: "Tryngolza (Autoinjector)" reads
    as "Tryngolza" in a sentence."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", str(name))


def _coverage_clause(v: dict) -> str:
    """How much of the business the figure in front of it actually covers.

    Never left out where there is anything to say. A model over a fraction of the
    revenue will always look small against a market capitalisation, and reading that as
    "the market is wrong" rather than "the model is thin" is the easiest mistake this
    page could invite. Moderna had no product rows, so coverage could not be measured
    and its "91% below the share price" went out with nothing behind it.
    """
    coverage = v.get("coverage") or {}
    s = v.get("sotp") or {}
    if coverage.get("share") is None:
        last = s.get("last_reported") or {}
        if not (s.get("marketed") or {}).get("n") and last.get("value"):
            return (f" No product on the market is modelled, so the figure leaves out "
                    f"what {v['ticker']} sells today: {_mm(last['value'])} of "
                    f"FY{last['fiscal_year']} revenue.")
        return ""
    basis = "reported" if coverage.get("basis") == "reported total" else "tagged"
    year = f"FY{coverage['fiscal_year']} {basis} revenue"
    counted = [m for m in v.get("modelled") or [] if m.get("counted", True)]
    streams = v.get("streams") or []
    if not counted and not streams:
        # Only the company's own rows are on file, and not every row is a product
        # (Wave's is a collaboration category), so this names a line, not a product.
        first = (coverage.get("unmodelled") or [None])[0]
        denominator = coverage.get("reported_revenue") or coverage.get("tagged_revenue")
        if first and first.get("revenue") and denominator:
            return (f" The largest revenue line on file is {_plain_name(first['name'])}, "
                    f"{first['revenue'] / denominator:.0%} of {year}.")
        return ""
    holds = f"The model's {_count(len(counted), 'asset')}"
    if streams:
        holds += f" and {_count(len(streams), 'revenue line')}"
    one = len(counted) == 1 and not streams
    # Glaxo's 99.976% printed as "100.0%" in the same sentence that named what the model
    # leaves out: what rounds to the whole is "all of", and nothing short of it prints
    # as 100.0%. Otherwise rounded as the tile above it is, so the two agree.
    share = coverage["share"]
    covered = "all of" if share >= 0.9995 else f"{min(share, 0.999):.1%} of"
    clause = f" {holds} {'covers' if one else 'cover'} {covered} {year}"
    # "X alone is Y% of what it leaves out" has to be a share of what is uncovered, not
    # of the whole: on a company covering 97%, Datroway's 0.1% of revenue printed as "0%
    # of what it does not". And only where the gap is worth naming: a share of a gap
    # under 1% of revenue says nothing.
    biggest = (coverage.get("unmodelled") or [None])[0]
    # From the absolutes, not by dividing one ratio by another: the covered share and
    # the row's share are measured against the same denominator, and taking their
    # quotient compounds both roundings into a figure that can exceed 100%.
    denominator = coverage.get("reported_revenue") or coverage.get("tagged_revenue")
    uncovered = (denominator - (coverage.get("modelled_revenue") or 0.0)
                 - (coverage.get("stream_revenue") or 0.0)) if denominator else None
    if (biggest and biggest.get("revenue") and uncovered and uncovered > 0
            and uncovered / denominator >= 0.01):
        of_the_gap = biggest["revenue"] / uncovered
        if of_the_gap >= 0.05:
            clause += (f"; {_plain_name(biggest['name'])} alone is {of_the_gap:.0%} of "
                       f"what it leaves out")
    return clause + "."


_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
          8: "eight", 9: "nine"}


def _count(n: int, noun: str) -> str:
    """"one asset", "two revenue lines", "32 assets": small counts read as words."""
    return f"{_WORDS.get(n, n)} {noun}{'' if n == 1 else 's'}"


def _money(value: float) -> str:
    """A per-share figure with its sign in front: "-$8.93", not "$-8.93", and a penny
    stock's fraction of a cent in four places rather than rounded to $0.00."""
    places = 4 if 0 < abs(value) < 0.01 else 2
    return f"{'-' if value < 0 else ''}${abs(value):,.{places}f}"


def _against(value: float, close: float) -> str:
    """Where a value sits against the price, in words: "7% above", "in line with", or "a
    small fraction of" where the percentage would read as 100% below."""
    gap = value / close - 1.0
    if round(gap, 2) == 0:
        return "in line with"
    if value >= 0 and gap < -0.95:
        return "a small fraction of"
    return f"{abs(gap):.0%} {'above' if gap > 0 else 'below'}"


_FRACTIONS = ((0.25, "a quarter"), (1 / 3, "a third"), (0.5, "half"), (2 / 3, "two-thirds"),
              (0.75, "three-quarters"))


def _share_words(share: float) -> str:
    """A share as a reader would say it: "about half" within two and a half points of
    it, the percentage otherwise. Five points let 45% read as "about half" for Merck
    and "45%" for Novo on the same page."""
    near, words = min(_FRACTIONS, key=lambda f: abs(f[0] - share))
    return f"about {words}" if abs(near - share) <= 0.025 else f"{share:.0%}"


def _verb(single: bool, value: float, add: str = "add", off: str = "take off") -> str:
    word = add if value >= 0 else off
    if not single:
        return word
    head, _, rest = word.partition(" ")
    return f"{head}s" + (f" {rest}" if rest else "")


def _join(clauses: list[str]) -> str:
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) == 2:
        return f"{clauses[0]}, and {clauses[1]}"
    return ", ".join(clauses[:-1]) + ", and " + clauses[-1]


def _sentence(text: str) -> str:
    return text[0].upper() + text[1:] + "."


def _sotp_headline(v: dict) -> str | None:
    """The company in a short paragraph an analyst would write: what it is worth a share
    against the price, where that value comes from, what the balance sheet does to it,
    and how much of the company the model covers. None where a part is missing.

    It says where the value comes from in shares ("about half", "most of the rest")
    rather than reading the bridge out item by item: the first rewrite still carried
    eleven to fourteen figures in a hundred words, which is the list the user asked to
    get away from, and the waterfall beside it already draws every step. The small steps
    (the investment growth needs, the roll forward to today, other claims) are left to
    the waterfall unless one is material, and then it is named with its figure.
    """
    s = v.get("sotp") or {}
    close = s.get("close")
    if not close:
        return None
    ticker = v["ticker"]
    equity = s.get("equity_per_share")
    whole = (equity if equity is not None
             else s.get("enterprise_today_per_share", s.get("enterprise_per_share")))
    if whole is None:
        return None

    # Where the value comes from: (value, who, how it is valued, one thing or many).
    m, p, lines = s.get("marketed") or {}, s.get("pipeline") or {}, s.get("lines") or {}
    future = s.get("future") or {}
    parts = []
    if m.get("n") and m.get("per_share") is not None:
        who = ("the single product" if m["n"] == 1
               else f"the {_count(m['n'], 'product')}")
        parts.append((m["per_share"], f"{who} already on the market", "", m["n"] == 1))
    if future.get("per_share") is not None:
        # The launches R&D already spent will buy, beyond the ones the book names: the
        # modelled pipeline, not the company's whole one, which on Incyte is not modelled.
        parts.append((future["per_share"], "launches beyond the modelled pipeline",
                      ", valued on what past R&D spending has bought", False))
    if p.get("n") and p.get("per_share") is not None:
        who = ("the single candidate" if p["n"] == 1
               else f"the {_count(p['n'], 'candidate')}")
        parts.append((p["per_share"], f"{who} in development",
                      " once weighted by its chance of approval" if p["n"] == 1
                      else " once each is weighted by its chance of approval", p["n"] == 1))
    if lines.get("n") and lines.get("per_share") is not None:
        # Revenue the book carries as a line because no product model holds it, which is
        # not to say no product earns it: Abbvie's lines are named products.
        parts.append((lines["per_share"], "revenue modelled as lines rather than products",
                      "", True))
    modelled = bool(parts)
    net = s.get("net_cash_per_share")
    # Cash a company holds is part of what its equity is worth, and on a small biotech it
    # is often most of it: Crispr's product and launches were $11.31 of a $31.92 value
    # and its net cash $19.77, so naming the product "the largest part" misled.
    if equity is not None and net is not None and net > 0 and modelled:
        parts.append((net, "net cash", "", True))
    parts.sort(key=lambda x: -x[0])

    if not modelled:
        out = [f"Nothing is modelled for {ticker} yet, so there is no value to set against "
               f"the {_money(close)} share price."]
        if net is not None:
            out.append(f"The balance sheet holds {_money(abs(net))} a share of "
                       f"{'net cash' if net >= 0 else 'net debt'}.")
        elif s.get("cash_per_share") is not None:
            # The gap is in the data, not the company: Alnylam carries convertible notes
            # that no debt row on file records.
            out.append(f"Cash on file comes to {_money(s['cash_per_share'])} a share; no "
                       f"debt figure is on file, so net cash is not stated.")
        return " ".join(out) + _coverage_clause(v)

    if equity is not None:
        if equity < 0:
            lead = (f"On the model, {ticker}'s equity is worth less than nothing, "
                    f"{_money(equity)} a share, against the {_money(close)} share price")
        else:
            lead = (f"On the model, {ticker}'s equity is worth {_money(equity)} a share, "
                    f"{_against(equity, close)} the {_money(close)} share price")
        if s.get("forward_12m") is not None and equity >= 0:
            lead += (f", and {_money(s['forward_12m'])} in twelve months, "
                     f"{_against(s['forward_12m'], close)} it")
        out = [lead + "."]
    else:
        out = [f"On the model, {ticker}'s enterprise value is {_money(whole)} a share, "
               f"{_against(whole, close)} the {_money(close)} share price."]

    # The largest source, and the second where it is most of what is left, as shares.
    value, who, how, single = parts[0]
    share = value / whole if whole > 0 else None
    used = 1
    if share is not None and 0.2 <= share <= 0.95:
        words = _share_words(share)
        if words.startswith("about"):
            line = f"{words.capitalize()} of that value comes from {who}{how}"
        else:
            line = f"{who} {'supplies' if single else 'supply'} {words} of that value{how}"
        if len(parts) > 1 and parts[1][0] > 0:
            value2, who2, how2, _ = parts[1]
            rest = whole - value
            ratio = value2 / rest if rest > 0 else None
            # Where the second part is more than is left, which happens when the balance
            # sheet takes a lot off, two shares would add past the whole ("56% ... and
            # about half" on Bristol), so it is given in dollars.
            words2 = ("most of the rest" if ratio is not None and 0.6 <= ratio <= 1.0
                      else _share_words(value2 / whole) if ratio is not None and ratio < 0.6
                      else f"another {_money(value2)} a share")
            line += "," if how else ""
            line += (f" and {words2} from {who2}{how2}" if words.startswith("about")
                     else f" and {who2} {words2}{how2}")
            used = 2
        out.append(_sentence(line))
    else:
        out.append(f"The largest part is {who}, at {_money(value)} a share{how}.")

    # What is left of the sum, the balance sheet, and any small step that is not small.
    clauses = [f"{w} {_verb(one, val)} {_money(abs(val))}{h}"
               for val, w, h, one in parts[used:]]
    if net is not None and net < 0:
        clauses.append(f"net debt takes off {_money(abs(net))} a share")
    material = []
    growth = (s.get("growth_investment") or {}).get("per_share")
    if growth:
        material.append((-abs(growth), "investment in plant and working capital for growth"))
    if s.get("carry_per_share"):
        material.append((s["carry_per_share"], "rolling the value forward to today"))
    if s.get("other_claims_per_share"):
        material.append((s["other_claims_per_share"], "other claims on the equity"))
    for val, what in material:
        if abs(val) > 0.1 * abs(whole):
            clauses.append(f"{what} {_verb(not what.startswith('other'), val)} "
                           f"{_money(abs(val))}")
    while clauses:
        out.append(_sentence(_join(clauses[:3])))
        clauses = clauses[3:]
    if not p.get("n") and future.get("per_share") is not None:
        out.append("No candidate in development is modelled yet.")
    if equity is None and s.get("cash_per_share") is not None:
        out.append(f"That is before {_money(s['cash_per_share'])} a share of cash; no debt "
                   f"figure is on file.")
    return " ".join(out) + _coverage_clause(v)


def _growth_whose(future: dict) -> str:
    """Who the long-run growth rate belongs to, so the sentence names its source.

    It is the ten-year breakeven from FRED wherever that series has been fetched, the
    book's own revenue-weighted growth only where it has not. Calling a Treasury
    breakeven "the growth the book assumes for its own products" credited a market
    rate to the analyst.
    """
    basis = (future.get("long_run_basis") or "").lower()
    if "t10yie" in basis or "breakeven" in basis:
        return "the market prices into the ten-year breakeven"
    if "revenue-weighted" in basis:
        return "the book assumes for its own products"
    return "the book is held to"


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
    future = s.get("future") or {}
    if future.get("per_share") is not None:
        own = future.get("own_rate")
        line = (f"The R&D every product is charged buys launches beyond the modelled "
                f"pipeline, and they are in the sum at {_per_share(future['per_share'])} "
                f"a share, at {future.get('rate_used', future['rate']):.2f} of annual "
                f"revenue per dollar of R&D. That rate blends {v['ticker']}'s own record "
                f"with the pool: across {future.get('pooled_filers')} large filers, "
                f"drugs approved in the last ten years earn {future['rate']:.2f} per "
                f"dollar spent over the ten years before")
        if own is not None:
            line += (f", {v['ticker']} earns {own:.2f} on "
                     f"{future.get('own_launches')} launches, and those launches earn "
                     f"its own record a {future.get('credibility', 0):.0%} weight")
        line += (f". Each year's R&D is taken to buy launches "
                 f"{future.get('lag_years')} years later, earning that rate for "
                 f"{future.get('life_years')} years before eroding, costed on the "
                 f"company's own ratios; the first arrive in "
                 f"{future.get('first_launch_year')}.")
        if (future.get("credited_share") or 1.0) < 1.0:
            # Two decimals of a percent, not none. This figure is usually expected
            # inflation off the ten-year breakeven, which moves in single basis
            # points: 2.34% and 2.49% both printed as "2%", so a reader watching it
            # move saw it stand still. And it is only the book's own assumption where
            # no market rate was fetched, so the sentence names whichever it is.
            line += (f" At that rate each generation of launches would buy "
                     f"{future['renewal']:.1f} times itself and compound past the "
                     f"{future.get('long_run_growth', 0):.2%} long-run growth "
                     f"{_growth_whose(future)}, so only "
                     f"{future['credited_share']:.0%} of the launches' R&D is credited "
                     f"with further launches; all of it is still charged.")
        if s.get("enterprise_book_only") is not None and s.get("close"):
            line += (" Without them the products on file are a run-off: every one fades "
                     "and erodes and nothing replaces it.")
        out.append(line)
    elif future.get("reason"):
        out.append(f"No value is taken for launches beyond the modelled pipeline: "
                   f"{future['reason']}.")
    if s.get("forward_12m") is not None and s.get("cost_of_equity") is not None:
        line = ""
        if s.get("valuation_anchor") and s.get("years_to_price"):
            line = (f"Every cash flow is discounted to {s['valuation_anchor']}, so the "
                    f"enterprise value is carried {s['years_to_price']:.2f} years to the "
                    f"{s.get('price_date')} close, adding "
                    f"{_per_share(s.get('carry_per_share'))} a share, before it is read "
                    f"against the price. ")
        line += (f"The twelve-month figure rolls today's value forward at a "
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
