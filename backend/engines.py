"""Three engines over one universe, and the rule that decides which one a company is on.

The split used to be two stages plus a modality tab, which put Abeona and AbbVie on the
same page and asked both the same questions. That is what produced the data gaps: the
portfolio view read 100% fresh for Abeona off 3.4m of product revenue, and cash runway
read blank for every company that sells anything. A metric its cohort cannot fill is not
a hole in the data, it is a question asked of the wrong company.

So the universe is partitioned exactly once, and each engine asks only what its cohort
can answer:

  Big pharma      where the revenue comes from and when it stops.
  Biotech         whether the next readout is funded and what reaches the market.
  Cell and gene   which platform, who is furthest, and who runs out of money first.

The rule, in order:

1. Revenue at or above PHARMA_MIN_REVENUE is major pharma. The threshold sits in the
   widest gap in the distribution, between Biogen at 9.9bn and Incyte at 5.1bn, so it is
   not a round number chosen to make a count come out.
2. A company with no financials at all cannot be placed by what it reports. Roche and
   Bayer are not SEC registrants, so EDGAR holds nothing for either, and both market
   more than PHARMA_MIN_REGISTER products. A marketed register that size is a major.
3. A cell or gene platform in its own filings, under PLATFORM_MAX_REVENUE of revenue, is
   a cell and gene developer. The revenue test is what keeps Vertex, Gilead and Bristol
   out of a startup engine, and Sarepta and BioNTech with them: they earn billions from
   products, so they read as product companies whatever the platform says.
4. Everything else is biotech.

Revenue here is the Revenues tag, which holds collaboration and licence income as well as
sales. At the scales the two thresholds sit at that does not change an answer, and the
alternative needs the product table, which parses for some filers and not others; a rule
that placed a company differently depending on whether its 10-K tabulates cleanly would be
a rule about parsing rather than about the company.

Every card carries a live figure computed by the same function the engine renders, so a
card and the page it opens cannot disagree.
"""

from __future__ import annotations

import datetime as dt

import catalysts
import db
import fx
import productivity
import runway
import themes
import whatchanged

PHARMA = "pharma"
BIOTECH = "biotech"
CELLGENE = "cellgene"
ENGINES = (PHARMA, BIOTECH, CELLGENE)

LABELS = {PHARMA: "Big pharma", BIOTECH: "Biotech", CELLGENE: "Cell and gene"}

# --- the assignment rule --------------------------------------------------------------

# Product revenue, USD, latest full year. The gap between Biogen and Incyte is the widest
# in the universe, so the line goes there.
PHARMA_MIN_REVENUE = 8e9

# Marketed products. Only consulted for a company with no financials at all, which in
# this universe is Roche and Bayer; both market more than fifty. A non-filer with a
# handful of products would fall through to one of the other two engines, which is the
# right answer for it.
PHARMA_MIN_REGISTER = 30

# Above this, a company with a cell or gene platform is read as a product company rather
# than as a developer of one. Legend earns a billion from Carvykti and Sarepta two from
# Elevidys: both are genuinely cell and gene, and both are answerable on revenue, which
# is the question the biotech engine asks.
PLATFORM_MAX_REVENUE = 1e9

# The platform tags that put a company on the cell and gene engine. Filtered against the
# theme vocabulary rather than restated, so a rename there cannot leave a dead string
# here silently matching nothing.
CELL_GENE_THEMES = tuple(
    t for t in ("Cell therapy", "CAR-T", "TCR and TIL", "Gene therapy", "Gene editing")
    if t in dict(themes.THEMES))


def assign(conn, company_id: int, revenue: float | None) -> str:
    """Which engine a company is read on. Exactly one, and derived.

    ``revenue`` is the latest full year of revenue in USD, or None when the company
    reports none. Passed in rather than looked up so a caller doing the whole universe
    resolves the FX rates once.
    """
    if revenue is not None and revenue >= PHARMA_MIN_REVENUE:
        return PHARMA

    reports = conn.execute(
        "SELECT 1 FROM financials WHERE company_id = ? LIMIT 1", (company_id,)).fetchone()
    if not reports:
        marketed = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE owner_company_id = ? AND is_marketed = 1",
            (company_id,)).fetchone()[0]
        if marketed >= PHARMA_MIN_REGISTER:
            return PHARMA

    if (revenue or 0) < PLATFORM_MAX_REVENUE and CELL_GENE_THEMES:
        marks = ",".join("?" * len(CELL_GENE_THEMES))
        platform = conn.execute(
            f"SELECT 1 FROM company_themes WHERE company_id = ?"
            f"  AND theme IN ({marks}) LIMIT 1",
            (company_id, *CELL_GENE_THEMES)).fetchone()
        if platform:
            return CELLGENE

    return BIOTECH


def home(db_path=None) -> dict:
    """{ticker: engine} for the whole universe."""
    conn = db.get_connection(db_path)
    try:
        rates = fx.latest_usd_rates(db_path)
        return {c["ticker"]: assign(conn, c["id"],
                                    productivity.latest_revenue(conn, c["id"], rates))
                for c in conn.execute("SELECT id, ticker FROM companies ORDER BY ticker")}
    finally:
        conn.close()


def tickers_for(db_path=None, engine: str | None = None) -> list:
    """The companies one engine covers, or every company when the engine is unknown."""
    homes = home(db_path)
    if engine not in ENGINES:
        return sorted(homes)
    return sorted(t for t, e in homes.items() if e == engine)


# --- the cards ------------------------------------------------------------------------

# How a bar in the distribution strip is coloured. A tone is a role rather than a colour:
# the frontend maps it onto a token, and PHASE means take the colour from the phase ramp
# using the bar's own label.
UP, DOWN, MUTED, PHASE = "up", "down", "muted", "phase"

# Under this many months of cash a runway bar turns. Twelve months is the line because
# below it the financing is the next event, whatever the pipeline says.
RUNWAY_ALARM_MONTHS = 12

# The longest runway the strip draws at full height. Past five years the figure stops
# meaning much, and one company at 590 months would flatten every other bar.
RUNWAY_CEILING_MONTHS = 60

# The stage above every phase, and the ordering the cell and gene strip reads on. Kept
# here rather than extending catalysts.PHASE_RANK, which orders running trials and has no
# business knowing about approvals.
MARKETED = "Marketed"
STAGE_RANK = dict(catalysts.PHASE_RANK,
                  **{MARKETED: max(catalysts.PHASE_RANK.values()) + 1})

# What the strip on each card plots, in the words that go on the card.
METRICS = {
    PHARMA: "share of product revenue from drugs approved in five years",
    BIOTECH: "months of cash at the current burn",
    # "On file" rather than "reached": a marketed product is read from the asset table,
    # and Krystal's Vyjuvek is not in it. Vyjuvek is a CBER licence, drugsfda covers CDER
    # only, and the NDC register that does list it also lists labelers for companies that
    # market nothing, so there is no free route that would not mark a developer marketed.
    CELLGENE: "furthest stage on file",
}

TAGLINES = {
    PHARMA: "Where the revenue comes from, and when it stops",
    BIOTECH: "What reaches the market, and what it costs to get there",
    CELLGENE: "Which platform, who is furthest, who runs out first",
}


def _leader(ticker, name, value, display) -> dict:
    return {"ticker": ticker, "name": name, "value": value, "display": display}


def _pharma(rows) -> dict:
    """Majors, led by how far portfolio renewal spreads them.

    The headline takes only a figure that rests on a dated drug. Moderna reads 100% and
    Lantheus 0%, both inferred from a whole marketed register rather than from any one
    drug's approval, and the most prominent sentence on the page should not rest on the
    weakest evidence available.
    """
    measured = [r for r in rows if r["fresh_share"] is not None]
    stated = sorted((r for r in measured
                     if not r.get("inferred_revenue") and not r.get("curated_revenue")),
                    key=lambda r: -r["fresh_share"])
    headline = None
    if len(stated) >= 2:
        top, bottom = stated[0], stated[-1]
        headline = (
            f"Portfolio renewal splits the group: {top['ticker']} earns "
            f"{top['fresh_share']:.0%} of its product revenue from drugs approved in the "
            f"last five years, {bottom['ticker']} {bottom['fresh_share']:.0%}.")
    return {
        "key": PHARMA,
        "count_label": "majors",
        "headline": headline,
        "detail": f"{len(measured)} of {len(rows)} measurable on portfolio freshness",
        "leaders": [_leader(r["ticker"], r["name"], r["fresh_share"],
                            f"{r['fresh_share']:.0%} of revenue is new")
                    for r in stated[:3]],
        "strip": [{"ticker": r["ticker"],
                   "height": r["fresh_share"],
                   "tone": UP if r["fresh_share"] is not None else MUTED,
                   "display": (f"{r['fresh_share']:.0%}"
                               if r["fresh_share"] is not None else "no figure")}
                  for r in sorted(rows, key=lambda r: -(r["fresh_share"] or 0))],
    }


def _runway_strip(rows) -> list:
    """Runway bars, longest first, so every engine's strip falls the same way and none of
    them can look like it is improving because of the sort. A company with no computable
    runway keeps its slot rather than dropping out, so the strip carries the coverage."""
    def order(row):
        return (row["runway_months"] is None, -(row["runway_months"] or 0))

    out = []
    for row in sorted(rows, key=order):
        months = row["runway_months"]
        out.append({
            "ticker": row["ticker"],
            "height": (min(months, RUNWAY_CEILING_MONTHS) / RUNWAY_CEILING_MONTHS
                       if months else None),
            "tone": (MUTED if not months
                     else DOWN if months < RUNWAY_ALARM_MONTHS else UP),
            "display": f"{months:.0f} months" if months else "no figure",
        })
    return out


def _biotech(rows, revenues) -> dict:
    """The middle of the market: some sell a product, some are still spending to.

    Two halves and one card, so the headline names the split and then the tightest
    balance sheet in it, which is the fact that decides what the pre-revenue half does
    next.

    The test is revenue rather than product revenue, and the card says so. The Revenues
    tag holds collaboration and licence income too, and for this cohort that is often
    most of it: Arrowhead's 340m is a partner payment, not a launch. Splitting the two
    needs the product table, which parses for some of these filers and not others, so
    calling the total product revenue here would be reporting a figure the source does
    not support.
    """
    earning = [r for r in rows if (revenues.get(r["ticker"]) or 0) > 0]
    silent = [r for r in rows if not (revenues.get(r["ticker"]) or 0)]
    funded = [r for r in rows if r["runway_months"]]
    tightest = min(funded, key=lambda r: r["runway_months"], default=None)

    headline = None
    if silent and tightest:
        headline = (
            f"{len(silent)} of the {len(rows)} book no revenue at all, and "
            f"{tightest['ticker']} has the least room at "
            f"{tightest['runway_months']:.0f} months of cash.")
    elif tightest:
        headline = (f"The tightest balance sheet on the engine is {tightest['ticker']} "
                    f"at {tightest['runway_months']:.0f} months of cash.")
    return {
        "key": BIOTECH,
        "count_label": "mid-cap and clinical",
        "headline": headline,
        "detail": (f"{len(earning)} book revenue of some kind, "
                   f"{len(funded)} have a measurable runway"),
        "leaders": [_leader(r["ticker"], r["name"], r["runway_months"],
                            f"{r['runway_months']:.0f} months of cash")
                    for r in sorted(funded, key=lambda r: r["runway_months"])[:3]],
        "strip": _runway_strip(rows),
    }


def _cellgene(rows, leads) -> dict:
    """The platform engine, led by the companies whose readout arrives after the money.

    Cash is the subject here rather than revenue, because none of them has any. What
    separates them is whether the next readout lands inside the runway: a company that
    has to finance before it has data finances on the story instead of on the result.
    """
    unfunded = [r for r in rows
                if r["funded_to_readout"] is False and not r["burn_flattered"]]
    funded = [r for r in rows if r["runway_months"]]
    tightest = min(funded, key=lambda r: r["runway_months"], default=None)

    headline = None
    if unfunded:
        headline = (
            f"{len(unfunded)} of the {len(rows)} reach their next readout only after the "
            "cash runs out, so they finance on no new data.")
        if tightest:
            headline += (f" {tightest['ticker']} has "
                         f"{tightest['runway_months']:.0f} months.")
    elif tightest:
        headline = (f"The shortest runway on the engine is {tightest['ticker']} at "
                    f"{tightest['runway_months']:.0f} months.")

    def rank(ticker):
        return STAGE_RANK.get(leads.get(ticker) or "", 0)

    late = [t for t, stage in leads.items()
            if STAGE_RANK.get(stage or "", 0) >= catalysts.LEAD_PHASE_CEILING]
    unplaced = [t for t in leads if not leads[t]]
    top = max(STAGE_RANK.values())
    return {
        "key": CELLGENE,
        "count_label": "platform developers",
        "headline": headline,
        "detail": (f"{len(late)} at Phase 3 or beyond, "
                   f"{len(unplaced)} with no trial on file"),
        "leaders": [_leader(r["ticker"], r["name"], rank(r["ticker"]),
                            leads.get(r["ticker"]) or "no trial on file")
                    for r in sorted(rows, key=lambda r: -rank(r["ticker"]))[:3]],
        "strip": [{"ticker": t,
                   "height": (STAGE_RANK[stage] / top if stage in STAGE_RANK else None),
                   "tone": PHASE if stage else MUTED,
                   "phase": stage,
                   "display": stage or "no trial on file"}
                  for t, stage in sorted(leads.items(), key=lambda kv: -rank(kv[0]))],
    }


def _lead_stage(conn, tickers) -> dict:
    """{ticker: furthest stage reached}, or None where nothing of its own places it.

    Marketed sits above every phase, which is the whole point of the axis on this engine:
    Abeona runs a Phase 4 trial because Zevaskyn is approved, and a reader looking for
    who is furthest wants that said rather than inferred from the trial number.
    """
    out = {}
    for ticker in tickers:
        marketed = conn.execute(
            "SELECT 1 FROM assets a JOIN companies c ON c.id = a.owner_company_id"
            " WHERE c.ticker = ? AND a.is_marketed = 1 LIMIT 1", (ticker,)).fetchone()
        if marketed:
            out[ticker] = MARKETED
            continue
        rows = conn.execute(
            "SELECT DISTINCT t.phase FROM trials t"
            "  JOIN assets a ON a.id = t.asset_id"
            "  JOIN companies c ON c.id = a.owner_company_id"
            " WHERE c.ticker = ? AND t.phase IS NOT NULL", (ticker,)).fetchall()
        ranked = [r["phase"] for r in rows if r["phase"] in catalysts.PHASE_RANK]
        out[ticker] = (max(ranked, key=lambda p: catalysts.PHASE_RANK[p])
                       if ranked else None)
    return out


# --- signals --------------------------------------------------------------------------

# What the strip looks back over. A week is long enough that a quiet day still has
# something on it and short enough that nothing on it is stale.
FEED_DAYS = 7

# How many signals the strip shows.
SIGNAL_LIMIT = 6

# Change types in the words a reader uses, since the stored names are engineering ones.
KIND_NAMES = {
    "new_approval": "approval",
    "efficacy_supplement": "label expansion",
    "leadership_change": "senior change",
    "status_change": "trial status",
    "date_slip": "date slipped",
    "date_change": "date moved",
    "new_filing": "filing",
    "label_change": "label revision",
    "risk_factors_change": "risk factors",
}

# The order the strip reads changes in, most material first. Significance alone does not
# separate them: 113 of last week's 183 high-significance items were risk-factor diffs,
# which is a rewrite of boilerplate, and ranking those level with an approval buries
# every approval. This orders the landing strip only; the change feed keeps its own rank.
SIGNAL_ORDER = ("new_approval", "efficacy_supplement", "leadership_change",
                "status_change", "date_slip", "date_change", "new_filing",
                "label_change", "risk_factors_change")


def signals(db_path=None, days: int = FEED_DAYS, limit: int = SIGNAL_LIMIT,
            homes: dict | None = None) -> list:
    """The most material changes across every engine, at most one per company.

    One per company because six items about the same filer is a page about that filer
    rather than about the week. ``homes`` is accepted so a caller that has already placed
    the universe does not place it twice.
    """
    homes = home(db_path) if homes is None else homes

    def rank(item):
        kind = item.get("change_type") or ""
        order = SIGNAL_ORDER.index(kind) if kind in SIGNAL_ORDER else len(SIGNAL_ORDER)
        date = (item.get("date") or "")[:10].replace("-", "")
        return (order, -int(date) if date.isdigit() else 0)

    out, seen = [], set()
    for item in sorted(whatchanged.build_feed(db_path, days=days), key=rank):
        ticker = (item.get("ticker") or "").upper()
        if item.get("kind") != "change" or not ticker or ticker in seen:
            continue
        seen.add(ticker)
        # Stored headlines open with the ticker, which the strip already shows in its own
        # column. Left in, every row would read "MRK   MRK FDA approval". Stripping it
        # leaves a lower-case first word, so the row is recapitalised to read as a line.
        headline = item.get("headline") or ""
        if headline.upper().startswith(ticker + " "):
            headline = headline[len(ticker) + 1:]
            headline = headline[:1].upper() + headline[1:]
        out.append({
            "ticker": ticker,
            "engine": homes.get(ticker),
            "kind": KIND_NAMES.get(item.get("change_type") or "",
                                   (item.get("change_type") or "").replace("_", " ")),
            "headline": headline,
            "date": (item.get("date") or "")[:10],
            "significance": item.get("significance"),
        })
        if len(out) >= limit:
            break
    return out


def build(db_path=None, today=None) -> dict:
    """The three cards and the signal strip, every figure from the engine behind it."""
    today = today or dt.date.today()
    homes = home(db_path)
    prod = {r["ticker"]: r for r in productivity.build(db_path, today=today,
                                                       stage_filter=None)}
    cash = {r["ticker"]: r for r in runway.build(db_path, today=today, stage_filter=None)}
    revenues = {t: (prod.get(t) or {}).get("revenue_latest") for t in homes}

    def cohort(key, source):
        return [source[t] for t in sorted(homes) if homes[t] == key and t in source]

    conn = db.get_connection(db_path)
    try:
        leads = _lead_stage(conn, [t for t in sorted(homes) if homes[t] == CELLGENE])
    finally:
        conn.close()

    cards = [_pharma(cohort(PHARMA, prod)),
             _biotech(cohort(BIOTECH, cash), revenues),
             _cellgene(cohort(CELLGENE, cash), leads)]
    for card in cards:
        card["label"] = LABELS[card["key"]]
        card["tagline"] = TAGLINES[card["key"]]
        card["metric"] = METRICS[card["key"]]
        card["count"] = sum(1 for e in homes.values() if e == card["key"])
    return {"universe": len(homes), "engines": cards,
            "signals": signals(db_path, homes=homes), "signal_days": FEED_DAYS}
