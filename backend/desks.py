"""The four ways into the terminal, each with the headline from its own desk.

Three desks and a feed. The desks exist because the questions differ, not because the
companies do: 30 of the 70 have no product revenue, so loss of exclusivity and revenue
mix are empty for them by construction, and cash runway is empty for the other 38. A
company is assigned by what it reports rather than by size, so the split is derived and
cannot drift with the market.

Every card carries a live figure from the desk behind it. A landing page whose only job
is to ask which door you want costs a click and tells you nothing; one that names the
sharpest thing on each desk answers the question most visits were going to ask anyway.

The figures come from the same functions the desks render, so a card and the page it
opens can never disagree.
"""

from __future__ import annotations

import datetime as dt

import db
import productivity
import runway
import themes_view
import whatchanged

# What the feed card looks back over. A week is long enough that a quiet day still has
# something on it and short enough that nothing on the card is stale.
FEED_DAYS = 7

# Change types in the words a reader uses, since the stored names are engineering ones.
_KIND_NAMES = {
    "date_slip": "trial dates slipped",
    "date_change": "trial dates moved",
    "status_change": "trial status changes",
    "leadership_change": "senior changes",
    "new_approval": "approvals",
    "efficacy_supplement": "label expansions",
    "new_filing": "material filings",
    "risk_factors_change": "risk factor rewrites",
    "label_change": "label revisions",
    "material event": "material events",
    "data readout": "readouts due",
    "loe": "exclusivity expiries",
}

# The revenue a company needs to be one of the two names in this desk's headline. The
# desk itself keeps everyone above a billion, but the sentence is about major pharma and
# Sarepta reading 100% off a single product is a true figure and a thin claim.
HEADLINE_MIN_REVENUE = 10e9

MAJOR = "major"
BIOTECH = "biotech"
FRONTIER = "frontier"
CHANGED = "changed"


def _major(db_path, rows) -> dict:
    """Commercial-stage names, led by how sharply portfolio renewal splits them."""
    # The headline compares the two ends, so it takes only figures that rest on a dated
    # drug. Moderna reads 100% and Lanthanum 0%, both inferred from the whole marketed
    # register rather than from any drug's own date, and putting the strongest claim on
    # the page's most prominent line on the weakest evidence is the wrong trade.
    measured = [r for r in rows if r["fresh_share"] is not None]
    # The two names in the sentence are drawn from a narrower pool than the count is.
    # Reusing one list for both reported 14 of 28 measurable when 23 are, because the
    # headline pool excludes the figures that rest on an inference or a curated map.
    headline_pool = sorted(
        (r for r in measured
         if not r.get("inferred_revenue") and not r.get("curated_revenue")
         and (r["revenue_latest"] or 0) >= HEADLINE_MIN_REVENUE),
        key=lambda r: -r["fresh_share"])
    headline = None
    if len(headline_pool) >= 2:
        top, bottom = headline_pool[0], headline_pool[-1]
        headline = (
            f"Portfolio renewal splits the group: {top['ticker']} earns "
            f"{top['fresh_share']:.0%} of its product revenue from drugs approved in "
            f"the last five years, {bottom['ticker']} {bottom['fresh_share']:.0%}.")
    return {
        "key": MAJOR, "label": "Major pharma", "stage": runway.COMMERCIAL,
        "count": len(rows), "count_label": "commercial-stage",
        "headline": headline,
        "detail": f"{len(measured)} of {len(rows)} measurable on portfolio freshness",
    }


def _biotech(db_path, rows) -> dict:
    """Clinical-stage names, led by the ones that cannot reach their own readout."""
    unfunded = [r for r in rows if r["funded_to_readout"] is False
                and not r["burn_flattered"]]
    shortest = next((r for r in rows if r["runway_months"]), None)
    headline = None
    if unfunded:
        headline = (
            f"{len(unfunded)} reach their next readout only after the cash runs out, so "
            "they have to finance on no new data.")
        if shortest and shortest["runway_months"]:
            headline += (f" {shortest['ticker']} has "
                         f"{shortest['runway_months']:.0f} months.")
    elif shortest and shortest["runway_months"]:
        headline = (f"The shortest runway on the desk is {shortest['ticker']} at "
                    f"{shortest['runway_months']:.0f} months.")
    return {
        "key": BIOTECH, "label": "Biotech", "stage": runway.CLINICAL,
        "count": len(rows), "count_label": "clinical-stage",
        "headline": headline,
        "detail": f"{len(unfunded)} unfunded to their next readout",
    }


def _frontier(db_path, themes, coverage) -> dict:
    """Modalities, led by the widest gap between platforms and classifiable programmes.

    That gap is the desk's own subject. Gene editing has one programme any free source
    can classify and fifteen companies whose filings describe the platform, and a reader
    who took the programme count for the truth would conclude nobody is doing it.
    """
    widest = max(themes, key=lambda t: len(t["platform_companies"]) - t["companies"],
                 default=None)
    headline = None
    if widest:
        headline = (
            f"{widest['theme']} spans {len(widest['platform_companies'])} companies by "
            f"their own filings and {widest['assets']} programmes any free source can "
            "classify.")
    return {
        "key": FRONTIER, "label": "Frontier", "stage": None,
        "count": len(themes), "count_label": "modalities tracked",
        "headline": headline,
        "detail": (f"{coverage['companies_on_platform']} of "
                   f"{coverage['companies']} companies on a platform"),
    }


def _changed(db_path, feed) -> dict:
    """What moved across every company, whatever desk it sits on."""
    high = [i for i in feed if i["significance"] == "high"]
    # Counted by kind rather than quoted. Three headlines run together and clipped at
    # sixty characters read as debris, and on this feed they are nearly always the same
    # kind of thing: a fortnight of trial dates moving by a few weeks.
    kinds: dict = {}
    for item in high:
        kinds[item["change_type"] or "other"] = kinds.get(item["change_type"] or "other",
                                                          0) + 1
    parts = [f"{count} {_KIND_NAMES.get(kind, kind.replace('_', ' '))}"
             for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1])[:4]]
    headline = ", ".join(parts) or None
    return {
        "key": CHANGED, "label": "What changed", "stage": None,
        "count": len(feed), "count_label": f"in {FEED_DAYS} days",
        "headline": headline,
        "detail": f"{len(high)} ranked high",
    }


def build(db_path=None, today=None) -> dict:
    """The four cards, each with the live headline from the desk it opens."""
    today = today or dt.date.today()
    commercial = [r for r in productivity.build(db_path, today=today)
                  if (r["revenue_latest"] or 0) >= productivity.SCORECARD_MIN_REVENUE]
    clinical = runway.build(db_path, today=today)
    themes = themes_view.build(db_path)
    coverage = themes_view.coverage(db_path)
    feed = whatchanged.build_feed(db_path, days=FEED_DAYS)

    conn = db.get_connection(db_path)
    try:
        universe = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    finally:
        conn.close()

    return {
        "universe": universe,
        "desks": [_major(db_path, commercial), _biotech(db_path, clinical),
                  _frontier(db_path, themes, coverage), _changed(db_path, feed)],
    }


def tickers_for(db_path=None, desk: str | None = None) -> list:
    """The companies a desk covers, or every company when it covers all of them.

    The frontier and the feed span the universe, so they filter nothing. A company the
    stage test cannot place stays on both desks rather than falling off the terminal.
    """
    conn = db.get_connection(db_path)
    try:
        rows = conn.execute("SELECT id, ticker FROM companies ORDER BY ticker").fetchall()
        if desk not in (MAJOR, BIOTECH):
            return [r["ticker"] for r in rows]
        wanted = runway.COMMERCIAL if desk == MAJOR else runway.CLINICAL
        return [r["ticker"] for r in rows
                if runway.stage(conn, r["id"]) in (wanted, runway.UNKNOWN)]
    finally:
        conn.close()
