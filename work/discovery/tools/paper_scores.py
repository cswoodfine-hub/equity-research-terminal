"""Two scores for the paper itself, read from its title and abstract and nothing else.

- **Feasibility**: how likely the work is to be taken up in the clinic. Trained on
  whether a paper was cited by a clinical article within three years (NIH iCite).
- **Commercial pull**: how likely industry is to build on the concept. Trained on
  whether a paper was cited, within three calendar years, by a work with an author at a
  company (OpenAlex). It is about the idea, so it can be high for a lab with no company.

Papers about COVID-19 are left out of the commercial model. From 2020 to 2022 industry
cited almost any vaccine paper, and a model trained on them put every mRNA vaccine paper
at the top of the list (seen 2026-11-15), which says nothing about the idea in hand.

Neither sees the authors, their record, their institution or their declared interests:
those are the third score, the team's. The inputs are the words of the title and
abstract and the rule flags for the model the work reached and what it de-risked.

    python3 work/discovery/tools/paper_scores.py <data folder> [--json out]

prints the backtest: trained on 2017 and 2018, scored on 2019 and 2020.
"""

import json
import pathlib
import re
import sys

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

import backtest as B
import discovery as D  # noqa: E402  (backtest puts the backend on the path)

CONTENT = sorted(B.RULES) + ["preprint"]
INDUSTRY_CITATIONS = 2                 # this many company-authored citing works is "built on"
PANDEMIC = re.compile(r"covid|sars-cov|coronavirus|pandemic", re.I)
_clean = D.clean
FLAG_NAMES = D.FLAG_NAMES
_NOT_A_REASON = D._NOT_A_REASON


def industry(folder):
    """Paper id -> the years of the company-authored works that cite it."""
    path = pathlib.Path(folder) / "industry.ndjson"
    if not path.exists():
        return {}
    return {r["id"]: r["industry"] for r in map(json.loads, path.open())}


def label(rows, cited):
    """Give each row its ``industry`` outcome: None where it was not looked up, or where
    the paper is about COVID-19."""
    for row in rows:
        years = cited.get(row["id"])
        row["industry"] = (None if years is None or PANDEMIC.search(row["text"])
                           else len(years) >= INDUSTRY_CITATIONS)


class ContentModel:
    """Words and content flags against an outcome, with the reasons behind a score."""

    def __init__(self, rows, outcome):
        self.scaler = StandardScaler().fit(self._flags(rows))
        self.words = TfidfVectorizer(ngram_range=(1, 2), min_df=5, max_df=0.6,
                                     sublinear_tf=True, stop_words="english",
                                     max_features=200_000, preprocessor=_clean)
        text = self.words.fit_transform([r["text"] for r in rows])
        self.model = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000)
        self.model.fit(self._join(text, rows), np.array([int(r[outcome]) for r in rows]))
        self.terms = self.words.get_feature_names_out()

    @staticmethod
    def _flags(rows):
        return [[r["flags"][n] for n in CONTENT] for r in rows]

    def _join(self, text, rows):
        return sparse.hstack([text, sparse.csr_matrix(
            self.scaler.transform(self._flags(rows)))]).tocsr()

    def score(self, rows):
        return self.model.decision_function(
            self._join(self.words.transform([r["text"] for r in rows]), rows))

    def reasons(self, row, limit=4):
        """What in this paper raised its score most: flags it has, then phrases."""
        weights = self.model.coef_[0]
        text = self.words.transform([row["text"]])
        found = [(float(weights[len(self.terms) + i]), FLAG_NAMES[name])
                 for i, name in enumerate(CONTENT)
                 if row["flags"][name] and weights[len(self.terms) + i] > 0.05]
        flags = [name for _w, name in sorted(found, reverse=True)[:2]]
        gain = text.multiply(weights[:len(self.terms)]).tocoo()
        phrases = []
        for value, column in sorted(zip(gain.data, gain.col), reverse=True):
            term = self.terms[column]
            parts = term.split()
            if (value <= 0 or any(p in _NOT_A_REASON or len(p) < 3 or p.isdigit() for p in parts)
                    or any(term in kept or kept in term for kept in phrases)):
                continue
            phrases.append(term)
            if len(phrases) == limit:
                break
        return {"flags": flags, "phrases": phrases}


def _top(scores, labels, share):
    order = np.argsort(-scores, kind="stable")
    k = max(1, int(round(len(scores) * share)))
    hits = labels[order[:k]].sum()
    return hits / k, hits / max(1, labels.sum())


def backtest(rows, outcome, where=lambda r: True, baseline=None):
    """Train on 2017-18, score 2019-20: the same shape of result ``backtest.py`` writes."""
    rows = [r for r in rows if r[outcome] is not None and where(r)]
    train = [r for r in rows if r["year"] <= 2018]
    test = [r for r in rows if 2019 <= r["year"] <= 2020]
    y = np.array([int(r[outcome]) for r in test])
    scores = {"rules + words": ContentModel(train, outcome).score(test)}
    if baseline:
        scores[baseline[0]] = np.array([baseline[1](r) for r in test], float)
    result = {"n": len(test), "events": int(y.sum()), "base": float(y.mean()), "scores": {}}
    for name, s in scores.items():
        cells = [(share,) + _top(s, y, share) for share in (0.01, 0.05, 0.10)]
        result["scores"][name] = {"auc": float(roc_auc_score(y, s)), "top": [
            {"share": sh, "precision": float(p), "lift": float(p / y.mean()),
             "captured": float(c)} for sh, p, c in cells]}
        print(f"    {name:24} AUC {result['scores'][name]['auc']:.3f} | " + " | ".join(
            f"top {sh:.0%}: {p:.0%}, {p / y.mean():.1f}x" for sh, p, _c in cells), flush=True)
    print(f"    {len(test):,} scored, {int(y.sum())} events, base {y.mean():.1%}"
          f" (trained on {len(train):,})", flush=True)
    return result


STUDIES = [
    ("feasibility", "clinical", "paper feasibility: cited by a clinical article",
     lambda r: True),
    ("feasibility, early", "clinical", "the same, papers not yet in patients",
     lambda r: not r["is_clinical_paper"] and not r["flags"]["patients"]),
    ("commercial", "industry", "paper commercial pull: cited by industry", lambda r: True),
    ("commercial, academic", "industry", "the same, papers with no company author",
     lambda r: not r["flags"]["company_author"]),
    ("commercial, early academic", "industry",
     "the same, no company author and not yet in patients",
     lambda r: not r["flags"]["company_author"] and not r["is_clinical_paper"]
     and not r["flags"]["patients"]),
]


def run(rows):
    report = {}
    for key, outcome, name, where in STUDIES:
        print(f"\n{name}", flush=True)
        apt = ("iCite apt (baseline)", lambda r: r["apt"] if r["apt"] is not None else -1.0)
        report[name] = backtest(rows, outcome, where, apt if outcome == "clinical" else None)
    return report


def main(argv):
    data = B.load(argv[1])
    rows = [B.describe(p, data) for p in data["papers"]]
    label(rows, industry(argv[1]))
    looked = [r for r in rows if r["industry"] is not None]
    print(f"{len(looked):,} papers with an industry lookup; "
          f"{np.mean([r['industry'] for r in looked]):.1%} cited by industry "
          f"{INDUSTRY_CITATIONS} or more times within three years", flush=True)
    report = run(rows)
    if "--json" in argv:
        pathlib.Path(argv[argv.index("--json") + 1]).write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main(sys.argv)
