"""The areas a paper is filed under: keyword rules on the title and abstract, finer than
the six modalities. A paper can sit in several, and most sit in none (about seven in ten
on 2026-11-14), so an area's counts are of its own papers, never shares of a whole.
"""

import re

AREAS = {
    "In vivo CAR-T": r"in vivo (car\b|chimeric)|in vivo.{0,40}(generat|engineer|program|produc)\w*.{0,30}(car[- ]t|car t cells|chimeric antigen)|in situ.{0,30}car[- ]t",
    "Allogeneic cells": r"allogeneic|off-the-shelf|universal car",
    "NK cell therapy": r"car[- ]nk|natural killer",
    "TCR-T": r"tcr[- ]t\b|tcr-engineered|t cell receptor[- ](engineered|gene)",
    "TIL therapy": r"tumou?r[- ]infiltrating lymphocyte",
    "CAR-T, solid tumours": r"(car[- ]t|chimeric antigen).{0,200}solid tumou?r|solid tumou?r.{0,200}(car[- ]t|chimeric antigen)",
    "CAR-T, autoimmune": r"(car[- ]t|chimeric antigen).{0,200}(lupus|autoimmun|multiple sclerosis|myasthenia|systemic sclerosis)|(lupus|autoimmun).{0,200}(car[- ]t|chimeric antigen)",
    "Base editing": r"base edit",
    "Prime editing": r"prime edit",
    "Epigenetic editing": r"epigenom\w* edit|epigenetic edit|crispr(off|on)\b|crispr interference|crispra\b|crispri\b",
    "RNA editing": r"rna edit|\badar\b",
    "Large insertion": r"integrase|transposase|retrotranspos|gene writ|large (dna )?(insertion|cargo)",
    "Capsid engineering": r"capsid.{0,30}(engineer|evolution|librar|variant)|engineered capsid|novel capsid",
    "AAV, brain": r"(aav|adeno-associated).{0,200}(brain|\bcns\b|blood-brain|intrathecal|neurodegenerat)",
    "AAV, eye": r"(aav|adeno-associated|gene therapy).{0,200}(retina|subretinal|intravitreal|ocular)",
    "AAV, muscle": r"(aav|adeno-associated|gene therapy).{0,200}(duchenne|dystrophin|muscular dystrophy|skeletal muscle)",
    "LNP beyond liver": r"(lipid nanoparticle|\blnps?\b).{0,200}(extrahepatic|lung|spleen|t cells|bone marrow|brain|non-liver|hematopoietic)",
    "mRNA therapeutics": r"mrna.{0,40}(therap|deliver|vaccin|lipid)",
    "Virus-like particles": r"virus-like particle|\bvlps?\b|\bevlp",
    "iPSC-derived cells": r"\bipsc|induced pluripotent",
    "Blood stem cell gene therapy": r"hematopoietic stem.{0,120}(gene therap|lentivir|edit)|sickle cell|thalass",
    "Regulatory T cells": r"regulatory t cell|\btregs?\b",
    "Macrophage therapy": r"car[- ]m\b|car[- ]macrophage|engineered macrophage|macrophage.{0,30}cell therap",
    "Extracellular vesicles": r"extracellular vesicle|exosome",
    "Manufacturing": r"manufactur|bioprocess|\bgmp\b",
}
_RULES = {name: re.compile(rule) for name, rule in AREAS.items()}


def tag(text):
    """The areas a title and abstract fall under."""
    text = (text or "").lower()
    return [name for name, rule in _RULES.items() if rule.search(text)]
