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
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

P3_SLIP_DAYS = 30                 # Phase 3 completion slip beyond this is high
CATALYST_SOON_DAYS = 14           # a catalyst inside this window ranks high
LOE_WINDOW_MONTHS = 24            # exclusivity expiring inside this is in the feed
REVENUE_RESTATEMENT_PCT = 0.05    # a restated product figure beyond this is high


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
    if change_type == "new_approval":
        return "FDA approval"
    if change_type == "new_filing":
        return "new filing"
    if change_type == "revenue_restatement":
        return f"restated over {REVENUE_RESTATEMENT_PCT:.0%}"
    return None
