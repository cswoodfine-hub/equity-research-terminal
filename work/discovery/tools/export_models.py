"""Fit the two paper scores for the app, check them against the backtest, and write what
the daily job reads: the weights, a parity fixture and the ranked lab heads.

    python3 work/discovery/tools/export_models.py <data folder> [as-of date]

The data folder is the one ``live.py`` reads. Three files are written:

- ``backend/discovery_models/paper_scores.json.gz``: one vocabulary shared by both scores,
  its idf, the stop words, the flag order and scaling, each score's weights, and the
  scores of the last year's papers as a quantile table, which is what turns a score into
  "top 3%". The app applies it with numpy (``backend/discovery.py``).
- ``backend/tests/fixtures/discovery/parity.json``: a few texts with the scores
  scikit-learn itself gives them, so a test can hold the app's arithmetic to it.
- ``data/discovery/labs_seed.ndjson``: the lab heads active in the two years to the date,
  ranked by the backtest's lab model, with what the alerts compare a new paper against.
  No company record is written: those are matched by name and some are the wrong person.

Before writing anything it refits both scores on 2017-18 with the shared vocabulary and
scores 2019-20, and stops if either AUC has moved more than 0.005 from the backtest's.
"""

import collections
import datetime as dt
import gzip
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
import discovery as D
import live as L
import paper_scores as P

ROOT = pathlib.Path(__file__).resolve().parents[3]
MAX_TERMS = 60_000
DOCUMENTED = {"clinical": 0.841, "industry": 0.785}      # RESULTS_STEP1.md, 2026-11-15
TOLERANCE = 0.005
QUANTILES = 2001


def _vectorizer():
    return TfidfVectorizer(ngram_range=(1, 2), min_df=5, max_df=0.6, sublinear_tf=True,
                           stop_words="english", max_features=MAX_TERMS,
                           preprocessor=D.clean)


def _flags(rows):
    return [[r["flags"][n] for n in P.CONTENT] for r in rows]


class Shared:
    """One vocabulary and one flag scaling, with a weight vector per score."""

    def __init__(self, rows):
        self.words = _vectorizer().fit([r["text"] for r in rows])
        self.scaler = StandardScaler().fit(_flags(rows))
        self.heads = {}

    def matrix(self, rows):
        return sparse.hstack([self.words.transform([r["text"] for r in rows]),
                              sparse.csr_matrix(self.scaler.transform(_flags(rows)))]).tocsr()

    def fit(self, name, rows, outcome):
        model = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000)
        model.fit(self.matrix(rows), np.array([int(r[outcome]) for r in rows]))
        self.heads[name] = model

    def score(self, name, rows):
        return self.heads[name].decision_function(self.matrix(rows))


def check(rows):
    """The backtest again, on the shared vocabulary."""
    train = [r for r in rows if r["year"] <= 2018]
    shared = Shared(train)
    for name, outcome in (("feas", "clinical"), ("comm", "industry")):
        fit_on = [r for r in train if r[outcome] is not None]
        test = [r for r in rows if 2019 <= r["year"] <= 2020 and r[outcome] is not None]
        shared.fit(name, fit_on, outcome)
        auc = roc_auc_score([int(r[outcome]) for r in test], shared.score(name, test))
        print(f"  {outcome}: AUC {auc:.3f} on {len(test):,} papers "
              f"(documented {DOCUMENTED[outcome]:.3f})", flush=True)
        if abs(auc - DOCUMENTED[outcome]) > TOLERANCE:
            sys.exit(f"{outcome} moved more than {TOLERANCE} from the backtest; nothing written")


def _edge_cases():
    return [
        {"title": "A title with no abstract", "abstract": "", "preprint": False},
        {"title": "<i>OTOF</i> gene therapy &amp; hearing", "abstract":
         "An <sup>AAV</sup> vector was given to mice.<br/>Hearing was restored.",
         "preprint": False},
        {"title": "β-thalassaemia and γ-globin", "abstract":
         "Base editing of the γ-globin promoters in patient-derived cells raised fetal"
         " haemoglobin; the effect was durable in mice.", "preprint": False},
        {"title": "Zzzq xqv", "abstract": "Qqqz vvxk wwpl.", "preprint": False},
        {"title": "In vivo CAR-T generation with lipid nanoparticles", "abstract":
         "Lipid nanoparticles delivered mRNA to T cells in vivo in non-human primates at"
         " a dose-dependent level, with no toxicity.", "preprint": True},
    ]


def main(folder, today=None):
    today = dt.date.fromisoformat(today) if today else dt.date.today()
    data = B.load(folder)
    described = {p["id"]: B.describe(p, data) for p in data["papers"]}
    rows = list(described.values())
    P.label(rows, P.industry(folder))
    by_id = {p["id"]: p for p in data["papers"]}
    print(f"{len(rows):,} papers", flush=True)
    check(rows)

    shared = Shared([r for r in rows if r["year"] <= 2022])
    shared.fit("feas", [r for r in rows if r["year"] <= 2020 and r["clinical"] is not None],
               "clinical")
    shared.fit("comm", [r for r in rows if r["year"] <= 2022 and r["industry"] is not None],
               "industry")
    year = [r for r in rows
            if today - dt.timedelta(days=365) < by_id[r["id"]]["date"] <= today]
    terms = shared.words.get_feature_names_out().tolist()
    version = f"{today.isoformat()}-{len(terms)}"
    model = {"version": version, "as_of": today.isoformat(), "reference_papers": len(year),
             "terms": terms, "idf": shared.words.idf_.tolist(),
             "stop": sorted(shared.words.get_stop_words()), "flags": P.CONTENT,
             "mean": shared.scaler.mean_.tolist(), "scale": shared.scaler.scale_.tolist(),
             "models": {}}
    for name in ("feas", "comm"):
        head = shared.heads[name]
        weights = head.coef_[0]
        model["models"][name] = {
            "text": weights[:len(terms)].tolist(), "flag": weights[len(terms):].tolist(),
            "intercept": float(head.intercept_[0]),
            "quantiles": np.quantile(shared.score(name, year),
                                     np.linspace(0, 1, QUANTILES)).tolist()}
    out = ROOT / "backend" / "discovery_models" / "paper_scores.json.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(out, "wb", mtime=0) as raw:
        raw.write(json.dumps(model, separators=(",", ":")).encode("utf-8"))
    print(f"model {version}: {len(terms):,} terms, {out.stat().st_size / 1e6:.1f} MB", flush=True)

    # Texts with scikit-learn's own scores, for the parity test. Open-access journal
    # papers only: the fixture is committed, abstract and all.
    free = sorted((r for r in year if by_id[r["id"]].get("open_access") == "Y"
                   and by_id[r["id"]].get("source") == "MED"), key=lambda r: r["id"])
    picked = free[::max(1, len(free) // 20)][:20]
    cases = [{"title": by_id[r["id"]].get("title") or "",
              "abstract": by_id[r["id"]].get("abstract") or "",
              "preprint": by_id[r["id"]].get("source") == "PPR"} for r in picked] + _edge_cases()
    probe = [{"text": D.text_of(c["title"], c["abstract"]),
              "flags": dict(D.flags(D.text_of(c["title"], c["abstract"])),
                            preprint=int(c["preprint"]))} for c in cases]
    for name in ("feas", "comm"):
        for case, value in zip(cases, shared.score(name, probe)):
            case[name] = float(value)
    fixture = ROOT / "backend" / "tests" / "fixtures" / "discovery" / "parity.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps({"version": version, "cases": cases}, indent=1))

    # The lab heads, ranked as live.py ranks them.
    people = L.seniors(data)
    earlier = (L.cohort(data, described, people, dt.date(2020, 12, 31))
               + L.cohort(data, described, people, dt.date(2022, 12, 31)))
    now = L.cohort(data, described, people, today)
    share = L._share(L.Ranker(earlier, "lab").score(now))
    labs = []
    for row, place in zip(now, share):
        known = row["known"]
        seen = collections.Counter(
            (i.get("name"), i.get("country")) for t in known
            for i in (t[1].get("oa") or {}).get("institutions") or [] if i.get("name"))
        country = collections.Counter(c for (_n, c), k in seen.items() for _ in range(k) if c)
        papers = [described[t[0]["id"]] for t in known]
        stages = [D.STAGES.index(s) for p in papers for s in D.STAGES if p["flags"][s]]
        places = [n for (n, _c), _k in seen.most_common(5)]
        if not places:
            # No institution from OpenAlex: the one the newest printed address names.
            for entry in reversed(known):
                found = [D.institution_of(a) for a in B._author(entry[1])[1]]
                places = sorted({f for f in found if f})
                if places:
                    break
        labs.append({
            "id": row["id"],
            "name": (data["people"].get(row["id"]) or {}).get("name")
                    or L._person(known[-1][1]),
            "name_keys": sorted({k for k in (D.name_key(t[1].get("first"), t[1].get("last"))
                                             for t in known) if k}),
            "institutions": places,
            "country": country.most_common(1)[0][0] if country else None,
            "pct": float(place), "ranked_as_of": today.isoformat(),
            "modalities": [m for m, rule in D.MODALITIES.items()
                           if sum(bool(re.search(rule, p["text"], re.I)) for p in papers)
                           >= max(1, len(papers) / 3)],
            "papers": len(known),
            "furthest_stage": D.STAGES[max(stages)] if stages else None,
            "company_coauthor": any(p["flags"]["company_author"] for p in papers)})
    labs.sort(key=lambda lab: -lab["pct"])
    seed = ROOT / "data" / "discovery" / "labs_seed.ndjson"
    seed.parent.mkdir(parents=True, exist_ok=True)
    with seed.open("w", encoding="utf-8") as handle:
        for rank, lab in enumerate(labs, 1):
            handle.write(json.dumps({**lab, "rank": rank}, ensure_ascii=False,
                                    sort_keys=True) + "\n")
    named = sum(bool(lab["name_keys"]) for lab in labs)
    print(f"{len(labs):,} lab heads written, {named:,} with a name that can be matched; "
          f"{seed.stat().st_size / 1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:3])
