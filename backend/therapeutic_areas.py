"""Group ClinicalTrials.gov condition strings into therapeutic areas.

The registry has 1,556 distinct condition strings across 2,578 trials, and the same
disease arrives spelled several ways: non-small cell lung cancer appears as "Carcinoma,
Non-Small-Cell Lung", "Non-Small Cell Lung Cancer", and "Non-small Cell Lung Cancer".
Raw conditions are therefore unusable as a browsing axis.

Matching is keyword based and deterministic, so the same trial always lands in the same
area and the rule that put it there can be read here. No model is involved, which keeps
this working with no key set. Anything unmatched stays in "Other" rather than being
forced into an area it does not belong to.

Order matters: the first area whose keywords match wins, so the more specific areas are
listed before the broader ones.
"""

from __future__ import annotations

import json

# Healthy volunteer studies are Phase 1 pharmacology, not a disease, and they are a
# real slice of the pipeline. They get their own bucket rather than polluting "Other".
AREAS: tuple = (
    ("Healthy volunteers", ("healthy",)),
    ("Oncology", (
        "cancer", "carcinoma", "tumor", "tumour", "neoplasm", "myeloma", "leukemia",
        "leukaemia", "lymphoma", "melanoma", "sarcoma", "glioma", "glioblastoma",
        "metasta", "oncolog", "malignan", "myelodysplastic", "mesothelioma",
        "adenocarcinoma", "blastoma",
    )),
    ("Immunology and inflammation", (
        "lupus", "arthritis", "psoria", "crohn", "colitis", "dermatitis",
        "eczema", "inflammatory bowel", "irritable bowel", "sjogren", "vasculitis", "urticaria",
        "hidradenitis", "scleroderma", "myasthenia", "immune thrombocytopenia",
        "graft versus host", "uveitis", "spondylitis", "vitiligo", "alopecia areata",
    )),
    ("Metabolic", (
        "obesity", "overweight", "diabet", "weight", "nash", "steatohepatitis",
        "dyslipidem", "hyperlipid", "cholesterol", "metabolic syndrome", "thyroid",
        "gout", "hyperkal", "insulin resistance", "triglycerid",
    )),
    ("Neuroscience", (
        "alzheimer", "parkinson", "multiple sclerosis", "epilep", "seizure",
        "migraine", "depress", "schizophren", "bipolar", "anxiety", "dementia",
        "huntington", "amyotrophic", "neuropath", "narcolep", "insomnia",
        "sleep-wake", "sleep disorder", "hypersomnia", "circadian",
        "myotonic", "muscular dystrophy", "spinal muscular", "pain",
    )),
    ("Cardiovascular", (
        "heart", "cardio", "cardiac", "hypertension", "atrial", "thrombo",
        "stroke", "atheroscler", "coronary", "myocardial", "aneurysm",
        "pulmonary arterial", "amyloidosis", "arterial", "ischemi",
    )),
    ("Infectious disease", (
        "hiv", "hepatitis", "influenza", "covid", "sars-cov", "rsv", "respiratory syncytial",
        "vaccin", "pneumococc", "bacterial", "tuberculosis", "malaria", "herpes",
        "cytomegalovirus", "clostridi", "fungal", "meningo", "dengue", "infection",
    )),
    ("Respiratory", (
        "asthma", "copd", "chronic obstructive", "pulmonary fibrosis", "bronchiect",
        "cystic fibrosis", "rhinitis", "sinusitis", "respiratory",
    )),
    ("Haematology", (
        "anemia", "anaemia", "haemophilia", "hemophilia", "sickle cell", "thalassem",
        "neutropenia", "polycythemia", "myelofibrosis", "von willebrand",
    )),
    ("Renal and hepatic", (
        "kidney", "renal", "nephro", "hepatic", "liver", "cirrhosis", "cholangitis",
    )),
    ("Ophthalmology", (
        "macular", "retinopath", "retinal", "glaucoma", "ophthalm", "dry eye",
        "geographic atrophy",
    )),
)

OTHER = "Other"


def classify(conditions) -> str:
    """The therapeutic area for one trial's condition list.

    Accepts the list, or the JSON string the trials table stores. A trial is placed by
    the first area matching any of its conditions, so a study listing both a cancer and
    a healthy cohort lands in Healthy volunteers only when nothing more specific hits.
    """
    if isinstance(conditions, str):
        try:
            conditions = json.loads(conditions or "[]")
        except (ValueError, TypeError):
            conditions = [conditions] if conditions else []
    blob = " ".join(str(c) for c in (conditions or [])).lower()
    if not blob.strip():
        return OTHER
    # Specific areas first, so an oncology trial in healthy volunteers reads as oncology.
    for area, needles in AREAS[1:]:
        if any(n in blob for n in needles):
            return area
    if any(n in blob for n in AREAS[0][1]):
        return AREAS[0][0]
    return OTHER


def area_names() -> list:
    return [name for name, _ in AREAS] + [OTHER]
