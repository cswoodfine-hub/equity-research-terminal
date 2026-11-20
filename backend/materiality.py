"""Materiality rules: the thresholds that decide whether a change is flagged.

One config. ``diff`` reads it when it writes a change's significance and
``whatchanged`` reads it when it ranks the feed and names the reason an item is
flagged. No threshold lives inside either of those modules.

The rules, as one list:
- a phase advance is always material
- a Phase 3 primary completion slip over ``P3_SLIP_DAYS`` days is material
- an 8-K whose items read material (acquisitions, agreements, impairments,
  FDA action) is material; edgar_items holds the item taxonomy
- exclusivity expiring inside ``LOE_WINDOW_MONTHS`` months is material
- an approval is always material
- a product revenue restatement over ``REVENUE_RESTATEMENT_PCT`` is material
- a Part D formulary share (listed, prior authorisation, step therapy) that moves
  ``PAYER_ACCESS_POINTS`` points from where it was last flagged is medium
- a new research paper ranked in the top ``1 - DISCOVERY_TOP_PCT`` of a year of papers
  on either Discovery score is medium, and high in the top ``1 - DISCOVERY_HIGH_PCT``
- a paper from a lab head ranked ``DISCOVERY_LAB_RANK`` or better is medium; that lab's
  first paper in primates or patients, or with a company among the authors, is high
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

P3_SLIP_DAYS = 30                 # Phase 3 completion slip beyond this is high
CATALYST_SOON_DAYS = 14           # a catalyst inside this window ranks high
LOE_WINDOW_MONTHS = 24            # exclusivity expiring inside this is in the feed
REVENUE_RESTATEMENT_PCT = 0.05    # a restated product figure beyond this is high
PAYER_ACCESS_POINTS = 10.0        # a formulary share moving this far is medium
PAYER_ACCESS_SIGNIFICANCE = "medium"

# Discovery: early research in cell and gene therapy (discovery.py). A score is a rank
# against a year of papers, so each bar is a share of them.
DISCOVERY_TOP_PCT = 0.95          # a paper outranking this share on either score is flagged
DISCOVERY_HIGH_PCT = 0.99         # and is high from here
DISCOVERY_LAB_RANK = 300          # lab alerts cover the lab heads ranked this well
DISCOVERY_LATE_STAGES = ("primate", "patients")   # a lab's first paper here is high
# A paper the book first saw more than this many days after Europe PMC indexed it is
# stored and raises nothing. The first run reads weeks of papers at once, and without
# this they would all arrive as today's news.
DISCOVERY_ALERT_DAYS = 7


def _days_between(old_date: Optional[str], new_date: Optional[str]) -> Optional[int]:
    try:
        old = dt.date.fromisoformat(str(old_date)[:10])
        new = dt.date.fromisoformat(str(new_date)[:10])
    except (ValueError, TypeError):
        return None
    return (new - old).days


def slip_significance(phase: Optional[str], old_date: Optional[str],
                      new_date: Optional[str]) -> str:
    """A completion slip's significance. Phase 3 over the threshold is high; every
    other slip stays medium, a real but earlier signal."""
    days = _days_between(old_date, new_date)
    if (phase or "").startswith("Phase 3") and days is not None \
            and days > P3_SLIP_DAYS:
        return "high"
    return "medium"


def restatement_is_material(old_value: Optional[float],
                            new_value: Optional[float]) -> bool:
    """True when a re-reported figure moves beyond the threshold. A figure that
    appears or disappears outright is handled as its own event, not judged here."""
    if not old_value or new_value is None:
        return False
    return abs(new_value - old_value) / abs(old_value) > REVENUE_RESTATEMENT_PCT


def discovery_paper_significance(feas_pct, comm_pct) -> Optional[str]:
    """How a paper's better score rates it, or None when neither clears the bar."""
    best = max((p for p in (feas_pct, comm_pct) if p is not None), default=None)
    if best is None or best < DISCOVERY_TOP_PCT:
        return None
    return "high" if best >= DISCOVERY_HIGH_PCT else "medium"


def discovery_is_news(indexed: Optional[str], seen: Optional[str]) -> bool:
    """True when the book saw a paper within ``DISCOVERY_ALERT_DAYS`` of its indexing."""
    days = _days_between(indexed, seen)
    return days is not None and days <= DISCOVERY_ALERT_DAYS


def discovery_stage_significance(stage: Optional[str]) -> str:
    return "high" if stage in DISCOVERY_LATE_STAGES else "medium"


_DISCOVERY_REASONS = {
    "discovery_paper_top": f"Discovery, paper in the top {round((1 - DISCOVERY_TOP_PCT) * 100)}%",
    "discovery_lab_paper": f"Discovery, lab head ranked in the top {DISCOVERY_LAB_RANK}",
    "discovery_lab_stage": "Discovery, lab reached a later model",
    "discovery_lab_company": "Discovery, lab's first company co-author",
}


def change_reason(change_type: str, old_value=None, new_value=None) -> Optional[str]:
    """The rule that flagged a change, as a short label the feed can print."""
    if change_type == "phase_advance":
        return "phase advance"
    if change_type == "date_slip":
        days = _days_between(old_value, new_value)
        return f"slipped {days}d" if days is not None else "completion slipped"
    if change_type == "status_change":
        return "status change"
    if change_type == "population_expansion":
        return "population widened"
    if change_type == "new_indication":
        return "new indication"
    if change_type == "label_change":
        return "label revised"
    if change_type == "efficacy_supplement":
        return "efficacy supplement"
    if change_type == "new_approval":
        return "FDA approval"
    if change_type == "new_filing":
        return "new filing"
    if change_type == "risk_factors_change":
        return "risk factors changed"
    if change_type == "revenue_restatement":
        return f"restated over {REVENUE_RESTATEMENT_PCT:.0%}"
    if change_type == "leadership_change":
        return "8-K item 5.02"
    # Measured against the level the last flag was written from, not the last refresh,
    # so the label says which bar was crossed rather than implying a one-day move.
    if change_type == "rate_move":
        return "risk-free rate moved"
    if change_type == "credit_move":
        return "credit spread moved"
    if change_type == "inflation_move":
        return "breakeven inflation moved"
    if change_type == "fx_move":
        return "reporting currency moved"
    if change_type == "ira_selected":
        return "CMS price negotiation"
    if change_type == "ira_deselected":
        return "CMS deselection, for review"
    if change_type == "payer_access":
        return f"Part D coverage moved {PAYER_ACCESS_POINTS:.0f} points or more"
    # A press release carries its kind in its type, e.g. press_data_readout. The rule
    # that flagged it is the company saying so, and the kind is what it said.
    if change_type.startswith("press_"):
        kind = change_type[len("press_"):].replace("_", " ")
        return "PDUFA" if kind == "pdufa" else kind
    # The daily pulse, an AI-written briefing: the label says so wherever it is printed.
    if change_type.startswith("pulse_"):
        return f"daily pulse (AI summary), {change_type[len('pulse_'):]}"
    if change_type in _DISCOVERY_REASONS:
        return _DISCOVERY_REASONS[change_type]
    return None
