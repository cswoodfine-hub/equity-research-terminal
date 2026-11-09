"""Which of a product's indications its label already covers.

Separate from both callers because both need it and neither can import the other:
``assumptions.load`` tags the indications it hands the engine, and ``forecast_view``
refuses a gate on an indication already approved. The rule has to be the same in both
places or a readout could be priced as an expansion by one and dismissed by the other.

The book cannot answer this from the phase. A phase comes from the trials, trials carry
on after an approval, and an approved indication therefore sits at Phase 3 for as long
as anyone is still studying it. Omvoh's Crohn's disease readout stood as a pending
expansion while the label had read "moderately to severely active Crohn's disease in
adults" since January 2025.
"""

from __future__ import annotations

import datetime as dt
import re

import indication_mapping

_LABEL_DAY = "%b %d, %Y"       # the labels table writes "Oct 22, 2026"

# A label says what the product is approved for and also what it is not, and the denial
# carries the disease's own words. Saphnelo's reads "has not been evaluated in patients
# with severe active lupus nephritis", and a test over the whole text found "lupus" and
# "nephritis" in that sentence and called lupus nephritis approved, which dismissed a
# live Phase 3 expansion as deciding nothing. Sentences that deny coverage are dropped
# before the words are read. The cues are specific rather than a bare "not", because a
# real indication sentence says things like "who have not received prior therapy".
_DENIES = re.compile(
    r"limitations? of use"
    r"|ha(?:s|ve) not been (?:evaluated|established|studied)"
    r"|(?:is|are|was|were) not (?:recommended|indicated|approved)"
    r"|should not be used",
    re.I)

# A label states a setting as well as a disease, and the setting is where an expansion
# lives: Etcamah is approved in "locally advanced or metastatic breast cancer" and reads
# out in early breast cancer after adjuvant endocrine therapy. The disease is the same in
# both, so a test on the disease name alone dismissed the expansion as already approved.
# Each entry is a setting and the words a label or a study uses for it, matched against
# text whose punctuation has been flattened to spaces.
SETTINGS = {
    "adjuvant": r"\badjuvant\b",
    "neoadjuvant": r"\bneoadjuvant\b|\bperioperative\b",
    "early stage": (r"\bearly(?:[ -]stage)?\b|\bresect"
                    r"|\bstage\s+(?:i{1,3}[ab]?\d?|[123])\b"
                    r"|\bnon[ -]metastatic\b|\blocali[sz]ed\b"),
    "first line": (r"\bfirst[ -]line\b|\b1l\b|\bpreviously untreated\b"
                   r"|\btreatment[ -]na[iï]ve\b"),
    "maintenance": r"\bmaintenance\b",
    "children": r"\bp(?:a)?ediatric\b|\bchildren\b|\badolescent",
}


def covered_text(label: str) -> str:
    """The label's indications with the sentences that deny coverage removed."""
    if not label:
        return ""
    return " ".join(part for part in re.split(r"(?<=[.;])\s+", label)
                    if not _DENIES.search(part))


def settings_in(text: str) -> set:
    """The settings a piece of text names, by the vocabulary above."""
    flat = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    return {name for name, pattern in SETTINGS.items() if re.search(pattern, flat)}


def setting_gap(conn, asset_id: int, nct) -> str | None:
    """The setting a study sits in that its product's label does not state, or None.

    Asked of a study whose disease the label already covers, so the only question left
    is whether the label covers the setting too. A study that names no setting at all is
    read as covered, which keeps a post-marketing comparison in an approved use where it
    belongs: Airsupra against its own component, Breztri in COPD.
    """
    if not nct or not str(nct).startswith("NCT"):
        return None
    trial = conn.execute("SELECT title, conditions FROM trials WHERE nct_id = ?",
                         (str(nct),)).fetchone()
    if trial is None:
        return None
    study = settings_in(f"{trial['title'] or ''} {trial['conditions'] or ''}")
    if not study:
        return None
    label = settings_in(covered_text(current_label(conn, asset_id) or ""))
    missing = sorted(study - label)
    return missing[0] if missing else None


def current_label(conn, asset_id: int):
    """The newest label's indications text, or None.

    The date is parsed rather than sorted in SQL. ``effective_time`` is text in the
    file's own format, so an ORDER BY on it sorts alphabetically: August beats October
    and December beats January, which picks a label at random among a product's
    revisions. A stale label is the one case that matters, because an indication
    approved since would read as unapproved.
    """
    best, best_day = None, None
    for row in conn.execute(
            "SELECT effective_time, indications_text FROM labels"
            "  WHERE asset_id = ? AND indications_text IS NOT NULL", (asset_id,)):
        try:
            day = dt.datetime.strptime((row["effective_time"] or "").strip(),
                                       _LABEL_DAY).date()
        except (ValueError, TypeError):
            day = None
        if best is None or (day and (best_day is None or day > best_day)):
            best, best_day = row["indications_text"], day
    return best


def for_asset(conn, asset_id: int) -> set:
    """The asset_indication ids this product is already approved in.

    Two tests, both conservative, and both failing towards treating an indication as
    unapproved rather than silently removing a gate or a layer.

    Phase 4 is a post-marketing study, which is what the phase means. And an indication
    whose name sits inside what the label says it covers is approved, compared on
    ``indication_mapping.tokens``, the vocabulary the book already matches studies to
    diseases with. That comparison separates the paediatric readouts from the adult ones
    with no extra rule: "Crohn Disease" is found inside "moderately to severely active
    Crohn's disease in adults", and "Pediatric Crohn's disease", which carries a token
    the adults-only label does not, is not.
    """
    pairs = conn.execute(
        "SELECT ai.id, ai.phase, i.name FROM asset_indications ai"
        "  JOIN indications i ON i.id = ai.indication_id"
        " WHERE ai.asset_id = ?", (asset_id,)).fetchall()
    if not pairs:
        return set()
    said = set(indication_mapping.tokens(
        covered_text(current_label(conn, asset_id) or "")))
    out = set()
    for pair in pairs:
        if (pair["phase"] or "") == "Phase 4":
            out.add(pair["id"])
            continue
        mine = set(indication_mapping.tokens(pair["name"] or ""))
        if mine and said and mine <= said:
            out.add(pair["id"])
    return out


def indication_ids(conn, asset_id: int) -> set:
    """The same answer keyed on the indication rather than on the pair, which is what
    the engine's per-indication entries carry."""
    approved = for_asset(conn, asset_id)
    if not approved:
        return set()
    marks = ",".join("?" * len(approved))
    return {r[0] for r in conn.execute(
        f"SELECT indication_id FROM asset_indications WHERE id IN ({marks})",
        tuple(sorted(approved)))}
