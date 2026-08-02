"""Snapshot diff engine.

Turns consecutive snapshots into rows in the changes table. Runs after the fetchers on
every refresh: it compares each trial's current state to its last per-trial snapshot
(status, primary completion date, phase) and treats a first-seen filing or approval as a
new-item signal. Baselines are per company, not global, so a single-company refresh never
baselines the rest of the universe. A company's first run emits nothing; later runs emit
each change once, since the compared snapshot is advanced when a change is recorded.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import db
import edgar_items
import filingtext
import materiality

# A first-seen filing or approval only counts as news if it is also recent. Wide enough to
# survive a refresh gap of several months, narrow enough to exclude back catalogue.
# Public because cleanup.py retires old poisoned rows by the same rule; one definition.
RECENCY_DAYS = 180

_HIGH_STATUS = {"Terminated", "Suspended", "Withdrawn"}
_PHASE_RANK = {
    "Phase 1": 1, "Phase 1/2": 2, "Phase 2": 3, "Phase 2/3": 4, "Phase 3": 5, "Phase 4": 6,
}


def _last_snapshot(conn, source, entity_type, entity_key):
    row = conn.execute(
        """
        SELECT payload FROM snapshots
         WHERE source = ? AND entity_type = ? AND entity_key = ?
         ORDER BY captured_at DESC, id DESC LIMIT 1
        """,
        (source, entity_type, entity_key),
    ).fetchone()
    return json.loads(row["payload"]) if row else None


def _write_snapshot(conn, source, entity_type, entity_key, payload, run_id):
    conn.execute(
        """
        INSERT INTO snapshots (source, entity_type, entity_key, payload, refresh_run_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (source, entity_type, entity_key, json.dumps(payload), run_id),
    )


def _write_change(conn, entity_type, entity_key, field, old, new, change_type, sig, run_id):
    conn.execute(
        """
        INSERT INTO changes
            (entity_type, entity_key, field, old_value, new_value, change_type,
             significance, refresh_run_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (entity_type, entity_key, field, old, new, change_type, sig, run_id),
    )


def _status_significance(status) -> str:
    if status in _HIGH_STATUS:
        return "high"
    if status == "Completed":
        return "medium"
    return "low"


def _diff_trials(conn, run_id) -> int:
    changed = 0
    rows = conn.execute(
        """
        SELECT t.nct_id, t.overall_status, t.primary_completion_date, t.phase, t.title,
               t.primary_outcome, t.design, t.enrollment, c.ticker
          FROM trials t LEFT JOIN companies c ON t.sponsor_company_id = c.id
        """
    ).fetchall()
    for row in rows:
        key = row["nct_id"]
        current = {
            "overall_status": row["overall_status"],
            "primary_completion_date": row["primary_completion_date"],
            "phase": row["phase"],
            "primary_outcome": row["primary_outcome"],
            "design": row["design"],
            "enrollment": row["enrollment"],
        }
        prior = _last_snapshot(conn, "trials", "trial", key)
        payload = {**current, "ticker": row["ticker"], "title": row["title"]}
        if prior is None:  # baseline: newly tracked trial, no signal
            _write_snapshot(conn, "trials", "trial", key, payload, run_id)
            continue

        emitted = False
        if prior.get("overall_status") != current["overall_status"]:
            _write_change(conn, "trial", key, "overall_status",
                          prior.get("overall_status"), current["overall_status"],
                          "status_change", _status_significance(current["overall_status"]),
                          run_id)
            emitted = True
        old_date, new_date = prior.get("primary_completion_date"), current["primary_completion_date"]
        if old_date != new_date and old_date and new_date:
            if new_date > old_date:
                # Materiality: a Phase 3 slip beyond the threshold is high; every
                # other slip is a real but earlier signal and stays medium.
                _write_change(conn, "trial", key, "primary_completion_date", old_date,
                              new_date, "date_slip",
                              materiality.slip_significance(current["phase"],
                                                            old_date, new_date),
                              run_id)
            else:
                _write_change(conn, "trial", key, "primary_completion_date", old_date,
                              new_date, "date_change", "low", run_id)
            emitted = True
        if prior.get("phase") != current["phase"]:
            old_rank = _PHASE_RANK.get(prior.get("phase"), 0)
            new_rank = _PHASE_RANK.get(current["phase"], 0)
            change_type = "phase_advance" if new_rank > old_rank else "phase_regress"
            sig = "high" if new_rank > old_rank else "medium"
            _write_change(conn, "trial", key, "phase", prior.get("phase"),
                          current["phase"], change_type, sig, run_id)
            emitted = True

        # A rewritten primary endpoint is the sponsor changing the question the trial
        # asks, after it has seen something. It is the single most informative thing
        # this engine can catch, and it is invisible without the previous wording.
        if (prior.get("primary_outcome") and current["primary_outcome"]
                and prior["primary_outcome"] != current["primary_outcome"]):
            _write_change(conn, "trial", key, "primary_outcome",
                          prior["primary_outcome"], current["primary_outcome"],
                          "endpoint_change",
                          "high" if (current["phase"] or "").startswith(
                              ("Phase 3", "Phase 2/3")) else "medium", run_id)
            emitted = True

        # Dropping a blind, or moving off randomisation, changes what the result can
        # support whatever the result is.
        if (prior.get("design") and current["design"]
                and prior["design"] != current["design"]):
            _write_change(conn, "trial", key, "design", prior["design"],
                          current["design"], "design_change", "medium", run_id)
            emitted = True

        # Enrolment moving by a fifth is a trial being resized. Smaller moves are the
        # ordinary drift of a recruiting study and say nothing.
        old_n, new_n = prior.get("enrollment"), current["enrollment"]
        if old_n and new_n and abs(new_n - old_n) >= max(20, old_n * 0.2):
            _write_change(conn, "trial", key, "enrollment", str(old_n), str(new_n),
                          "enrollment_change",
                          "medium" if new_n < old_n else "low", run_id)
            emitted = True

        if emitted:
            changed += 1
            _write_snapshot(conn, "trials", "trial", key, payload, run_id)
    return changed


def _baselined_tickers(conn, entity_type) -> set:
    """Tickers this entity type has already been snapshotted for.

    Scoped per company because refreshes are: a single-company refresh must not baseline
    the rest of the universe and turn their back catalogue into news on the next run.
    """
    rows = conn.execute(
        "SELECT DISTINCT json_extract(payload, '$.ticker') AS ticker"
        "  FROM snapshots WHERE entity_type = ?",
        (entity_type,),
    ).fetchall()
    return {r["ticker"] for r in rows}


def is_recent(value, today=None) -> bool:
    """True for an ISO date within the recency window. Missing or unparseable is False.

    ``today`` is injectable so cleanup can ask the question as of when a change was
    detected, rather than as of now.
    """
    if not value:
        return False
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return False
    return parsed >= (today or date.today()) - timedelta(days=RECENCY_DAYS)


def _detect_new(conn, run_id, source, entity_type, rows, change_type, date_field) -> int:
    """First-seen entities (filings, approvals) are the signal, once past the baseline.

    Two gates, both required. A company's first sighting is its baseline and emits
    nothing, so adding a company mid-life does not replay its history. Past that, only
    an item dated inside the recency window is news; an approval from 2008 first seen
    today is a gap in our coverage, not an event.
    """
    baselined = _baselined_tickers(conn, entity_type)
    emitted = 0
    for key, payload, label, significance in rows:
        if _last_snapshot(conn, source, entity_type, key) is not None:
            continue
        if payload.get("ticker") in baselined and is_recent(payload.get(date_field)):
            _write_change(conn, entity_type, key, entity_type, None, label,
                          change_type, significance, run_id)
            emitted += 1
        _write_snapshot(conn, source, entity_type, key, payload, run_id)
    return emitted


def _diff_filings(conn, run_id) -> int:
    rows = conn.execute(
        """
        SELECT f.accession, f.form_type, f.filed_date, f.title, c.ticker
          FROM filings f LEFT JOIN companies c ON f.company_id = c.id
         ORDER BY f.filed_date DESC
        """
    ).fetchall()
    # An 8-K reporting a completed acquisition or a signed material agreement is not
    # the same event as one reporting a shareholder vote, and the item codes say which
    # is which. Material ones rank high so they lead the feed and the note.
    items = [
        (r["accession"],
         {"form_type": r["form_type"], "filed_date": r["filed_date"], "ticker": r["ticker"]},
         f"{r['ticker']} {r['form_type']}: {r['title']}",
         "high" if edgar_items.is_material_title(r["title"])
         else "medium" if r["form_type"] in ("8-K", "6-K") else "low")
        for r in rows
    ]
    return _detect_new(conn, run_id, "filings", "filing", items, "new_filing", "filed_date")


def _label_change(prior, current) -> tuple | None:
    """The strongest label event between two versions, or None.

    A widened population outranks a new indication, which outranks a bare revision.
    An age floor dropping or a ceiling rising is an expansion; the headline leads
    with the numbers, e.g. "age floor 12 -> 2". Fields that are null on either side
    fall through to the plainer signal rather than reading a change into a gap.
    """
    old_floor, new_floor = prior.get("age_floor_years"), current.get("age_floor_years")
    old_ceiling = prior.get("age_ceiling_years")
    new_ceiling = current.get("age_ceiling_years")
    drug = current.get("drug_name") or current.get("ticker") or "product"
    if (old_floor is not None and new_floor is not None and new_floor < old_floor) or \
       (old_ceiling is not None and new_ceiling is not None and new_ceiling > old_ceiling):
        if new_floor is not None and old_floor is not None and new_floor < old_floor:
            detail = f"age floor {old_floor:g} -> {new_floor:g}"
        else:
            detail = f"age ceiling {old_ceiling:g} -> {new_ceiling:g}"
        return ("population_expansion", "high",
                f"{current.get('ticker')} label: {drug} population widens, {detail}")
    old_count, new_count = prior.get("indication_count"), current.get("indication_count")
    if old_count is not None and new_count is not None and new_count > old_count:
        return ("new_indication", "high",
                f"{current.get('ticker')} label: {drug} indications "
                f"{old_count} -> {new_count}")
    return ("label_change", "medium",
            f"{current.get('ticker')} label: {drug} revised to version "
            f"{current.get('spl_version')}")


def _diff_labels(conn, run_id) -> int:
    """Version increments on tracked labels become change rows.

    Reads current label state from the labels table and compares it to the last
    per-setid snapshot, the same way trials are diffed: a first sighting baselines
    and emits nothing, and the compared snapshot advances only when a change is
    recorded, so re-running detects nothing new.
    """
    changed = 0
    rows = conn.execute(
        """
        SELECT l.setid, l.drug_name, l.spl_version, l.indication_count,
               l.age_floor_years, l.age_ceiling_years, l.population_text, c.ticker
          FROM labels l
          LEFT JOIN assets a ON a.id = l.asset_id
          LEFT JOIN companies c ON c.id = a.owner_company_id
        """
    ).fetchall()
    for row in rows:
        key = row["setid"]
        current = {k: row[k] for k in row.keys()}
        prior = _last_snapshot(conn, "labels", "label", key)
        if prior is None:                     # baseline a newly tracked label
            _write_snapshot(conn, "labels", "label", key, current, run_id)
            continue
        if prior.get("spl_version") == current.get("spl_version"):
            continue                          # nothing revised
        change_type, significance, headline = _label_change(prior, current)
        _write_change(conn, "label", key, "spl_version",
                      str(prior.get("spl_version")), headline, change_type,
                      significance, run_id)
        _write_snapshot(conn, "labels", "label", key, current, run_id)
        changed += 1
    return changed


def _diff_approvals(conn, run_id) -> int:
    rows = conn.execute(
        """
        SELECT ap.application_number, ap.approval_date, a.brand_name, c.ticker
          FROM approvals ap JOIN assets a ON ap.asset_id = a.id
          LEFT JOIN companies c ON a.owner_company_id = c.id
        """
    ).fetchall()
    items = [
        (r["application_number"],
         {"approval_date": r["approval_date"], "ticker": r["ticker"]},
         f"{r['ticker']} FDA approval: {r['brand_name']} ({r['application_number']})",
         "high")
        for r in rows
    ]
    return _detect_new(conn, run_id, "approvals", "approval", items, "new_approval",
                       "approval_date")


def _diff_product_revenue(conn, run_id) -> int:
    """Restatements: a tagged product figure that moves on re-report.

    Each asset-year is its own entity, so a figure appearing for a new year is a
    baseline, not an event. Only an existing figure that moves beyond the
    materiality threshold is flagged; smaller drift is re-snapshotted silently.
    """
    rows = conn.execute(
        """
        SELECT r.asset_id, r.fiscal_year, r.period, r.value, r.unit,
               a.brand_name, c.ticker
          FROM asset_revenue r JOIN assets a ON a.id = r.asset_id
          LEFT JOIN companies c ON c.id = a.owner_company_id
        """
    ).fetchall()
    emitted = 0
    for row in rows:
        # The period is part of the key. Without it a quarter and its year shared one
        # slot and each refresh read the other as a restatement of it.
        key = f"{row['asset_id']}:{row['fiscal_year']}:{row['period']}"
        payload = {"value": row["value"], "unit": row["unit"],
                   "ticker": row["ticker"], "brand": row["brand_name"]}
        prior = _last_snapshot(conn, "asset_revenue", "product_revenue", key)
        if prior is None:
            _write_snapshot(conn, "asset_revenue", "product_revenue", key, payload,
                            run_id)
            continue
        old_value = prior.get("value")
        if old_value == row["value"]:
            continue
        if materiality.restatement_is_material(old_value, row["value"]):
            label = (f"{row['ticker']} restated {row['brand_name']} "
                     f"FY{row['fiscal_year']}: {old_value} -> {row['value']}")
            _write_change(conn, "product_revenue", key, "value", str(old_value),
                          label, "revenue_restatement", "high", run_id)
            emitted += 1
        _write_snapshot(conn, "asset_revenue", "product_revenue", key, payload,
                        run_id)
    return emitted


def _diff_supplements(conn, run_id) -> int:
    """A newly seen approved efficacy supplement is a label expansion. Same gate as
    approvals: a company's first sighting baselines, and only a supplement approved
    inside the recency window is news, so the back catalogue of old supplements is
    not replayed as events."""
    rows = conn.execute(
        """
        SELECT s.application_number, s.submission_number, s.approval_date,
               a.brand_name, c.ticker
          FROM supplements s
          LEFT JOIN assets a ON a.id = s.asset_id
          LEFT JOIN companies c ON c.id = a.owner_company_id
        """
    ).fetchall()
    items = [
        (f"{r['application_number']}:{r['submission_number']}",
         {"approval_date": r["approval_date"], "ticker": r["ticker"]},
         f"{r['ticker']} efficacy supplement: {r['brand_name'] or r['application_number']}"
         f" approved {r['approval_date']}",
         "high")
        for r in rows
    ]
    return _detect_new(conn, run_id, "supplements", "supplement", items,
                       "efficacy_supplement", "approval_date")


def _diff_filing_text(conn, run_id) -> int:
    """A rewritten risk factors section becomes a change row.

    Risk factors is prose that turns over slowly, so what is added or removed against the
    last filing of the same form is a real signal; MD&A is rewritten wholesale every
    period and carries no comparable signal, so it is stored but not flagged. The two
    most recent filings of a form are compared, keyed on the newer accession so the event
    emits once and a re-run detects nothing new.
    """
    emitted = 0
    companies = [r["company_id"] for r in conn.execute(
        "SELECT DISTINCT company_id FROM filing_sections")]
    for company_id in companies:
        ticker_row = conn.execute(
            "SELECT ticker FROM companies WHERE id = ?", (company_id,)).fetchone()
        ticker = ticker_row["ticker"] if ticker_row else None
        for form in ("10-K", "10-Q"):
            rows = conn.execute(
                "SELECT accession, filed_date, text FROM filing_sections"
                " WHERE company_id = ? AND form_type = ? AND section = 'risk_factors'"
                " ORDER BY filed_date DESC, accession DESC LIMIT 2",
                (company_id, form)).fetchall()
            if len(rows) < 2:
                continue                       # no prior of this form to compare against
            newest, prior = rows[0], rows[1]
            already = conn.execute(
                "SELECT 1 FROM changes WHERE entity_type = 'filing'"
                "   AND entity_key = ? AND field = 'risk_factors' LIMIT 1",
                (newest["accession"],)).fetchone()
            if already:
                continue
            result = filingtext.diff_sections(prior["text"], newest["text"])
            if not result["changed"]:
                continue
            magnitude = result["added"] + result["removed"]
            significance = "high" if magnitude >= 8 else "medium"
            headline = (f"{ticker} risk factors changed: {result['added']} added, "
                        f"{result['removed']} removed vs {form} {prior['filed_date'][:4]}")
            _write_change(conn, "filing", newest["accession"], "risk_factors",
                          prior["accession"], headline, "risk_factors_change",
                          significance, run_id)
            emitted += 1
    return emitted


def detect_changes(db_path=None, run_id=None) -> dict:
    conn = db.get_connection(db_path)
    try:
        summary = {
            "trial_changes": _diff_trials(conn, run_id),
            "new_filings": _diff_filings(conn, run_id),
            "new_approvals": _diff_approvals(conn, run_id),
            "restatements": _diff_product_revenue(conn, run_id),
            "label_changes": _diff_labels(conn, run_id),
            "efficacy_supplements": _diff_supplements(conn, run_id),
            "filing_text_changes": _diff_filing_text(conn, run_id),
        }
        conn.commit()
    finally:
        conn.close()
    return summary
