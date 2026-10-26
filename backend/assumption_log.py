"""The ledger of changes to the model's own inputs (migration 088).

Every other history the terminal keeps is of the world: a trial that changed phase, a
label that gained an indication, a price that moved. This one is of the model. A number
an analyst sets is the part of a valuation no source can hand back, and the assumptions
table overwrites it on write, so until now the only record of a prior figure was the git
diff of the seed file it started in. That misses every value edited in the terminal.

Three rules, and they are the licensing argument as much as the engineering one:

- A change is written once, with the value it replaced, and never updated. The same rule
  model_calls follows, for the same reason: a record improved with hindsight is not a
  record.
- A change to a number the book calls an assumption rather than evidence must say why.
  The vocabulary is small and closed, so a quarter's changes group and read; the
  analyst's own words ride beside it in ``rationale``.
- The reason travels with the valuation it moved. "pos 0.25 to 0.92" is a number. "pos
  0.25 to 0.92 on the CYCLONE 3 readout, rNPV 1,412mm to 2,840mm" is a changelog entry.

Reading back is forward-only: the last edit at or before a date is the row as it stood,
because the ledger opens with a create for every row already on file. Nothing here
inverts the present, which is what makes a reconstruction defensible.
"""

from __future__ import annotations

import uuid

import evidence

# Why a number moved. Closed, because a changelog whose reasons are free text cannot be
# grouped, counted, or audited, and the analyst's own words have their own column.
REASONS = (
    "readout",               # a trial reported and the odds or the curve moved with it
    "label_change",          # the FDA label gained or lost an indication
    "pricing_update",        # a list price, a discount or a net realisation restated
    "source_restatement",    # the source itself restated the figure
    "epidemiology_update",   # a new prevalence, incidence or eligible fraction
    "correction",            # the number was wrong
    "convention_change",     # a house default moved and the rows that lean on it follow
    "initial_seed",          # the row's first write, from the seed file
    "review",                # an analyst confirmed the grade a rule read off the row
)

# Grades the book reads as an assumption rather than as evidence, in evidence.CLASS terms.
# Changing one of these is a change to a judgement, so it has to carry a reason. An
# ungraded row is weaker still, but it is weak because nobody has graded it rather than
# because somebody judged it, and demanding a reason there would charge the analyst for
# the backfill's unfinished work.
REQUIRES_REASON = ("convention", "judgement")


class ReasonRequired(ValueError):
    """A judgement moved without saying why."""


def new_batch() -> str:
    """An id for one save, so a change set reads as one entry rather than as nine rows."""
    return uuid.uuid4().hex[:16]


def check_reason(reason: str | None) -> str | None:
    """The reason, or a refusal. A reason outside the vocabulary is a typo, not a new kind."""
    if reason is None or not str(reason).strip():
        return None
    name = str(reason).strip().lower()
    if name not in REASONS:
        raise ValueError(f"'{reason}' is not a reason: one of {', '.join(REASONS)}")
    return name


def analyst(given: str | None = None) -> str | None:
    """Who made the change: the caller's word for it, the setting, else the checkout's own
    git identity. Null rather than a guess when the machine cannot say."""
    import os
    import subprocess
    from pathlib import Path

    if given and given.strip():
        return given.strip()
    for name in ("ER_TOOL_ANALYST", "ANALYST"):
        if os.getenv(name):
            return os.environ[name].strip()
    try:
        out = subprocess.run(["git", "config", "user.email"],
                             cwd=Path(__file__).resolve().parent, capture_output=True,
                             text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def code_version() -> str | None:
    """The commit that wrote the change, by the rule call_log already uses."""
    try:
        import call_log
        return call_log.code_version()
    except Exception:                                            # noqa: BLE001
        return None


def requires_reason(old_grade: str | None, new_grade: str | None) -> bool:
    """Whether a move between these two grades has to say why."""
    return old_grade in REQUIRES_REASON or new_grade in REQUIRES_REASON


def names_for(conn, asset_id, indication_id) -> tuple:
    """(ticker, asset name, indication name) as they stand now.

    Written onto every ledger row so a row can say what it is about without a surrogate
    id. A rebuild reissues those ids before the assets exist, so a row carrying only an
    id can stop meaning anything; one carrying the names is always re-resolvable (091,
    backend/relink.py).
    """
    ticker = asset = indication = None
    if asset_id is not None:
        row = conn.execute(
            """SELECT c.ticker AS t,
                      COALESCE(NULLIF(TRIM(a.brand_name), ''), a.generic_name) AS n
                 FROM assets a JOIN companies c ON c.id = a.owner_company_id
                WHERE a.id = ?""", (asset_id,)).fetchone()
        if row is not None:
            ticker, asset = row["t"], row["n"]
    if indication_id is not None:
        row = conn.execute("SELECT name FROM indications WHERE id = ?",
                           (indication_id,)).fetchone()
        if row is not None:
            indication = row["name"]
    return ticker, asset, indication


def record(conn, *, asset_id: int, indication_id, region: str, scenario: str, key: str,
           year, op: str, before: dict | None, after: dict | None,
           changed_by: str | None = None, reason: str | None = None,
           rationale: str | None = None, trigger_ref: str | None = None,
           batch_id: str | None = None, refresh_run_id: int | None = None) -> None:
    """Write one change. Called inside the same transaction as the write it records, so a
    number cannot move without the ledger moving with it."""
    before = before or {}
    after = after or {}
    ticker, asset_name, indication_name = names_for(conn, asset_id, indication_id)
    # OR IGNORE so a reseed cannot log a row's first write twice. The unique index it
    # defers to covers seed rows only (090), so an analyst creating, deleting and
    # recreating a row still records three events.
    conn.execute(
        """INSERT OR IGNORE INTO assumption_edits
               (asset_id, indication_id, region, scenario, key, year, op,
                old_value, old_text, old_unit, old_source, old_note,
                old_evidence, old_evidence_reviewed,
                new_value, new_text, new_unit, new_source, new_note,
                new_evidence, new_evidence_reviewed,
                changed_by, reason, rationale, trigger_ref, batch_id,
                code_version, refresh_run_id,
                ticker, asset_name, indication_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?, ?, ?)""",
        (asset_id, indication_id, region, scenario, key, year, op,
         before.get("value"), before.get("text_value"), before.get("unit"),
         before.get("source"), before.get("note"),
         before.get("evidence"), before.get("evidence_reviewed"),
         after.get("value"), after.get("text_value"), after.get("unit"),
         after.get("source"), after.get("note"),
         after.get("evidence"), after.get("evidence_reviewed"),
         analyst(changed_by), reason, rationale, trigger_ref, batch_id,
         code_version(), refresh_run_id,
         ticker, asset_name, indication_name))


def price_batch(conn, batch_id: str, rnpv_before, rnpv_after) -> None:
    """Attach the valuation the change set moved. The one write a ledger row takes after
    it is inserted, because the effect is only known once the engine has rebuilt: the
    numbers the row already carries are not touched."""
    if not batch_id:
        return
    conn.execute("UPDATE assumption_edits SET rnpv_before = ?, rnpv_after = ?"
                 " WHERE batch_id = ?", (rnpv_before, rnpv_after, batch_id))


# --- reading back ------------------------------------------------------------

def review_queue(conn, limit: int = 200) -> list[dict]:
    """The unreviewed judgements and conventions, grouped by the words that graded them.

    2,192 rows carried an unconfirmed judgement or convention on 2026-10-26, and reading
    that as 2,192 decisions is what made the queue look unworkable. It is not. Twelve
    source sentences carry 1,119 of those rows: "the engine's terminal value is a
    zero-growth perpetuity" is one house convention applied to 354 assets, not 354
    opinions about 354 drugs.

    So the unit of review is the sentence, not the row. An analyst reads the convention
    once and confirms every row that rests on it, and the queue becomes roughly twenty
    decisions and a tail.
    """
    rows = conn.execute(
        """SELECT a.evidence, COALESCE(a.source, '') AS source, COUNT(*) AS rows_on_it,
                  COUNT(DISTINCT a.asset_id) AS assets,
                  COUNT(DISTINCT a.key) AS keys,
                  MIN(a.key) AS a_key, MAX(a.key) AS z_key
             FROM assumptions a
            WHERE a.evidence_reviewed = 0 AND a.evidence IN (?, ?)
            GROUP BY a.evidence, source
            ORDER BY rows_on_it DESC LIMIT ?""",
        (*REQUIRES_REASON, int(limit))).fetchall()
    return [{"evidence": r["evidence"], "source": r["source"],
             "rows": r["rows_on_it"], "assets": r["assets"],
             "keys": r["keys"],
             "key": r["a_key"] if r["a_key"] == r["z_key"] else None}
            for r in rows]


def confirm_grade(conn, source: str, evidence: str, changed_by: str | None = None,
                  rationale: str | None = None) -> dict:
    """Confirm one graded sentence across every row that rests on it.

    The grade is the analyst's to give, so this only ever marks reviewed what a rule had
    already read; it never changes a grade and never touches a value. Each row gets its
    own ledger entry under one batch, because 354 rows becoming confirmed is 354 changes
    to what the book claims about itself, however few keystrokes made it.
    """
    if evidence not in REQUIRES_REASON:
        raise ValueError(f"only {' and '.join(REQUIRES_REASON)} rows are in the queue")
    rows = conn.execute(
        """SELECT * FROM assumptions
            WHERE evidence_reviewed = 0 AND evidence = ?
              AND COALESCE(source, '') = ?""", (evidence, source)).fetchall()
    if not rows:
        return {"confirmed": 0, "batch_id": None}
    batch = new_batch()
    for row in rows:
        before = dict(row)
        after = {**before, "evidence_reviewed": 1}
        conn.execute("UPDATE assumptions SET evidence_reviewed = 1 WHERE id = ?",
                     (row["id"],))
        record(conn, asset_id=row["asset_id"], indication_id=row["indication_id"],
               region=row["region"], scenario=row["scenario"], key=row["key"],
               year=row["year"], op="update", before=before, after=after,
               changed_by=changed_by, reason="review", batch_id=batch,
               rationale=rationale or f"grade {evidence} confirmed on the source it was "
                                      f"read from")
    conn.commit()
    return {"confirmed": len(rows), "batch_id": batch}


BULK_RATIONALE = ("confirmed in bulk, not read row by row")


def confirm_all(conn, changed_by: str | None = None) -> dict:
    """Confirm every unreviewed judgement and convention in one act.

    What it is for: a book whose conventions are already trusted, where an unreviewed
    flag that will never be cleared tells a reader less than a confirmed one.

    What it costs, recorded rather than hidden: ``evidence_reviewed`` is the only field
    in the book that claims a person looked at a row, and after this it claims that of
    rows nobody read. So every ledger entry says so in its own words, and reopen_grade
    is the way back. A reader who later asks who reviewed these gets "confirmed in bulk
    on this date", which is the truth, instead of an implication of care that was not
    taken.
    """
    rows = conn.execute(
        """SELECT * FROM assumptions
            WHERE evidence_reviewed = 0 AND evidence IN (?, ?)""",
        REQUIRES_REASON).fetchall()
    if not rows:
        return {"confirmed": 0, "batch_id": None}
    batch = new_batch()
    for row in rows:
        before = dict(row)
        conn.execute("UPDATE assumptions SET evidence_reviewed = 1 WHERE id = ?",
                     (row["id"],))
        record(conn, asset_id=row["asset_id"], indication_id=row["indication_id"],
               region=row["region"], scenario=row["scenario"], key=row["key"],
               year=row["year"], op="update", before=before,
               after={**before, "evidence_reviewed": 1}, changed_by=changed_by,
               reason="review", batch_id=batch, rationale=BULK_RATIONALE)
    conn.commit()
    return {"confirmed": len(rows), "batch_id": batch}


def reopen_grade(conn, batch_id: str | None = None, source: str | None = None,
                 changed_by: str | None = None) -> dict:
    """Put confirmed grades back in the queue, by the batch that confirmed them or by
    the sentence they rest on.

    The way back. A confirmation that cannot be undone is a one-way door, and a bulk one
    is exactly the kind worth being able to walk back through.
    """
    if not batch_id and not source:
        raise ValueError("name the batch to reopen, or the sentence")
    if batch_id:
        ids = [r["id"] for r in conn.execute(
            """SELECT a.id FROM assumptions a
                 JOIN assumption_edits e ON e.asset_id = a.asset_id AND e.key = a.key
                  AND IFNULL(e.indication_id, 0) = IFNULL(a.indication_id, 0)
                  AND IFNULL(e.year, 0) = IFNULL(a.year, 0)
                  AND e.region = a.region AND e.scenario = a.scenario
                WHERE e.batch_id = ? AND a.evidence_reviewed = 1""", (batch_id,))]
    else:
        ids = [r["id"] for r in conn.execute(
            """SELECT id FROM assumptions WHERE evidence_reviewed = 1
                AND COALESCE(source, '') = ?""", (source,))]
    if not ids:
        return {"reopened": 0, "batch_id": None}
    batch = new_batch()
    for row_id in ids:
        row = conn.execute("SELECT * FROM assumptions WHERE id = ?", (row_id,)).fetchone()
        before = dict(row)
        conn.execute("UPDATE assumptions SET evidence_reviewed = 0 WHERE id = ?",
                     (row_id,))
        record(conn, asset_id=row["asset_id"], indication_id=row["indication_id"],
               region=row["region"], scenario=row["scenario"], key=row["key"],
               year=row["year"], op="update", before=before,
               after={**before, "evidence_reviewed": 0}, changed_by=changed_by,
               reason="review", batch_id=batch,
               rationale="reopened for review")
    conn.commit()
    return {"reopened": len(ids), "batch_id": batch}


def log(conn, asset_id: int | None = None, since: str | None = None,
        reason: str | None = None, limit: int = 200,
        ticker: str | None = None) -> list[dict]:
    """The change set, newest first. The changelog a licensee is handed."""
    where, args = ["1 = 1"], []
    if asset_id is not None:
        where.append("e.asset_id = ?")
        args.append(asset_id)
    if ticker:
        # The ledger's own ticker, not the joined one: a row whose asset the next
        # rebuild has not yet recreated still belongs to the company that wrote it.
        where.append("e.ticker = ?")
        args.append(ticker.upper())
    if since:
        where.append("e.changed_at >= ?")
        args.append(since)
    if reason:
        where.append("e.reason = ?")
        args.append(reason)
    args.append(int(limit))
    return [dict(r) for r in conn.execute(
        f"""SELECT e.*, COALESCE(i.name, e.indication_name) AS indication,
                   COALESCE(a.brand_name, a.generic_name, e.asset_name) AS brand_name,
                   a.generic_name
              FROM assumption_edits e
              LEFT JOIN indications i ON i.id = e.indication_id
              LEFT JOIN assets a ON a.id = e.asset_id
             WHERE {' AND '.join(where)}
             ORDER BY e.changed_at DESC, e.id DESC LIMIT ?""", args)]


def value_at(conn, asset_id: int, key: str, when: str, indication_id=None,
             region: str = "US", scenario: str = "base", year=None) -> dict | None:
    """The row as it stood on a date, or None where it did not exist then.

    The last edit at or before the date is the answer, because the ledger opens with a
    create for every row already on file. A date before the ledger begins has no state to
    give and says None rather than presenting today's number as though it were then's.

    A bare date means the end of that day. Timestamps are compared as text, so a date
    asked for as "2026-10-24" would otherwise sort below every edit made during it and
    report the day before: the state at the close of business is what a date means.
    """
    if when and len(str(when).strip()) == 10:
        when = f"{str(when).strip()} 23:59:59"
    row = conn.execute(
        """SELECT * FROM assumption_edits
            WHERE asset_id = ? AND IFNULL(indication_id, 0) = IFNULL(?, 0)
              AND region = ? AND scenario = ? AND key = ?
              AND IFNULL(year, 0) = IFNULL(?, 0) AND changed_at <= ?
            ORDER BY changed_at DESC, id DESC LIMIT 1""",
        (asset_id, indication_id, region, scenario, key, year, when)).fetchone()
    if row is None or row["op"] == "delete":
        return None
    return {"value": row["new_value"], "text_value": row["new_text"],
            "unit": row["new_unit"], "source": row["new_source"],
            "note": row["new_note"], "evidence": row["new_evidence"],
            "evidence_reviewed": row["new_evidence_reviewed"],
            "as_of": row["changed_at"], "reason": row["reason"],
            "changed_by": row["changed_by"]}


def unreviewed_judgements(conn, asset_id: int | None = None) -> list[dict]:
    """Rows the book reads as an assumption that no analyst has confirmed. The review
    queue: what a reader of the model is entitled to be told is a judgement."""
    args = []
    where = "a.evidence_reviewed = 0 AND a.evidence IN ({})".format(
        ", ".join("?" * len(REQUIRES_REASON)))
    args.extend(REQUIRES_REASON)
    if asset_id is not None:
        where += " AND a.asset_id = ?"
        args.append(asset_id)
    return [dict(r) for r in conn.execute(
        f"""SELECT a.id, a.asset_id, a.key, a.value, a.evidence, a.source, a.note,
                   i.name AS indication, s.brand_name
              FROM assumptions a
              LEFT JOIN indications i ON i.id = a.indication_id
              LEFT JOIN assets s ON s.id = a.asset_id
             WHERE {where} ORDER BY a.asset_id, a.key""", args)]


def classes(conn, asset_id: int) -> dict:
    """How much of one asset's model is evidence, partial evidence and assumption. The
    board sentence evidence.py was written for, counted."""
    out = {"evidence": 0, "partial evidence": 0, "assumption": 0}
    for row in conn.execute("SELECT evidence FROM assumptions WHERE asset_id = ?",
                            (asset_id,)):
        out[evidence.evidence_class(row["evidence"])] += 1
    return out
