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
import re

# Healthy volunteer studies are Phase 1 pharmacology, not a disease, and they are a
# real slice of the pipeline. They get their own bucket rather than polluting "Other".
AREAS: tuple = (
    ("Healthy volunteers", ("healthy",)),
    ("Oncology", (
        "cancer", "carcinoma", "tumor", "tumour", "neoplasm", "myeloma", "leukemia",
        "leukaemia", "lymphoma", "melanoma", "sarcoma", "glioma", "glioblastoma",
        "metasta", "oncolog", "malignan", "myelodysplastic", "mesothelioma",
        "adenocarcinoma", "blastoma", "neurofibroma",
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
        "gout", "hyperkal", "insulin", "triglycerid", "osteoporosis",
        "growth hormone", "growth failure",
    )),
    ("Neuroscience", (
        "alzheimer", "parkinson", "multiple sclerosis", "epilep", "seizure",
        "migraine", "depress", "schizophren", "bipolar", "anxiety", "dementia",
        "attention-deficit", "attention deficit", "adhd",
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
    ("Urology", (
        "erectile dysfunction", "benign prostatic hyperplasia", "overactive bladder",
        "urinary incontinence", "nocturia", "urinary tract",
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


# A label's indications section names the primary use first and everything else after,
# including risks and secondary uses. Reading the whole section put Olumiant, a
# rheumatoid arthritis drug, in oncology on the strength of a malignancy warning.
_HEADER = re.compile(r"^\s*\d*\s*INDICATIONS AND USAGE\s*", re.I)
_SENTENCE = re.compile(r"(?<=[a-z])\.\s+")


def classify_label(indications: str) -> str:
    """The therapeutic area a marketed product sits in, read from its label.

    The first indication decides, because that is the product's primary use. Only when
    it names nothing this taxonomy knows does the rest of the section get a say, and a
    label that names nothing at all comes back Other rather than a guess.
    """
    if not indications:
        return OTHER
    body = _HEADER.sub("", indications)
    first = _SENTENCE.split(body)[0][:400]
    return _earliest(first) or _earliest(body[:1200]) or OTHER


def _earliest(text: str):
    """The area whose vocabulary appears first in the text, or None.

    A label lists the main indication first and the rest after, so position carries the
    answer where precedence does not: Cymbalta is indicated for major depressive
    disorder and, further down, for diabetic peripheral neuropathic pain. Taking the
    areas in their own order made it metabolic on the strength of the word diabetic.
    Ties keep the declared order, so a sentence naming two areas at once still resolves
    to the more specific one.
    """
    blob = (text or "").lower()
    if not blob.strip():
        return None
    best_area, best_at = None, len(blob) + 1
    for area, needles in AREAS[1:]:
        for needle in needles:
            at = blob.find(needle)
            if at != -1 and at < best_at:
                best_area, best_at = area, at
    return best_area


def area_names() -> list:
    return [name for name, _ in AREAS] + [OTHER]
