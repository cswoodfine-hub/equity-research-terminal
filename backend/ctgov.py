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
