"""Probability of success for a big pharma Phase 2 or 3 asset, from where it actually is.

The rate the book used was a likelihood of approval read off one table by therapeutic
area and phase. It is honestly sourced and it is right for an asset that has just
entered its phase, and it is the same number for an asset whose pivotal trial read out
positive last month, which is wrong by a factor of two. Of 330 assets carrying a
probability of their own, 319 are marketed products at 1.0; the pipeline runs almost
entirely on that table.

This does three things the table cannot, and refuses a fourth.

It places the asset at its gate. The published likelihood is the product of the phase
transitions still ahead, and the trials table says which of them have already been
crossed: a Phase 3 with a positive readout on file has only the NDA/BLA-to-approval
transition left. The chain reproduces the table exactly for an asset at its phase's
entry, so nothing moves unless evidence moves it.

It shows a band, not a point pretending to be one. The same report cuts the same
transitions by modality, by oncology tumour type and by disease prevalence, and this
computes the chain under each cut the asset qualifies for and reports the spread. The
point estimate stays on the area cut, which is the best sampled and the one the model
has always used; the band is what the asset's other attributes say about it.

It carries the design of the pivotal trial, enrolment, allocation and masking, beside
the number, as facts a reader weighs. No free source publishes success rates by those,
so they are shown and never multiplied.

It does not infer a biomarker. The report's strongest cut is patient preselection
biomarkers, which roughly double the Phase 2 transition, and it identified them by
mapping trial-design records this repository does not hold. A title containing a gene
name is not that. The cut applies only where a person has recorded on the asset that
its pivotal trial selected patients on a biomarker, as a ``biomarker_selected`` row.

Big pharma only, and Phase 2 or 3 only, by construction: everywhere else the book
behaves as it did.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
import re

import engines
import fx
import productivity

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
TRANSITIONS = DATA_DIR / "pos_transitions.csv"

# The transitions ahead of an asset at each gate, in order. A stage names the gate the
# asset stands at now, which is the first transition it still has to make.
CHAIN = ("p1_to_p2", "p2_to_p3", "p3_to_nda", "nda_to_approval")
FROM_PHASE = {"Phase 2": "p2_to_p3", "Phase 2/3": "p2_to_p3", "Phase 3": "p3_to_nda"}

# A band cut is refused where the report's n for any transition it would use is below
# this. Figure 10b puts CAR-T's Phase 3 transition at 66.7% on three programmes and
# ADCs' NDA transition at 100% on twelve; a reader is better served by the area rate
# than by a decimal read off a handful. The area chain itself is never refused on n:
# it is the figure pos_by_area.csv already carries, n and all, and refusing Metabolic
# for its 48 approvals would move the book for no new evidence.
MIN_N = 50

# A Phase 3 that is still open when another has read out negative. The negative is
# one trial's answer and these are the others still asking.
OPEN_STATUSES = ("Recruiting", "Active not recruiting", "Not yet recruiting",
                 "Enrolling by invitation")

# The Orphan Drug Act line, which is also the report's own rare-disease criterion on
# page 13. Chronic high prevalence is its other pole, over one million US patients.
RARE_US_PREVALENCE = 200_000
CHRONIC_US_PREVALENCE = 1_000_000

# The report's area names for this model's, the same map pos_by_area.csv documents.
AREA_TO_REPORT = {
    "Oncology": "Oncology", "Immunology and inflammation": "Autoimmune",
    "Metabolic": "Metabolic", "Neuroscience": "Neurology", "Cardiovascular": "Cardiovascular",
    "Respiratory": "Respiratory", "Haematology": "Hematology", "Urology": "Urology",
    "Ophthalmology": "Ophthalmology", "Infectious disease": "Infectious disease",
    "Endocrine": "Endocrine", "Psychiatry": "Psychiatry", "Allergy": "Allergy",
    "Gastroenterology": "Gastroenterology",
}

# INN stems to the report's modality classes. The stem is the only thing a pipeline
# asset carries before it has a label, and a code number carries nothing, so an asset
# named MK-1045 gets no modality cut and the basis says so. A bispecific is folded
# into the antibody class because the report has no class for it, and that is stated.
_STEMS = (
    (re.compile(r"(vedotin|deruxtecan|tecan|adizutecan|samrotecan|tirumotecan|mafodotin|govitecan)$"),
     "ADCs", "an antibody-drug conjugate by its stem"),
    (re.compile(r"(tamig|amig|xizumab)$"), "Monoclonal antibody",
     "a bispecific antibody by its stem, folded into the report's antibody class"),
    (re.compile(r"(mab)$"), "Monoclonal antibody", "a monoclonal antibody by its stem"),
    (re.compile(r"(siran)$"), "siRNA/RNAi", "an siRNA by its stem"),
    (re.compile(r"(rsen|nersen)$"), "Antisense", "an antisense oligonucleotide by its stem"),
    (re.compile(r"(cept)$"), "Protein", "a fusion protein by its stem"),
    (re.compile(r"(tide|glutide|relin|pressin)$"), "Peptide", "a peptide by its stem"),
    (re.compile(r"autogene|(cel)$"), "Gene therapy", "a gene or cell therapy by its stem"),
    (re.compile(r"(nib|mib|ciclib|lisib|stat|sib|domide|rasib|kibart|parib|degib|"
                r"tinib|ostat|vir|prazole|sartan|gliptin|gliflozin|lutamide)$"),
     "Small molecule", "a small molecule by its stem"),
)

_HEME = re.compile(r"leuk|lymphom|myelom|myelodysplas|hematolog|haematolog|"
                   r"myelofibro|polycyth|thrombocyth", re.I)
_IO = re.compile(r"\bpd-?1\b|\bpd-?l1\b|ctla-?4|checkpoint|immuno-?oncolog|\btigit\b|"
                 r"\blag-?3\b", re.I)


def transitions(path=None) -> dict:
    """{(cut, group, transition): {pos, n, source}} from the published report."""
    source = pathlib.Path(path) if path else TRANSITIONS
    out: dict = {}
    if not source.exists():
        return out
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle
                                  if not line.lstrip().startswith("#")):
            try:
                out[(row["cut"], row["group"], row["transition"])] = {
                    "pos": float(row["pos"]), "n": int(row["n"] or 0),
                    "source": (row.get("source") or "").strip()}
            except (KeyError, TypeError, ValueError):
                continue
    return out


def modality_of(name: str | None, stored: str | None = None) -> tuple:
    """(report class, how it was read) from the assets row or an INN stem, or (None, why).

    The assets column holds only "small molecule" or "biologic" today. The first is the
    report's own class; the second spans six of them, so it decides nothing and the
    stem is read instead.
    """
    if (stored or "").strip().lower() == "small molecule":
        return "Small molecule", "a small molecule on the assets row"
    text = (name or "").strip().lower()
    if not text:
        return None, "no name on file"
    if re.match(r"^[a-z]{1,4}-?\d{3,}", text):
        return None, "a code number carries no stem"
    for pattern, group, how in _STEMS:
        if pattern.search(text):
            return group, how
    return None, "no recognised stem"


def stage_of(conn, asset_id: int, company_id: int, names: list, today=None) -> dict:
    """Where the asset stands, from the trials and readouts on file.

    A passed primary completion date with no readout is not evidence of success and
    does not advance the chain; it is reported, because a reader wants to know a
    readout is due. Only a readout does: positive from a Phase 3 moves the asset to the
    NDA/BLA gate, and negative puts it at nil, which is the convention the analyst's
    own hand-typed rows already follow.
    """
    today = (today or dt.date.today()).isoformat()
    p3 = [dict(r) for r in conn.execute(
        """SELECT nct_id, overall_status, primary_completion_date, enrollment, design,
                  title FROM trials
            WHERE asset_id = ? AND phase LIKE '%3%'
              AND COALESCE(overall_status, '') NOT IN ('Withdrawn')
            ORDER BY COALESCE(enrollment, 0) DESC""", (asset_id,))]
    pivotal = p3[0] if p3 else None
    passed = [t for t in p3 if (t["primary_completion_date"] or "9999") <= today]

    def norm(s):
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())
    mine = {norm(n) for n in names if n}
    readouts = []
    for r in conn.execute(
            "SELECT drug, phase, outcome, event_date, accession FROM trial_readouts"
            " WHERE company_id = ? ORDER BY event_date DESC", (company_id,)):
        drug = norm(r["drug"])
        if drug in mine or any(len(n) > 4 and n in drug for n in mine):
            readouts.append(dict(r))
    phase3_readouts = [r for r in readouts if str(r["phase"] or "") == "3"]

    def cite(r):
        return f"on {r['event_date']}" + (f" ({r['accession']})" if r.get("accession") else "")

    positive = next((r for r in phase3_readouts
                     if (r["outcome"] or "").lower() == "positive"), None)
    negative = next((r for r in phase3_readouts
                     if (r["outcome"] or "").lower() == "negative"), None)
    if positive:
        return {"stage": "positive", "gate": "nda_to_approval", "pivotal": pivotal,
                "evidence": f"Phase 3 read out positive {cite(positive)}"}
    if negative:
        # One trial's answer. Volrustomig's lung study was stopped for futility with
        # three other Phase 3 studies recruiting to 2030; the asset is not nil, the
        # remaining studies are at their gate and the downside is.
        remaining = [t for t in p3 if t["overall_status"] in OPEN_STATUSES
                     and (t["primary_completion_date"] or "9999") > negative["event_date"]]
        if remaining:
            return {"stage": "mixed", "gate": None, "pivotal": remaining[0],
                    "evidence": f"one Phase 3 read out negative {cite(negative)} with "
                                f"{len(remaining)} Phase 3 still listed open on the "
                                f"registry, the largest {remaining[0]['nct_id']} to "
                                f"{remaining[0]['primary_completion_date']}"}
        return {"stage": "negative", "gate": None, "pivotal": pivotal,
                "evidence": f"Phase 3 read out negative {cite(negative)} and no Phase 3 "
                            f"remains open"}
    if passed:
        t = passed[0]
        return {"stage": "reading_out", "gate": None, "pivotal": pivotal,
                "evidence": f"{t['nct_id']} passed primary completion "
                            f"{t['primary_completion_date']} with no readout on file"}
    return {"stage": "entering", "gate": None, "pivotal": pivotal,
            "evidence": (f"{pivotal['nct_id']} {(pivotal['overall_status'] or '').lower()}"
                         if pivotal else "no Phase 3 on the registry")}


def _chain(table: dict, cut: str, group: str, gates: tuple, min_n: int = MIN_N) -> tuple:
    """(product, [used rows], refused reason). Refuses a cut short of min_n anywhere."""
    product, used = 1.0, []
    for gate in gates:
        row = table.get((cut, group, gate))
        if row is None:
            return None, used, f"{cut} {group} has no {gate} rate"
        if row["n"] < min_n:
            return None, used, f"{cut} {group} rests on n={row['n']} at {gate}"
        product *= row["pos"]
        used.append((gate, row))
    return product, used, None


def resolve(conn, asset_id: int, *, area: str | None, phase: str | None,
            names: list, company_id: int, prevalence_us: float | None,
            biomarker_selected: bool, conditions_text: str = "",
            stored_modality: str | None = None, today=None, table=None) -> dict | None:
    """The probability, its band, and everything it rests on. None where not applicable.

    Applies only from Phase 2, Phase 2/3 or Phase 3, and only where the area chain can
    be computed. The point is the area chain from the asset's gate; the band is the
    same chain under every other cut the asset qualifies for and the report samples
    well enough to trust.
    """
    table = table if table is not None else transitions()
    first = FROM_PHASE.get(phase or "")
    if not first or not table:
        return None
    where = stage_of(conn, asset_id, company_id, names, today)
    if where["stage"] == "negative":
        return {"pos": 0.0, "low": 0.0, "high": 0.0, "stage": where["stage"],
                "evidence": where["evidence"], "chain": [], "cuts": [],
                "design": _design(where["pivotal"]),
                "basis": f"nil: {where['evidence']}"}
    start = where["gate"] or first
    gates = CHAIN[CHAIN.index(start):]

    report_area = AREA_TO_REPORT.get(area or "", None)
    point, used, why = _chain(table, "area", report_area or "All indications", gates, 0)
    label = report_area or "all indications"
    if point is None:
        point, used, why = _chain(table, "area", "All indications", gates, 0)
        label = "all indications"
        if point is None:
            return None

    # The other cuts the asset qualifies for. Each is the whole chain under that cut,
    # so the band is what the asset's attributes say and not an independence
    # assumption multiplied across them.
    cuts, refused = [], []
    modality, how = modality_of(names[0] if names else None, stored_modality)
    if modality:
        v, rows, reason = _chain(table, "modality", modality, gates)
        (cuts if v is not None else refused).append(
            {"cut": "modality", "group": modality, "pos": v, "how": how,
             "why": reason, "rows": rows})
    else:
        refused.append({"cut": "modality", "group": None, "pos": None, "how": how,
                        "why": how, "rows": []})
    if report_area == "Oncology":
        sub = ("Hematologic" if _HEME.search(conditions_text) else
               "IO" if _IO.search(conditions_text) else None)
        if sub:
            v, rows, reason = _chain(table, "oncology", sub, gates)
            (cuts if v is not None else refused).append(
                {"cut": "oncology", "group": sub, "pos": v, "why": reason, "rows": rows,
                 "how": "from the registry's conditions and titles"})
    elif prevalence_us is not None:
        # The report's chronic pole is the CMS chronic-conditions list. An infection, a
        # vaccine's at-risk population or a disease of no known area is not on it
        # however many people it counts.
        chronic_ok = (report_area not in (None, "Infectious disease")
                      and modality != "Vaccine")
        group = ("Rare" if prevalence_us < RARE_US_PREVALENCE else
                 "Chronic high prevalence"
                 if prevalence_us > CHRONIC_US_PREVALENCE and chronic_ok else None)
        if group:
            v, rows, reason = _chain(table, "prevalence", group, gates)
            (cuts if v is not None else refused).append(
                {"cut": "prevalence", "group": group, "pos": v, "why": reason,
                 "rows": rows, "how": f"US prevalence {prevalence_us:,.0f} on file"})
    if biomarker_selected:
        v, rows, reason = _chain(table, "biomarker", "Preselection biomarkers", gates)
        (cuts if v is not None else refused).append(
            {"cut": "biomarker", "group": "Preselection biomarkers", "pos": v,
             "why": reason, "rows": rows, "how": "recorded on the asset by hand"})

    spread = [point] + [c["pos"] for c in cuts]
    if where["stage"] == "mixed":
        spread.append(0.0)
    stage_note = {"positive": "at the NDA/BLA gate: ", "reading_out": "readout due: ",
                  "mixed": "one Phase 3 negative, the rest at their gate: ",
                  "entering": ("seamless Phase 2/3 read at the Phase 2 gate: "
                               if phase == "Phase 2/3" else "")}[where["stage"]]
    steps = " x ".join(f"{gate.replace('_', ' ')} {row['pos']:.1%} (n={row['n']})"
                       for gate, row in used)
    basis = (f"{stage_note}{steps} for {label}, BIO/Informa/QLS 2011-2020; "
             f"{where['evidence']}")
    if cuts:
        basis += "; band from " + ", ".join(f"{c['group']} {c['pos']:.0%}" for c in cuts)
    return {"pos": round(point, 4), "low": round(min(spread), 4),
            "high": round(max(spread), 4), "stage": where["stage"],
            "evidence": where["evidence"], "area": label,
            "chain": [{"gate": g, "pos": r["pos"], "n": r["n"], "source": r["source"]}
                      for g, r in used],
            "cuts": [{k: v for k, v in c.items() if k != "rows"} for c in cuts],
            "refused": [{k: v for k, v in c.items() if k != "rows"} for c in refused],
            "design": _design(where["pivotal"]), "basis": basis}


def _design(pivotal: dict | None) -> dict | None:
    """The pivotal trial's shape, as facts. Shown beside the number, never in it: no
    free source publishes success rates by enrolment or masking."""
    if not pivotal:
        return None
    parts = [p.strip() for p in (pivotal.get("design") or "").split(",")]
    return {"nct_id": pivotal.get("nct_id"), "enrollment": pivotal.get("enrollment"),
            "allocation": parts[0] if parts else None,
            "masking": parts[1] if len(parts) > 1 else None,
            "status": pivotal.get("overall_status"),
            "primary_completion": pivotal.get("primary_completion_date"),
            "title": pivotal.get("title")}


def big_pharma(conn, company_id: int) -> bool:
    """Whether the company is read on the pharma engine. The same rule as the universe
    split, so an asset is granular exactly where its owner is a pharma company."""
    row = conn.execute("PRAGMA database_list").fetchone()
    db_path = (row["file"] or None) if row is not None else None
    rates = fx.latest_usd_rates(db_path)
    revenue = productivity.latest_revenue(conn, company_id, rates)
    return engines.assign(conn, company_id, revenue) == engines.PHARMA


def for_asset(conn, asset_id: int, *, area: str | None, phase: str | None,
              scalars: dict | None = None, today=None) -> dict | None:
    """Everything resolve() needs, gathered from the asset's own rows. None where the
    asset is outside the gate: marketed, not Phase 2 or 3, or not big pharma's."""
    if phase not in FROM_PHASE:
        return None
    asset = conn.execute(
        "SELECT owner_company_id, generic_name, brand_name, internal_code, modality,"
        "       is_marketed FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if asset is None or asset["is_marketed"]:
        return None
    if not big_pharma(conn, asset["owner_company_id"]):
        return None
    names = [n for n in (asset["generic_name"], asset["brand_name"],
                         asset["internal_code"]) if n]
    # The lead indication's US prevalence, from the row the model already holds.
    prevalence = conn.execute(
        """SELECT a.value FROM assumptions a
             JOIN asset_indications ai ON ai.asset_id = a.asset_id
                                      AND ai.indication_id = a.indication_id
            WHERE a.asset_id = ? AND a.key = 'prevalence' AND a.region = 'US'
              AND a.scenario = 'base' AND a.year IS NULL AND a.value IS NOT NULL
              AND a.unit = 'patients' 
            ORDER BY ai.is_lead DESC, a.value DESC LIMIT 1""", (asset_id,)).fetchone()
    blob = conn.execute(
        "SELECT GROUP_CONCAT(COALESCE(conditions, '') || ' ' || COALESCE(title, ''), ' ')"
        "  FROM trials WHERE asset_id = ?", (asset_id,)).fetchone()[0] or ""
    return resolve(conn, asset_id, area=area, phase=phase, names=names,
                   company_id=asset["owner_company_id"],
                   prevalence_us=(prevalence["value"] if prevalence else None),
                   biomarker_selected=bool((scalars or {}).get("biomarker_selected")),
                   conditions_text=blob, stored_modality=asset["modality"], today=today)
