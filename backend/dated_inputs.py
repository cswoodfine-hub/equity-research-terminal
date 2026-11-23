"""What was known about a drug or a study on a past day, and nothing learnt since.

A model input that is meant to have been known before an event has to be read as of
that event. On 2026-11-23 the share of Phase 3 readouts that came out positive was cut
by whether the drug was "marketed", read from ``assets.is_marketed``, and came out at
88% against 78%. That column says how the drug stands today: a drug is marketed
because its Phase 3 worked. Asked as of each readout's own date the figures are 87.5%
and 81.1%. The first answer was hindsight, and nothing in the code stopped it.

So every input the odds are allowed to use is a function here that takes the day and
reads only rows dated before it. ``INPUTS`` is the list. A test reads the text of each
for a column that carries no date (``signal_test.UNDATED_COLUMNS``) and checks, input
by input, that a fact dated after the day is not seen.

An input answers None where the book cannot say, never a guess: a drug with no
approval on file is not thereby unapproved in every market, only unapproved as far as
this book has read.

Reads only.
"""

from __future__ import annotations

import datetime as dt


def _day(value) -> str | None:
    try:
        return dt.date.fromisoformat(str(value or "")[:10]).isoformat()
    except ValueError:
        return None


def approved_before(conn, asset_id, day) -> bool | None:
    """Whether the asset had an approval dated before ``day``, anywhere. Dated by
    ``approvals.approval_date``. None where no asset or no day is given."""
    cut = _day(day)
    if asset_id is None or cut is None:
        return None
    row = conn.execute(
        "SELECT MIN(approval_date) AS first FROM approvals"
        " WHERE asset_id = ? AND approval_date IS NOT NULL", (asset_id,)).fetchone()
    first = _day(row["first"]) if row else None
    return bool(first and first < cut)


def earlier_positive_phase3(conn, company_id, drug, day, gap_days: int = 45) -> bool | None:
    """Whether the company had already reported a positive Phase 3 for the same drug at
    least ``gap_days`` before ``day``. Dated by ``trial_readouts.event_date``. The gap
    keeps a second announcement of one result from counting as an earlier one."""
    cut = _day(day)
    name = (drug or "").strip().lower()
    if company_id is None or cut is None or not name:
        return None
    limit = (dt.date.fromisoformat(cut) - dt.timedelta(days=gap_days)).isoformat()
    row = conn.execute(
        "SELECT 1 FROM trial_readouts WHERE company_id = ? AND lower(drug) = ?"
        "   AND phase = 3 AND outcome = 'positive'"
        "   AND event_date IS NOT NULL AND substr(event_date, 1, 10) < ? LIMIT 1",
        (company_id, name, limit)).fetchone()
    return row is not None


def results_posted_before(conn, nct_id, day) -> bool | None:
    """Whether the registry had posted the study's results before ``day``. Dated by
    ``trial_result_fetches.results_date``. None where the study has not been asked."""
    cut = _day(day)
    if not nct_id or cut is None:
        return None
    row = conn.execute(
        "SELECT has_results, results_date FROM trial_result_fetches WHERE nct_id = ?",
        (nct_id,)).fetchone()
    if row is None:
        return None
    posted = _day(row["results_date"])
    return bool(row["has_results"] and posted and posted < cut)


# The inputs the odds may use, each with the column that dates it. Adding one means
# adding it here, and the tests then hold it to the rule.
INPUTS = {
    "approved_before": (approved_before, "approvals.approval_date"),
    "earlier_positive_phase3": (earlier_positive_phase3, "trial_readouts.event_date"),
    "results_posted_before": (results_posted_before, "trial_result_fetches.results_date"),
}
