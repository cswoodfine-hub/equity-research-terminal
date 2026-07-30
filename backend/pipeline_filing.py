"""The programmes a company describes in its own filing but has not yet put in a trial.

Every other route into the asset table needs a registered study or an approval:
trial_mapping reads ClinicalTrials.gov interventions, assets_util reads FDA marketed
products, revenue_mdna reads the product revenue table. So a programme that is preclinical
or has an IND and no registered study cannot exist in the model at all, however plainly the
filing describes it. Dyne names eight programmes in its 10-Q and the app held two: DYNE-302
had FDA clearance to start a Phase 1 in FSHD and was nowhere.

This reads the rest of them out of the text that is already stored. Three rules keep it
from inventing a pipeline:

It never assigns a phase. A phase means a registered trial, and a registered trial is
already the trial mapper's job; a company that says it "plans to evaluate DYNE-302 in a
Phase 1" has not started one. What this records is the stage the filing states in its own
words, from IND cleared down to discovery, and nothing when the filing states none.

It only takes a programme the company claims as its own. The test is a first-person
sentence, "we are developing DYNE-302", because a filing names other companies' compounds
too: Merck's discussion mentions TERN-701 and Solid's mentions Entrada's ENTR-601. A
sentence that names another organisation is not ownership evidence, whoever it mentions.

It never overwrites a trial. A code the company already holds an asset for is skipped, so
this can only add what the registry does not have.

The evidence sentence is stored with every row, because a reader who does not believe
"DYNE-302, FSHD, IND cleared" needs the sentence that said so and the filing it came from.

What it still gets wrong: a trial's name has the same shape as a compound's, and the tests
that separate them are the word next to it and whether its prefix is an ordinary word.
Exelixis names STELLAR-001 through STELLAR-316 in a list with neither signal, so four of
them read as programmes. That is why every row carries its sentence and its accession. The
error is visible rather than silent, and it is one an analyst can delete.
"""

from __future__ import annotations

import re

import asset_merge
import db

# The stages a filing states, most advanced first. A programme takes the furthest one any
# sentence about it supports. No phase appears here by design: see the module docstring.
STAGE_PATTERNS = (
    ("IND cleared", (r"\bclearance\b.{0,80}?\b(?:investigational new drug|IND)\b",
                     r"\bIND\b.{0,60}?\b(?:cleared|clearance|allowed to proceed)\b",
                     r"\bcleared\b.{0,60}?\bIND\b")),
    ("IND-enabling", (r"\bIND[- ]enabling\b",)),
    ("Development candidate", (r"\bdevelopment candidate",)),
    ("Preclinical", (r"\bpre-?clinical\b",)),
    ("Discovery", (r"\bdiscovery[- ](?:stage|phase|program|effort)",)),
)
STAGES = tuple(name for name, _patterns in STAGE_PATTERNS)

# The company talking about itself. Without this the reader of a Merck filing would find
# TERN-701 in Merck's pipeline because the filing happens to name it.
_FIRST_PERSON = re.compile(r"\b(?:we|our|us|ours)\b", re.IGNORECASE)

# Somebody else talking. A capitalised word followed by a corporate form is another party,
# so the sentence stops counting as ownership evidence even though it says "we". The comma
# is optional because "Moderna, Inc." is written that way and was getting through.
_OTHER_PARTY = re.compile(
    r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?,?\s+"
    r"(?:Inc\.?|Ltd\.?|LLC|L\.L\.C\.|plc|PLC|AG|SE|N\.V\.|S\.A\.|Corporation|Corp\.?|"
    r"Therapeutics|Pharmaceuticals|Pharma|Biosciences|Biotherapeutics|Biopharma|"
    r"Bioscience|Medicines|Laboratories)\b")

# What the programme is for. Tried in order; the first that answers wins. A bare "in X" is
# not among them: across the universe it read "in November 2025", "in Lexington" and "in
# Phase 1 clinical development" far more often than it read a disease.
_INDICATION = (
    r"for the (?:potential )?treatment of\s+(?P<what>[A-Za-z][^.;:()]{2,70})",
    r"product candidate for\s+(?P<what>[A-Za-z][^.;:()]{2,70})",
    r"\bour\s+(?P<what>[A-Za-z][A-Za-z0-9/ -]{1,40}?)\s+product candidate",
    r"\bin\s+(?:patients|participants|individuals|adults|people)\s+with\s+"
    r"(?P<what>[A-Za-z][^.;:()]{2,70})",
)

# A captured phrase that is not a disease. Dates and phases are what a filing puts next to
# a programme most often after the disease itself.
_NOT_AN_INDICATION = re.compile(
    r"^(?:phase\b|january|february|march|april|may|june|july|august|september|october|"
    r"november|december|\d)", re.IGNORECASE)

# Where a disease name ends and a subpopulation begins. "DMD amenable to skipping of exons
# 53, 45, 44, 55" is four programmes in one sentence and one disease, so the qualifier is
# cut rather than attached to whichever code happened to be first.
_QUALIFIER = re.compile(
    r"\s+(?:amenable\b|who\b|with\b|in patients\b|in participants\b|in adults\b|"
    r"in individuals\b|that\b|which\b|caused by\b)", re.IGNORECASE)

# A sentence has to be a sentence. Section text carries table fragments and headings, and
# a run of digits and single words is not a claim about a programme.
_SENTENCE = re.compile(r"(?<=[.;])\s+")

# Things that are named like a compound and are not one: a trial (STELLAR-303,
# FORWARD-53), a capsid (POLARIS-101), a platform, an assay. What separates them from a
# drug is that the name sits directly against the noun, "the STELLAR-303 trial", while a
# drug reached by a preposition is what the study is of: "a Phase 1 clinical trial for
# DYNE-302". So the match has to be adjacent, with nothing but punctuation between. A
# window of a few words instead threw away the sentence saying Dyne's IND was cleared.
_ARTEFACT = (r"(?:trial|study|studies|cohort|registry|capsid|vector|platform|"
             r"technology|trademark|mark|assay|construct|promoter|cell line)")
_ADJACENT = 3

# How many times a code has to appear in the document before it counts as a programme
# rather than a stray token.
MIN_MENTIONS = 2


def _clean(sentence: str) -> str:
    return " ".join((sentence or "").split())


def _names_an_artefact(text: str, code: str) -> bool:
    """Whether this token is a trial, a capsid or a platform rather than a compound.

    Judged over the whole document, not the sentence in hand. Exelixis introduces its
    trial once, "Our first such trial, STELLAR-303, was initiated in June 2022", and then
    lists STELLAR-001 through STELLAR-316 without the word again. A token is one kind of
    thing or the other throughout, so one sighting settles it everywhere.
    """
    escaped = re.escape(code)
    adjacent = (rf"{escaped}\W{{0,{_ADJACENT}}}{_ARTEFACT}\b"
                rf"|\b{_ARTEFACT}\W{{0,{_ADJACENT}}}{escaped}")
    return bool(re.search(adjacent, text, re.IGNORECASE))


def _is_a_word(text: str, code: str) -> bool:
    """Whether the code's prefix is an ordinary word rather than a family name.

    Wave's FORWARD-53 is a trial, and "forward" appears lower case in the same filing, in
    "forward-looking statements". A company's own prefix does not: DYNE, SRP, CTX, AXS and
    BEAM are never written as words, even the one that is a word.
    """
    prefix = re.match(r"^([A-Z]+)", code)
    if not prefix or len(prefix.group(1)) < 3:
        return False
    return bool(re.search(rf"\b{prefix.group(1).lower()}\b", text))


def _codes_in(sentence: str, excluded: set = frozenset()) -> set:
    return asset_merge.development_codes(sentence) - excluded


def _stage(sentence: str) -> str | None:
    for name, patterns in STAGE_PATTERNS:
        if any(re.search(p, sentence, re.IGNORECASE) for p in patterns):
            return name
    return None


def _indication(sentence: str, code: str) -> str | None:
    """The disease the sentence attaches to this code, or None.

    Read from the code forward, so a sentence naming two programmes gives each the
    indication that follows it rather than the first one in the sentence.
    """
    start = sentence.upper().find(code)
    tail = sentence[start + len(code):] if start >= 0 else sentence
    for pattern in _INDICATION:
        match = re.search(pattern, tail)
        if not match:
            continue
        what = _QUALIFIER.split(match.group("what"), 1)[0].strip(" ,;:-")
        if len(what) < 3 or _NOT_AN_INDICATION.match(what):
            continue
        return what
    return None


def programmes(text: str, company_name: str = "", corroboration: str = "") -> list:
    """Every programme the text claims as the company's own, with its stated stage.

    ``corroboration`` is further text from the same filing, used only to count how often a
    code appears. Dyne names DYNE-244, 245, 253 and 255 once each in the MD&A, in a single
    sentence putting all four into IND-enabling studies, and a threshold of one mention
    would let a typo through. The risk factors name the same four, which is corroboration
    that the code is real without treating a risk factor as a pipeline description.

    Pure: takes filing text and returns rows. The caller decides which of them are new.
    """
    sentences = [_clean(s) for s in _SENTENCE.split(text or "")]
    whole = " ".join(sentences)
    # Judged once over the whole document: a token is a trial name or a drug name
    # throughout, not one in each sentence.
    artefacts = {code for code in asset_merge.development_codes(whole)
                 if _names_an_artefact(whole, code) or _is_a_word(whole, code)}

    mentions: dict = {}
    for sentence in sentences + [_clean(corroboration)]:
        for code in _codes_in(sentence, artefacts):
            mentions[code] = mentions.get(code, 0) + 1

    found: dict = {}
    for sentence in sentences:
        if not _FIRST_PERSON.search(sentence):
            continue
        # The company naming itself is not another party, so its own name is removed
        # before the test rather than special-cased inside it.
        without_self = (sentence.replace(company_name, " ") if company_name else sentence)
        if _OTHER_PARTY.search(without_self):
            continue
        stage = _stage(sentence)
        for code in _codes_in(sentence, artefacts):
            if mentions.get(code, 0) < MIN_MENTIONS:
                continue
            entry = found.setdefault(code, {"code": code, "stage": None,
                                            "indication": None, "evidence": None})
            if stage and (entry["stage"] is None
                          or STAGES.index(stage) < STAGES.index(entry["stage"])):
                entry["stage"] = stage
                entry["evidence"] = sentence
            indication = _indication(sentence, code)
            if indication and not entry["indication"]:
                entry["indication"] = indication
                entry["evidence"] = entry["evidence"] or sentence
            entry["evidence"] = entry["evidence"] or sentence
    return sorted(found.values(), key=lambda r: r["code"])


def owned_codes(conn, company_id: int) -> set:
    """Every development code the company holds an asset for from some other source.

    Rows this module wrote are deliberately excluded, so a programme it already knows is
    re-read rather than frozen at the stage it was first seen at. DYNE-302 was preclinical
    for two years and IND-cleared in July; the row has to be able to follow that.
    """
    out = set()
    for row in conn.execute(
            "SELECT generic_name, brand_name, internal_code FROM assets"
            "  WHERE owner_company_id = ? AND id NOT IN"
            "    (SELECT asset_id FROM filing_programmes WHERE asset_id IS NOT NULL)",
            (company_id,)):
        out |= asset_merge.development_codes(
            " ".join(str(row[f]) for f in row.keys() if row[f]))
    return out


def latest_section(conn, company_id: int):
    """The most recent narrative section on file, whichever form carried it.

    The MD&A is where a filer describes its programmes. Risk factors name the same codes
    and describe what could go wrong with them, which is not a pipeline.
    """
    return conn.execute(
        "SELECT accession, form_type, filed_date, text FROM filing_sections"
        "  WHERE company_id = ? AND section = 'mdna' AND text IS NOT NULL"
        "  ORDER BY filed_date DESC LIMIT 1", (company_id,)).fetchone()


def extract(conn, company_id: int, ticker: str = "", name: str = "") -> list:
    """The company's filing-only programmes: named by it, and not already in the model."""
    section = latest_section(conn, company_id)
    if section is None:
        return []
    other = conn.execute(
        "SELECT text FROM filing_sections WHERE company_id = ? AND accession = ?"
        "  AND section != 'mdna' AND text IS NOT NULL", (company_id, section["accession"]))
    corroboration = " ".join(row["text"] for row in other)
    known = owned_codes(conn, company_id)
    rows = []
    for entry in programmes(section["text"], name, corroboration):
        if entry["code"] in known:
            continue                      # the registry already has it, with a phase
        rows.append({**entry, "company_id": company_id, "ticker": ticker,
                     "accession": section["accession"],
                     "form_type": section["form_type"],
                     "filed_date": section["filed_date"]})
    return rows


def build(db_path=None) -> dict:
    """Write each filing-only programme as an asset and record where it came from.

    Idempotent: a programme already on file is updated in place, and one that has since
    acquired a trial is skipped by the owned-code test rather than duplicated.
    """
    conn = db.get_connection(db_path)
    created = updated = 0
    try:
        for company in conn.execute("SELECT id, ticker, name FROM companies ORDER BY ticker"):
            for row in extract(conn, company["id"], company["ticker"], company["name"]):
                existing = conn.execute(
                    "SELECT id, asset_id FROM filing_programmes"
                    "  WHERE company_id = ? AND code = ?",
                    (company["id"], row["code"])).fetchone()
                note = (f"named in the {row['form_type']} filed {row['filed_date']}, "
                        "no trial on file")
                if existing is None:
                    cursor = conn.execute(
                        "INSERT INTO assets (owner_company_id, generic_name,"
                        "  internal_code, is_marketed, notes) VALUES (?, ?, ?, 0, ?)",
                        (company["id"], row["code"], row["code"], note))
                    asset_id = cursor.lastrowid
                    created += 1
                else:
                    asset_id = existing["asset_id"]
                    conn.execute("UPDATE assets SET notes = ?, updated_at = datetime('now')"
                                 "  WHERE id = ?", (note, asset_id))
                    updated += 1
                conn.execute(
                    "INSERT INTO filing_programmes (company_id, asset_id, code, stage,"
                    "    indication, evidence, accession, form_type, filed_date)"
                    "  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    "  ON CONFLICT(company_id, code) DO UPDATE SET"
                    "    stage = excluded.stage, indication = excluded.indication,"
                    "    evidence = excluded.evidence, accession = excluded.accession,"
                    "    form_type = excluded.form_type,"
                    "    filed_date = excluded.filed_date,"
                    "    updated_at = datetime('now')",
                    (company["id"], asset_id, row["code"], row["stage"],
                     row["indication"], row["evidence"], row["accession"],
                     row["form_type"], row["filed_date"]))
        conn.commit()
    finally:
        conn.close()
    return {"created": created, "updated": updated}


def prune(db_path=None) -> dict:
    """Drop a filing-derived programme that has since been bound to a trial elsewhere.

    Nothing here should compete with the registry. Once a study names the compound the
    trial mapper owns it, and this row would be the second copy.
    """
    conn = db.get_connection(db_path)
    dropped = 0
    try:
        for row in conn.execute(
                "SELECT p.id, p.asset_id FROM filing_programmes p"
                "  JOIN trials t ON t.asset_id = p.asset_id").fetchall():
            conn.execute("DELETE FROM filing_programmes WHERE id = ?", (row["id"],))
            dropped += 1
        conn.commit()
    finally:
        conn.close()
    return {"dropped": dropped}
