"""The company-facts parser, shared by every source that produces XBRL facts.

EDGAR's company facts are one shape: ``{"facts": {taxonomy: {concept: {"units": {unit:
[entries]}}}}}``, each entry carrying ``start``, ``end``, ``val``, ``form`` and ``filed``.
Everything that turns that shape into the three statements lives here, so a second
source can reach the same lines by producing the same shape. The ESEF fetcher does that
for filers the SEC never sees: an annual report filed in the European Single Electronic
Format is tagged in the same ``ifrs-full`` taxonomy a 20-F is, so Bayer's revenue
resolves through the candidate list Novo's already does.

Pure: no network, no database.
"""

from __future__ import annotations

import datetime as dt

import statements

# The line map is the single source of truth for which concepts belong to which line;
# these three are named here because the snapshot payload and comps read them by key.
METRIC_CANDIDATES = {
    key: list(statements.LINES_BY_KEY[key].candidates)
    for key in ("Revenues", "NetIncomeLoss", "ResearchAndDevelopmentExpense")
}
CASH_CANDIDATES = list(statements.LINES_BY_KEY["CashAndEquivalents"].candidates)
DEBT_COMBINED_CANDIDATES = [("us-gaap", "DebtLongtermAndShorttermCombinedAmount"),
                            # IFRS filers tag one total instead of a split, which
                            # is why Novo, GSK and Sanofi carried no debt at all.
                            ("ifrs-full", "Borrowings")]

# How many recent periods of each line to store. Company facts already carry the full
# history in one response, so raising these costs storage rather than extra EDGAR calls.
# Instants get the largest budget because a balance sheet date lands every quarter.
# One more fiscal year is kept than the six shown: the seventh is the base the oldest
# shown year's year-over-year growth divides by, so the growth and margin lines on the
# trend start together instead of the growth line missing its first year.
# Company facts carry the whole history in one response, so the only cost of a longer one
# is storage. Twenty years reaches 2006 for a filer that has tagged XBRL since the mandate
# phased in, which is what makes a growth line long enough to show a patent cliff and a
# recovery rather than one cycle.
# It was seventeen, which cut off at exactly 2009 and threw away years the payload already
# carried: the FY2009 10-K tags its two comparative columns, so 2007 and 2008 are in the
# response for eight of the filers and were being dropped on the floor. The launch
# productivity rate divides fresh revenue by the R&D that bought it, and every year of R&D
# history it loses is a year the window cannot be moved back towards the spend that
# actually paid for the launches.
MAX_FISCAL_YEARS = 20
MAX_PERIODS = {statements.FY: MAX_FISCAL_YEARS, statements.Q: 40,
               statements.YTD: 40, statements.INSTANT: 60}


# --- pure parsing --------------------------------------------------------
def _concept(facts: dict, taxonomy: str, name: str) -> dict | None:
    return (facts.get(taxonomy) or {}).get(name)


def _entries_by_period(concept: dict, kind: str) -> dict[tuple[str, str], dict]:
    """Values of one period kind, deduped by period, keeping the latest filed.

    Deduping on filed date is what makes restatements resolve to the current number:
    a fiscal year appears in its own 10-K and again as the comparative in the next two,
    and the latest filing is the one that stands.
    """
    by_period: dict[tuple[str, str], dict] = {}
    for unit, entries in (concept.get("units") or {}).items():
        for e in entries:
            key = statements.classify_period(e)
            if key is None or key[1] != kind:
                continue
            current = by_period.get(key)
            if current is None or e.get("filed", "") > current["filed"]:
                by_period[key] = {"val": e["val"], "unit": unit, "end": key[0],
                                  "period_type": key[1],
                                  "months": statements.duration_label(e),
                                  "filed": e.get("filed", "")}
    return by_period


# A second concept may backfill years the winner lacks, but only if the two agree where
# they overlap. Filers switch tags mid-history and the old one keeps reporting the same
# number for a year or two, which is the signal that they mean the same thing.
_AGREEMENT_TOLERANCE = 0.01


def _agrees(series, winner) -> bool:
    """True when two annual series report the same value in every shared year.

    LLY moved R&D from the plain concept to the excluding-acquired one in 2021 and both
    read 6.93bn for that year, so the older series safely extends the newer one back to
    2020. JNJ reports both concurrently and they differ by two orders of magnitude,
    because the plain one holds acquired in-process R&D alone; that fails here and the
    winner is used by itself.
    """
    shared = set(series) & set(winner)
    if not shared:
        return False           # nothing to check it against, so do not trust it
    return all(abs(series[y]["val"] - winner[y]["val"])
               <= abs(winner[y]["val"]) * _AGREEMENT_TOLERANCE for y in shared)


# How far apart two values can sit at a handover and still be the same line. A revenue
# standard changing does not change the size of a company: JNJ reported 76.5bn in 2017
# under the old concept and 81.6bn in 2018 under the new one.
_HANDOVER_RATIO = 2.0
# And how far apart the two period ends can sit. One fiscal year, give or take the weeks
# a 52/53-week filer moves its year end by.
_HANDOVER_MIN_DAYS = 300
_HANDOVER_MAX_DAYS = 430


def _continues(series, winner) -> bool:
    """True when an annual series ends one year before the winner begins, at a like size.

    The agreement test refuses a series with no shared period, which is right for a
    concept measuring something else and wrong for a concept the filer stopped using. ASC
    606 moved revenue from SalesRevenueGoodsNet to RevenueFromContractWithCustomer on a
    date: JNJ tagged the old one to 2017 and the new one from 2018, and the two never
    overlap by construction. Without this its history starts in 2018.

    Two conditions, both needed. The two period ends have to be about a year apart, so an
    unrelated concept that happens to stop early cannot be glued on. And the values at the
    join have to be within a factor, so a line measuring a different quantity is refused
    even where its dates line up.
    """
    if not series or not winner or set(series) & set(winner):
        return False
    last, first = max(series), min(winner)
    try:
        gap = (dt.date.fromisoformat(first[0]) - dt.date.fromisoformat(last[0])).days
    except (ValueError, TypeError, IndexError):
        return False
    if not _HANDOVER_MIN_DAYS <= gap <= _HANDOVER_MAX_DAYS:
        return False
    old_value, new_value = abs(series[last]["val"]), abs(winner[first]["val"])
    if not old_value or not new_value:
        return False
    return max(old_value, new_value) / min(old_value, new_value) <= _HANDOVER_RATIO


def pick_kind_series(facts: dict, candidates, kind: str):
    """Build one period kind's series from the highest-priority concept that reaches
    the latest period, extended backwards by any candidate that agrees with it.

    Returns (unit, {period_key: entry}); (None, {}) when no candidate has data.

    Selection runs per kind rather than across all of them at once. A filer can tag its
    quarters under a newer concept than its years, and judging "reaches the latest
    period" over the pooled set would let the quarterly concept win and take the annual
    series down with it, since the two share no period to be checked for agreement.
    """
    per_candidate = []
    for taxonomy, name in candidates:
        concept = _concept(facts, taxonomy, name)
        if not concept:
            continue
        by_period = _entries_by_period(concept, kind)
        if by_period:
            per_candidate.append((name, by_period))
    if not per_candidate:
        return None, {}
    latest = max(k for _, by in per_candidate for k in by)
    name, chosen = next(((n, by) for n, by in per_candidate if latest in by),
                        per_candidate[0])

    merged = {k: dict(v, concept=name) for k, v in chosen.items()}
    for other_name, by_period in per_candidate:
        if by_period is chosen:
            continue
        extends = (_agrees(by_period, chosen)
                   or (kind == statements.FY and _continues(by_period, chosen)))
        if not extends:
            continue
        for key, entry in by_period.items():
            merged.setdefault(key, dict(entry, concept=other_name))  # winner keeps ties

    return chosen[max(chosen)]["unit"], merged


# Concepts a filer tags acquired in-process R&D under, the part the excluding concept
# leaves out and the plain concept keeps in.
_IPRD_CONCEPTS = ("ResearchAndDevelopmentInProcess",
                  "ResearchAndDevelopmentAssetAcquiredOtherThanThroughBusinessCombinationWrittenOff")


def backfill_rd_less_iprd(facts: dict, periods: dict) -> dict:
    """Years before a filer's excluding-acquired R&D series begins, read as its plain R&D
    less the acquired in-process R&D it tags for the same year.

    Vertex moved to the excluding concept in 2020, and the plain one includes acquired
    in-process R&D, so the two disagree and the agreement test refuses the older years.
    Its history on file started in 2020, and its launch record was measured on five years
    of R&D. But the difference is exactly what it tags as acquired in-process R&D:
    $1,829.5mm less $184.6mm is the excluding concept's $1,644.9mm for 2020, and 2021
    reconciles the same way. Where that holds in every year all three are tagged, the
    earlier years are the plain figure less the tagged in-process amount.

    A year is filled only where both are tagged, a zero included. The fill is refused
    outright if any year with all three tagged fails to reconcile. Gilead's 2018 plain
    figure sits $1,098mm above its excluding one against a tagged in-process nil, so its
    older years stay off. Returns the new entries, keyed like ``periods``.
    """
    us = facts.get("us-gaap") or {}
    fy = statements.FY
    winner = {int(end[:4]): e for (end, kind), e in periods.items()
              if kind == fy and e.get("concept") == "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"}
    if not winner or "ResearchAndDevelopmentExpense" not in us:
        return {}
    plain = {int(end[:4]): e for (end, _), e in
             _entries_by_period(us["ResearchAndDevelopmentExpense"], fy).items()}
    iprd: dict[int, float] = {}
    for name in _IPRD_CONCEPTS:
        if name in us:
            for (end, _), e in _entries_by_period(us[name], fy).items():
                iprd.setdefault(int(end[:4]), e["val"])
    shared = set(winner) & set(plain) & set(iprd)
    if not shared:
        return {}
    for year in shared:
        expected = winner[year]["val"]
        if abs(plain[year]["val"] - iprd[year] - expected) > abs(expected) * _AGREEMENT_TOLERANCE:
            return {}
    first = min(winner)
    out = {}
    for year, e in plain.items():
        if year >= first or year not in iprd:
            continue
        out[(e["end"], fy)] = dict(e, val=e["val"] - iprd[year],
                                   concept="ResearchAndDevelopmentExpense less in-process R&D")
    return out


def rd_less_expensed_iprd(facts: dict, periods: dict) -> dict:
    """Every fiscal year of the R&D line with the acquired in-process R&D inside it taken
    out, keyed like ``periods``.

    Launch productivity divides the revenue R&D bought by the R&D that bought it, and an
    asset purchase expensed as in-process R&D is capital allocation, not research: the
    cost charge already treats deal payments that way. Merck expenses them inside R&D,
    $11.4bn of its $30.5bn in 2023, so its research read a third larger than it was, while
    AbbVie, Pfizer and Lilly present them on a line of their own and report R&D without.

    Only a year the R&D line took from the plain concept is netted, by the in-process
    amount tagged for that year. The excluding concept and the backfilled fill already
    leave it out. A filer whose plain and excluding figures agree in a year it tags
    in-process R&D is presenting that R&D elsewhere, so nothing of it is netted: Lilly's
    2021 plain and excluding R&D are both $6,931mm against $970mm tagged.
    """
    us = facts.get("us-gaap") or {}
    fy = statements.FY
    iprd: dict[int, float] = {}
    for name in _IPRD_CONCEPTS:
        if name in us:
            for (end, _), e in _entries_by_period(us[name], fy).items():
                if e["val"]:
                    iprd.setdefault(int(end[:4]), e["val"])
    annual = {key: e for key, e in periods.items() if key[1] == fy}
    if not annual:
        return {}
    excluding = "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"
    if iprd and excluding in us and "ResearchAndDevelopmentExpense" in us:
        plain = {int(end[:4]): e["val"] for (end, _), e in
                 _entries_by_period(us["ResearchAndDevelopmentExpense"], fy).items()}
        excl = {int(end[:4]): e["val"] for (end, _), e in
                _entries_by_period(us[excluding], fy).items()}
        for year in set(plain) & set(excl) & set(iprd):
            if abs(plain[year] - excl[year]) <= abs(excl[year]) * _AGREEMENT_TOLERANCE:
                iprd = {}
                break
    out = {}
    for key, e in annual.items():
        year = int(e["end"][:4])
        amount = iprd.get(year)
        if e.get("concept") == "ResearchAndDevelopmentExpense" and amount and 0 < amount < e["val"]:
            out[key] = dict(e, val=e["val"] - amount,
                            concept="ResearchAndDevelopmentExpense less expensed in-process R&D")
        else:
            out[key] = dict(e)
    return out


def pick_annual_series(facts: dict, candidates):
    """The fiscal-year series, keyed by year. Returns (unit, {year: {'val','end'}})."""
    unit, series = pick_kind_series(facts, candidates, statements.FY)
    by_year = {int(end[:4]): {"val": e["val"], "end": e["end"]}
               for (end, _), e in series.items()}
    return unit, by_year


def instant_series(facts: dict, candidates):
    """(unit, {period_key: entry}) for a balance sheet line, at every date tagged."""
    return pick_kind_series(facts, candidates, statements.INSTANT)


def select_instant(facts: dict, candidates, at: str):
    """The value of a balance sheet line on one date, or (None, None)."""
    unit, series = instant_series(facts, candidates)
    entry = series.get((at, statements.INSTANT))
    return (entry["val"], entry["unit"]) if entry else (None, None)


# The current portion of debt, in priority order. Filers move between these by period:
# JNJ tags DebtCurrent at its year ends and ShortTermBorrowings at its quarters. They go
# through the same agreement check as any other line, so a filer that tags two of them
# at once only has them merged when they match where they overlap.
DEBT_CURRENT_CANDIDATES = [("us-gaap", "DebtCurrent"),
                           ("us-gaap", "LongTermDebtCurrent"),
                           ("us-gaap", "ShortTermBorrowings")]


def total_debt_series(facts: dict) -> dict[str, dict]:
    """Total debt at every date it resolves, as {end: {'val','unit','concept'}}.

    Three bases, in order: long-term non-current plus the current portion, the single
    combined tag, then the single long-term tag. The basis reaching the latest date
    wins the whole series and the others only fill dates it lacks, and then only where
    they agree with it. Resolving each date independently instead reads as a debt
    move that is really a tag change: Lilly tags the combined amount at year ends only,
    which put a 1.6bn step into every fourth quarter of an otherwise clean series.

    The two bases do reconcile for Lilly, exactly, once DebtCurrent is in the ladder:
    40.868 non-current plus 1.635 current is the 42.503 the combined tag reports.
    """
    _, noncurrent = instant_series(facts, [("us-gaap", "LongTermDebtNoncurrent")])
    _, current = instant_series(facts, DEBT_CURRENT_CANDIDATES)
    combined_unit, combined = instant_series(facts, DEBT_COMBINED_CANDIDATES)
    single_unit, single = instant_series(facts, [("us-gaap", "LongTermDebt")])

    split = {}
    for key, entry in noncurrent.items():
        near = current.get(key)
        # A filer that tags a current portion somewhere but not on this date has a gap
        # in its tagging, not zero short-term debt. Adding zero would understate the
        # total and read as a paydown, so the date is left out instead.
        if near is None and current:
            continue
        split[key] = {"val": entry["val"] + (near["val"] if near else 0),
                      "unit": entry["unit"],
                      "concept": "LongTermDebtNoncurrent + current portion"}

    bases = [(b, u) for b, u in ((split, None),
                                 (combined, combined_unit),
                                 (single, single_unit)) if b]
    if not bases:
        return {}
    latest = max(k for b, _ in bases for k in b)
    chosen, chosen_unit = next(((b, u) for b, u in bases if latest in b), bases[0])

    merged = dict(chosen)
    for base, _ in bases:
        if base is chosen or not _agrees(base, chosen):
            continue
        for key, entry in base.items():
            merged.setdefault(key, entry)

    return {end: {"val": e["val"], "unit": e.get("unit") or chosen_unit,
                  "concept": e.get("concept", "LongTermDebt")}
            for (end, _), e in merged.items()}


def select_total_debt(facts: dict, fy_end: str):
    """Total debt at one date, as (value, unit); (None, None) when nothing resolves."""
    entry = total_debt_series(facts).get(fy_end)
    return (entry["val"], entry["unit"]) if entry else (None, None)


def latest_shares(facts: dict) -> dict | None:
    concept = _concept(facts, "dei", "EntityCommonStockSharesOutstanding")
    if not concept:
        return None
    best = None
    for entries in (concept.get("units") or {}).values():
        for e in entries:
            end = e.get("end")
            if not end:
                continue
            key = (end, e.get("filed", ""))
            if best is None or key > best[0]:
                best = (key, e["val"], end)
    return {"as_of": best[2], "val": int(best[1])} if best else None


def _trim(periods: dict) -> dict:
    """Keep the most recent N periods of each kind, N per MAX_PERIODS."""
    kept: dict = {}
    for kind, limit in MAX_PERIODS.items():
        of_kind = sorted((k for k in periods if k[1] == kind), reverse=True)[:limit]
        kept.update({k: periods[k] for k in of_kind})
    return kept


def parse_statements(payload: dict) -> dict:
    """Every reported line at every period the filer tags. Pure.

    Lines the filer does not tag are absent from the result, not zero. Lines that exist
    only as arithmetic on other lines (free cash flow, net debt) are not computed here:
    this function returns reported facts and nothing else.
    """
    facts = payload.get("facts") or {}
    lines: dict[str, dict] = {}
    for line in statements.LINES:
        if not line.candidates:
            continue                       # derived, or resolved by its own ladder
        kinds = ((statements.INSTANT,) if line.kind == "instant"
                 else statements.DURATION_TYPES)
        unit, periods = None, {}
        for kind in kinds:
            kind_unit, series = pick_kind_series(facts, line.candidates, kind)
            periods.update(series)
            # The annual series names the unit when there is one, so a line whose
            # quarters are tagged in a different unit cannot rename the column.
            if kind_unit and (unit is None or kind == statements.FY):
                unit = kind_unit
        if line.resign:
            periods = {key: (dict(entry, val=-entry["val"])
                             if entry.get("concept") in line.resign else entry)
                       for key, entry in periods.items()}
        if line.key == "ResearchAndDevelopmentExpense" and periods:
            for key, entry in backfill_rd_less_iprd(facts, periods).items():
                periods.setdefault(key, entry)
        if periods:
            lines[line.key] = {"unit": unit, "periods": _trim(periods)}

    rd = lines.get("ResearchAndDevelopmentExpense")
    if rd:
        net = rd_less_expensed_iprd(facts, rd["periods"])
        if net:
            lines["ResearchLessExpensedIprd"] = {"unit": rd["unit"], "periods": net}

    debt = total_debt_series(facts)
    if debt:
        lines["TotalDebt"] = {
            "unit": next((d["unit"] for d in debt.values() if d["unit"]), None),
            "periods": _trim({
                (end, statements.INSTANT): {
                    "val": d["val"], "unit": d["unit"], "end": end,
                    "period_type": statements.INSTANT, "months": None,
                    "concept": d["concept"]}
                for end, d in debt.items()}),
        }

    revenue = lines.get("Revenues", {})
    income = lines.get("NetIncomeLoss", {})
    currency = revenue.get("unit") or income.get("unit")
    fy_ends = sorted(end for key in ("Revenues", "NetIncomeLoss")
                     for (end, kind) in lines.get(key, {}).get("periods", {})
                     if kind == statements.FY)
    return {
        "entity_name": payload.get("entityName"),
        "currency": currency,
        "fy_end": fy_ends[-1] if fy_ends else None,
        "lines": lines,            # {key: {'unit', 'periods': {(end, type): entry}}}
        "shares": latest_shares(facts),
    }


def _annual_from(parsed: dict, key: str) -> dict[int, dict]:
    periods = parsed["lines"].get(key, {}).get("periods", {})
    return {int(end[:4]): {"val": e["val"], "end": e["end"]}
            for (end, kind), e in periods.items() if kind == statements.FY}


def headline(parsed: dict) -> dict:
    """The three headline metrics plus the balance-sheet inputs to EV.

    A projection of parse_statements, kept because comps and the financials snapshot
    read this shape.
    """
    annual = {metric: _annual_from(parsed, metric) for metric in METRIC_CANDIDATES}
    fy_end = parsed["fy_end"]

    def at_fy_end(key):
        entry = parsed["lines"].get(key, {}).get("periods", {}).get(
            (fy_end, statements.INSTANT))
        return entry["val"] if entry else None

    return {
        "entity_name": parsed["entity_name"],
        "currency": parsed["currency"],
        "fy_end": fy_end,
        "annual": annual,          # {metric: {year: {'val','end'}}}
        "shares": parsed["shares"],
        "cash": at_fy_end("CashAndEquivalents") if fy_end else None,
        "total_debt": at_fy_end("TotalDebt") if fy_end else None,
    }


def parse_companyfacts(payload: dict) -> dict:
    return headline(parse_statements(payload))


def _latest(series: dict):
    """Latest {'val'} from an annual series, or None."""
    if not series:
        return None
    return series[max(series)]["val"]


def _latest_year(series):
    return max(series) if series else None


def financial_rows(parsed: dict) -> list[dict]:
    """``parse_statements`` output as rows for the ``financials`` table, less the source.

    One conversion for every fetcher that parses company facts, so a line stored from
    EDGAR and the same line stored from an ESEF filing cannot differ in shape.
    """
    rows: list[dict] = []
    for key, line in parsed["lines"].items():
        for (end, period_type), entry in line["periods"].items():
            rows.append(
                {
                    "metric": key,
                    "value": entry["val"],
                    # The tagged unit, not the reporting currency: EPS is USD/shares
                    # and share counts are shares, and calling either of those USD
                    # would put a currency symbol on a number that has none.
                    "unit": entry.get("unit") or line["unit"],
                    "period_end": end,
                    "period_type": period_type,
                    "fiscal_year": int(end[:4]),
                    # The months covered is a fact about the filing. Which fiscal
                    # quarter that makes it depends on the filer's year end, so the
                    # API works that out where the whole series is in hand.
                    "fiscal_period": entry.get("months"),
                }
            )
    shares = parsed["shares"]
    if shares:
        rows.append(
            {
                "metric": "SharesOutstanding",
                "value": shares["val"],
                "unit": "shares",
                "period_end": shares["as_of"],
                "period_type": "instant",
                "fiscal_year": int(shares["as_of"][:4]),
                "fiscal_period": None,
            }
        )
    return rows
