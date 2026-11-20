"""Discovery: what is read out of a research paper, and how it is scored.

Early research in cell and gene therapy, read each day from Europe PMC
(``fetchers/papers_europepmc.py``). This module holds the definitions every part of that
shares, so there is one of each: the rule flags, the areas and modalities a paper is filed
under, the model stages, the two scores and the lab heads they are matched to.

**The two scores read the title and abstract and nothing else.** Feasibility was trained
on whether a paper was cited by a clinical article within three years, commercial pull on
whether it was cited by work with a company author. Neither knows who wrote the paper.
They were fitted offline with scikit-learn (``work/discovery/tools/export_models.py``) and
are applied here with numpy alone, from the weights in ``discovery_models/``, so the app
needs no machine-learning library. A parity test holds the two implementations together.

A score is shown as a rank ("top 3%") against the year of papers the model file carries,
never as a probability. With no model file the scores are null and everything else works.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import pathlib
import re
import unicodedata

MODEL_PATH = pathlib.Path(__file__).resolve().parent / "discovery_models" / "paper_scores.json.gz"
LABS_SEED = pathlib.Path(__file__).resolve().parents[1] / "data" / "discovery" / "labs_seed.ndjson"

# What the title and abstract are searched for. The scores were trained with exactly these,
# so a change here needs the models exported again.
RULES = {
    "mouse": r"\bmice\b|\bmouse\b|\bmurine\b",
    "large_animal": r"\bpigs?\b|\bporcine\b|\bdogs?\b|\bcanine\b|\bsheep\b|\bovine\b",
    "primate": r"non-?human primate|\bnhps?\b|macaque|cynomolgus|rhesus",
    "human_cells": r"patient-derived|primary human|human ipsc|organoid|human donor",
    "patients": r"\bpatients\b|phase (i|1|ii|2)\b|clinical trial|first-in-human",
    "in_vivo": r"in vivo",
    "dose": r"vg/kg|vector genomes?|dose[- ]dependent|dose[- ]response|dose escalation",
    "biodistribution": r"biodistribution",
    "immunogenicity": r"neutrali[sz]ing antibod|immunogenic|pre-existing immunity",
    "off_target": r"off-target|guide-seq|genotoxic|insertional",
    "manufacturing": r"\bgmp\b|manufactur|scal(e|able) (up|production)|large-scale",
    "durability": r"long-term|durable|sustained expression|persisten",
    "safety": r"\btoxicit|\bsafety\b|well tolerated",
    "efficacy": r"\befficacy\b|therapeutic (effect|benefit)|rescue[ds]?\b|survival",
    "novel": r"\bnovel\b|first time|new class|engineered",
    "platform": r"\bplatform\b|versatile|broadly applicable|modular",
    "capsid": r"capsid|serotype|tropism",
    "delivery": r"deliver",
}
# The models a piece of work can have reached, earliest first.
STAGES = ["human_cells", "mouse", "large_animal", "primate", "patients"]
STAGE_NAMES = {"human_cells": "human cells", "mouse": "mice", "large_animal": "large animals",
               "primate": "primates", "patients": "patients"}
DERISK = ["dose", "biodistribution", "immunogenicity", "off_target", "manufacturing",
          "durability"]
FLAG_NAMES = {
    "patients": "tested in patients", "primate": "tested in primates",
    "large_animal": "tested in large animals", "mouse": "tested in mice",
    "human_cells": "human cells or tissue", "in_vivo": "in vivo data",
    "dose": "dose response shown", "biodistribution": "biodistribution shown",
    "immunogenicity": "immune reaction addressed", "off_target": "off-target effects checked",
    "manufacturing": "manufacturing addressed", "durability": "durability shown",
    "safety": "safety reported", "efficacy": "efficacy in a disease model",
    "novel": "presented as new", "platform": "presented as a platform",
    "capsid": "capsid work", "delivery": "delivery work", "preprint": "a preprint"}

MODALITIES = {
    "AAV": r"\baav\d*\b|adeno-associated", "Lentiviral": r"lentivir|retrovir",
    "CAR-T": r"car[- ]t\b|chimeric antigen|tcr[- ]t\b|car[- ]nk",
    "Cell therapy": r"cell therap|ipsc|pluripotent|mesenchymal|stem cell transplant|"
                    r"adoptive cell",
    "Gene editing": r"crispr|cas9|cas12|base edit|prime edit|genome edit|gene edit|"
                    r"talen\b|zinc[- ]finger",
    "LNP / mRNA": r"lipid nanoparticle|\blnps?\b|\bmrna\b"}

# Finer than the modalities. A paper can sit in several, and most sit in none, so an
# area's counts are of its own papers, never shares of a whole.
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
_AREAS = {name: re.compile(rule) for name, rule in AREAS.items()}

# A company among the authors' addresses, and what looks like one but is not.
COMPANY = re.compile(
    r"\b(inc|llc|ltd|gmbh|corp|corporation|s\.a\.|therapeutics|pharmaceuticals?|"
    r"biosciences?|biotherapeutics|biotech(nology|nologies)?|pharma|genomics)\b\.?", re.I)
NOT_COMPANY = re.compile(r"universit|hospital|institut|school|college|center|centre|"
                         r"academy|department of", re.I)

_JUNK = re.compile(r"<[^>]+>|&[a-z]+;")
_TOKEN = re.compile(r"(?u)\b\w\w+\b")
_NOT_A_REASON = {"sup", "sub", "lt", "gt", "amp", "italic", "study", "results", "using",
                 "used", "showed", "shown", "demonstrated", "demonstrate", "based", "data"}


def text_of(title, abstract) -> str:
    """The text every rule and both scores read."""
    return f"{title or ''}. {abstract or ''}"


def clean(text: str) -> str:
    """Lower case, with markup and entities blanked: what the scores' words are cut from."""
    return _JUNK.sub(" ", text.lower())


def flags(text: str) -> dict:
    return {name: int(bool(re.search(rule, text, re.I))) for name, rule in RULES.items()}


def areas(text: str) -> list:
    low = (text or "").lower()
    return [name for name, rule in _AREAS.items() if rule.search(low)]


def modalities(text: str) -> list:
    return [name for name, rule in MODALITIES.items() if re.search(rule, text, re.I)]


def furthest(found: dict):
    """The latest model stage among a paper's flags, or None for lab work only."""
    reached = [s for s in STAGES if found.get(s)]
    return reached[-1] if reached else None


def company_among(addresses) -> bool:
    return any(COMPANY.search(part) and not NOT_COMPANY.search(part)
               for address in addresses or [] for part in str(address).split(";"))


def _letters(text) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", text.lower())


def name_key(first, last):
    """"first|last" for matching a person by name, or None where the first name is only an
    initial: an initial and a surname is not enough to say who someone is."""
    first = _letters((first or "").split(" ")[0])
    last = _letters(last)
    return f"{first}|{last}" if len(first) >= 3 and len(last) >= 2 else None


def text_sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class Scorer:
    """The two paper scores, from the exported weights."""

    def __init__(self, model: dict):
        import numpy as np

        self._np = np
        self.version = model["version"]
        self.index = {term: i for i, term in enumerate(model["terms"])}
        self.terms = model["terms"]
        self.idf = np.array(model["idf"], dtype=np.float64)
        self.stop = set(model["stop"])
        self.flag_order = model["flags"]
        self.mean = np.array(model["mean"], dtype=np.float64)
        self.scale = np.array(model["scale"], dtype=np.float64)
        self.models = {
            name: {"text": np.array(m["text"], dtype=np.float64),
                   "flag": np.array(m["flag"], dtype=np.float64),
                   "intercept": float(m["intercept"]),
                   "quantiles": np.array(m["quantiles"], dtype=np.float64)}
            for name, m in model["models"].items()}

    def _weights(self, text: str) -> dict:
        """Column -> tf-idf weight for one text, as scikit-learn's TfidfVectorizer gives
        it with one- and two-word terms, stop words taken out first, sublinear term
        frequency and an l2 norm over the terms the vocabulary holds."""
        tokens = [t for t in _TOKEN.findall(clean(text)) if t not in self.stop]
        counts: dict = {}
        for term in tokens + [" ".join(pair) for pair in zip(tokens, tokens[1:])]:
            column = self.index.get(term)
            if column is not None:
                counts[column] = counts.get(column, 0) + 1
        weights = {c: (1.0 + math.log(n)) * self.idf[c] for c, n in counts.items()}
        norm = math.sqrt(sum(w * w for w in weights.values()))
        return {c: w / norm for c, w in weights.items()} if norm else {}

    def _flag_values(self, text: str, preprint: bool):
        found = dict(flags(text), preprint=int(bool(preprint)))
        raw = self._np.array([found[name] for name in self.flag_order], dtype=self._np.float64)
        return found, (raw - self.mean) / self.scale

    def score(self, title, abstract, preprint=False) -> dict:
        """{"feas", "comm"}: each {"score", "pct", "reasons"}. ``pct`` is the share of the
        reference year's papers this one outranks, so 0.97 reads as the top 3%."""
        np = self._np
        text = text_of(title, abstract)
        weights = self._weights(text)
        found, scaled = self._flag_values(text, preprint)
        out = {}
        for name, m in self.models.items():
            logit = (sum(w * m["text"][c] for c, w in weights.items())
                     + float(scaled @ m["flag"]) + m["intercept"])
            below = int(np.searchsorted(m["quantiles"], logit, side="right"))
            out[name] = {"score": float(logit), "pct": below / len(m["quantiles"]),
                         "reasons": self._reasons(m, weights, found)}
        return out

    def _reasons(self, m, weights, found, limit=4) -> dict:
        """What in this paper raised the score most: the flags it has, then its phrases."""
        raised = sorted(((float(m["flag"][i]), name) for i, name in enumerate(self.flag_order)
                         if found[name] and m["flag"][i] > 0.05), reverse=True)
        phrases = []
        for value, column in sorted(((w * m["text"][c], c) for c, w in weights.items()),
                                    reverse=True):
            term = self.terms[column]
            parts = term.split()
            if (value <= 0
                    or any(p in _NOT_A_REASON or len(p) < 3 or p.isdigit() for p in parts)
                    or any(term in kept or kept in term for kept in phrases)):
                continue
            phrases.append(term)
            if len(phrases) == limit:
                break
        return {"flags": [FLAG_NAMES[name] for _w, name in raised[:2]], "phrases": phrases}


_scorer: list = []


def scorer(path=None):
    """The scorer, read once; None where there is no model file to read."""
    if path is None and _scorer:
        return _scorer[0]
    source = pathlib.Path(path) if path else MODEL_PATH
    if not source.exists():
        return None
    with gzip.open(source, "rt", encoding="utf-8") as handle:
        made = Scorer(json.load(handle))
    if path is None:
        _scorer.append(made)
    return made


def top_share(pct):
    """0.97 -> "top 3%". Nothing is ever shown as better than the top 1%."""
    if pct is None:
        return None
    return f"top {max(1, math.ceil((1 - pct) * 100))}%"


def load_labs(conn, path=None) -> int:
    """Insert the ranked lab heads a seed file holds; a lab already there is left as it is.
    Returns how many were added."""
    source = pathlib.Path(path) if path else LABS_SEED
    if not source.exists():
        return 0
    added = 0
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            lab = json.loads(line)
            added += conn.execute(
                "INSERT OR IGNORE INTO discovery_labs (id, name, name_keys, institutions,"
                " country, rank, pct, ranked_as_of, modalities, papers, furthest_stage,"
                " company_coauthor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (lab["id"], lab["name"], json.dumps(lab["name_keys"]),
                 json.dumps(lab["institutions"]), lab.get("country"), lab["rank"],
                 lab["pct"], lab["ranked_as_of"], json.dumps(lab.get("modalities") or []),
                 lab.get("papers"), lab.get("furthest_stage"),
                 int(bool(lab.get("company_coauthor"))))).rowcount
    return added
