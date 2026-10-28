"""Assets to indications, which CLAUDE.md calls the unit of analysis.

The table had never held a row, and the reason was vocabulary rather than data. 3,159 of
3,184 trials already carry both an asset and a condition list, but the sponsor's free text
gives 2,061 distinct strings for those 3,184 trials: "Non-Small Cell Lung Cancer" (50),
"Carcinoma, Non-Small-Cell Lung" (49) and "Non-small Cell Lung Cancer" (43) are one
indication scattered three ways, and "Healthy" (65), "Healthy Volunteers" (46) and
"Healthy Participants" (30) are Phase 1 studies with no indication at all.

ClinicalTrials.gov indexes every study against MeSH, so the descriptor is the identity:
D009223 takes "Myotonic Dystrophy Type 1 (DM1)" and "Myotonic Dystrophy" alike.

The trap is that the registry's ``meshes`` list is not the specific term. For NCT06926621
it runs to twelve entries ending in "Nervous System Diseases", while for NCT05027269 it
holds two and the broad ones sit in ``ancestors`` instead. Filing an asset under "Nervous
System Diseases" is filing it under nothing.

What decides specificity is the sponsor's own words: a descriptor counts only where it
overlaps what the company said it was studying. "Type 1 Diabetes" carries "Diabetes
Mellitus, Type 1" and carries nothing about the nervous system.

Refusing every descriptor that is somebody's parent somewhere in the corpus was tried and
is wrong, because the sector's biggest indications have subtypes and are therefore
parents. It lost obesity across 143 trials, systemic lupus across 53, breast cancer across
34 and rheumatoid arthritis across 26, all of them named by the sponsor in plain words.
The sponsor anchor alone leaks only a short tail of top-of-tree terms, and those are named
below rather than inferred, so the rule can be argued with.

Two rules decide what the table means:

- A trial condition is an intention, not a fact. Where a marketed asset has an approved
  indication on its label, that is the better record and it wins.
- The phase is the highest that asset has reached in that indication, across all of its
  studies. A company running Phase 1 and Phase 3 in the same disease is in Phase 3 there.
"""

from __future__ import annotations

import csv
import json
import pathlib
import re
import unicodedata

import db

# A study population rather than a disease.
_NOT_AN_INDICATION = re.compile(
    r"^(?:healthy|healthy volunteers?|healthy participants?|healthy subjects?|"
    r"normal volunteers?|none|not applicable|n/?a)$", re.I)

# Only words that carry no meaning are dropped. "Type" and the digits stay, because they
# are the whole difference between Type 1 and Type 2 diabetes.
_STOPWORDS = {"the", "of", "and", "in", "with", "for", "a", "to"}

# How much of the shorter phrase the two have to share. At a half, "Anemia, Sickle Cell"
# still answers to "Sickle Cell Disease" while "Nervous System Diseases" answers to
# nothing a sponsor wrote.
MATCH_THRESHOLD = 0.5

# Descriptors that are a branch of the tree and never a forecastable indication, even when
# a sponsor writes one as its condition. Matched exactly, so "Lymphoma, Non-Hodgkin" and
# "Lung Neoplasms" are unaffected while bare "Lymphoma" and "Lung Diseases" are not. Short
# and explicit on purpose: this is the one place the rule is a judgement rather than a
# derivation, and it should be readable as such.
TOO_BROAD = frozenset(x.lower() for x in (
    "Neoplasms", "Carcinoma", "Lymphoma", "Leukemia", "Syndrome", "Infections",
    "Nervous System Diseases", "Immune System Diseases", "Digestive System Diseases",
    "Lung Diseases", "Autoimmune Diseases", "Hematologic Diseases",
    "Musculoskeletal Diseases", "Genetic Diseases, Inborn", "Muscular Diseases",
    "Neuromuscular Diseases", "Neurodegenerative Diseases", "Metabolic Diseases",
    "Kidney Diseases", "Liver Diseases", "Heart Diseases", "Skin Diseases",
    "Endocrine System Diseases", "Respiratory Tract Diseases", "Inflammation",
    # Read off what the book had actually built. A marketed product's unapproved
    # indications are the list an expansion layer would be valued over, and 37 of them
    # stood against Lilly's marketed assets, of which these carried no product.
    #
    # Ancestors and pathology classes of a disease the asset is already in. Kisunla's
    # eleven indications were Alzheimer's disease and seven ways of restating it, so a
    # layer per row would have valued Alzheimer's eight times.
    "Brain Diseases", "Central Nervous System Diseases", "Neurocognitive Disorders",
    "Mental Disorders", "Tauopathies", "Synucleinopathies", "Plaque, Amyloid",
    # Oncology roll-ups that name no tumour. The specific sites stay: Verzenio keeps
    # non-small-cell lung, prostate, Ewing sarcoma and glioma and loses these two.
    "Neoplasm Metastasis", "Urogenital Neoplasms",
    # Not diseases. The registry indexes an obesity master protocol under the behaviour
    # and the metabolism it studies, so orforglipron arrived with Fasting, Behavior and
    # Feeding Behavior beside its real indications.
    "Fasting", "Behavior", "Feeding Behavior", "Weight Gain",
    "Glucose Metabolism Disorders", "Nutritional and Metabolic Diseases",
))

_PHASE_ORDER = ("Early Phase 1", "Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3",
                "Phase 3", "Phase 4")
_PHASE_RANK = {p: i for i, p in enumerate(_PHASE_ORDER)}

# A status that says the asset is no longer being developed in that indication. Kept
# rather than deleted: a programme that was dropped is a fact about the asset.
_STOPPED = {"Terminated", "Withdrawn", "Suspended"}


def is_indication(term: str) -> bool:
    """False for a study population, and for a branch of the tree."""
    text = (term or "").strip()
    return bool(text) and not _NOT_AN_INDICATION.match(text) \
        and text.lower() not in TOO_BROAD


# The sponsor writes English and MeSH writes its own register. "Metastatic Castration-
# Sensitive Prostate Cancer" is MeSH's "Prostatic Neoplasms", "Haemophilia A" is
# "Hemophilia A" and "Gastric Cancer" is "Stomach Neoplasms": the same disease with no word
# in common, so saruparib's, AAA817's, mevrometostat's and Mim8's Phase 3s were filed under
# nothing and their readouts sat outside the gate model (2026-10-10). Each word is mapped to
# MeSH's own before the overlap is measured. Short and explicit, like TOO_BROAD.
_SPELLING = {
    "haemophilia": "hemophilia", "leukaemia": "leukemia", "leukaemias": "leukemias",
    "anaemia": "anemia", "oesophageal": "esophageal", "oesophagus": "esophagus",
    "haematological": "hematologic", "haematologic": "hematologic", "oedema": "edema",
    "diarrhoea": "diarrhea", "haemorrhage": "hemorrhage", "paediatric": "pediatric",
    "oestrogen": "estrogen", "coeliac": "celiac", "tumour": "tumor", "tumours": "tumors",
}
_MESH_WORD = {
    "cancer": "neoplasms", "cancers": "neoplasms", "tumor": "neoplasms",
    "tumors": "neoplasms", "neoplasm": "neoplasms",
    "prostate": "prostatic", "gastric": "stomach", "colon": "colonic",
    "urothelial": "transitional",
}

# Words that name a kind of disease rather than which one. Once "cancer" reads as
# "neoplasms", every cancer shares that word with every MeSH neoplasm, and "Lung Cancer"
# would answer to "Bronchial Neoplasms" and "Neoplasms by Site" on it alone. A match has
# to share a word outside this set.
_GENERIC = {"neoplasm", "disease", "disorder", "syndrome", "infection", "carcinoma"}


def _stem(word: str) -> str:
    """A plural or a possessive read as its singular, on both sides alike: sponsors write
    "Crohns Disease" and "Sjogrens Syndrome" where MeSH has "Crohn Disease" and
    "Sjogren's Syndrome", and before the generic words stopped counting those matched
    on "disease" alone."""
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") \
        else word


def tokens(text: str) -> set:
    out = set()
    # "Sjögren's" is "Sjogren's": an accent would otherwise split the word in two.
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"['’]", "", text)
    for w in re.split(r"[^a-z0-9]+", text):
        if w and w not in _STOPWORDS:
            w = _SPELLING.get(w, w)
            out.add(_stem(_MESH_WORD.get(w, w)))
    return out


def _numbers(words: set) -> set:
    """The bare digits in a phrase, which are how a subtype is named."""
    return {w for w in words if w.isdigit()}


def containment(a: set, b: set) -> float:
    """Share of the shorter phrase the two have in common, subtypes permitting.

    Type 1 and type 2 diabetes share "diabetes" and "type", which is two words out of
    three and enough to match on overlap alone. They are different diseases with different
    drugs, so where both phrases number themselves and the numbers disagree, they are not
    the same indication whatever else they share. Where only one carries a number, it does
    not bite: "Myotonic Dystrophy Type 1" is still myotonic dystrophy.
    """
    if not a or not b:
        return 0.0
    na, nb = _numbers(a), _numbers(b)
    if na and nb and not (na & nb):
        return 0.0
    if not (a & b) - _GENERIC:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def parse_browse(raw) -> dict:
    """The stored mesh_terms column, tolerating null, bad JSON and the older list shape."""
    if not raw:
        return {"meshes": [], "ancestors": []}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {"meshes": [], "ancestors": []}
    if isinstance(data, list):                     # shape written before ancestors existed
        return {"meshes": data, "ancestors": []}
    if not isinstance(data, dict):
        return {"meshes": [], "ancestors": []}
    clean = lambda key: [t for t in (data.get(key) or [])
                         if isinstance(t, dict) and t.get("id") and t.get("term")]
    return {"meshes": clean("meshes"), "ancestors": clean("ancestors")}


# A sponsor names what a basket study leaves out in the same field it names what it
# takes in. DESTINY-PanTumor02 registers as "... Rare Tumors, Any Tumor Type Excluding
# Breast, Gastric, Colorectal Cancer", and matching on the whole string gave Enhertu a
# colorectal indication derived from the sentence that excludes colorectal. A phantom
# indication becomes a phantom gate, so the words after the marker are dropped before
# anything is matched against them.
#
# "non-" is deliberately not a marker here. It opens "non-small cell lung cancer", which
# is a disease rather than an exclusion, and treating it as one would silently empty the
# largest oncology indication in the book.
_EXCLUDES = re.compile(r"\b(?:excluding|except(?:\s+for)?|other\s+than|but\s+not)\b", re.I)


def before_exclusion(phrase: str) -> str:
    """The part of a condition string that says what a study is in, not what it is not."""
    return _EXCLUDES.split(phrase or "", maxsplit=1)[0]


def indications_for(conditions, browse) -> list[dict]:
    """The MeSH descriptors that are this study's actual indications.

    ``conditions`` is the sponsor's free text and ``browse`` the parsed mesh_terms column.
    """
    try:
        sponsor = json.loads(conditions) if isinstance(conditions, str) else (conditions or [])
    except (TypeError, ValueError):
        sponsor = []
    trimmed = [before_exclusion(s) for s in sponsor if isinstance(s, str)]
    said = [tokens(s) for s in trimmed if is_indication(s)]
    out = []
    for term in browse["meshes"]:
        if not is_indication(term["term"]):
            continue
        mesh = tokens(term["term"])
        if max((containment(mesh, s) for s in said), default=0.0) >= MATCH_THRESHOLD:
            out.append(term)
    return out


def phase_rank(phase: str | None) -> int:
    """Where a phase sits in the order of advance. Unknown phases sort lowest."""
    return _PHASE_RANK.get(phase or "", -1)


def higher_phase(a: str | None, b: str | None) -> str | None:
    """The further along of two phases."""
    return a if phase_rank(a) >= phase_rank(b) else b


def status_for(statuses) -> str:
    """One development status for a pair, from its studies.

    Active beats stopped: an asset with a terminated Phase 2 and a recruiting Phase 3 in
    the same disease is in development there, and reading the terminated study alone would
    retire a live programme.
    """
    live = [s for s in statuses if s and s not in _STOPPED]
    if live:
        for preferred in ("Recruiting", "Active not recruiting",
                          "Enrolling by invitation", "Not yet recruiting"):
            if preferred in live:
                return preferred
        return live[0]
    return next((s for s in statuses if s), None) or "Unknown"


# A rollover keeps patients on a drug; it does not study a disease.
#
# "A Long-term Extension Study of PCI-32765 (Ibrutinib)" enrols whoever finished one of
# the parent studies, so the registry lists every disease those studies covered. The
# book read NCT01804686 as the live Phase 3 behind Imbruvica in follicular lymphoma,
# diffuse large B-cell lymphoma and mantle-cell -- two of them published misses and the
# third an indication the FDA withdrew in 2023 -- because a rollover never finishes and
# never changes status. 109 of these are mapped to an asset and between them they assert
# 152 indication pairs.
#
# What a rollover must not contribute is a *pre-approval* phase. The registry files
# these under whatever the parent studies were, so Imbruvica's extension reads Phase 3
# and Active-not-recruiting for ever, and the book priced three decided indications --
# two published misses and one the FDA withdrew in 2023 -- as live Phase 3 gates.
#
# Phase 4 still counts, and the distinction is not a convenience. Phase 4 means a
# post-marketing study, which is exactly what a rollover on an approved drug is, and the
# book reads it as evidence the indication is already approved. Tafinlar's melanoma and
# non-small cell lung rows are asserted by Phase 4 rollovers alone and are its two
# approved indications; blanking them would turn two approved diseases into open
# expansions, which is the very mistake this is meant to stop.
#
# So the pair survives either way -- the drug genuinely has been given in that disease --
# and only a pre-approval claim about a programme is refused.
_ROLLOVER = re.compile(
    r"\b(?:roll[-\s]?over"
    r"|long[-\s]term\s+(?:extension|follow[-\s]?up)"
    r"|extension\s+study"
    r"|continued\s+(?:study\s+)?(?:treatment|access)"
    r"|continuation\s+(?:study|protocol)"
    r"|expanded\s+access)\b", re.I)


def is_rollover(title: str) -> bool:
    """Whether a study exists to continue treatment rather than to test an indication."""
    return bool(_ROLLOVER.search(title or ""))


def pairs_from_trials(rows) -> dict:
    """(asset_id, mesh_id) -> the pair's phase, statuses, enrolment and first sighting.

    One trial in three indications makes three pairs, which is the point: the unit of
    analysis is the pair, not the study.
    """
    out: dict = {}
    for row in rows:
        asset_id = row.get("asset_id")
        if not asset_id:
            continue
        browse = parse_browse(row.get("mesh_terms"))
        rollover = is_rollover(row.get("title"))
        for term in indications_for(row.get("conditions"), browse):
            entry = out.setdefault((asset_id, term["id"]), {
                "term": term["term"], "phase": None, "statuses": [],
                "enrollment": 0, "first_posted": None, "trials": 0,
                "real_trials": 0})
            entry["real_trials"] += 0 if rollover else 1
            if rollover and (row.get("phase") or "") != "Phase 4":
                # Enrolment and first sighting still count: those are facts about
                # patients. A pre-approval phase and a status are claims about a
                # programme, and a continuation protocol makes neither.
                entry["enrollment"] += row.get("enrollment") or 0
                posted = row.get("first_posted")
                if posted and (entry["first_posted"] is None
                               or posted < entry["first_posted"]):
                    entry["first_posted"] = posted
                entry["trials"] += 1
                continue
            entry["phase"] = higher_phase(entry["phase"], row.get("phase"))
            entry["statuses"].append(row.get("overall_status"))
            entry["enrollment"] += row.get("enrollment") or 0
            entry["trials"] += 1
            posted = row.get("first_posted")
            if posted and (entry["first_posted"] is None
                           or posted < entry["first_posted"]):
                entry["first_posted"] = posted
    return out


# Pairs no vocabulary can reach, named by hand with the reason. MK-8527's prevention
# studies are indexed only under "Acquired Immunodeficiency Syndrome", ABP 234's under no
# descriptor at all, and zibotentan/dapagliflozin's under "Kidney Diseases", which is
# TOO_BROAD. A row names the asset, the descriptor and the trials that make the pair; the
# phase, status and enrolment are read from those trials, never from the file, and a row
# whose trials are not mapped to that asset asserts nothing.
ADDITIONS_CSV = (pathlib.Path(__file__).resolve().parent.parent
                 / "data" / "asset_indication_additions.csv")

# The mirror of the additions file, for pairs the derivation asserts that are not true.
# One shape of error needs it: a master protocol giving different drugs to different
# diseases. The registry records interventions and conditions as two flat lists with
# nothing joining them, so a protocol testing drug A in disease X and drug B in disease
# Y reads as both drugs in both diseases, and no rule over the registry record can
# separate them. Amgen's NCT06570798 gives inebilizumab to lupus and blinatumomab to
# rheumatoid arthritis, and Uplizna acquired a rheumatoid arthritis programme it has
# never had.
EXCLUSIONS_CSV = (pathlib.Path(__file__).resolve().parent.parent
                  / "data" / "asset_indication_exclusions.csv")


def _curated_rows(conn, path):
    """(asset_id, row, studies) for each row of a curated pair file whose asset and
    trials are on file. ``studies`` are the named trials' (phase, status, enrolment,
    first posted), read from the registry rows, never from the file."""
    if not path.exists():
        return
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle if not line.startswith("#")):
            name = (row.get("asset") or "").strip()
            ncts = (row.get("nct_ids") or "").split()
            if not (name and (row.get("term") or "").strip() and ncts):
                continue
            asset = conn.execute(
                """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                    WHERE c.ticker = ? AND (LOWER(TRIM(a.generic_name)) = LOWER(?)
                       OR LOWER(TRIM(a.brand_name)) = LOWER(?)
                       OR LOWER(TRIM(a.internal_code)) = LOWER(?))""",
                ((row.get("ticker") or "").strip().upper(), name, name, name)).fetchone()
            if not asset:
                continue
            marks = ",".join("?" * len(ncts))
            studies = conn.execute(
                f"""SELECT phase, overall_status, enrollment, first_posted FROM trials
                     WHERE nct_id IN ({marks}) AND asset_id = ?
                    UNION ALL
                    SELECT phase, NULL, enrollment, NULL FROM completed_trials
                     WHERE nct_id IN ({marks}) AND asset_id = ?""",
                (*ncts, asset[0], *ncts, asset[0])).fetchall()
            if studies:
                yield asset[0], row, studies


def _fold(entry: dict, studies) -> dict:
    for phase, status, enrollment, posted in studies:
        entry["phase"] = higher_phase(entry["phase"], phase)
        entry["statuses"].append(status)
        entry["enrollment"] += enrollment or 0
        entry["trials"] += 1
        if posted and (entry["first_posted"] is None or posted < entry["first_posted"]):
            entry["first_posted"] = posted
    return entry


def _blank(term: str) -> dict:
    return {"term": term, "phase": None, "statuses": [], "enrollment": 0,
            "first_posted": None, "trials": 0}


def curated_additions(conn, path=None) -> dict:
    """(asset_id, mesh_id) -> pair entry, in pairs_from_trials' shape, for each row of
    ``data/asset_indication_additions.csv`` whose asset and trials are on file."""
    out: dict = {}
    for asset_id, row, studies in _curated_rows(conn, pathlib.Path(path or ADDITIONS_CSV)):
        mesh_id = (row.get("mesh_id") or "").strip()
        if not mesh_id:
            continue
        _fold(out.setdefault((asset_id, mesh_id), _blank(row["term"].strip())), studies)
    return out


# A paediatric row per asset and disease, for readouts in children. MeSH indexes a study
# of children with atopic dermatitis under "Dermatitis, Atopic", the descriptor the adult
# study gets, so without a row of its own the readout either decides the adults' approved
# indication or, as attach_catalyst_indications rules, links to nothing. MeSH defines a
# paediatric concept for a few diseases (Pediatric Crohn's disease, C536215), and a row
# naming one is an ordinary pair. For the rest the row is the asset's own, keyed by its
# name with no descriptor, because inventing an identifier MeSH does not have would put a
# false one in the column every other module reads as MeSH. A row also names the studies
# that read out in it, and a readout of one of them links to it whatever the registry
# indexed, which is the only way a study the registry never indexed can link at all.
PAEDIATRIC_CSV = (pathlib.Path(__file__).resolve().parent.parent
                  / "data" / "paediatric_indications.csv")


def curated_paediatric(conn, path=None) -> dict:
    """(asset_id, term) -> {"mesh_id", "nct_ids", "entry"} for each row of
    ``data/paediatric_indications.csv`` whose asset and trials are on file. ``entry`` is
    the pair in pairs_from_trials' shape; ``mesh_id`` is None where MeSH has no
    paediatric concept for the disease."""
    out: dict = {}
    for asset_id, row, studies in _curated_rows(conn, pathlib.Path(path or PAEDIATRIC_CSV)):
        term = row["term"].strip()
        item = out.setdefault((asset_id, term), {
            "mesh_id": (row.get("mesh_id") or "").strip() or None,
            "nct_ids": set(), "entry": _blank(term)})
        item["nct_ids"].update((row.get("nct_ids") or "").split())
        _fold(item["entry"], studies)
    return out


def curated_exclusions(conn, path=None) -> set:
    """{(asset_id, mesh_id)} for each row of ``data/asset_indication_exclusions.csv``
    whose asset and trials are on file.

    A row asserts nothing on its own: it removes a pair the trials would otherwise make,
    and only where those trials are the asset's. A row naming a study the asset is not
    mapped to is ignored, the same way an addition naming one is.
    """
    path = pathlib.Path(path or EXCLUSIONS_CSV)
    if not path.exists():
        return set()
    out = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle if not line.startswith("#")):
            name = (row.get("asset") or "").strip()
            mesh_id = (row.get("mesh_id") or "").strip()
            ncts = (row.get("nct_ids") or "").split()
            if not (name and mesh_id and ncts and (row.get("basis") or "").strip()):
                continue
            asset = conn.execute(
                """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                    WHERE c.ticker = ? AND (LOWER(TRIM(a.generic_name)) = LOWER(?)
                       OR LOWER(TRIM(a.brand_name)) = LOWER(?)
                       OR LOWER(TRIM(a.internal_code)) = LOWER(?))""",
                ((row.get("ticker") or "").strip().upper(), name, name, name)).fetchone()
            if not asset:
                continue
            marks = ",".join("?" * len(ncts))
            if conn.execute(f"SELECT 1 FROM trials WHERE nct_id IN ({marks})"
                            f"   AND asset_id = ?", (*ncts, asset[0])).fetchone():
                out.add((asset[0], mesh_id))
    return out


# The additions file read once per change of the file, since every gate view asks it
# about every study it reads.
_ADDITIONS_CACHE: dict = {}


def _addition_rows(path) -> list:
    stat = path.stat()
    stamp = (str(path), stat.st_mtime_ns, stat.st_size)
    if stamp not in _ADDITIONS_CACHE:
        with path.open(newline="", encoding="utf-8") as handle:
            _ADDITIONS_CACHE.clear()
            _ADDITIONS_CACHE[stamp] = list(csv.DictReader(
                line for line in handle if not line.startswith("#")))
    return _ADDITIONS_CACHE[stamp]


def curated_terms(conn, nct_id: str, path=None) -> list[dict]:
    """The descriptors ``data/asset_indication_additions.csv`` names for one study, each
    {"id", "term"}, where the study is mapped to the row's asset, by the rule
    curated_additions applies.

    The build writes the pair from these rows; a view that asks which indication a study
    is in has to read them too, or the pair stands and its studies do not. MK-8527's two
    Phase 3s made a Pre-Exposure Prophylaxis pair, and their readouts still read as
    matching no indication, so the gate that pair carries could never be priced."""
    path = pathlib.Path(path or ADDITIONS_CSV)
    if not nct_id or not path.exists():
        return []
    out: list = []
    for row in _addition_rows(path):
        name = (row.get("asset") or "").strip()
        mesh_id, term = (row.get("mesh_id") or "").strip(), (row.get("term") or "").strip()
        if not (name and mesh_id and term) or nct_id not in (row.get("nct_ids") or "").split():
            continue
        asset = conn.execute(
            """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                WHERE c.ticker = ? AND (LOWER(TRIM(a.generic_name)) = LOWER(?)
                   OR LOWER(TRIM(a.brand_name)) = LOWER(?)
                   OR LOWER(TRIM(a.internal_code)) = LOWER(?))""",
            ((row.get("ticker") or "").strip().upper(), name, name, name)).fetchone()
        if not asset:
            continue
        mapped = conn.execute(
            """SELECT 1 FROM trials WHERE nct_id = ? AND asset_id = ?
               UNION ALL
               SELECT 1 FROM completed_trials WHERE nct_id = ? AND asset_id = ?""",
            (nct_id, asset[0], nct_id, asset[0])).fetchone()
        if mapped and mesh_id not in {t["id"] for t in out}:
            out.append({"id": mesh_id, "term": term})
    return out


def _upsert_indications(conn, pairs) -> dict:
    """One indications row per MeSH descriptor. Returns mesh_id -> indication_id."""
    ids = {}
    for (_, mesh_id), entry in pairs.items():
        if mesh_id in ids:
            continue
        row = conn.execute("SELECT id FROM indications WHERE mesh_id = ?",
                           (mesh_id,)).fetchone()
        if row:
            ids[mesh_id] = row[0]
            continue
        ids[mesh_id] = conn.execute(
            "INSERT INTO indications (name, mesh_id) VALUES (?, ?)",
            (entry["term"], mesh_id)).lastrowid
    return ids


def _paediatric_indication(conn, term: str, mesh_id) -> int:
    """The indications row a paediatric pair points at: the MeSH concept's row where MeSH
    has one, otherwise the row of that name, created once."""
    if mesh_id:
        row = conn.execute("SELECT id FROM indications WHERE mesh_id = ?",
                           (mesh_id,)).fetchone()
        if row:
            return row[0]
    row = conn.execute("SELECT id FROM indications WHERE name = ?", (term,)).fetchone()
    if row:
        return row[0]
    return conn.execute("INSERT INTO indications (name, mesh_id) VALUES (?, ?)",
                        (term, mesh_id)).lastrowid


# A site or family term sitting beside one of its own children on the same asset is the
# same patient pool counted twice. MeSH indexes a non-small-cell lung study under both
# "Carcinoma, Non-Small-Cell Lung" and "Lung Neoplasms", and the layer model then prices
# a lung expansion for a drug whose lung expansion is already the row above. Twenty-eight
# marketed assets carried such a pair on 2026-10-26, twelve of them this one.
#
# Only parents that are never themselves an indication are listed. "Breast Neoplasms" is
# deliberately absent: an asset studied in triple-negative and in hormone-receptor
# positive disease carries both terms honestly, and suppressing the parent would delete
# the second indication rather than a duplicate. Which of those an asset really has is a
# question for the seed rows, not the vocabulary.
#
# Relational, not a TOO_BROAD entry: the parent is dropped only where that asset also
# carries the child. An asset with the parent alone keeps it.
PARENT_TERMS = {
    "lung neoplasms": ("carcinoma, non-small-cell lung", "small cell lung carcinoma",
                       "adenocarcinoma of lung"),
    "head and neck neoplasms": ("squamous cell carcinoma of head and neck",),
    "lymphoma, non-hodgkin": ("lymphoma, large b-cell, diffuse", "lymphoma, follicular",
                              "lymphoma, mantle-cell",
                              "leukemia, lymphocytic, chronic, b-cell"),
    "leukemia": ("precursor cell lymphoblastic leukemia-lymphoma",
                 "leukemia, myeloid, acute", "leukemia, lymphocytic, chronic, b-cell",
                 "leukemia, myelogenous, chronic, bcr-abl positive"),
}


def drop_parent_of_child(pairs: dict) -> int:
    """Remove a site or family term from an asset that also carries one of its children.

    Mutates ``pairs`` in place and returns how many it dropped, so a refresh can report
    the number rather than change the book silently.
    """
    terms: dict = {}
    for (asset_id, mesh_id), entry in pairs.items():
        terms.setdefault(asset_id, {})[(entry.get("term") or "").strip().lower()] = mesh_id
    dropped = 0
    for asset_id, by_term in terms.items():
        for parent, children in PARENT_TERMS.items():
            if parent not in by_term:
                continue
            if any(child in by_term for child in children):
                pairs.pop((asset_id, by_term[parent]), None)
                dropped += 1
    return dropped


def build(db_path=None) -> dict:
    """Derive asset_indications from the trials on file. Returns a count summary.

    Rebuilt wholesale rather than merged, because a pair with no trial behind it should
    stop being asserted. ``first_seen_phase`` survives the rebuild, so a phase advance
    stays visible to the diff engine.
    """
    conn = db.get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT asset_id, conditions, mesh_terms, phase, overall_status,
                      enrollment, first_posted
                 FROM trials WHERE asset_id IS NOT NULL
                UNION ALL
               SELECT asset_id, conditions, mesh_terms, phase, NULL, enrollment, NULL
                 FROM completed_trials WHERE asset_id IS NOT NULL""")]
        pairs = pairs_from_trials(rows)
        for key in curated_exclusions(conn):
            pairs.pop(key, None)
        for key, entry in curated_additions(conn).items():
            pairs.setdefault(key, entry)
        # Before the indications are written, so a parent the asset's own child makes
        # redundant never becomes a row the layer model can price.
        parents_dropped = drop_parent_of_child(pairs)
        indication_ids = _upsert_indications(conn, pairs)
        overrides = {(r["asset_id"], r["indication_id"]): dict(r) for r in
                     conn.execute("SELECT * FROM asset_indication_overrides")}
        seen = {(r["asset_id"], r["indication_id"]): r["first_seen_phase"]
                for r in conn.execute("SELECT asset_id, indication_id, first_seen_phase"
                                      " FROM asset_indications")}

        # The lead indication is the furthest advanced, ties going to the larger
        # enrolment, which is the nearest thing to a stated priority a registry holds.
        lead: dict = {}
        for (asset_id, mesh_id), entry in pairs.items():
            key = (phase_rank(entry["phase"]), entry["enrollment"])
            if asset_id not in lead or key > lead[asset_id][0]:
                lead[asset_id] = (key, mesh_id)

        # Anything pointing at a row about to be deleted has to let go of it first.
        # catalysts.asset_indication_id is the one such reference, written by
        # applications.resolve when a filing names the disease it is for. The rebuild is
        # wholesale, so the ids it points at do not survive it, and a foreign key error
        # here would break every refresh. The link is re-derived rather than remembered:
        # applications.resolve runs later in the same refresh and reattaches it against
        # the new rows.
        conn.execute("UPDATE catalysts SET asset_indication_id = NULL"
                     " WHERE asset_indication_id IS NOT NULL")
        conn.execute("DELETE FROM asset_indications")
        written = excluded = 0
        for (asset_id, mesh_id), entry in sorted(pairs.items()):
            indication_id = indication_ids[mesh_id]
            override = overrides.get((asset_id, indication_id)) or {}
            if override.get("exclude"):
                excluded += 1
                continue
            phase = override.get("phase") or entry["phase"]
            conn.execute(
                """INSERT INTO asset_indications
                       (asset_id, indication_id, phase, development_status, is_lead,
                        region, first_seen_phase, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'US', ?, datetime('now'))""",
                (asset_id, indication_id, phase, status_for(entry["statuses"]),
                 1 if lead.get(asset_id, (None, None))[1] == mesh_id else 0,
                 seen.get((asset_id, indication_id)) or phase))
            written += 1
        paediatric = 0
        for (asset_id, term), item in sorted(curated_paediatric(conn).items()):
            indication_id = _paediatric_indication(conn, term, item["mesh_id"])
            if conn.execute("SELECT 1 FROM asset_indications WHERE asset_id = ?"
                            " AND indication_id = ? AND region = 'US'",
                            (asset_id, indication_id)).fetchone():
                continue                    # the registry already made this pair
            override = overrides.get((asset_id, indication_id)) or {}
            if override.get("exclude"):
                excluded += 1
                continue
            entry = item["entry"]
            phase = override.get("phase") or entry["phase"]
            conn.execute(
                """INSERT INTO asset_indications
                       (asset_id, indication_id, phase, development_status, is_lead,
                        region, first_seen_phase, updated_at)
                   VALUES (?, ?, ?, ?, 0, 'US', ?, datetime('now'))""",
                (asset_id, indication_id, phase, status_for(entry["statuses"]),
                 seen.get((asset_id, indication_id)) or phase))
            written += 1
            paediatric += 1
        linked = attach_catalyst_indications(conn)
        conn.commit()
        return {"pairs": written, "indications": len(indication_ids),
                "paediatric_pairs": paediatric,
                "assets": len({a for a, _ in pairs}),
                "parents_dropped": parents_dropped,
                "excluded_by_override": excluded,
                "catalysts_linked": linked["linked"],
                "catalysts_ambiguous": linked["ambiguous"],
                "catalysts_paediatric_unmatched": linked["paediatric_unmatched"]}
    finally:
        conn.close()


_CTGOV_URL = "https://clinicaltrials.gov/study/"

# Words that make an indication row the paediatric one. ``tokens`` folds the British
# spelling into the American, so "Paediatric" and "Pediatric" both arrive as "pediatric".
_PAEDIATRIC_WORDS = frozenset(("pediatric", "paediatric", "child", "children",
                               "adolescent", "adolescents", "juvenile", "infant"))

# The registry gives no eligibility age on the rows this repository stores, so the title
# is the signal there is. It is explicit where it exists ("A Study of Mirikizumab in
# Pediatric Participants"), and a study whose title does not say so is read as adult,
# which is the common case and the safe default: an adult reading keeps today's
# behaviour, and only an explicit paediatric title diverts a readout.
_PAEDIATRIC_TITLE = re.compile(
    r"\b(pa?ediatrics?|child|children|adolescents?|juvenile|infants?)\b", re.I)

# A study that enrols both ages is not the paediatric one. "Remibrutinib in Adult and
# Adolescent Patients With Moderate to Severe Chronic Spontaneous Urticaria" is the
# adult label expansion, read out once across an age range that happens to reach down
# to twelve; so is upadacitinib's, icotrokinra's and eighteen others. Diverting them to
# a paediatric row the book mostly does not carry left 21 readouts unpriced, which is
# the opposite of what the paediatric rule is for: it exists to stop a readout in
# children being read as deciding the adults' approved indication, not to discard a
# readout that decides both.
_ADULT_TITLE = re.compile(r"\badults?\b", re.I)


# MeSH indexes a study under every descriptor that fits, so a trial in obesity arrives
# carrying "Obesity" and its own parent "Overweight", and one in hidradenitis
# suppurativa arrives carrying "Hidradenitis" as well. Both descriptors are real rows on
# the asset, so the readout matched two indications and was left unlinked as ambiguous:
# 153 catalysts, 38 of them the obesity pair alone, every one of them a readout whose
# disease is not actually in doubt.
#
# Where one of the matches is the MeSH parent of another, the narrower descriptor is the
# study's disease and the broader one is co-indexing. This is the same rule
# ``drop_parent_of_child`` applies to an asset's own indications, kept as a separate
# relation because it is wider: dropping these at asset level would retire rows that
# carry assumptions, and this only decides which row a readout points at.
#
# A judgement sits in the first entry and is worth stating. A trial enrolling "obesity
# or overweight" does cover both, and the book carries both rows; reading it as the
# obesity readout follows the label these products are written to ("chronic weight
# management in obesity, or overweight with a comorbidity") and takes the pool the
# programme is valued on. The alternative is 38 unpriced readouts on the largest
# franchise in the book.
_NARROWS_TO = {
    "overweight": ("obesity",),
    "hidradenitis": ("hidradenitis suppurativa",),
    "dermatitis": ("dermatitis, atopic", "eczema"),
    "eczema": ("dermatitis, atopic",),
    "alopecia": ("alopecia areata", "alopecia universalis"),
    "alopecia areata": ("alopecia universalis",),
    "scleroderma, systemic": ("scleroderma, diffuse",),
    "nephritis": ("lupus nephritis",),
    "macular degeneration": ("wet macular degeneration",),
    "retinal degeneration": ("macular degeneration", "wet macular degeneration"),
    **{parent: children for parent, children in PARENT_TERMS.items()},
}


def _narrow(names: dict) -> dict:
    """Drop every match that is the MeSH parent of another match on the same study.

    ``names`` maps the asset_indication id to its lowercased indication name. Returns
    the same mapping without the broader terms. A set that narrows to nothing, or to
    more than one unrelated disease, is returned unchanged for the caller to refuse.
    """
    present = {n: pid for pid, n in names.items()}
    drop = set()
    for parent, children in _NARROWS_TO.items():
        if parent in present and any(child in present for child in children):
            drop.add(present[parent])
    return {pid: n for pid, n in names.items() if pid not in drop} or names


def _by_condition_text(conditions, candidates: list) -> set:
    """The asset's own indications named whole inside the study's condition text.

    The registry indexes most studies into MeSH, and where it does that is the better
    signal because it is somebody's deliberate classification. But 143 readouts on the
    book carry conditions the registry never indexed — "Metastatic Castration-Resistant
    Prostate Cancer", "Relapsing Multiple Sclerosis", "Non-Clear Cell Renal Cell
    Carcinoma" — and they are not obscure. They are the free text a sponsor typed.

    So where MeSH yields nothing, the condition text is read against the asset's own
    indication names, which is the vocabulary the book already matched this study to
    when it built the asset_indications row. That keeps the module's rule intact: the
    catalyst and the forecast it prices against cannot disagree about what the study is
    in, because both now come from the same row.

    Two guards, because containment alone is too generous here. The book's name must be
    at least two meaningful words, since a one-word row like "Pain" sits inside any
    phrase mentioning it and would swallow every analgesic readout. And it must sit
    inside the condition whole rather than merely overlapping it, so "Prostatic
    Neoplasms" matches "Metastatic Castration-Resistant Prostate Cancer" and nothing
    matches on a shared qualifier like "metastatic".
    """
    try:
        conds = json.loads(conditions or "[]")
    except (TypeError, ValueError):
        return set()
    if not isinstance(conds, list):
        return set()
    out = set()
    for phrase in conds:
        said = set(tokens(phrase if isinstance(phrase, str) else ""))
        if len(said) < 2:
            continue
        for pair_id, words in candidates:
            if len(words) >= 2 and words <= said:
                out.add(pair_id)
    return out


def _is_paediatric(title) -> bool:
    text = title or ""
    if _ADULT_TITLE.search(text):
        return False
    return bool(_PAEDIATRIC_TITLE.search(text))


def attach_catalyst_indications(conn) -> dict:
    """Say which indication a registry readout reads out in.

    A readout is an event in one disease, not in the asset as a whole, and until the
    catalyst says which the model cannot price it as one: a label expansion on an
    approved drug is worth the indication it opens, and 794 of the 812 catalysts on the
    book named no indication at all. ``applications.resolve`` sets this where an FDA
    filing states the disease, which reached 18 of them; this reads the study.

    The rule is ``indications_for``, the same one asset_indications is built with, so a
    catalyst and the forecast it prices against cannot disagree about what the study is
    in. Run at the end of ``build`` because the wholesale rebuild above has just cleared
    the column and written the rows this matches against.

    A study in several of the asset's indications is left null. One readout then stands
    for two diseases, and choosing between them would be a guess about which the market
    is pricing; unlinked it stays unpriced and says so, which is the honest answer.
    """
    # indications_for answers in MeSH descriptors; asset_indications is keyed on the
    # indication row. The indications table carries the mesh_id that joins them.
    by_mesh = {r["mesh_id"]: r["id"] for r in conn.execute(
        "SELECT id, mesh_id FROM indications WHERE mesh_id IS NOT NULL")}
    pairs, paediatric, pair_name, by_asset = {}, {}, {}, {}
    for row in conn.execute(
            "SELECT ai.id, ai.asset_id, ai.indication_id, i.name FROM asset_indications ai"
            "  JOIN indications i ON i.id = ai.indication_id"):
        pairs[(row["asset_id"], row["indication_id"])] = row["id"]
        pair_name[row["id"]] = (row["name"] or "").strip().lower()
        by_asset.setdefault(row["asset_id"], []).append(
            (row["id"], set(tokens(row["name"] or ""))))
        words = set(tokens(row["name"] or ""))
        if words & _PAEDIATRIC_WORDS:
            paediatric.setdefault(row["asset_id"], []).append((row["id"], words))

    # A paediatric row names the studies that read out in it, and those link to it by
    # name, whatever MeSH indexed them under or whether it indexed them at all.
    named = {}
    for (asset_id, term), item in curated_paediatric(conn).items():
        found = conn.execute(
            "SELECT ai.id FROM asset_indications ai JOIN indications i"
            "    ON i.id = ai.indication_id"
            " WHERE ai.asset_id = ? AND (i.name = ? OR (i.mesh_id IS NOT NULL"
            "       AND i.mesh_id = ?))", (asset_id, term, item["mesh_id"])).fetchone()
        if found:
            for nct_id in item["nct_ids"]:
                named[(asset_id, nct_id)] = found[0]

    rows = conn.execute(
        f"""SELECT cat.id, cat.source_url, COALESCE(t.asset_id, cat.asset_id) AS asset_id,
                   t.nct_id, t.conditions, t.mesh_terms, t.title
              FROM catalysts cat
              JOIN trials t ON t.nct_id =
                   substr(cat.source_url, {len(_CTGOV_URL) + 1})
             WHERE cat.asset_indication_id IS NULL
               AND cat.source_url LIKE '{_CTGOV_URL}%'""").fetchall()

    linked = ambiguous = paediatric_unmatched = text_matched = 0
    for row in rows:
        if not row["asset_id"]:
            continue
        if (row["asset_id"], row["nct_id"]) in named:
            conn.execute("UPDATE catalysts SET asset_indication_id = ? WHERE id = ?",
                         (named[(row["asset_id"], row["nct_id"])], row["id"]))
            linked += 1
            continue
        try:
            terms = indications_for(row["conditions"], parse_browse(row["mesh_terms"]))
        except Exception:                                  # noqa: BLE001 - messy payload
            continue
        hits = {pairs[(row["asset_id"], by_mesh[t["id"]])] for t in terms
                if t["id"] in by_mesh and (row["asset_id"], by_mesh[t["id"]]) in pairs}

        # MeSH indexes a study of children with Crohn's disease as "Crohn Disease", the
        # same descriptor it gives the adult study, so the readout of Omvoh's paediatric
        # trial landed on the adult row. That row is an approved indication and the
        # adult approval is already in the revenue, so the one genuine gate the product
        # has was being read as decided. Where the asset carries a paediatric row for
        # the same disease the readout belongs to it.
        if _is_paediatric(row["title"]):
            wanted = {w for t in terms for w in tokens(t["term"] or "")}
            fits = [pid for pid, words in paediatric.get(row["asset_id"]) or []
                    if wanted and (words - _PAEDIATRIC_WORDS) <= wanted]
            if len(fits) != 1:
                # No paediatric row for this disease, or more than one. The adult row is
                # not the answer: a readout in children does not decide the indication
                # the adults are already approved in.
                paediatric_unmatched += 1
                continue
            hits = {fits[0]}

        if not hits and not _is_paediatric(row["title"]):
            hits = _by_condition_text(row["conditions"], by_asset.get(row["asset_id"]) or [])
            text_matched += 1 if len(hits) == 1 else 0
        if len(hits) > 1:
            hits = set(_narrow({pid: pair_name.get(pid, "") for pid in hits}))
        if len(hits) != 1:
            ambiguous += 1 if hits else 0
            continue
        conn.execute("UPDATE catalysts SET asset_indication_id = ? WHERE id = ?",
                     (hits.pop(), row["id"]))
        linked += 1
    return {"linked": linked, "ambiguous": ambiguous,
            "paediatric_unmatched": paediatric_unmatched,
            "text_matched": text_matched}
