"""What kind of thing a drug is, across companies.

The terminal is organised by ticker, and the questions worth asking are not. "Cell
therapy is having a bad month" spans Gilead, Legend, Autolus and Iovance; "the editors
are being repriced" spans Intellia, Beam, CRISPR and Prime. Neither is answerable from
a company view, and neither is what a therapeutic area says: oncology holds a CAR-T, a
checkpoint antibody and a small molecule, which trade on completely different news.

So this is the modality axis. Keyword rules, deterministic and readable, in the shape of
therapeutic_areas.py and for the same reason: the rule that tagged something can be read
here, and no key is needed to run it.

Two things it does that an area classifier does not. A drug can carry several themes,
because a CAR-T is a cell therapy and both are worth counting; the parent is implied
rather than repeated in the keywords. And every tag records the phrase that produced it,
so "why is this a radioligand" is answerable without rerunning anything.
"""

from __future__ import annotations

import re

# Ordered most specific first, so an autologous CAR-T reads as CAR-T rather than as
# cell therapy generally. Keywords are matched on word boundaries: "til" is a real
# modality abbreviation and also the middle of "until".
THEMES: tuple = (
    ("CAR-T", (
        r"car-?\s?t\b", r"chimeric antigen receptor", r"car-?nk\b", r"cart-?\d",
        # WHO assigns -cabtagene to CAR-T constructs, so the name itself says so:
        # ciltacabtagene, idecabtagene, lisocabtagene, brexucabtagene, obecabtagene.
        r"cabtagene",
    )),
    ("TCR and TIL", (
        r"\btil\b", r"tumou?r[- ]infiltrating lymphocyte", r"\btcr-?t\b",
        r"engineered t[- ]cell receptor",
    )),
    ("Cell therapy", (
        r"cell therap(?:y|ies)", r"\ballogeneic\b", r"\bautologous\b", r"stem cell",
        r"\bnk cell", r"regulatory t[- ]cell", r"\btreg\b",
        # -cel closes every cell-therapy INN: autotemcel, autoleucel, eucel, demcel.
        # -leucel sits here rather than under TIL because both a CAR-T and a TIL carry
        # it (ciltacabtagene autoleucel, lifileucel); it means autologous leukocytes and
        # nothing narrower. CAR-T is tested first and claims its own by -cabtagene.
        r"\w{4,}(?:tem|leu|eu|dem|mo)cel\b",
    )),
    ("Gene editing", (
        r"\bcrispr\b", r"\bcas9\b", r"\bcas12", r"base[- ]edit", r"prime[- ]edit",
        r"zinc finger", r"\btalen\b", r"gene[- ]edit",
        # exagamglogene, reshcabtagene: -glogene marks an edited construct.
        r"\w+glogene\b",
    )),
    ("Gene therapy", (
        r"\baav\b", r"adeno-?associated", r"\blentiviral\b", r"gene therap(?:y|ies)",
        r"gene transfer", r"\bvector\b.{0,20}gene",
        # -gene as the INN's first word plus a -vec or -cel partner: onasemnogene
        # abeparvovec, etranacogene dezaparvovec, betibeglogene autotemcel.
        r"\w+parvovec\b", r"\w+repvec\b", r"\w+gene\s+\w+vec\b",
    )),
    ("Antibody-drug conjugate", (
        r"antibody[- ]drug conjugate", r"\badc\b",
        # How a label words it: "HER2-directed antibody and topoisomerase inhibitor
        # conjugate". Anchored to "antibody" so a plain "conjugate" cannot claim it.
        r"antibody\b.{0,48}\bconjugate\b",
        # The conjugate stem is its own word in an INN: "fam-trastuzumab deruxtecan-nxki",
        # not one word. Requiring it to be attached matched none of them.
        r"\bvedotin\b", r"\bderuxtecan\b", r"\bmafodotin\b", r"\bgovitecan\b",
        r"\btirumotecan\b", r"\bemtansine\b", r"\bozogamicin\b", r"\btesirine\b",
    )),
    ("T-cell engager", (
        r"bispecific", r"trispecific", r"t[- ]cell engager", r"\bbite\b",
        r"\bcd3\b.{0,12}engag",
    )),
    ("Radioligand", (
        r"radioligand", r"radiopharmaceutical", r"\blutetium\b", r"177lu", r"\bactinium\b",
        r"225ac", r"radioconjugate", r"\bpsma\b.{0,14}(?:therapy|177|lutetium)",
    )),
    ("Protein degrader", (
        r"degrader", r"\bprotac\b", r"molecular glue", r"degradation of",
    )),
    ("RNA", (
        r"\bsirna\b", r"antisense", r"\baso\b", r"oligonucleotide", r"\brnai\b",
        r"gapmer", r"exon[- ]skipping",
        # -siran is the siRNA stem (patisiran, inclisiran, vutrisiran, fitusiran);
        # -rsen the antisense one (nusinersen, tofersen, eteplirsen, casimersen).
        r"\w+siran\b", r"\w+rsen\b",
    )),
    ("mRNA", (
        r"\bmrna\b", r"messenger rna", r"self[- ]amplifying rna", r"\bsarna\b",
    )),
    ("Incretin", (
        r"\bglp-?1\b", r"\bgip\b", r"glucagon receptor", r"\bamylin\b",
        r"tirzepatide", r"semaglutide", r"retatrutide", r"orforglipron", r"survodutide",
    )),
    ("Checkpoint", (
        r"\bpd-?1\b", r"\bpd-?l1\b", r"\bctla-?4\b", r"checkpoint inhibitor",
        r"\blag-?3\b", r"\btigit\b",
    )),
    ("Vaccine", (
        r"\bvaccines?\b", r"immuni[sz]ation", r"\bvaccination\b",
    )),
)

# A CAR-T is a cell therapy; an editor is delivered as a gene therapy often enough that
# the parent is implied, not asserted. Kept separate from the keywords so the specific
# rule stays readable and the hierarchy is stated once.
PARENTS = {
    "CAR-T": "Cell therapy",
    "TCR and TIL": "Cell therapy",
    "Gene editing": "Gene therapy",
    "mRNA": "RNA",
}

_COMPILED = tuple((name, tuple(re.compile(p, re.I) for p in patterns))
                  for name, patterns in THEMES)


def classify(*texts) -> dict:
    """{theme: the phrase that matched} for everything the texts show this drug to be.

    Empty when nothing matches, which is the honest answer for most small molecules:
    a kinase inhibitor is not a modality story and should not be filed under one.
    """
    blob = " ".join(str(t) for t in texts if t)
    if not blob.strip():
        return {}
    found: dict = {}
    for name, patterns in _COMPILED:
        for pattern in patterns:
            match = pattern.search(blob)
            if match:
                found[name] = match.group(0).strip()
                break
    for child, parent in PARENTS.items():
        if child in found and parent not in found:
            found[parent] = f"implied by {child}"
    return found


def theme_names() -> list:
    return [name for name, _ in THEMES]


# A label opens by saying what the drug is: "ENHERTU is a HER2-directed antibody and
# topoisomerase inhibitor conjugate indicated for...". That clause is the FDA's own
# class statement and describes nothing but this drug, which is what makes it safe to
# read where the rest of the indications text is not: the prose after "indicated"
# names prior therapies and comparators, and tagging a drug with those is how Darzalex
# became a CAR-T. So the match stops at "indicated".
_CLASS_CLAUSE = re.compile(
    r"\b(?:is|are)\s+(?:a|an|the)?\s*(.{0,220}?)\bindicated\b", re.I | re.S)


def class_clause(indications_text: str) -> str | None:
    """The label's own statement of what the drug is, or None when it does not make one.

    Roughly one label in six goes straight to "X is indicated for", claiming no class.
    That returns None rather than a guess.
    """
    match = _CLASS_CLAUSE.search(indications_text or "")
    if not match:
        return None
    clause = match.group(1).strip()
    if not clause:
        return None
    # Where a label makes no class statement, the first "is" belongs to the indication
    # itself, and reading that describes the disease rather than the drug. These words
    # mark that prose, so the clause is refused rather than half-trusted.
    if any(word in clause.lower() for word in
           ("patients", "treatment of", "adults", "who have", "in combination")):
        return None
    return clause


def _own_interventions(conn, asset_id: int, own_names) -> list:
    """The intervention names on this asset's studies that name this asset.

    A study's intervention list holds the comparator and the combination partners too,
    and reading those tags a drug with what it was tested against. So a name is kept
    only when one of the asset's own names appears in it: "DJI136 CAR-T cells" is
    DJI136 described more fully, and the CAR-T in the control arm is a different drug.
    """
    import trial_mapping

    canon = {c for c in (trial_mapping.canonical(str(n)) for n in own_names)
             if c and len(c) > 2}
    if not canon:
        return []
    rows = conn.execute(
        "SELECT DISTINCT i.name FROM trial_interventions i"
        " WHERE i.nct_id IN (SELECT nct_id FROM trials WHERE asset_id = ?"
        "                    UNION SELECT nct_id FROM completed_trials WHERE asset_id = ?)"
        " LIMIT 400", (asset_id, asset_id)).fetchall()
    kept = []
    for row in rows:
        name = row[0] or ""
        norm = trial_mapping.canonical(name) or ""
        # Substring on the canonical form, so spacing and punctuation cannot decide it.
        if any(c in norm for c in canon):
            kept.append(name)
    return kept


def derive(db_path=None) -> dict:
    """Tag every asset with the themes its own words show it to be.

    Only text that refers to this drug is read. That restriction is the whole design.
    A trial lists its comparator and its combination partners alongside the drug under
    study, so classifying an asset from its trials' full intervention lists tagged
    Darzalex as a CAR-T and Columvi as an antibody-drug conjugate, on the evidence of
    what they were tested against. Trial titles leak the same way, and a label's
    indications say what a drug treats rather than what it is.

    So the text is the asset's own names, plus the intervention names that name this
    asset: "DJI136 CAR-T cells" describes DJI136 and is worth reading, while the CAR-T
    in the next arm of the same study is not.

    The cost is recall. A cell therapy called only by a code number, whose registry
    entry adds nothing, stays untagged, and that is the right failure: no theme reads
    as no theme, where a wrong theme reads as a fact.

    Idempotent: the table is rebuilt from scratch on each run.
    """
    import db
    import trial_mapping

    conn = db.get_connection(db_path)
    written = 0
    try:
        # Cleared first, so a tag whose evidence has gone disappears rather than
        # lingering from an earlier vocabulary. Inside the transaction, so a failure
        # part-way leaves yesterday's tags rather than none.
        conn.execute("DELETE FROM asset_themes")
        assets = conn.execute(
            "SELECT id, brand_name, generic_name, internal_code FROM assets").fetchall()
        for asset in assets:
            own_names = [x for x in (asset["brand_name"], asset["generic_name"],
                                     asset["internal_code"]) if x]
            found: dict = {}
            label = (conn.execute(
                "SELECT indications_text FROM labels WHERE asset_id = ?"
                "  ORDER BY effective_time DESC LIMIT 1", (asset["id"],)).fetchone()
                or [None])[0]
            for source, text in (("name", " ".join(own_names)),
                                 ("label", class_clause(label)),
                                 ("intervention",
                                  " ".join(_own_interventions(conn, asset["id"],
                                                              own_names)))):
                for theme, evidence in classify(text).items():
                    found.setdefault(theme, (evidence, source))
            for theme, (evidence, source) in found.items():
                conn.execute(
                    "INSERT INTO asset_themes (asset_id, theme, evidence, source)"
                    " VALUES (?, ?, ?, ?)"
                    " ON CONFLICT(asset_id, theme) DO UPDATE SET"
                    "   evidence = excluded.evidence, source = excluded.source,"
                    "   derived_at = datetime('now')",
                    (asset["id"], theme, evidence, source))
                written += 1
        conn.commit()
    finally:
        conn.close()
    return {"tagged": written}


# --- what a company says it does, read from its own filing ---------------------------

# First person, then a modality within a short reach. This is the whole guard, and it
# is doing more work than it looks like.
#
# A risk factors section names every modality in the sector, because it is required to
# describe the competition: Beam's filing mentions CAR-T, CRISPR, gene therapy and cell
# therapy, and Rocket's mentions cell therapy it does not run. Counting terms would tag
# every company with everything, which is the comparator-arm leak again in a longer
# document.
#
# What separates a platform from a landscape is who the sentence is about. "Our
# proprietary base editing platform" is Beam; "competitors developing base editing
# therapies" is not. So the match must start at a first-person marker and reach the
# modality without leaving the sentence.
_SELF = re.compile(
    r"\b(?:we are|we have|we use|we develop|our)\b[^.;]{0,110}", re.I)

# Some phrases are first person and still describe someone else's work: a licence taken
# from another party, or a patent covering a rival's method. These sit in the same
# sentence shape and are refused.
_NOT_OURS = (
    "we own a patent", "we own two patent", "patent family", "license from",
    "licensed from", "our competitors", "our peers", "third part", "we compete",
    "competing", "other companies", "we may face",
)

# A company describing what its platform avoids uses the same words as one describing
# what it does. Atara's filing says its T-cell platform "does not require TCR or HLA
# gene editing", and reading that tagged Atara as a gene editing company on the strength
# of a sentence denying it. A negated window is dropped whole rather than parsed: a
# company that genuinely runs the platform states it positively somewhere else.
_NEGATED = (
    "does not require", "do not require", "does not use", "do not use", "without the",
    "without any", "rather than", "instead of", "avoids", "avoiding", "eliminates the",
    "no need for", "unlike", "does not involve", "do not involve", "free from",
    "as opposed to", "is not a", "are not a",
)

# How many self-describing windows to read per company. The annual report repeats its
# own platform sentence many times; the first few hundred carry it.
_SELF_WINDOWS = 400


def self_descriptions(text: str) -> list:
    """The first-person windows in a filing that could describe this company's platform."""
    found = []
    for match in _SELF.finditer(text or ""):
        window = re.sub(r"\s+", " ", match.group(0)).strip()
        low = window.lower()
        if any(phrase in low for phrase in _NOT_OURS + _NEGATED):
            continue
        found.append(window)
        if len(found) >= _SELF_WINDOWS:
            break
    return found


def derive_companies(db_path=None) -> dict:
    """Tag each company with the platforms its own filing says it runs.

    Reads the stored 10-K and 20-F sections rather than fetching, so this is cheap and
    repeatable. Rebuilt on each run, like the asset tags.
    """
    import db

    conn = db.get_connection(db_path)
    written = 0
    try:
        conn.execute("DELETE FROM company_themes")
        companies = conn.execute("SELECT id, ticker FROM companies").fetchall()
        for company in companies:
            rows = conn.execute(
                "SELECT accession, text FROM filing_sections"
                "  WHERE company_id = ? ORDER BY filed_date DESC LIMIT 6",
                (company["id"],)).fetchall()
            found: dict = {}
            for row in rows:
                for window in self_descriptions(row["text"]):
                    for theme, evidence in classify(window).items():
                        # The window, not the bare keyword, so a reader can see whose
                        # platform the sentence was describing.
                        found.setdefault(theme, (window[:240], row["accession"]))
            for theme, (evidence, accession) in found.items():
                conn.execute(
                    "INSERT INTO company_themes (company_id, theme, evidence, accession)"
                    " VALUES (?, ?, ?, ?)",
                    (company["id"], theme, evidence, accession))
                written += 1
        conn.commit()
    finally:
        conn.close()
    return {"tagged": written}
