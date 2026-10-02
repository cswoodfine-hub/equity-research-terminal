"""What both ClinicalTrials.gov fetchers need to know about the registry.

Two fetchers ask this registry different questions: one for the active studies that are
the pipeline, one for the completed studies that are a product's record. They must agree
on which sponsor a company is and what a phase array means, and fetchers do not import
each other, so the shared knowledge lives here beside dailymed.py.

The sponsor terms matter more than they look. A company's legal name is not its lead
sponsor name in the registry: AstraZeneca PLC files as "AstraZeneca", Novartis AG as
"Novartis Pharmaceuticals", Merck & Co as "Merck Sharp & Dohme LLC". Querying the legal
name returns almost nothing, which is exactly what happened when the completed-studies
fetch was written against it and AstraZeneca came back with zero.
"""

from __future__ import annotations

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"

# CTGov lead-sponsor search term per ticker (verified against the live API).
SPONSOR_LEAD = {
    "LLY": "Eli Lilly and Company",
    "NVO": "Novo Nordisk A/S",
    "MRK": "Merck Sharp & Dohme LLC",
    "PFE": "Pfizer",
    "ABBV": "AbbVie",
    "JNJ": "Janssen Research & Development, LLC",
    "AZN": "AstraZeneca",
    "GSK": "GlaxoSmithKline",
    "NVS": "Novartis Pharmaceuticals",
    "ROG": "Hoffmann-La Roche",
    "SNY": "Sanofi",
    "BMY": "Bristol-Myers Squibb",
    "AMGN": "Amgen",
    "GILD": "Gilead Sciences",
    "VRTX": "Vertex Pharmaceuticals Incorporated",
    "REGN": "Regeneron Pharmaceuticals",
    "BIIB": "Biogen",
    "BAYN": "Bayer",
}

PHASE_MAP = {
    ("EARLY_PHASE1",): "Phase 1",
    ("PHASE1",): "Phase 1",
    ("PHASE1", "PHASE2"): "Phase 1/2",
    ("PHASE2",): "Phase 2",
    ("PHASE2", "PHASE3"): "Phase 2/3",
    ("PHASE3",): "Phase 3",
    ("PHASE4",): "Phase 4",
}
PHASES = ["Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Phase 4"]


def normalize_phase(phases) -> str | None:
    """Map a CTGov phases array to a heatmap column, or None for NA/observational."""
    if not phases:
        return None
    return PHASE_MAP.get(tuple(phases))


# The words a company's name carries to say what kind of company it is in law. They are
# dropped before two names are compared, so "Vertex Pharmaceuticals Inc" and "Vertex
# Pharmaceuticals Incorporated" read as one company. "Co" is not among them: without it
# "Merck & Co" would shrink to "Merck" and take Merck KGaA's studies as its own.
_LEGAL_WORDS = {
    "inc", "incorporated", "corp", "corporation", "plc", "ag", "se", "sa", "nv", "bv",
    "gmbh", "ltd", "limited", "llc", "lp", "holding", "holdings",
}


def _key(name) -> str:
    """A company name reduced for comparison: lowercase, punctuation to spaces, the
    trailing legal form dropped. "Novo Nordisk A/S" and "Novo Nordisk" give one key."""
    words = "".join(c if c.isalnum() else " " for c in (name or "").lower()).split()
    while words and (words[-1] in _LEGAL_WORDS
                     or (len(words) > 1 and words[-2:] == ["a", "s"])):
        words = words[:-2] if words[-2:] == ["a", "s"] else words[:-1]
    return " ".join(words)


def lead_names(lead, names) -> bool:
    """Whether the registry's lead sponsor is one of these companies.

    The lead sponsor is the registry's own answer to whose study it is, so it is the
    test, not the query that found the study. A name counts when it appears in the lead
    as whole words, which is how a subsidiary is still its parent's: "Wyeth is now a
    wholly owned subsidiary of Pfizer" and "Karuna Therapeutics, Inc., a Bristol Myers
    Squibb company" both name the parent. A lead the registry does not state names
    nobody.
    """
    lead_key = f" {_key(lead)} "
    if not lead_key.strip():
        return False
    return any(key and f" {key} " in lead_key for key in map(_key, names or ()))
