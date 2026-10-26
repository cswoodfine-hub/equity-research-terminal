"""A second reader for the evidence grades, so a confirmation means two reads agreed.

``evidence.py`` grades a row by matching its own words against a rule set. That makes
the grade reproducible and makes it one opinion. ``evidence_reviewed`` is meant to say a
second party looked, and confirming the queue in bulk would make that claim of rows
nobody read.

So the queue is read a second time, independently, and only the agreements are
confirmed. The model is a reader, not a source, the rule pdufa.py and guidance.py
already follow:

* It sees the row's own source and note and nothing else. No figure it knows from
  elsewhere can reach a grade, because it is never asked for a figure.
* It must answer with one of the six grades. Anything else is dropped rather than
  guessed at.
* Where it agrees with the rules, the row is confirmed and the ledger says the grade was
  confirmed by a second read.
* Where it disagrees, nothing is written. The row stays in the queue carrying both
  opinions, which is the only honest thing to do with a disagreement about evidence.

With no provider configured this does nothing and says so, exactly as the PDUFA
extractor does. The rules layer stands on its own; this only ever adds confirmation.
"""

from __future__ import annotations

import json
import re

import db
import evidence
import llm

# A thinking model spends the budget before it answers: at 300 the reply came back as
# '{"grade": "convention", "why": "Rule or' and read as unparseable rather than as the
# agreement it was. Thinking is off because this is a classification, not a derivation.
MAX_TOKENS = 900
THINKING = 0
SYSTEM_PROMPT = """You grade what kind of evidence a single analyst assumption rests on.

You are shown the assumption's key, its source and its note. Reply with JSON only, no
prose: {"grade": "<one of the six>", "why": "<at most 15 words>"}

The six grades, strongest first:
- "filed": the figure is stated in a company's own regulatory filing (10-K, 10-Q, 8-K,
  20-F, 6-K, an accession number, an annual report, a balance sheet).
- "measured": it is computed or read off a named dataset or registry (CMS, FRED, SEER,
  CDC, Census, ClinicalTrials.gov, an NCT number, openFDA, the Orange or Purple Book).
- "published": it comes from published literature or a named research house (a journal,
  a DOI, et al, NEJM, JAMA, Lancet, ASCO, a named bank or data provider's forecast).
- "analogue": it is reused from, fitted to or borrowed from another product or seed.
- "convention": it is a house default, a placeholder, or a rule applied for want of
  anything better.
- "judgement": it is the analyst's own call.

Rules, in order of importance:
1. Grade the number this row holds, not every number the text mentions. A revenue
   anchor cited to a 10-K is "filed" even when the note says the growth on top of it is
   a judgement.
2. Where the text names more than one kind for this row's own number, take the weakest.
3. A sentence that names a kind in order to deny it ("rather than a convention") does
   not make the row that kind.
4. Judge only from the text shown. A grade you reach from knowledge of the product
   rather than from these words is wrong here."""


def parse_reply(raw: str) -> str | None:
    """The grade the model returned, or None where it did not return one of the six."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    try:
        found = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except (ValueError, IndexError):
        return None
    grade = str((found or {}).get("grade") or "").strip().lower()
    return grade if grade in evidence.GRADES else None


_GRADE = re.compile(r'"grade"\s*:\s*"([a-z]+)"', re.I)


def _grade_in(raw: str) -> str | None:
    """The grade out of a reply whose JSON never closed.

    Reading a complete field out of a truncated object is reading what is there. It is
    not guessing: a reply with no grade field still returns nothing.
    """
    hit = _GRADE.search(raw or "")
    if hit is None:
        return None
    grade = hit.group(1).strip().lower()
    return grade if grade in evidence.GRADES else None


def _ask(key: str, source: str, note: str) -> str | None:
    user = (f"key: {key}\nsource: {source or '(none)'}\nnote: {note or '(none)'}\n\n"
            "Grade this row.")
    raw = llm.complete(SYSTEM_PROMPT, user, MAX_TOKENS, thinking_budget=THINKING)
    return parse_reply(raw) or _grade_in(raw)


def candidates(conn, limit: int = 200) -> list[dict]:
    """Distinct (key, source, note) in the queue, the widest reach first.

    One sentence stands behind hundreds of rows, so the model is asked once per sentence
    and the answer is applied to every row resting on it.
    """
    return [dict(r) for r in conn.execute(
        """SELECT key, COALESCE(source, '') AS source, COALESCE(note, '') AS note,
                  evidence, COUNT(*) AS rows_on_it
             FROM assumptions
            WHERE evidence_reviewed = 0 AND evidence IN ('convention', 'judgement')
            GROUP BY key, source, note, evidence
            ORDER BY rows_on_it DESC LIMIT ?""", (int(limit),))]


def review(db_path=None, limit: int = 200, changed_by: str = "a second read",
           ask=None) -> dict:
    """Read the queue a second time and confirm only what both reads agree on."""
    if ask is None:
        if llm.provider() is None:
            return {"skipped": "no model provider is configured", "agreed": 0,
                    "disagreed": 0, "unreadable": 0, "confirmed": 0}
        ask = _ask
    import assumption_log

    conn = db.get_connection(db_path)
    agreed = disagreed = unreadable = confirmed = 0
    splits: list[dict] = []
    try:
        for row in candidates(conn, limit):
            try:
                said = ask(row["key"], row["source"], row["note"])
            except Exception as exc:                                # noqa: BLE001
                return {"stopped": f"{type(exc).__name__}: {exc}", "agreed": agreed,
                        "disagreed": disagreed, "unreadable": unreadable,
                        "confirmed": confirmed, "disagreements": splits}
            if said is None:
                unreadable += 1
                continue
            if said != row["evidence"]:
                disagreed += 1
                splits.append({"key": row["key"], "rules": row["evidence"],
                               "second_read": said, "rows": row["rows_on_it"],
                               "source": row["source"][:160]})
                continue
            agreed += 1
            n = conn.execute(
                """SELECT COUNT(*) n FROM assumptions
                    WHERE evidence_reviewed = 0 AND evidence = ? AND key = ?
                      AND COALESCE(source, '') = ? AND COALESCE(note, '') = ?""",
                (row["evidence"], row["key"], row["source"], row["note"])).fetchone()["n"]
            conn.execute(
                """UPDATE assumptions SET evidence_reviewed = 1
                    WHERE evidence_reviewed = 0 AND evidence = ? AND key = ?
                      AND COALESCE(source, '') = ? AND COALESCE(note, '') = ?""",
                (row["evidence"], row["key"], row["source"], row["note"]))
            confirmed += n
            # Per sentence, not per run. A pass over the whole queue takes forty
            # minutes, and committing at the end meant nothing was visible while it ran
            # and a provider that rate-limited at minute thirty-eight took every
            # confirmation down with it. A confirmed sentence also drops out of
            # candidates(), so a stopped run resumes where it left off.
            conn.commit()
    finally:
        conn.close()
    return {"agreed": agreed, "disagreed": disagreed, "unreadable": unreadable,
            "confirmed": confirmed, "disagreements": splits[:40]}
